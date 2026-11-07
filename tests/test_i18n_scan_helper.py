# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""T393: kullanıcıya hâlâ Türkçe konuşan sabitlerin taranması (PLAN R8-4).

Geçiş testleri kendi modüllerine "kullanıcıya dönük bir şey kaldı mı?" diye sorar. Türkçe harf yazan
her string sabiti bildirilir; üç biçim muaftır: docstring (okuyucuya, kullanıcıya değil), logging
çağrısının argümanı (kayıta) ve allow verilen modül düzeyi sabit (modele dönük prompt, eşleştirme
tablosu). f-string'in düz parçaları da birer sabittir, bir sözlüğün değeri de bir değerdir - ikisi de
yakalanır; muafiyet metne değil çağrının biçimine bağlı, o yüzden aynı cümle `show(...)` içinde gelir.
Satır numarası sabitin kendi satırıdır ki geçiş testi "şu satırı kataloğa taşı" diyebilsin.
"""

from textwrap import dedent

from nl2sql.i18n.scan import user_literals


def scan(tmp_path, source, allow=()):
    path = tmp_path / "ornek.py"
    path.write_text(dedent(source), encoding="utf-8")
    return user_literals(path, allow=allow)


def test_docstring_skipped(tmp_path):
    hits = scan(tmp_path, '''
        """Modül belgesi: Satır bulunamadı."""


        class Rapor:
            """Sınıf belgesi: Müşteri sayısı."""

            def sor(self):
                """Fonksiyon belgesi: Kayıt yok."""
                return "Kayıt yok"
        ''')
    assert hits == [(10, "Kayıt yok")]


def test_log_call_skipped(tmp_path):
    hits = scan(tmp_path, '''
        import logging
        import logging as _log
        from logging import getLogger

        logger = getLogger(__name__)
        log = logger

        logging.info("Kayıt bulunamadı")
        logger.warning(f"{ad} için kayıt yok")
        log.debug("Satır yok")
        _log.error("Bağlantı koptu")
        show("Kayıt bulunamadı")
        ''')
    assert [text for _, text in hits] == ["Kayıt bulunamadı"]


def test_allowed_constant_skipped(tmp_path):
    source = '''
        SYSTEM = "Sen bir SQL asistanısın"
        CHART_WISHES = {"çubuk": "çubuk grafik"}
        HATA = "Cümleyi yeniden kur"
        '''
    assert scan(tmp_path, source, allow=("SYSTEM", "CHART_WISHES")) == [(4, "Cümleyi yeniden kur")]
    assert scan(tmp_path, source, allow=("narrate.SYSTEM", "CHART_WISHES")) == [
        (4, "Cümleyi yeniden kur")
    ]
    assert [text for _, text in scan(tmp_path, source)] == [
        "Sen bir SQL asistanısın",
        "çubuk",
        "çubuk grafik",
        "Cümleyi yeniden kur",
    ]


def test_allow_covers_module_level_only(tmp_path):
    hits = scan(tmp_path, '''
        def build():
            SYSTEM = "Sen bir SQL asistanısın"
            return SYSTEM
        ''', allow=("SYSTEM",))
    assert [text for _, text in hits] == ["Sen bir SQL asistanısın"]


def test_fstring_part_caught(tmp_path):
    hits = scan(tmp_path, '''
        def ozet(adet):
            return f"{adet} müşteri bulunamadı"
        ''')
    assert hits == [(3, " müşteri bulunamadı")]


def test_dict_value_caught(tmp_path):
    hits = scan(tmp_path, '''
        ERRORS = {
            "blank": "Lütfen soruyu yeniden yaz",
            "fail": "Sorgu çalışmadı",
        }
        ''')
    assert [text for _, text in hits] == ["Lütfen soruyu yeniden yaz", "Sorgu çalışmadı"]


def test_plain_english_ignored(tmp_path):
    assert scan(tmp_path, '''
        MESSAGE = "No rows found for this query"
        raise ValueError("Connection string is missing")
        label = f"{count} rows returned"
        ''') == []


def test_line_numbers(tmp_path):
    hits = scan(tmp_path, '''
        a = "Tutar geçersiz"
        b = "Total amount"
        c = f"{adet} adet kaldı"
        d = {"h": "Satır bulunamadı"}
        ''')
    assert hits == [(2, "Tutar geçersiz"), (4, " adet kaldı"), (5, "Satır bulunamadı")]
