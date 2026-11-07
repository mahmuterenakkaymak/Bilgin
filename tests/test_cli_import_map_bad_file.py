# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""T110: import-map çöp bir dosyayla karşılaşınca iz dökmez (Delight 3, T84'ün sözü).

openpyxl yalnızca desteklediği uzantıdaki kitabı açar: düz metin ya da eski .xls arşive
bakılmadan ``InvalidFileException`` ile reddedilir, yani ``read_workbook``un yakaladıklarının
dışında kalırdı. Cümle kullanıcının düzeltebileceği şeyi söylüyor — hangi dosyanın olduğu ve
hangi biçimin desteklenmediği — ve bundan fazlası çıkmıyor.
"""

from nl2sql.cli import main as cli


def not_a_book(tmp_path, name):
    path = tmp_path / name
    path.write_text("TABLO;KOLON\nTBLA;KOD\n", encoding="utf-8")
    return path


def no_model(preview):
    raise AssertionError("okunamayan dosyada model aranmaz")


def test_a_plain_text_file_exits_2_naming_the_file(tmp_path, capsys):
    path = not_a_book(tmp_path, "harita.txt")
    assert cli.import_map(path, no_model) == 2

    out = capsys.readouterr().out
    assert "Hata" in out and "harita.txt" in out and "Traceback" not in out


def test_a_legacy_xls_file_exits_2_naming_the_file(tmp_path, capsys):
    path = not_a_book(tmp_path, "harita.xls")
    assert cli.import_map(path, no_model) == 2

    out = capsys.readouterr().out
    assert "Hata" in out and "harita.xls" in out and "Traceback" not in out
