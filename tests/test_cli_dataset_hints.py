"""``--dataset`` verildiğinde kurtarma cümlesi de o kümeyi söyler (PLAN R4-14).

Eksik bir veritabanı ya da bayat bir indeks tek başına bir arıza değil; asıl kaybedilen, cümlenin
``build-db``nin adsız halini önermesi: ``--dataset wwi`` ile çalışan biri o kurulumla kendi
dünyasının dosyasını elde edemez, yani tavsiye aynı arızayı tekrar üretir. Küme söylenmediğinde ise
cümleler eskisiyle harfi harfine aynı kalmalı — tek kümeyle çalışan bir koşumda isim gürültüdür.
Bir ``ask`` koşumunda küme satırı her şeyden önce gelmeli: auto çözümü ondan önce not basarsa
ekran hangi dünyayla çalışıldığını ilk satırda söylemez.
"""

import json
from pathlib import Path

import pytest

from nl2sql import config
from nl2sql.agent import fake
from nl2sql.cli import main as cli
from nl2sql.datasets import load_dataset
from nl2sql.index.store import FileStore, MissingIndexError, StaleIndexError

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "datasets"
QUESTION = "Siparişlerin toplamı ne kadar?"
# Değişiklik öncesi cümleler: küme söylenmeyen koşumda harfi harfine bunlar basılmalı.
OLD_NO_DB = "Veritabanı yok: {path}\nÖnce `python -m nl2sql build-db` çalıştırın."
OLD_MISSING = "İndeks bulunamadı: {path}. Önce `python -m nl2sql build-index` çalıştırın."
OLD_STALE = "İndeks eski: `python -m nl2sql build-index` çalıştırın."


@pytest.fixture
def project(tmp_path, monkeypatch):
    """Proje kökü geçici: kümenin veritabanı ve indeksi oraya düşer, gerçek repoya tek dosya geçmez."""
    monkeypatch.setattr(config, "ROOT", tmp_path)
    monkeypatch.setenv("NL2SQL_DATASETS_DIR", str(FIXTURE_ROOT))
    return tmp_path


# ------------------------------------------------------------------ cümlenin hedefi küme


def test_a_missing_database_names_the_dataset_it_wants_built(project, capsys):
    assert cli.main(["ask", QUESTION, "--llm", "fake", "--dataset", "mini"]) == 2
    out = capsys.readouterr().out

    assert "build-db --dataset mini" in out
    assert str(project / "data" / "mini.db") in out
    assert "Traceback" not in out


def test_a_missing_index_names_the_dataset_it_wants_built(project, capsys):
    assert cli.build_database(dataset="mini") == 0
    capsys.readouterr()

    code = cli.main(["ask", QUESTION, "--llm", "fake", "--dataset", "mini", "--mode", "rag"])
    out = capsys.readouterr().out

    assert code == 2
    assert "İndeks bulunamadı" in out and "build-index --dataset mini" in out


def test_a_stale_index_names_the_dataset_it_wants_built(project, capsys):
    assert cli.build_database(dataset="mini") == 0
    assert cli.build_index("fake", dataset="mini") == 0
    meta = load_dataset("mini").index_dir / "meta.json"
    stored = json.loads(meta.read_text(encoding="utf-8"))
    stored["content_hash"] = "baska-bir-semanın-imzası"
    meta.write_text(json.dumps(stored, ensure_ascii=False), encoding="utf-8")
    capsys.readouterr()

    code = cli.main(["ask", QUESTION, "--llm", "fake", "--dataset", "mini", "--mode", "rag"])
    out = capsys.readouterr().out

    assert code == 2
    assert "İndeks eski" in out and "build-index --dataset mini" in out


# ------------------------------------------------------------------ kümesiz hal eskisi gibi


def test_without_a_dataset_the_sentences_are_the_old_ones(tmp_path, capsys):
    missing_db = tmp_path / "test.db"

    code = cli.ask(
        QUESTION, fake.FakeLLM([]), db_path=missing_db, audit_path=tmp_path / "audit.jsonl"
    )

    assert code == 2
    assert capsys.readouterr().out == OLD_NO_DB.format(path=missing_db) + "\n"

    with pytest.raises(MissingIndexError) as exc:
        FileStore(tmp_path / "yok").load_checked("imza")
    assert str(exc.value) == OLD_MISSING.format(path=tmp_path / "yok" / "docs.json")

    store = FileStore(tmp_path / "index")
    store.save([], [], {"content_hash": "abc"})
    with pytest.raises(StaleIndexError) as exc:
        store.load_checked("baska-imza")
    assert str(exc.value) == OLD_STALE


# ------------------------------------------------------------------ küme satırı her şeyden önce


def test_the_dataset_line_stays_the_first_line(project, monkeypatch, capsys):
    monkeypatch.setattr(config, "AUTO_FULL_MAX_TOKENS", 1)  # her halükarda indeks denenir

    assert cli.main(["ask", QUESTION, "--llm", "fake", "--dataset", "mini"]) == 2
    out = capsys.readouterr().out

    assert out.splitlines()[0] == f"Veri kümesi: {load_dataset('mini').display_name} (mini)"
    assert out.count("Veri kümesi:") == 1, "satır bir daha aşağıda yinelenmemeli"
    assert cli.NO_INDEX_NOTE in out, "düşüş notu küme satırının üstüne çıkamaz"


def test_auto_refuses_a_foreign_index_instead_of_falling_back(project, monkeypatch, capsys):
    assert cli.build_index("fake", index_dir=load_dataset("mini").index_dir) == 0  # adsız = synthetic_erp
    monkeypatch.setattr(config, "AUTO_FULL_MAX_TOKENS", 1)
    capsys.readouterr()

    assert cli.main(["ask", QUESTION, "--llm", "fake", "--dataset", "mini"]) == 2
    out = capsys.readouterr().out

    assert "İndeks başka veri kümesine ait: synthetic_erp (istenen mini)" in out
    assert "build-index --dataset mini" in out
    assert cli.NO_INDEX_NOTE not in out, "yabancı indeks sessizce full'a düşürülemez"
    assert "Traceback" not in out and out.startswith("Veri kümesi:")
