# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""Koşu modunu ve etiketini taşır: seçimi, skorları ve imzası (T62).

Model yine yok; veritabanı, arama indeksi ve join graph gerçek. Üç şey bir arada görülüyor:
runner'ın etiket filtresi ile modu sorunun sonuna kadar taşıması (rag'da bağlam gerçekten
araçlara ulaşıyor), raporun modu ve etiket başına skoru kaydetmesi, imzanın aynı ölçümü aynı
sayıp altın, kural ya da mod değişince kendisinin değişmesi.
"""

import json

import pytest

from nl2sql import config
from nl2sql.agent import fake, modes
from nl2sql.engine.executor import LocalExecutor
from nl2sql.eval import report, runner
from nl2sql.eval.runner import QuestionResult
from nl2sql.graph.graph import build_graph
from nl2sql.graph.profile import load_profile
from nl2sql.index.embed import FakeEmbedder
from nl2sql.index.search import build_search
from nl2sql.schema_map import build, doc
from nl2sql.schema_map.rules import load_rules

GOLDEN = runner.load_golden()
BY_ID = {line["id"]: line for line in GOLDEN}
SCHEMA = doc.load_schema()
RULES = load_rules()

ARCHIVE = [line["id"] for line in GOLDEN if "archive" in line["tags"]]
IPTAL = [line["id"] for line in GOLDEN if "trap:iptal" in line["tags"]]

# Rapor tarafının sahte koşusu: iki etiket üç soruya dağılıyor, Q02 tek kaybeden.
SCORES = {"Q01": "pass", "Q02": "wrong_result", "Q03": "pass"}
TAGS = {"Q01": ["archive", "multi_join"], "Q02": ["archive"], "Q03": ["multi_join"]}


@pytest.fixture(scope="module")
def executor(tmp_path_factory):
    paths = tmp_path_factory.mktemp("eval-modes")
    db = paths / "test.db"
    build.build_db(config.SEED, db, paths / "test.sql")
    return LocalExecutor("sqlite", db, audit_path=paths / "audit.jsonl")


@pytest.fixture(scope="module")
def search():
    return build_search(SCHEMA, RULES, FakeEmbedder())


@pytest.fixture(scope="module")
def graph():
    return build_graph(SCHEMA, load_profile())


def run(executor, llm, golden=GOLDEN, **kwargs):
    return runner.run_eval(lambda: llm, executor, golden, **kwargs)


def made(outcomes: dict[str, str] = SCORES, tags: dict[str, list[str]] | None = None,
         mode: str = "rag") -> list[QuestionResult]:
    """Rapor testlerinin sahte koşusu: etiketler soru başına elle veriliyor."""
    tags = TAGS if tags is None else tags
    return [
        QuestionResult(
            id=qid,
            question="Soru?",
            outcome=outcome,
            sql="SELECT 1",
            golden_sql="SELECT 1",
            reason="" if outcome == "pass" else "Satırlar farklı: 1 satır karşı tarafta yok.",
            tool_calls=3,
            max_prompt_tokens=1000,
            total_tokens=2000,
            seconds=1.0,
            mode=mode,
            tags=tags.get(qid, []),
        )
        for qid, outcome in outcomes.items()
    ]


def written(run_dir) -> dict:
    return json.loads((run_dir / "report.json").read_text(encoding="utf-8"))


def markdown(run_dir) -> str:
    return (run_dir / "report.md").read_text(encoding="utf-8")


def fp(**changes) -> dict:
    """Tam altın kümesiyle imza; bir alan değişince imzanın döndüğünü sınayan testler bunu kullanır."""
    args = {
        "mode": "full",
        "llm": "fake",
        "model": "strata",
        "golden": GOLDEN,
        "schema": SCHEMA,
        "rules": RULES,
        "index_hash": "",
        "max_tool_calls": config.MAX_TOOL_CALLS_BY_MODE["full"],
    }
    args.update(changes)
    return report.fingerprint(**args)


# ------------------------------------------------------------------ etiket filtresi


def test_a_tag_keeps_only_the_questions_carrying_it(executor):
    assert IPTAL, "senaryo boş bir kümenin üzerinde geçmesin"
    results = run(executor, fake.for_golden(GOLDEN), tags=["trap:iptal"])
    assert [result.id for result in results] == IPTAL
    assert all(result.outcome == "pass" for result in results)


def test_several_tags_keep_the_union_in_golden_order(executor):
    wanted = {"archive", "trap:cok_depo"}
    results = run(executor, fake.for_golden(GOLDEN), tags=sorted(wanted))
    assert [result.id for result in results] == [
        line["id"] for line in GOLDEN if wanted & set(line["tags"])
    ]
    assert set(ARCHIVE) <= {result.id for result in results}
    assert all(wanted & set(result.tags) for result in results)


def test_the_id_filter_and_the_tag_filter_meet_on_the_intersection(executor):
    results = run(executor, fake.for_golden(GOLDEN), only=["Q01", "Q02"], tags=["needs_values"])
    assert [result.id for result in results] == ["Q01"]


def test_a_tag_no_question_carries_runs_nothing(executor):
    assert run(executor, fake.for_golden(GOLDEN), tags=["boyle_bir_etiket_yok"]) == []


# ------------------------------------------------------------------ mod ve bağlam


def test_every_result_carries_the_mode_and_its_own_tags(executor):
    results = run(executor, fake.for_golden(GOLDEN), only=["Q03", "Q04"], mode="full_rules")
    assert [result.outcome for result in results] == ["pass", "pass"]
    assert [result.mode for result in results] == ["full_rules", "full_rules"]
    assert [result.tags for result in results] == [BY_ID["Q03"]["tags"], BY_ID["Q04"]["tags"]]


def test_a_line_without_tags_still_runs_in_full_mode(executor):
    line = {**BY_ID["Q01"], "tags": []}
    results = run(executor, fake.for_golden([line]), [line])
    assert (results[0].mode, results[0].tags) == ("full", [])
    assert results[0].outcome == "pass"


def test_the_context_reaches_the_tools_of_the_mode(executor, search, graph):
    """Bağlam boş bir süs değil: arama ve graph olmadan rag yolunun araç adımları düşer."""
    lines = [BY_ID["Q04"]]
    context = modes.ToolContext(
        executor=executor, schema=SCHEMA, rules=RULES, search=search, graph=graph, mode="rag"
    )
    results = run(executor, fake.for_golden(lines, mode="rag"), lines, mode="rag", context=context)
    assert (results[0].mode, results[0].outcome) == ("rag", "pass")
    assert [step.tool for step in results[0].steps] == [
        "search_schema",
        "get_table_details",
        "find_join_path",
        "run_sql",
        "submit_sql",
    ]
    assert all(step.ok for step in results[0].steps)


# ------------------------------------------------------------------ rapor


def test_the_report_scores_every_tag(tmp_path):
    data = written(report.write_report(made(), tmp_path, model="fake", mode="rag"))
    assert data["mode"] == "rag"
    assert data["tags"] == {
        "archive": {"passed": 1, "total": 2},
        "multi_join": {"passed": 2, "total": 2},
    }
    assert [question["mode"] for question in data["questions"]] == ["rag"] * 3
    assert data["questions"][0]["tags"] == TAGS["Q01"]


def test_the_markdown_names_the_mode_and_tables_the_tags(tmp_path):
    text = markdown(report.write_report(made(), tmp_path, model="fake", mode="rag"))
    assert "- Mod: rag" in text
    assert "## Etiket skorları" in text
    assert "| archive | 1/2 |" in text
    assert "| multi_join | 2/2 |" in text


def test_a_run_without_tags_writes_no_tag_table(tmp_path):
    text = markdown(report.write_report(made(tags={}), tmp_path, model="fake", mode="full"))
    assert "- Mod: full" in text
    assert "Etiket" not in text


def test_two_modes_in_their_own_directories_have_nothing_to_compare(tmp_path):
    """R2-12: fark aynı modun kendi klasöründe aranır; rag koşusu full'un rakibi olmaz."""
    report.write_report(made(), tmp_path / "full", model="fake", mode="full")
    run_dir = report.write_report(made(), tmp_path / "rag", model="fake", mode="rag")
    assert written(run_dir)["previous"] is None
    assert (tmp_path / "rag" / "latest" / "report.md").exists()


# ------------------------------------------------------------------ imza


def test_the_fingerprint_carries_every_contract_field():
    assert set(fp()) == {
        "mode",
        "llm",
        "model",
        "question_ids",
        "golden_hash",
        "schema_hash",
        "rules_hash",
        "index_hash",
        "max_tool_calls",
    }
    assert fp()["question_ids"] == [line["id"] for line in GOLDEN]


def test_equal_inputs_fingerprint_the_same_way():
    assert fp() == fp()
    assert fp(golden=[dict(line) for line in GOLDEN]) == fp()


def test_a_different_mode_golden_or_rules_is_a_different_fingerprint():
    base = fp()
    assert fp(mode="rag") != base
    assert fp(model="qwen3") != base
    assert fp(max_tool_calls=12) != base
    assert fp(index_hash="abc123") != base
    assert fp(rules=RULES[:-1]) != base
    assert fp(schema={**SCHEMA, "tables": SCHEMA["tables"][:-1]}) != base
    assert fp(golden=GOLDEN[:-1]) != base
    assert fp(golden=[{**GOLDEN[0], "sql": "SELECT 1"}, *GOLDEN[1:]]) != base


def test_a_golden_note_outside_the_measurement_leaves_the_fingerprint_alone():
    """İmza ölçümü tutar: sorunun inceleme notu değişince iki koşu kıyaslanamaz hâle gelmemeli."""
    annotated = [{**line, "notes": "elden", "review": "ok"} for line in GOLDEN]
    assert fp(golden=annotated) == fp()


def test_the_fingerprint_rides_in_the_report_config(tmp_path):
    digest = fp(mode="rag", index_hash="abc123", max_tool_calls=12)
    data = written(
        report.write_report(made(), tmp_path, model="fake", config={"fingerprint": digest}, mode="rag")
    )
    assert data["config"]["fingerprint"] == digest
