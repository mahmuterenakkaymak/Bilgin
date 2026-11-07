# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""T290: context notunun doğrulanması ve kanıt satırı (PLAN R7-5, Contracts "ContextNote").

Not modelden gelir, kanıt konuşmadan: doğrulama, kullanılan turun kolonlarında ve maskeli
satırlarında ya da SQL'inde bulunmayan bir değeri tüm notla birlikte düşürür. Kanıt satırı
kullanıcıya teknik kolon adını hiç göstermez - etiket şemadaki açıklamanın başı, parantez
değerin bulunduğu satırın diğer metin hücresidir.
"""

from nl2sql.agent.context import evidence_line, validate_note

SCHEMA = {
    "tables": [
        {
            "name": "TBLCARİ",
            "description": "Cari kartları",
            "columns": [
                {"name": "CARI_KOD", "type": "INT", "description": "Cari kodu; birincil anahtar.", "fk": None},
                {"name": "ADI", "type": "VARCHAR(50)", "description": "Carinin adı.", "fk": None},
                {"name": "IL", "type": "VARCHAR(30)", "description": "Şehir.", "fk": None},
            ],
        }
    ]
}

# wwi_real biçimli: kolon adları İngilizce, kaydın adı ayrı bir metin hücresinde
WWI_SCHEMA = {
    "tables": [
        {
            "name": "Sales.Customers",
            "description": "Müşteriler",
            "columns": [
                {"name": "CustomerID", "type": "INT", "description": "Müşteri; birincil anahtar.", "fk": None},
                {"name": "CustomerName", "type": "VARCHAR(100)", "description": "Müşterinin adı.", "fk": None},
            ],
        }
    ]
}


def turn(n, sql=None, rows=None):
    """Konuşma deposundan çıkmış gibi bir history turn (Contracts "history turn")."""
    return {
        "n": n,
        "question": f"{n}. soru",
        "choice": None,
        "sql": sql or "SELECT TOP 5 CARI_KOD, ADI FROM TBLCARİ WHERE IL = 'Ankara'",
        "summary": {
            "columns": ["CARI_KOD", "ADI"],
            "row_count": 40,
            "rows": [[100 + i, f"Müşteri {i}"] for i in range(5)] if rows is None else rows,
            "facts": [],
            "chart_kind": None,
            "context": None,
            "clarification": None,
        },
    }


def wwi_turn(n=1):
    """wwi_real biçimli tur: müşteri numarası ile müşteri adı aynı satırda."""
    return {
        "n": n,
        "question": "En büyük müşteri kim?",
        "choice": None,
        "sql": "SELECT TOP 5 CustomerID, CustomerName FROM Sales.Customers ORDER BY BuyingDays DESC",
        "summary": {
            "columns": ["CustomerID", "CustomerName"],
            "row_count": 5,
            "rows": [[832, "Tailspin Toys (Head Office)"], [40, "Tailspin Toys (Sales)"]],
            "facts": [],
            "chart_kind": None,
            "context": None,
            "clarification": None,
        },
    }


def turns():
    return [turn(1), turn(2)]


def test_a_note_whose_evidence_is_in_the_turn_stands():
    note = {"uses_turns": [2], "entities": [{"column": "CARI_KOD", "value": "100"}], "refines_sql_of": 2}

    kept, reason = validate_note(note, turns())

    assert reason is None
    assert kept == {"uses_turns": [2], "entities": [{"column": "CARI_KOD", "value": "100"}], "refines_sql_of": 2}


def test_a_value_only_in_the_used_turns_sql_stands():
    note = {"uses_turns": [1], "entities": [{"column": "ADI", "value": "Müşteri 9"}], "refines_sql_of": None}

    kept, reason = validate_note(note, [turn(1, sql="SELECT ADI FROM TBLCARİ WHERE ADI = 'Müşteri 9'")])

    assert reason is None
    assert kept["entities"] == [{"column": "ADI", "value": "Müşteri 9"}]


def test_the_evidence_is_compared_as_folded_text():
    note = {"uses_turns": [1], "entities": [{"column": "adi", "value": "MÜŞTERİ 0"}], "refines_sql_of": None}

    assert validate_note(note, [turn(1)]) == (
        {"uses_turns": [1], "entities": [{"column": "adi", "value": "MÜŞTERİ 0"}], "refines_sql_of": None},
        None,
    )


def test_a_missing_note_is_an_empty_note_and_never_invalid():
    empty = {"uses_turns": [], "entities": [], "refines_sql_of": None}

    assert validate_note(None, turns()) == (empty, None)
    assert validate_note({}, turns()) == (empty, None)


def test_an_unknown_turn_number_drops_the_note_with_a_reason():
    note = {"uses_turns": [1, 5], "entities": [], "refines_sql_of": None}

    kept, reason = validate_note(note, turns())

    assert kept is None
    assert "5" in reason


def test_refines_sql_of_must_be_one_of_the_used_turns():
    note = {"uses_turns": [1], "entities": [], "refines_sql_of": 2}

    kept, reason = validate_note(note, turns())

    assert kept is None
    assert "refines_sql_of" in reason


def test_a_value_absent_from_rows_and_sql_drops_the_note():
    note = {"uses_turns": [2], "entities": [{"column": "CARI_KOD", "value": "9999"}], "refines_sql_of": None}

    kept, reason = validate_note(note, turns())

    assert kept is None
    assert "9999" in reason


def test_a_column_the_turn_does_not_have_drops_the_note():
    note = {"uses_turns": [2], "entities": [{"column": "TELEFON", "value": "100"}], "refines_sql_of": None}

    kept, reason = validate_note(note, turns())

    assert kept is None
    assert "TELEFON" in reason


def test_an_entity_of_a_turn_the_note_does_not_use_drops_the_note():
    # 40 yalnız 1. turun satırlarında duruyor; not ise 2. tura dayandığını söylüyor
    note = {"uses_turns": [2], "entities": [{"column": "CARI_KOD", "value": "40"}], "refines_sql_of": None}

    kept, reason = validate_note(note, [turn(1, rows=[[40, "Müşteri 40"]]), turn(2)])

    assert kept is None
    assert "40" in reason


def test_the_line_for_a_customer_id_shows_the_label_and_the_row_name():
    note = {"uses_turns": [1], "entities": [{"column": "CustomerID", "value": "832"}], "refines_sql_of": 1}

    assert evidence_line(note, [wwi_turn()], WWI_SCHEMA) == (
        "Önceki cevaptan: müşteri 832 (Tailspin Toys (Head Office))"
    )


def test_no_line_shows_a_technical_column_name():
    note = {"uses_turns": [1], "entities": [{"column": "CustomerID", "value": "832"}], "refines_sql_of": None}

    line = evidence_line(note, [wwi_turn()], WWI_SCHEMA)

    assert "CustomerID" not in line
    assert "CustomerName" not in line


def test_a_column_without_a_description_falls_back_to_the_generic_label():
    schema = {"tables": [{"name": "TBLCARİ", "columns": [{"name": "CARI_KOD", "type": "INT"}]}]}
    note = {"uses_turns": [1], "entities": [{"column": "CARI_KOD", "value": "100"}], "refines_sql_of": None}

    assert evidence_line(note, [turn(1)], schema) == "Önceki cevaptan: değer 100 (Müşteri 0)"


def test_a_value_only_in_the_sql_has_no_parenthesis():
    note = {"uses_turns": [1], "entities": [{"column": "ADI", "value": "Müşteri 9"}], "refines_sql_of": None}

    line = evidence_line(note, [turn(1, sql="SELECT ADI FROM TBLCARİ WHERE ADI = 'Müşteri 9'")], SCHEMA)

    assert line == "Önceki cevaptan: carinin adı Müşteri 9"


def test_no_entity_points_at_the_turn_whose_sql_was_refined():
    assert evidence_line({"uses_turns": [2], "entities": [], "refines_sql_of": 2}, turns(), SCHEMA) == (
        "Önceki cevaptan: 2. turun sorgusu temel alındı."
    )
    assert evidence_line({"uses_turns": [1, 2], "entities": [], "refines_sql_of": None}, turns(), SCHEMA) == (
        "Önceki cevaptan: 1. turun sorgusu temel alındı."
    )


def test_a_note_that_used_no_turn_has_no_line():
    assert evidence_line(None, turns(), SCHEMA) is None
    assert evidence_line({"uses_turns": [], "entities": [], "refines_sql_of": None}, turns(), SCHEMA) is None
