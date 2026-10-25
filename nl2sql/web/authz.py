"""HTTP yetkisi: oturum çerezi, seviyeler ve matrisin tek tablosu (PLAN R6-5).

Kapının kendisi ``require``: yol hangi seviyeyi istediğini söyler, geri kalanı burada durur.
``users`` hiç kurulmamışsa Run 5'in tek kullanıcısıdır - hiçbir seviye kimseyi çevirmez,
kullanıcı ``None``dır, yani eski davranışına hiçbir şey eklenmez.
"""

from __future__ import annotations

from fastapi import HTTPException, Request

from nl2sql import config

# Sözleşme "error body": Run 6'nın her reddi ``{"detail": str}``; cümleler ekranın gösterdikleri.
NO_SESSION = "Oturum açmanız gerekiyor."
NOT_ADMIN = "Bu işlem yalnız yöneticiye açık."
AUTH_OFF = "Kimlik doğrulama kapalı."

# Brief "Roles enforced on the server" matrisi: yol başına gereken seviye, FastAPI'ın şablon
# adlarıyla. Bir yol buradaysa kapı ondan haberdardır; yeni yol eklerken satırı da eklenir.
ROUTE_ROLES: dict[tuple[str, str], str] = {
    ("GET", "/"): "public",
    # Mount'ın yazıldığı ön ek: derlenmiş dosyalar oturum sormaz (brief "/assets/* public").
    ("GET", "/assets"): "public",
    ("POST", "/api/auth/login"): "public",
    ("POST", "/api/auth/logout"): "public",
    ("GET", "/api/auth/me"): "user",
    ("POST", "/api/ask"): "user",
    ("POST", "/api/replay/{audit_id}"): "user",
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
    ("GET", "/api/users"): "admin",
    ("POST", "/api/users"): "admin",
    ("PUT", "/api/users/{id}"): "admin",
    # ASSUMPTION: brief'in ``/api/schema-map/*``, ``/api/datasets*`` satırları henüz
    # ``create_app``te yol değil - satır, yolun doğduğu görevle birlikte buraya yazılır (R6-5).
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
    tanıyorum, işi değil. İkisinin gövdesi de sözleşme cümlesidir, ayrıntı sızdırmaz.
    """

    def dependency(request: Request) -> dict | None:
        if request.app.state.users is None:
            return None  # Run 5: kapı yok, yol kullanıcısız koşar.
        user = current_user(request)
        if user is None:
            raise HTTPException(status_code=401, detail=NO_SESSION)
        if level == "admin" and user["role"] != "admin":
            raise HTTPException(status_code=403, detail=NOT_ADMIN)
        return user

    return dependency
