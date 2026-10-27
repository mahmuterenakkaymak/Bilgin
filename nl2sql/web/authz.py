"""HTTP yetkisi: oturum çerezi, seviyeler ve matrisin tek tablosu (PLAN R6-5).

Kapının kendisi ``require``: yol hangi seviyeyi istediğini söyler, geri kalanı burada durur.
``users`` hiç kurulmamışsa Run 5'in tek kullanıcısıdır - hiçbir seviye kimseyi çevirmez,
kullanıcı ``None``dır, yani eski davranışına hiçbir şey eklenmez.
"""

from __future__ import annotations

from fastapi import HTTPException, Request

from nl2sql import config
from nl2sql.i18n import t
from nl2sql.web.lang import request_lang

# Sözleşme "error body": Run 6'nın her reddi ``{"detail": str}``. R8-5: kapının cümleleri kataloğundur
# ve reddeden yol onu isteğin diliyle okur; buradaki adlar başka modüllerin importıdır, o yüzden
# anahtarları değil program dilinin cümlesini taşırlar.
NO_SESSION = t("auth.no_session")
NOT_ADMIN = t("auth.not_admin")
AUTH_OFF = t("auth.off")

# Brief "Roles enforced on the server" matrisi: yol başına gereken seviye, FastAPI'ın şablon
# adlarıyla. Bir yol buradaysa kapı ondan haberdardır; yeni yol eklerken satırı da eklenir.
ROUTE_ROLES: dict[tuple[str, str], str] = {
    ("GET", "/"): "public",
    # Mount'ın yazıldığı ön ek: derlenmiş dosyalar oturum sormaz (brief "/assets/* public").
    ("GET", "/assets"): "public",
    ("POST", "/api/auth/login"): "public",
    ("POST", "/api/auth/logout"): "public",
    ("GET", "/api/auth/me"): "user",
    # R8-5: kişi kendi dil tercihini kendi yazar - yönetici değil, oturumun kendisi.
    ("PUT", "/api/auth/me"): "user",
    ("POST", "/api/ask"): "user",
    ("POST", "/api/replay/{audit_id}"): "user",
    # R7-8: konuşmanın üç yolu - seviye oturum, sahiplik yolda çözülür, başkasınınki 403 değil 404.
    ("GET", "/api/conversations"): "user",
    ("GET", "/api/conversations/{id}"): "user",
    ("DELETE", "/api/conversations/{id}"): "user",
    ("GET", "/api/health"): "user",
    ("GET", "/api/examples"): "user",
    ("GET", "/api/tables"): "user",
    ("GET", "/api/rules"): "user",
    ("GET", "/api/saved"): "user",
    ("POST", "/api/saved"): "user",
    ("DELETE", "/api/saved/{id}"): "user",
    ("GET", "/api/history"): "user",
    ("GET", "/api/export/{audit_id}.csv"): "user",
    ("GET", "/api/export/{audit_id}.xlsx"): "user",
    ("POST", "/api/rules"): "admin",
    ("PUT", "/api/rules/{rule_id}"): "admin",
    ("DELETE", "/api/rules/{rule_id}"): "admin",
    ("POST", "/api/index/rebuild"): "admin",
    # R6-18: etkin kümeyi değiştirmek sunucunun hangi veritabanına baktığını değiştirmektir.
    ("GET", "/api/datasets"): "admin",
    ("POST", "/api/datasets/active"): "admin",
    ("GET", "/api/datasets/{name}/login-script.sql"): "admin",
    # R6-16, R6-17: şemayı tanıtan ekran - biri sunucuya yeni bir veri kümesi ekliyor.
    ("GET", "/api/schema-map/info"): "admin",
    ("GET", "/api/schema-map/template.xlsx"): "admin",
    ("GET", "/api/schema-map/sample.xlsx"): "admin",
    ("POST", "/api/schema-map/preview"): "admin",
    ("POST", "/api/schema-map/apply"): "admin",
    ("GET", "/api/schema-map/status/{preview_id}"): "admin",
    ("GET", "/api/users"): "admin",
    ("POST", "/api/users"): "admin",
    ("PUT", "/api/users/{id}"): "admin",
    # R7-17, R7-18: başlangıç ekranının kartları ve kişinin kendi panosu herkesin; hazır soruların
    # deposu - listesi, onayı, değişikliği, silinmesi - yalnız yöneticinin.
    ("GET", "/api/start"): "user",
    ("POST", "/api/start/cards"): "user",
    ("POST", "/api/start/cards/{id}/open"): "user",
    ("POST", "/api/start/cards/{id}/refresh"): "user",
    ("DELETE", "/api/start/cards/{id}"): "user",
    ("GET", "/api/ready-questions"): "admin",
    ("POST", "/api/ready-questions"): "admin",
    ("PUT", "/api/ready-questions/{id}"): "admin",
    ("DELETE", "/api/ready-questions/{id}"): "admin",
    # R7-20: öneri işini başlatan da yoklayan da yönetici - aday satırlar onaylanmadan kimse görmez.
    ("POST", "/api/ready-questions/suggest"): "admin",
    ("GET", "/api/ready-questions/suggest/{job_id}"): "admin",
    # R7-22..R7-24: bağlantı yazmak, kümenin hangi veritabanına baktığını yazmaktır - sırrın
    # içeri girdiği tek yollar bunlardır, o yüzden dördü de yalnız yöneticiye açıktır.
    ("GET", "/api/connections"): "admin",
    ("GET", "/api/connections/{dataset}"): "admin",
    ("PUT", "/api/connections/{dataset}"): "admin",
    ("POST", "/api/connections/{dataset}/test"): "admin",
}


def current_user(request: Request) -> dict | None:
    """Çerezdeki oturumun kullanıcısı; oturum yoksa ya da kimlik doğrulama kapalıysa None."""
    users = request.app.state.users
    if users is None:
        return None
    return users.session_user(request.cookies.get(config.SESSION_COOKIE, ""))


def require(level: str):
    """Seviyesinden geçen bağımlılık: kullanıcının public sözlüğü, ya 401 ya 403 (R6-5).

    Oturum hiç yoksa 401 - tanımıyorum, reddetmiyorum. Rol yetmiyorsa 403: kullanıcıyı
    tanıyorum, işi değil. İkisinin gövdesi de sözleşme cümlesidir, ayrıntı sızdırmaz; R8-5'te
    cümle isteğin dilinden okunur - çeviride oturamayan kişi reddi de kendi dilinde görür.
    """

    def dependency(request: Request) -> dict | None:
        if request.app.state.users is None:
            return None  # Run 5: kapı yok, yol kullanıcısız koşar.
        user = current_user(request)
        if user is None:
            raise HTTPException(
                status_code=401, detail=t("auth.no_session", request_lang(request, None))
            )
        if level == "admin" and user["role"] != "admin":
            raise HTTPException(
                status_code=403, detail=t("auth.not_admin", request_lang(request, user))
            )
        return user

    return dependency
