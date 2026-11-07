# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""T399: takibat ve sunum isteği İngilizce de okunuyor (PLAN R8-9).

Eşikler kelime tablolarından okunduğu için İngilizce bir sorunun sunum değişikliği de modeli
koşurmaz, önceki tura bağlayan işaretleri de bulunur, tekil zamirli varlık sorusu da şıkla
sorulur. Şıkkın cümlesi, kanıt satırı ve modelsiz sunumun cümlesi catalog'un o dilindendir;
Türkçeleri eskisiyle aynıdır. İddialar sözel: veritabanı yok, model yok.
"""

from bilgin.agent import context, refine
from bilgin.agent.context import evidence_line, followup_hints
from bilgin.i18n.scan import user_literals

# Kolon adları ASCII, açıklamaları İngilizce: etiket oradan okunur, teknik ad ekrana çıkmaz.
SCHEMA = {
    "tables": [
        {
            "name": "Sales.Customers",
            "description": "Customers",
            "columns": [
                {"name": "CustomerID", "type": "INT", "description": "Customer; primary key.", "fk": None},
                {"name": "CustomerName", "type": "VARCHAR(100)", "description": "Name of the customer.", "fk": None},
            ],
        }
    ]
}

TR_SCHEMA = {
    "tables": [
        {
            "name": "MUSTERILER",
            "description": "Müşteri kartları",
            "columns": [
                {"name": "MUSTERI_ID", "type": "INT", "description": "Müşteri; birincil anahtar.", "fk": None},
                {"name": "MUSTERI_ADI", "type": "VARCHAR(100)", "description": "Müşterinin adı.", "fk": None},
            ],
        }
    ]
}

NOTE = {"uses_turns": [1], "entities": [{"column": "CustomerID", "value": "832"}], "refines_sql_of": 1}


def answered_turn(n, columns, rows):
    """``chart_only``/``ambiguous_entity``/``evidence_line``ın okuduğu alanlar (Contracts "history turn")."""
    return {
        "n": n,
        "sql": "SELECT * FROM Sales.Customers",
        "status": "answered",
        "summary": {"columns": list(columns), "row_count": len(rows), "rows": [list(row) for row in rows]},
    }


def turns():
    """Yanıtlı tek tur: iki farklı müşteri, yani hangisinin kastedildiği yalnız kullanıcıda."""
    return [answered_turn(1, ["CustomerID", "CustomerName"], [("832", "Tailspin Toys"), ("833", "Wide World")])]


# ------------------------------------------------------------------ sunum değişikliği (R7-10)
def test_english_chart_request_is_presentation_only():
    for question, kind in [
        ("show it as a bar chart", "bar"),
        ("make it a pie chart please", "pie"),
        ("show it as a table", "table"),
    ]:
        assert refine.chart_only(question, turns()) == kind


def test_english_request_that_names_new_data_goes_back_to_the_agent():
    assert refine.chart_only("show it as a bar chart for Texas", turns()) is None


def test_turkish_chart_request_is_unchanged():
    assert refine.chart_only("Grafiği çubuk yap", turns()) == "bar"


# ------------------------------------------------------------------ takibat işaretleri (R7-11)
def test_english_followup_question_gets_markers():
    assert followup_hints("which of these customers bought the most?", SCHEMA)["markers"] == ["these"]


def test_turkish_followup_question_gets_markers():
    assert followup_hints("Bu müşteriye başka ne sattık?", SCHEMA)["markers"] == ["bu"]


# ------------------------------------------------------------------ varlık şıkkı (R7-12)
def test_english_entity_question_and_options():
    asked = refine.ambiguous_entity("this customer", turns(), SCHEMA, lang="en")

    assert asked["question"] == "Which customer do you mean?"
    assert asked["column"] == "CustomerID"
    assert asked["options"] == ["832 (Tailspin Toys)", "833 (Wide World)"]
    assert asked["values"] == ["832", "833"]


def test_plural_english_demonstrative_asks_no_single_entity():
    assert refine.ambiguous_entity("which of these customers bought the most?", turns(), SCHEMA, lang="en") is None


def test_turkish_entity_question_is_unchanged():
    assert refine.ambiguous_entity("Bu müşteri kaç sipariş verdi?", turns(), TR_SCHEMA)["question"] == (
        "Hangi müşteriyi kastediyorsunuz?"
    )


# ------------------------------------------------------------------ kanıt satırı (R7-5)
def test_evidence_line_in_english():
    assert evidence_line(NOTE, turns(), SCHEMA, lang="en") == (
        "From the previous answer: customer 832 (Tailspin Toys)"
    )
    refined = {"uses_turns": [2], "entities": [], "refines_sql_of": 2}
    assert evidence_line(refined, turns(), SCHEMA, lang="en") == (
        "From the previous answer: the query of turn 2 was used."
    )


def test_evidence_line_without_a_description_falls_back_in_english():
    schema = {"tables": [{"name": "Sales.Customers", "columns": [{"name": "CustomerID", "type": "INT"}]}]}

    line = evidence_line({**NOTE, "refines_sql_of": None}, turns(), schema, lang="en")

    assert line == "From the previous answer: value 832 (Tailspin Toys)"


def test_evidence_line_in_turkish_is_unchanged():
    tr_note = {"uses_turns": [1], "entities": [{"column": "MUSTERI_ID", "value": "832"}], "refines_sql_of": 1}

    assert evidence_line(tr_note, turns(), TR_SCHEMA) == "Önceki cevaptan: müşteri 832 (Tailspin Toys)"
    assert evidence_line({"uses_turns": [2], "entities": [], "refines_sql_of": 2}, turns(), SCHEMA) == (
        "Önceki cevaptan: 2. turun sorgusu temel alındı."
    )


# ------------------------------------------------------------------ catalog dışı Türkçe kalmadı
REFINE_TABLES = (
    "CHART_WISHES",
    "CHART_FILLERS",
    "REFINE_HINTS",
    "TOP_WORDS",
    "TOP_HINT",
    "ENTITY_NOUNS",
    "ENTITY_MARKERS",
    "ENTITY_PLURAL",
    "ENTITY_PERIOD_WORDS",
    "_TURKISH_TO_ASCII",
)
CONTEXT_TABLES = ("HISTORY_HEADER", "FOLLOWUP_RULES")


def test_refine_has_no_turkish_literal_left():
    assert user_literals(refine.__file__, allow=REFINE_TABLES) == []


def test_context_says_its_evidence_from_the_catalog():
    # ASSUMPTION: context.pyde kalan Türkçe satırlar modelin okuduğu blok ile not düşme
    # gerekçeleridir - kendi görevlerinin dili taşıyacak; burada ekrana çıkan cümleler catalog'a geçti.
    left = [text for _, text in user_literals(context.__file__, allow=CONTEXT_TABLES)]
    assert [text for text in left if "cevaptan" in text or "temel alındı" in text or text == "değer"] == []
