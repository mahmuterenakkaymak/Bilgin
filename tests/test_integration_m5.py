"""T57: M5 entegrasyonu — diske yazılmış gerçek indeks, gerçek 40 altın soruyla aranır.

Zincirin halkalarının hiçbiri taklit değil: gerçek schema.json + rules.json -> dokümanlar ->
FakeEmbedder -> FileStore -> load_search -> run_retrieval. Sahte olan tek şey ağı olmayan embedder;
ölçütün kendisi (recall@k) altın satırdaki gerçek tablo listesi üzerinden hesaplanıyor. Aynı zincir
üzerinde iki sözleşme daha burada birleşiyor: içerik imzası kıpırdarsa indeks yüklenmez (bayatlık
sessiz tolere edilmez) ve altın sorunun dili aranabilir metne sızmaz.
"""

import json

import pytest

from nl2sql import config
from nl2sql.eval.retrieval import run_retrieval
from nl2sql.eval.runner import load_golden
from nl2sql.graph.graph import build_graph
from nl2sql.graph.profile import load_profile
from nl2sql.index.docs import build_documents, leaks
from nl2sql.index.embed import FakeEmbedder
from nl2sql.index.search import METHODS, load_search
from nl2sql.index.store import FileStore, StaleIndexError, content_hash
from nl2sql.schema_map.doc import load_schema
from nl2sql.schema_map.rules import load_rules
from test_graph_path import _golden_joins, _sides

IDS = [f"Q{i:02d}" for i in range(1, 41)]
SCHEMA = load_schema()
RULES = load_rules()
GOLDEN = load_golden()
BY_ID = {line["id"]: line for line in GOLDEN}
MULTI_JOIN = [line for line in GOLDEN if "multi_join" in line["tags"]]
EMBEDDER = FakeEmbedder()
DOCS = build_documents(SCHEMA, RULES)


@pytest.fixture(scope="module")
def index_dir(tmp_path_factory):
    """`build-index`'in ürettiği üç dosya: gerçek şema, gerçek kurallar, gerçek bir dizin."""
    directory = tmp_path_factory.mktemp("m5")
    FileStore(directory).save(
        DOCS,
        EMBEDDER.embed([doc.text for doc in DOCS]),
        {
            "content_hash": content_hash(SCHEMA, RULES),
            "embedder": EMBEDDER.id,
            "dim": EMBEDDER.dim,
        },
    )
    return directory


# ------------------------------------------------------- diskteki indeks -> ölçümün kendisi


def test_an_edited_rule_definition_makes_the_stored_index_stale(index_dir, tmp_path):
    """Tanım değişince aynı dosyalar başka içeriğin indeksi sayılır; yüklemek yerine patlar (R2-9)."""
    data = json.loads(config.RULES_PATH.read_text(encoding="utf-8"))
    data["rules"][0]["definition"] += " (elle değiştirilmiş tanım)"
    edited = tmp_path / "rules.json"
    edited.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(StaleIndexError, match="build-index"):
        load_search(index_dir, SCHEMA, load_rules(edited))


# ------------------------------------------------------- altın soru aranabilir metne sızmaz


def test_no_golden_question_leaks_into_the_searchable_text():
    assert leaks(DOCS, GOLDEN) == []


# ------------------------------------------------------- join graphı golden joinleri taşıyor


