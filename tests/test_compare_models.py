# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""Model x mod hücreleri, elle kurulmuş tekrarlarla: sayılar nereden geldiği bilinen sayılar (T151, R4-13).

Model de veritabanı da yok; her hücre ``QuestionResult`` listeleridir ve beklenen her sayı o
listelerden elde kâğıtla hesaplanmıştır. Görülen şeyler: hücrenin yedi ölçümü (ort/min/max,
cevap yüzdesi, iki tepe, taşma/kırpma toplamları, soru başına süre), etiket yayılımı ve soru soru
tekrar sonuçları, profil hanesinin olmadığı modelde sıfır durması, atlanan modelin json'da,
markdown'da ve konsolda listelenmesi, iki dosyanın ``compare_<dataset>_<ts>`` adıyla yazılması ve
ping'in kapalı uç noktada URL'yi söyleyen sebebi döndürüp asla fırlatmaması.
"""

import json
import re
import socket
import types

from nl2sql.agent import llm
from nl2sql.agent.llm import ModelProfile
from nl2sql.eval import compare_models
from nl2sql.eval.runner import QuestionResult

STRATA = ModelProfile(
    name="strata",
    base_url="http://127.0.0.1:8080/v1",
    model="strata",
    context_budget=262144,
    max_output_tokens=8192,
)
QWEN = ModelProfile(
    name="qwen27b-16k",
    base_url="http://127.0.0.1:8888/v1",
    model="unsloth/Qwen3.8-27B-GGUF",
    api_key_env="UNSLOTH_API_KEY",
    context_budget=16384,
    max_output_tokens=4096,
)
PROFILES = {STRATA.name: STRATA, QWEN.name: QWEN}
SKIPPED = {"qwen27b-24k": "Model endpoint'ine ulaşılamadı: http://127.0.0.1:8888/v1."}


def result(
    qid: str,
    outcome: str,
    *,
    submitted: bool | None = None,
    peak: int = 0,
    reported: int = 0,
    seconds: float = 0.0,
    tags: tuple[str, ...] = (),
    trimmed: int = 0,
    overflows: int = 0,
) -> QuestionResult:
    """Tek sorunun ölçümü; ``submitted`` verilmemişse submit etmiş demek sonuçla aynı şey."""
    return QuestionResult(
        id=qid,
        question=f"{qid} sorusu?",
        outcome=outcome,
        submitted=(outcome == "pass") if submitted is None else submitted,
        max_prompt_tokens=reported,
        peak_estimate=peak,
        seconds=seconds,
        tags=list(tags),
        trimmed=trimmed,
        overflows=overflows,
    )


# strata/full_rules iki tekrar: 1. tekrarda Q02 yanlış, ikincisinde doğru.
STRATA_RULES = [
    [
        result("Q01", "pass", peak=9000, reported=8000, seconds=2.0, tags=("trap",)),
        result(
            "Q02", "wrong_result", submitted=False, peak=4000, reported=3000,
            seconds=4.0, tags=("join",),
        ),
    ],
    [
        result("Q01", "pass", peak=8000, reported=7000, seconds=6.0, tags=("trap",)),
        result("Q02", "pass", peak=1000, reported=500, seconds=2.0, tags=("join",)),
    ],
]
# strata/rag tek tekrar: Q01 bütçeye sığmıyor, Q02 geçiyor.
STRATA_RAG = [
    [
        result("Q01", "context_overflow", peak=20000, seconds=0.5, tags=("trap",), trimmed=2, overflows=1),
        result("Q02", "pass", peak=3000, reported=2500, seconds=1.5, tags=("join",)),
    ]
]
# 16K'lık pencere: full_rules'ta cevap var, rag'de hiçbir soru bütçeye sığmıyor.
QWEN_RULES = [
    [
        result("Q01", "pass", peak=9000, reported=8500, seconds=3.0),
        result("Q02", "wrong_result", submitted=True, peak=8000, reported=7500, seconds=5.0),
    ]
]
QWEN_RAG = [
    [
        result("Q01", "context_overflow", peak=13000, seconds=0.1, overflows=1),
        result("Q02", "context_overflow", peak=14000, seconds=0.3, overflows=1),
    ]
]
CELLS = {
    STRATA.name: {"full_rules": STRATA_RULES, "rag": STRATA_RAG},
    QWEN.name: {"full_rules": QWEN_RULES, "rag": QWEN_RAG},
}


def report(dataset="wwi"):
    return compare_models.build_model_compare(CELLS, PROFILES, dataset, SKIPPED)


def cell(rep, model, mode):
    return rep["cells"][model][mode]


# ------------------------------------------------------------------ hücre ölçümleri


def test_cell_averages_answered_and_peaks():
    # geçenler tekrar başına [1, 2] -> ort 1.5; 4 ölçümün 3'ü submit edildi -> %75.
    assert cell(report(), STRATA.name, "full_rules") == {
        "profile": {"model": "strata", "context_budget": 262144, "prompt_limit": 253952},
        "scores": {"mean": 1.5, "min": 1, "max": 2},
        "answered_pct": 75,
        "peak_estimate": 9000,
        "peak_reported": 8000,
        "overflows": 0,
        "trimmed": 0,
        "seconds_per_question": 3.5,
        "tags": {
            "trap": {"mean": 1.0, "min": 1, "max": 1},
            "join": {"mean": 0.5, "min": 0, "max": 1},
        },
        "outcomes": {"Q01": ["pass", "pass"], "Q02": ["wrong_result", "pass"]},
    }


def test_overflow_cell_counts_its_own_numbers():
    # tek tekrar, bir geçen; taşma ve kırpma toplanır, sürelerin ortalaması (0,5 + 1,5)/2 = 1,0.
    rag = cell(report(), STRATA.name, "rag")
    assert rag["scores"] == {"mean": 1.0, "min": 1, "max": 1}
    assert rag["answered_pct"] == 50
    assert rag["peak_estimate"] == 20000
    assert rag["peak_reported"] == 2500
    assert rag["overflows"] == 1
    assert rag["trimmed"] == 2
    assert rag["seconds_per_question"] == 1.0
    assert rag["outcomes"] == {"Q01": ["context_overflow"], "Q02": ["pass"]}


def test_tiny_window_cell_overflows_every_question():
    qwen = cell(report(), QWEN.name, "rag")
    assert qwen["answered_pct"] == 0
    assert qwen["overflows"] == 2
    assert qwen["peak_estimate"] == 14000
    assert qwen["profile"]["prompt_limit"] == 12288


def test_cell_without_a_profile_keeps_zeros_not_none():
    rep = compare_models.build_model_compare(CELLS, {}, "wwi")
    assert cell(rep, QWEN.name, "full_rules")["profile"] == {
        "model": "",
        "context_budget": 0,
        "prompt_limit": 0,
    }


# ------------------------------------------------------------------ raporun kendisi


def test_report_names_models_modes_questions_and_repeat():
    rep = report(types.SimpleNamespace(name="wwi", display_name="WWI"))
    assert rep["models"] == [STRATA.name, QWEN.name]
    assert rep["modes"] == ["full_rules", "rag"]
    assert rep["questions"] == 2
    assert rep["repeat"] == 2
    assert rep["dataset"] == "wwi"
    assert rep["skipped"] == SKIPPED
    assert re.match(r"^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d$", rep["timestamp"])


def test_empty_cells_still_make_a_readable_report():
    rep = compare_models.build_model_compare({}, {}, None, None)
    assert rep["dataset"] == ""
    assert rep["cells"] == {}
    assert rep["skipped"] == {}
    assert compare_models.console_lines(rep) == []
    assert "Model x mod" in compare_models.render_model_compare(rep)


# ------------------------------------------------------------------ ekran ve markdown


def test_console_lines_are_the_r4_14_form_plus_the_skips():
    lines = compare_models.console_lines(report())
    assert lines[0] == (
        f"{STRATA.name} | full_rules | 1.5/2 (ort.) | cevap %75 "
        "| tepe 9.0K/254.0K | taşma 0 | 3.5 sn/soru"
    )
    assert len(lines) == 5  # dört hücre + bir atlanan
    assert lines[-1] == f"⚠ qwen27b-24k: {SKIPPED['qwen27b-24k']}"


def test_markdown_shows_every_cell_tag_and_skip():
    text = compare_models.render_model_compare(report())
    for model in (STRATA.name, QWEN.name):
        for mode in ("full_rules", "rag"):
            assert f"| {model} | {mode} | " in text
    assert "## Etiket skorları" in text
    # kolonlar hücre sırasıyla: etiketi olmayan iki hücre "-" taşır, uydurulmuş 0 değil.
    assert "| trap | 1/1/1 | 0/0/0 | - | - |" in text
    assert "| join | 0.5/0/1 | 1/1/1 | - | - |" in text
    assert "## Atlanan modeller" in text
    assert "`qwen27b-24k`" in text
    assert "tepe 14.0K/12.3K" in text  # 16K pencerede taşan hücre kendi bütçesiyle yazılır


def test_markdown_without_skips_leaves_the_section_out():
    rep = compare_models.build_model_compare(CELLS, PROFILES, "mini")
    assert "Atlanan" not in compare_models.render_model_compare(rep)


# ------------------------------------------------------------------ dosyalar


def test_write_model_compare_writes_both_files_under_its_own_name(tmp_path):
    rep = report()
    path = compare_models.write_model_compare(rep, tmp_path)
    assert re.match(r"^compare_wwi_\d{8}-\d{6}\.md$", path.name)
    json_path = path.with_suffix(".json")
    assert json_path.exists() and path.exists()
    assert json.loads(json_path.read_text(encoding="utf-8")) == rep
    assert path.read_text(encoding="utf-8") == compare_models.render_model_compare(rep)


def test_write_model_compare_falls_back_to_a_nameless_file(tmp_path):
    rep = compare_models.build_model_compare(CELLS, PROFILES, None)
    path = compare_models.write_model_compare(rep, tmp_path)
    assert re.match(r"^compare_dataset_\d{8}-\d{6}\.md$", path.name)
    assert path.exists()


# ------------------------------------------------------------------ ping


def closed_url() -> str:
    """Boşta bir bağlantı noktası al, bırak: orada dinleyen hiçbir şey yok."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    return f"http://127.0.0.1:{port}/v1"


def test_ping_closed_port_returns_the_reason_naming_the_url():
    url = closed_url()
    reason = llm.ping(
        ModelProfile(name="kapali", base_url=url, model="yok", context_budget=8192),
        timeout_s=0.5,
    )
    assert reason and url in reason and "ulaşılamadı" in reason


def test_ping_returns_none_when_the_endpoint_answers(monkeypatch):
    asked = []
    monkeypatch.setattr(
        llm.OpenAIClient, "list_models", lambda self, timeout_s=None: asked.append(timeout_s)
    )
    assert llm.ping(STRATA, timeout_s=0.25) is None
    assert asked == [0.25]


def test_ping_reports_a_missing_key_instead_of_raising(monkeypatch):
    monkeypatch.delenv("UNSLOTH_API_KEY", raising=False)
    reason = llm.ping(QWEN)
    assert reason and "UNSLOTH_API_KEY" in reason
