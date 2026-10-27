"""T479: uyarılar cevabın dilinde okunur (PLAN R8-3: "error/warning sentences t(..., answer_lang)").

Dünya test_checks_basic ile test_checks_fanout'un dünyası: ``build_db`` ile kurulmuş sentetik ERP,
gerçek schema ve gerçek ``LocalExecutor``, yani uyarı hazır bir nesneye değil kapıdan geçmiş bir
sonuca bakıyor. İngilizce taraf kataloğun kendi satırıdır; Türkçe taraf 2026-10-27'de ekranda okunan
cümlenin harfi harfinesi - cümleler modülün sabitlerinden kataloğa taşınırken baytlar oynamadı. Son
iki iddia modülün ve sunucunun kendisininki: ``checks.py`` kullanıcıya artık Türkçe bir sabit söylemez,
ve kapıdan geçen İngilizce bir cevap uyarısını da İngilizce alır.
"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from nl2sql import config
from nl2sql.agent import fake
from nl2sql.app.session import open_session
from nl2sql.engine import checks
from nl2sql.engine.executor import LocalExecutor
from nl2sql.engine.result import Budget
from nl2sql.i18n import t
from nl2sql.i18n.scan import user_literals
from nl2sql.schema_map import build, doc
from nl2sql.web.app import create_app

SCHEMA = doc.load_schema()
FULL = Budget(max_rows=100000)

EMPTY_SQL = "SELECT STOK_ADI FROM TBLSTSABIT WHERE STOK_ADI = 'OLMAYAN URUN'"
NULL_SQL = "SELECT CASE WHEN 1 = 2 THEN 'x' END AS BOS_KOLON FROM TBLSTSABIT"
CROSS_SQL = "SELECT A.STOK_KODU, B.STOK_KODU AS B_KOD FROM TBLSTHAR A, TBLSTHAR B"
TCKN_SQL = "SELECT TCKN FROM TBLPERSONEL ORDER BY PERSONEL_KODU"

AUGUST = "f.TARIH >= '2026-08-01' AND f.TARIH < '2026-09-01'"
FAN_SQL = (
    "SELECT SUM(f.GENELTOPLAM) AS TOPLAM FROM TBLFATUIRS f "
    "JOIN TBLSTHAR s ON s.CARI_KODU = f.CARI_KODU WHERE " + AUGUST
)
JOINED_COUNT_SQL = (
    "SELECT COUNT(*) FROM TBLFATUIRS f JOIN TBLSTHAR s ON s.CARI_KODU = f.CARI_KODU WHERE " + AUGUST
)
DRIVING_COUNT_SQL = "SELECT COUNT(*) FROM TBLFATUIRS f WHERE " + AUGUST

EN_QUESTION = "List the products that no sale has ever had"

# 2026-10-27'de ekranda okunan cümleler: sabitler kataloğa taşınırken baytlar oynamadı.
TODAY = {
    "checks.empty": "Sonuç boş: bu koşullara uyan kayıt yok.",
    "checks.all_null": "'{col}' kolonunun tüm değerleri boş (NULL).",
    "checks.top_limited": "Sonuç {n} satırlık üst sınırda kesildi; tamamı daha fazla olabilir.",
    "checks.masked": "Maskelendi: {cols} — kişisel veri gösterilmez.",
    "checks.fan_out": (
        "Join sonrası {joined} satır, sürücü tablo {table} {driving} satır ({ratio}x): "
        "toplamlar çoğalmış olabilir."
    ),
}


@pytest.fixture(scope="module")
def db(tmp_path_factory):
    path = tmp_path_factory.mktemp("checks-lang") / "test.db"
    build.build_db(config.SEED, path, path.with_suffix(".sql"))
    return path


@pytest.fixture
def executor(db, tmp_path):
    return LocalExecutor("sqlite", db, doc.allowlist(SCHEMA), tmp_path / "audit.jsonl", SCHEMA)


# ------------------------------------------------------------------ dört kolay denetim


@pytest.mark.parametrize(
    "code,sql,key,params",
    [
        ("empty", EMPTY_SQL, "checks.empty", {}),
        ("all_null", NULL_SQL, "checks.all_null", {"col": "BOS_KOLON"}),
        ("top_limited", CROSS_SQL, "checks.top_limited", {"n": config.TOP_N}),
        ("masked", TCKN_SQL, "checks.masked", {"cols": "TCKN"}),
    ],
    ids=["empty", "all_null", "top_limited", "masked"],
)
def test_a_warning_says_its_line_in_the_language_asked(executor, code, sql, key, params):
    result = executor.execute(sql, FULL)
    assert result.error is None

    english = checks.post_checks(sql, result, executor, "en")
    assert [warning.code for warning in english] == [code]
    assert english[0].message == t(key, "en", **params)

    assert checks.post_checks(sql, result, executor) == checks.post_checks(
        sql, result, executor, "tr"
    ), "söylenmeyen dil bugünkü gibi Türkçe"
    assert [w.message for w in checks.post_checks(sql, result, executor, "tr")] == [
        TODAY[key].format(**params)
    ]


# ------------------------------------------------------------------ katlanan join


def test_a_fanning_join_warns_in_english_too(executor):
    result = executor.execute(FAN_SQL, FULL)
    assert result.error is None
    joined = executor.execute(JOINED_COUNT_SQL, FULL).rows[0][0]
    driving = executor.execute(DRIVING_COUNT_SQL, FULL).rows[0][0]
    params = {
        "joined": joined,
        "table": "TBLFATUIRS",
        "driving": driving,
        "ratio": f"{joined / driving:.1f}".replace(".", ","),
    }

    assert checks.post_checks(FAN_SQL, result, executor, "en")[0].message == t(
        "checks.fan_out", "en", **params
    )
    assert checks.post_checks(FAN_SQL, result, executor)[0].message == TODAY[
        "checks.fan_out"
    ].format(**params)


# ------------------------------------------------------------------ modülün kendisi ve sunucu


def test_checks_py_holds_no_turkish_user_literals():
    assert user_literals(Path(checks.__file__)) == []


@pytest.fixture
def client(db, tmp_path):
    """Sunucunun kapısı: senaryosu elle verilmiş sahte model boş dönen bir sorgu oynatır."""
    session = open_session(
        llm="fake",
        db_path=db,
        audit_path=tmp_path / "audit.jsonl",
        ask_log=tmp_path / "asks.jsonl",
        client_factory=lambda mode: fake.FakeLLM(fake.wrong_sql(EMPTY_SQL)),
    )
    app = create_app(session, saved_path=tmp_path / "bilgin.db", static_dir=tmp_path / "static")
    test_client = TestClient(app)
    test_client.headers["accept-language"] = "en"
    return test_client


def test_an_english_answer_on_the_server_warns_in_english(client):
    body = client.post("/api/ask", json={"question": EN_QUESTION, "mode": "full"}).json()

    assert body["status"] == "answered" and body["answer_lang"] == "en"
    assert [warning["code"] for warning in body["warnings"]] == ["empty"]
    assert body["warnings"][0]["message"] == t("checks.empty", "en")
