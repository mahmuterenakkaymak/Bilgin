"""T101: M9 entegrasyonu — maske tek kapıda, iki katman aynı kolonları sayıyor, altın küme yeşil.

Elle yapılmış sahte yok: dünya gerçek ``build_db``, kapı gerçek ``LocalExecutor`` (pii işaretleri gerçek
``schema/schema.json``'dan), kaçış kümesi gerçek ``tests/data/pii_bypass.jsonl``, giriş betiği gerçek
``readonly_login_sql`` ve CLI'ın yazdığı dosya, sorular gerçek altın küme ve gerçek döngüden geçmiş kendi
kaydı. Fazın iddiası üç cümle: maske satırları executor'da, yedekten döndükten sonra gördüğü için hiçbir
çağıran ham değer görmüyor; veritabanı yetkisi ile parser **aynı** şemayı sayıyor (biri düşerse öbürü
neyi kaybettiğimizi bilmeli); ve iki katmanın hiçbiri altın cevapları değiştirmiyor. Son test Run 3'ün
ekranı: README'de yazılmayan bir komut kullanıcının elinde yoktur.
"""

import json
import re
import sqlite3
from pathlib import Path

import pytest
import sqlglot

from nl2sql import config
from nl2sql.agent import fake
from nl2sql.cli import main as cli
from nl2sql.engine import login_script
from nl2sql.engine.executor import LocalExecutor
from nl2sql.engine.result import Budget
from nl2sql.eval import runner
from nl2sql.policy import pii
from nl2sql.schema_map import build, doc

SCHEMA = doc.load_schema()
MARKS = pii.column_map(SCHEMA)
GOLDEN = runner.load_golden()
CASES = [
    json.loads(line)
    for line in (Path(__file__).parent / "data" / "pii_bypass.jsonl")
    .read_text(encoding="utf-8")
    .splitlines()
    if line.strip()
]
MASKED = [case for case in CASES if case["expect"] == "masked"]
# beyaz listedeki COUNT satırları "masked" bekler ama maskelenecek kolonu yoktur (R3-6)
HIDING = [case for case in MASKED if case["masked_columns"]]
REJECTED = [case for case in CASES if case["expect"] == "rejected"]
FULL = Budget(max_rows=config.COMPARE_MAX_ROWS)

# Run 3'ün eklediği yüzey: README'de her biri ayrı ayrı geçecek (R3-13, R3-14).
SUBCOMMANDS = ("import-map", "introspect", "diff-map", "merge-map", "make-login-script")
FLAGS = (
    "--accept",
    "--mapping",
    "--sample",
    "--db-schema",
    "--login",
    "--schema",
    "--mode auto",
    "--repeat",
)
README_MARKS = (
    "Bilgin",
    "__DEGISTIR__",
    "Windows auth",
    "sysadmin",
    "ApplicationIntent=ReadOnly",
    "DENY SELECT",
    "Maskelendi:",
    "fail closed",
    "AUTO_FULL_MAX_TOKENS",
    "fark gürültü içinde",
    "Nothing in the test suite touches a real server",
)

COLUMN_DENY = re.compile(r"DENY SELECT \(([^)]*)\) ON \[dbo\]\.\[(\w+)\] TO")
NOT_IN = re.compile(r"NOT IN \(([^)]*)\)")
PASSWORD = re.compile(r"PASSWORD\s*=\s*'([^']*)'")


def denied_columns(script: str) -> set[tuple[str, str]]:
    return {
        (table, column)
        for columns, table in COLUMN_DENY.findall(script)
        for column in columns.split(", ")
    }


def raw_values(db) -> set:
    """Pii işaretli her kolonun ham değerleri: doğrudan dosyadan, executor'a hiç uğramadan."""
    found = set()
    conn = sqlite3.connect(db)
    try:
        for table, column in sorted(MARKS):
            for (value,) in conn.execute(f"SELECT [{column}] FROM [{table}]"):
                if isinstance(value, str) and value.strip():
                    found.add(value)
    finally:
        conn.close()
    return found


@pytest.fixture(scope="module")
def db(tmp_path_factory):
    root = tmp_path_factory.mktemp("m9")
    path = root / "test.db"
    build.build_db(config.SEED, path, root / "test.sql")
    return path


@pytest.fixture(scope="module")
def guarded(db, tmp_path_factory):
    """Tek kapı, tek denetim kaydı: şemanın pii işaretleriyle kurulmuş gerçek executor."""
    audit = tmp_path_factory.mktemp("m9-audit") / "audit.jsonl"
    return LocalExecutor("sqlite", db, doc.allowlist(SCHEMA), audit, SCHEMA), audit


# ----------------------------------------------------------- kaçış kümesi gerçek kapıdan


@pytest.mark.parametrize("case", MASKED, ids=[case["id"] for case in MASKED])
def test_a_bypass_case_leaves_only_the_columns_the_file_lists(case, guarded):
    executor, _ = guarded
    result = executor.execute(case["sql"], FULL, case["id"])
    assert result.error is None, result.error
    assert result.rows, f"{case['id']} boş döndü; maske hiçbir hücreyi görmedi"
    assert result.masked_columns == case["masked_columns"]


@pytest.mark.parametrize("case", REJECTED, ids=[case["id"] for case in REJECTED])
def test_a_filtered_pii_column_is_refused_before_the_database(case, guarded):
    executor, _ = guarded
    result = executor.execute(case["sql"], FULL, case["id"])
    assert result.error is not None and result.error.kind == "policy"
    assert "PII kolon:" in result.error.message, "sebep kolonu adlandırmıyor"
    assert result.rows == [] and result.masked_columns == []


def test_a_masked_column_never_carries_a_raw_value(db, guarded):
    """Maske değeri göstermez: maskelendiği söylenen hiçbir kolon ham bir pii değeri taşımaz."""
    executor, _ = guarded
    leaked = raw_values(db)
    assert leaked, "pii işaretli kolonlarda okunacak değer yok; test hiçbir şey ölçmüyor"
    assert HIDING, "kümede maskelenen kolonu olan satır kalmadı"
    for case in HIDING:
        result = executor.execute(case["sql"], FULL, case["id"])
        hidden = [
            (index, name)
            for index, name in enumerate(result.columns)
            if name in result.masked_columns
        ]
        assert hidden, f"{case['id']} maskelendi dediği kolonu bulamadı: {result.columns}"
        for row in result.rows:
            for index, name in hidden:
                assert row[index] not in leaked, f"{case['id']}.{name} ham değer verdi"


def test_the_audit_of_the_whole_set_names_columns_and_never_values(db, tmp_path):
    """Kümenin tamamı tek kayda yazılır: satırlar da değerler de orada değil, adlar orada."""
    audit = tmp_path / "audit.jsonl"
    executor = LocalExecutor("sqlite", db, doc.allowlist(SCHEMA), audit, SCHEMA)
    for case in CASES:
        executor.execute(case["sql"], FULL, case["id"])

    lines = [json.loads(line) for line in audit.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(lines) == len(CASES), "her deneme tek satır"
    by_source = {line["source"]: line for line in lines}
    for case in MASKED:
        assert by_source[case["id"]].get("masked", []) == case["masked_columns"]
    for case in REJECTED:
        assert by_source[case["id"]]["outcome"] == "policy"

    text = audit.read_text(encoding="utf-8")
    assert all(value not in text for value in raw_values(db)), "denetim satırında değer var"


# ----------------------------------------------------------- birinci katman: veritabanı yetkisi


def test_the_login_script_denies_exactly_what_the_schema_marks(tmp_path):
    """CLI'ın yazdığı betik: kolon DENY kümesi şemanın pii işaretleriyle birebir aynı, fazlası değil."""
    out = tmp_path / "ro.sql"
    assert cli.make_login_script(out=out) == 0
    script = out.read_text(encoding="utf-8")

    sqlglot.parse(script, read="tsql")  # kalıcı kontrol T-SQL olarak ayrışmıyorsa hiçbir şeyi garanti etmez
    assert denied_columns(script) == set(MARKS)
    assert doc.allowlist(SCHEMA) <= set(
        re.findall(r"'([^']*)'", NOT_IN.search(script).group(1))
    ), "allowlist'teki bir tablo cursor'ın NOT IN listesinde değil"
    assert PASSWORD.findall(script) == [login_script.PASSWORD_PLACEHOLDER]


# ----------------------------------------------------------- altın küme maske kapalıyken de yeşil


def test_every_golden_question_still_passes_with_the_pii_layer_on(db, tmp_path):
    """Gerçek kayıt, gerçek döngü, gerçek executor: PII katmanı hiçbir altın cevabı değiştirmedi."""
    executor = LocalExecutor("sqlite", db, doc.allowlist(SCHEMA), tmp_path / "audit.jsonl", SCHEMA)
    results = runner.run_eval(
        lambda: fake.for_golden(GOLDEN), executor, golden=GOLDEN, schema=SCHEMA
    )
    assert [result.outcome for result in results] == ["pass"] * len(GOLDEN)


def test_no_golden_answer_needs_a_mask(db, tmp_path):
    """Altın sorular personel/maaş verisine dokunmaz; maskelenen bir kolon çıkarsa şema değişmiştir."""
    executor = LocalExecutor("sqlite", db, doc.allowlist(SCHEMA), tmp_path / "audit.jsonl", SCHEMA)
    for line in GOLDEN:
        result = executor.execute(line["sql"], FULL, line["id"])
        assert result.error is None, f"{line['id']}: {result.error}"
        assert result.masked_columns == [], f"{line['id']} maskelendi: {result.masked_columns}"


# ----------------------------------------------------------- Run 3 ekranı README'de


@pytest.mark.parametrize("command", SUBCOMMANDS)
def test_the_readme_documents_every_new_subcommand(command):
    readme = (config.ROOT / "README.md").read_text(encoding="utf-8")
    assert f"`{command}`" in readme, f"{command} README'de yok"


@pytest.mark.parametrize("flag", FLAGS)
def test_the_readme_documents_every_new_flag(flag):
    readme = (config.ROOT / "README.md").read_text(encoding="utf-8")
    assert flag in readme, f"{flag} README'de yok"


@pytest.mark.parametrize("mark", README_MARKS)
def test_the_readme_documents_the_run_3_setup(mark):
    readme = (config.ROOT / "README.md").read_text(encoding="utf-8")
    assert mark in readme
