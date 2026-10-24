"""T135: M11 entegrasyonu — iki dünya, aynı dört kapı.

Elle yapılmış sahte parça yok: dünya her kümenin kendi ``builder``ı, kapı gerçek
``LocalExecutor``, indeks gerçek ``build_documents`` + ``FakeEmbedder`` + ``FileStore``, ölçüm gerçek
``evaluate`` (gerçek döngü, gerçek sahte kayıt), ekran gerçek alt süreç. Fazın iddiası dört cümle:
her kümenin altın SQL'i kendi Python doğrulusundan 2 haneye indirilmiş haliyle farksız; bir kümenin
indeksi öbürünün için yüklenmiyor (R4-8); mini kendi ``rag`` ölçümünde soru başına pass alıyor ve
raporunda kendi dünyasının dışına çıkmıyor; ``build-db --dataset`` depo kökünden hangi dünyayla
çalıştığını ilk satırda söylüyor.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from nl2sql import config
from nl2sql.cli import main as cli
from nl2sql.datasets import load_dataset
from nl2sql.engine.executor import LocalExecutor
from nl2sql.engine.result import Budget, Result
from nl2sql.eval import compare
from nl2sql.index.docs import build_documents
from nl2sql.index.embed import FakeEmbedder
from nl2sql.index.search import load_search
from nl2sql.index.store import ForeignIndexError, FileStore, content_hash
from nl2sql.schema_map import doc

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "datasets"
DATASETS = (load_dataset("synthetic_erp"), load_dataset("mini", root=FIXTURE_ROOT))
BY_NAME = {dataset.name: dataset for dataset in DATASETS}
REFERENCES = {dataset.name: dataset.references() for dataset in DATASETS}
# Eval karşılaştırma bütçesi: ne altının ne doğrunun satırı kesilmesin (PLAN Decision 8).
COMPARE = Budget(max_rows=config.COMPARE_MAX_ROWS)
CASES = [(dataset, line) for dataset in DATASETS for line in dataset.golden()]
CASE_IDS = [f"{dataset.name}:{line['id']}" for dataset, line in CASES]
PAIRS = [("synthetic_erp", "mini"), ("mini", "synthetic_erp")]


def truth(rows: list[tuple]) -> Result:
    """Python doğrusu, eval'in kıyaslayıcısının gördüğü biçimde: kolon adı yok, değer var."""
    return Result(
        columns=[str(index) for index in range(len(rows[0]) if rows else 0)],
        rows=[tuple(row) for row in rows],
        row_count=len(rows),
    )


@pytest.fixture(scope="module")
def worlds(tmp_path_factory):
    """Küme başına kendi builder'ının kurduğu dosya ve ona bakan tek gerçek kapı."""
    root = tmp_path_factory.mktemp("m11")
    doors = {}
    for dataset in DATASETS:
        folder = root / dataset.name
        database = folder / f"{dataset.name}.db"
        dataset.build_db(db_path=database, sql_path=folder / f"{dataset.name}.sql")
        doors[dataset.name] = LocalExecutor(
            "sqlite",
            database,
            doc.allowlist(dataset.schema()),
            folder / "audit.jsonl",
            dataset.schema(),
        )
    return doors


@pytest.fixture(scope="module")
def rows():
    """Altın doğruların baktığı satırlar: aynı tohumun üreticisi, kurulu dosyaya hiç dokunmadan."""
    return {dataset.name: dataset.generate() for dataset in DATASETS}


@pytest.fixture(scope="module")
def indexes(tmp_path_factory):
    """Küme başına kendi indeks klasörü: gerçek dokümanlar, sahte vektörler, meta.dataset (R4-8)."""
    root = tmp_path_factory.mktemp("m11-index")
    directories = {}
    for dataset in DATASETS:
        schema, rules = dataset.schema(), dataset.rules()
        documents = build_documents(schema, rules)
        embedder = FakeEmbedder()
        index = root / dataset.name
        FileStore(index).save(
            documents,
            embedder.embed([item.text for item in documents]),
            {
                "content_hash": content_hash(schema, rules),
                "embedder": embedder.id,
                "dim": embedder.dim,
                "dataset": dataset.name,
            },
        )
        directories[dataset.name] = index
    return directories


# ------------------------------------------------- altın SQL == Python doğrulusu, her iki dünyada


@pytest.mark.parametrize("case", CASES, ids=CASE_IDS)
def test_a_golden_sql_answers_exactly_what_its_own_reference_computes(case, worlds, rows):
    dataset, line = case
    result = worlds[dataset.name].execute(line["sql"], COMPARE, line["id"])
    assert result.error is None, f"{line['id']}: {result.error}"
    assert result.rows, f"{line['id']} boş döndü; soru hiçbir şey ölçmüyor"

    expected = truth(REFERENCES[dataset.name][line["id"]](rows[dataset.name]))
    verdict = compare.compare(expected, result, line["ordered"])
    assert verdict.match, f"{line['id']} SQL sonucu {dataset.name} doğrulundan farklı: {verdict.reason}"
    assert verdict.extra_columns == []


# ------------------------------------------------- indeksin sahibi var (R4-8)


def test_an_index_loads_for_the_dataset_it_was_built_for(indexes):
    for dataset in DATASETS:
        schema, rules = dataset.schema(), dataset.rules()
        search = load_search(indexes[dataset.name], schema, rules, dataset=dataset.name)
        tables = {table["name"] for table in dataset.schema()["tables"]}

        hits = search.search(dataset.golden()[0]["question"], k=3)

        assert hits, f"{dataset.name} kendi indeksinden tablo çıkaramadı"
        assert all(hit.title in tables for hit in hits), "cevap başka bir dünyanın tablosu"


@pytest.mark.parametrize(("built", "wanted"), PAIRS)
def test_an_index_is_refused_for_the_other_dataset(indexes, built, wanted):
    other = BY_NAME[wanted]

    with pytest.raises(ForeignIndexError) as failure:
        load_search(indexes[built], other.schema(), other.rules(), dataset=wanted)

    assert f"İndeks başka veri kümesine ait: {built} (istenen {wanted})" in str(failure.value)


# ------------------------------------------------- mini kendi rag ölçümünde yeşil


def test_mini_scores_full_marks_in_rag_through_the_real_loop(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("NL2SQL_DATASETS_DIR", str(FIXTURE_ROOT))
    dataset = BY_NAME["mini"]
    database = tmp_path / "mini.db"
    dataset.build_db(db_path=database, sql_path=tmp_path / "mini.sql")
    index = tmp_path / "index"
    assert cli.build_index("fake", index_dir=index, dataset="mini") == 0
    capsys.readouterr()

    code = cli.evaluate(
        cli.make_client("fake", "rag", dataset),
        mode="rag",
        db_path=database,
        audit_path=tmp_path / "audit.jsonl",
        out_dir=tmp_path / "eval_out" / "rag",
        index_dir=index,
        dataset="mini",
    )
    out = capsys.readouterr().out
    report = json.loads(
        (tmp_path / "eval_out" / "rag" / "latest" / "report.json").read_text(encoding="utf-8")
    )

    assert code == 0
    assert [question["outcome"] for question in report["questions"]] == ["pass"] * len(
        dataset.golden()
    )
    assert f"Skor: {len(dataset.golden())}/{len(dataset.golden())}" in out
    assert report["dataset"] == "mini"
    # Ölçüm mini'nin dünyasında kaldı: Run 1 şemasının bir tablo adı bile raporun SQL'ine sızmamalı.
    assert all("TBLSTSABIT" not in question["sql"] for question in report["questions"])


# ------------------------------------------------- ekran: küme söylenince dünya söylenir


def test_build_db_from_the_project_root_names_the_dataset_it_built():
    result = subprocess.run(
        [sys.executable, "-m", "nl2sql", "build-db", "--dataset", "synthetic_erp"],
        cwd=config.ROOT,
        capture_output=True,
        encoding="utf-8",
        env={**os.environ, "NL2SQL_BACKEND": "sqlite", "PYTHONIOENCODING": "utf-8"},
    )
    dataset = BY_NAME["synthetic_erp"]

    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.startswith(
        f"Veri kümesi: {dataset.display_name} ({dataset.name})"
    ), "hangi dünyayla çalışıldığı ilk satırda okunmalı"
    assert str(dataset.db_path) in result.stdout
