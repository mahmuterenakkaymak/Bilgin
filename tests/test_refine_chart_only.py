# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""T298: "Grafiği çubuk yap" modeli koşurmaz (PLAN R7-10).

Dünya gerçek (``build_db`` ile kurulmuş sentetik ERP), ajan ve anlatıcı sayaçlı sahte: iddianın
özü ikisinin de hiç çağrılmaması, yani sunum değişikliğinin sayı uyduracak bir tarafının
kalmaması. Cevabın SQL'i birinci turun SQL'iyle birebir aynı, grafiği istenen türde, cümlesi
koddan; biçim isteği kaldırmıyorsa eski grafik kalıp gerekçe konuşur. İşaret yeni bir konuşmaya
sorulursa - yani yeniden koşulacak bir sorgu yoksa - ajan her zamanki gibi koşar.
"""

import json

import pytest

from nl2sql import config
from nl2sql.agent import fake
from nl2sql.app.ask import ask_payload
from nl2sql.app.conversations import ConversationStore
from nl2sql.app.session import open_session
from nl2sql.schema_map import build

# Birinci turun biçimi çizgi (tarih + sayı): "çubuk" isteği türü gerçekten değiştiriyor.
MONTH_SQL = (
    "SELECT TOP 8 TARIH, SUM(GENELTOPLAM) AS TOPLAM FROM TBLFATUIRS"
    " WHERE IPTAL = 'H' GROUP BY TARIH ORDER BY TARIH"
)
# Birinci turun biçimi sütun (kategori + sayı): "çizgi" isteği biçime çarpıyor.
STOCK_SQL = (
    "SELECT TOP 5 STOK_KODU, SUM(STHAR_GCMIK) AS MIKTAR FROM TBLSTHAR"
    " GROUP BY STOK_KODU ORDER BY MIKTAR DESC"
)

Q_MONTH = "Aylık fatura toplamı ne kadar?"
Q_STOCK = "Ürünlerin toplam çıkış miktarı ne kadar?"
BAR_WISH = "Grafiği çubuk yap"
LINE_WISH = "Grafiği çizgi yap"


class Scripted:
    """Ajanın sahte modeli: her koşum sıradaki senaryoyu oynar ve her isteği sayar (T291'in düzeni)."""

    def __init__(self, scripts):
        self._scripts = list(scripts)
        self._run = -1
        self.chats = 0

    def client_factory(self, mode):
        self._run += 1
        return self

    def chat(self, messages, tools=None):
        self.chats += 1
        script = self._scripts[min(self._run, len(self._scripts) - 1)]
        return fake.FakeLLM(script).chat(messages, tools)


class Recording:
    """Senaryolu anlatıcının etrafında sayaç: kaç kez cümle istendiği buradan okunur."""

    def __init__(self, client):
        self.client = client
        self.calls = []

    def chat(self, messages, tools=None):
        self.calls.append(messages)
        return self.client.chat(messages, tools)


def records(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "ROOT", tmp_path)
    return tmp_path


@pytest.fixture(scope="module")
def erp_db(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("refine-chart-only")
    path = tmp / "test.db"
    build.build_db(config.SEED, path, path.with_suffix(".sql"))
    return path


@pytest.fixture
def store(tmp_path):
    return ConversationStore(tmp_path / "app.db")


@pytest.fixture
def world(erp_db, project):
    """``(oturum, ajan, anlatıcı)`` üreteci: günlükler tmp'de, konuşma deposu çağırandan."""

    def make(scripts):
        scripted = Scripted(scripts)
        speaker = Recording(fake.narration_client())
        session = open_session(
            llm="fake",
            db_path=erp_db,
            audit_path=project / "audit.jsonl",
            ask_log=project / "asks.jsonl",
            client_factory=scripted.client_factory,
        )
        session.narrator = lambda: speaker
        return session, scripted, speaker

    return make


def two_turns(world, store, question, first_sql, wish):
    """İki turu tek konuşmada koşar: ``(birinci, ikinci, (ajan, anlatıcı), birinci turun sayaçları)``."""
    session, scripted, speaker = world([fake.wrong_sql(first_sql)])
    first = ask_payload(session, question, mode="full", conversations=store)
    before = (scripted.chats, len(speaker.calls))
    second = ask_payload(
        session, wish, mode="full", conversations=store, conversation_id=first["conversation_id"]
    )
    return first, second, (scripted, speaker), before


# ------------------------------------------------------------------ modelsiz sunum değişikliği


def test_a_chart_wish_reruns_the_previous_sql_without_any_model(project, store, world):
    first, second, (scripted, speaker), before = two_turns(world, store, Q_MONTH, MONTH_SQL, BAR_WISH)

    assert before[0] > 0 and before[1] > 0, "birinci tur model ve anlatıcıyı gerçekten koştu"
    assert (scripted.chats, len(speaker.calls)) == before, "sunum değişikliği modeli koşurmaz"
    assert second["status"] == "answered" and second["turn"] == 2
    assert second["sql"] == MONTH_SQL and second["rows"] == first["rows"]
    assert first["chart"]["type"] == "line" and second["chart"]["type"] == "bar"
    assert "reason" not in second["chart"], "biçim isteği kaldırdı"
    assert second["answer_text"] == "Grafik çubuk olarak gösteriliyor."
    assert second["narration_source"] == "template"
    assert [step["tool"] for step in second["steps"]] == ["chart"]
    assert second["facts"], "olgular koddan yeniden kurulur"
    assert second["context"] == {
        "uses_turns": [1],
        "entities": [],
        "refines_sql_of": 1,
        "line": "Önceki cevaptan: 1. turun sorgusu temel alındı.",
    }


def test_the_rerun_is_audited_under_this_turn_and_stored_as_its_own(project, store, world):
    first, second, _, _ = two_turns(world, store, Q_MONTH, MONTH_SQL, BAR_WISH)

    lines = records(project / "audit.jsonl")
    reruns = [line for line in lines if line["source"] == f"web:{second['audit_id']}"]
    assert [line["sql"] for line in reruns] == [MONTH_SQL] and reruns[0]["outcome"] == "ok"

    turn = store.get(first["conversation_id"])["turns"][1]
    assert turn["sql"] == MONTH_SQL and turn["answer_text"] == second["answer_text"]
    assert turn["summary"]["chart_kind"] == "bar"
    assert turn["summary"]["context"]["line"] == second["context"]["line"]
    assert [line["turn"] for line in records(project / "asks.jsonl")] == [1, 2]


# ------------------------------------------------------------------ biçimin kaldırmadığı istek


def test_a_wish_the_shape_refuses_keeps_the_old_chart_and_says_why(project, store, world):
    first, second, (scripted, speaker), before = two_turns(world, store, Q_STOCK, STOCK_SQL, LINE_WISH)

    assert (scripted.chats, len(speaker.calls)) == before
    assert second["status"] == "answered" and second["sql"] == STOCK_SQL
    assert first["chart"]["type"] == second["chart"]["type"] == "bar", "eski grafik kalır"
    assert "tarih" in second["chart"]["reason"]
    assert second["answer_text"] == second["chart"]["reason"]
    assert second["narration_source"] == "template"


# ------------------------------------------------------------------ yeniden koşulacak sorgu yok


def test_the_same_wish_on_a_new_conversation_goes_to_the_agent(project, store, world):
    session, scripted, speaker = world([fake.wrong_sql(STOCK_SQL)])

    payload = ask_payload(session, BAR_WISH, mode="full", conversations=store)

    assert scripted.chats > 0 and len(speaker.calls) > 0, "yeni konuşmada ajan her zamanki gibi koşar"
    assert payload["status"] == "answered" and payload["turn"] == 1
    assert payload["sql"] == STOCK_SQL and "chart" not in [step["tool"] for step in payload["steps"]]
    assert payload["context"] is None, "notu olmayan tur bağlam taşımaz"
