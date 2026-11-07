# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""Aynı soruların modlar arasındaki yan yana okunuşu: karar, dönenler ve rapor (T64).

Model yine yok; raporlar ``report._report`` ile kurulan sahte koşuların çıktısı. Dört şey görülüyor:
kararın iki koşulu ve iki satır biçimi sayılarıyla birlikte, dönüşün yalnız sonucu gerçekten
farklaşan sorularda yazılması, Contracts alanlarının json'da ve md'de eksiksiz durması ve bir
``latest``in ancak aynı imzayla yeniden koşulmaması.
"""

import json
from datetime import datetime

from nl2sql import config
from nl2sql.eval import compare_modes, report
from nl2sql.eval.runner import QuestionResult

MODEL = "strata"
STAMP = datetime(2026, 10, 23, 12, 0, 0)
TAGS = {"Q01": ["archive", "multi_join"], "Q02": ["archive"], "Q03": ["needs_rule"], "Q04": []}

# Üç mod aynı dört soruyu koşuyor: full 3/4, full_rules 2/4, rag 2/4 ve rag'in tepe bağlamı en düşük.
FULL = {"Q01": "pass", "Q02": "pass", "Q03": "pass", "Q04": "wrong_result"}
RULES = {"Q01": "pass", "Q02": "pass", "Q03": "wrong_result", "Q04": "wrong_result"}
RAG = {"Q01": "pass", "Q02": "pass", "Q03": "wrong_result", "Q04": "sql_error"}

KEEP = "Karar: RAG kalır — rag 2/4 ≥ full_rules 2/4 ve tepe bağlam 6.2K < 28.4K token."


def made(outcomes, mode, peak=1000, calls=3, seconds=1.0, tags=TAGS) -> dict:
    """Bir modun raporu: runner'ın QuestionResult'larından, gerçek rapor işleviyle kuruluyor."""
    results = [
        QuestionResult(
            id=qid,
            question="Soru?",
            outcome=outcome,
            sql="SELECT 1",
            golden_sql="SELECT 1",
            reason="" if outcome == "pass" else "Satırlar farklı: 1 satır karşı tarafta yok.",
            tool_calls=calls[qid] if isinstance(calls, dict) else calls,
            max_prompt_tokens=peak,
            total_tokens=peak,
            seconds=seconds,
            mode=mode,
            tags=tags.get(qid, []),
        )
        for qid, outcome in outcomes.items()
    ]
    return report._report(results, MODEL, {}, STAMP, mode=mode)


def modes(rag=RAG, rag_peak=6200, rules_peak=28400) -> dict:
    return {
        "full": made(FULL, "full", peak=30000),
        "full_rules": made(RULES, "full_rules", peak=rules_peak),
        "rag": made(rag, "rag", peak=rag_peak),
    }


def built() -> dict:
    return compare_modes.build_compare(modes(), 28400, ["full"])


def written(directory) -> dict:
    return json.loads((directory / "report.json").read_text(encoding="utf-8"))


def markdown(directory) -> str:
    return (directory / "report.md").read_text(encoding="utf-8")


def fingerprint(**changes) -> dict:
    args = {
        "mode": "rag",
        "llm": "fake",
        "model": MODEL,
        "golden": [{"id": "Q01", "question": "Soru?", "sql": "SELECT 1", "ordered": False}],
        "schema": {"tables": []},
        "rules": [],
        "index_hash": "abc123",
        "max_tool_calls": 12,
    }
    args.update(changes)
    return report.fingerprint(**args)


# ------------------------------------------------------------------ karar (R2-13)


def test_the_verdict_keeps_rag_when_both_conditions_hold():
    assert compare_modes.verdict(modes()) == {"keep_rag": True, "line": KEEP}


def test_a_higher_score_with_a_lower_peak_keeps_rag_too():
    verdict = compare_modes.verdict(modes(rag=FULL))
    assert verdict["keep_rag"] is True
    assert verdict["line"] == (
        "Karar: RAG kalır — rag 3/4 ≥ full_rules 2/4 ve tepe bağlam 6.2K < 28.4K token."
    )


def test_a_lower_score_than_full_rules_is_no_rag():
    weaker = modes(rag={"Q01": "pass", "Q02": "wrong_result", "Q03": "wrong_result", "Q04": "wrong_result"})
    verdict = compare_modes.verdict(weaker)
    assert verdict["keep_rag"] is False
    assert verdict["line"] == "Karar: RAG yok — rag 1/4 < full_rules 2/4."


def test_a_peak_that_is_not_lower_is_no_rag():
    verdict = compare_modes.verdict(modes(rag_peak=30000))
    assert verdict["keep_rag"] is False
    assert verdict["line"] == "Karar: RAG yok — tepe bağlam 30.0K > 28.4K token."


def test_an_equal_peak_is_no_rag_either():
    verdict = compare_modes.verdict(modes(rag_peak=28400))
    assert verdict["keep_rag"] is False
    assert verdict["line"] == "Karar: RAG yok — tepe bağlam 28.4K ≥ 28.4K token."


def test_a_missing_mode_is_measured_as_nothing_rather_than_crashing():
    verdict = compare_modes.verdict({"full_rules": made(RULES, "full_rules")})
    assert verdict["keep_rag"] is False
    assert verdict["line"] == "Karar: RAG yok — rag 0/0 < full_rules 2/4."


# ------------------------------------------------------------------ dönen sorular


def test_only_the_questions_whose_outcome_differs_flip():
    reports = {
        "full": made(FULL, "full"),
        "full_rules": made(RULES, "full_rules"),
        "rag": made(
            {"Q01": "pass", "Q02": "pass", "Q03": "wrong_result", "Q04": "pass", "Q05": "sql_error"},
            "rag",
        ),
    }
    assert [flip["id"] for flip in compare_modes.flips(reports)] == ["Q03", "Q04"]
    assert compare_modes.flips(reports)[0]["outcomes"] == {
        "full": "pass",
        "full_rules": "wrong_result",
        "rag": "wrong_result",
    }


def test_two_modes_are_enough_to_flip_and_one_mode_is_not():
    reports = {"rag": made({"Q07": "pass"}, "rag"), "full": made({"Q07": "wrong_result"}, "full")}
    assert compare_modes.flips(reports) == [
        {"id": "Q07", "outcomes": {"full": "wrong_result", "rag": "pass"}}
    ]
    assert compare_modes.flips({"rag": made({"Q07": "pass"}, "rag")}) == []


# ------------------------------------------------------------------ karşılaştırma raporu


def test_the_json_carries_every_contract_field():
    data = built()
    assert set(data) == {
        "timestamp",
        "model",
        "questions",
        "schema_tokens",
        "modes",
        "flips",
        "verdict",
    }
    assert (data["model"], data["questions"], data["schema_tokens"]) == (MODEL, 4, 28400)
    assert list(data["modes"]) == list(config.MODES)
    for summary in data["modes"].values():
        assert set(summary) == {
            "score",
            "tags",
            "context",
            "tool_calls",
            "seconds",
            "report",
            "reused",
        }
        assert set(summary["context"]) == {"max_prompt_tokens", "median_prompt_tokens"}
        assert set(summary["tool_calls"]) == {"mean", "max"}
        assert set(summary["seconds"]) == {"mean", "total"}
        assert summary["report"].endswith("report.json")
    assert data["verdict"] == {"keep_rag": True, "line": KEEP}
    assert all(set(flip) == {"id", "outcomes"} for flip in data["flips"])


def test_only_a_mode_taken_from_latest_is_marked_reused():
    data = built()
    assert (data["modes"]["full"]["reused"], data["modes"]["rag"]["reused"]) == (True, False)
    assert all(
        summary["reused"] is False
        for summary in compare_modes.build_compare(modes(), 0)["modes"].values()
    )


def test_tool_calls_and_seconds_are_averaged_over_the_questions():
    single = {"full": made(FULL, "full", calls={"Q01": 2, "Q02": 4, "Q03": 4, "Q04": 6}, seconds=2.5)}
    summary = compare_modes.build_compare(single, 0)["modes"]["full"]
    assert summary["tool_calls"] == {"mean": 4.0, "max": 6}
    assert summary["seconds"] == {"mean": 2.5, "total": 10.0}


def test_a_half_written_mode_report_never_becomes_a_broken_number(tmp_path):
    report_json = compare_modes.build_compare({"full_rules": {}, "rag": {}}, 0)
    assert report_json["questions"] == 0
    assert report_json["modes"]["rag"]["score"] == {"passed": 0, "total": 0}
    assert report_json["modes"]["rag"]["tool_calls"] == {"mean": 0.0, "max": 0}
    assert report_json["modes"]["rag"]["tags"] == {}
    text = markdown(compare_modes.write_compare(report_json, tmp_path))
    assert "nan" not in text.lower() and "None" not in text


# ------------------------------------------------------------------ report.md / report.json


def test_write_compare_lands_in_the_run_and_the_latest(tmp_path):
    run_dir = compare_modes.write_compare(built(), tmp_path / "compare")
    assert run_dir.parent.name == "compare"
    for directory in (run_dir, tmp_path / "compare" / "latest"):
        assert written(directory) == written(run_dir)
        assert KEEP in markdown(directory)


def test_the_markdown_lines_up_the_modes(tmp_path):
    text = markdown(compare_modes.write_compare(built(), tmp_path))
    assert f"# Mod karşılaştırması — {MODEL}" in text
    assert f"- Model: `{MODEL}`" in text
    assert "- Soru: 4" in text
    assert "- Şema tahmini: 28.4K token" in text
    assert (
        "| Mod | Skor | Bağlam (tepe/medyan) | Araç (ort/max) | Süre (ort/toplam) | Not |" in text
    )
    assert "| full | 3/4 | 30.0K / 30.0K | 3.0 / 3 | 1.0 / 4.0 sn | (önceki koşu) |" in text
    assert "| rag | 2/4 | 6.2K / 6.2K | 3.0 / 3 | 1.0 / 4.0 sn | - |" in text
    assert f"**{KEEP}**" in text


def test_the_markdown_tables_the_tags_against_every_mode(tmp_path):
    text = markdown(compare_modes.write_compare(built(), tmp_path))
    assert "## Etiket skorları" in text
    assert "| Etiket | full | full_rules | rag |" in text
    assert "| archive | 2/2 | 2/2 | 2/2 |" in text
    assert "| multi_join | 1/1 | 1/1 | 1/1 |" in text
    assert "| needs_rule | 1/1 | 0/1 | 0/1 |" in text


def test_a_mode_without_a_tag_shows_a_dash_instead_of_a_zero(tmp_path):
    reports = {"full": made(FULL, "full"), "rag": made(RAG, "rag", tags={})}
    text = markdown(compare_modes.write_compare(compare_modes.build_compare(reports, 0), tmp_path))
    assert "| archive | 2/2 | - |" in text


def test_the_markdown_tables_the_flips(tmp_path):
    text = markdown(compare_modes.write_compare(built(), tmp_path))
    assert "## Dönen sorular" in text
    assert "| Soru | full | full_rules | rag |" in text
    assert "| Q03 | ✓ pass | ✗ wrong_result | ✗ wrong_result |" in text
    assert "| Q04 | ✗ wrong_result | ✗ wrong_result | ✗ sql_error |" in text


def test_a_comparison_without_flips_says_so(tmp_path):
    reports = {"full": made(FULL, "full"), "rag": made(FULL, "rag")}
    text = markdown(compare_modes.write_compare(compare_modes.build_compare(reports, 0), tmp_path))
    assert compare_modes.NO_FLIPS in text
    assert "Dönen sorular" in text


# ------------------------------------------------------------------ yeniden kullanım (R2-12)


def test_a_latest_is_reusable_only_under_the_equal_fingerprint():
    digest = fingerprint()
    stored = made(RAG, "rag")
    stored["config"]["fingerprint"] = digest
    assert compare_modes.reusable(stored, digest)
    assert not compare_modes.reusable(stored, fingerprint(model="qwen3"))
    assert not compare_modes.reusable(stored, fingerprint(index_hash=""))
    assert not compare_modes.reusable(made(RAG, "rag"), digest)
    assert not compare_modes.reusable(None, digest)
    assert not compare_modes.reusable({"config": {"fingerprint": None}}, digest)
