# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""Aynı modun tekrarları: gürültünün ölçülmesi ve kararın ortalamayla kurulması (T108, R3-11).

Model yine yok; tekrarlar ``report._report`` ile kurulan sahte koşular. Dört şey görülüyor: karar
iki ortalamanın farkını kendi yayılımlarıyla kıyaslıyor ve fark yayılımdan küçükse satır gürültüyü
adıyla söylüyor, mod içi dönüş yalnız tekrarları olan modda sayılıyor, tekrarlı karşılaştırma
raporu ``repeat``/``scores``/``flips_within_mode`` alanlarını taşıyor (tek ölçümde hiç yazılmıyor),
CLI ``--repeat 2``de aynı sayıları ekrana da basıyor.
"""

import json
import re
from datetime import datetime

import pytest

from bilgin import config
from bilgin.agent import fake
from bilgin.cli import main as cli
from bilgin.eval import compare_modes, report, runner
from bilgin.eval.runner import QuestionResult
from bilgin.schema_map import build

MODEL = "strata"
STAMP = datetime(2026, 10, 24, 12, 0, 0)
IDS = ("Q01", "Q02", "Q03", "Q04")
TAGS = {"Q01": ["archive"], "Q02": ["archive"], "Q03": ["needs_rule"], "Q04": []}
NOISE = compare_modes.NOISE

GOLDEN = runner.load_golden()
MODES = list(config.MODES)
TOTAL = len(GOLDEN)
REUSED = "(önceki koşu)"


# ------------------------------------------------------------------ sahte tekrarlar


def run(outcomes: dict, mode: str, peak: int = 6200) -> dict:
    """Tek ölçüm: runner'ın QuestionResult'larından gerçek rapor işleviyle."""
    results = [
        QuestionResult(
            id=qid,
            question="Soru?",
            outcome=outcome,
            sql="SELECT 1",
            golden_sql="SELECT 1",
            reason="" if outcome == "pass" else "Satırlar farklı.",
            tool_calls=2,
            max_prompt_tokens=peak,
            total_tokens=peak,
            seconds=1.0,
            mode=mode,
            tags=TAGS.get(qid, []),
        )
        for qid, outcome in outcomes.items()
    ]
    return report._report(results, MODEL, {}, STAMP, mode=mode)


def repeats(counts, mode: str, peak: int = 6200) -> list[dict]:
    """Her tekrarda ``count`` sorunun geçtiği ölçümler; geçenler IDS sırasıyla baştan dolar."""
    return [
        run(
            {qid: "pass" if i < count else "wrong_result" for i, qid in enumerate(IDS)},
            mode,
            peak=peak,
        )
        for count in counts
    ]


def repeated(rag=(3, 2), rules=(2, 2)) -> dict:
    """rag 2.5 ortalamaya ve 1 yayılıma, full_rules 2 ortalamaya ve 0 yayılıma sahip koşum."""
    return {
        "full_rules": repeats(rules, "full_rules", peak=28400),
        "rag": repeats(rag, "rag", peak=6200),
    }


def built(**kwargs) -> dict:
    return compare_modes.build_compare(repeated(**kwargs), 28400)


def markdown(directory) -> str:
    return (directory / "report.md").read_text(encoding="utf-8")


# ------------------------------------------------------------------ karar (ortalamalar + gürültü)


def test_a_difference_smaller_than_the_spread_is_noise():
    verdict = compare_modes.verdict(repeated(rag=(3, 1), rules=(2, 2)))
    assert verdict["keep_rag"] is True
    assert verdict["line"] == (
        "Karar: RAG kalır — rag 2/4 ≥ full_rules 2/4 ve tepe bağlam 6.2K < 28.4K token; "
        "fark gürültü içinde."
    )


def test_a_difference_beyond_both_spreads_is_a_real_difference():
    verdict = compare_modes.verdict(repeated(rag=(3, 3), rules=(2, 2)))
    assert verdict["keep_rag"] is True
    assert verdict["line"] == (
        "Karar: RAG kalır — rag 3/4 ≥ full_rules 2/4 ve tepe bağlam 6.2K < 28.4K token."
    )
    assert NOISE not in verdict["line"]


def test_the_verdict_is_built_on_the_means_and_prints_the_fraction():
    verdict = compare_modes.verdict(repeated(rag=(1, 2), rules=(2, 2)))
    assert verdict["keep_rag"] is False
    assert verdict["line"] == (
        "Karar: RAG yok — rag 1.5/4 < full_rules 2/4; fark gürültü içinde."
    )


def test_a_single_measurement_has_no_spread_and_never_claims_noise():
    single = {
        "full_rules": run({qid: "pass" for qid in IDS}, "full_rules", peak=28400),
        "rag": run({qid: "pass" for qid in IDS}, "rag"),
    }
    assert NOISE not in compare_modes.verdict(single)["line"]


# ------------------------------------------------------------------ mod içi dönüş


def test_only_a_repeated_mode_can_flip_within_itself():
    assert compare_modes.flips_within_mode({"rag": repeats([3, 2], "rag")}) == 1
    assert compare_modes.flips_within_mode({"rag": run({"Q01": "pass"}, "rag")}) == 0


def test_the_same_question_flipping_in_two_modes_is_one_question():
    assert compare_modes.flips_within_mode(repeated(rag=(3, 2), rules=(3, 2))) == 1


def test_two_different_questions_flipping_are_two_questions():
    assert compare_modes.flips_within_mode(repeated(rag=(3, 2), rules=(2, 1))) == 2


def test_a_stable_repeat_flips_nowhere():
    assert compare_modes.flips_within_mode(repeated(rag=(3, 3), rules=(2, 2))) == 0


# ------------------------------------------------------------------ karşılaştırma raporu


def test_the_repeat_report_carries_the_noise_fields():
    data = built()
    assert data["repeat"] == 2
    assert data["flips_within_mode"] == 1
    rag = data["modes"]["rag"]
    assert rag["score"] == {"passed": 3, "total": 4}
    assert rag["scores"] == {"mean": 2.5, "min": 2, "max": 3}
    assert rag["tags"]["archive"] == {
        "passed": 2,
        "total": 2,
        "scores": {"mean": 2.0, "min": 2, "max": 2},
    }
    assert rag["tags"]["needs_rule"]["scores"] == {"mean": 0.5, "min": 0, "max": 1}


def test_the_verdict_of_the_report_is_the_verdict_of_the_means():
    assert built()["verdict"] == compare_modes.verdict(repeated())


def test_a_single_measurement_writes_no_noise_fields():
    data = compare_modes.build_compare(
        {"full_rules": run({"Q01": "pass"}, "full_rules"), "rag": run({"Q01": "pass"}, "rag")}, 0
    )
    assert "repeat" not in data and "flips_within_mode" not in data
    for summary in data["modes"].values():
        assert "scores" not in summary
        assert all("scores" not in counts for counts in summary["tags"].values())


def test_the_markdown_shows_the_spread_and_names_the_noise(tmp_path):
    text = markdown(compare_modes.write_compare(built(), tmp_path))
    assert "- Tekrar: 2 (her mod 2 kez koşuldu)" in text
    assert "- Mod içi dönüş: 1 soru" in text
    assert "| Mod | Skor (ort/min/max) | Bağlam (tepe/medyan) |" in text
    assert "| rag | 2.5/2/3 |" in text
    assert "| full_rules | 2/2/2 |" in text
    assert "| needs_rule | 0/0/0 | 0.5/0/1 |" in text
    assert f"**{built()['verdict']['line']}**" in text


def test_the_markdown_of_a_single_run_stays_the_run_2_table(tmp_path):
    single = {"full_rules": run({"Q01": "pass"}, "full_rules"), "rag": run({"Q01": "pass"}, "rag")}
    text = markdown(compare_modes.write_compare(compare_modes.build_compare(single, 0), tmp_path))
    assert "| Mod | Skor | Bağlam (tepe/medyan) |" in text
    assert "Tekrar:" not in text and "Mod içi dönüş:" not in text


# ------------------------------------------------------------------ CLI --repeat


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    """Modül boyunca tek kurulum: veritabanı, sahte indeks ve audit tek tmp klasörde."""
    paths = tmp_path_factory.mktemp("compare-repeat")
    database = paths / "test.db"
    build.build_db(config.SEED, database, paths / "test.sql")
    cli.build_index("fake", index_dir=paths / "index")
    return database, paths / "index", paths / "audit.jsonl"


def compare(world, tmp_path, **kwargs):
    database, index, audit = world
    out_dir = tmp_path / "eval_out"
    code = cli.compare_modes(
        lambda mode: fake.for_golden(GOLDEN, mode=mode),
        db_path=database,
        audit_path=audit,
        out_dir=out_dir,
        index_dir=index,
        **kwargs,
    )
    return code, out_dir


def comparison(out_dir) -> dict:
    path = out_dir / "compare" / "latest" / "report.json"
    return json.loads(path.read_text(encoding="utf-8"))


def test_repeat_two_runs_each_mode_twice_and_writes_the_fields(world, tmp_path, capsys):
    code, out_dir = compare(world, tmp_path, repeat=2)
    out = capsys.readouterr().out
    data = comparison(out_dir)

    assert code == 0
    assert data["repeat"] == 2
    assert data["flips_within_mode"] == 0
    assert data["questions"] == TOTAL
    assert "Tekrar: her mod 2 kez koşuluyor" in out
    assert out.count("koşuluyor 1/2") == len(MODES)
    assert out.count("koşuluyor 2/2") == len(MODES)
    assert REUSED not in out, "tekrarlı koşu tek ölçümlük latesti yetkili saymaz"

    for mode in MODES:
        summary = data["modes"][mode]
        assert summary["scores"] == {"mean": float(TOTAL), "min": TOTAL, "max": TOTAL}
        spreads = [counts["scores"] for counts in summary["tags"].values()]
        assert all(spread["min"] == spread["max"] for spread in spreads)
        assert re.search(rf"^{mode}\s+{TOTAL}/{TOTAL}/{TOTAL}", out, re.MULTILINE), f"{mode}: {out}"
    assert data["verdict"]["line"] in out


def test_a_second_repeat_run_still_reruns_the_modes_it_could_reuse(world, tmp_path, capsys):
    compare(world, tmp_path)
    capsys.readouterr()

    code, out_dir = compare(world, tmp_path, repeat=2)
    out = capsys.readouterr().out

    assert code == 0
    assert comparison(out_dir)["repeat"] == 2
    assert REUSED not in out, "yayılımı olmayan bir ölçüm tekrarın yerine geçmez"


def test_main_routes_repeat(monkeypatch):
    seen = []
    monkeypatch.setattr(
        cli, "compare_modes", lambda factory, **kwargs: seen.append(kwargs) or 0
    )

    assert cli.main(["eval", "--llm", "fake", "--compare", "--repeat", "2"]) == 0
    assert seen[-1]["repeat"] == 2

    assert cli.main(["eval", "--llm", "fake", "--compare"]) == 0
    assert seen[-1]["repeat"] == 1


def test_a_repeat_below_one_says_so_without_running(tmp_path, capsys):
    assert cli.main(["eval", "--llm", "fake", "--compare", "--repeat", "0"]) == 2
    assert "en az 1" in capsys.readouterr().out
