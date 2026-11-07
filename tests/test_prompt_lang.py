# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""Cevabın dili ajana tek satırla iner (PLAN R8-9).

İki iddia sınanıyor: Türkçe istem bugün neyse odur, İngilizce istem ise onunla aynı ve sonda tek
bir satır daha var. Satır üslubu değil dili söylediği için üç modun isteminde de durmalı, ama
modele gösterilen araçlarda bir şey değiştirmemeli - İngilizce cevap veren bir koşumun
çağırabilecekleri Türkçe koşumla bayt bayt aynı.
"""

from dataclasses import replace

import pytest

from nl2sql import config
from nl2sql.agent import loop, modes, prompt
from nl2sql.agent.fake import FALLBACK_SQL, FakeLLM
from nl2sql.agent.llm import ChatResponse, ToolCall
from nl2sql.engine.executor import LocalExecutor
from nl2sql.schema_map import build, doc
from nl2sql.schema_map.rules import load_rules

QUESTION = "Ankara'daki alıcı carilerin kodu ve ünvanı nedir?"
LINE = prompt.ANSWER_LANG_LINE

# Her modda ilk turda submit edilen tek senaryo: burada ölçülen sistem mesajı, araçların sırası değil.
SUBMIT = ChatResponse(tool_calls=[ToolCall(id="c1", name="submit_sql", arguments={"sql": FALLBACK_SQL})])


@pytest.fixture(scope="module")
def schema():
    return doc.load_schema()


@pytest.fixture(scope="module")
def rules():
    return load_rules()


@pytest.fixture(scope="module")
def executor(tmp_path_factory):
    paths = tmp_path_factory.mktemp("promptlang")
    db = paths / "test.db"
    build.build_db(config.SEED, db, paths / "test.sql")
    return LocalExecutor("sqlite", db, audit_path=paths / "audit.jsonl")


def _lang(lang: str | None) -> dict:
    """Dili söylememek ile "tr" demek ayrı çağrılar: birincisi bugünkü baytların kendisi."""
    return {} if lang is None else {"answer_lang": lang}


def builders(schema: dict, rules: list) -> dict:
    """Dört istemin dili çevrilebilir halleri; anahtarlar fonksiyon adlarıyla aynı."""
    return {
        "system_prompt": lambda lang=None: prompt.system_prompt(
            config.AS_OF, "TBLSTHAR — Stok hareketleri", **_lang(lang)
        ),
        "full_prompt": lambda lang=None: prompt.full_prompt(config.AS_OF, schema, **_lang(lang)),
        "full_rules_prompt": lambda lang=None: prompt.full_rules_prompt(
            config.AS_OF, schema, rules, **_lang(lang)
        ),
        "rag_prompt": lambda lang=None: prompt.rag_prompt(config.AS_OF, schema, **_lang(lang)),
    }


def system_of(executor, schema: dict, rules: list, mode: str, answer_lang: str) -> str:
    """Döngünün modele gönderdiği sistem mesajı; bağlamı run_agent'ın dili kuruyor."""
    seen = []

    def script(messages):
        seen.append(messages)
        return [SUBMIT]

    context = modes.ToolContext(executor=executor, schema=schema, rules=rules, mode=mode)
    result = loop.run_agent(
        QUESTION, FakeLLM(script), executor, schema, "test",
        mode=mode, context=context, answer_lang=answer_lang,
    )
    assert result.status == "submitted"
    return seen[0][0]["content"]


# ------------------------------------------------------------------ istemler


def test_the_language_line_is_one_english_line():
    assert LINE.startswith("Answer language: English") and LINE.endswith(".")
    assert "\n" not in LINE and LINE == LINE.strip()


@pytest.mark.parametrize("name", sorted(builders({}, [])))
def test_the_turkish_prompt_is_unchanged(name, schema, rules):
    text = builders(schema, rules)[name]
    assert text("tr") == text()
    assert LINE not in text("tr")


@pytest.mark.parametrize("name", sorted(builders({}, [])))
def test_the_english_prompt_is_the_turkish_one_plus_the_line(name, schema, rules):
    text = builders(schema, rules)[name]
    assert text("en") == text("tr") + LINE + "\n"
    assert text("en").count(LINE) == 1


@pytest.mark.parametrize("mode", sorted(config.MODES))
def test_every_mode_hands_its_prompt_the_language(mode, schema, rules):
    def text(lang, **given):
        context = modes.ToolContext(
            executor=None, schema=schema, rules=rules, mode=mode, answer_lang=lang, **given
        )
        return modes.system_prompt(context)

    assert text("en") == text("tr") + LINE + "\n"
    # Açıklama sorusu açıksa satır yine oradadır: seçeneklerin dili de İngilizce olacak.
    assert LINE in text("en", clarify=True)


@pytest.mark.parametrize("mode", sorted(config.MODES))
def test_the_tools_are_the_same_in_both_languages(mode, schema, rules):
    context = modes.ToolContext(
        executor=None, schema=schema, rules=rules, mode=mode, clarify=True
    )
    assert modes.mode_tools(replace(context, answer_lang="en")) == modes.mode_tools(context)


# ------------------------------------------------------------------ döngü


@pytest.mark.parametrize("mode", sorted(config.MODES))
def test_the_run_shows_the_line_only_for_english(mode, executor, schema, rules):
    turkish = system_of(executor, schema, rules, mode, "tr")
    english = system_of(executor, schema, rules, mode, "en")
    assert LINE not in turkish
    assert english == turkish + LINE + "\n"


def test_the_default_run_is_turkish(executor, schema, rules):
    """Koşum dili söylemeyince hiçbir şey eklenmez: Run 1-7'nin istemi varsayılanın ta kendisi."""
    seen = []

    def script(messages):
        seen.append(messages)
        return [SUBMIT]

    loop.run_agent(QUESTION, FakeLLM(script), executor, schema, "test")
    assert LINE not in seen[0][0]["content"]
