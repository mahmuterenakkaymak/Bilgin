"""Run 2 ek verisi: fiyat geçmişi, günlük döviz kuru, cari şubesi, kampanya, arşiv ve muhasebe fişleri.

Run 1 akışından bağımsız kendi rastgele akışıyla çalışır; Run 1 satırlarını ve Run 1 rng'sini
okumaz, değiştirmez. Yalnız Run 2 için eklenen veri tablolarını doldurur.
"""

from __future__ import annotations

import datetime as dt
import random
from collections import defaultdict

from nl2sql.schema_map import doc, generator

FIYAT_TIPLERI = ("S", "A")
DOVIZ_BAS = {"USD": 34.0, "EUR": 37.0}
SUBE_AD = ["Merkez", "Anadolu", "Avrupa", "Liman", "Organize"]
ILCELER = ["Merkez", "Çankaya", "Kadıköy", "Konak", "Nilüfer", "Muratpaşa", "Selçuklu"]
KAMPANYA_AD = ["Yaz", "Kış", "Bahar", "Bayram", "Okula Dönüş", "Sezon Sonu", "Hafta Sonu", "Süper"]
MUH_HESAP = {1: ("600", "A"), 3: ("610", "B"), 2: ("153", "B")}
KDV_ORANI = 0.20
# Arşiv hareket sayısı (T iki satır üretir) ve hareket tipinin Run 1 ile aynı çıkış/giriş eşleşmesi.
ARSIV_MIN, ARSIV_MAX = 240, 320
ARSIV_TURLER = ("S", "S", "S", "S", "A", "A", "I", "T", "T", "D")
ARSIV_GCKOD = {"S": "C", "A": "G", "I": "G"}
# 2025 şampiyonu Eylül 2026'nınki olmasın: diğer ürünlerin en yüksek satış toplamının üstüne taşınır.
SAMPIYON_SATIR = 12
SAMPIYON_FARK = 500.0
EYLUL = ("2026-09-01", "2026-09-30")

# Ölçüm dönemi Haziran-Eylül 2026; fiyat geçmişi 2025 Ocak'tan dönem sonuna kadar uzanır.
OLCUM_BAS = dt.date(2026, 6, 1)
OLCUM_BITIM = dt.date(2026, 9, 30)
FIYAT_BAS = dt.date(2025, 1, 1)
FIYAT_BITIM = dt.date(2026, 9, 30)
ARSIV_BAS = dt.date(2025, 1, 1)
ARSIV_BITIM = dt.date(2025, 12, 31)


def extend(dataset: dict, seed: int) -> None:
    """Run 2 tablolarını kendi akışıyla doldurur; yerinde değiştirir, Run 1'e dokunmaz."""
    rng = random.Random(f"{seed}:run2")
    columns = {table["name"]: [c["name"] for c in table["columns"]] for table in doc.load_schema()["tables"]}
    _stok_fiyat(dataset, columns, rng)
    _doviz_kur(dataset, columns, rng)
    _cari_sube(dataset, columns, rng)
    _kampanya(dataset, columns, rng)
    _arsiv(dataset, columns, rng)
    _muhfis(dataset, columns, rng)


def _stok_fiyat(dataset: dict, columns: dict, rng: random.Random) -> None:
    """Ürün başına 2-4 satış/alış fiyat satırı; en az bir ürünün liste fiyatı dönem içinde değişir."""
    urunler = dataset["TBLSTSABIT"]
    degisen = set(rng.sample(range(len(urunler)), max(1, len(urunler) // 3)))
    satirlar: list[dict] = []
    for i, urun in enumerate(urunler):
        taban = urun["BIRIM_FIYAT"] or round(rng.uniform(10.0, 200.0), 2)
        plan: list[tuple] = []
        if i in degisen:
            taban_fiyat = round(taban * rng.uniform(0.85, 1.05), 2)
            plan.append(("S", _tarih(rng, dt.date(2025, 1, 1), dt.date(2025, 12, 31)), taban_fiyat))
            plan.append(("S", _tarih(rng, OLCUM_BAS, OLCUM_BITIM), round(taban_fiyat * 1.15, 2)))
        else:
            plan.append((rng.choice(FIYAT_TIPLERI), _tarih(rng, FIYAT_BAS, FIYAT_BITIM), round(taban * rng.uniform(0.85, 1.15), 2)))
        for _ in range(rng.randint(2, 4) - len(plan)):
            plan.append((rng.choice(FIYAT_TIPLERI), _tarih(rng, FIYAT_BAS, FIYAT_BITIM), round(taban * rng.uniform(0.85, 1.15), 2)))
        for tip, tarih, fiyat in plan:
            satirlar.append({"STOK_KODU": urun["STOK_KODU"], "FIYAT_TIPI": tip, "FIYAT": fiyat, "GECERLILIK_TARIHI": tarih})
    for j, satir in enumerate(satirlar, start=1):
        satir["FIAT_ID"] = j
    _fill(dataset, "TBLSTOKFIAT", columns.get("TBLSTOKFIAT"), satirlar)


def _doviz_kur(dataset: dict, columns: dict, rng: random.Random) -> None:
    """Dönem içinde her gün için USD ve EUR; satış kuru alış kurundan daima yüksek."""
    kur = dict(DOVIZ_BAS)
    satirlar: list[dict] = []
    gun = OLCUM_BAS
    while gun <= OLCUM_BITIM:
        for kod in ("USD", "EUR"):
            kur[kod] *= rng.uniform(0.995, 1.006)
            alis = round(kur[kod], 2)
            satis = round(alis * rng.uniform(1.001, 1.02), 2)
            if satis <= alis:
                satis = round(alis + 0.01, 2)
            satirlar.append({"KUR_TARIH": gun.isoformat(), "DOVIZ_KODU": kod, "ALIS": alis, "SATIS": satis})
        gun += dt.timedelta(days=1)
    _fill(dataset, "TBLDOVKUR", columns.get("TBLDOVKUR"), satirlar)


def _cari_sube(dataset: dict, columns: dict, rng: random.Random) -> None:
    """Cari başına 0-3 şube; en az bir şube kapalı ve en az bir cari kendi ili dışında şube taşır."""
    caris = dataset["TBLCASABIT"]
    iller = generator.CITIES
    hedef = rng.randrange(len(caris))
    satirlar: list[dict] = []
    for i, cari in enumerate(caris):
        adet = max(1, rng.randint(0, 3)) if i == hedef else rng.randint(0, 3)
        for _ in range(adet):
            il = rng.choice(iller)
            if i == hedef and il == cari["IL"]:
                il = rng.choice([x for x in iller if x != cari["IL"]])
            satirlar.append({
                "CARI_KOD": cari["CARI_KOD"],
                "SUBE_ADI": f"{cari['CARI_ISIM']} {rng.choice(SUBE_AD)} Şubesi",
                "IL": il,
                "ILCE": None if rng.random() < 0.3 else rng.choice(ILCELER),
                "AKTIF": "H" if rng.random() < 0.25 else "E",
            })
    satirlar[0]["AKTIF"] = "H"
    for j, satir in enumerate(satirlar, start=1):
        satir["SUBE_KODU"] = f"SBR{j:04d}"
    _fill(dataset, "TBLCARISUBE", columns.get("TBLCARISUBE"), satirlar)


def _kampanya(dataset: dict, columns: dict, rng: random.Random) -> None:
    """5-8 kampanya; gerçek ürünler üzerinde, dönemin içinde kalan tarih aralığı ve %5-30 indirim."""
    urunler = dataset["TBLSTSABIT"]
    satirlar: list[dict] = []
    for i in range(rng.randint(5, 8)):
        bas = _tarih(rng, OLCUM_BAS, OLCUM_BITIM)
        bitis = _tarih(rng, OLCUM_BAS, OLCUM_BITIM)
        if bitis < bas:
            bas, bitis = bitis, bas
        satirlar.append({
            "KAMPANYA_KODU": f"KMP{i + 1:03d}",
            "KAMPANYA_ADI": f"{rng.choice(KAMPANYA_AD)} Kampanyası",
            "STOK_KODU": rng.choice(urunler)["STOK_KODU"],
            "BASLANGIC": bas,
            "BITIS": bitis,
            "INDIRIM_ORANI": float(rng.randint(5, 30)),
        })
    _fill(dataset, "TBLKAMPANYA", columns.get("TBLKAMPANYA"), satirlar)


def _arsiv(dataset: dict, columns: dict, rng: random.Random) -> None:
    """2025 Ocak-Aralık hareketleri; kartlar Run 1'den, faturasız tipler (T/D) FISNO NULL kalır."""
    urunler = dataset["TBLSTSABIT"]
    depolar = dataset["TBLDEPO"]
    alicilar = [c for c in dataset["TBLCASABIT"] if c["CARI_TIP"] in ("A", "H")]
    saticilar = [c for c in dataset["TBLCASABIT"] if c["CARI_TIP"] in ("S", "H")]
    satirlar: list[dict] = []
    belge = 0

    def satir(urun, depo, gckod, miktar, nf, tarih, htur, fisno, cari) -> None:
        satirlar.append({
            "STHAR_ID": len(satirlar) + 1,
            "STOK_KODU": urun["STOK_KODU"],
            "DEPO_KODU": depo["DEPO_KODU"],
            "STHAR_GCKOD": gckod,
            "STHAR_GCMIK": miktar,
            "STHAR_NF": nf,
            "STHAR_TARIH": tarih,
            "STHAR_HTUR": htur,
            "FISNO": fisno,
            "CARI_KODU": cari,
        })

    amac = rng.randint(ARSIV_MIN, ARSIV_MAX)
    while len(satirlar) < amac:
        urun = rng.choice(urunler)
        tarih = _tarih(rng, ARSIV_BAS, ARSIV_BITIM)
        miktar = generator._miktar(rng, urun)
        htur = rng.choice(ARSIV_TURLER)
        if htur == "T":
            kaynak, varis = rng.sample(depolar, 2)
            for depo, gckod in ((kaynak, "C"), (varis, "G")):
                satir(urun, depo, gckod, miktar, None, tarih, htur, None, None)
        elif htur == "D":
            satir(urun, rng.choice(depolar), "G", miktar, None, tarih, htur, None, None)
        else:
            cari = rng.choice(alicilar if htur in ("S", "I") else saticilar)
            belge += 1
            satir(urun, rng.choice(depolar), ARSIV_GCKOD[htur], miktar, generator._fiyat(rng, urun),
                  tarih, htur, f"ARS{belge:06d}", cari["CARI_KOD"])

    # Arşiv tuzağı: "en çok satan ürün" sorusunun cevabı kaynağa göre değişsin, o yüzden 2025'in
    # şampiyonu Eylül 2026'da birinci olmayan bir üründür ve öbür tüm ürünleri açık ara geçer.
    eylul = _satis_toplami(dataset["TBLSTHAR"], EYLUL[0], EYLUL[1])
    en_yuksek = max(eylul.values(), default=0.0)
    adaylar = [u for u in urunler if eylul.get(u["STOK_KODU"], 0.0) < en_yuksek] or urunler
    sampiyon = rng.choice(adaylar)
    arsiv = _satis_toplami(satirlar, ARSIV_BAS.isoformat(), ARSIV_BITIM.isoformat())
    tavan = max((adet for kod, adet in arsiv.items() if kod != sampiyon["STOK_KODU"]), default=0.0)
    miktar = round((tavan + SAMPIYON_FARK) / SAMPIYON_SATIR, 2)
    for _ in range(SAMPIYON_SATIR):
        belge += 1
        satir(sampiyon, rng.choice(depolar), "C", miktar, generator._fiyat(rng, sampiyon),
              _tarih(rng, ARSIV_BAS, ARSIV_BITIM), "S", f"ARS{belge:06d}", rng.choice(alicilar)["CARI_KOD"])

    _fill(dataset, "TBLSTHAR_ARSIV", columns.get("TBLSTHAR_ARSIV"), satirlar)


def _satis_toplami(hareketler: list[dict], bas: str, bitim: str) -> dict:
    """Dönem içindeki satış (S) çıkışlarının ürün bazında miktar toplamı."""
    toplam: dict[str, float] = defaultdict(float)
    for hareket in hareketler:
        if hareket["STHAR_HTUR"] == "S" and bas <= hareket["STHAR_TARIH"] <= bitim:
            toplam[hareket["STOK_KODU"]] += hareket["STHAR_GCMIK"]
    return toplam


def _muhfis(dataset: dict, columns: dict, rng: random.Random) -> None:
    """Her fatura (iptal edilenler dahil) için bir gelir/gider ve bir hesaplanan KDV satırı."""
    satirlar: list[dict] = []
    for i, fatura in enumerate(dataset["TBLFATUIRS"], start=1):
        hesap, yon = MUH_HESAP[fatura["FTIRSIP"]]
        kdv = round(fatura["GENELTOPLAM"] * KDV_ORANI / (1 + KDV_ORANI), 2)
        for j, (kod, tutar) in enumerate((("391", kdv), (hesap, round(fatura["GENELTOPLAM"] - kdv, 2))), start=1):
            satirlar.append({
                "MUHFIS_ID": len(satirlar) + 1,
                "FIS_NO": f"MF{i:06d}",
                "TARIH": fatura["TARIH"],
                "HESAP_KODU": kod,
                "BA": yon,
                "TUTAR": tutar,
                "FATIRS_NO": fatura["FATIRS_NO"],
            })
    _fill(dataset, "TBLMUHFIS", columns.get("TBLMUHFIS"), satirlar)


def _tarih(rng: random.Random, bas: dt.date, bitim: dt.date) -> str:
    gun = (bitim - bas).days
    return (bas + dt.timedelta(days=rng.randrange(gun + 1))).isoformat()


def _fill(dataset: dict, name: str, cols: list[str] | None, degerler: list[dict]) -> None:
    """Satır anahtarları tam olarak şema sütunları, şema sırasıyla.

    ASSUMPTION: şema bir hedef tabloyu bu üreticinin ürettiği sütunlardan farklı tanımlarsa
    (ör. testlerin sahte şeması) tablo boş kalır; böylece Run 1 dünyası ve şema sözleşmesi bozulmaz.
    """
    if cols is None or any(set(deger) != set(cols) for deger in degerler):
        dataset[name] = []
    else:
        dataset[name] = [{c: deger[c] for c in cols} for deger in degerler]
