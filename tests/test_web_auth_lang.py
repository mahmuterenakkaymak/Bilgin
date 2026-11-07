# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""T405: kimlik ve küçük API modüllerinin red cümleleri isteğin dilinde (PLAN R8-5).

Dünya test_web_auth ile aynı - kopya, import değil: kurulmuş mini küme, sahte model, tmp günlükler -
bir de iki kimlik: yöneticinin kendi üstündeki reddi ve oturumsuzun 401'i ancak böyle ölçülür. Dil
tek bir başlıkla seçilir, ``Accept-Language``, yani aynı dünyanın kapısı iki dilde de okunur. tr
tarafı bugün ekranda okunan cümleye sabittir: katalog bir gün bozulursa buradan anlaşılır.
"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from bilgin import config
from bilgin.app.session import open_session
from bilgin.auth import store as store_module
from bilgin.auth.store import UserStore
from bilgin.cli import main as cli
from bilgin.i18n import t
from bilgin.i18n.scan import user_literals
from bilgin.web import auth_api as auth_api_module
from bilgin.web import authz as authz_module
from bilgin.web import conversations_api as conversations_module
from bilgin.web import saved as saved_module
from bilgin.web.app import create_app

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "datasets"

PAROLA = "Bilgin2026!erp"
YANLIS = "YanlisParola2026!"
ADMIN, USER, LOCKED = "eren", "ayse", "kilitli"

# 2026-10-27'de ekranda okunan cümleler: Türkçe yolun kataloğa taşınırken değişmediğinin ölçütü.
TODAY = {
    "auth.login_failed": "Kullanıcı adı ya da parola hatalı.",
    "auth.locked": "Çok fazla hatalı deneme. {minutes} dakika sonra yeniden deneyin.",
    "auth.no_session": "Oturum açmanız gerekiyor.",
    "auth.not_admin": "Bu işlem yalnız yöneticiye açık.",
    "auth.password_short": "Parola en az {n} karakter olmalı.",
    "auth.last_admin": "Son etkin yönetici pasifleştirilemez ya da rolü düşürülemez.",
    "auth.own_business_role": "Kendi iş rolünüzü değiştiremezsiniz.",
    "conversations.not_found": "Konuşma bulunamadı.",
    "app.no_saved": "Kayıtlı soru bulunamadı.",
}

REJECTIONS = (
    "login_failed",
    "locked",
    "no_session",
    "not_admin",
    "password_short",
    "last_admin",
    "own_business_role",
    "conversation_missing",
    "saved_missing",
)


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "ROOT", tmp_path)
    monkeypatch.setenv("BILGIN_DATASETS_DIR", str(FIXTURE_ROOT))
    cli.build_database(dataset="mini")
    return tmp_path


@pytest.fixture
def session(project, capsys):
    """Altın kaydı olan küme ve sahte model: kayıtların kümesi oturumdan okunuyor."""
    capsys.readouterr()
    return open_session(
        dataset="mini",
        llm="fake",
        audit_path=project / "audit.jsonl",
        ask_log=project / "asks.jsonl",
    )


@pytest.fixture
def users(project):
    """İki kimlik: biri yönetici, biri değil - 403ün iki yüzü de ancak böyle ölçülür."""
    store = UserStore(project / "bilgin.db")
    store.add_user(ADMIN, PAROLA, "admin")
    store.add_user(USER, PAROLA, "user")
    return store


@pytest.fixture
def app(session, project, users):
    return create_app(
        session, saved_path=project / "bilgin.db", static_dir=project / "static", users=users
    )


def client(app, lang: str, username: str | None = None) -> TestClient:
    """Başlığı sabitlenmiş istemci; ``username`` verilmişse o kimliğin çereziyle açılır."""
    made = TestClient(app)
    made.headers["accept-language"] = lang
    if username:
        granted = made.post("/api/auth/login", json={"username": username, "password": PAROLA})
        assert granted.status_code == 200, f"{username} giriş yapamadı: {granted.status_code}"
    return made


def expected(key: str, lang: str, **params) -> str:
    """Türkçe bugün okunan cümle, İngilizce kataloğun kendi satırı (R8-5)."""
    return TODAY[key].format(**params) if lang == "tr" else t(key, lang, **params)


def reject(name: str, lang: str, app, users) -> tuple[str, dict, int, object]:
    """Adı geçen redi koşar: (kataloğun anahtarı, parametreleri, HTTP durumu, gelen cevap)."""
    if name == "login_failed":
        return "auth.login_failed", {}, 401, client(app, lang).post(
            "/api/auth/login", json={"username": USER, "password": YANLIS}
        )
    if name == "locked":
        made = client(app, lang)
        for _ in range(config.LOGIN_MAX_FAILURES):
            made.post("/api/auth/login", json={"username": LOCKED, "password": YANLIS})
        return "auth.locked", {"minutes": config.LOCKOUT_MIN}, 429, made.post(
            "/api/auth/login", json={"username": LOCKED, "password": PAROLA}
        )
    if name == "no_session":
        return "auth.no_session", {}, 401, client(app, lang).get("/api/auth/me")
    if name == "not_admin":
        return "auth.not_admin", {}, 403, client(app, lang, USER).get("/api/users")
    if name == "password_short":
        return (
            "auth.password_short",
            {"n": config.PASSWORD_MIN_LEN},
            422,
            client(app, lang, ADMIN).post(
                "/api/users", json={"username": "kisa.ad", "password": "Kisa1!"}
            ),
        )
    if name == "last_admin":
        return "auth.last_admin", {}, 409, client(app, lang, ADMIN).put(
            f"/api/users/{users.get_user(ADMIN)['id']}", json={"active": False}
        )
    if name == "own_business_role":
        return "auth.own_business_role", {}, 403, client(app, lang, ADMIN).put(
            f"/api/users/{users.get_user(ADMIN)['id']}", json={"business_role": "satis"}
        )
    if name == "conversation_missing":
        return (
            "conversations.not_found",
            {},
            404,
            client(app, lang, ADMIN).get(f"/api/conversations/{'0' * 32}"),
        )
    return "app.no_saved", {}, 404, client(app, lang, ADMIN).delete("/api/saved/42")


@pytest.mark.parametrize("lang", ["tr", "en"])
@pytest.mark.parametrize("name", REJECTIONS)
def test_a_rejection_reads_the_request_language(name, lang, app, users):
    key, params, status, response = reject(name, lang, app, users)

    assert response.status_code == status
    assert response.json() == {"detail": expected(key, lang, **params)}


def test_the_request_language_beats_the_browser_header_of_a_user_who_chose_one(app, users):
    """Tercihini yazan kişi başlığı Türkçe kalsa da İngilizce reddedilir (R8-5 çözülme sırası)."""
    made = client(app, "tr", ADMIN)
    assert made.put("/api/auth/me", json={"lang": "en"}).status_code == 200

    refused = made.delete("/api/conversations/00000000000000000000000000000000")

    assert refused.status_code == 404
    assert refused.json() == {"detail": t("conversations.not_found", "en")}


def test_no_turkish_literal_is_left_in_the_five_modules():
    for module in (
        store_module,
        auth_api_module,
        authz_module,
        saved_module,
        conversations_module,
    ):
        assert user_literals(Path(module.__file__)) == []
