# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""Technical column names never reach the user's sentence (2026-10-25, real WideWorldImporters: "StateProvinceName
olarak Texas ...", "GrossProfit toplamı"). A sentence that writes one is asked for once more with the names listed;
if the second one still does, the template speaks. Plain Turkish words that happen to equal a column (`Ciro`)
are not technical and stay allowed.
"""

from types import SimpleNamespace

from bilgin.report import narrate
from bilgin.report.facts import compute_facts

COLUMNS = ["StateProvinceName", "ToplamCiro"]
ROWS = [("Texas", 11957764.15), ("Colorado", 5544840.13)]


class Scripted:
    """Answers the given texts in order and keeps the messages it was sent."""

    def __init__(self, *texts):
        self.texts, self.calls = list(texts), []

    def chat(self, messages, tools):
        self.calls.append(messages)
        return SimpleNamespace(content=self.texts.pop(0))


def run(*texts):
    llm = Scripted(*texts)
    return narrate.narrate("Eyalete göre ciro nedir?", COLUMNS, ROWS, compute_facts(COLUMNS, ROWS), llm), llm


def test_technical_names_are_detected_as_whole_words():
    assert narrate._leaked_names("StateProvinceName olarak Texas öne çıkıyor.", COLUMNS) == ["StateProvinceName"]
    assert narrate._leaked_names("En yüksek ciro Texas'ta.", COLUMNS) == []
    assert narrate._leaked_names("CIRO toplamı", ["CIRO"]) == ["CIRO"]
    assert narrate._leaked_names("Toplam ciro yüksek.", ["Ciro"]) == []      # a Turkish word, not a code
    assert narrate._leaked_names("SATIS_MIKTARI arttı", ["SATIS_MIKTARI"]) == ["SATIS_MIKTARI"]


def test_a_sentence_with_a_column_name_is_asked_again_with_the_names():
    result, llm = run("StateProvinceName olarak Texas 11.957.764,15 ile önde.",
                      "En yüksek ciro 11.957.764,15 ile Texas eyaletinde.")
    assert result.source == "llm_retry" and result.text.startswith("En yüksek ciro")
    assert "StateProvinceName" in result.rejected
    assert "StateProvinceName" in llm.calls[1][-1]["content"]


def test_two_leaking_sentences_fall_back_to_the_template():
    result, _ = run("ToplamCiro Texas için 11.957.764,15.", "ToplamCiro yine Texas'ta 11.957.764,15.")
    assert result.source == "template"
    assert "ToplamCiro" not in result.text and "StateProvinceName" not in result.text


def test_the_prompt_forbids_column_names():
    assert "ASLA" in narrate.SYSTEM and "StateProvinceName" in narrate.SYSTEM
