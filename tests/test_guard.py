# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""T178: Anlatının sayıları sonuçta yoksa cümle geçmez (PLAN R5-8, Contracts GuardResult).

İddia: bekçi Türkçe yazılmış doğru sayıları geçirir, uydurulanı ve yanlış yuvarlananı yakalar.
İzin listesi sonucun kendisinden gelir: hücreler, metin içindeki tam sayılar, ISO tarihin
parçaları, satır sayısı, olgular ve sorunun sayıları. Tolerans gösterilen son basamağın yarısıdır,
o yüzden "12,5 bin" 12.460 için geçerli de "12,4 bin" değildir. Yüzde yüzde olgusuna denk düşer.
Biçim sayı kadar kesindir: İngilizce yazım sayı doğru olsa bile geçmez, harfe yapışık kod ise hiç
sayı değildir.
"""

from nl2sql.policy import pii
from nl2sql.report import facts, guard

COLUMNS = ["URUN_ADI", "NET_TUTAR"]
ROWS = [("Çay", 1234.56), ("Kahve", 12460.0)]
QUESTION = "2026 yılında toplam net tutar ne kadardı?"
ALLOWED = guard.allowed_values(COLUMNS, ROWS, facts.compute_facts(COLUMNS, ROWS), QUESTION)

SHARE_COLUMNS = ["URUN_ADI", "SATIS_MIKTARI"]
SHARE_ROWS = [("Çay", 123.0), ("Kahve", 877.0)]
SHARE_FACTS = [facts.Fact("top_share", "En yüksek pay", 12.3, "%12,3", "SATIS_MIKTARI", percent=True)]
SHARE_ALLOWED = guard.allowed_values(SHARE_COLUMNS, [("Çay", 123.0)], SHARE_FACTS, "En yüksek pay nedir?")


# ------------------------------------------------------------------ geçen sayılar


def test_the_turkish_writings_of_real_values_pass():
    result = guard.check_text("Çay 1.234,56 TL, Kahve 12,5 bin TL; 2026 yılında.", ALLOWED)

    assert result.ok, f"geçmesi gereken sayılar: {result.offending}"
    assert result.offending == []
    assert [token.raw for token in result.numbers] == ["1.234,56", "12,5 bin", "2026"]


def test_a_percent_matches_the_percent_fact_of_the_result():
    assert guard.check_text("En yüksek pay %12.", SHARE_ALLOWED).ok, "12,3 payı %12 diye okunur"
    caught = guard.check_text("En yüksek pay %13.", SHARE_ALLOWED)

    assert not caught.ok
    assert caught.offending == ["%13"], "yarım basamağı aşan yüzde uydurmadır"


def test_a_percent_fact_comes_from_the_result_itself():
    allowed = guard.allowed_values(
        SHARE_COLUMNS, SHARE_ROWS, facts.compute_facts(SHARE_COLUMNS, SHARE_ROWS), "En yüksek pay nedir?"
    )

    assert guard.check_text("En yüksek pay %88.", allowed).ok, "877 / 1000 = %87,7"
    assert not guard.check_text("En yüksek pay %89.", allowed).ok


def test_a_number_of_the_question_is_allowed():
    assert guard.check_text("2026 yılında 2 satır var.", ALLOWED).ok


# ------------------------------------------------------------------ yakalanan sayılar


def test_a_number_that_is_not_in_the_result_is_offending():
    result = guard.check_text("Toplam 9.999 TL.", ALLOWED)

    assert not result.ok
    assert result.offending == ["9.999"]


def test_an_honest_rounding_passes_and_a_wrong_one_is_caught():
    assert guard.check_text("12,5 bin", ALLOWED).ok, "12.460 -> 12,5 bin"
    caught = guard.check_text("12,4 bin", ALLOWED)

    assert not caught.ok
    assert caught.offending == ["12,4 bin"], "60 birimlik sapma gösterilen basamağın yarısı değildir"


def test_an_invented_decimal_is_caught():
    assert not guard.check_text("Çay 1.234,5 TL.", ALLOWED).ok, "1.234,56 iki basamakla yazılır"


def test_an_english_writing_is_caught_even_when_the_number_is_right():
    result = guard.check_text("Toplam 1,234.56 TL ve 12.5 adet.", ALLOWED)

    assert not result.ok
    assert result.offending == ["1,234.56", "12.5"]
    assert all(token.format_error for token in result.numbers)


def test_offending_numbers_are_listed_in_text_order():
    result = guard.check_text("Önce 9.999, sonra %13, en son 8.888.", SHARE_ALLOWED)

    assert result.offending == ["9.999", "%13", "8.888"]


# ------------------------------------------------------------------ sayının okunuşu


def test_turkish_forms_are_read_with_their_scale_and_percent():
    tokens = guard.extract_numbers("-3 ile 1234 ve 12,5 ve %12 ve %12,5 ve 1,5 bin ve 2,5 milyon ve 1,5 milyar")

    assert [token.raw for token in tokens] == [
        "-3",
        "1234",
        "12,5",
        "%12",
        "%12,5",
        "1,5 bin",
        "2,5 milyon",
        "1,5 milyar",
    ]
    assert [token.value for token in tokens] == [
        -3.0,
        1234.0,
        12.5,
        12.0,
        12.5,
        1500.0,
        2500000.0,
        1500000000.0,
    ]
    assert [token.decimals for token in tokens] == [0, 0, 1, 0, 1, 1, 1, 1]
    assert [token.scale for token in tokens] == [1.0, 1.0, 1.0, 1.0, 1.0, 1e3, 1e6, 1e9]
    assert [token.percent for token in tokens] == [False, False, False, True, True, False, False, False]
    assert not any(token.format_error for token in tokens)


def test_a_thousands_dot_is_not_an_english_decimal():
    assert [token.value for token in guard.extract_numbers("1.234 ile 1.234.567")] == [1234.0, 1234567.0]


def test_the_period_at_the_end_of_a_sentence_is_not_part_of_the_number():
    assert [token.raw for token in guard.extract_numbers("Toplam 1.234,56.")] == ["1.234,56"]


def test_a_code_is_not_a_number():
    assert guard.extract_numbers("STK001 için Q3 kapanışı ve 25TLFINIŞ") == []
    assert guard.check_text("STK001 kodlu ürün 1.234,56 TL.", ALLOWED).ok


def test_an_empty_sentence_has_nothing_to_check():
    result = guard.check_text("", ALLOWED)

    assert result.ok and result.numbers == []


# ------------------------------------------------------------------ izin listesi


def test_allowed_values_are_the_cells_their_dates_and_the_question_numbers():
    columns = ["TARIH", "DEPO_ADI", "MIKTAR"]
    rows = [("2026-09-01", "Depo 7", 12.5), ("2026-10-03", "Depo 7", 15.0)]
    allowed = guard.allowed_values(columns, rows, facts.compute_facts(columns, rows), "Eylül 2026 için kaç satır?")

    values = allowed["values"]
    assert 12.5 in values and 15.0 in values, "sayısal hücreler"
    assert 2 in values, "satır sayısı"
    assert 2026 in values and 9 in values and 1 in values and 3 in values, "ISO tarihin parçaları"
    assert 7 in values, "metin hücresinin tam sayısı"
    assert 13.75 in values, "olguların değeri de izin listesinde"
    assert 54.5 in allowed["percent"], "pay olgusu yüzde havuzundadır"


def test_a_masked_cell_gives_no_allowed_number():
    columns = ["AD_SOYAD", "NET_TUTAR"]
    rows = [(pii.mask("person_name", "Ayşe Yılmaz"), pii.mask("salary", 45230.5))]
    allowed = guard.allowed_values(columns, rows, facts.compute_facts(columns, rows), "")

    assert set(allowed["values"]) == {1}, "maskeli hücrenin sayısı değil; yalnız satır sayısı"
    assert allowed["percent"] == []
