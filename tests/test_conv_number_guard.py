# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""T292: Bekçi ikinci turun sayılarını birinci turdan almaz (PLAN R7-6, brief §4).

Dünya gerçek (``build_db`` ile kurulmuş sentetik ERP) ve cevap gerçek ``ask_payload``dan gelir;
yalnız anlatıcı senaryolu sahte: ikinci turun cümlesine birinci turun toplamını kopyalar. İddia
aynı kaynağın dört yüzünde okunur: bekçi o sayıyı geçirmiyor, cevap şablon cümleye düşüyor, ve
ikinci turun izin listesi yalnız kendi kolonlarının, satırlarının, olgularının ve sorusunun
sayılarıdır — kullanıcının soruya kendisinin yazdığı sayı serbest, miras kalan sayı yasak.
"""

import pytest

from nl2sql import config
from nl2sql.agent import fake
from nl2sql.agent.llm import ChatResponse
from nl2sql.app.ask import ask_payload
from nl2sql.app.conversations import ConversationStore
from nl2sql.app.session import open_session
from nl2sql.report import fmt, guard, narrate
from nl2sql.schema_map import build

TOTAL_SQL = "SELECT SUM(STHAR_GCMIK * STHAR_NF) AS TOPLAM FROM TBLSTHAR WHERE STHAR_GCKOD = 'C'"
LIST_SQL = "SELECT TOP 5 STOK_KODU, STOK_ADI FROM TBLSTSABIT ORDER BY STOK_KODU"

# İkinci turun sorusu kendi sayısını taşıyor: kullanıcının yazdığı sayı kendi turunda serbesttir.
Q1 = "Satışların toplam tutarı ne kadar?"
Q2 = "Bunların ilk 7 satırını yazar mısın?"
TYPED = 7

# Birinci tur toplamı, ikinci tur aynı ürünlerin listesini cevaplar.
TWO_TURNS = [fake.wrong_sql(TOTAL_SQL), fake.wrong_sql(LIST_SQL)]


class Scripted:
    """Ajanın sahte modeli: her koşum sıradaki senaryoyu oynar (T291'in düzeni)."""

    def __init__(self, scripts):
        self._scripts = list(scripts)
        self._run = -1

    def client_factory(self, mode):
        self._run += 1
        return fake.FakeLLM(self._scripts[min(self._run, len(self._scripts) - 1)])


class Recording:
    """Senaryolu anlatıcının etrafında sayaç: reddin gerekçesi payload'a inmez, istekten okunur."""

    def __init__(self, client):
        self.client = client
        self.calls = []

    def chat(self, messages, tools=None):
        self.calls.append(messages)
        return self.client.chat(messages, tools)


def narrator(sentences):
    """Her denemede sıradaki cümleyi söyleyen sahte anlatıcı."""
    return Recording(fake.FakeLLM([ChatResponse(content=text) for text in sentences]))


def run_turn(session, store, question, conversation_id=None, speaker=None):
    """Bir turu ``ask_payload``la koşar; ``speaker`` verilirse anlatıcının yerine geçer."""
    if speaker is not None:
        session.narrator = lambda: speaker
    return ask_payload(
        session, question, mode="full", conversations=store, conversation_id=conversation_id
    )


def allowed(payload):
    """O turun kendi izin listesi: bekçinin anlatıcıya verdiği havuzun aynısı (PLAN R5-8)."""
    return guard.allowed_values(
        payload["columns"], payload["rows"], payload["facts"], payload["question"]
    )


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "ROOT", tmp_path)
    return tmp_path


@pytest.fixture(scope="module")
def erp_db(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("conv-number-guard")
    path = tmp / "test.db"
    build.build_db(config.SEED, path, path.with_suffix(".sql"))
    return path


@pytest.fixture
def store(tmp_path):
    return ConversationStore(tmp_path / "app.db")


@pytest.fixture
def world(erp_db, project):
    """``(oturum)`` üreteci: günlükler tmp'de, konuşma deposu çağırandan (T291'in düzeni)."""

    def make(scripts):
        return open_session(
            llm="fake",
            db_path=erp_db,
            audit_path=project / "audit.jsonl",
            ask_log=project / "asks.jsonl",
            client_factory=Scripted(scripts).client_factory,
        )

    return make


# ------------------------------------------------------------------ kopyalanan sayı geçmez


def test_the_first_turns_total_copied_into_the_second_answer_falls_back(project, store, world):
    session = world(TWO_TURNS)
    first = run_turn(session, store, Q1)
    assert first["status"] == "answered" and first["rows"]

    leak = fmt.tr_number(first["rows"][0][0])
    speaker = narrator([f"Önceki cevapta toplam {leak} çıkmıştı.", f"Toplam yine {leak}."])
    second = run_turn(session, store, Q2, conversation_id=first["conversation_id"], speaker=speaker)

    assert second["status"] == "answered"
    assert second["narration_source"] == "template", "bekçiyi geçmeyen cümle ekrana çıkmaz"
    assert second["answer_text"] == narrate.template_sentence(Q2, second["facts"])
    assert leak not in second["answer_text"]
    assert len(speaker.calls) == 2, "bir deneme, bir yeniden yazma; üçüncüsü yok"
    assert speaker.calls[1][-1]["content"] == (
        f"Şu sayılar sonuçta yok: {leak}. Yalnız verilen sayılarla yeniden yaz."
    ), "reddin gerekçesi kopyalanan sayıdır"


# ------------------------------------------------------------------ kullanıcının kendi sayısı


def test_the_number_the_user_typed_in_the_second_question_is_allowed(project, store, world):
    session = world(TWO_TURNS)
    first = run_turn(session, store, Q1)
    speaker = narrator([f"İlk {TYPED} satırın kodlarını ve adlarını sıraladım."])

    second = run_turn(session, store, Q2, conversation_id=first["conversation_id"], speaker=speaker)

    assert second["narration_source"] == "llm", "sorunun kendi sayısı bekçiyi geçer"
    assert str(TYPED) in second["answer_text"]
    assert len(speaker.calls) == 1, "geçen cümle için yeniden yazma yoktur"


# ------------------------------------------------------------------ izin listesinin sınırı


def test_each_turns_allowed_set_holds_only_its_own_numbers(project, store, world):
    session = world(TWO_TURNS)
    first = run_turn(session, store, Q1)
    second = run_turn(session, store, Q2, conversation_id=first["conversation_id"])

    total = first["rows"][0][0]
    first_allowed, second_allowed = allowed(first), allowed(second)
    assert total in first_allowed["values"], "birinci turun sayısı kendi turundadır"
    assert total not in second_allowed["values"], "izin listesi geçmişin sayısını taşımaz"
    assert not guard.check_text(f"Toplam {fmt.tr_number(total)}.", second_allowed).ok
    assert guard.check_text(f"İlk {TYPED} satır.", second_allowed).ok
