# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""T322: hazır soru tohumları (PLAN R7-19).

Tohum, kümenin klasöründeki ``ready_questions.json``dır ve SQL'i altın kaydın cümlesidir: başlangıç
ekranı taze bir kurulumda da boş kalmaz. Tohum satırı yürütülmez, yalnız yürütücünün politika
süzgecinden geçer - yürümeyecek bir cümle ekranda hata kartı olmak yerine tek satırlık bir notla
düşer. Ayar yazıldığı için ikinci bir açılış hiçbir şey eklemez; yönetici bir kartı sildiğinde geri
gelmez. wwi_real'in tohumu SQL Server'da koşmaz, yani test onun cümlelerini yalnız kendi allowlist
süzgecinden geçirir.
"""

import json
import shutil
from pathlib import Path

import pytest

from bilgin import config, datasets
from bilgin.app.session import open_session
from bilgin.auth.store import UserStore
from bilgin.cli import main as cli
from bilgin.engine.executor import LocalExecutor
from bilgin.policy import policy
from bilgin.schema_map import build, doc
from bilgin.start.cards import card_result
from bilgin.start.ready import DISPLAYS, EVERY_ROLE, ReadyStore
from bilgin.start.seed import SETTING, ensure_seeded

SYNTHETIC = "synthetic_erp"
WWI = "wwi_real"
FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "datasets"
PAROLA = "Bilgin2026!erp"

# Mini kümesinin tohum satırları: biri süzgeçten geçer, öteki kendi kümesinin tablosunu okumaz.
MINI_OK = {
    "business_role": "satis",
    "title": "Müşteri listesi",
    "question": "Müşteriler kim?",
    "sql": "SELECT CustomerID, CustomerName FROM Sales.Customers ORDER BY CustomerID",
    "display": "table",
    "position": 1,
}
MINI_DENIED = {
    "business_role": "*",
    "title": "Yasak tablo",
    "question": "Olmayan tablo?",
    "sql": "SELECT CARI_KOD FROM TBLSTHAR",
    "display": "number",
    "position": 0,
}


@pytest.fixture
def world(tmp_path):
    """Kurulmuş sentetik ERP, gerçek oturum ve iki depo: model hiç çağrılmaz."""
    db = tmp_path / "test.db"
    build.build_db(config.SEED, db, db.with_suffix(".sql"))
    session = open_session(
        dataset=SYNTHETIC,
        llm="fake",
        db_path=db,
        audit_path=tmp_path / "audit.jsonl",
        ask_log=tmp_path / "asks.jsonl",
    )
    users = UserStore(tmp_path / "app.db")
    return session, ReadyStore(tmp_path / "app.db"), users


def _executor_for(ds: datasets.Dataset, tmp_path: Path) -> LocalExecutor:
    """Kümenin şemasıyla bir yürütücü: tohum hiçbir şey yürütmediği için veritabanı gerekmez."""
    schema = ds.schema()
    return LocalExecutor(
        db_path=tmp_path / "yok.db",
        allowlist=doc.allowlist(schema),
        audit_path=tmp_path / "audit.jsonl",
        pii_schema=schema,
    )


def _mini(tmp_path: Path, lines: list[dict] | None = None) -> datasets.Dataset:
    """Mini kümesinin tmp kopyası: satır söylenirse tohum dosyası yazılır ve ``files``a eklenir."""
    folder = tmp_path / "datasets" / "mini"
    shutil.copytree(FIXTURE_ROOT / "mini", folder)
    if lines is not None:
        (folder / "ready_questions.json").write_text(
            json.dumps(lines, ensure_ascii=False), encoding="utf-8"
        )
        meta = json.loads((folder / "dataset.json").read_text(encoding="utf-8"))
        meta["files"] = {**(meta.get("files") or {}), "ready_questions": "ready_questions.json"}
        (folder / "dataset.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    return datasets.load_dataset("mini", root=tmp_path / "datasets")


# --------------------------------------------------------------------- sentetik tohumun yürüyüşü


def test_the_seeded_cards_run_on_the_built_database_with_results(world):
    session, store, users = world

    seeded = ensure_seeded(store, users, session.dataset, session.executor)

    lines = session.dataset.ready_questions()
    assert seeded == len(lines) == len(store.list_all(SYNTHETIC))
    for card in store.list_all(SYNTHETIC):
        payload = card_result(session.executor, card, "test")
        assert "error" not in payload, f"{card['title']}: {payload.get('error')}"
        if card["display"] == "number":
            assert isinstance(payload["value"], (int, float)), "sayı kartının değeri olmalı"
        elif card["display"] == "chart":
            assert payload["chart"] is not None, "grafik kartının çizilecek bir şeyi olmalı"
        else:
            assert payload["rows"], "tablo kartının satırı olmalı"


def test_every_business_role_sees_its_own_cards_and_the_common_one(world):
    session, store, users = world
    ensure_seeded(store, users, session.dataset, session.executor)

    common = [card for card in store.list_all(SYNTHETIC) if card["business_role"] == EVERY_ROLE]
    assert len(common) == 1 and common[0]["approved"] is True
    for role in config.BUSINESS_ROLES:
        visible = store.list_for(SYNTHETIC, role, "eren")
        assert common[0] in visible, "ortak kart her rolün ekranındadır"
        assert len(visible) >= 3, "kendi kartları + ortak kart"
    own = {
        role: {card["id"] for card in store.list_for(SYNTHETIC, role, "eren")} - {common[0]["id"]}
        for role in config.BUSINESS_ROLES
    }
    # Her rolün iki kartı var ve hiçbiri ötekininkiyle aynı değil: rol kartı gerçekten ayrıdır.
    assert all(len(ids) == 2 for ids in own.values())
    assert len(set().union(*own.values())) == 2 * len(config.BUSINESS_ROLES)


def test_the_synthetic_seeds_carry_every_display():
    lines = datasets.load_dataset(SYNTHETIC).ready_questions()

    assert {line["display"] for line in lines} == set(DISPLAYS)


# ------------------------------------------------------------------------- tohumun sözleşmesi


@pytest.mark.parametrize("name", [SYNTHETIC, WWI])
def test_every_seed_line_stays_inside_the_contract(name):
    lines = datasets.load_dataset(name).ready_questions()

    assert lines
    for line in lines:
        assert line["business_role"] == EVERY_ROLE or line["business_role"] in config.BUSINESS_ROLES
        assert line["display"] in DISPLAYS
        assert line["title"].strip() and line["question"].strip() and line["sql"].strip()
        assert isinstance(line["position"], int)
    for role in config.BUSINESS_ROLES:
        assert sum(1 for line in lines if line["business_role"] == role) >= 2, role


def test_the_wwi_real_seeds_pass_their_own_allowlist(tmp_path, capsys):
    ds = datasets.load_dataset(WWI)
    lines = ds.ready_questions()

    allowlist = doc.allowlist(ds.schema())
    for line in lines:
        verdict = policy.check(line["sql"], allowlist, config.TOP_N)
        assert verdict.ok, f"{line['title']}: {verdict.reason}"

    store, users = ReadyStore(tmp_path / "app.db"), UserStore(tmp_path / "app.db")
    assert ensure_seeded(store, users, ds, _executor_for(ds, tmp_path)) == len(lines)
    assert capsys.readouterr().out == "", "hiçbir satır düşmez"


# ---------------------------------------------------------------------------- bir kez tohumlama


def test_seeding_twice_adds_nothing_and_a_deleted_card_does_not_come_back(world):
    session, store, users = world
    seeded = ensure_seeded(store, users, session.dataset, session.executor)
    rows = store.list_all(SYNTHETIC)

    assert ensure_seeded(store, users, session.dataset, session.executor) == 0
    assert store.list_all(SYNTHETIC) == rows
    assert users.get_setting(SETTING.format(name=SYNTHETIC)) == str(seeded)

    store.delete(rows[0]["id"])
    assert ensure_seeded(store, users, session.dataset, session.executor) == 0
    assert rows[0]["id"] not in {card["id"] for card in store.list_all(SYNTHETIC)}


def test_a_dataset_without_a_seed_file_is_never_stamped(tmp_path):
    ds = _mini(tmp_path)
    store, users = ReadyStore(tmp_path / "app.db"), UserStore(tmp_path / "app.db")

    assert ds.ready_questions_path is None
    assert ensure_seeded(store, users, ds, _executor_for(ds, tmp_path)) == 0
    assert users.get_setting(SETTING.format(name="mini")) is None
    assert store.list_all("mini") == []


# ------------------------------------------------------------------- çağrının yeri ve reddi


def test_the_first_serve_of_a_dataset_writes_its_seeds(tmp_path, monkeypatch, capsys):
    """Çağrı yeri (R7-19): ``serve`` açılışta tohumu yazar - küme geçişi de aynı kapıdan geçer."""
    _mini(tmp_path, [MINI_OK])
    monkeypatch.setattr(config, "ROOT", tmp_path)
    monkeypatch.setenv("BILGIN_DATASETS_DIR", str(tmp_path / "datasets"))
    monkeypatch.setenv("BILGIN_REAL_DATASETS_DIR", str(tmp_path / "real_datasets"))
    monkeypatch.setenv("BILGIN_APP_DB", str(tmp_path / "app.db"))
    assert cli.build_database(dataset="mini") == 0
    users = UserStore(tmp_path / "app.db")
    users.add_user("admin", PAROLA, "admin")
    monkeypatch.setattr(cli, "run_server", lambda app, host, port: None)
    capsys.readouterr()

    assert cli.serve(llm_kind="fake", dataset="mini") == 0

    assert [card["title"] for card in ReadyStore(tmp_path / "app.db").list_all("mini")] == (
        ["Müşteri listesi"]
    )
    assert users.get_setting(SETTING.format(name="mini")) == "1"


def test_a_seed_line_the_policy_refuses_is_skipped_with_one_log_line(tmp_path, capsys):
    ds = _mini(tmp_path, [MINI_DENIED, MINI_OK])
    store, users = ReadyStore(tmp_path / "app.db"), UserStore(tmp_path / "app.db")

    assert ensure_seeded(store, users, ds, _executor_for(ds, tmp_path)) == 1

    out = capsys.readouterr().out
    assert "Yasak tablo" in out and "TBLSTHAR" in out, "not kümenin, satırın ve reddin cümlesini taşır"
    assert [card["title"] for card in store.list_all("mini")] == ["Müşteri listesi"]
    assert users.get_setting(SETTING.format(name="mini")) == "1"
