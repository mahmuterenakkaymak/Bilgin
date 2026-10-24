"""R4-8: bir indeks bir veri kümesinindir - mini kümesi üzerinde.

İmza içeriği, `dataset` ise kime ait olduğunu söyler: `mini` için vektörlenmiş bir indeks
`synthetic_erp`nin yerine yüklenirse arama başka bir dünyanın tablolarını döndürür ve bunu modelin
hatası gibi gösterir. Reddin mesajı iki tarafı da ve doğru komutu adıyla söylemeli; sınıf
`StaleIndexError`ın alt sınıfı kalmalı, çünkü CLI zaten bayatlığı yakalayıp yol gösteriyor.
Mini kümesi seçildi, çünkü gerçek şemanın yanı sıra ikinci bir küme ancak onunla var.
"""

import json
from pathlib import Path

import pytest

from nl2sql import config
from nl2sql.cli import main as cli
from nl2sql.datasets import load_dataset
from nl2sql.index.docs import build_documents
from nl2sql.index.embed import FakeEmbedder
from nl2sql.index.search import load_search
from nl2sql.index.store import (
    META_FILE,
    FileStore,
    ForeignIndexError,
    StaleIndexError,
    content_hash,
)

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "datasets"
DATASET = load_dataset("mini", root=FIXTURE_ROOT)
SCHEMA = DATASET.schema()
RULES = DATASET.rules()
DIGEST = content_hash(SCHEMA, RULES)


def save(tmp_path, meta):
    """Mini şemasının gerçek dokümanlarıyla indeks yazar; meta olduğu gibi geçer."""
    docs = build_documents(SCHEMA, RULES)
    store = FileStore(tmp_path / "index")
    store.save(docs, FakeEmbedder().embed([item.text for item in docs]), meta)
    return store


def build(tmp_path, **kwargs):
    """Gerçek üretici: build-index, mini şeması ve verilen veri kümesi adı üzerinde."""
    index_dir = tmp_path / "index"
    code = cli.build_index(
        "fake",
        index_dir=index_dir,
        schema_path=DATASET.schema_path,
        rules_path=DATASET.rules_path,
        **kwargs,
    )
    assert code == 0
    return json.loads((index_dir / META_FILE).read_text(encoding="utf-8"))


# ------------------------------------------------------------------ yükleyici


def test_its_own_dataset_loads_the_index(tmp_path):
    store = save(tmp_path, {"content_hash": DIGEST, "embedder": "fake", "dataset": "mini"})

    assert store.load_checked(DIGEST, dataset="mini").meta["dataset"] == "mini"


def test_another_dataset_is_refused_by_name(tmp_path):
    store = save(tmp_path, {"content_hash": DIGEST, "embedder": "fake", "dataset": "mini"})

    # CLI'ın yakaladığı tip StaleIndexError; reddin onu da uyandırması yeter.
    with pytest.raises(StaleIndexError) as exc:
        store.load_checked(DIGEST, dataset="synthetic_erp")

    assert isinstance(exc.value, ForeignIndexError)
    message = str(exc.value)
    assert "mini" in message and "synthetic_erp" in message
    assert "build-index --dataset synthetic_erp" in message


def test_meta_without_the_key_is_the_old_single_dataset(tmp_path):
    store = save(tmp_path, {"content_hash": DIGEST, "embedder": "fake"})

    assert store.load_checked(DIGEST, dataset="synthetic_erp").meta.get("dataset") is None


def test_a_foreign_index_is_still_read_for_its_own_dataset(tmp_path):
    save(tmp_path, {"content_hash": DIGEST, "embedder": "fake", "dataset": "mini"})

    assert load_search(tmp_path / "index", SCHEMA, RULES, dataset="mini").search("sipariş")
    with pytest.raises(ForeignIndexError):
        load_search(tmp_path / "index", SCHEMA, RULES, dataset="synthetic_erp")


# ------------------------------------------------------------------ üretici


def test_build_index_writes_the_dataset_it_was_told(tmp_path):
    assert build(tmp_path, dataset_name="mini")["dataset"] == "mini"


def test_build_index_without_a_dataset_names_the_default(tmp_path):
    assert build(tmp_path)["dataset"] == config.DEFAULT_DATASET
