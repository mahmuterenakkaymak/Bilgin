"""Sır klasörü: bir Windows servisi ortam değişkeni taşımadığı için anahtar dosyada durur (R8-21).

Bloblar DPAPI ile mühürlüdür, o yüzden yaz/oku çifti yalnız Windows'ta koşar; öbür makine
``read_secret``ın ``None``ını ve komutun kaçıncı kodla çıktığını görür. İkinci mesele sırrın
sızıntısıdır: ne ekran ne log satırı anahtarın değerini taşımaz.
"""

import getpass
import logging
import sys

import pytest

from nl2sql import config
from nl2sql.agent import llm
from nl2sql.cli import main as cli
from nl2sql.engine import dpapi
from nl2sql.service import secrets

ENV = "NL2SQL_TEST_MODEL_KEY"
KEY = "sk-test-4f9c2e7a1b"

WINDOWS = pytest.mark.skipif(sys.platform != "win32", reason="DPAPI yalnız Windows'ta vardır")


@pytest.fixture
def home(tmp_path, monkeypatch):
    """Sır klasörü tmp'nin altına taşınır: ``home=`` da config'in sabiti de orayı görür."""
    monkeypatch.setattr(config, "SECRETS_DIR", tmp_path / "secrets")
    return tmp_path


def type_key(monkeypatch, *values) -> list[str]:
    """``getpass.getpass``in yerinde sıradaki anahtarı döndüren sahte girdi; sorulanlar birikir."""
    asked: list[str] = []
    remaining = list(values)

    def fake(prompt=""):
        asked.append(prompt)
        return remaining.pop(0)

    monkeypatch.setattr(getpass, "getpass", fake)
    return asked


# ------------------------------------------------------------------ entropy + path


def test_the_entropy_is_the_variable_name_behind_the_project_prefix():
    assert secrets.entropy_for(ENV) == f"bilgin-secret:{ENV}".encode("utf-8")


def test_the_default_folder_is_the_home_secrets_dir(home):
    assert secrets.secret_path(ENV) == home / "secrets" / f"{ENV}.bin"


# ------------------------------------------------------------------ read + write


@WINDOWS
def test_a_written_blob_is_read_back(home):
    path = secrets.write_secret(ENV, KEY, home=home)

    assert path == home / "secrets" / f"{ENV}.bin"
    assert KEY.encode("utf-8") not in path.read_bytes()
    assert secrets.read_secret(ENV, home=home) == KEY


@WINDOWS
def test_a_missing_file_is_no_secret_and_logs_nothing(home, caplog):
    with caplog.at_level(logging.WARNING):
        assert secrets.read_secret("NL2SQL_TEST_ABSENT_KEY", home=home) is None

    assert caplog.records == []


@WINDOWS
def test_a_blob_sealed_to_another_name_is_no_secret_with_one_log_line(home, caplog):
    path = secrets.secret_path(ENV, home=home)
    path.parent.mkdir(parents=True)
    path.write_bytes(dpapi.protect(KEY.encode("utf-8"), b"bilgin-secret:OPENAI_API_KEY"))

    with caplog.at_level(logging.WARNING):
        assert secrets.read_secret(ENV, home=home) is None

    assert len(caplog.records) == 1
    assert KEY not in caplog.text


def test_a_machine_without_dpapi_reads_no_secret_even_when_the_file_is_there(home, monkeypatch):
    path = secrets.secret_path(ENV, home=home)
    path.parent.mkdir(parents=True)
    path.write_bytes(b"not-a-dpapi-blob")
    monkeypatch.setattr(secrets.sys, "platform", "linux")

    assert secrets.read_secret(ENV, home=home) is None


# ------------------------------------------------------------------ the llm key


@WINDOWS
def test_the_llm_key_comes_from_the_file_when_the_env_var_is_unset(home, monkeypatch):
    monkeypatch.delenv(ENV, raising=False)
    secrets.write_secret(ENV, KEY, home=home)

    assert llm.key_missing_reason(ENV) is None
    assert llm._api_key(ENV) == KEY


@WINDOWS
def test_the_env_var_wins_when_both_the_env_and_the_file_exist(home, monkeypatch):
    secrets.write_secret(ENV, KEY, home=home)
    monkeypatch.setenv(ENV, "env-key")

    assert llm._api_key(ENV) == "env-key"


def test_a_key_in_neither_place_is_refused_by_its_variable_name(home, monkeypatch):
    monkeypatch.delenv(ENV, raising=False)

    assert ENV in llm.key_missing_reason(ENV)
    with pytest.raises(llm.LLMError):
        llm._api_key(ENV)


# ------------------------------------------------------------------ secret-set


@WINDOWS
def test_secret_set_writes_the_blob_and_prints_only_the_path(home, monkeypatch, capsys):
    asked = type_key(monkeypatch, KEY, KEY)

    assert cli.main(["secret-set", ENV]) == 0

    out = capsys.readouterr().out
    assert len(asked) == 2 and asked[0] != asked[1]
    assert KEY not in out
    assert str(secrets.secret_path(ENV, home=home)) in out
    assert secrets.read_secret(ENV, home=home) == KEY


@WINDOWS
def test_a_mismatched_second_typing_writes_nothing(home, monkeypatch, capsys):
    type_key(monkeypatch, KEY, KEY + "x")

    assert cli.main(["secret-set", ENV]) == 2

    assert not secrets.secret_path(ENV, home=home).exists()
    assert KEY not in capsys.readouterr().out


@WINDOWS
def test_an_empty_key_writes_nothing(home, monkeypatch, capsys):
    type_key(monkeypatch, "", "")

    assert cli.main(["secret-set", ENV]) == 2

    assert not secrets.secret_path(ENV, home=home).exists()


def test_the_command_refuses_a_machine_without_dpapi(home, monkeypatch, capsys):
    type_key(monkeypatch, KEY, KEY)
    monkeypatch.setattr(dpapi, "available", lambda: False)

    assert cli.main(["secret-set", ENV, "--lang", "en"]) == 2

    assert not (home / "secrets").exists()
    out = capsys.readouterr().out
    assert KEY not in out
    assert ENV in out
