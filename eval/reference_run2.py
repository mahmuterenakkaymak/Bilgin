# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""Run 2 golden sorularının (Q11-Q40) doğruları: saf Python, DB'ye dokunmaz.

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
EYLUL = ("2026-09-01", "2026-10-01")
ARSIV_2025 = ("2025-01-01", "2026-01-01")
LISTE_FIYATI_ESIGI = 100.0  # Q15'in "100 TL'nin üzerinde"si
IADE_ORANI_ESIGI = 0.1  # Q19'un "%10'un üzerinde"si

# Q31-Q40 kayıtlı değere süzen sorular: yazımlar golden SQL'deki metinlerle birebir aynı olmalı.
GRUP_KURUYEMIS = "Kuruyemiş"
GRUP_GIDA = "Gıda"
KAMPANYA_ADI = "Kış Kampanyası"
DEPO_ADLARI = ("Merkez Depo", "Ege Bölge Deposu")
DEPO_AVRUPA = "Avrupa Yakası Deposu"
SUBE_ILCE = "Çankaya"
SUBE_ILI = "İZMİR"
DOVIZ_EUR = "EUR"
HESAP_SATIS_GELIRI = "600"


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


def _cariler(dataset: Dataset) -> dict[str, dict]:
    return {cari["CARI_KOD"]: cari for cari in dataset["TBLCASABIT"]}


def _alici(cari: dict) -> bool:
    """CARI_TIP='H' hem alıcı hem satıcıdır; tek başına 'A' aramak onu kaçırır."""
    return cari["CARI_TIP"] in ("A", "H")


def _plasiyer_adlari(dataset: Dataset) -> dict[str, str]:
    return {plasiyer["PLASIYER_KODU"]: plasiyer["AD_SOYAD"] for plasiyer in dataset["TBLPLASIYER"]}


def _kampanyalar(dataset: Dataset) -> list[dict]:
    return sorted(dataset["TBLKAMPANYA"], key=lambda kampanya: kampanya["KAMPANYA_KODU"])


def q21(dataset: Dataset) -> list[tuple]:
    subeliler = {sube["CARI_KOD"] for sube in dataset["TBLCARISUBE"]}
    adlar = _plasiyer_adlari(dataset)
    caris: dict[str, set[str]] = defaultdict(set)
    for cari in dataset["TBLCASABIT"]:
        if cari["PLASIYER_KODU"] and cari["CARI_KOD"] in subeliler and _alici(cari):
            caris[cari["PLASIYER_KODU"]].add(cari["CARI_KOD"])
    return [(kod, adlar[kod], len(kodlar)) for kod, kodlar in sorted(caris.items())]


def q22(dataset: Dataset) -> list[tuple]:
    """İl cari kartınındır; şubelerin IL alanı ondan farklı olabilir."""
    cariler = _cariler(dataset)
    iller: dict[str, tuple[float, int]] = {}
    for fatura in _satis_faturalari(dataset, EYLUL):
        il = cariler[fatura["CARI_KODU"]]["IL"]
        tutar, adet = iller.get(il, (0.0, 0))
        iller[il] = (tutar + fatura["GENELTOPLAM"], adet + 1)
    return [(il, tutar, adet) for il, (tutar, adet) in sorted(iller.items())]


def q23(dataset: Dataset) -> list[tuple]:
    grubu = {urun["STOK_KODU"]: urun["GRUP_KODU"] for urun in dataset["TBLSTSABIT"]}
    adlar = {grup["GRUP_KODU"]: grup["GRUP_ISIMI"] for grup in dataset["TBLSTGRUP"]}
    bekleyen: dict[str, tuple[int, float]] = {}
    for satir in dataset["TBLSIPATRA"]:
        if satir["TESLIM_TARIHI"] is not None:
            continue
        kod = grubu[satir["STOK_KODU"]]
        adet, tutar = bekleyen.get(kod, (0, 0.0))
        bekleyen[kod] = (adet + 1, tutar + satir["TUTAR"])
    return [(kod, adlar[kod], adet, tutar) for kod, (adet, tutar) in sorted(bekleyen.items())]


def q24(dataset: Dataset) -> list[tuple]:
    """Kampanya burada bir ürün kümesi: sipariş satırları kampanya tarih aralığına göre süzülmüyor."""
    satirlar: dict[str, list[dict]] = defaultdict(list)
    for satir in dataset["TBLSIPATRA"]:
        satirlar[satir["STOK_KODU"]].append(satir)
    sonuc = []
    for kampanya in _kampanyalar(dataset):
        urun_satirlari = satirlar.get(kampanya["STOK_KODU"], [])
        if urun_satirlari:
            sonuc.append((
                kampanya["KAMPANYA_KODU"],
                kampanya["KAMPANYA_ADI"],
                sum(satir["MIKTAR"] for satir in urun_satirlari),
                sum(satir["TUTAR"] for satir in urun_satirlari),
            ))
    return sonuc


def q25(dataset: Dataset) -> list[tuple]:
    """Kampanya aralığı günleri içerir (yarı-açık değil); dönemi boş kalan kampanya satır üretmez."""
    satislar = list(_hareketler(dataset, "TBLSTHAR", ("S",)))
    sonuc = []
    for kampanya in _kampanyalar(dataset):
        donem = [
            hareket
            for hareket in satislar
            if hareket["STOK_KODU"] == kampanya["STOK_KODU"]
            and kampanya["BASLANGIC"] <= hareket["STHAR_TARIH"] <= kampanya["BITIS"]
        ]
        if donem:
            sonuc.append((
                kampanya["KAMPANYA_KODU"],
                kampanya["KAMPANYA_ADI"],
                sum(hareket["STHAR_GCMIK"] for hareket in donem),
                len({hareket["CARI_KODU"] for hareket in donem}),
            ))
    return sonuc


def q26(dataset: Dataset) -> list[tuple]:
    """Kur faturanın kendi tarihindeki USD satırıdır; TL tutar dövize kura bölünerek çıkar."""
    cariler = _cariler(dataset)
    adlar = _plasiyer_adlari(dataset)
    kur = {
        satir["KUR_TARIH"]: satir["SATIS"]
        for satir in dataset["TBLDOVKUR"]
        if satir["DOVIZ_KODU"] == "USD"
    }
    tutarlar: dict[str, float] = defaultdict(float)
    for fatura in _satis_faturalari(dataset, GECEN_AY):
        kod = cariler[fatura["CARI_KODU"]]["PLASIYER_KODU"]
        if kod and fatura["TARIH"] in kur:
            tutarlar[kod] += fatura["GENELTOPLAM"] / kur[fatura["TARIH"]]
    return [(kod, adlar[kod], tutar) for kod, tutar in sorted(tutarlar.items())]


def q27(dataset: Dataset) -> list[tuple]:
    adlar = {depo["DEPO_KODU"]: depo["DEPO_ISIMI"] for depo in dataset["TBLDEPO"]}
    ciro: dict[str, float] = defaultdict(float)
    urunler: dict[str, set[str]] = defaultdict(set)
    for hareket in _hareketler(dataset, "TBLSTHAR", ("S",), EYLUL):
        kod = hareket["DEPO_KODU"]
        ciro[kod] += hareket["STHAR_GCMIK"] * hareket["STHAR_NF"]
        urunler[kod].add(hareket["STOK_KODU"])
    ilk_uc = sorted(ciro, key=lambda kod: (-ciro[kod], kod))[:3]
    return [(kod, adlar[kod], ciro[kod], len(urunler[kod])) for kod in ilk_uc]


def q28(dataset: Dataset) -> list[tuple]:
    """BA yönü borcu alacaktan ayırır; tek toplama almak bakiyeyi verirdi."""
    cariler = _cariler(dataset)
    adlar = _plasiyer_adlari(dataset)
    toplamlar: dict[str, list[float]] = defaultdict(lambda: [0.0, 0.0])
    for hareket in dataset["TBLCAHAR"]:
        kod = cariler[hareket["CARI_KODU"]]["PLASIYER_KODU"]
        if kod and _in_span(hareket["TARIH"], BU_YIL):
            toplamlar[kod][0 if hareket["BA"] == "B" else 1] += hareket["TUTAR"]
    return [(kod, adlar[kod], borc, alacak) for kod, (borc, alacak) in sorted(toplamlar.items())]


def q29(dataset: Dataset) -> list[tuple]:
    """EXISTS'in karşılığı: şubenin varlığı ölçülüyor, sayısı değil; hareketler şube başına tekrarlanmıyor."""
    cariler = _cariler(dataset)
    kosul = {
        cari["CARI_KOD"]
        for cari in dataset["TBLCASABIT"]
        if _alici(cari)
        and any(sube["CARI_KOD"] == cari["CARI_KOD"] and sube["IL"] != cari["IL"] for sube in dataset["TBLCARISUBE"])
    }
    tutarlar: dict[str, float] = defaultdict(float)
    for hareket in _hareketler(dataset, "TBLSTHAR", ("S",), BU_YIL):
        if hareket["CARI_KODU"] in kosul:
            tutarlar[hareket["CARI_KODU"]] += hareket["STHAR_GCMIK"] * hareket["STHAR_NF"]
    return [(kod, cariler[kod]["CARI_ISIM"], tutar) for kod, tutar in sorted(tutarlar.items())]


def q30(dataset: Dataset) -> list[tuple]:
    grubu = {urun["STOK_KODU"]: urun["GRUP_KODU"] for urun in dataset["TBLSTSABIT"]}
    adlar = {grup["GRUP_KODU"]: grup["GRUP_ISIMI"] for grup in dataset["TBLSTGRUP"]}
    ciro: dict[str, float] = defaultdict(float)
    urunler: dict[str, set[str]] = defaultdict(set)
    for hareket in _hareketler(dataset, "TBLSTHAR", ("S",), BU_YIL):
        kod = grubu[hareket["STOK_KODU"]]
        ciro[kod] += hareket["STHAR_GCMIK"] * hareket["STHAR_NF"]
        urunler[kod].add(hareket["STOK_KODU"])
    return [(kod, adlar[kod], ciro[kod], len(urunler[kod])) for kod in sorted(ciro)]


def q31(dataset: Dataset) -> list[tuple]:
    """Grup adı bir metindir: 'Kuruyemiş' yazımı TBLSTGRUP.GRUP_ISIMI'nden gelir, kod tahmin edilmez."""
    adlar = {grup["GRUP_KODU"]: grup["GRUP_ISIMI"] for grup in dataset["TBLSTGRUP"]}
    grubu = {urun["STOK_KODU"]: urun["GRUP_KODU"] for urun in dataset["TBLSTSABIT"]}
    ciro: dict[str, float] = defaultdict(float)
    urunler: dict[str, set[str]] = defaultdict(set)
    for hareket in _hareketler(dataset, "TBLSTHAR", ("S",), BU_YIL):
        kod = grubu[hareket["STOK_KODU"]]
        if adlar[kod] != GRUP_KURUYEMIS:
            continue
        ciro[kod] += hareket["STHAR_GCMIK"] * hareket["STHAR_NF"]
        urunler[kod].add(hareket["STOK_KODU"])
    return [(kod, adlar[kod], ciro[kod], len(urunler[kod])) for kod in sorted(ciro)]


def q32(dataset: Dataset) -> list[tuple]:
    """Kampanya adı benzersiz değil: kırılım KAMPANYA_KODU iledir, adın kendisi ise bilinen bir süzme değeri."""
    satislar = list(_hareketler(dataset, "TBLSTHAR", ("S",)))
    sonuc = []
    for kampanya in _kampanyalar(dataset):
        if kampanya["KAMPANYA_ADI"] != KAMPANYA_ADI:
            continue
        donem = [
            hareket
            for hareket in satislar
            if hareket["STOK_KODU"] == kampanya["STOK_KODU"]
            and kampanya["BASLANGIC"] <= hareket["STHAR_TARIH"] <= kampanya["BITIS"]
        ]
        if donem:
            sonuc.append((kampanya["KAMPANYA_KODU"], kampanya["KAMPANYA_ADI"], _ciro(donem)))
    return sonuc


def q33(dataset: Dataset) -> list[tuple]:
    """Hareketin kendi sütununda yalnız depo kodu var; depo adları TBLDEPO'dan süzülür."""
    adlar = {depo["DEPO_KODU"]: depo["DEPO_ISIMI"] for depo in dataset["TBLDEPO"]}
    ciro: dict[str, float] = defaultdict(float)
    adet: dict[str, int] = defaultdict(int)
    for hareket in _hareketler(dataset, "TBLSTHAR", ("S",), BU_YIL):
        kod = hareket["DEPO_KODU"]
        if adlar[kod] not in DEPO_ADLARI:
            continue
        ciro[kod] += hareket["STHAR_GCMIK"] * hareket["STHAR_NF"]
        adet[kod] += 1
    return [(kod, adlar[kod], ciro[kod], adet[kod]) for kod in sorted(ciro)]


def q34(dataset: Dataset) -> list[tuple]:
    """ILCE NULL olabilir; eşitlik koşulu o şubeleri kendiliğinden eler, ayrıca IS NOT NULL gerekmez."""
    cariler = _cariler(dataset)
    sayilar: dict[str, int] = defaultdict(int)
    for sube in dataset["TBLCARISUBE"]:
        cari = cariler[sube["CARI_KOD"]]
        if sube["ILCE"] != SUBE_ILCE or not _alici(cari):
            continue
        sayilar[cari["CARI_KOD"]] += 1
    return [(kod, cariler[kod]["CARI_ISIM"], adet) for kod, adet in sorted(sayilar.items())]


def q35(dataset: Dataset) -> list[tuple]:
    """EXISTS'in karşılığı: şubenin varlığı ölçülüyor, faturalar şube başına tekrarlanmıyor."""
    cariler = _cariler(dataset)
    kosul = {sube["CARI_KOD"] for sube in dataset["TBLCARISUBE"] if sube["IL"] == SUBE_ILI}
    toplamlar: dict[str, list] = defaultdict(lambda: [0.0, 0])
    for fatura in _satis_faturalari(dataset, EYLUL):
        cari = cariler[fatura["CARI_KODU"]]
        if _alici(cari) and cari["CARI_KOD"] in kosul:
            toplamlar[cari["CARI_KOD"]][0] += fatura["GENELTOPLAM"]
            toplamlar[cari["CARI_KOD"]][1] += 1
    return [
        (kod, cariler[kod]["CARI_ISIM"], tutar, adet)
        for kod, (tutar, adet) in sorted(toplamlar.items())
    ]


def q36(dataset: Dataset) -> list[tuple]:
    """Kur faturanın kendi tarihindeki EUR satırıdır; TL tutar Euro'ya kura bölünerek geçer."""
    kur = {
        satir["KUR_TARIH"]: satir["SATIS"]
        for satir in dataset["TBLDOVKUR"]
        if satir["DOVIZ_KODU"] == DOVIZ_EUR
    }
    return [
        (
            sum(
                fatura["GENELTOPLAM"] / kur[fatura["TARIH"]]
                for fatura in _satis_faturalari(dataset, EYLUL)
                if fatura["TARIH"] in kur
            ),
        )
    ]


def q37(dataset: Dataset) -> list[tuple]:
    """2025 arşivi ayrı tabloda durur; depo adı yine TBLDEPO.DEPO_ISIMI'nden süzülür."""
    adlar = {depo["DEPO_KODU"]: depo["DEPO_ISIMI"] for depo in dataset["TBLDEPO"]}
    ciro: dict[str, float] = defaultdict(float)
    urunler: dict[str, set[str]] = defaultdict(set)
    for hareket in _hareketler(dataset, "TBLSTHAR_ARSIV", ("S",)):
        kod = hareket["DEPO_KODU"]
        if adlar[kod] != DEPO_AVRUPA:
            continue
        ciro[kod] += hareket["STHAR_GCMIK"] * hareket["STHAR_NF"]
        urunler[kod].add(hareket["STOK_KODU"])
    return [(kod, adlar[kod], ciro[kod], len(urunler[kod])) for kod in sorted(ciro)]


def q38(dataset: Dataset) -> list[tuple]:
    """Filtre ürün grubunun adı; cari ünvanlarındaki 'Gıda' sözcüğü aynı şey değildir."""
    adlar = {grup["GRUP_KODU"]: grup["GRUP_ISIMI"] for grup in dataset["TBLSTGRUP"]}
    grubu = {urun["STOK_KODU"]: urun["GRUP_KODU"] for urun in dataset["TBLSTSABIT"]}
    bekleyen = [
        satir
        for satir in dataset["TBLSIPATRA"]
        if satir["TESLIM_TARIHI"] is None and adlar[grubu[satir["STOK_KODU"]]] == GRUP_GIDA
    ]
    return [(len(bekleyen), sum(satir["TUTAR"] for satir in bekleyen))]


def q39(dataset: Dataset) -> list[tuple]:
    """İki sayı iki kaynaktan: fatura başlığı KDV dahil, 600 hesap KDV hariç ve iptalleri de içerir."""
    fatura = sum(f["GENELTOPLAM"] for f in _satis_faturalari(dataset, EYLUL))
    hesap = sum(
        satir["TUTAR"]
        for satir in dataset["TBLMUHFIS"]
        if satir["HESAP_KODU"] == HESAP_SATIS_GELIRI and _in_span(satir["TARIH"], EYLUL)
    )
    return [(fatura, hesap)]


def q40(dataset: Dataset) -> list[tuple]:
    """Arşivde de net satış miktar bazlıdır; grup adı TBLSTGRUP.GRUP_ISIMI'ndeki yazımla süzülür."""
    adlar = {grup["GRUP_KODU"]: grup["GRUP_ISIMI"] for grup in dataset["TBLSTGRUP"]}
    grubu = {urun["STOK_KODU"]: urun["GRUP_KODU"] for urun in dataset["TBLSTSABIT"]}
    net: dict[str, float] = defaultdict(float)
    for hareket in _hareketler(dataset, "TBLSTHAR_ARSIV", ("S", "I")):
        ad = adlar[grubu[hareket["STOK_KODU"]]]
        if ad != GRUP_KURUYEMIS:
            continue
        net[ad] += hareket["STHAR_GCMIK"] * (1 if hareket["STHAR_HTUR"] == "S" else -1)
    return [(ad, miktar) for ad, miktar in sorted(net.items())]


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
    "Q21": q21,
    "Q22": q22,
    "Q23": q23,
    "Q24": q24,
    "Q25": q25,
    "Q26": q26,
    "Q27": q27,
    "Q28": q28,
    "Q29": q29,
    "Q30": q30,
    "Q31": q31,
    "Q32": q32,
    "Q33": q33,
    "Q34": q34,
    "Q35": q35,
    "Q36": q36,
    "Q37": q37,
    "Q38": q38,
    "Q39": q39,
    "Q40": q40,
}
