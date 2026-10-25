"""Belirsiz soruyu oynatan sahte: açıklama turu, devamının seçilen okunuşla cevaplanması (R5-11).

Model burada da yok; sınanan şey sahtenin belirsiz soru karşısında *hangi turu* oynattığı. Bunun
ölçümde bir anlamı olması turun döngüden geçmesine bağlı, o yüzden ask_clarification çağrısı
aracın kendi denetiminden de (`tools.clarify_request`) geçiriliyor. Devam iki modda da sınanıyor:
`full` doğrudan altın kaydı gibi oynatır, `rag` önce arama aracını çağırır. Altın soruların
senaryosu belirsiz set verilse de değişmemeli - ölçümün bozulmadığı oradan anlaşılır.
"""

import json

import pytest

from nl2sql import config
from nl2sql.agent.clarify import follow_up_text, split_follow_up
from nl2sql.agent.fake import FALLBACK_SQL, FakeLLM, for_golden, over_clarify
from nl2sql.agent.tools import clarify_request


def golden_lines(path=config.GOLDEN_PATH):
    with open(path, encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


GOLDEN_LINES = golden_lines()
BRUT, NET = GOLDEN_LINES[0]["sql"], GOLDEN_LINES[1]["sql"]
TERM = "satış"
QUESTION = "Eylül 2026'da satışlarımız ne kadar?"
LABELS = ["Brüt satış (iptaller dahil)", "Net satış (iptaller düşülmüş)"]
CLARIFY_TEXT = f"'{TERM}' ile neyi kastediyorsunuz?"
AMBIGUOUS = [
    {
        "id": "A01",
        "question": QUESTION,
        "expect": "clarify",
        "term": TERM,
        "readings": [{"label": LABELS[0], "sql": BRUT}, {"label": LABELS[1], "sql": NET}],
        "notes": "",
    }
]


def messages_for(turn, question=QUESTION):
    """Döngünün n. çağrısı: sistem + soru + n tane (asistan mesajı, araç sonucu) çifti."""
    messages = [{"role": "system", "content": "şema ve kurallar"}, {"role": "user", "content": question}]
    for n in range(turn):
        messages.append({"role": "assistant", "content": "", "tool_calls": [{"id": f"c{n}"}]})
        messages.append({"role": "tool", "tool_call_id": f"c{n}", "content": "4 satır"})
    return messages


def calls(response):
    return [(call.name, call.arguments) for call in response.tool_calls]


def asked(llm, question, turns):
    return [calls(llm.chat(messages_for(n, question))) for n in range(turns)]


# ------------------------------------------------------------------ devam metni

def test_the_follow_up_text_is_the_question_plus_the_chosen_meaning():
    assert follow_up_text(QUESTION, LABELS[0]) == f"{QUESTION}\n\nKullanıcının seçtiği anlam: {LABELS[0]}"


def test_splitting_a_follow_up_text_gives_back_both_halves():
    assert split_follow_up(follow_up_text(QUESTION, LABELS[1])) == (QUESTION, LABELS[1])


@pytest.mark.parametrize("text", [QUESTION, "", "   "])
def test_a_question_nobody_chose_about_splits_to_itself_with_no_choice(text):
    assert split_follow_up(text) == (text.strip(), None)


def test_a_question_that_quotes_the_marker_splits_at_the_last_one():
    nested = follow_up_text(follow_up_text(QUESTION, LABELS[0]), LABELS[1])
    assert split_follow_up(nested) == (follow_up_text(QUESTION, LABELS[0]), LABELS[1])


# ------------------------------------------------------------------ belirsiz soru sorar

def test_an_ambiguous_question_gets_one_clarification_with_the_reading_labels():
    response = for_golden(GOLDEN_LINES, ambiguous=AMBIGUOUS).chat(messages_for(0))
    assert calls(response) == [("ask_clarification", {"question": CLARIFY_TEXT, "options": LABELS})]


def test_the_question_the_fake_asks_passes_the_tools_own_check():
    """Döngü bu çağrıyı reddederse belirsiz soru cevaplanmış olur; ölçümün anlamı kalmaz."""
    arguments = calls(for_golden(GOLDEN_LINES, ambiguous=AMBIGUOUS).chat(messages_for(0)))[0][1]
    assert clarify_request(arguments) == (CLARIFY_TEXT, LABELS)


def test_the_ambiguous_question_is_matched_after_stripping():
    response = for_golden(GOLDEN_LINES, ambiguous=AMBIGUOUS).chat(messages_for(0, f"  {QUESTION}  "))
    assert calls(response)[0][1]["options"] == LABELS


def test_a_line_that_cannot_be_asked_about_is_never_matched():
    """Tek okunuş sorulacak soru değildir; sorusuz satır da eşleşmez, ikisi de stock sorguya düşer."""
    both = [{"label": LABELS[0], "sql": BRUT}, {"label": LABELS[1], "sql": NET}]
    broken = [
        {"question": QUESTION, "term": TERM, "readings": both[:1]},
        {"question": "  ", "term": TERM, "readings": both},
    ]
    assert asked(for_golden(GOLDEN_LINES, ambiguous=broken), QUESTION, 1) == [[("get_schema", {})]]


# ------------------------------------------------------------------ devam cevap verir

@pytest.mark.parametrize("choice,sql", [(LABELS[0], BRUT), (LABELS[1], NET)])
def test_the_follow_up_runs_the_chosen_reading(choice, sql):
    llm = for_golden(GOLDEN_LINES, ambiguous=AMBIGUOUS)
    assert asked(llm, follow_up_text(QUESTION, choice), 3) == [
        [("get_schema", {})],
        [("run_sql", {"sql": sql})],
        [("submit_sql", {"sql": sql})],
    ]


@pytest.mark.parametrize("choice,sql", [(LABELS[0], BRUT), (LABELS[1], NET)])
def test_in_rag_mode_the_follow_up_searches_before_it_runs(choice, sql):
    llm = for_golden(GOLDEN_LINES, mode="rag", ambiguous=AMBIGUOUS)
    assert asked(llm, follow_up_text(QUESTION, choice), 4) == [
        [("search_schema", {"query": QUESTION})],
        [("get_schema", {})],
        [("run_sql", {"sql": sql})],
        [("submit_sql", {"sql": sql})],
    ]


def test_a_choice_no_reading_offers_falls_back_to_the_stock_query():
    llm = for_golden(GOLDEN_LINES, ambiguous=AMBIGUOUS)
    assert asked(llm, follow_up_text(QUESTION, "Üçüncü bir okunuş"), 3)[-1] == [
        ("submit_sql", {"sql": FALLBACK_SQL})
    ]


def test_the_stock_query_is_searched_too_in_rag_mode():
    llm = for_golden(GOLDEN_LINES, mode="rag", ambiguous=AMBIGUOUS)
    assert asked(llm, follow_up_text(QUESTION, "Üçüncü bir okunuş"), 1) == [
        [("search_schema", {"query": QUESTION})]
    ]


# ------------------------------------------------------------------ altın sorular değişmez

def test_a_golden_question_never_asks_even_with_the_ambiguous_set_given():
    llm = for_golden(GOLDEN_LINES, ambiguous=AMBIGUOUS)
    for line in GOLDEN_LINES:
        assert asked(llm, line["question"], 3) == [
            [("get_schema", {})],
            [("run_sql", {"sql": line["sql"]})],
            [("submit_sql", {"sql": line["sql"]})],
        ], line["id"]


def test_a_choice_on_a_golden_question_is_only_ignored():
    """Seçim belirsiz sorunun devamıdır; altın soruda metnin öbür yarısı sorunun kendisidir."""
    line = GOLDEN_LINES[2]
    llm = for_golden(GOLDEN_LINES, ambiguous=AMBIGUOUS)
    assert asked(llm, follow_up_text(line["question"], LABELS[0]), 3)[-1] == [
        ("submit_sql", {"sql": line["sql"]})
    ]


# ------------------------------------------------------------------ çok soran sahte

def test_over_clarify_asks_on_a_golden_question_and_never_stops_asking():
    llm = FakeLLM(over_clarify())
    question, options = clarify_request(calls(llm.chat(messages_for(0, GOLDEN_LINES[0]["question"])))[0][1])
    assert question and len(options) >= 2
    assert calls(llm.chat(messages_for(4, GOLDEN_LINES[0]["question"]))) == calls(
        llm.chat(messages_for(0, GOLDEN_LINES[0]["question"]))
    )
