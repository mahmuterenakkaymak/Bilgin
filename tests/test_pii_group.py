# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""R5-21 grup yan kanalı: tek kişilik departmanda maaş ortalaması maskelenir.

Maske kuralı (R3-6) bir toplulaştırmayı yalnız COUNT için sayı bırakıyor; AVG/MAX/SUM maaş
beyaz listede değil. Tehlike GROUP BY'da: bir departmanda tek aktif kişi varsa o kişinin
ORTALAMASI doğrudan kendi maaşıdır - toplulaştırma hiçbir şeyi gizlemiyordur. Bu test kurulmuş
dünyada gerçek ``LocalExecutor``'dan geçirerek o ortalamanın yine maskelendiğini, MAX/SUM ve
``HAVING COUNT(*) = 1`` biçimlerinin de maskeli ya da reddedilmiş kaldığını, ``COUNT(*)``'ın ise
sayı olarak döndüğünü kanıtlar; aynı SQL ``ask_payload``'tan da maskeli ve uyarılı çıkar.

ASSUMPTION: üretici DEPARTMAN_KODU'yu NULL bırakıyor (extra.py: TBLDEPARTMAN şema-yalnız), o
yüzde kurulmuş veride "tek aktif kişili departman" BULUNAMAZ; senaryo testin kendi tmp kopyasında
departman kodları atanarak kurulur - üreticiye ve başka testlere dokunulmaz.
"""

import sqlite3
from pathlib import Path

import pytest

from bilgin import config
from bilgin.agent import fake
from bilgin.app.ask import ask_payload
from bilgin.app.session import open_session
from bilgin.engine.executor import LocalExecutor
from bilgin.engine.result import Budget
from bilgin.schema_map import build, doc

SCHEMA = doc.load_schema()
FULL = Budget(max_rows=100000)
SOLO = "D002"  # tek aktif kişili departman; ötekiler D001'de toplanır
FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "datasets"

JOIN = "FROM TBLPERSONEL p JOIN TBLMAAS m ON m.PERSONEL_KODU = p.PERSONEL_KODU WHERE p.AKTIF = 'E'"
AVG_SQL = f"SELECT p.DEPARTMAN_KODU, AVG(m.NET_TUTAR) AS ORT_NET {JOIN} GROUP BY p.DEPARTMAN_KODU"
MAX_SQL = f"SELECT p.DEPARTMAN_KODU, MAX(m.NET_TUTAR) AS AG_SQL {JOIN} GROUP BY p.DEPARTMAN_KODU"
SUM_SQL = f"SELECT p.DEPARTMAN_KODU, SUM(m.NET_TUTAR) AS TOPLAM_NET {JOIN} GROUP BY p.DEPARTMAN_KODU"
HAVING_SQL = f"{AVG_SQL} HAVING COUNT(*) = 1"
COUNT_SQL = f"SELECT p.DEPARTMAN_KODU, COUNT(*) AS ADET {JOIN} GROUP BY p.DEPARTMAN_KODU"


def _arrange(db) -> tuple[str, float]:
    """Tek aktif kişili, tek bordroluk bir departman kurar; (departman, o kişinin net maaşı) döner.

    ASSUMPTION: üretici departman kodu vermediği için (yukarıdaki ASSUMPTION) kodlar burada
    atanır; solo kişi tek bordroya indirilir ki AVG tam olarak onun maaşı olsun - maskelenmezse
    ham maaşın ekrana düşeceği en uç durum.
    """
    conn = sqlite3.connect(db)
    try:
        solo = conn.execute(
            "SELECT p.PERSONEL_KODU FROM TBLPERSONEL p JOIN TBLMAAS m ON m.PERSONEL_KODU = p.PERSONEL_KODU"
            " WHERE p.AKTIF = 'E' ORDER BY p.PERSONEL_KODU LIMIT 1"
        ).fetchone()[0]
        conn.execute(
            "DELETE FROM TBLMAAS WHERE PERSONEL_KODU = ? AND MAAS_ID NOT IN"
            " (SELECT MIN(MAAS_ID) FROM TBLMAAS WHERE PERSONEL_KODU = ?)",
            (solo, solo),
        )
        conn.execute("UPDATE TBLPERSONEL SET DEPARTMAN_KODU = 'D001'")
        conn.execute("UPDATE TBLPERSONEL SET DEPARTMAN_KODU = ? WHERE PERSONEL_KODU = ?", (SOLO, solo))
        conn.commit()
        net = conn.execute("SELECT NET_TUTAR FROM TBLMAAS WHERE PERSONEL_KODU = ?", (solo,)).fetchone()[0]
    finally:
        conn.close()
    return SOLO, net


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("pii-group")
    db = tmp / "test.db"
    build.build_db(config.SEED, db, db.with_suffix(".sql"))
    return db, _arrange(db)


@pytest.fixture(scope="module")
def db(world):
    return world[0]


@pytest.fixture(scope="module")
def solo(world):
    return world[1]


@pytest.fixture
def executor(db, tmp_path):
    return LocalExecutor("sqlite", db, doc.allowlist(SCHEMA), tmp_path / "audit.jsonl", SCHEMA)


def cell(result, departman, column):
    """Verilen departmanın satırında o kolonun hücresi; satır yoksa KeyError ile patlar."""
    index = result.columns.index(column)
    row = next(row for row in result.rows if row[0] == departman)
    return row[index]


def assert_masked_or_rejected(result, column):
    """Ya politika reddetti ya da dönen her hücre maskeli: hiçbir durumda ham maaş yok."""
    if result.error is not None:
        assert result.error.kind == "policy"
        return
    assert column not in result.columns or all(
        value == "***" for value in (row[result.columns.index(column)] for row in result.rows)
    )


# ----------------------------------------------------------------- the scenario is real


def test_the_built_world_has_a_single_active_employee_department(db, solo):
    departman, net = solo
    conn = sqlite3.connect(db)
    try:
        active = conn.execute(
            "SELECT COUNT(*) FROM TBLPERSONEL WHERE AKTIF = 'E' AND DEPARTMAN_KODU = ?", (departman,)
        ).fetchone()[0]
        bordro = conn.execute(
            "SELECT COUNT(*) FROM TBLMAAS m JOIN TBLPERSONEL p ON p.PERSONEL_KODU = m.PERSONEL_KODU"
            " WHERE p.DEPARTMAN_KODU = ?",
            (departman,),
        ).fetchone()[0]
    finally:
        conn.close()
    assert active == 1 and bordro == 1, "senaryo tek kişi + tek bordro olmalı"
    assert net > 0


# ----------------------------------------------------------------- AVG masked on the single-person group


def test_avg_over_a_single_person_stays_masked(executor, solo):
    departman, net = solo
    result = executor.execute(AVG_SQL, FULL, "group-avg")

    assert result.error is None, result.error
    assert result.rows, "tek kişilik departman sonuçta yok"
    assert result.masked_columns == ["ORT_NET"]
    assert cell(result, departman, "ORT_NET") == "***"
    assert net not in [row[1] for row in result.rows], "ham maaş ortalama kolonunda göründü"


@pytest.mark.parametrize("sql,column", [(MAX_SQL, "AG_SQL"), (SUM_SQL, "TOPLAM_NET"), (AVG_SQL, "ORT_NET")])
def test_max_sum_avg_variants_stay_masked(executor, sql, column):
    assert_masked_or_rejected(executor.execute(sql, FULL, f"group-{column}"), column)


def test_having_count_one_does_not_unmask(executor, solo):
    departman, net = solo
    result = executor.execute(HAVING_SQL, FULL, "group-having")

    assert_masked_or_rejected(result, "ORT_NET")
    if result.error is None and result.rows:
        assert cell(result, departman, "ORT_NET") == "***"
        assert net not in [row[1] for row in result.rows]


# ----------------------------------------------------------------- COUNT stays a number


def test_count_per_department_stays_a_number(executor, solo):
    departman, _ = solo
    result = executor.execute(COUNT_SQL, FULL, "group-count")

    assert result.error is None, result.error
    assert "ADET" not in result.masked_columns
    value = cell(result, departman, "ADET")
    assert isinstance(value, int) and value == 1


# ----------------------------------------------------------------- through ask_payload


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "ROOT", tmp_path)
    monkeypatch.setenv("BILGIN_DATASETS_DIR", str(FIXTURE_ROOT))
    return tmp_path


def test_ask_payload_of_the_group_query_is_masked_with_a_warning(project, db, solo):
    departman, net = solo
    session = open_session(
        llm="fake",
        db_path=db,
        audit_path=project / "audit.jsonl",
        ask_log=project / "asks.jsonl",
        client_factory=lambda mode: fake.FakeLLM(fake.wrong_sql(AVG_SQL)),
    )
    payload = ask_payload(session, "Departman başına ortalama net maaş ne kadar?", mode="full")

    assert payload["status"] == "answered"
    assert "ORT_NET" in payload["masked_columns"]
    assert any(warning["code"] == "masked" for warning in payload["warnings"])
    index = payload["columns"].index("ORT_NET")
    row = next(row for row in payload["rows"] if row[0] == departman)
    assert row[index] == "***"
    assert all(row[index] != net for row in payload["rows"]), "ham maaş payload'a düştü"
