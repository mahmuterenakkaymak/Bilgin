"""Golden soruların doğruları: aynı Dataset'ten saf Python ile hesaplanır, DB'ye dokunmaz.

Ürün kodu bu modülü hiç import etmez; yalnız testler ve eval karşılaştırması kullanır.
Her fonksiyonun sütun sırası eval/golden.jsonl'daki ilgili SQL'in select sırasıyla aynıdır.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator

# Golden SQL'deki sabit (yarı-açık) tarih aralıklarıyla birebir aynı olmalı — PLAN Decision 3.
JUL = ("2026-07-01", "2026-08-01")
AUG = ("2026-08-01", "2026-09-01")
SEP = ("2026-09-01", "2026-10-01")

Dataset = dict[str, list[dict]]


def _in_span(value: str, span: tuple[str, str]) -> bool:
    return span[0] <= value < span[1]


def _add(totals: dict, key: str, value: float) -> None:
    totals[key] = totals.get(key, 0.0) + value


def _hareketler(dataset: Dataset, hturler: tuple[str, ...], span: tuple[str, str] | None = None) -> Iterator[dict]:
    for hareket in dataset["TBLSTHAR"]:
        if hareket["STHAR_HTUR"] in hturler and (span is None or _in_span(hareket["STHAR_TARIH"], span)):
            yield hareket


def _faturalar(dataset: Dataset, ftirsip: int | None = None, span: tuple[str, str] | None = None) -> Iterator[dict]:
    """İptal edilmemiş faturalar; iptal edilenler hiçbir toplama girmez."""
    for fatura in dataset["TBLFATUIRS"]:
        same_type = ftirsip is None or fatura["FTIRSIP"] == ftirsip
        if same_type and fatura["IPTAL"] == "H" and (span is None or _in_span(fatura["TARIH"], span)):
            yield fatura


def _cariler(dataset: Dataset) -> dict[str, dict]:
    return {cari["CARI_KOD"]: cari for cari in dataset["TBLCASABIT"]}


def q01(dataset: Dataset) -> list[tuple]:
    return [
        (cari["CARI_KOD"], cari["CARI_ISIM"])
        for cari in sorted(dataset["TBLCASABIT"], key=lambda cari: cari["CARI_KOD"])
        if cari["IL"] == "ANKARA" and cari["CARI_TIP"] in ("A", "H")
    ]


def q02(dataset: Dataset) -> list[tuple]:
    adlar = {urun["STOK_KODU"]: urun["STOK_ADI"] for urun in dataset["TBLSTSABIT"]}
    miktarlar: dict[str, float] = {}
    for hareket in _hareketler(dataset, ("S",), SEP):
        _add(miktarlar, hareket["STOK_KODU"], hareket["STHAR_GCMIK"])
    ilk_bes = sorted(miktarlar.items(), key=lambda item: (-item[1], item[0]))[:5]
    return [(kod, adlar[kod], miktar) for kod, miktar in ilk_bes]


def q03(dataset: Dataset) -> list[tuple]:
    return [(
        sum(h["STHAR_GCMIK"] * h["STHAR_NF"] for h in _hareketler(dataset, ("S",), AUG)),)
    ]


def q04(dataset: Dataset) -> list[tuple]:
    cariler = _cariler(dataset)
    plasiyerler = {p["PLASIYER_KODU"]: p for p in dataset["TBLPLASIYER"]}
    toplamlar: dict[str, float] = {}
    for fatura in _faturalar(dataset, 1, SEP):
        kod = cariler[fatura["CARI_KODU"]]["PLASIYER_KODU"]
        if kod is not None:
            _add(toplamlar, kod, fatura["GENELTOPLAM"])
    return [(kod, plasiyerler[kod]["AD_SOYAD"], tutar) for kod, tutar in sorted(toplamlar.items())]


def q05(dataset: Dataset) -> list[tuple]:
    net: dict[str, float] = {}
    for hareket in _hareketler(dataset, ("S", "I"), AUG):
        yon = 1 if hareket["STHAR_HTUR"] == "S" else -1
        _add(net, hareket["STOK_KODU"], yon * hareket["STHAR_GCMIK"])
    return sorted(net.items())


def q06(dataset: Dataset) -> list[tuple]:
    satirlilar = {h["FISNO"] for h in dataset["TBLSTHAR"] if h["FISNO"] is not None}
    return [(
        sum(f["GENELTOPLAM"] for f in _faturalar(dataset, None, JUL) if f["FATIRS_NO"] in satirlilar),)
    ]


def q07(dataset: Dataset) -> list[tuple]:
    girisler: dict[str, float] = {}
    for hareket in dataset["TBLSTHAR"]:
        if hareket["STHAR_GCKOD"] == "G":
            _add(girisler, hareket["DEPO_KODU"], hareket["STHAR_GCMIK"])
    return sorted(girisler.items())


def q08(dataset: Dataset) -> list[tuple]:
    cariler = _cariler(dataset)
    toplamlar: dict[str, float] = {}
    for fatura in _faturalar(dataset, 2):
        cari = cariler[fatura["CARI_KODU"]]
        if cari["CARI_TIP"] in ("S", "H"):
            _add(toplamlar, cari["CARI_KOD"], fatura["GENELTOPLAM"])
    return [(kod, cariler[kod]["CARI_ISIM"], tutar) for kod, tutar in sorted(toplamlar.items())]


def q09(dataset: Dataset) -> list[tuple]:
    cariler = _cariler(dataset)
    siparis_carisi = {s["SIPARIS_NO"]: s["CARI_KODU"] for s in dataset["TBLSIPAMAS"]}
    sayilar: dict[str, int] = {}
    for satir in dataset["TBLSIPATRA"]:
        if satir["TESLIM_TARIHI"] is None:
            kod = siparis_carisi[satir["SIPARIS_NO"]]
            sayilar[kod] = sayilar.get(kod, 0) + 1
    return [(kod, cariler[kod]["CARI_ISIM"], adet) for kod, adet in sorted(sayilar.items())]


def q10(dataset: Dataset) -> list[tuple]:
    satis, iade = {}, {}
    for hareket in _hareketler(dataset, ("S", "I")):
        hedef = satis if hareket["STHAR_HTUR"] == "S" else iade
        _add(hedef, hareket["STOK_KODU"], hareket["STHAR_GCMIK"])
    return [
        (kod, iade.get(kod, 0.0) * 100.0 / tutar)
        for kod, tutar in sorted(satis.items())
        if tutar > 0 and iade.get(kod, 0.0) > 0.1 * tutar
    ]


REFERENCES: dict[str, Callable[[Dataset], list[tuple]]] = {
    "Q01": q01,
    "Q02": q02,
    "Q03": q03,
    "Q04": q04,
    "Q05": q05,
    "Q06": q06,
    "Q07": q07,
    "Q08": q08,
    "Q09": q09,
    "Q10": q10,
}
