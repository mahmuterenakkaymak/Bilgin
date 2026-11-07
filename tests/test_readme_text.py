# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""``readme_text`` (R8-14): iki README alt alta, olmayan dosya metne girmeden.

İşaret denetimleri bu yardımcıya geçtikçe birliğin kendisi burada ölçülür: README.md önde ve
eksiksiz durur, README.tr.md bir satır boşluksuz altına gelir, tr dosyası yokken metin tek dosyadır.
Kök ``config.ROOT`` çağrı anında okunduğu için dünya tmp'de kurulur; depodaki README'lere dokunulmaz.
"""

from bilgin import config
from readme_text import readme_text

TR = "Satır sayısı beş."
EN = "Row count is five."


def test_both_files_are_read_one_after_the_other(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "ROOT", tmp_path)
    (tmp_path / "README.md").write_text(EN, encoding="utf-8")
    (tmp_path / "README.tr.md").write_text(TR, encoding="utf-8")

    assert readme_text() == f"{EN}\n{TR}"


def test_the_turkish_file_is_optional(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "ROOT", tmp_path)
    (tmp_path / "README.md").write_text(EN, encoding="utf-8")

    assert readme_text() == EN
