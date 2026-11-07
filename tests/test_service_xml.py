# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""``deploy/windows/bilgin.xml`` şablonu ve ``python -m nl2sql service-xml`` (PLAN R8-22, R8-23).

Kurulum betiği XML'i elle yazmaz, şablonun boşluklarını programın kendisine doldurur; test o
yüzden üç şeyi sabitler. Birincisi XML gerçekten kurulacak servisi anlatır: çalıştırılacak dosya,
komut satırı, çalışma klasörü, ortam anahtarları, üç restart denemesi, gecikmeli otomatik
başlangıç, sanal hesap ve ``NL2SQL_HOME``ın altındaki günlük klasörü. İkincisi sırrın *adı* bile
XML'e yaklaşmaz - ortamda bir bağlantı dizesi ya da kurulum parolası dururken çıktının hiçbir
satırına düşmez, şablona sır taşıyan bir env anahtarı yazılsa bile reddedilir. Üçüncüsü yarım
boşluk yoktur: doldurulmayan bir token servis yanlış bir değerle başlamasın diye fırlatır.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from nl2sql import config
from nl2sql.cli import main as cli
from nl2sql.service import winsw

REPO = r"C:\dev\bilgin"
HOME = r"C:\ProgramData\Bilgin"
PYTHON = r"C:\dev\bilgin\.venv\Scripts\python.exe"
ENV_KEYS = ["NL2SQL_HOME", "NL2SQL_LANG", "NL2SQL_BACKEND"]
CONN_STR = "DRIVER={ODBC Driver 18 for SQL Server};SERVER=sunucu;UID=ro;PWD=gizli-parola-1;"
ADMIN_PASSWORD = "bulucu-parola-9"


def render(**overrides) -> str:
    args = {
        "python_exe": PYTHON,
        "repo": REPO,
        "home": HOME,
        "port": 8777,
        "dataset": "wwi",
        "lang": "tr",
        "backend": "sqlite",
    }
    args.update(overrides)
    return winsw.render_xml(**args)


def env_keys(text: str) -> list[str]:
    return [env.get("key") for env in ET.fromstring(text).findall("env")]


def broken_template(monkeypatch, tmp_path, old: str, new: str) -> None:
    """Şablonun tek satırını bozan kopya: iki red de şablonun kendisinden doğar."""
    path = tmp_path / "bilgin.xml"
    path.write_text(
        winsw.TEMPLATE_PATH.read_text(encoding="utf-8").replace(old, new), encoding="utf-8"
    )
    monkeypatch.setattr(winsw, "TEMPLATE_PATH", path)


def test_the_rendered_xml_is_the_service_the_installer_needs():
    root = ET.fromstring(render())
    assert root.findtext("executable") == PYTHON
    assert (
        root.findtext("arguments") == "-m nl2sql serve --host 127.0.0.1 --port 8777 --dataset wwi"
    )
    assert root.findtext("workingdirectory") == REPO
    assert env_keys(render()) == ENV_KEYS
    assert [(f.get("action"), f.get("delay")) for f in root.findall("onfailure")] == [
        ("restart", "10 sec"),
        ("restart", "30 sec"),
        ("restart", "60 sec"),
    ]
    assert root.findtext("startmode") == "Automatic"
    assert root.findtext("delayedAutoStart") == "true"
    assert root.findtext("serviceaccount/username") == r"NT SERVICE\Bilgin"
    assert Path(root.findtext("logpath")) == Path(HOME) / "logs"
    assert root.find("log").get("mode") == "roll-by-size"


def test_datasets_dir_env_line_appears_only_when_it_is_given():
    text = render(datasets_dir=r"D:\kümeler")
    assert env_keys(text) == [*ENV_KEYS, "NL2SQL_DATASETS_DIR"]
    values = {env.get("key"): env.get("value") for env in ET.fromstring(text).findall("env")}
    assert values["NL2SQL_DATASETS_DIR"] == r"D:\kümeler"


def test_the_display_name_says_which_language_the_service_was_installed_in():
    assert ET.fromstring(render(lang="tr")).findtext("name") == "Bilgin - yerel veri analisti"
    assert ET.fromstring(render(lang="en")).findtext("name") == "Bilgin - local data analyst"
    english = ET.fromstring(render(lang="en", port=8899, dataset="wwi_real"))
    assert english.findtext("description") == (
        "Bilgin local data analyst: http://127.0.0.1:8899 (dataset: wwi_real)"
    )


def test_the_secrets_of_the_environment_never_reach_the_xml(monkeypatch):
    monkeypatch.setenv("NL2SQL_MSSQL_CONN", CONN_STR)
    monkeypatch.setenv("NL2SQL_DEV_ADMIN_PASSWORD", ADMIN_PASSWORD)
    text = render()
    assert ADMIN_PASSWORD not in text
    assert "gizli-parola-1" not in text
    assert "NL2SQL_MSSQL_CONN" not in text
    assert env_keys(text) == ENV_KEYS


def test_an_env_key_that_admits_a_secret_is_refused(monkeypatch, tmp_path):
    broken_template(
        monkeypatch,
        tmp_path,
        '<env key="NL2SQL_BACKEND"',
        '<env key="NL2SQL_MSSQL_CONN" value="x" />\n  <env key="NL2SQL_BACKEND"',
    )
    with pytest.raises(ValueError, match="NL2SQL_MSSQL_CONN"):
        render()


def test_a_token_the_code_does_not_fill_is_refused(monkeypatch, tmp_path):
    broken_template(monkeypatch, tmp_path, "<id>Bilgin</id>", "<id>@SERVICE_ID@</id>")
    with pytest.raises(ValueError, match="SERVICE_ID"):
        render()


def test_a_path_with_an_ampersand_survives_the_round_trip():
    text = render(repo=r"C:\a&b\bilgin", home=r"C:\Program Data\K&K")
    assert "&amp;" in text
    root = ET.fromstring(text)
    assert root.findtext("workingdirectory") == r"C:\a&b\bilgin"
    assert root.findtext("logpath") == r"C:\Program Data\K&K\logs"
    values = {env.get("key"): env.get("value") for env in root.findall("env")}
    assert values["NL2SQL_HOME"] == r"C:\Program Data\K&K"


def test_service_xml_writes_the_file_and_prints_only_its_path(tmp_path, capsys, monkeypatch):
    monkeypatch.delenv("NL2SQL_DATASETS_DIR", raising=False)
    monkeypatch.setenv("NL2SQL_MSSQL_CONN", CONN_STR)
    monkeypatch.setenv("NL2SQL_DEV_ADMIN_PASSWORD", ADMIN_PASSWORD)
    out = tmp_path / "deploy" / "bilgin.xml"
    code = cli.main(
        [
            "service-xml",
            "--port",
            "8899",
            "--dataset",
            "wwi",
            "--home",
            HOME,
            "--out",
            str(out),
        ]
    )
    assert code == 0
    text = out.read_text(encoding="utf-8")
    assert "--port 8899" in text and "--dataset wwi" in text
    assert env_keys(text) == ENV_KEYS
    assert ADMIN_PASSWORD not in text and "gizli-parola-1" not in text
    printed = capsys.readouterr().out.strip()
    assert printed.endswith(str(out)) and "<" not in printed


def test_service_xml_prints_the_xml_itself_when_no_out_is_given(capsys, monkeypatch):
    monkeypatch.delenv("NL2SQL_DATASETS_DIR", raising=False)
    assert cli.main(["service-xml", "--dataset", "wwi", "--home", HOME, "--lang", "en"]) == 0
    root = ET.fromstring(capsys.readouterr().out)
    assert root.findtext("name") == "Bilgin - local data analyst"
    assert root.findtext("workingdirectory") == str(config.ROOT)
