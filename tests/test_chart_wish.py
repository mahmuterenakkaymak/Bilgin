# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""T296: grafik istekleri (PLAN R7-10).

``chart_wish`` soruda hangi grafik türünün istendiğini, ``chart_only`` sorunun *yalnızca* sunumu
değiştirip değiştirmediğini söyler: istekle dolgu ve önceki tura bağlayan işaretler düşünce geriye
yeni bir bilgi kalmamalı ve yeniden koşulacak yanıtlanmış bir tur bulunmalı.
"""

from nl2sql.agent.refine import CHART_WISHES, chart_only, chart_wish


def turn(n=1, status="answered", sql="SELECT 1"):
    """Konuşmanın son yanıtlanmış turu (Contracts "history turn" biçimi)."""
    return {"n": n, "question": f"{n}. soru", "choice": None, "status": status, "sql": sql, "summary": {}}


def test_chart_wishes_table():
    assert CHART_WISHES == {
        "line": ("çizgi", "line", "trend"),
        "bar": ("çubuk", "sütun", "bar"),
        "pie": ("pasta", "dilim", "pie"),
        "table": ("tablo", "tablo olarak"),
    }


def test_chart_wish_names_the_kind():
    assert chart_wish("Grafiği çubuk yap") == "bar"
    assert chart_wish("çizgi grafik olarak göster") == "line"
    assert chart_wish("pasta olsun lütfen") == "pie"
    assert chart_wish("Tablo olarak göster") == "table"
    assert chart_wish("Aylık ciro ne kadar?") is None


def test_chart_only_is_presentation_only():
    turns = [turn()]
    assert chart_only("Grafiği çubuk yap", turns) == "bar"
    assert chart_only("çizgi grafik olarak göster", turns) == "line"
    assert chart_only("pasta olsun lütfen", turns) == "pie"
    assert chart_only("Tablo olarak göster", turns) == "table"


def test_chart_only_refuses_a_question_with_new_data():
    turns = [turn()]
    assert chart_only("Sadece Texas, çubuk grafik", turns) is None
    assert chart_only("Çubuk grafikle aylık ciro", turns) is None


def test_chart_only_needs_an_answered_turn():
    assert chart_only("Grafiği çubuk yap", None) is None
    assert chart_only("Grafiği çubuk yap", []) is None
    assert chart_only("Grafiği çubuk yap", [turn(status="needs_clarification")]) is None
    assert chart_only("Grafiği çubuk yap", [turn(sql=None)]) is None


def test_chart_only_accepts_a_history_turn_without_status():
    """last_turnsın döndürdüğü tur zaten yanıtlıdır, status alanı taşımaz."""
    history = {"n": 1, "question": "Aylık ciro ne kadar?", "choice": None, "sql": "SELECT 1", "summary_json": None}
    assert chart_only("Grafiği çubuk yap", [history]) == "bar"
