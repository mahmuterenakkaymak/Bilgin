"""Run 4 README'si: dataset/model yüzeyi ve 27B koşusu dokümanda geçmeli.

``test_smoke_run3``ün Run 4 karşılığı: dokümanda yazılı olmayan bir bayrak kullanıcının elinde yok
sayılır, o yüzden her işaret ayrı bir parametrik testte README.md'de aranıyor. Burada komut koşulmaz
— yalnızca metin denetlenir; ağ ve model yok.
"""

import pytest

from readme_text import readme_text

# README'de birebir geçmesi gereken işaretler (R4-14 ve 27B bölümü).
README_MARKS = (
    "--dataset",
    "wwi",
    "synthetic_erp",
    "--model",
    "config/models.json",
    "UNSLOTH_API_KEY",
    "--context-length 16384",
    "24576",
    "-np 1",
    "eval --compare --models",
    "context_overflow",
    "compare_",
    "ApplicationIntent=ReadOnly",
    "MIT",
)


@pytest.mark.parametrize("mark", README_MARKS)
def test_the_readme_documents_every_run4_mark(mark):
    readme = readme_text()
    assert mark in readme, f"{mark} README'de yok"
