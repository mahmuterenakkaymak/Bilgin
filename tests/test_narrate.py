"""T179: Cümleyi LLM kurar, sayıları bekçi onaylar; olmazsa şablon konuşur (PLAN R5-9, Contracts Narration).

İddia: anlatıcıya sonucun kendisi gösterilir (soru, kolonlar, satırlar, GERÇEKLER) ve ürettiği cümle
bekçiyi geçer. Bekçiyi geçiren her ne ise odur — uydurulan sayı bir kez daha istenir, ikinci
deneme de geçmezse ya da endpoint çalışmazsa koddan kurulan cümle döner. Şablon sayılarını
olguların `display` alanından aldığı için bekçiyi her zaman geçer; boş sonuçta LLM'e hiç
gidilmez. Sayaç sarmalayıcı kaç çağrı yapıldığını ve yeniden yazma mesajının ne söylediğini
göstermek için burada.
"""

import json

from nl2sql.agent import fake
from nl2sql.report import facts, guard, narrate

COLUMNS = ["URUN_ADI", "NET_TUTAR"]
ROWS = [("Çay", 1234.56), ("Kahve", 2468.1)]
QUESTION = "Ürünlerin toplam net tutarı ne kadardı?"
FACTS = facts.compute_facts(COLUMNS, ROWS)
ALLOWED = guard.allowed_values(COLUMNS, ROWS, FACTS, QUESTION)

DATE_COLUMNS = ["TARIH", "SATIS_TUTARI"]
DATE_ROWS = [("2026-07-01", 100.0), ("2026-08-01", 250.0), ("2026-09-01", 180.0)]
DATE_QUESTION = "Aylara göre satış tutarı ne kadar?"
DATE_FACTS = facts.compute_facts(DATE_COLUMNS, DATE_ROWS)

FACT_KINDS = {
    "row_count",
    "total",
    "max",
    "min",
    "mean",
    "top_item",
    "top_share",
    "last_period",
    "previous_period",
    "change",
    "change_pct",
}


class SpyLLM:
    """Sahte anlatıcının etrafında sayaç: kaç çağrı oldu, son mesajlar neydi."""

    def __init__(self, client) -> None:
        self.client = client
        self.calls: list[list[dict]] = []

    def chat(self, messages, tools=None):
        self.calls.append(messages)
        return self.client.chat(messages, tools)


def user_message(messages: list[dict]) -> str:
    return str(messages[1]["content"])


# ------------------------------------------------------------------ LLM'in kurduğu cümle


def test_the_narrator_writes_the_facts_it_was_shown():
    spy = SpyLLM(fake.narration_client())

    narration = narrate.narrate(QUESTION, COLUMNS, ROWS, FACTS, spy)

    assert narration.source == "llm"
    assert narration.rejected == []
    assert guard.check_text(narration.text, ALLOWED).ok, narration.text
    assert len(spy.calls) == 1, "geçen cümle için ikinci çağrı yoktur"


def test_the_narrator_is_shown_the_question_columns_rows_and_facts():
    spy = SpyLLM(fake.narration_client())

    narrate.narrate(QUESTION, COLUMNS, ROWS, FACTS, spy)

    messages = spy.calls[0]
    assert [message["role"] for message in messages] == ["system", "user"]
    assert "1-3 cümle" in messages[0]["content"]
    text = user_message(messages)
    assert QUESTION in text and "URUN_ADI, NET_TUTAR" in text
    assert "Çay | 1.234,56" in text, "sayılar anlatıcıya Türkçe okunuşuyla verilir"
    _, _, tail = text.partition("GERÇEKLER:")
    assert json.loads(tail) == [fact.to_dict() for fact in FACTS]


def test_only_max_rows_rows_reach_the_narrator():
    spy = SpyLLM(fake.narration_client())

    narrate.narrate(QUESTION, COLUMNS, ROWS, FACTS, spy, max_rows=1)

    rows_shown = user_message(spy.calls[0]).partition("GERÇEKLER:")[0]
    assert "Çay" in rows_shown and "Kahve" not in rows_shown
    assert "SATIRLAR (ilk 1 / 2):" in rows_shown, "gösterilmeyen satır vardır, anlatıcı bunu bilmeli"


def test_a_wrong_rounding_is_rewritten_once():
    spy = SpyLLM(fake.rounding_narrator())

    narration = narrate.narrate(QUESTION, COLUMNS, ROWS, FACTS, spy)

    assert narration.source == "llm_retry"
    assert narration.rejected == ["3"], "ilk denemenin uydurduğu basamak yazılır"
    assert guard.check_text(narration.text, ALLOWED).ok, narration.text
    assert len(spy.calls) == 2


# ------------------------------------------------------------------ şablona düşme


def test_an_invented_number_falls_back_to_the_template():
    spy = SpyLLM(fake.inventing_narrator())

    narration = narrate.narrate(QUESTION, COLUMNS, ROWS, FACTS, spy)

    assert narration.source == "template"
    assert narration.text == narrate.template_sentence(QUESTION, FACTS)
    assert guard.check_text(narration.text, ALLOWED).ok, "bekçiyi geçmeyen metin kullanıcıya gitmez"
    assert narration.rejected == [fake.INVENTED_NUMBER, fake.INVENTED_NUMBER]
    assert len(spy.calls) == 2, "bir deneme, bir yeniden yazma; üçüncüsü yok"
    retry = spy.calls[1][-1]
    assert retry["role"] == "user"
    assert retry["content"] == (
        f"Şu sayılar sonuçta yok: {fake.INVENTED_NUMBER}. Yalnız verilen sayılarla yeniden yaz."
    )


def test_a_dead_endpoint_still_gives_a_sentence():
    spy = SpyLLM(fake.FakeLLM(fake.unreachable()))

    narration = narrate.narrate(QUESTION, COLUMNS, ROWS, FACTS, spy)

    assert narration.source == "template"
    assert narration.rejected == []
    assert guard.check_text(narration.text, ALLOWED).ok
    assert len(spy.calls) == 1, "endpoint bir kez denenir; yeniden yazılacak cümle yoktur"


def test_an_empty_result_is_templated_without_the_llm():
    spy = SpyLLM(fake.narration_client())
    empty = facts.compute_facts(COLUMNS, [])

    narration = narrate.narrate(QUESTION, COLUMNS, [], empty, spy)

    assert narration.source == "template"
    assert spy.calls == []
    allowed = guard.allowed_values(COLUMNS, [], empty, QUESTION)
    assert guard.check_text(narration.text, allowed).ok
    assert "Satır sayısı 0." in narration.text


# ------------------------------------------------------------------ şablon cümlenin garantisi


def test_the_template_passes_the_guard_for_every_fact_kind():
    assert {fact.name for fact in [*FACTS, *DATE_FACTS]} == FACT_KINDS

    for fact in [*FACTS, *DATE_FACTS]:
        for columns, rows, question, all_facts in (
            (COLUMNS, ROWS, QUESTION, FACTS),
            (DATE_COLUMNS, DATE_ROWS, DATE_QUESTION, DATE_FACTS),
        ):
            if fact not in all_facts:
                continue
            allowed = guard.allowed_values(columns, rows, [fact], question)
            text = narrate.template_sentence(question, [fact])
            assert guard.check_text(text, allowed).ok, f"{text} -> {allowed}"


def test_the_template_covers_the_facts_it_promised_in_order():
    assert narrate.template_sentence(QUESTION, FACTS) == "Satır sayısı 2. Toplam 3.702,66. Öne çıkan Kahve."
    assert narrate.template_sentence(DATE_QUESTION, DATE_FACTS) == "Satır sayısı 3. Toplam 530. Değişim -70."


def test_the_template_without_facts_has_no_numbers():
    text = narrate.template_sentence(QUESTION, [])

    assert guard.check_text(text, guard.allowed_values(COLUMNS, ROWS, [], QUESTION)).ok
    assert guard.extract_numbers(text) == []
