# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""T205: kısa bir iş terimi kelimenin içinde değil, başına başınaysa söylenmiştir (PLAN R3-9).

"Kuruyemiş ürün grubunun bu yılki KDV hariç satış cirosu ..." kural yakalama açısından döviz
kuralı değildi, ama alt dizi araması "kur"u her uzun kelimenin içinde gördüğü için sorgusuna
" döviz USD EUR TL karşılığı" ekleniyordu. Kelime kökünü yakalamak istediğimiz şey ciro ->
cirosu; o davranış dört katlanmış harften uzun ifadelerde kalıyor, kur/TL/USD gibi kısaltmalar
tam bir sözcük olmak zorunda. Ölçüm elle kurulmuş kurallar üzerinde (kısa eş anlamlılar ancak
orada biter), gerçek küme üzerinde ise tek yönlü iddia: hiçbir golden soru kelimenin içindeki
bir parça yüzünden döviz kuralını yakalamıyor.
"""

from bilgin.eval.runner import load_golden
from bilgin.index.search import synonym_query
from bilgin.index.text import fold, tokens
from bilgin.schema_map.rules import load_rules

# Elle kurulu kural: eş anlamlıları kısa, yani kelime testi ancak burada görülür.
DOVIZ = {"id": "doviz_tl", "term": "döviz kuru", "synonyms": ["kur", "USD"]}
CIRO = {"id": "ciro", "term": "ciro", "synonyms": ["satış geliri"]}
KISA = {"id": "kisa", "term": "para birimi", "synonyms": ["TL", "döviz kuru"]}

RULES = load_rules()
GOLDEN = [line["question"] for line in load_golden()]
DOVIZ_RULE = next(rule for rule in RULES if rule["id"] == "doviz_tl")
# ASSUMPTION: görev "kur" ya da "döviz" demeyen bir golden sorunun döviz kuralını yakalamadığını
# söylüyor; USD/EUR ile soran iki soru kuralı gerçekten söylüyor, o yüzden dışlama kuralın kendi
# tetiklerinden kuruluyor - uydurma bir kelime listesi değil.
SAID = {fold(word) for word in [DOVIZ_RULE["term"], *DOVIZ_RULE["synonyms"]] if word}


def added(query: str, rules: list[dict]) -> str:
    """Genişletmenin sorgunun sonuna eklediği metin; sorgu değişmediyse boş."""
    full = synonym_query(query, rules)
    assert full.startswith(query)
    return full[len(query) :].strip()


# ------------------------------------------------------------------ kısa ifade tam sözcük


def test_a_product_group_that_only_looks_like_a_short_term_stays_out():
    query = "Kuruyemiş ürün grubunun bu yılki KDV hariç satış cirosu ne kadardır?"
    assert added(query, [DOVIZ]) == ""


def test_kur_farki_says_the_short_term_and_bring_the_rest():
    assert added("kur farkı nedir", [DOVIZ]) == "USD"


def test_usd_cinsinden_says_the_short_term_too():
    assert added("USD cinsinden", [DOVIZ]) == "kur"


def test_a_two_character_synonym_needs_a_whole_word():
    assert added("TL cinsinden toplam", [KISA]) == "döviz kuru"
    assert added("Atlas satışı", [KISA]) == ""


# ------------------------------------------------------------------ uzun ifade alt dizi


def test_a_word_form_of_a_long_term_still_lights_the_rule():
    assert added("Geçen ayın cirosu ne kadar?", [CIRO]) == "satış geliri"


def test_a_short_synonym_hidden_in_a_longer_word_is_still_added():
    assert added("döviz kuru kaç TL, kuruyemiş hariç", [DOVIZ]) == "kur USD"


# ------------------------------------------------------------------ gerçek küme


def test_no_golden_question_borrows_the_doviz_rule_through_a_word():
    for question in GOLDEN:
        if SAID & set(tokens(question)):
            continue
        assert "döviz" not in fold(added(question, RULES)), question


def test_the_kuruyemis_question_is_among_the_ones_checked():
    question = next(q for q in GOLDEN if "kuruyemi" in fold(q))
    assert "döviz" not in fold(added(question, RULES))
