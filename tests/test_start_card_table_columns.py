# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""T369: kart tablosu sorunun ölçtüğü kolonu gösterir (M23 görsel inceleme 4).

Kart ~380px genişliğinde, başlıklar ve hücreler ``nowrap``: son kolon kartın sağına sığıyor ama
ekrana çıkmıyor - "Teslim tarihi belirsiz sipariş satırları" CARI_KOD + CARI_ISIM çiziyor, sayı
kayboluyor. Yükte düzeltilir: tablo kartı her sayısal kolonu ve en dar tek metin kolonunu tutar;
tam tablo kart açılınca zaten görünüyor. ``CARD_TABLE_ROWS`` satır sınırı değişmez.
"""

from bilgin import config
from bilgin.engine.result import Result
from bilgin.start.cards import card_result

SQL = "SELECT CARI_KOD, CARI_ISIM, BELIRSIZ_SATIR FROM V_SIPARIS_SATIR"


class _Executor:
    """Tek sonucu dönen sahte yürütücü: kartın SQL'i koşmaz, ölçülecek şey kartın yüküdür."""

    def __init__(self, columns, rows):
        self._pii_schema = None
        self._result = Result(columns=columns, rows=rows, row_count=len(rows))

    def execute(self, sql, budget=None, source=""):
        return self._result


def _payload(columns, rows):
    card = {
        "id": 1,
        "dataset": "synthetic_erp",
        "business_role": "satis",
        "title": "Kart",
        "question": "Teslim tarihi belirsiz sipariş satırları",
        "sql": SQL,
        "display": "table",
    }
    return card_result(_Executor(columns, rows), card)


def _cari_rows(count):
    return [
        (f"12001068{i:02d}", f"İÇ ANADOLU GIDA VE TARIM ÜRÜNLERİ SANAYİ {i}", i)
        for i in range(count)
    ]


def test_the_measure_the_question_asked_for_stays_on_the_card():
    payload = _payload(["CARI_KOD", "CARI_ISIM", "BELIRSIZ_SATIR"], _cari_rows(12))

    assert "BELIRSIZ_SATIR" in payload["columns"], "ölçü her zaman kartta"
    assert len(payload["columns"]) <= 3
    assert payload["columns"] == ["CARI_KOD", "BELIRSIZ_SATIR"], "en geniş metin kolonu düşer"
    assert payload["rows"] == [
        [f"12001068{i:02d}", i] for i in range(config.CARD_TABLE_ROWS)
    ], "her satır aynı kolon indekslerine kesilir, satır sayısı CARD_TABLE_ROWS ile sınırlı"


def test_a_two_column_card_comes_back_whole():
    payload = _payload(
        ["STOK_ADI", "CIRO"], [("Zeytinyağı 1 L", 257959.42), ("Pirinç 5 kg", 14890.0)]
    )

    assert payload["columns"] == ["STOK_ADI", "CIRO"]
    assert payload["rows"] == [["Zeytinyağı 1 L", 257959.42], ["Pirinç 5 kg", 14890.0]]


def test_a_card_whose_result_is_all_text_keeps_one_text_column():
    adres = [
        ("ANKARA", "ÇANKAYA", "Kızılırmak Mah. 1440. Sokak No 12"),
        ("IZMIR", "KONAK", "Alsancak Mah. No 8"),
    ]
    payload = _payload(["IL", "ILCE", "ADRES"], adres)

    assert payload["columns"] == ["IL"], "en dar tek metin kolonu kalır"
    assert payload["rows"] == [["ANKARA"], ["IZMIR"]]
