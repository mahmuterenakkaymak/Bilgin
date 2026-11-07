# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""``build-index``: aramanın girdisinin kurulumu ve ölü embedding sunucusu.

İndeks iki şeyin toplamı: doküman metni ve onun vektörü. Ekran bu yüzden kaç doküman yazıldığını
(koleksiyon koleksiyon), vektörlerin kimden ve kaç genişlikten geldiğini, içeriğin imzasını ve
süreyi söyler; imza ``ask`` tarafının bayat indeksi reddetmesinin kendisidir. Ölü bir embedding
sunucusu ise iz dökümü değil hangi adresin patladığını ve ne deneneceğini söylemeli, üstelik
yarım bir indeks de bırakmamalı.
"""

import json
import socket

from nl2sql import config
from nl2sql.cli import main as cli
from nl2sql.index import store
from nl2sql.schema_map import doc
from nl2sql.schema_map.rules import load_rules


def closed_port() -> int:
    """Boş bir port al, bırak: bağlananın reddedileceği bir adresin adresi olur."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


# ------------------------------------------------------------------ kurulum


def test_fake_embedder_builds_the_index(tmp_path, capsys):
    index_dir = tmp_path / "index"
    code = cli.build_index("fake", index_dir=index_dir)
    out = capsys.readouterr().out

    assert code == 0
    assert (index_dir / "docs.json").exists() and (index_dir / "vectors.json").exists()

    schema = doc.load_schema()
    rules = load_rules()
    meta = json.loads((index_dir / "meta.json").read_text(encoding="utf-8"))
    assert meta["content_hash"] == store.content_hash(schema, rules)
    assert meta["embedder"] == f"fake:{config.FAKE_EMBED_DIM}"
    assert meta["dim"] == config.FAKE_EMBED_DIM
    assert meta["counts"] == {
        "tables": len(schema["tables"]),
        "rules": len(rules),
        "summaries": len(schema["tables"]),  # one summary per table since T190; Updated 2026-10-24 with Eren's approval (R5-20 added the summaries collection).
        "examples": 0,
    }

    assert f"tables {len(schema['tables'])}" in out and f"rules {len(rules)}" in out
    assert f"Embedder: fake:{config.FAKE_EMBED_DIM} (dim {config.FAKE_EMBED_DIM})" in out
    assert f"İmza: {meta['content_hash'][:12]}" in out
    assert "Süre:" in out and f"İndeks: {index_dir}" in out


# ------------------------------------------------------------------ ölü sunucu


def test_dead_embedding_server_names_the_url(tmp_path, monkeypatch, capsys):
    url = f"http://127.0.0.1:{closed_port()}/v1"
    monkeypatch.setenv("NL2SQL_EMBED_BASE_URL", url)
    index_dir = tmp_path / "index"

    code = cli.build_index("openai", index_dir=index_dir)
    out = capsys.readouterr().out

    assert code == 3
    assert url in out and "NL2SQL_EMBED_BASE_URL" in out and "Traceback" not in out
    assert out.count(url) == 1, "adres iki kere saydırılmamalı"
    assert "Dokümanlar:" not in out
    assert not index_dir.exists(), "vektörsüz bir indeks bırakılmamalı"


# ------------------------------------------------------------------ söz dizimi


def test_main_routes_build_index(monkeypatch):
    seen = {}

    def record(**kwargs):
        seen.update(kwargs)
        return 0

    monkeypatch.setattr(cli, "build_index", record)
    assert cli.main(["build-index", "--embed", "fake"]) == 0
    assert seen == {"embed": "fake"}


def test_build_index_defaults_to_the_real_embedder(monkeypatch):
    seen = {}

    def record(**kwargs):
        seen.update(kwargs)
        return 0

    monkeypatch.setattr(cli, "build_index", record)
    assert cli.main(["build-index"]) == 0
    assert seen["embed"] == "openai"
