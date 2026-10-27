"""Run 6 README'si: kullanıcılar ve roller, oturum, geliştirme yöneticisi ve harita ekranı.

``test_readme_run5``in Run 6 karşılığı: dokümanda yazılı olmayan bir komut ya da düğme kullanıcının
elinde yok sayılır, o yüzden her işaret ayrı bir parametrik testte README.md'de aranıyor. Ayrıca
``NL2SQL_DEV_ADMIN_PASSWORD=`` işaretinin yanında gerçek bir parola duramaz - yalnız köşeli ayraçlı
yer tutucu. Burada hiçbir komut koşulmaz; yalnız metin denetlenir.
"""

import re

import pytest

from readme_text import readme_text

# README'de birebir geçmesi gereken işaretler (R6 kullanıcı/rol yüzeyi, harita ekranı, SQL Server).
README_MARKS = (
    "user add",
    "--role admin",
    "NL2SQL_DEV_ADMIN_PASSWORD",
    "bilgin-veritabani-sablonu.xlsx",
    "Kontrol et",
    "Bu veri kümesine geç",
    "NL2SQL_MSSQL_CONN",
    "__DEGISTIR__",
    "Yeni bir veritabanını Bilgin'e tanıtmak",
)


def _readme() -> str:
    return readme_text()


@pytest.mark.parametrize("mark", README_MARKS)
def test_the_readme_documents_every_run6_mark(mark):
    assert mark in _readme(), f"{mark} README'de yok"


def test_the_dev_admin_variable_never_shows_a_password():
    """``NL2SQL_DEV_ADMIN_PASSWORD=<parola>`` yazılabilir; gerçek bir değer yazılamaz."""
    for line in _readme().splitlines():
        for match in re.finditer(r"NL2SQL_DEV_ADMIN_PASSWORD=(\S*)", line):
            value = match.group(1)
            assert re.fullmatch(r"<[^<>]+>", value), f"parola gibi duran değer: {line.strip()}"
