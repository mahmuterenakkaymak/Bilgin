"""Run 2 ek verisi: fiyat geçmişi, günlük döviz kuru, cari şubesi, kampanya, arşiv ve muhasebe fişleri.

Run 1 akışından bağımsız kendi rastgele akışıyla çalışır; Run 1 satırlarını ve Run 1 rng'sini
okumaz, değiştirmez. Run 2 için eklenen veri tablolarını ve distractor satırlarını doldurur.
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

# Yakın kopyalar (R2-4): gerçek tablonun satırlarından türerler ama cevabı bilinçli olarak saptırırlar;
# bu yüzden sayıları DISTRACTOR_ROWS'tan bağımsızdır, her zaman üretilirler.
YAKIN_KOPYALAR = ("TBLSTHAR_LOG", "TBLFATUIRS_TASLAK", "TBLCASABIT_YEDEK", "TBLSTSABIT_ESKI", "TBLSIPATRA_TMP")
LOG_KOPYA = 30
TASLAK_MIN, TASLAK_MAX = 5, 10
KOPYA_ARALIGI = 3  # kartın her üçüncü satırı yedeğe/eski sürüme girer
KULLANICI_ADLARI = ("admin", "muhasebe", "depo", "satis1", "servis")
DOLGU_METIN = ("Eski kayıt", "Arşiv kaydı", "Manuel giriş", "Sistem kaydı", "Kontrol listesi")
# Diğer distractor tabloların dolgu satırı sayısı üst sınırı (0-5); 0 = tablo şemada kaldığı gibi kalır.
DISTRACTOR_ROWS = 0
DOLGU_BAS = dt.date(2026, 1, 1)
DOLGU_BITIM = dt.date(2026, 12, 31)


def extend(dataset: dict, seed: int) -> None:
    """Run 2 tablolarını kendi akışıyla doldurur; yerinde değiştirir, Run 1'e dokunmaz."""
    rng = random.Random(f"{seed}:run2")
    schema = doc.load_schema()
    columns = {table["name"]: [c["name"] for c in table["columns"]] for table in schema["tables"]}
    _stok_fiyat(dataset, columns, rng)
    _doviz_kur(dataset, columns, rng)
    _cari_sube(dataset, columns, rng)
    _kampanya(dataset, columns, rng)
    _arsiv(dataset, columns, rng)
    _muhfis(dataset, columns, rng)
    distractor_rows(dataset, schema, rng)


def distractor_rows(dataset: dict, schema: dict, rng: random.Random) -> None:
    """Distractor tablolarını doldurur: yakın kopyalar gerçek cevaptan sapar, diğerleri dolgu alır."""
    columns = {table["name"]: [c["name"] for c in table["columns"]] for table in schema["tables"]}
    _sthar_log(dataset, columns.get("TBLSTHAR_LOG"), rng)
    _fatuir_taslak(dataset, columns.get("TBLFATUIRS_TASLAK"), rng)
    _cari_yedek(dataset, columns.get("TBLCASABIT_YEDEK"), rng)
    _stok_eski(dataset, columns.get("TBLSTSABIT_ESKI"), rng)
    _sipatra_tmp(dataset, columns.get("TBLSIPATRA_TMP"), rng)

    kodlar = {
        "STOK_KODU": [urun["STOK_KODU"] for urun in dataset["TBLSTSABIT"]],
        "CARI_KOD": [cari["CARI_KOD"] for cari in dataset["TBLCASABIT"]],
        "CARI_KODU": [cari["CARI_KOD"] for cari in dataset["TBLCASABIT"]],
        "DEPO_KODU": [depo["DEPO_KODU"] for depo in dataset["TBLDEPO"]],
        "_dataset": dataset,
    }
    dolgu = {t["name"]: t for t in schema["tables"] if t.get("kind") == "distractor" and t["name"] not in YAKIN_KOPYALAR}
    yapildi: set[str] = set()

    def doldur(table: dict) -> None:
        name = table["name"]
        if name in yapildi:
            return
        yapildi.add(name)
        for c in table["columns"]:  # fk hedefi de dolgu tablosuysa önce o dolsun
            hedef = c["fk"].split(".")[0] if c.get("fk") else None
            if hedef in dolgu:
                doldur(dolgu[hedef])
        adet = rng.randint(0, min(DISTRACTOR_ROWS, 5))  # varsayılan 0: tablo şemada kaldığı gibi kalır
        if any(_hedefi_bos(c, dataset) for c in table["columns"]):  # hedefi boş olan NOT NULL fk: geçerli satır yazılamaz
            adet = 0
        degerler = [
            {c["name"]: _dolgu_degeri(c, rng, kodlar, i) for c in table["columns"]} for i in range(1, adet + 1)
        ]
        _fill(dataset, name, columns.get(name), degerler)

    for table in dolgu.values():
        doldur(table)


def _sthar_log(dataset: dict, cols: list[str] | None, rng: random.Random) -> None:
    """Eylül 2026 hareketlerinin ~30 kopyası; bir kısmının miktarı düzenlenmiş, bir kısmı iki kez yazılmış."""
    eylul = [h for h in dataset["TBLSTHAR"] if EYLUL[0] <= h["STHAR_TARIH"] <= EYLUL[1]]
    kopya = rng.sample(eylul, min(LOG_KOPYA, len(eylul)))
    # Satış toplamı gerçek tabloyla aynı kalmasın: kopyadaki ilk satış hareketi mutlaka düzenlenir.
    hedef = next((i for i, h in enumerate(kopya) if h["STHAR_HTUR"] == "S"), None)
    satirlar: list[dict] = []
    for i, hareket in enumerate(kopya):
        satir = dict(hareket)
        satir["ISLEM"] = "D" if i == hedef or i % 5 == 0 else "E"
        if satir["ISLEM"] == "D":
            satir["STHAR_GCMIK"] = round(hareket["STHAR_GCMIK"] * 1.1, 2)
        satir["LOG_TARIH"] = hareket["STHAR_TARIH"]
        satirlar.append(satir)
        if i % 7 == 0:
            satirlar.append(dict(satir, ISLEM="D"))
    _fill(dataset, "TBLSTHAR_LOG", cols, satirlar)


def _fatuir_taslak(dataset: dict, cols: list[str] | None, rng: random.Random) -> None:
    """Eylül 2026'nın onaylanmamış fatura taslakları: ONAY_TARIHI boş, numaraları gerçek faturalarla çakışmaz."""
    alicilar = [c["CARI_KOD"] for c in dataset["TBLCASABIT"] if c["CARI_TIP"] in ("A", "H")]
    adet = rng.randint(TASLAK_MIN, TASLAK_MAX) if alicilar else 0
    satirlar: list[dict] = []
    for i in range(adet):
        satirlar.append({
            "FTIRSIP": 1,
            "FATIRS_NO": f"TSS{i + 1:05d}",
            "CARI_KODU": rng.choice(alicilar),
            "TARIH": _tarih(rng, dt.date(2026, 9, 1), dt.date(2026, 9, 30)),
            "GENELTOPLAM": round(rng.uniform(500.0, 40000.0), 2),
            "IPTAL": "H",
            "ONAY_TARIHI": None,
            "KULLANICI": rng.choice(KULLANICI_ADLARI),
        })
    _fill(dataset, "TBLFATUIRS_TASLAK", cols, satirlar)


def _cari_yedek(dataset: dict, cols: list[str] | None, rng: random.Random) -> None:
    """Kartların 2025 yedeği; yedeklerin bir kısmının ili güncel kartla uyuşmaz."""
    satirlar: list[dict] = []
    for i, cari in enumerate(dataset["TBLCASABIT"]):
        if i % KOPYA_ARALIGI:
            continue
        satir = dict(cari)
        if (i // KOPYA_ARALIGI) % 2 == 0:
            satir["IL"] = rng.choice([il for il in generator.CITIES if il != cari["IL"]])
        satir["KAYIT_TARIHI"] = _tarih(rng, ARSIV_BAS, ARSIV_BITIM)
        satir["ACIKLAMA"] = None if rng.random() < 0.4 else "Eski kart kaydı"
        satirlar.append(satir)
    _fill(dataset, "TBLCASABIT_YEDEK", cols, satirlar)


def _stok_eski(dataset: dict, cols: list[str] | None, rng: random.Random) -> None:
    """Ürün kartlarının eski sürümü: liste fiyatı bugünkünden düşük, VERSIYON 1."""
    satirlar: list[dict] = []
    for i, urun in enumerate(dataset["TBLSTSABIT"]):
        if i % KOPYA_ARALIGI:
            continue
        satir = dict(urun)
        if urun["BIRIM_FIYAT"] is not None:
            satir["BIRIM_FIYAT"] = round(urun["BIRIM_FIYAT"] * 0.9, 2)
        satir["KAYIT_TARIHI"] = _tarih(rng, ARSIV_BAS, ARSIV_BITIM)
        satir["VERSIYON"] = 1
        satirlar.append(satir)
    _fill(dataset, "TBLSTSABIT_ESKI", cols, satirlar)


def _sipatra_tmp(dataset: dict, cols: list[str] | None, rng: random.Random) -> None:
    """Sipariş satırlarının ara kaydı: aynı satırlar, bir kısmı vazgeçilmiş."""
    satirlar: list[dict] = []
    for i, satir in enumerate(dataset["TBLSIPATRA"]):
        if i % KOPYA_ARALIGI:
            continue
        satirlar.append(dict(satir, DURUM=rng.choice(("B", "O", "V")), EKLEYEN=rng.choice(KULLANICI_ADLARI)))
    _fill(dataset, "TBLSIPATRA_TMP", cols, satirlar)


def _hedefi_bos(column: dict, dataset: dict) -> bool:
    """NOT NULL bir fk sütununun hedefinde satır kalmadıysa bu tabloya geçerli satır yazılamaz."""
    if column["nullable"] or not column.get("fk"):
        return False
    return not dataset.get(column["fk"].split(".")[0])


def _dolgu_degeri(column: dict, rng: random.Random, kodlar: dict, sira: int):
    """Dolgu satırı değeri: gerçek kod, şemadaki kod kümesi ya da türe uygun rastgele değer."""
    if column.get("fk"):
        hedef_tablo, hedef_sutun = column["fk"].split(".")
        degerler = [satir[hedef_sutun] for satir in kodlar["_dataset"].get(hedef_tablo, [])]
        return rng.choice(degerler) if degerler else None  # hedef dolgu tablosu boşsa yalnız NULL sütuna girer
    if column["nullable"] and rng.random() < 0.25:
        return None
    havuz = kodlar.get(column["name"])
    if havuz:
        return rng.choice(havuz)
    tip = column["type"].split("(")[0].upper()
    if column["values"]:
        kod = rng.choice(sorted(column["values"]))
        return int(kod) if tip == "INT" and kod.isdigit() else kod
    if tip == "DATE":
        return _tarih(rng, DOLGU_BAS, DOLGU_BITIM)
    if tip == "INT":
        return sira
    if tip == "DECIMAL":
        return round(rng.uniform(1.0, 25000.0), 2)
    if tip == "NVARCHAR":
        return rng.choice(DOLGU_METIN)
    return f"{column['name'][:6]}{sira:04d}"


def _stok_fiyat(dataset: dict, columns: dict, rng: random.Random) -> None:
    """Ürün başına 2-4 satış/alış fiyat satırı; en az bir ürünün liste fiyatı dönem içinde değişir."""
    urunler = dataset["TBLSTSABIT"]
    degisen = set(rng.sample(range(len(urunler)), max(1, len(urunler) // 3)))
    satirlar: list[dict] = []
    kullanilan: set[tuple[str, str, str]] = set()
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
            tarih = _benzersiz_tarih(urun["STOK_KODU"], tip, tarih, kullanilan)
            satirlar.append({"STOK_KODU": urun["STOK_KODU"], "FIYAT_TIPI": tip, "FIYAT": fiyat, "GECERLILIK_TARIHI": tarih})
    for j, satir in enumerate(satirlar, start=1):
        satir["FIAT_ID"] = j
    _fill(dataset, "TBLSTOKFIAT", columns.get("TBLSTOKFIAT"), satirlar)


def _benzersiz_tarih(kod: str, tip: str, tarih: str, kullanilan: set) -> str:
    """Aynı (ürün, fiyat tipi, tarih) iki kez yazılmaz; R2-3'ün "en son geçerlik tarihli satırı" belirsiz kalmasın.

    ASSUMPTION: çakışan tarih, satırın kendi aralığındaki (dönem içi satırlar Haziran-Eylül 2026 içinde
    kalır) ilk boş güne kayar; rng'ye dokunulmadığı için çakışma olmayan tohumların satırları değişmez.
    """
    bas, bitim = (OLCUM_BAS, OLCUM_BITIM) if OLCUM_BAS <= dt.date.fromisoformat(tarih) <= OLCUM_BITIM else (FIYAT_BAS, FIYAT_BITIM)
    ara, gun = (bitim - bas).days + 1, (dt.date.fromisoformat(tarih) - bas).days
    while (kod, tip, (bas + dt.timedelta(days=gun)).isoformat()) in kullanilan:
        gun = (gun + 1) % ara
    tarih = (bas + dt.timedelta(days=gun)).isoformat()
    kullanilan.add((kod, tip, tarih))
    return tarih


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
