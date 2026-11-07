# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""T288: context block ve kırpma (PLAN R7-4, Contracts "history turn").

Blok üç turun sırayla sorusu, SQL'i, kolonları ve örnek satırlarıdır; bütçe daralınca önce en eski
tur düşer, sonra kalanların satırları eksilir - kullanıcının çıplak sorusuna hiçbir kesim dokunmaz.
İddialar metinde ve sayaçlarda: sıra, ``CONV_KEEP_ROWS`` sınırı, turun düşmesi, satırın eksilmesi ve
çıplak prompt'un bile sığmadığı bütçe.
"""

from bilgin import config
from bilgin.agent.budget import estimate_prompt
from bilgin.agent.context import context_block, fit_history

SYSTEM = "Sen ERP şeması üzerinde çalışan bir SQL asistanısın."
QUESTION = "Peki bu müşterinin toplamı ne kadar?"


def turn(n, rows=8, row_count=40):
    """Konuşma deposundan çıkmış gibi bir history turn (Contracts "history turn")."""
    return {
        "n": n,
        "question": f"{n}. soru",
        "choice": None,
        "sql": f"SELECT TOP {row_count} * FROM TBLMÜŞTERİ WHERE N = {n}",
        "summary": {
            "columns": ["CARI_KOD", "ADI"],
            "row_count": row_count,
            "rows": [[100 + i, f"Müşteri {i}"] for i in range(rows)],
            "facts": [],
            "chart_kind": None,
            "context": None,
            "clarification": None,
        },
    }


def messages():
    return [{"role": "system", "content": SYSTEM}, {"role": "user", "content": QUESTION}]


def estimate(turns, msgs):
    """Blok system mesajının sonundaymış gibi tahmin - fit_history'nin ölçtüğü şey."""
    probe = [{"role": "system", "content": SYSTEM + "\n\n" + context_block(turns, None)}, msgs[1]]
    return estimate_prompt(probe, None)


def test_three_turns_render_in_order_with_their_sql_and_kept_rows():
    block = context_block([turn(1), turn(2), turn(3)], {"markers": ["bu", "peki"], "table_noun": True})

    assert block.startswith("## Önceki turlar")
    starts = [block.index(f"Tur {n} sorusu: {n}. soru") for n in (1, 2, 3)]
    assert starts == sorted(starts)
    for n in (1, 2, 3):
        assert f"Tur {n} SQL: SELECT TOP 40 * FROM TBLMÜŞTERİ WHERE N = {n}" in block
        assert f"Tur {n} kolonlar: CARI_KOD | ADI" in block
        assert f"Tur {n} satırlar ({config.CONV_KEEP_ROWS} / 40):" in block
    assert block.count("100 | Müşteri 0") == 3
    assert "105 | Müşteri 5" not in block
    assert "bu, peki" in block
    assert "önceki turlardaki bir sayıyı cevaba kopyalama" in block
    assert "submit_sql'in context alanını doldur" in block


def test_a_tight_budget_drops_turn_1_first_then_rows():
    turns = [turn(1), turn(2), turn(3)]
    msgs = messages()
    before = [dict(message) for message in msgs]
    budget = estimate(turns[1:], msgs) - 1

    kept, rows_dropped, result = fit_history(turns, msgs, None, budget)

    assert kept == 2 and [item["n"] for item in turns] == [2, 3]
    assert rows_dropped >= 1
    assert len(turns[0]["summary"]["rows"]) == config.CONV_KEEP_ROWS - rows_dropped
    assert result <= budget
    assert msgs == before
    assert msgs[1]["content"] == QUESTION


def test_a_budget_below_the_bare_prompt_keeps_no_turn_and_returns_the_overflow():
    turns = [turn(1), turn(2), turn(3)]
    msgs = messages()
    budget = estimate_prompt(msgs, None) - 1

    kept, _, result = fit_history(turns, msgs, None, budget)

    assert kept == 0 and turns == []
    assert result == estimate_prompt(msgs, None) > budget


def test_no_budget_keeps_every_turn_and_row():
    turns = [turn(1), turn(2), turn(3)]
    msgs = messages()

    kept, rows_dropped, result = fit_history(turns, msgs, None, None)

    assert (kept, rows_dropped) == (3, 0)
    assert [item["n"] for item in turns] == [1, 2, 3]
    assert len(turns[0]["summary"]["rows"]) == 8
    assert result == estimate(turns, msgs)
