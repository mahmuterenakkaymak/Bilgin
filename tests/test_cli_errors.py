# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""Kullanıcının düzeltebileceği iki arıza: veritabanı kurulmamış, uç nokta ölü.

İkisinde de ekranda iz dökümü değil tek bir cümle durmalı: dosya yoksa hangi yolun boş olduğu ve
"önce kur", uç nokta düşmüşse hangi adresin patladığı ve ne denenecek. Bu yüzden testler çıkış
koduna (kurulu değilse 2, uç nokta hiç çalışmıyorsa 3), cümlenin kendisine ve ``Traceback``
geçmediğine bakıyor. İkinci bir grup da kuralın sınırını tutuyor: uç nokta *bazen* düşüyorsa bu
artık ölçüm verisidir, koşu raporuyla birlikte tamamlanır.
"""

import pytest

from bilgin import config
from bilgin.agent import fake
from bilgin.agent.fake import FAKE_URL, FakeLLM
from bilgin.agent.llm import FAILED, UNREACHABLE, LLMError
from bilgin.cli import main as cli
from bilgin.eval import runner
from bilgin.schema_map import build

GOLDEN = runner.load_golden()
BY_ID = {line["id"]: line for line in GOLDEN}
BUILD = "Önce `python -m bilgin build-db` çalıştırın"


@pytest.fixture(scope="module")
def db(tmp_path_factory):
    """Modül boyunca tek kurulum: hata olmayan yollar da gerçek SQLite üzerinde yürüyor."""
    paths = tmp_path_factory.mktemp("cli-errors")
    database = paths / "test.db"
    build.build_db(config.SEED, database, paths / "test.sql")
    return database


class SometimesDown:
    """Uç noktanın tek bir soruda düştüğü istemci; öteki sorular altın kaydı oynatır."""

    def __init__(self, down_question: str, golden) -> None:
        self._down_question = down_question
        self._golden = golden

    def chat(self, messages, tools=None):
        asked = {str(message.get("content") or "") for message in messages}
        if self._down_question in asked:
            raise LLMError(UNREACHABLE.format(url=FAKE_URL))
        return self._golden.chat(messages, tools)


# ------------------------------------------------------------------ veritabanı yok


def test_ask_without_a_database_says_build_first(tmp_path, capsys):
    missing = tmp_path / "test.db"
    code = cli.ask(
        BY_ID["Q03"]["question"],
        fake.for_golden(GOLDEN),
        db_path=missing,
        audit_path=tmp_path / "audit.jsonl",
    )
    out = capsys.readouterr().out

    assert code == 2
    assert BUILD in out and str(missing) in out
    assert "Traceback" not in out and "SQLite" not in out


def test_eval_without_a_database_says_build_first(tmp_path, capsys):
    out_dir = tmp_path / "eval_out"
    code = cli.evaluate(
        fake.for_golden(GOLDEN),
        db_path=tmp_path / "test.db",
        audit_path=tmp_path / "audit.jsonl",
        out_dir=out_dir,
    )
    out = capsys.readouterr().out

    assert code == 2
    assert BUILD in out and "Traceback" not in out
    assert not out_dir.exists(), "kurulu olmayan veritabanının raporu yazılmamalı"


# ------------------------------------------------------------------ uç nokta ölü


def test_ask_names_the_dead_endpoint(db, tmp_path, capsys):
    code = cli.ask(
        BY_ID["Q03"]["question"],
        FakeLLM(fake.unreachable()),
        db_path=db,
        audit_path=tmp_path / "audit.jsonl",
    )
    out = capsys.readouterr().out

    assert code == 3
    assert FAKE_URL in out and "Strata" in out and "BILGIN_LLM_BASE_URL" in out
    assert "Traceback" not in out
    assert "Adımlar:" not in out, "yanıtlanmamış bir tur adım listesi olmaz"
    assert "Cevap gönderilmedi" not in out, "model reddetmedi, konuşamadı"


def test_eval_stops_when_the_endpoint_answers_nothing(db, tmp_path, capsys):
    out_dir = tmp_path / "eval_out"
    code = cli.evaluate(
        FakeLLM(fake.unreachable()),
        db_path=db,
        audit_path=tmp_path / "audit.jsonl",
        out_dir=out_dir,
    )
    out = capsys.readouterr().out

    assert code == 3
    assert FAKE_URL in out and "BILGIN_LLM_BASE_URL" in out and "Traceback" not in out
    assert "Skor:" not in out and not out_dir.exists()


def test_the_hint_is_added_when_the_error_carries_none(db, tmp_path, capsys):
    """HTTP 500 gibi bir hata adresi söyler ama ne deneneceğini söylemez; öneri CLI'den gelir."""
    code = cli.ask(
        BY_ID["Q03"]["question"],
        FakeLLM([LLMError(FAILED.format(url=FAKE_URL, error="HTTP 500"))]),
        db_path=db,
        audit_path=tmp_path / "audit.jsonl",
    )
    out = capsys.readouterr().out

    assert code == 3
    assert FAKE_URL in out and "BILGIN_LLM_BASE_URL" in out and "Traceback" not in out
    assert out.count(FAKE_URL) == 1, "adres iki kere saydırılmamalı"


def test_one_dead_question_is_still_a_score(db, tmp_path, capsys):
    out_dir = tmp_path / "eval_out"
    code = cli.evaluate(
        SometimesDown(BY_ID["Q01"]["question"], fake.for_golden(GOLDEN)),
        only=["Q01", "Q02"],
        db_path=db,
        audit_path=tmp_path / "audit.jsonl",
        out_dir=out_dir,
    )
    out = capsys.readouterr().out

    assert code == 0
    assert "Skor: 1/2" in out and "Hata:" not in out
    assert (out_dir / "latest" / "report.json").exists()
