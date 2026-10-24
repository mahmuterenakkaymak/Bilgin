"""Döngü bağlam bütçesini zorlar: her çağrı öncesi tahmin, sığmazsa kalıcı kırpma, yetmezse taşma.

Model yine yok; FakeLLM senaryo oynatıyor, veritabanı gerçek (build_db ile kurulmuş SQLite üzerinde
LocalExecutor). Ölçülen döngünün R4-11 sözleşmesi: llm.chat öncesi istem tahmin ediliyor, bütçeyi
aşan sohbet trim_tool_answers ile kalıcı olarak kırpılıyor, kırpma da yetmezse modele HİÇ gitmeden
context_overflow ile duruluyor. Bütçe None ise ne kırpma ne taşma var; transcript bugünküle birebir
aynı, yalnız tepe tahmini doluyor. Bütçeler kırılgan sabitler olmasın diye bütçesiz bir ön koşudan
ölçülüyor: modele giden gerçek transcript'in tahmininin hemen altına/aşırına yerleştiriliyor.
"""

import pytest

from nl2sql import config
from nl2sql.agent import budget, loop, modes
from nl2sql.agent.fake import FakeLLM, golden_replay
from nl2sql.agent.llm import ChatResponse, ToolCall
from nl2sql.engine.executor import LocalExecutor
from nl2sql.graph.graph import build_graph
from nl2sql.graph.profile import load_profile
from nl2sql.index.embed import FakeEmbedder
from nl2sql.index.search import build_search
from nl2sql.schema_map import build, doc
from nl2sql.schema_map.rules import load_rules

GOLDEN = "SELECT CARI_KOD, CARI_ISIM FROM TBLCASABIT WHERE IL = 'ANKARA' ORDER BY CARI_KOD"
QUESTION = "Ankara'daki alıcı carilerin kodu ve ünvanı nedir?"

# Detayı TOOL_RESULT_MAX_CHARS'a dayanan geniş tablo listesi; kırpılacak uzun araç cevabı buradan.
WIDE = ["TBLCASABIT", "TBLFATUIRS", "TBLSTHAR", "TBLSTHAR_ARSIV"]
RAG_TOOLS = modes.get_mode("rag").tools


@pytest.fixture(scope="module")
def schema():
    return doc.load_schema()


@pytest.fixture(scope="module")
def rules():
    return load_rules()


@pytest.fixture(scope="module")
def search(schema, rules):
    return build_search(schema, rules, FakeEmbedder())


@pytest.fixture(scope="module")
def graph(schema):
    return build_graph(schema, load_profile())


@pytest.fixture(scope="module")
def executor(tmp_path_factory):
    paths = tmp_path_factory.mktemp("budget")
    db = paths / "test.db"
    build.build_db(config.SEED, db, paths / "test.sql")
    return LocalExecutor("sqlite", db, audit_path=paths / "audit.jsonl")


def world(executor, schema, rules, search, graph):
    return modes.ToolContext(
        executor=executor, schema=schema, rules=rules, search=search, graph=graph, mode="rag"
    )


def ask(name: str, **arguments) -> ChatResponse:
    return ChatResponse(tool_calls=[ToolCall(id="", name=name, arguments=arguments)])


def details() -> ChatResponse:
    return ask("get_table_details", tables=WIDE)


class Recorder:
    """Senaryoyu oynatırken modele giden sohbeti ve çağrı sayısını saklar; bütçe ölçümü buradan."""

    def __init__(self, script):
        self._llm = FakeLLM(script)
        self.calls = 0
        self.seen = []

    def chat(self, messages, tools=None):
        self.calls += 1
        self.seen.append([dict(message) for message in messages])
        return self._llm.chat(messages, tools)


def measure(executor, schema, rules, search, graph, script):
    """Bütçesiz bir ön koşu: üçüncü çağrıya giden gerçek sohbetin tahminini döndürür."""
    probe = Recorder(script)
    loop.run_agent(
        QUESTION, probe, executor, schema, "test", mode="rag", context=world(executor, schema, rules, search, graph), budget=None
    )
    return budget.estimate_prompt(probe.seen[2], RAG_TOOLS)


def run(executor, schema, rules, search, graph, script, limit):
    return loop.run_agent(
        QUESTION,
        Recorder(script),
        executor,
        schema,
        "test",
        mode="rag",
        context=world(executor, schema, rules, search, graph),
        budget=limit,
    )


# İki uzun araç cevabı, sonra submit: üçüncü çağrı öncesi sohbet bütçeyi aşar, eski cevap kırpılır.
def _script():
    return [details(), details(), ask("submit_sql", sql=GOLDEN)]


# ------------------------------------------------------------------ kırpma ama yine de submit

def test_a_tight_budget_trims_old_answers_and_still_submits(executor, schema, rules, search, graph):
    over = measure(executor, schema, rules, search, graph, _script())
    result = run(executor, schema, rules, search, graph, _script(), over - 1)
    assert result.status == "submitted"
    assert result.submitted_sql == GOLDEN
    assert result.trimmed > 0, "sığmayan eski araç cevabı kısaltılmalı"
    assert result.overflows == 0


def test_a_submitted_run_never_sends_more_than_the_budget(executor, schema, rules, search, graph):
    over = measure(executor, schema, rules, search, graph, _script())
    limit = over - 1
    result = run(executor, schema, rules, search, graph, _script(), limit)
    assert result.status == "submitted"
    assert result.peak_estimate <= limit, "gönderilen her istem bütçenin içinde kalmalı"


# ------------------------------------------------------------------ sistem istemi sığmıyor

def test_a_system_prompt_over_the_budget_overflows_before_the_first_call(executor, schema):
    recorder = Recorder(golden_replay(GOLDEN))
    result = loop.run_agent(QUESTION, recorder, executor, schema, "test", budget=100)
    assert result.status == "context_overflow"
    assert recorder.calls == 0, "taşma tur 1'de: modele hiç gidilmez"
    assert result.overflows == 1
    assert result.trimmed == 0, "henüz kırpılacak araç cevabı yok"
    assert result.peak_estimate > 100, "reddedilen tahmin tepe olarak kaydedilir"
    assert "Bağlam bütçesi aşıldı" in result.stop_reason
    assert "sınır 100 token" in result.stop_reason


# ------------------------------------------------------------------ üçüncü turda taşma

def test_a_budget_that_overflows_on_the_third_turn_calls_the_model_twice(
    executor, schema, rules, search, graph
):
    # Bütçe = ikinci çağrının tahmini: tur 1 ve 2 tam sığar, tur 3 kırpma sonrası da taşar.
    limit = measure_second_turn(executor, schema, rules, search, graph)
    recorder = Recorder(_script())
    result = loop.run_agent(
        QUESTION,
        recorder,
        executor,
        schema,
        "test",
        mode="rag",
        context=world(executor, schema, rules, search, graph),
        budget=limit,
    )
    assert result.status == "context_overflow"
    assert recorder.calls == 2, "yalnız ilk iki tur gönderildi, üçüncüsü reddedildi"
    assert result.overflows == 1
    assert result.submitted_sql is None


def measure_second_turn(executor, schema, rules, search, graph):
    probe = Recorder(_script())
    loop.run_agent(
        QUESTION,
        probe,
        executor,
        schema,
        "test",
        mode="rag",
        context=world(executor, schema, rules, search, graph),
        budget=None,
    )
    return budget.estimate_prompt(probe.seen[1], RAG_TOOLS)


# ------------------------------------------------------------------ bütçe yok

def test_no_budget_leaves_only_the_peak_estimate_filled(executor, schema):
    result = loop.run_agent(QUESTION, FakeLLM(golden_replay(GOLDEN)), executor, schema, "test")
    assert result.status == "submitted"
    assert result.trimmed == 0
    assert result.overflows == 0
    assert result.peak_estimate > 0, "tepe tahmini bütçesiz de ölçülür"
