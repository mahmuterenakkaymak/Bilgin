"""T235: görsel inceleme kendi kum havuzunda koşar (PLAN R6-20).

``scripts/visual_serve.py`` tarayıcı akışının ``serve``ı: kullanıcıları kendisi açar, veriyi
``data/visual/`` altında tutar. İzolasyonun kendisi yol denetimi olduğu için iki şey ölçülür: kum
havuzunda ne kurulur, dışarıda ne reddedilir. Son iki test parolanın sınırını söyler —
``VISUAL_PASSWORD`` bir kum havuzu sabitidir, ürün kodunun (``nl2sql/``) hiçbir dosyasına giremez
ama akışın her sayfası da onu yazmak zorundadır, yoksa inceleme giriş kartında kalır.
"""

import contextlib
import json
import sqlite3

import pytest

from nl2sql import config
from nl2sql.auth.store import UserStore
from nl2sql.schema_map import template
from scripts import visual_serve

# visual.json'ın yanlış parola denemesi; doğrusu modül sabitinden okunur, kopyalanmaz.
WRONG_PASSWORD = "Yanlis-Parola-2026"


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    """Kum havuzu tmp'nin içine taşınır: test ne ``data/`` ne ``real_datasets/`` dokunur."""
    monkeypatch.setattr(visual_serve, "VISUAL_DIR", tmp_path / "visual")
    return visual_serve.VISUAL_DIR


def typed_passwords(page: dict) -> list[str]:
    """Sayfanın parola alanına yazdığı değerler, adımların sırasıyla."""
    return [
        step["fill"][1]
        for step in page["steps"]
        if isinstance(step, dict) and step.get("fill", [None])[0] == "#login-password"
    ]


# ------------------------------------------------------------------ kum havuzunun içi


def test_seeding_opens_exactly_the_two_reviewer_accounts(sandbox):
    users = visual_serve.seed_users(sandbox / "bilgin.db")

    store = UserStore(sandbox / "bilgin.db")
    assert [user["username"] for user in users] == ["admin", "analist"]
    assert [(u["username"], u["role"]) for u in store.list_users()] == [("admin", "admin"), ("analist", "user")]
    store.authenticate("admin", visual_serve.VISUAL_PASSWORD)
    store.authenticate("analist", visual_serve.VISUAL_PASSWORD)


def test_seeding_starts_from_an_empty_user_table_every_run(sandbox):
    """Her koşu baştan kurulur: önceki koşunun bıraktığı hesap incelemede görünmez."""
    visual_serve.seed_users(sandbox / "bilgin.db")
    UserStore(sandbox / "bilgin.db").add_user("yabanci", visual_serve.VISUAL_PASSWORD, "user")

    visual_serve.seed_users(sandbox / "bilgin.db")

    assert [u["username"] for u in UserStore(sandbox / "bilgin.db").list_users()] == ["admin", "analist"]


# ------------------------------------------------------------------ haritanın örnek kümesi


def test_the_sample_flow_gets_a_database_it_can_switch_to(tmp_path):
    """Akışın son adımları örnek kümeye geçer; veritabanı olmayan kümeye geçiş 409'dur.

    Küme uygulandığında veritabanı üretilmediği için dosyayı akışın kendisi kurar, ve yolu
    parametredir: test ``data/ornek_fatura.db``ye değil ``tmp_path``e bakar.
    """
    db = visual_serve.build_sample_db(tmp_path / "ornek_fatura.db")

    with contextlib.closing(sqlite3.connect(db)) as conn:
        tables = [row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        columns = [row[1] for row in conn.execute(f'PRAGMA table_info("{template.EXAMPLE_TABLE}")')]

    assert db.is_file()
    # Okuyucu adları büyütür (R4-5): tablonun doğduğunu adının birebir kopyası değil, ölçüsü söyler.
    assert [name.upper() for name in tables] == [template.EXAMPLE_TABLE.upper()], (
        "örnek şablonun tek tablosu diskte doğmadı"
    )
    assert "FATURAID" in columns, "DDL şablonun kolonlarını taşımıyor"


# ------------------------------------------------------------------ kum havuzunun dışı


def test_seeding_refuses_the_default_app_database(tmp_path, monkeypatch, sandbox):
    """``data/bilgin.db`` kum havuzunun dışıdır: gerçek kullanıcı deposu asla sıfırlanamaz."""
    monkeypatch.setattr(config, "APP_DB_PATH", tmp_path / "uygulama" / "bilgin.db")
    real = config.APP_DB_PATH
    real.parent.mkdir(parents=True)
    real.write_bytes(b"gercek kullanicilar")

    with pytest.raises(visual_serve.VisualError):
        visual_serve.seed_users(config.APP_DB_PATH)

    assert real.read_bytes() == b"gercek kullanicilar"


def test_seeding_refuses_any_path_outside_the_visual_root(sandbox):
    outside_root = sandbox.parent
    for outside in (outside_root / "bilgin.db", outside_root / "visual_x" / "bilgin.db"):
        with pytest.raises(visual_serve.VisualError):
            visual_serve.seed_users(outside)
        assert not outside.exists(), "reddedilen yol silinmiş ya da kurulmuş"


# ------------------------------------------------------------------ parolanın sınırı


def test_the_fixture_password_never_enters_the_product_code():
    """Kum havuzu parolası yalnız betikte ve akışta durur; ürün kodu onu tanımaz."""
    needle = visual_serve.VISUAL_PASSWORD.encode("utf-8")
    root = config.ROOT / "nl2sql"
    hits = [
        str(path.relative_to(root))
        for path in sorted(root.rglob("*"))
        if path.is_file() and needle in path.read_bytes()
    ]

    assert not hits


def test_every_page_logs_in_with_the_password_the_sandbox_seeds():
    """Sabit değişirse akışın her sayfası girişte kalır: iki taraf birlikte kırmızıya döner."""
    doc = json.loads((config.ROOT / ".hybrid" / "visual.json").read_text(encoding="utf-8"))

    for page in doc["pages"]:
        typed = typed_passwords(page)
        assert visual_serve.VISUAL_PASSWORD in typed, f"{page['name']} doğru parolayı yazmıyor"
        assert set(typed) <= {visual_serve.VISUAL_PASSWORD, WRONG_PASSWORD}, page["name"]
