"""``--embed`` ve ``--embed-model``: ölçümün hangi vektör uzayıyla yapıldığı komutun kendisinde.

Model adı daha önce yalnız ``NL2SQL_EMBED_MODEL`` ile değişebiliyordu; iki modeli karşılaştırmanın
yolu ortam değişkenini iki kere düzenlemekti. Artık ``--embed-model bge-m3`` komutta durur,
``meta.json`` da hangi uzayla ölçtüğünü yazar. ``--embed``in soneki serbest metin olduğu için
biçimi bozuk bir değer iz dökümü değil tek cümle olmalı, ölü bir sunucu da hangi adresi denediğimizi
söyleyip yarım bir indeks bırakmadan çıkmalı.
"""

import json
import socket

from nl2sql.cli import main as cli


def closed_port() -> int:
    """Boş bir port al, bırak: bağlananın reddedileceği bir adresin adresi olur."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def to_tmp(monkeypatch, name: str, **fixed):
    """Komutu gerçek işlevine bağlar, tek sabiti kendi tmp yoluna çevirir.

    ``index_dir``/``out_dir`` varsayılanı imzada bağlı olduğu için monkeypatch yolu işlemez;
    bayrağın kendisinin mi, yoksa komutun mu yazdığı böylece ayrılmış olur.
    """
    real = getattr(cli, name)
    monkeypatch.setattr(cli, name, lambda **kwargs: real(**{**fixed, **kwargs}))


# ------------------------------------------------------------------ sahte uzay


def test_build_index_writes_the_dim_it_was_given(tmp_path, monkeypatch, capsys):
    index_dir = tmp_path / "index"
    to_tmp(monkeypatch, "build_index", index_dir=index_dir)

    assert cli.main(["build-index", "--embed", "fake:64"]) == 0
    out = capsys.readouterr().out

    meta = json.loads((index_dir / "meta.json").read_text(encoding="utf-8"))
    assert meta["embedder"] == "fake:64"
    assert meta["dim"] == 64
    assert "Embedder: fake:64 (dim 64)" in out


def test_eval_retrieval_measures_with_another_dim(tmp_path, monkeypatch, capsys):
    out_dir = tmp_path / "retrieval"
    to_tmp(monkeypatch, "eval_retrieval", out_dir=out_dir)

    assert cli.main(["eval-retrieval", "--embed", "fake:128"]) == 0
    out = capsys.readouterr().out

    assert "Q01" in out and "Rapor:" in out and "Traceback" not in out
    assert (out_dir / "latest" / "report.md").exists()


# ------------------------------------------------------------------ model adı


def test_embed_model_composes_the_openai_id(monkeypatch):
    seen = {}

    def record(**kwargs):
        seen.update(kwargs)
        return 0

    monkeypatch.setattr(cli, "build_index", record)
    monkeypatch.setattr(cli, "eval_retrieval", record)

    assert cli.main(["build-index", "--embed-model", "bge-m3"]) == 0
    assert seen["embed"] == "openai:bge-m3"
    assert cli.main(["eval-retrieval", "--embed", "openai", "--embed-model", "bge-m3"]) == 0
    assert seen["embed"] == "openai:bge-m3"


def test_dead_server_names_the_url_and_leaves_no_index(tmp_path, monkeypatch, capsys):
    url = f"http://127.0.0.1:{closed_port()}/v1"
    monkeypatch.setenv("NL2SQL_EMBED_BASE_URL", url)
    index_dir = tmp_path / "index"
    to_tmp(monkeypatch, "build_index", index_dir=index_dir)

    assert cli.main(["build-index", "--embed-model", "bge-m3"]) == 3
    out = capsys.readouterr().out

    assert url in out and "NL2SQL_EMBED_BASE_URL" in out and "Traceback" not in out
    assert not index_dir.exists(), "vektörsüz bir indeks bırakılmamalı"


# ------------------------------------------------------------------ bozuk değer


def test_model_name_without_a_server_source_is_refused(monkeypatch, capsys):
    seen = {}
    monkeypatch.setattr(cli, "build_index", lambda **kwargs: seen.update(kwargs) or 0)

    assert cli.main(["build-index", "--embed", "fake:64", "--embed-model", "bge-m3"]) == 2
    out = capsys.readouterr().out

    assert seen == {} and "fake:64:bge-m3" in out and "Traceback" not in out


def test_a_dimension_that_is_not_a_number_is_refused(monkeypatch, capsys):
    seen = {}
    monkeypatch.setattr(cli, "build_index", lambda **kwargs: seen.update(kwargs) or 0)

    assert cli.main(["build-index", "--embed", "fake:koc"]) == 2
    out = capsys.readouterr().out

    assert seen == {} and "fake:koc" in out and "Traceback" not in out
