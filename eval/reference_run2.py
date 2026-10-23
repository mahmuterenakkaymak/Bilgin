"""Run 2 golden sorularının (Q11-Q20) doğruları: saf Python, DB'ye dokunmaz.

eval/reference.py'nin sonunda REFERENCES'a birleştirilir. Buradaki hiçbir fonksiyon golden SQL'i
okumaz ve eval/reference.py'den bir şey almaz; doğrular sorgudan bağımsız kalsın diye iki dosya
ayrı dünyalardır. Sütun sırası eval/golden.jsonl'daki ilgili SQL'in select sırasıyla aynıdır.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Iterator

Dataset = dict[str, list[dict]]

# Golden SQL'deki sabit (yarı-açık) tarih aralıklarıyla birebir aynı olmalı — PLAN Decision 3.
BU_YIL = ("2026-01-01", "2027-01-01")
GECEN_AY = ("2026-08-01", "2026-09-01")
ARSIV_2025 = ("2025-01-01", "2026-01-01")
LISTE_FIYATI_ESIGI = 100.0  # Q15'in "100 TL'nin üzerinde"si
IADE_ORANI_ESIGI = 0.1  # Q19'un "%10'un üzerinde"si


def _in_span(value: str, span: tuple[str, str] | None) -> bool:
    return span is None or span[0] <= value < span[1]


def _hareketler(
    dataset: Dataset, tablo: str, hturler: tuple[str, ...], span: tuple[str, str] | None = None
) -> Iterator[dict]:
    for hareket in dataset[tablo]:
        if hareket["STHAR_HTUR"] in hturler and _in_span(hareket["STHAR_TARIH"], span):
            yield hareket


def _satis_faturalari(dataset: Dataset, span: tuple[str, str] | None) -> Iterator[dict]:
    """İptal edilmemiş satış faturaları (FTIRSIP=1); brüt satış KDV dahil başlık tutarından gelir."""
    for fatura in dataset["TBLFATUIRS"]:
        if fatura["FTIRSIP"] == 1 and fatura["IPTAL"] == "H" and _in_span(fatura["TARIH"], span):
            yield fatura


def _net_miktar(hareketler) -> float:
    """Satış (S) miktarlarından satış iadesi (I) miktarlarının düşülmüş hali."""
    return sum(h["STHAR_GCMIK"] * (1 if h["STHAR_HTUR"] == "S" else -1) for h in hareketler)


def _ciro(hareketler) -> float:
    return sum(h["STHAR_GCMIK"] * h["STHAR_NF"] for h in hareketler)


def q11(dataset: Dataset) -> list[tuple]:
    return [(_net_miktar(_hareketler(dataset, "TBLSTHAR", ("S", "I"), BU_YIL)),)]


def q12(dataset: Dataset) -> list[tuple]:
    return [(sum(f["GENELTOPLAM"] for f in _satis_faturalari(dataset, GECEN_AY)),)]


def q13(dataset: Dataset) -> list[tuple]:
    adlar = {urun["STOK_KODU"]: urun["STOK_ADI"] for urun in dataset["TBLSTSABIT"]}
    miktarlar: dict[str, float] = defaultdict(float)
    for hareket in _hareketler(dataset, "TBLSTHAR_ARSIV", ("S",)):
        miktarlar[hareket["STOK_KODU"]] += hareket["STHAR_GCMIK"]
    ilk_bes = sorted(miktarlar.items(), key=lambda item: (-item[1], item[0]))[:5]
    return [(kod, adlar[kod], miktar) for kod, miktar in ilk_bes]


def q14(dataset: Dataset) -> list[tuple]:
    """Tüm zamanlar: 2026 hareketleri ile 2025 arşivi tek toplamda birleşir."""
    tum = list(_hareketler(dataset, "TBLSTHAR", ("S",))) + list(_hareketler(dataset, "TBLSTHAR_ARSIV", ("S",)))
    return [(_ciro(tum),)]


def q15(dataset: Dataset) -> list[tuple]:
    """Güncel liste fiyatı: FIYAT_TIPI='S' satırlarının en son geçerlik tarihli olanı."""
    adlar = {urun["STOK_KODU"]: urun["STOK_ADI"] for urun in dataset["TBLSTSABIT"]}
    son_tarih: dict[str, str] = {}
    for fiyat in dataset["TBLSTOKFIAT"]:
        if fiyat["FIYAT_TIPI"] == "S":
            kod = fiyat["STOK_KODU"]
            son_tarih[kod] = max(son_tarih.get(kod, ""), fiyat["GECERLILIK_TARIHI"])
    return [
        (satir["STOK_KODU"], adlar[satir["STOK_KODU"]], satir["FIYAT"])
        for satir in dataset["TBLSTOKFIAT"]
        if satir["FIYAT_TIPI"] == "S"
        and satir["GECERLILIK_TARIHI"] == son_tarih[satir["STOK_KODU"]]
        and satir["FIYAT"] > LISTE_FIYATI_ESIGI
    ]


def q16(dataset: Dataset) -> list[tuple]:
    return [
        (
            sum(f["GENELTOPLAM"] for f in _satis_faturalari(dataset, BU_YIL)),
            _ciro(_hareketler(dataset, "TBLSTHAR", ("S",), BU_YIL)),
        )
    ]


def q17(dataset: Dataset) -> list[tuple]:
    grubu = {urun["STOK_KODU"]: urun["GRUP_KODU"] for urun in dataset["TBLSTSABIT"]}
    adlar = {grup["GRUP_KODU"]: grup["GRUP_ISIMI"] for grup in dataset["TBLSTGRUP"]}
    net: dict[str, float] = defaultdict(float)
    for hareket in _hareketler(dataset, "TBLSTHAR", ("S", "I"), BU_YIL):
        yon = 1 if hareket["STHAR_HTUR"] == "S" else -1
        net[grubu[hareket["STOK_KODU"]]] += hareket["STHAR_GCMIK"] * yon
    return [(kod, adlar[kod], miktar) for kod, miktar in sorted(net.items())]


def q18(dataset: Dataset) -> list[tuple]:
    cariler = {cari["CARI_KOD"]: cari for cari in dataset["TBLCASABIT"]}
    tutarlar: dict[str, float] = defaultdict(float)
    for hareket in _hareketler(dataset, "TBLSTHAR_ARSIV", ("S",), ARSIV_2025):
        cari = cariler[hareket["CARI_KODU"]]
        if cari["CARI_TIP"] in ("A", "H"):
            tutarlar[cari["CARI_KOD"]] += hareket["STHAR_GCMIK"] * hareket["STHAR_NF"]
    return [(kod, cariler[kod]["CARI_ISIM"], tutar) for kod, tutar in sorted(tutarlar.items())]


def q19(dataset: Dataset) -> list[tuple]:
    satis: dict[str, float] = defaultdict(float)
    iade: dict[str, float] = defaultdict(float)
    for hareket in _hareketler(dataset, "TBLSTHAR_ARSIV", ("S", "I"), ARSIV_2025):
        hedef = satis if hareket["STHAR_HTUR"] == "S" else iade
        hedef[hareket["STOK_KODU"]] += hareket["STHAR_GCMIK"]
    return [
        (kod, iade.get(kod, 0.0) * 100.0 / tutar)
        for kod, tutar in sorted(satis.items())
        if tutar > 0 and iade.get(kod, 0.0) > IADE_ORANI_ESIGI * tutar
    ]


def q20(dataset: Dataset) -> list[tuple]:
    """Kampanya aralığı günleri içerir (BASLANGIC ve BITIS dahil), o yüzden yarı-açık değil."""
    adlar = {kampanya["KAMPANYA_KODU"]: kampanya["KAMPANYA_ADI"] for kampanya in dataset["TBLKAMPANYA"]}
    satislar = list(_hareketler(dataset, "TBLSTHAR", ("S",)))
    tutarlar: dict[str, float] = defaultdict(float)
    for kampanya in dataset["TBLKAMPANYA"]:
        bas, bitis = kampanya["BASLANGIC"], kampanya["BITIS"]
        for hareket in satislar:
            if hareket["STOK_KODU"] == kampanya["STOK_KODU"] and bas <= hareket["STHAR_TARIH"] <= bitis:
                tutarlar[kampanya["KAMPANYA_KODU"]] += hareket["STHAR_GCMIK"] * hareket["STHAR_NF"]
    return [(kod, adlar[kod], tutar) for kod, tutar in sorted(tutarlar.items())]


REFERENCES: dict[str, Callable[[Dataset], list[tuple]]] = {
    "Q11": q11,
    "Q12": q12,
    "Q13": q13,
    "Q14": q14,
    "Q15": q15,
    "Q16": q16,
    "Q17": q17,
    "Q18": q18,
    "Q19": q19,
    "Q20": q20,
}
