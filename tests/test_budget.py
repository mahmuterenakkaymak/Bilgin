# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""Bağlam bütçesi: istem tahmini ve araç cevaplarının kısaltılması (PLAN R4-11).

Tahmin karakter sayımıdır, ama testler formülü tekrarlamasın diye içerik uzunlukları
CHARS_PER_TOKEN'in katından seçildi: beklenen sayı doğrudan uzunluklardan okunabiliyor.
Kesintide asıl korunması gereken şey transcript'in geçerli kalması - bir tool mesajı silinirse
cevap verdiği araç çağrısı havada kalır - o yüzden burada ölçülen hem sıralama hem neyin
dokunulmadan kaldığı.
"""

import json

from bilgin import config
from bilgin.agent import budget
from bilgin.schema_map import doc

MARKER = "… (bağlam bütçesi için kısaltıldı: {n} karakter)"


def tool(answer: str) -> dict:
    return {"role": "tool", "tool_call_id": "c1", "content": answer}


def transcript(*answers: str) -> list[dict]:
    """system + user + her cevap için bir tool mesajı; sondaki en yeni araç cevabı."""
    messages = [{"role": "system", "content": "s" * 8}, {"role": "user", "content": "u" * 8}]
    return messages + [tool(answer) for answer in answers]


def test_estimate_is_hand_computable():
    messages = [{"role": "system", "content": "a" * 10}, {"role": "user", "content": "b" * 6}]
    # 16 karakter / 4 = 4 token, artı mesaj başına 4 token * 2 mesaj = 8 token.
    assert budget.estimate_prompt(messages) == 12


def test_a_partial_token_rounds_up():
    # 3 karakter = 1 token (0,75 yukarıya), artı o mesajın payı.
    assert budget.estimate_prompt([{"role": "user", "content": "abc"}]) == (
        1 + config.MESSAGE_OVERHEAD_TOKENS
    )


def test_tool_calls_add_their_own_json():
    call = {
        "id": "c1",
        "type": "function",
        "function": {"name": "run_sql", "arguments": '{"sql": "SELECT 1"}'},
    }
    plain = [{"role": "assistant", "content": ""}]
    echoed = [{"role": "assistant", "content": "", "tool_calls": [call]}]
    added = doc.estimate_tokens(json.dumps(call, ensure_ascii=False))
    assert budget.estimate_prompt(echoed) == budget.estimate_prompt(plain) + added


def test_tool_schemas_are_part_of_the_prompt():
    tools = [{"type": "function", "function": {"name": "run_sql", "parameters": {}}}]
    # 8 karakterlik içerik CHARS_PER_TOKEN'in katı: fark tam olarak şema JSON'u kadar oluyor.
    messages = [{"role": "user", "content": "x" * 8}]
    added = doc.estimate_tokens(json.dumps(tools, ensure_ascii=False))
    assert budget.estimate_prompt(messages, tools) == budget.estimate_prompt(messages) + added


def test_a_transcript_that_already_fits_is_untouched():
    messages = transcript("a" * 1000, "b" * 1000)
    estimate = budget.estimate_prompt(messages)
    trimmed, cuts, result = budget.trim_tool_answers(messages, estimate)
    assert (cuts, result) == (0, estimate)
    assert trimmed == messages


def test_the_oldest_tool_answer_is_cut_first():
    messages = transcript("a" * 1000, "b" * 1000, "c" * 1000)
    trimmed, cuts, estimate = budget.trim_tool_answers(messages, 700)
    assert cuts == 1
    assert trimmed[2]["content"] == "a" * config.TRIM_TOOL_CHARS + MARKER.format(n=600)
    assert trimmed[3]["content"] == "b" * 1000
    assert estimate == budget.estimate_prompt(trimmed)
    assert estimate <= 700


def test_the_marker_names_the_removed_characters():
    trimmed, _, _ = budget.trim_tool_answers(transcript("a" * 401, "b" * 100), 0)
    assert trimmed[2]["content"] == "a" * config.TRIM_TOOL_CHARS + MARKER.format(n=1)


def test_the_newest_tool_answer_is_never_cut():
    trimmed, cuts, _ = budget.trim_tool_answers(transcript("a" * 1000, "b" * 1000), 0)
    assert cuts == 1
    assert trimmed[-1]["content"] == "b" * 1000


def test_only_tool_messages_are_cut():
    prose = "p" * 2000
    messages = [
        {"role": "system", "content": "s" * 2000},
        {"role": "user", "content": "u" * 2000},
        {"role": "assistant", "content": prose},
        tool("a" * 2000),
        tool("b" * 2000),
    ]
    trimmed, cuts, _ = budget.trim_tool_answers(messages, 0)
    assert cuts == 1
    assert [message["content"] for message in trimmed[:3]] == ["s" * 2000, "u" * 2000, prose]


def test_an_answer_already_short_enough_is_left_alone():
    short = "x" * config.TRIM_TOOL_CHARS
    messages = transcript(short, "y" * (config.TRIM_TOOL_CHARS + 1), "z" * 1000)
    trimmed, cuts, _ = budget.trim_tool_answers(messages, 0)
    assert cuts == 1, "tam sınırdaki cevap kısaltılmaz; sınırın 1 üstü kısaltılır"
    assert trimmed[2]["content"] == short
    assert trimmed[3]["content"].endswith(MARKER.format(n=1))


def test_it_stops_as_soon_as_the_estimate_fits():
    messages = transcript("a" * 1000, "b" * 1000, "c" * 1000, "d" * 1000)
    trimmed, cuts, estimate = budget.trim_tool_answers(messages, 800)
    assert cuts == 2, "iki kısaltma 752 token veriyor; üçüncüsüne gerek kalmıyor"
    assert trimmed[4]["content"] == "c" * 1000
    assert estimate <= 800


def test_when_nothing_more_can_be_cut_the_best_estimate_comes_back():
    messages = [
        {"role": "system", "content": "s" * 100_000},
        {"role": "user", "content": "u" * 8},
        tool("a" * 1000),
        tool("b" * 1000),
    ]
    trimmed, cuts, estimate = budget.trim_tool_answers(messages, 1000)
    assert cuts == 1
    assert estimate > 1000
    assert estimate == budget.estimate_prompt(trimmed)


def test_the_input_transcript_is_untouched():
    messages = transcript("a" * 1000, "b" * 1000)
    before = [dict(message) for message in messages]
    trimmed, cuts, _ = budget.trim_tool_answers(messages, 0)
    assert cuts == 1
    assert messages == before
    assert trimmed is not messages
    assert trimmed[2] is not messages[2]
