# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""T397: anlatı cevabın dilinde (PLAN R8-8): aynı bekçi, aynı şablon, İngilizce kural listesi.

İddia: `lang="en"` anlatıcıya SYSTEM'in kural kural ikizini, satırları İngilizce okunuşla ve
bekçiyi İngilizce gramerle gösterir — o yüzden "3,702.66" geçer, "1.234,56" bir uydurma gibi bir
kez daha istenir. Yeniden yazma cümleleri, sayısız özet cümlesi ve şablon catalog'dan o dilin
metnidir. Türkçe tarafın mesajları bugünküyle bayt bayttır: sistem metni burada saklanan kopyasıyla,
kullanıcı mesajı bugünkü satırlarıyla kıyaslanır.
"""

import json
from pathlib import Path

from nl2sql.agent.llm import ChatResponse
from nl2sql.i18n import scan, t
from nl2sql.report import facts, guard, narrate

COLUMNS = ["STOK_ADI", "NET_TUTAR"]
ROWS = [("Çay", 1234.56), ("Kahve", 2468.1)]
QUESTION = "Ürünlerin toplam net tutarı ne kadardı?"

TR_FACTS = facts.compute_facts(COLUMNS, ROWS)
EN_FACTS = facts.compute_facts(COLUMNS, ROWS, lang="en")
ALLOWED = guard.allowed_values(COLUMNS, ROWS, EN_FACTS, QUESTION)

# Bugünün SYSTEM metninin bayt bayt kopyası: R8-8 Türkçe yolu hiç değiştirmemeli.
SYSTEM_TR = """Sen bir sorgu sonucunu kullanıcıya Türkçe anlatan bir rapor asistanısın.

KURALLAR
1. 1-3 cümle düz metin yaz: başlık, madde işareti ve tablo yok.
2. Yalnızca aşağıdaki satırlarda ve GERÇEKLER'de gördüğün sayıları kullan. Hiçbir hesap yapma: toplam, fark, oran, yüzde veya ortalamayı kendin üretme; sayı gerektirmeyen bir şeyi sayıyla söyleme.
3. Sayıyı gösterildiği biçimde aynen yaz: binlik ayıracı nokta, ondalık virgül, yüzde `%12,3`. Basamak ekleme ya da atma; İngilizce yazım (`1,234.56`) bekçi tarafından reddedilir.
4. KOLONLAR satırındaki teknik adları (StateProvinceName, ToplamCiro, CIRO gibi) cümlede ASLA yazma; ne anlattıklarını sorunun dilinde Türkçe söyle ("eyalet", "toplam ciro", "tedarikçi"). Satırlardaki değerleri (ürün, firma, şehir adları) olduğu gibi yaz.
5. Cümle sorunun doğrudan cevabı olsun ve bir insanın konuşacağı gibi doğal Türkçe olsun; cümleye sayıyla başlamak zorunda değilsin.
"""


class ScriptedLLM:
    """Günceli olanı söyler: n'inci çağrı script'in n'inci cümlesini verir, mesajları da saklar."""

    def __init__(self, script: list[str]) -> None:
        self.script = script
        self.calls: list[list[dict]] = []

    def chat(self, messages, tools=None) -> ChatResponse:
        self.calls.append(messages)
        return ChatResponse(content=self.script[min(len(self.calls) - 1, len(self.script) - 1)])


def display(fact_list, name: str) -> str:
    return next(fact.display for fact in fact_list if fact.name == name)


def user_message(messages: list[dict]) -> str:
    return str(messages[1]["content"])


# ------------------------------------------------------------------ İngilizce anlatı


def test_an_english_sentence_is_accepted_on_the_first_call():
    llm = ScriptedLLM([f"The total is {display(EN_FACTS, 'total')}."])

    narration = narrate.narrate(QUESTION, COLUMNS, ROWS, EN_FACTS, llm, lang="en")

    assert narration.source == "llm"
    assert narration.text == "The total is 3,702.66."
    assert len(llm.calls) == 1, "bekçi İngilizce gramerle baktığı için cümle yerinde durur"
    assert guard.check_text(narration.text, ALLOWED, "en").ok
    assert not guard.check_text(narration.text, ALLOWED, "tr").ok, "yazım İngilizce"


def test_the_english_narrator_is_shown_english_numbers_and_english_labels():
    llm = ScriptedLLM(["Understood."])

    narrate.narrate(QUESTION, COLUMNS, ROWS, EN_FACTS, llm, lang="en")

    messages = llm.calls[0]
    assert [message["role"] for message in messages] == ["system", "user"]
    assert "1-3 sentences" in messages[0]["content"]
    text = user_message(messages)
    assert "Çay | 1,234.56" in text, "satırlar anlatıcıya İngilizce okunuşla verilir"
    assert "COLUMNS: STOK_ADI, NET_TUTAR" in text
    _, _, tail = text.partition("FACTS:")
    assert json.loads(tail) == [fact.to_dict() for fact in EN_FACTS]


def test_a_turkish_spelled_number_is_retried_and_then_the_english_template_speaks():
    llm = ScriptedLLM(["The total is 1.234,56."])

    narration = narrate.narrate(QUESTION, COLUMNS, ROWS, EN_FACTS, llm, lang="en")

    assert narration.source == "template"
    assert narration.text == narrate.template_sentence(QUESTION, EN_FACTS, lang="en")
    assert narration.text == "Row count 2. Total 3,702.66. Top item Kahve."
    assert guard.check_text(narration.text, ALLOWED, "en").ok, "bekçiyi geçmeyen metin gitmez"
    assert narration.rejected == ["1.234,56", "1.234,56"]
    assert len(llm.calls) == 2, "bir deneme, bir yeniden yazma; üçüncüsü yok"
    retry = llm.calls[1][-1]
    assert retry["role"] == "user"
    assert retry["content"] == t("narrate.retry.numbers", "en", tokens="1.234,56")
    assert retry["content"] == (
        "These numbers are not in the result: 1.234,56. Rewrite using only the numbers given."
    )


def test_a_technical_name_is_sent_back_with_an_english_note():
    llm = ScriptedLLM(["NET_TUTAR is the highest.", f"The total is {display(EN_FACTS, 'total')}."])

    narration = narrate.narrate(QUESTION, COLUMNS, ROWS, EN_FACTS, llm, lang="en")

    assert narration.source == "llm_retry"
    assert narration.rejected == ["NET_TUTAR"]
    assert len(llm.calls) == 2
    assert llm.calls[1][-1]["content"] == t("narrate.retry.names", "en", names="NET_TUTAR")
    assert llm.calls[1][-1]["content"] == (
        "Do not use these technical column names in the sentence: NET_TUTAR. "
        "Say what they mean in English and rewrite."
    )


def test_an_empty_result_is_templated_in_english_without_the_llm():
    llm = ScriptedLLM(["Bu cümle hiç okunmayacak."])
    empty = facts.compute_facts(COLUMNS, [], lang="en")

    narration = narrate.narrate(QUESTION, COLUMNS, [], empty, llm, lang="en")

    assert narration.source == "template"
    assert llm.calls == []
    assert narration.text == f"Row count 0. Question: {QUESTION}"


def test_the_no_number_sentence_speaks_the_language_of_the_answer():
    assert narrate.template_sentence(QUESTION, [], lang="en") == "There is no numeric summary to describe."
    assert narrate.template_sentence(QUESTION, []) == "Sonuçta anlatılacak sayısal özet yok."


# ------------------------------------------------------------------ Türkçe yol değişmedi


def test_the_turkish_system_message_is_the_one_of_today():
    assert narrate.SYSTEM == SYSTEM_TR


def test_the_turkish_user_message_is_the_one_of_today():
    llm = ScriptedLLM(["Anlaşıldı."])

    narrate.narrate(QUESTION, COLUMNS, ROWS, TR_FACTS, llm)

    head, _, tail = user_message(llm.calls[0]).partition("GERÇEKLER:")
    assert head == (
        f"Soru: {QUESTION}\n"
        "\n"
        "KOLONLAR: STOK_ADI, NET_TUTAR\n"
        "SATIRLAR:\n"
        "Çay | 1.234,56\n"
        "Kahve | 2.468,1\n"
        "\n"
    )
    assert json.loads(tail) == [fact.to_dict() for fact in TR_FACTS]


def test_the_english_system_message_is_the_rule_for_rule_twin():
    assert narrate.SYSTEM_EN != narrate.SYSTEM
    for token in ("1-3 sentences", "12.3%", "1.234,56", "StateProvinceName", "COLUMNS", "FACTS"):
        assert token in narrate.SYSTEM_EN, token
    assert len(narrate.SYSTEM_EN.splitlines()) == len(narrate.SYSTEM.splitlines())


def test_the_module_has_no_turkish_literals_left():
    assert scan.user_literals(Path(narrate.__file__), allow=("SYSTEM",)) == []
