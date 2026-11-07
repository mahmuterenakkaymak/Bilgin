# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""``ask --mode`` ve modun söylenmediği hali (T65).

Sahte istemci rag kaydını oynatıyor, yani adımlar gerçekten diskteki indeksten ve join graphından
geçiyor; ekranda R2-14'ün adım notları durmalı: aramanın bulduğu tablolar, kaç tablo detayı, kaç
join. Tam modda ise o notlar yok — aracın cevabı uzun, ekrana sığacak olan kaç birim döndüğü.
Taze indeks yoksa rag ölçülemez: varsayılan full'a düşer ve bunu tek satırda söyler (R2-12).
"""

import json
import re
import shutil

import pytest

from bilgin import config
from bilgin.agent import fake
from bilgin.cli import main as cli
from bilgin.eval import runner
from bilgin.index.store import META_FILE
from bilgin.schema_map import build

GOLDEN = runner.load_golden()
BY_ID = {line["id"]: line for line in GOLDEN}
FALLBACK = "İndeks yok/eski; full modda çalışılıyor."


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    """Modül boyunca tek kurulum: veritabanı, sahte indeks ve audit tek tmp klasörde."""
    paths = tmp_path_factory.mktemp("cli-ask-modes")
    database = paths / "test.db"
    build.build_db(config.SEED, database, paths / "test.sql")
    cli.build_index("fake", index_dir=paths / "index")
    return database, paths / "index", paths / "audit.jsonl"


def ask(world, line, mode):
    database, index, audit = world
    return cli.ask(
        line["question"],
        fake.for_golden(GOLDEN, mode=mode),
        mode=mode,
        db_path=database,
        audit_path=audit,
        index_dir=index,
    )


# ------------------------------------------------------------------ modlar


def test_rag_shows_what_the_index_and_the_graph_found(world, capsys):
    line = BY_ID["Q04"]  # üç tablo: arama, detay ve join yolu birlikte konuşuyor

    assert ask(world, line, "rag") == 0
    out = capsys.readouterr().out

    assert "Mod: rag" in out and f"Soru: {line['question']}" in out
    assert "✓ search_schema" in out and "✓ find_join_path" in out
    assert re.search(r"→ TBL[A-Z0-9_]+, TBL[A-Z0-9_]+", out), "bulunan tablolar satırda durmalı"
    assert re.search(r"→ \d+ tablo", out)
    assert re.search(r"→ \d+ join", out)
    assert line["sql"] in out


def test_full_mode_keeps_its_steps_as_they_were(world, capsys):
    line = BY_ID["Q03"]

    assert ask(world, line, "full") == 0
    out = capsys.readouterr().out

    assert "Mod: full" in out
    assert " 1 ✓ get_schema" in out and " 3 ✓ submit_sql" in out
    assert "→" not in out, "tam modda arama aracının notu olmaz"


# ------------------------------------------------------------------ varsayılanın çözümü


def test_no_index_makes_full_the_default_with_a_note(tmp_path, capsys):
    assert cli._ask_mode(tmp_path / "yok") == "full"
    out = capsys.readouterr().out

    assert FALLBACK in out and "Traceback" not in out


def test_a_stale_index_is_not_a_rag_default(world, tmp_path, capsys):
    stale = tmp_path / "index"
    shutil.copytree(world[1], stale)
    meta = json.loads((stale / META_FILE).read_text(encoding="utf-8"))
    (stale / META_FILE).write_text(
        json.dumps({**meta, "content_hash": "bayat"}), encoding="utf-8"
    )

    assert cli._ask_mode(stale) == "full"
    assert FALLBACK in capsys.readouterr().out


def test_a_fresh_index_makes_rag_the_default(world, capsys):
    assert cli._ask_mode(world[1]) == "rag"
    assert "İndeks" not in capsys.readouterr().out


def test_main_passes_the_chosen_mode_on(monkeypatch):
    seen = {}
    monkeypatch.setattr(cli, "ask", lambda **kwargs: seen.update(kwargs) or 0)

    assert cli.main(["ask", "Geçen ayın cirosu?", "--llm", "fake", "--mode", "rag"]) == 0
    assert seen["mode"] == "rag" and isinstance(seen["llm"], fake.FakeLLM)
