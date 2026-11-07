# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""R2-9: indeks ya günceldir ya da hiç yüklenmemiş sayılır.

Bayat bir indeksle arama yapmak, şemanın göremediği bir tabloyu modelin hatası gibi gösterir;
bu yüzden imza uyuşmazlığı sessiz geçmez. Sayı uyuşmazlığı da aynı şekilde ele alınır: vektörler
dokümanlarla aynı sırayı taşıdığı sürece anlamlıdır.
"""

import copy
import json

import pytest

from nl2sql.index.docs import Doc, build_documents
from nl2sql.index.store import (
    DOCS_FILE,
    META_FILE,
    VECTORS_FILE,
    FileStore,
    MissingIndexError,
    StaleIndexError,
    VectorStore,
    content_hash,
)
from nl2sql.schema_map.doc import load_schema
from nl2sql.schema_map.rules import load_rules

SCHEMA = load_schema()
RULES = load_rules()

DOCS = [
    Doc(id="table:TBLSTHAR", collection="tables", title="TBLSTHAR", text="stok hareketleri"),
    Doc(id="rule:ciro", collection="rules", title="Ciro", text="KDV hariç", meta={"term": "Ciro"}),
]
VECTORS = [[1.0, 0.0], [0.0, 1.0]]
META = {"content_hash": "abc", "embedder": "fake:256", "dim": 2}


def test_round_trip(tmp_path):
    store = FileStore(tmp_path / "index")
    store.save(DOCS, VECTORS, META)

    index = store.load()

    assert index.docs == DOCS
    assert index.vectors == VECTORS
    assert index.meta["content_hash"] == "abc"
    assert index.meta["embedder"] == "fake:256"
    # summaries key since T190; Updated 2026-10-24 with Eren's approval (R5-20 added the summaries collection).
    assert index.meta["counts"] == {"tables": 1, "rules": 1, "summaries": 0, "examples": 0}
    assert index.meta["built_at"]


def test_save_leaves_no_temp_files(tmp_path):
    store = FileStore(tmp_path / "index")
    store.save(DOCS, VECTORS, META)

    assert sorted(path.name for path in (tmp_path / "index").iterdir()) == [
        DOCS_FILE,
        META_FILE,
        VECTORS_FILE,
    ]


def test_vectors_are_reloaded_as_floats(tmp_path):
    store = FileStore(tmp_path / "index")
    store.save(DOCS, [[1, 2], [3, 4]], META)

    index = store.load()

    assert index.vectors == [[1.0, 2.0], [3.0, 4.0]]
    assert all(isinstance(v, float) for row in index.vectors for v in row)


def test_changed_rules_raise_stale(tmp_path):
    store = FileStore(tmp_path / "index")
    store.save(DOCS, VECTORS, {"content_hash": content_hash(SCHEMA, RULES)})

    changed = copy.deepcopy(RULES)
    changed[0]["definition"] += " (güncellendi)"

    with pytest.raises(StaleIndexError) as exc:
        store.load_checked(content_hash(SCHEMA, changed))
    assert "build-index" in str(exc.value)


def test_load_checked_accepts_matching_hash(tmp_path):
    store = FileStore(tmp_path / "index")
    digest = content_hash(SCHEMA, RULES)
    store.save(build_documents(SCHEMA, RULES), [[] for _ in SCHEMA["tables"]] + [[] for _ in RULES], {"content_hash": digest})

    assert store.load_checked(digest).meta["content_hash"] == digest


def test_missing_directory_raises_missing(tmp_path):
    store = FileStore(tmp_path / "nope")

    with pytest.raises(MissingIndexError) as exc:
        store.load_checked("anything")
    assert "build-index" in str(exc.value)


def test_missing_single_file_raises_missing(tmp_path):
    store = FileStore(tmp_path / "index")
    store.save(DOCS, VECTORS, META)
    (tmp_path / "index" / VECTORS_FILE).unlink()

    with pytest.raises(MissingIndexError):
        store.load()


def test_vector_count_mismatch_rejected_on_save(tmp_path):
    store = FileStore(tmp_path / "index")

    with pytest.raises(StaleIndexError):
        store.save(DOCS, [VECTORS[0]], META)
    assert not (tmp_path / "index" / DOCS_FILE).exists()


def test_vector_count_mismatch_on_disk_rejected(tmp_path):
    directory = tmp_path / "index"
    FileStore(directory).save(DOCS, VECTORS, META)
    with open(directory / VECTORS_FILE, "w", encoding="utf-8") as handle:
        json.dump([[1.0, 0.0]], handle)

    with pytest.raises(StaleIndexError):
        FileStore(directory).load()


def test_content_hash_is_canonical():
    shuffled = {"tables": [dict(reversed(list(table.items()))) for table in SCHEMA["tables"]]}
    assert content_hash(shuffled, RULES) == content_hash(SCHEMA, RULES)
    assert content_hash(SCHEMA, []) != content_hash(SCHEMA, RULES)


def test_filestore_satisfies_protocol(tmp_path):
    assert isinstance(FileStore(tmp_path), VectorStore)
