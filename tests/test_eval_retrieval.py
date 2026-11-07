# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""T56: geri çağırma ölçütünün aritmetiği, raporu ve ekranı.

Ölçüm aracının kendisi ölçülmeli: recall@k elle doğrulanmadıysa "RAG kazandı" satırının bir
temeli kalmaz. Geri çağırma burada gerçek indeks üzerinde değil, elle yazılmış sıralamalar
üzerinde hesaplanıyor; böylece görülen 0,5'in küme mi bölme mi hatası olduğu tartışması bitiyor.
Ekran ve rapor aynı sayıdan çıktığı için testlerin yarısı da aynı iki yere bakıyor.
"""

import json
import socket
from datetime import datetime
from types import SimpleNamespace

from nl2sql import config
from nl2sql.cli import main as cli
from nl2sql.eval import retrieval, runner
from nl2sql.index.search import METHODS, Hit

GOLDEN = [
    {"id": "Q01", "question": "soru bir", "tags": ["x"], "requires_tables": ["TABLO_A", "TABLO_B"]},
    {"id": "Q02", "question": "soru iki", "tags": ["x", "y"], "requires_tables": ["TABLO_C"]},
]

# Elle yazılmış sıralamalar: Q01'de bm25 bir tabloyu kaçırır, dense ikisini de; Q02'de dense boş döner.
ORDER = {
    "hybrid": {"soru bir": ["TABLO_A", "TABLO_B"], "soru iki": ["TABLO_C"]},
    "bm25": {"soru bir": ["TABLO_A", "TABLO_D"], "soru iki": ["TABLO_C"]},
    "dense": {"soru bir": ["TABLO_D"], "soru iki": []},
}


class StubSearch:
    """Elle yazılmış sıralamaları döndüren arama; çağıranı (koleksiyon, yöntem, k) diye kaydeder."""

    def __init__(self, order: dict[str, dict[str, list[str]]]) -> None:
        self.order = order
        self.calls: list[tuple[str, str, int]] = []
        self.embedder = SimpleNamespace(id="stub:1")

    def search(self, query, collection="tables", k=config.SEARCH_K, method="hybrid", rewrite=False):
        self.calls.append((collection, method, k))
        tables = self.order.get(method, {}).get(query, [])[:k]
        return [
            Hit(doc_id=f"table:{name}", title=name, score=1.0 / rank, rank=rank)
            for rank, name in enumerate(tables, start=1)
        ]


def closed_port() -> int:
    """Boş bir port al, bırak: bağlananın reddedileceği bir adresin adresi olur."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


# ------------------------------------------------------------------ aritmetik


def test_recall_per_question_means_and_tags():
    report = retrieval.run_retrieval(StubSearch(ORDER), GOLDEN, k=3)

    assert report["k"] == 3 and report["embedder"] == "stub:1"
    first, second = report["questions"]
    assert first["id"] == "Q01" and first["requires"] == ["TABLO_A", "TABLO_B"]
    assert (first["hybrid"], first["bm25"], first["dense"]) == (1.0, 0.5, 0.0)
    assert (second["hybrid"], second["bm25"], second["dense"]) == (1.0, 1.0, 0.0)
    assert first["missing"] == {"hybrid": [], "bm25": ["TABLO_B"], "dense": ["TABLO_A", "TABLO_B"]}
    assert second["missing"] == {"hybrid": [], "bm25": [], "dense": ["TABLO_C"]}
    assert report["mean"] == {"hybrid": 1.0, "bm25": 0.75, "dense": 0.0}
    assert report["by_tag"] == {
        "x": {"hybrid": 1.0, "bm25": 0.75, "dense": 0.0},
        "y": {"hybrid": 1.0, "bm25": 1.0, "dense": 0.0},
    }


def test_every_method_is_asked_for_tables_at_the_given_k():
    search = StubSearch(ORDER)
    retrieval.run_retrieval(search, GOLDEN, k=2)
    assert search.calls == [
        ("tables", method, 2) for _ in GOLDEN for method in METHODS
    ]


def test_question_without_required_tables_is_not_a_zero():
    report = retrieval.run_retrieval(
        StubSearch({method: {} for method in METHODS}),
        [{"id": "Q99", "question": "tablosuz soru"}],
        k=5,
    )
    question = report["questions"][0]
    assert question["tags"] == [] and question["requires"] == []
    assert all(question[method] == 1.0 for method in METHODS)
    assert all(question["missing"][method] == [] for method in METHODS)
    assert report["mean"] == {method: 1.0 for method in METHODS}
    assert report["by_tag"] == {}


# ------------------------------------------------------------------ rapor


def test_write_retrieval_writes_the_run_and_latest(tmp_path):
    report = retrieval.run_retrieval(StubSearch(ORDER), GOLDEN, k=3)
    out = tmp_path / "retrieval"

    run_dir = retrieval.write_retrieval(report, out)

    assert run_dir.parent == out and run_dir.name != "latest"
    assert len(run_dir.name) == len(datetime.now().strftime(retrieval.STAMP))
    for directory in (run_dir, out / "latest"):
        data = json.loads((directory / "report.json").read_text(encoding="utf-8"))
        assert data["k"] == 3 and data["mean"] == report["mean"]
        assert data["questions"][0]["missing"]["dense"] == ["TABLO_A", "TABLO_B"]
        assert "timestamp" in data
        markdown = (directory / "report.md").read_text(encoding="utf-8")
        assert "| Soru | hybrid | bm25 | dense | eksik |" in markdown
        assert "bm25: TABLO_B; dense: TABLO_A, TABLO_B" in markdown
        assert "## Etiket ortalamaları" in markdown
    assert "timestamp" not in report, "girdi sözlüğü yazımda değişmemeli"


# ------------------------------------------------------------------ ekran


def test_console_lines_show_every_question_means_and_tags():
    lines = retrieval.console_lines(retrieval.run_retrieval(StubSearch(ORDER), GOLDEN, k=3))
    out = "\n".join(lines)

    assert lines[0].startswith("Soru") and "hybrid" in lines[0] and "eksik" in lines[0]
    means = next(line for line in lines if line.startswith("Ortalama:"))
    assert all(method in means for method in METHODS)
    assert "0.75" in means and "k=3" in means and "stub:1" in means
    assert "Etiket ortalamaları (hybrid/bm25/dense):" in out
    assert "bm25: TABLO_B" in out


# ------------------------------------------------------------------ CLI


def test_cli_eval_retrieval_prints_every_golden_question(tmp_path, capsys):
    out_dir = tmp_path / "retrieval"

    code = cli.eval_retrieval("fake", out_dir=out_dir)
    out = capsys.readouterr().out

    assert code == 0
    for line in runner.load_golden():
        assert line["id"] in out, f"{line['id']} satırda yok"
    assert "Soru" in out and "eksik" in out
    means = next(l for l in out.splitlines() if l.startswith("Ortalama:"))
    assert all(method in means for method in METHODS)
    assert "Etiket ortalamaları" in out
    assert (out_dir / "latest" / "report.json").exists()
    assert (out_dir / "latest" / "report.md").exists()
    assert "Rapor:" in out


def test_cli_eval_retrieval_dead_embedding_server(tmp_path, monkeypatch, capsys):
    url = f"http://127.0.0.1:{closed_port()}/v1"
    monkeypatch.setenv("NL2SQL_EMBED_BASE_URL", url)
    out_dir = tmp_path / "retrieval"

    code = cli.eval_retrieval("openai", out_dir=out_dir)
    out = capsys.readouterr().out

    assert code == 3
    assert url in out and "NL2SQL_EMBED_BASE_URL" in out and "Traceback" not in out
    assert "Ortalama:" not in out
    assert not out_dir.exists(), "ölçüm tamamlanmadan rapor yazılmamalı"


def test_main_routes_eval_retrieval(monkeypatch):
    seen = {}

    def record(**kwargs):
        seen.update(kwargs)
        return 0

    monkeypatch.setattr(cli, "eval_retrieval", record)
    assert cli.main(["eval-retrieval", "--embed", "fake", "--k", "3"]) == 0
    assert seen == {"embed": "fake", "k": 3}


def test_main_defaults_eval_retrieval_to_the_real_embedder_and_search_k(monkeypatch):
    seen = {}

    def record(**kwargs):
        seen.update(kwargs)
        return 0

    monkeypatch.setattr(cli, "eval_retrieval", record)
    assert cli.main(["eval-retrieval"]) == 0
    assert seen == {"embed": "openai", "k": config.SEARCH_K}
