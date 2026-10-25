"""R5-20: tablo özeti üç girdinin kopyasıdır - uydurduğu bir cümle yok, sızdırdığı bir kolon yok.

Özet, tablo dokümanının yanına yazılan ikinci bir ses: açıklama, anahtar kolonlar, işleyen kural
terimleri ve join graphındaki komşular. Dört iddia var: her tablonun tam bir özeti vardır, hiçbir
özet `deny` kolonun adını taşımaz (R4-7 - adını gören model onu sorgusuna da yazar), aynı girdi aynı
metni verir (iki koşumun indeksi ancak o zaman kıyaslanabilir), ve hiçbir özet altın soruyu
tekrar etmez (R2-16 - kaçaklı retrieval'ın skoru yalandır).
"""

import pytest

from nl2sql.cli import main as cli
from nl2sql.datasets import load_dataset
from nl2sql.graph.graph import build_graph
from nl2sql.graph.profile import load_profile
from nl2sql.index.docs import leaks
from nl2sql.index.store import FileStore
from nl2sql.index.summaries import table_summaries

DATASETS = ("wwi", "wwi")


def world(name: str):
    """Kümenin gerçek üç girdisi ve onlardan türeyen özetler: şema, kurallar, join graphı."""
    ds = load_dataset(name)
    schema = ds.schema()
    graph = build_graph(schema, load_profile(ds.profile_path))
    return ds, schema, table_summaries(schema, ds.rules(), graph)


# ------------------------------------------------------------------ biçim


@pytest.mark.parametrize("name", DATASETS)
def test_one_summary_per_table_in_schema_order(name):
    _, schema, summaries = world(name)

    assert [doc.id for doc in summaries] == [f"summary:{t['name']}" for t in schema["tables"]]
    assert all(doc.collection == "summaries" for doc in summaries)
    assert all(doc.title == doc.meta["table"] for doc in summaries)
    assert all(set(doc.meta) == {"table"} for doc in summaries)


@pytest.mark.parametrize("name", DATASETS)
def test_the_summary_reads_like_the_template(name):
    _, schema, summaries = world(name)
    table = next(t for t in schema["tables"] if t["description"] and t["module"])
    doc = next(doc for doc in summaries if doc.id == f"summary:{table['name']}")

    assert doc.text.startswith(f"Tablo {table['name']} ({table['module']}): {table['description']}")


# ------------------------------------------------------------------ yasaklar


def test_a_deny_column_never_appears_in_a_summary():
    _, schema, summaries = world("wwi")
    denied = {
        column["name"]
        for table in schema["tables"]
        for column in table["columns"]
        if column.get("deny")
    }

    assert {"HashedPassword", "Photo"} <= denied
    assert [name for name in denied for doc in summaries if name in doc.text] == []


@pytest.mark.parametrize("name", DATASETS)
def test_no_summary_repeats_a_golden_question(name):
    ds, _, summaries = world(name)

    assert leaks(summaries, ds.golden()) == []


# ------------------------------------------------------------------ determinizm


@pytest.mark.parametrize("name", DATASETS)
def test_the_same_input_gives_the_same_text(name):
    first = [(doc.id, doc.text, doc.meta) for doc in world(name)[2]]
    second = [(doc.id, doc.text, doc.meta) for doc in world(name)[2]]

    assert first == second


# ------------------------------------------------------------------ build-index


@pytest.mark.parametrize("name", DATASETS)
def test_build_index_stores_the_summaries_next_to_the_other_docs(name, tmp_path, capsys):
    index_dir = tmp_path / name
    schema = load_dataset(name).schema()

    assert cli.build_index("fake", index_dir=index_dir, dataset=name) == 0

    stored = FileStore(index_dir).load()
    summaries = [doc for doc in stored.docs if doc.collection == "summaries"]
    assert [doc.id for doc in summaries] == [f"summary:{t['name']}" for t in schema["tables"]]
    assert len(stored.vectors) == len(stored.docs), "özetler de vektörlendi"
    assert stored.meta["counts"]["summaries"] == len(schema["tables"])
    assert f"summaries {len(schema['tables'])}" in capsys.readouterr().out
