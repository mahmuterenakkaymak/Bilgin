"""T395: Bekçi sayıyı dilinin biçimiyle okur (PLAN R8-7).

İddia: İngilizce cevap `1,234.56`, `1234.56`, `12.3%`, `-12.3%` yazar ve bekçi bunları okur; aynı
sayının Türkçe yazımı (`1.234,56`, `%12,3`) İngilizce cevapta yabancıdır ve değeri sonuçta durduğu
hâlde geçmez. Türkçe cevapta da tam tersi olur. `1,234` ve `1.234` iki anlamlıdır: dili okur.
Tolerans değişmez — gösterilen son basamağın yarısı, İngilizcede de böyledir. Türkçenin okunuşu
test_guard.py'deki hâliyle durur.
"""

from nl2sql.report import facts, guard

COLUMNS = ["STOK_ADI", "NET_TUTAR"]
ROWS = [("Çay", 1234.56), ("Kahve", 12460.0)]
QUESTION = "2026 yılında toplam net tutar ne kadardı?"
ALLOWED = guard.allowed_values(COLUMNS, ROWS, facts.compute_facts(COLUMNS, ROWS), QUESTION)

SHARE_COLUMNS = ["STOK_ADI", "SATIS_MIKTARI"]
SHARE_FACTS = [facts.Fact("top_share", "En yüksek pay", 12.3, "%12,3", "SATIS_MIKTARI", percent=True)]
SHARE_ALLOWED = guard.allowed_values(SHARE_COLUMNS, [("Çay", 123.0)], SHARE_FACTS, "En yüksek pay nedir?")


# ------------------------------------------------------------------ dilin kendi biçimi


def test_an_english_answer_writes_english_formats():
    result = guard.check_text("Tea 1,234.56 TL, 1234.56 again; 2 rows in 2026.", ALLOWED, "en")

    assert result.ok, f"İngilizce yazımlar İngilizce cevapta geçmeli: {result.offending}"
    assert [token.raw for token in result.numbers] == ["1,234.56", "1234.56", "2", "2026"]


def test_english_forms_are_read_with_their_percent_and_sign():
    tokens = guard.extract_numbers("1,234.56 and 1234.56 and 12.3% and -12.3% and 7", "en")

    assert [token.raw for token in tokens] == ["1,234.56", "1234.56", "12.3%", "-12.3%", "7"]
    assert [token.value for token in tokens] == [1234.56, 1234.56, 12.3, -12.3, 7.0]
    assert [token.decimals for token in tokens] == [2, 2, 1, 1, 0]
    assert [token.percent for token in tokens] == [False, False, True, True, False]
    assert not any(token.format_error for token in tokens)


def test_the_same_value_passes_only_in_its_own_language():
    english = "Tea 1,234.56 TL."
    turkish = "Çay 1.234,56 TL."

    assert guard.check_text(english, ALLOWED, "en").ok
    assert guard.check_text(turkish, ALLOWED, "tr").ok
    assert not guard.check_text(turkish, ALLOWED, "en").ok, "sayı sonuçta var, yabancı olan yazımı"
    assert not guard.check_text(english, ALLOWED, "tr").ok


# ------------------------------------------------------------------ öteki dilin biçimi yabancıdır


def test_turkish_formats_are_rejected_in_an_english_answer():
    result = guard.check_text("Tea 1.234,56 TL and %12,3 of the share.", ALLOWED, "en")

    assert not result.ok
    assert result.offending == ["1.234,56", "%12,3"]
    assert all(token.format_error for token in result.numbers), "yabancı biçim hiç okunmaz"


def test_english_formats_are_rejected_in_a_turkish_answer():
    result = guard.check_text("Çay 1,234.56 TL ve %12.3 pay.", ALLOWED)

    assert not result.ok
    assert result.offending == ["1,234.56", "%12.3"]
    assert all(token.format_error for token in result.numbers)


# ------------------------------------------------------------------ iki anlamlı yazım


def test_an_ambiguous_group_is_read_by_the_language():
    english = guard.extract_numbers("1,234 and 1.234", "en")
    turkish = guard.extract_numbers("1,234 ve 1.234", "tr")

    assert [token.value for token in english] == [1234.0, 1.234]
    assert [token.decimals for token in english] == [0, 3]
    assert [token.value for token in turkish] == [1.234, 1234.0]
    assert [token.decimals for token in turkish] == [3, 0]


# ------------------------------------------------------------------ tolerans ve havuzlar


def test_the_tolerance_is_half_of_the_last_shown_decimal_in_english():
    assert guard.check_text("Tea 1,234.6 TL.", ALLOWED, "en").ok, "1234.56 -> 1,234.6"
    assert not guard.check_text("Tea 1,234.7 TL.", ALLOWED, "en").ok


def test_an_english_percent_falls_into_the_percent_pool():
    assert guard.check_text("The top share is 12.3%.", SHARE_ALLOWED, "en").ok
    assert not guard.check_text("The top share is 12.4%.", SHARE_ALLOWED, "en").ok


def test_years_and_the_questions_own_numbers_pass_in_both_languages():
    assert guard.check_text("In 2026 there are 2 rows.", ALLOWED, "en").ok
    assert guard.check_text("2026 yılında 2 satır var.", ALLOWED, "tr").ok
