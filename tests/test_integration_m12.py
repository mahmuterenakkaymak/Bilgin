# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""T145: M12 entegrasyonu — wwi dünyası baştan sona, elle yapılmış tek parça olmadan.

Dünya gerçek ``load_dataset("wwi")``nın kendi builder'ı, kapı gerçek ``LocalExecutor``, indeks gerçek
``cli.build_index`` (FakeEmbedder ile), ölçüm gerçek ``cli.evaluate`` (gerçek döngü, gerçek sahte
kayıt) ve geri çağırma gerçek ``cli.eval_retrieval``. Fazın iddiası dört cümle: wwi'nin her altın
SQL'i kendi Python doğrulusundan 2 haneye indirilmiş haliyle farksız; ``full_rules`` ve ``rag``
ölçümlerinin her sorusu gerçek döngüde pass alır ve raporu hangi dünyayı ölçtüğünü söyler; geri
çağırma raporu wwi'nin her sorusu için bir satır taşır; sentetik dünyanın indeksi wwi için
yüklenmez (R4-8).
"""

import json

import pytest

from nl2sql import datasets
from nl2sql.cli import main as cli
from nl2sql.datasets import load_dataset
from nl2sql.engine.executor import LocalExecutor
from nl2sql.engine.result import Result
from nl2sql.eval import compare
from nl2sql.eval.runner import COMPARE
from nl2sql.index.search import load_search
from nl2sql.index.store import ForeignIndexError
from nl2sql.schema_map import doc

WWI = load_dataset("wwi")
GOLDEN = WWI.golden()
ROWS = WWI.generate()
REFS = WWI.references()
CASE_IDS = [line["id"] for line in GOLDEN]
MODES = ("full_rules", "rag")


def truth(rows: list[tuple]) -> Result:
    """Python doğrusu, eval'in kıyaslayıcısının gördüğü biçimde: kolon adı yok, değer var."""
    return Result(
        columns=[str(index) for index in range(len(rows[0]) if rows else 0)],
        rows=[tuple(row) for row in rows],
        row_count=len(rows),
    )


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    """wwi builder'ının kurduğu dosya ve ona bakan tek gerçek kapı (ham doğrulu, pii maskesiz)."""
    folder = tmp_path_factory.mktemp("m12")
    database = folder / "wwi.db"
    WWI.build_db(db_path=database, sql_path=folder / "wwi.sql")
    door = LocalExecutor(
        "sqlite",
        database,
        doc.allowlist(WWI.schema()),
        folder / "audit.jsonl",
    )
    return database, door


@pytest.fixture
def indexes(tmp_path, capsys):
    """wwi'nin kendi indeksi ve reddedilecek sentetik indeks, ikisi de tmp'de (FakeEmbedder)."""
    root = tmp_path / "index"
    assert cli.build_index("fake", index_dir=root / "wwi", dataset="wwi") == 0
    assert cli.build_index("fake", index_dir=root / "synthetic_erp") == 0
    capsys.readouterr()
    return root / "wwi", root / "synthetic_erp"


# ------------------------------------------------- altın SQL == Python doğrulusu, wwi dünyasında


@pytest.mark.parametrize("line", GOLDEN, ids=CASE_IDS)
def test_golden_sql_answers_exactly_what_the_reference_computes(line, world):
    _, door = world
    result = door.execute(line["sql"], COMPARE, line["id"])
    assert result.error is None, f"{line['id']}: {result.error}"
    assert result.rows, f"{line['id']} boş döndü; soru hiçbir şey ölçmüyor"

    verdict = compare.compare(truth(REFS[line["id"]](ROWS)), result, line["ordered"])
    assert verdict.match, f"{line['id']} SQL sonucu wwi doğrulundan farklı: {verdict.reason}"
    assert verdict.extra_columns == []


# ------------------------------------------------- ölçümün her sorusu gerçek döngüde pass


@pytest.mark.parametrize("mode", MODES)
def test_every_wwi_question_passes_in_its_own_mode(mode, indexes, tmp_path, capsys):
    wwi_index, _ = indexes
    database = tmp_path / "wwi.db"
    WWI.build_db(db_path=database, sql_path=tmp_path / "wwi.sql")
    out_dir = tmp_path / "eval_out" / mode

    code = cli.evaluate(
        cli.make_client("fake", mode, WWI),
        mode=mode,
        db_path=database,
        audit_path=tmp_path / "audit.jsonl",
        out_dir=out_dir,
        index_dir=wwi_index,
        dataset="wwi",
    )
    out = capsys.readouterr().out
    report = json.loads((out_dir / "latest" / "report.json").read_text(encoding="utf-8"))

    assert code == 0
    assert [question["outcome"] for question in report["questions"]] == ["pass"] * len(GOLDEN)
    assert [question["id"] for question in report["questions"]] == CASE_IDS
    assert f"Skor: {len(GOLDEN)}/{len(GOLDEN)}" in out
    assert report["dataset"] == "wwi"


# ------------------------------------------------- geri çağırma her wwi sorusunu ölçer


def test_retrieval_report_has_a_row_for_every_wwi_question(tmp_path, capsys):
    out_dir = tmp_path / "retrieval"

    assert cli.eval_retrieval("fake", out_dir=out_dir, dataset="wwi") == 0
    capsys.readouterr()

    report = json.loads((out_dir / "latest" / "report.json").read_text(encoding="utf-8"))
    assert [question["id"] for question in report["questions"]] == CASE_IDS


# ------------------------------------------------- sentetik indeks wwi için yüklenmez (R4-8)


def test_the_synthetic_index_is_refused_for_wwi(indexes):
    _, synthetic_index = indexes

    with pytest.raises(ForeignIndexError) as failure:
        load_search(synthetic_index, WWI.schema(), WWI.rules(), dataset="wwi")

    assert "İndeks başka veri kümesine ait: synthetic_erp (istenen wwi)" in str(failure.value)


# ------------------------------------------------- iki dünya da kayıtlı


def test_both_datasets_are_listed():
    assert {"synthetic_erp", "wwi"} <= set(datasets.list_datasets())
