"""Windows servis bölümü (R8-20..R8-23): iki README de aynı kurulum sayfasını taşıyor.

Servis bir kez kurulur ve sonra elle yoklanır; betik adları, `-WhatIf`, `-RemoveData`,
`NL2SQL_HOME`, `WinSwSha256`, `python -m nl2sql paths` ve yeniden başlatma denetimi bir dilde
yazılmadıysa o dildeki kurulumcu onların varlığından habersiz kalır. Bölümün başlığı dildedir
(`## Windows service` / `## Windows servisi`), o yüzden her işaret dosyasında aranıyor; yeniden
başlatma da her iki dilin kendi sözüyle denetleniyor. Burada hiçbir komut koşulmaz; yalnız metin
denetlenir.
"""

import pytest

from nl2sql import config

# Dosya başlığı ve yeniden başlatma cümlesinin o dildeki hali.
FILES = {
    "README.md": {"heading": "## Windows service", "reboot": "reboot"},
    "README.tr.md": {"heading": "## Windows servisi", "reboot": "yeniden başlat"},
}

# Bölümde birebir geçmesi gereken işaretler: üç betik, iki bayrak, veri kökü, yolların kaynağı,
# doldurulması gereken sabit ve servisin adresi.
SERVICE_MARKS = (
    "scripts\\install-service.ps1",
    "scripts\\update-service.ps1",
    "scripts\\uninstall-service.ps1",
    "-WhatIf",
    "-RemoveData",
    "NL2SQL_HOME",
    "C:\\ProgramData\\Bilgin",
    "python -m nl2sql paths",
    "WinSwSha256",
    "http://127.0.0.1:8777",
)


def _readme(name: str) -> str:
    return (config.ROOT / name).read_text(encoding="utf-8")


@pytest.mark.parametrize("name", sorted(FILES))
def test_the_file_has_the_service_heading(name):
    lines = _readme(name).splitlines()
    assert FILES[name]["heading"] in lines, f'{FILES[name]["heading"]} {name} içinde başlık değil'


@pytest.mark.parametrize("mark", SERVICE_MARKS)
@pytest.mark.parametrize("name", sorted(FILES))
def test_both_readmes_document_the_service_mark(name, mark):
    assert mark in _readme(name), f"{mark} {name} içinde yok"


@pytest.mark.parametrize("name", sorted(FILES))
def test_both_readmes_document_the_reboot_check(name):
    text = _readme(name).lower()
    assert FILES[name]["reboot"] in text, f"yeniden başlatma denetimi {name} içinde yok"
