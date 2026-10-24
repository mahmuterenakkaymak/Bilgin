"""Run 5 README'si: web arayüzü, dışa aktarım, netleştirme ve yeni eval metrikleri dokümanda geçmeli.

``test_readme_run4``ün Run 5 karşılığı: dokümanda yazılı olmayan bir bayrak kullanıcının elinde yok
sayılır, o yüzden her işaret ayrı bir parametrik testte README.md'de aranıyor. Burada komut koşulmaz
— yalnızca metin denetlenir; ağ ve model yok.
"""

import pytest

from nl2sql import config

# README'de birebir geçmesi gereken işaretler (R5 web yüzeyi, dışa aktarım, netleştirme, eval).
README_MARKS = (
    "serve",
    "--llm fake",
    "127.0.0.1",
    "npm --prefix web run build",
    "ask --json",
    "--choice",
    "--ambiguous",
    "--narrate",
    "--summaries",
    "data/bilgin.db",
    "logs/asks.jsonl",
    "rules.json",
    "eval/SUMMARIES.md",
)


@pytest.mark.parametrize("mark", README_MARKS)
def test_the_readme_documents_every_run5_mark(mark):
    readme = (config.ROOT / "README.md").read_text(encoding="utf-8")
    assert mark in readme, f"{mark} README'de yok"
