# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""T400: cevabın dili payload'ın kendi alanında (PLAN R8-6, Contracts "AskPayload (ext.)").

Dünya gerçek (``build_db`` ile kurulmuş sentetik ERP), model ``cli.make_client``ın gerçek sahtesi:
altın soruyu tanıdığı için altın SQL'ini oynatır. İddia payload'ın ``answer_lang``inde ve o alanın
değiştirdiği cümlelerde: Türkçe altın soru "tr"dir ve payload anahtarın dışında bugünkü payloaddır;
İngilizce soru "en"dir, yani olgunun etiketi İngilizce okunur; şıkkın dili sorunun dilidir; hatanın
cümlesi cevabın dilindendir, ham hata ``detail``da kalmıştır. Son iddia modülün kendisininki:
``ask.py`` kullanıcıya artık Türkçe bir sabit söylemez.
"""

from pathlib import Path

import pytest

from bilgin import config
from bilgin.agent import fake
from bilgin.app import ask
from bilgin.app.ask import ask_payload
from bilgin.app.session import open_session
from bilgin.cli import main as cli
from bilgin.eval import runner
from bilgin.i18n import t
from bilgin.i18n.scan import user_literals
from bilgin.schema_map import build

GOLDEN = runner.load_golden()
BY_ID = {line["id"]: line for line in GOLDEN}

TR_QUESTION = BY_ID["Q02"]["question"]
EN_QUESTION = "List the top five products by total sales quantity"

# İki koşum yalnız bu alanlarda ayrılır: dil anahtarı ve koşum başına değişenler.
VOLATILE = {"answer_lang", "audit_id", "timings"}


@pytest.fixture
def project(tmp_path, monkeypatch):
    """Dünya tmp'de: oturum kendi yollarını alır, günlükler testin dosyasına düşer."""
    monkeypatch.setattr(config, "ROOT", tmp_path)
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.db")
    monkeypatch.setattr(config, "INDEX_DIR", tmp_path / "index")
    monkeypatch.setattr(config, "AUDIT_LOG", tmp_path / "audit.jsonl")
    monkeypatch.setattr(config, "ASK_LOG", tmp_path / "asks.jsonl")
    build.build_db(config.SEED, tmp_path / "test.db", tmp_path / "test.sql")
    return tmp_path


def make_client(mode: str = "full"):
    """Kümenin gerçek sahte modeli: tanınan soru altın SQL'ini, tanımadığı soru kendi sorgusunu oynatır."""
    return cli.make_client("fake", mode)


def make_session(project, client_factory=None):
    return open_session(
        llm="fake",
        audit_path=project / "audit.jsonl",
        ask_log=project / "asks.jsonl",
        client_factory=client_factory or make_client,
    )


def comparable(payload: dict) -> dict:
    return {key: value for key, value in payload.items() if key not in VOLATILE}


# ------------------------------------------------------------------ sorunun dili


def test_a_turkish_golden_question_answers_in_turkish(project):
    payload = ask_payload(make_session(project), TR_QUESTION, mode="full")
    forced = ask_payload(make_session(project), TR_QUESTION, mode="full", lang="tr")

    assert payload["status"] == "answered" and payload["answer_lang"] == "tr"
    assert comparable(payload) == comparable(forced), "yeni anahtarın dışında hiçbir alan oynamaz"
    assert payload["facts"][0]["label"] == t("facts.row_count", "tr")


def test_an_english_question_answers_in_english(project):
    payload = ask_payload(make_session(project), EN_QUESTION, mode="full")

    assert payload["status"] == "answered" and payload["answer_lang"] == "en"
    assert payload["facts"][0]["label"] == t("facts.row_count", "en")


def test_a_choice_keeps_the_language_of_its_question(project):
    # Şıkkın metriği Türkçe harf taşısa da dili şıkkın değil sorunun kendisinin okunur (R8-6).
    payload = ask_payload(make_session(project), EN_QUESTION, mode="full", choice="Brüt")

    assert payload["answer_lang"] == "en"


# ------------------------------------------------------------------ hatanın cümlesi


def test_the_failure_sentence_follows_the_answer_language(project):
    session = make_session(project, client_factory=lambda mode: fake.FakeLLM(fake.never_submit()))
    turkish = ask_payload(session, "Ürünlerin listesi?", mode="full")
    english = ask_payload(session, "List the products?", mode="full")

    assert turkish["answer_lang"] == "tr" and english["answer_lang"] == "en"
    assert turkish["error"]["kind"] == english["error"]["kind"] == "no_submission"
    assert english["error"]["message"] == english["answer_text"] == t("ask.fail.no_submission", "en")
    assert turkish["answer_text"] == t("ask.fail.no_submission", "tr")
    # Ham hata kaybolmaz: ekranda cümle okunur, ayrıntı teknik alanda durur.
    assert english["error"]["detail"] and english["error"]["detail"] != english["answer_text"]


# ------------------------------------------------------------------ modülün kendisi


def test_ask_py_keeps_no_turkish_literal():
    assert user_literals(Path(ask.__file__)) == []
