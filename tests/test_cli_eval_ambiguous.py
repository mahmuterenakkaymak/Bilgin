"""``eval --ambiguous`` ve ``--narrate``: sayıların göründüğü her yer (R5-12, R5-13, R5-14).

Koşum yine FakeLLM iledir; veritabanı, audit ve raporun hepsi tmp klasörde, yani test repoya hiçbir
şey yazmıyor. Ekranın göstermesi gereken şey aynı ölçülerin dört kopyası: canlı blok, report.json,
report.md ve imza. İki arıza kullanıcının kendi düzelteceği şeylerdir ve iz dökümü değil tek
cümledir — kümenin belirsiz seti yoktur, ya da ``--compare`` üç modu koşarken tek modluk bir
netleştirme ölçümünü koşamaz. İmza eski koşuları kırdırmaz: netleştirme kapalıyken anahtar hiç
yazılmaz, yani diskteki ``latest``ler yeniden kullanılabilir kalır.
"""

import json

import pytest
from pathlib import Path

from nl2sql import config, datasets
from nl2sql.cli import main as cli
from nl2sql.schema_map import build

DATASET = "synthetic_erp"
NO_AMBIGUOUS = "Bu veri kümesinin belirsiz soru seti yok."
AMBIGUOUS_COMPARE = "--ambiguous tek mod eval'i içindir."
SOURCES = ("llm", "llm_retry", "template")


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    """Modül boyunca tek kurulum: sentetik dünyanın veritabanı ve audit'i tek tmp klasörde."""
    paths = tmp_path_factory.mktemp("cli-eval-ambiguous")
    database = paths / "test.db"
    build.build_db(config.SEED, database, paths / "test.sql")
    return database, paths / "audit.jsonl"


def run(world, tmp_path, **kwargs):
    """``evaluate``ın tek çağrısı; sahte istemci belirsiz seti de tanır, out_dir geri verilir."""
    database, audit = world
    out_dir = tmp_path / "eval_out"
    ds = datasets.load_dataset(DATASET)
    code = cli.evaluate(
        cli.make_client("fake", "full", ds),
        db_path=database,
        audit_path=audit,
        out_dir=out_dir / "full",
        dataset=DATASET,
        **kwargs,
    )
    return code, out_dir


def written(out_dir) -> dict:
    return json.loads((out_dir / "full" / "latest" / "report.json").read_text(encoding="utf-8"))


def markdown(out_dir) -> str:
    return (out_dir / "full" / "latest" / "report.md").read_text(encoding="utf-8")


# ------------------------------------------------------------------ belirsiz set


def test_the_ambiguous_set_is_measured_everywhere_it_shows_up(world, tmp_path, capsys):
    code, out_dir = run(world, tmp_path, ambiguous=True)
    out = capsys.readouterr().out

    assert code == 0
    data = written(out_dir)
    metrics = data["metrics"]
    # Sahte kayıt belirsiz soruyu sorar, altın soruyu sorup tahmin etmez: ikisi de 1 (R5-12).
    assert metrics["clarify_precision"] == 1.0 and metrics["clarify_recall"] == 1.0
    assert metrics["accuracy"] == 1.0, "belirsiz set altın cevabın yerine geçmez"

    lines = datasets.load_dataset(DATASET).ambiguous()
    ambiguous = [question for question in data["questions"] if question["kind"] == "ambiguous"]
    assert [question["id"] for question in ambiguous] == [line["id"] for line in lines]
    assert metrics["ambiguous"] == len(lines)
    assert metrics["golden"] + len(lines) == len(data["questions"])
    assert {question["outcome"] for question in ambiguous} == {"clarified"}
    assert all(question["clarification"] for question in ambiguous), "sorulan şık satırda durur"

    assert "Metrikler:" in out and "Netleştirme duyarlılığı" in out
    text = markdown(out_dir)
    assert "## Metrikler" in text and "| Netleştirme kesinliği | %100,00 |" in text
    assert data["config"]["fingerprint"]["clarify"] is True


def test_a_dataset_without_the_set_names_the_missing_one(world, tmp_path, capsys, monkeypatch):
    # Updated 2026-10-26 (Eren: "otomatik olsun"): wwi gained this set for the visual flows (Run 8 brief); the mini fixture has none.
    monkeypatch.setenv("NL2SQL_DATASETS_DIR", str(Path(__file__).parent / "fixtures" / "datasets"))
    out_dir = tmp_path / "eval_out"
    code = cli.evaluate(
        cli.make_client("fake"), out_dir=out_dir, dataset="mini", ambiguous=True
    )
    out = capsys.readouterr().out

    assert code == 2
    assert NO_AMBIGUOUS in out and "Traceback" not in out
    assert "Skor:" not in out and not out_dir.exists(), "koşulmayan bir koşunun raporu yazılmaz"


def test_compare_refuses_the_ambiguous_set(capsys):
    assert cli.main(["eval", "--llm", "fake", "--compare", "--ambiguous"]) == 2
    out = capsys.readouterr().out

    assert AMBIGUOUS_COMPARE in out and "Traceback" not in out
    assert "Mod:" not in out and "Skor:" not in out


# ------------------------------------------------------------------ anlatı


def test_narrate_counts_the_sources_of_every_answered_question(world, tmp_path):
    code, out_dir = run(world, tmp_path, narrate=True)

    assert code == 0
    data = written(out_dir)
    narration = data["narration"]
    submitted = [question for question in data["questions"] if question["submitted"]]
    assert sum(narration[key] for key in SOURCES) == len(submitted)
    assert narration["template_pct"] == round(narration["template"] / len(submitted), 4)
    assert all(question["narration_source"] in SOURCES for question in submitted)
    assert "Anlatı:" in markdown(out_dir)


def test_a_plain_run_narrates_nothing_and_measures_no_clarifications(world, tmp_path):
    code, out_dir = run(world, tmp_path)

    assert code == 0
    data = written(out_dir)
    assert data["narration"] is None
    assert data["metrics"]["clarify_precision"] is None
    assert data["metrics"]["clarify_recall"] is None
    assert all(question["narration_source"] is None for question in data["questions"])
    assert "clarify" not in data["config"]["fingerprint"], "eski imza byte-eşit kalmalı"
    assert "Anlatı:" not in markdown(out_dir)


# ------------------------------------------------------------------ söz dizimi


def test_main_routes_the_two_flags_to_the_single_mode_run(monkeypatch):
    seen = {}
    monkeypatch.setattr(cli, "evaluate", lambda **kwargs: seen.update(kwargs) or 0)

    assert cli.main(["eval", "--llm", "fake", "--ambiguous", "--narrate"]) == 0
    assert seen["ambiguous"] is True and seen["narrate"] is True
    assert seen["dataset"] == config.DEFAULT_DATASET, "belirsiz set bir kümeye aittir"

    seen.clear()
    assert cli.main(["eval", "--llm", "fake"]) == 0
    assert seen["ambiguous"] is False and "dataset" not in seen
