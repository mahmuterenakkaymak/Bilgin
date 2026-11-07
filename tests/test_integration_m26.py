# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""T402: M26 entegrasyonu — İngilizce cevap uçtan uca, elle yapılmış tek parça olmadan (PLAN R8-3..R8-10).

Küme gerçek ``load_dataset("wwi")``, dosyalar kümenin kendi builder'ının tmp'de kurdukları, oturum
gerçek ``open_session``: sahte model ``cli.make_client("fake")``ın ``golden_en``ı da oynatan hâli,
yani ``serve --llm fake``ın kendi istemcisi. Cevap gerçek ``ask_payload`` ve iddia zincirin çıktısı:
İngilizce sorunun cevabı "en"dir — her olgu adı en.json'dan, her okunuş İngilizce biçimden, cümle
İngilizce bekçiden geçer; aynı sayılar Türkçe soruda Türkçe okunur. Cevabın dilini soru söyler,
program değil: ``BILGIN_LANG="en"`` ile koşan Türkçe sorunun olguları ve cümlesi o değişken yokken
çıkanla birebir aynıdır. Son iddia bekçinin kendi inadı: Türkçe yazılmış bir sayı İngilizce cevapta
yabancıdır, iki deneme de geçmez ve koddan kurulan İngilizce cümle konuşur.
"""

from __future__ import annotations

import re

import pytest
from pytest import MonkeyPatch

from bilgin.agent import fake
from bilgin.app.ask import ask_payload
from bilgin.app.session import open_session
from bilgin.datasets import load_dataset
from bilgin.i18n import t
from bilgin.report import guard, narrate

WWI = load_dataset("wwi")
EN_LINE = next(line for line in WWI.golden("en") if line["id"] == "E01")
TR_LINE = next(line for line in WWI.golden() if line["id"] == "Q01")

# İngilizce binlik ayıracı: cümlede bundan varsa Türkçe bekçi o sayıyı kendi dilinde okuyamaz.
GROUPED = re.compile(r"\d{1,3}(?:,\d{3})+")


@pytest.fixture(scope="module")
def session(tmp_path_factory):
    """Dünya bir kez: kümenin kendi builder'ının kurduğu dosya ve ona bakan gerçek oturum.

    ``client_factory`` verilmezse oturum ``cli.make_client``ı kendi kümesiyle çağırır — sahtenin
    altın kaydı o yüzden ``golden.jsonl`` ile ``golden_en.jsonl``ın birleşimidir. Kabukta ambiyans
    duran ``BILGIN_MSSQL_CONN`` ve ``BILGIN_BACKEND`` silinir: küme SQLite'ı kendi taşır (R7-29).
    """
    root = tmp_path_factory.mktemp("m26")
    mp = MonkeyPatch()
    mp.delenv("BILGIN_MSSQL_CONN", raising=False)
    mp.delenv("BILGIN_BACKEND", raising=False)
    mp.delenv("BILGIN_LANG", raising=False)
    try:
        database = root / "wwi.db"
        WWI.build_db(db_path=database, sql_path=root / "wwi.sql")
        yield open_session(
            dataset="wwi",
            llm="fake",
            db_path=database,
            index_dir=root / "index",
            audit_path=root / "audit.jsonl",
            ask_log=root / "asks.jsonl",
        )
    finally:
        mp.undo()


@pytest.fixture(scope="module")
def english(session):
    """E01'in İngilizce cevabı: zincirin çıktısı bir kez kurulur, beş test onu okur."""
    return ask_payload(session, EN_LINE["question"], mode="full")


def allowed(payload: dict, question: str) -> dict:
    """Bekçinin izin listesi, cevabın kendi satır ve olgularından kurulur (R5-8)."""
    return guard.allowed_values(
        payload["columns"], [tuple(row) for row in payload["rows"]], payload["facts"], question
    )


# ------------------------------------------------------------------ sahtenin oynattığı kayıt


def test_the_fake_replays_the_english_golden_set(session):
    # E01'in SQL'i sahtenin geri dönüş sorgusuyla aynıdır; İngilizce kaydı ayırt eden kümenin gerisidir.
    line = next(item for item in WWI.golden("en") if item["id"] == "E03")

    payload = ask_payload(session, line["question"], mode="full")

    assert payload["status"] == "answered", payload["error"]
    assert payload["answer_lang"] == "en"
    assert payload["sql"] == line["sql"], "İngilizce soru Türkçe altın kümenin kaydıyla koştu"


# ------------------------------------------------------------------ İngilizce cevap


def test_the_english_question_answers_in_english(english):
    assert english["status"] == "answered", english["error"]
    assert english["answer_lang"] == "en"
    assert english["row_count"] > 0, "boş cevap hiçbir şeyi doğrulamaz"

    for fact in english["facts"]:
        prefix = t(f"facts.{fact['name']}", "en").split(" (")[0]
        assert fact["label"] == prefix or fact["label"].startswith(f"{prefix} (")
        # Okunuş İngilizce biçimden: Türkçe yazılmış bir sayı bu dilde yabancıdır.
        assert not any(n.format_error for n in guard.extract_numbers(fact["display"], "en"))

    shown = {fact["name"]: fact["display"] for fact in english["facts"]}
    assert shown["mean"] == "4.00"
    assert shown["top_share"] == "25.0%"

    sentence, permit = english["answer_text"], allowed(english, EN_LINE["question"])
    assert guard.check_text(sentence, permit, "en").ok
    if GROUPED.search(sentence):
        assert not guard.check_text(sentence, permit, "tr").ok, "İngilizce sayı Türkçe bekçiye geçmesin"


def test_the_turkish_twin_shows_the_same_numbers_the_other_way(session, english):
    turkish = ask_payload(session, TR_LINE["question"], mode="full")

    assert turkish["status"] == "answered" and turkish["answer_lang"] == "tr"
    assert [f["value"] for f in turkish["facts"]] == [f["value"] for f in english["facts"]]
    assert [f["label"] for f in turkish["facts"]] != [f["label"] for f in english["facts"]]
    assert {f["name"]: f["display"] for f in turkish["facts"]}["mean"] == "4,00"
    assert guard.check_text(turkish["answer_text"], allowed(turkish, TR_LINE["question"]), "tr").ok


def test_the_program_language_never_overrides_the_question(session, monkeypatch):
    plain = ask_payload(session, TR_LINE["question"], mode="full")

    monkeypatch.setenv("BILGIN_LANG", "en")
    english_ui = ask_payload(session, TR_LINE["question"], mode="full")

    assert english_ui["answer_lang"] == "tr" == plain["answer_lang"]
    assert english_ui["facts"] == plain["facts"]
    assert english_ui["answer_text"] == plain["answer_text"]


# ------------------------------------------------------------------ bekçinin dili


def test_a_turkish_number_in_an_english_answer_falls_back_to_the_english_template(english):
    """Zorlanmış yabancı biçimli anlatı: gerçek ``narrate`` + gerçek bekçi, şablon İngilizce konuşur."""
    narration = narrate.narrate(
        EN_LINE["question"],
        english["columns"],
        [tuple(row) for row in english["rows"]],
        english["facts"],
        fake.inventing_narrator(),
        lang="en",
    )

    assert narration.source == "template"
    assert narration.rejected and set(narration.rejected) == {fake.INVENTED_NUMBER}
    assert narration.text == narrate.template_sentence(EN_LINE["question"], english["facts"], "en")
    assert narration.text.startswith(f"{t('facts.row_count', 'en')} ")
    assert guard.check_text(narration.text, allowed(english, EN_LINE["question"]), "en").ok
