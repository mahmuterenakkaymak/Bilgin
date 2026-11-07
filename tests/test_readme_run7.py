# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""Run 7 README'si: konuşma — ardışık sorular, kanıt satırı, CLI bayrakları ve `eval --followups`.

Aynı denetim Run 7'nin öteki bölümü için de koşar: ``## Başlangıç ekranı ve hazır sorular``
(R7-17..R7-20) -- kartın iş rolü, onayın doğumu, önerinin onaysız hâli, önbelleğin sınırı.

``test_readme_run6``ın Run 7 karşılığı: dokümanda yazılı olmayan bir bayrak ya da düğme kullanıcının
elinde yok sayılır, o yüzden her işaret ayrı bir parametrik testte README.md'de aranıyor. Bölüm ayrıca
üçüncü taraf bir ürün ya da şirket adı taşıyamaz: ölçüm kutusu kullanıcının kendi verisini anlatır, bir
satıcınınkini değil. Burada hiçbir komut koşulmaz; yalnız metin denetlenir.
"""

import re

import pytest

from readme_text import readme_text

HEADING = "## Konuşma: ardışık sorular"

# README'de birebir geçmesi gereken işaretler (R7 konuşma yüzeyi, CLI, eval, elle gerçek küme koşumu).
README_MARKS = (
    "`CONV_TURNS` (3)",
    "## Önceki turlar",
    "#context-line",
    "Önceki cevaptan",
    "context_dropped",
    "#/c/<id>",
    "Yeni konuşma",
    "#conversation-list",
    "Konuşma bulunamadı.",
    "--new",
    "--conversation <id>",
    "Konuşma: <id> · tur <n>",
    "eval --followups",
    "turn_accuracy",
    "chain_accuracy",
    "context_accuracy",
    "Ardışık sorular",
    "NL2SQL_BACKEND=mssql",
    "wwi_real",
    "`CONV_KEEP_ROWS` (5)",
    "data/bilgin.db",
)

# Bölümde adı geçmemesi gereken üçüncü taraf ürün/şirket adları: örnek veritabanının satıcısı ve o
# verinin içinde dolaşan hayali şirketler — bir kanıt satırı örneği en kolay buradan sızıyor.
# ASSUMPTION: Run 6 testinde yasak ad listesi yok (orada yalnız NL2SQL_DEV_ADMIN_PASSWORD= sonrası
# denetleniyor), o yüzden liste burada; Run 7 bölümünün denetimi de kendi dosyasında durur.
FORBIDDEN_NAMES = ("Microsoft", "WideWorldImporters", "Wide World", "Tailspin", "Wingtip")


def _readme() -> str:
    return readme_text()


def _section() -> str:
    """Konuşma bölümü: kendi başlığından bir sonraki başlığa (ya da dosyanın sonuna) kadar."""
    lines = _readme().splitlines()
    if HEADING not in lines:
        pytest.fail(f"{HEADING} README'de yok")
    start = lines.index(HEADING)
    end = next(
        (i for i, line in enumerate(lines[start + 1:], start + 1) if re.match(r"#\s\S", line)),
        len(lines),
    )
    return "\n".join(lines[start:end])


def test_the_readme_has_the_conversation_heading():
    assert HEADING in _readme().splitlines(), f"{HEADING} README'de başlık olarak yok"


@pytest.mark.parametrize("mark", README_MARKS)
def test_the_readme_documents_every_run7_mark(mark):
    assert mark in _section(), f"{mark} Run 7 konuşma bölümünde yok"


@pytest.mark.parametrize("name", FORBIDDEN_NAMES)
def test_the_section_names_no_third_party_product_or_company(name):
    assert name.lower() not in _section().lower(), f"{name} Run 7 konuşma bölümünde geçiyor"


# Run 7'nin öteki yüzü: başlangıç ekranı ve hazır sorular (R7-17..R7-20). Aynı denetim, kendi
# başlığının altında -- kartın rolü, onayın doğumu, önerinin onaysız hâli, önbelleğin sınırı.
START_HEADING = "## Başlangıç ekranı ve hazır sorular"

START_MARKS = (
    "İş rolü",
    "`BUSINESS_ROLES` (5)",
    "`POST /api/users`",
    "404",
    "Cevaptan onay",
    "Hazır soru yap",
    "`#/hazir-sorular`",
    "Onay bekliyor",
    "Kişisel kart",
    "Panoma ekle",
    "`PERSONAL_CARDS` (6)",
    "`Öneri iste`",
    "onaysız",
    "`START_CACHE_S` (300)",
    "`CARD_REFRESH_MIN_S` (30)",
    "429",
    "`ready_questions.json`",
    "wwi_real",
)


def _start_section() -> str:
    """Başlangıç ekranı bölümü: kendi başlığından bir sonraki başlığa (ya da dosyanın sonuna) kadar."""
    lines = _readme().splitlines()
    if START_HEADING not in lines:
        pytest.fail(f"{START_HEADING} README'de yok")
    start = lines.index(START_HEADING)
    end = next(
        (i for i, line in enumerate(lines[start + 1:], start + 1) if re.match(r"#\s\S", line)),
        len(lines),
    )
    return "\n".join(lines[start:end])


def test_the_readme_has_the_start_screen_heading():
    assert START_HEADING in _readme().splitlines(), f"{START_HEADING} README'de başlık olarak yok"


@pytest.mark.parametrize("mark", START_MARKS)
def test_the_readme_documents_every_start_screen_mark(mark):
    assert mark in _start_section(), f"{mark} başlangıç ekranı bölümünde yok"


@pytest.mark.parametrize("name", FORBIDDEN_NAMES)
def test_the_start_section_names_no_third_party_product_or_company(name):
    assert name.lower() not in _start_section().lower(), f"{name} başlangıç ekranı bölümünde geçiyor"


# Run 7'nin üçüncü yüzü: veritabanı bağlantıları (R7-22..R7-27). Aynı denetim, kendi başlığının
# altında -- kümenin kendi yolu, DPAPI'nin neyi koruduğu, ortam değişkeninin önceliği, bekçinin
# reddi ve durum noktasının kimin ne okuduğu.
CONN_HEADING = "## Veritabanı bağlantıları"

CONN_MARKS = (
    "`data/bilgin.db`",
    "`#/baglantilar`",
    "**Son başarılı**",
    "**Son hata**",
    "`değiştirmek için yazın`",
    "**DPAPI**",
    "extra entropy",
    "`has_secret`",
    "`connections.scrub`",
    "`NL2SQL_MSSQL_CONN_<DATASET>`",
    "`NL2SQL_MSSQL_CONN`",
    "`Ortam değişkeninden`",
    "`Bu bağlantı ortam değişkeninden geliyor; ekrandan değiştirilemez.`",
    "`Bağlantıyı test et`",
    "`sysadmin`",
    "`db_owner`",
    "409",
    "**no row is written**",
    "`Salt okunur giriş betiğini indir`",
    "`login-script.sql`",
    "`DB_CHECK_S` (60)",
    "`#db-dot`",
    "`#db-banner`",
    "`Veritabanına bağlanılamıyor, yöneticinize haber verin.`",
    "`message_admin`",
    "`db_down`",
)


def _conn_section() -> str:
    """Bağlantılar bölümü: kendi başlığından bir sonraki başlığa (ya da dosyanın sonuna) kadar."""
    lines = _readme().splitlines()
    if CONN_HEADING not in lines:
        pytest.fail(f"{CONN_HEADING} README'de yok")
    start = lines.index(CONN_HEADING)
    end = next(
        (i for i, line in enumerate(lines[start + 1:], start + 1) if re.match(r"#\s\S", line)),
        len(lines),
    )
    return "\n".join(lines[start:end])


def test_the_readme_has_the_connections_heading():
    assert CONN_HEADING in _readme().splitlines(), f"{CONN_HEADING} README'de başlık olarak yok"


@pytest.mark.parametrize("mark", CONN_MARKS)
def test_the_readme_documents_every_connections_mark(mark):
    assert mark in _conn_section(), f"{mark} bağlantılar bölümünde yok"


@pytest.mark.parametrize("name", FORBIDDEN_NAMES)
def test_the_connections_section_names_no_third_party_product_or_company(name):
    assert name.lower() not in _conn_section().lower(), f"{name} bağlantılar bölümünde geçiyor"
