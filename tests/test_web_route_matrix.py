# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""T237: kapının seviyesi matristen okunur (PLAN R6-5).

Dünya ``tests/test_web_rules.py`` ile aynı - kopya, import değil: tmp'ye kopyalanmış mini küme,
sahte model, tmp yollar, yani kural yazımları asıl fixture'ın kuralına dokunmaz. Yollar elle
yazılmaz: ``app.routes`` yürünür, matrisle karşılaştırılır ve her yol üç kimlikle bir kez koşulur
- oturumsuz, kullanıcı, yönetici.
"""

import re
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from nl2sql import config
from nl2sql.app.session import open_session
from nl2sql.auth.store import UserStore
from nl2sql.cli import main as cli
from nl2sql.web.app import create_app
from nl2sql.web.authz import NOT_ADMIN, NO_SESSION, ROUTE_ROLES

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "datasets"
PAROLA = "Bilgin2026!erp"
ADMIN, USER = "yonetici", "kullanici"

# Zararsız çağrının gövdesi: doğrulamayı geçsin ki kapı doğrulamadan önce konuşsun, ama iş de
# yapmasın - boş soru 400, boş kural 422, olmayan kimlik 404; hiçbiri kapının kendisi değil.
BODIES = {
    "/api/ask": {"question": " "},
    "/api/saved": {"question": " "},
    "/api/rules": {},
    "/api/rules/{rule_id}": {},
    "/api/auth/login": {"username": ADMIN, "password": PAROLA},
}

# Her yol her kimlikle bir kez: (yöntem, yol, matristeki seviye, kimlik).
CASES = [
    (method, path, level, who)
    for (method, path), level in sorted(ROUTE_ROLES.items())
    for who in ("anonim", "user", "admin")
]


def login(client, username) -> None:
    response = client.post("/api/auth/login", json={"username": username, "password": PAROLA})
    assert response.status_code == 200, f"{username} giriş yapamadı: {response.status_code}"


def url(path: str) -> str:
    """Yol parametreleri zararsız değerlerle dolar: ``{id}`` -> ``1``, yani olmayan kayıt."""
    return re.sub(r"\{[^}]+\}", "1", path)


def walk(routes, prefix: str = ""):
    """``app.routes`` yürüyüşü: (yöntem, yol).

    ``include_router`` yolları ağacın içine koyar, o yüzden gömülü olan da açılır; Mount'ın yolu
    önektir ama yöntemi yoktur, yani kapı değil - ``/assets``ın publicliği ayrı ölçülür.
    """
    for route in routes:
        inner = getattr(route, "routes", None) or getattr(
            getattr(route, "original_router", None), "routes", None
        )
        if inner:
            yield from walk(inner, prefix + getattr(route, "path", "") or "")
        else:
            for method in getattr(route, "methods", None) or ():
                if method not in {"HEAD", "OPTIONS"}:
                    yield method, prefix + route.path


def api_routes(app) -> set[tuple[str, str]]:
    """Kapının bildiği /api yolları: yürüyüşün API altı, yani matrisin ölçülecek tarafı."""
    return {(method, path) for method, path in walk(app.routes) if path.startswith("/api")}


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    """Modülün kapısı bir kez: tmp kopya mini küme, sahte model, bir yönetici ve bir kullanıcı."""
    root = tmp_path_factory.mktemp("matrix")
    shutil.copytree(FIXTURE_ROOT / "mini", root / "datasets" / "mini")
    patch = pytest.MonkeyPatch()
    patch.setattr(config, "ROOT", root)
    patch.setenv("NL2SQL_DATASETS_DIR", str(root / "datasets"))
    try:
        cli.build_database(dataset="mini")
        session = open_session(
            dataset="mini",
            llm="fake",
            audit_path=root / "audit.jsonl",
            ask_log=root / "asks.jsonl",
        )
        users = UserStore(root / "bilgin.db")
        users.add_user(ADMIN, PAROLA, "admin")
        users.add_user(USER, PAROLA, "user")
        yield SimpleNamespace(
            root=root,
            session=session,
            users=users,
            app=create_app(
                session, saved_path=root / "bilgin.db", static_dir=root / "static", users=users
            ),
        )
    finally:
        patch.undo()


def test_her_api_yolu_matriste_satir_bulur(world):
    """Satırsız bir /api yolu seviyesiz doğar; satırı olan ama olmayan satır da ölçülmez kalır."""
    assert api_routes(world.app) == {
        key for key in ROUTE_ROLES if key[1].startswith("/api")
    }, "kapı ile matris ayrıştı"


@pytest.mark.parametrize("method,path,level,who", CASES)
def test_kapinin_seviyesi_matristeki_seviye(world, method, path, level, who):
    client = TestClient(world.app)
    if who == "admin":
        login(client, ADMIN)
    elif who == "user":
        login(client, USER)

    response = client.request(method, url(path), json=BODIES.get(path))

    if who == "anonim" and level != "public":
        assert response.status_code == 401, f"{method} {path} oturumsuz {response.status_code}"
        assert response.json() == {"detail": NO_SESSION}
    elif who == "user" and level == "admin":
        assert response.status_code == 403, f"{method} {path} kullanıcıya {response.status_code}"
        assert response.json() == {"detail": NOT_ADMIN}
    else:
        assert response.status_code not in (401, 403), (
            f"{method} {path} {who} için {response.status_code} verdi (matris: {level})"
        )


def test_sayfa_ve_varliklar_hicbir_kimlikten_oturum_istemez(world):
    """Public satırların davranışı: derin bağlantı 401 değil arayüzün kendisi, /assets altı dosya."""
    static = world.root / "built"
    (static / "assets").mkdir(parents=True, exist_ok=True)
    (static / "assets" / "app.js").write_text("ok\n", encoding="utf-8")
    client = TestClient(
        create_app(
            world.session,
            saved_path=world.root / "bilgin.db",
            static_dir=static,
            users=world.users,
        )
    )

    assert client.get("/").status_code == 200
    assert client.get("/kural/brut_ciro").status_code == 200
    assert client.get("/assets/app.js").status_code == 200
