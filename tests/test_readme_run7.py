"""Run 7 README'si: konuşma — ardışık sorular, kanıt satırı, CLI bayrakları ve `eval --followups`.

``test_readme_run6``ın Run 7 karşılığı: dokümanda yazılı olmayan bir bayrak ya da düğme kullanıcının
elinde yok sayılır, o yüzden her işaret ayrı bir parametrik testte README.md'de aranıyor. Bölüm ayrıca
üçüncü taraf bir ürün ya da şirket adı taşıyamaz: ölçüm kutusu kullanıcının kendi verisini anlatır, bir
satıcınınkini değil. Burada hiçbir komut koşulmaz; yalnız metin denetlenir.
"""

import re

import pytest

from nl2sql import config

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
    return (config.ROOT / "README.md").read_text(encoding="utf-8")


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
