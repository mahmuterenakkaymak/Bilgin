# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""Servisin modeli: kurulumun profili servisin ortamına da yazılır (PLAN R8-22, R8-23).

Kurulum betiği model anahtarını ``config/models.json``daki bir profil için mühürler, ama servis
kendi ortamında doğar - shell'den miras alacağı ``BILGIN_LLM_MODEL`` yoktur. Profil XML'e
yazılmadığında servis programın varsayılanına başlar ve anahtarı başka bir profilin altında
arar. Test üç şeyi sabitler: ``model`` verilen XML o satırı taşır ve sırrın adını taşımayan bir
env anahtarı olduğu için reddedilmez; verilmeyen hiç taşımaz; ``service-xml`` profili hem
``--model``den hem koştuğu ortamın ``BILGIN_LLM_MODEL``inden alır, ``service-check`` de aynı
profilin ucunu yoklar.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET

from bilgin.agent.llm import get_profile
from bilgin.cli import main as cli
from bilgin.service import winsw

REPO = r"C:\dev\bilgin"
HOME = r"C:\ProgramData\Bilgin"
PYTHON = r"C:\dev\bilgin\.venv\Scripts\python.exe"
MODEL_ENV_KEY = "BILGIN_LLM_MODEL"
PROFILE = "qwen27b-24k"


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


def env_values(text: str) -> dict[str, str]:
    """XML kurulabildiği ölçüde okunur: kök zaten ``ET.fromstring``in işi."""
    return {env.get("key"): env.get("value") for env in ET.fromstring(text).findall("env")}


def test_the_sealed_profile_is_written_to_the_service_env():
    values = env_values(render(model=PROFILE))
    assert values[MODEL_ENV_KEY] == PROFILE
    assert list(values) == ["BILGIN_HOME", "BILGIN_LANG", "BILGIN_BACKEND", MODEL_ENV_KEY]


def test_no_model_line_when_the_installer_names_no_profile():
    text = render()
    assert MODEL_ENV_KEY not in env_values(text)
    assert "@MODEL_ENV@" not in text


def test_service_xml_writes_the_model_it_is_given(tmp_path, monkeypatch):
    monkeypatch.delenv("BILGIN_LLM_MODEL", raising=False)
    monkeypatch.delenv("BILGIN_DATASETS_DIR", raising=False)
    out = tmp_path / "Bilgin.xml"
    code = cli.main(
        [
            "service-xml",
            "--dataset",
            "wwi",
            "--home",
            HOME,
            "--model",
            PROFILE,
            "--out",
            str(out),
        ]
    )
    assert code == 0
    assert env_values(out.read_text(encoding="utf-8"))[MODEL_ENV_KEY] == PROFILE


def test_service_xml_takes_the_profile_from_the_environment_it_runs_in(tmp_path, monkeypatch):
    monkeypatch.setenv(MODEL_ENV_KEY, PROFILE)
    monkeypatch.delenv("BILGIN_DATASETS_DIR", raising=False)
    out = tmp_path / "Bilgin.xml"
    assert cli.main(["service-xml", "--dataset", "wwi", "--home", HOME, "--out", str(out)]) == 0
    assert env_values(out.read_text(encoding="utf-8"))[MODEL_ENV_KEY] == PROFILE


def test_service_check_probes_the_endpoint_of_the_profile_it_is_given(capsys, monkeypatch):
    monkeypatch.setenv("BILGIN_LLM_BASE_URL", "http://127.0.0.1:9999/v1")
    seen = []

    def up(profile) -> None:
        seen.append(profile)
        return None

    assert cli.service_check("synthetic_erp", json_out=True, model=PROFILE, ping=up) == 0
    assert seen == [get_profile(PROFILE)]
    assert get_profile(PROFILE).base_url in capsys.readouterr().out


def test_service_check_names_an_unknown_profile_instead_of_refusing(capsys):
    code = cli.service_check(
        "synthetic_erp", json_out=True, model="olmayan-profil", ping=lambda profile: None
    )
    assert code == 0
    assert "olmayan-profil" in capsys.readouterr().out
