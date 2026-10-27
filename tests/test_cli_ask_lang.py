"""T410: ``ask`` ve ``user *`` ekranı çözülen dilde (PLAN R8-5, R8-10).

Çerçeve ``cli.ask.*``/``cli.user.*`` kataloğundan ``--lang``da gelir; cevabın dili yine sorunun
dilidir (R8-6), yani ``--lang en`` Türkçe bir sorunun çevresini İngilizce söyler. tr çıktısı
bugünkü halidir: aynı komutların tr koşumu da burada durur. Model ``--llm fake``.
"""

import getpass
import re

import pytest

from nl2sql import config
from nl2sql.cli import main as cli
from nl2sql.eval import runner
from nl2sql.i18n import t
from nl2sql.schema_map import build

GOLDEN = runner.load_golden()
BY_ID = {line["id"]: line for line in GOLDEN}
# Altın kayıtta olmayan bir soru: sahte kendi stok sorgusunu oynatır, yani cevap yine de gelir.
EN_QUESTION = "How many products are there?"
PAROLA = "Parola2026!"
YENI = "YeniParola2026!"
# Çerçevenin Türkçe hali; İngilizce koşumda hiçbiri ekrana çıkmamalı.
TR_FRAME = ("Soru:", "Cevap SQL:", "Sonuç:", "Adımlar:", "Token:", "Süre:")
EN_FRAME = ("Question:", "Answer SQL:", "Result:", "Steps:", "Tokens:", "Time:")


@pytest.fixture
def project(tmp_path, monkeypatch):
    """Yollar tmp'ye çevrilir: ``ask`` çağrı anında config'den, konuşma deposu ``NL2SQL_APP_DB``den okur."""
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.db")
    monkeypatch.setattr(config, "INDEX_DIR", tmp_path / "index")
    monkeypatch.setattr(config, "AUDIT_LOG", tmp_path / "audit.jsonl")
    monkeypatch.setattr(config, "ASK_LOG", tmp_path / "asks.jsonl")
    monkeypatch.setenv("NL2SQL_APP_DB", str(tmp_path / "app.db"))
    return tmp_path


def build_db(tmp):
    build.build_db(config.SEED, tmp / "test.db", tmp / "test.sql")


def type_passwords(monkeypatch, *values) -> list[str]:
    """``getpass.getpass``in yerinde sıradaki parolayı döndüren sahte girdi; sorulanlar da birikir."""
    asked: list[str] = []
    remaining = list(values)

    def fake(prompt=""):
        asked.append(prompt)
        return remaining.pop(0)

    monkeypatch.setattr(getpass, "getpass", fake)
    return asked


def answer_lines(out: str) -> list[str]:
    """Cevap satırları: başlığı iki dilde de aranır, yani satırın kendisi dilin kanıtıdır."""
    return [line for line in out.splitlines() if line.startswith(("Cevap: ", "Answer: "))]


# ------------------------------------------------------------------ ask


def test_english_frame_around_the_turkish_answer(project, capsys):
    build_db(project)
    line = BY_ID["Q02"]
    code = cli.main(["ask", line["question"], "--llm", "fake", "--mode", "full", "--lang", "en"])
    out = capsys.readouterr().out

    assert code == 0
    assert f"Question: {line['question']}" in out
    assert "Answer SQL:" in out and line["sql"] in out
    assert "Result:" in out and "Tokens:" in out and "Time:" in out
    assert all(head in out for head in EN_FRAME)
    assert all(turkish not in out for turkish in TR_FRAME)
    # cevabın dili sorunun dilidir (R8-6): İngilizce çerçevenin içinde Türkçe olgu cümlesi durur
    answer = answer_lines(out)[0]
    assert t("facts.row_count", "tr") in answer and t("facts.row_count", "en") not in answer


def test_an_english_question_answers_in_english(project, capsys):
    build_db(project)
    code = cli.main(["ask", EN_QUESTION, "--llm", "fake", "--mode", "full", "--lang", "en"])
    out = capsys.readouterr().out

    assert code == 0
    answer = answer_lines(out)[0]
    assert t("facts.row_count", "en") in answer and t("facts.row_count", "tr") not in answer


def test_the_conversation_line_follows_the_flag(project, capsys):
    build_db(project)
    code = cli.main(
        ["ask", BY_ID["Q02"]["question"], "--llm", "fake", "--mode", "full", "--new", "--lang", "en"]
    )
    out = capsys.readouterr().out

    assert code == 0
    assert re.search(r"Conversation: [0-9a-f]+ · turn 1", out)
    assert "Konuşma:" not in out


def test_a_missing_db_says_so_in_english(project, capsys):
    code = cli.main(["ask", "Ciro ne kadar?", "--llm", "fake", "--mode", "full", "--lang", "en"])
    out = capsys.readouterr().out

    assert code == 2
    assert "No database:" in out and "build-db" in out
    assert "Veritabanı yok" not in out


# ------------------------------------------------------------------ user *


def test_user_list_header_in_english(project, monkeypatch, capsys):
    type_passwords(monkeypatch, PAROLA, PAROLA)
    assert cli.main(["user", "add", "admin", "--role", "admin"]) == 0
    capsys.readouterr()

    assert cli.main(["user", "list", "--lang", "en"]) == 0
    listing = capsys.readouterr().out

    for column in ("User", "Role", "Business role", "Status", "Last login"):
        assert column in listing
    for turkish in ("Kullanıcı", "İş rolü", "Durum", "Son giriş", "etkin"):
        assert turkish not in listing
    assert "admin" in listing and "active" in listing


def test_the_password_prompts_and_the_errors_follow_the_flag(project, monkeypatch, capsys):
    asked = type_passwords(monkeypatch, PAROLA, YENI)
    assert cli.main(["user", "add", "admin", "--role", "admin", "--lang", "en"]) == 2

    assert asked == ["Password: ", "Password (repeat): "]
    assert "Passwords do not match." in capsys.readouterr().out

    type_passwords(monkeypatch, PAROLA, PAROLA)
    assert cli.main(["user", "add", "admin", "--role", "admin", "--lang", "en"]) == 0
    added = capsys.readouterr().out
    assert "✓ admin added (role admin)." in added and "Business role:" in added

    assert cli.main(["user", "passwd", "yok", "--lang", "en"]) == 2
    assert "The user was not found." in capsys.readouterr().out

    assert cli.main(["user", "set", "admin", "--deactivate", "--lang", "en"]) == 2
    assert t("auth.last_admin", "en") in capsys.readouterr().out


# ------------------------------------------------------------------ tr bugün neyse o


def test_turkish_output_is_todays(project, monkeypatch, capsys):
    build_db(project)
    line = BY_ID["Q02"]
    assert cli.main(["ask", line["question"], "--llm", "fake", "--mode", "full"]) == 0
    out = capsys.readouterr().out

    assert f"Soru: {line['question']}" in out
    assert "Cevap SQL:" in out and line["sql"] in out
    assert all(head in out for head in TR_FRAME)
    assert all(english not in out for english in EN_FRAME)
    assert f"Cevap: {t('facts.row_count', 'tr')}" in out

    type_passwords(monkeypatch, PAROLA, PAROLA)
    assert cli.main(["user", "add", "admin", "--role", "admin"]) == 0
    assert "✓ admin eklendi (rol admin)." in capsys.readouterr().out

    assert cli.main(["user", "list"]) == 0
    listing = capsys.readouterr().out
    for column in ("Kullanıcı", "Rol", "İş rolü", "Durum", "Son giriş"):
        assert column in listing
    assert "etkin" in listing and "active" not in listing
