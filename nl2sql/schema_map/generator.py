"""Synthetic Netsis-like dataset: master cards, then the documents (invoices, movements, orders) that point at them."""

from __future__ import annotations

import datetime as dt
import random

from nl2sql import config
from nl2sql.schema_map import doc, extra

CITIES = ["ANKARA", "İSTANBUL", "İZMİR", "BURSA", "KONYA", "SAMSUN", "ANTALYA"]
VAT_RATES = (10.0, 20.0)

GROUPS = [
    ("Gıda", "Kuru gıda ve temel mutfak ürünleri"),
    ("İçecek", "Çay, kahve, su, meyve suyu"),
    ("Temizlik", "Ev ve çamaşır temizlik ürünleri"),
    ("Kişisel Bakım", "Şampuan, sabun, diş macunu"),
    ("Kahvaltılık", "Peynir, zeytin, bal"),
    ("Kuruyemiş", "Çekirdek, kuru meyve, fındık"),
    ("Baharat", "Tuz, pul biber, karabiber"),
    ("Atıştırmalık", "Bisküvi, cips, çikolata"),
]

PRODUCTS = [
    ("Domates Salçası 700 g", "ADET", "Gıda"),
    ("Toz Şeker 5 kg", "ADET", "Gıda"),
    ("Buğday Unu 500 g", "ADET", "Gıda"),
    ("Pirinç 2 kg", "ADET", "Gıda"),
    ("Bulgur Pilavlık 1 kg", "KG", "Gıda"),
    ("Makarna 500 g", "ADET", "Gıda"),
    ("Zeytinyağı 1 L", "ADET", "Gıda"),
    ("Kuru Fasulye 1 kg", "KG", "Gıda"),
    ("Nohut 1 kg", "KG", "Gıda"),
    ("Kırmızı Mercimek 1 kg", "KG", "Gıda"),
    ("Siyah Çay 500 g", "ADET", "İçecek"),
    ("Elma Suyu 1 L", "ADET", "İçecek"),
    ("İçme Suyu 5 L", "ADET", "İçecek"),
    ("Türk Kahvesi 100 g", "ADET", "İçecek"),
    ("Çamaşır Deterjanı 3 L", "ADET", "Temizlik"),
    ("Bulaşık Deterjanı 750 ml", "ADET", "Temizlik"),
    ("Çamaşır Suyu 2 L", "ADET", "Temizlik"),
    ("Yumuşatıcı 1 L", "ADET", "Temizlik"),
    ("Streç Film 30 m", "M", "Temizlik"),
    ("Alüminyum Folyo 10 m", "M", "Temizlik"),
    ("Şampuan 400 ml", "ADET", "Kişisel Bakım"),
    ("Kalıp Sabun 120 g", "ADET", "Kişisel Bakım"),
    ("Diş Macunu 100 ml", "ADET", "Kişisel Bakım"),
    ("Beyaz Peynir", "KG", "Kahvaltılık"),
    ("Siyah Zeytin", "KG", "Kahvaltılık"),
    ("Yeşil Zeytin", "KG", "Kahvaltılık"),
    ("Süzme Bal 850 g", "ADET", "Kahvaltılık"),
    ("Fındık Ezmesi 400 g", "ADET", "Kahvaltılık"),
    ("Kabak Çekirdeği", "KG", "Kuruyemiş"),
    ("Kuru Üzüm", "KG", "Kuruyemiş"),
    ("Çiğ Fındık", "KG", "Kuruyemiş"),
    ("Tuz 750 g", "ADET", "Baharat"),
    ("Pul Biber 100 g", "ADET", "Baharat"),
    ("Karabiber 100 g", "ADET", "Baharat"),
    ("Kakaolu Bisküvi 500 g", "ADET", "Atıştırmalık"),
    ("Patates Cipsi 150 g", "ADET", "Atıştırmalık"),
    ("Süt Çikolatası 90 g", "ADET", "Atıştırmalık"),
]

DEPOTS = [
    ("Merkez Depo", "ANKARA", "E"),
    ("Avrupa Yakası Deposu", "İSTANBUL", "H"),
    ("Ege Bölge Deposu", "İZMİR", "H"),
    ("Transit Depo", None, "H"),
]

PLASIYER_NAMES = [
    "Ahmet Yıldırım",
    "Ayşe Demir",
    "Mehmet Kaya",
    "Fatma Şahin",
    "Mustafa Çelik",
    "Zeynep Arslan",
    "Hasan Doğan",
    "Elif Koç",
    "İbrahim Kurt",
    "Emine Aslan",
]

CARI_HEADS = [
    "Anadolu", "Marmara", "Ege", "Akdeniz", "Karadeniz", "Başkent", "Yıldız", "Zafer",
    "Mertaş", "Kuzey", "Doğu", "Batı", "Altın", "Gümüş", "Pirinç", "Çınar",
    "Deniz", "Orkide", "Lale", "Papatya", "Şimşek", "Bereket", "Hilal", "Zümrüt",
    "Elmas", "Fırat", "Dicle", "Toros", "Kartal", "Dolunay", "Yeşil", "Altay",
]

CARI_TAILS = [
    "Gıda Ltd. Şti.",
    "Market A.Ş.",
    "Toptancılık Ltd. Şti.",
    "İhtiyaç Maddeleri A.Ş.",
    "Gıda ve Market",
    "Temizlik Ürünleri Ltd.",
]

# Ölçüm dönemi: golden soruların tümü Haziran-Eylül 2026 aralığını kapsar.
MONTHS = ("2026-06", "2026-07", "2026-08", "2026-09")
FATURA_ONEV = {"1": "SF", "2": "AF", "3": "IF"}
HAREKET_YONU = {"1": ("C", "S"), "2": ("G", "A"), "3": ("G", "I")}
CAHAR_YONU = {"1": "B", "2": "A", "3": "A"}


def generate(seed: int = config.SEED) -> dict[str, list[dict]]:
    """Dataset for one seed; the same seed always replays the same rows."""
    rng = random.Random(seed)
    columns = {table["name"]: [c["name"] for c in table["columns"]] for table in doc.load_schema()["tables"]}
    groups = _groups(rng, columns["TBLSTGRUP"])
    products = _products(rng, columns["TBLSTSABIT"], groups)
    depots = _depots(columns["TBLDEPO"])
    reps = _reps(rng, columns["TBLPLASIYER"])
    caris = _caris(rng, columns["TBLCASABIT"], reps)
    invoices, movements, cari_movements, orders, order_lines = _documents(
        rng, columns, products, depots, caris
    )
    dataset = {
        "TBLSTGRUP": groups,
        "TBLSTSABIT": products,
        "TBLDEPO": depots,
        "TBLPLASIYER": reps,
        "TBLCASABIT": caris,
        "TBLFATUIRS": invoices,
        "TBLSTHAR": movements,
        "TBLCAHAR": cari_movements,
        "TBLSIPAMAS": orders,
        "TBLSIPATRA": order_lines,
    }
    # R2-1: her şema tablosunun anahtarı vardır; burada doldurmadıklarımız boş liste kalır.
    for name in columns:
        dataset.setdefault(name, [])
    # R2-3: Run 2 ek verisi kendi akışıyla en sonda eklenir; Run 1 satırlarını değiştirmez.
    extra.extend(dataset, seed)
    # R3-7: Run 3'ün uydurma PII verisi kendi akışıyla en sonda eklenir; Run 1/Run 2 satırları aynı kalır.
    extra.extend_run3(dataset, seed)
    return dataset


def _groups(rng: random.Random, names: list[str]) -> list[dict]:
    aciklamasiz = _some_indices(rng, len(GROUPS), 0.25)
    return [
        _row(
            names,
            {
                "GRUP_KODU": f"GRP{i:02d}",
                "GRUP_ISIMI": isim,
                "ACIKLAMA": None if i in aciklamasiz else aciklama,
            },
        )
        for i, (isim, aciklama) in enumerate(GROUPS)
    ]


def _products(rng: random.Random, names: list[str], groups: list[dict]) -> list[dict]:
    kodlar = {group["GRUP_ISIMI"]: group["GRUP_KODU"] for group in groups}
    secim = rng.sample(PRODUCTS, rng.randint(18, 26))
    fiyatsiz = _some_indices(rng, len(secim), 0.15)
    pasif = _some_indices(rng, len(secim), 0.15)
    rows = []
    for i, (ad, birim, grup) in enumerate(secim):
        rows.append(
            _row(
                names,
                {
                    "STOK_KODU": f"STK{i + 1:04d}",
                    "STOK_ADI": ad,
                    "GRUP_KODU": kodlar[grup],
                    "OLCU_BR1": birim,
                    "KDV_ORANI": rng.choice(VAT_RATES),
                    "BIRIM_FIYAT": None if i in fiyatsiz else round(rng.uniform(5.0, 450.0), 2),
                    "AKTIF": "H" if i in pasif else "E",
                },
            )
        )
    return rows


def _depots(names: list[str]) -> list[dict]:
    return [
        _row(
            names,
            {
                "DEPO_KODU": f"DEP{i:02d}",
                "DEPO_ISIMI": isim,
                "IL": il,
                "VARSAYILAN": varsayilan,
            },
        )
        for i, (isim, il, varsayilan) in enumerate(DEPOTS)
    ]


def _reps(rng: random.Random, names: list[str]) -> list[dict]:
    secim = rng.sample(PLASIYER_NAMES, rng.randint(5, 7))
    ilsiz = _some_indices(rng, len(secim), 0.2)
    telsiz = _some_indices(rng, len(secim), 0.3)
    rows = []
    for i, ad in enumerate(secim):
        telefon = f"0{rng.randint(212, 555)} {rng.randint(200, 899)} {rng.randint(10, 99)} {rng.randint(10, 99)}"
        rows.append(
            _row(
                names,
                {
                    "PLASIYER_KODU": f"PLS{i + 1:03d}",
                    "AD_SOYAD": ad,
                    "IL": None if i in ilsiz else rng.choice(CITIES),
                    "TELEFON": None if i in telsiz else telefon,
                },
            )
        )
    return rows


def _caris(rng: random.Random, names: list[str], reps: list[dict]) -> list[dict]:
    # Her şehirde en az bir alıcı ve her tipten en az bir cari: hiçbir tohumda Q01/Q08 boş sonuçla ölçülmesin.
    ikili = [(sehir, "A") for sehir in CITIES] + [("ANKARA", "S"), ("İSTANBUL", "H")]
    for _ in range(rng.randint(15, 22)):
        ikili.append((rng.choice(CITIES), rng.choice(("A", "S", "H"))))
    rng.shuffle(ikili)
    plasiyersiz = _some_indices(rng, len(ikili), 0.2)
    rows = []
    for i, (il, tip) in enumerate(ikili):
        rows.append(
            _row(
                names,
                {
                    "CARI_KOD": f"CAR{i + 1:05d}",
                    "CARI_ISIM": f"{CARI_HEADS[i]} {rng.choice(CARI_TAILS)}",
                    "CARI_TIP": tip,
                    "IL": il,
                    "PLASIYER_KODU": None if i in plasiyersiz else rng.choice(reps)["PLASIYER_KODU"],
                },
            )
        )
    return rows


def _documents(rng: random.Random, columns: dict, products: list[dict], depots: list[dict], caris: list[dict]):
    """Fatura, stok hareketi, cari hesap ve sipariş belgeleri; tuzakların hepsi burada kurulur."""
    fatura_ad = columns["TBLFATUIRS"]
    sthar_ad = columns["TBLSTHAR"]
    cahar_ad = columns["TBLCAHAR"]
    siparis_ad = columns["TBLSIPAMAS"]
    satir_ad = columns["TBLSIPATRA"]

    alicilar = [c for c in caris if c["CARI_TIP"] in ("A", "H")]
    saticilar = [c for c in caris if c["CARI_TIP"] in ("S", "H")]
    ikili = next(c for c in caris if c["CARI_TIP"] == "H")
    havuz = [p for p in products if p["AKTIF"] == "E"]
    iade_fazla, iade_az, depo_urun, fiyat_urun = rng.sample(havuz, 4)
    serbest = [
        p for p in havuz if p not in (iade_fazla, iade_az, depo_urun, fiyat_urun)
    ]

    faturalar: list[dict] = []
    hareketler: list[dict] = []
    caharlar: list[dict] = []
    siparisler: list[dict] = []
    sip_satirlari: list[dict] = []
    numaralar = {"1": 0, "2": 0, "3": 0}

    def gun(ay: str | None = None) -> str:
        return f"{ay or rng.choice(MONTHS)}-{rng.randint(1, 28):02d}"

    def fatura(tip, cari, cizgiler=(), ay=None, iptal="H", toplam=None) -> dict:
        numaralar[tip] += 1
        fisno = f"{FATURA_ONEV[tip]}{numaralar[tip]:05d}"
        tarih = gun(ay)
        gckod, htur = HAREKET_YONU[tip]
        ara = 0.0
        for urun, miktar, depo, nf in cizgiler:
            fiyat = _fiyat(rng, urun) if nf is None else nf
            ara += _kdvli(round(miktar * fiyat, 2), urun)
            hareketler.append(
                _row(
                    sthar_ad,
                    {
                        "STHAR_ID": len(hareketler) + 1,
                        "STOK_KODU": urun["STOK_KODU"],
                        "DEPO_KODU": depo["DEPO_KODU"],
                        "STHAR_GCKOD": gckod,
                        "STHAR_GCMIK": miktar,
                        "STHAR_NF": fiyat,
                        "STHAR_TARIH": tarih,
                        "STHAR_HTUR": htur,
                        "FISNO": fisno,
                        "CARI_KODU": cari["CARI_KOD"],
                    },
                )
            )
        belge = _row(
            fatura_ad,
            {
                "FTIRSIP": int(tip),
                "FATIRS_NO": fisno,
                "CARI_KODU": cari["CARI_KOD"],
                "TARIH": tarih,
                "GENELTOPLAM": round(toplam if toplam is not None else ara, 2),
                "IPTAL": iptal,
            },
        )
        faturalar.append(belge)
        if iptal == "H":
            caharlar.append(
                _row(
                    cahar_ad,
                    {
                        "CAHAR_ID": len(caharlar) + 1,
                        "CARI_KODU": cari["CARI_KOD"],
                        "TARIH": tarih,
                        "BA": CAHAR_YONU[tip],
                        "TUTAR": belge["GENELTOPLAM"],
                        "FISNO": fisno,
                        "ACIKLAMA": None if rng.random() < 0.25 else f"Fatura {fisno}",
                    },
                )
            )
        return belge

    def siparis(cari, satirlar, ay=None) -> None:
        no = f"SPO{len(siparisler) + 1:05d}"
        tarih = gun(ay)
        ara = 0.0
        for urun, miktar, belirsiz in satirlar:
            fiyat = _fiyat(rng, urun)
            tutar = round(miktar * fiyat, 2)
            ara += _kdvli(tutar, urun)
            sip_satirlari.append(
                _row(
                    satir_ad,
                    {
                        "SIPATRA_ID": len(sip_satirlari) + 1,
                        "SIPARIS_NO": no,
                        "STOK_KODU": urun["STOK_KODU"],
                        "MIKTAR": miktar,
                        "BIRIM_FIYAT": fiyat,
                        "TUTAR": tutar,
                        "TESLIM_TARIHI": None if belirsiz else _teslim(rng, tarih),
                    },
                )
            )
        siparisler.append(
            _row(
                siparis_ad,
                {
                    "SIPARIS_NO": no,
                    "CARI_KODU": cari["CARI_KOD"],
                    "TARIH": tarih,
                    "TOPLAM_TUTAR": round(ara, 2),
                },
            )
        )

    # --- tuzaklar: her tohumda gerçekten kurulması gereken şekiller ---------------
    # Q02: aynı ürün Eylül'de iki ayrı depodan çıkıyor; depoya göre gruplayan sayıyı böler.
    for depo in rng.sample(depots, 2):
        fatura("1", rng.choice(alicilar), [(depo_urun, _miktar(rng, depo_urun), depo, None)], "2026-09")

    # Q03: aynı ürün Ağustos'ta iki farklı net fiyatla satılıyor; kart fiyatı ciroyu yanlış verir.
    taban = _fiyat(rng, fiyat_urun)
    for katsayi in (1.0, 1.2):
        cizgi = (fiyat_urun, _miktar(rng, fiyat_urun), rng.choice(depots), round(taban * katsayi, 2))
        fatura("1", rng.choice(alicilar), [cizgi], "2026-08")

    # Q08: H tipli cari hem satış hem alış tarafında görünür.
    fatura("1", ikili, _cizgiler(rng, serbest, depots))
    fatura("2", ikili, _cizgiler(rng, serbest, depots))

    # Q06: üç satırlı fatura; başlığı satırlarla join edip toplamak tutarı katlar.
    fatura("1", rng.choice(alicilar), _cizgiler(rng, serbest, depots, 3))

    # Q05/Q10: bir üründe iade oranı %10'un üzerinde, diğerinin altında.
    for _ in range(4):
        fatura("1", rng.choice(alicilar), [(iade_fazla, 20.0, rng.choice(depots), None)])
    for _ in range(2):
        fatura("3", rng.choice(alicilar), [(iade_fazla, 15.0, rng.choice(depots), None)])
    for _ in range(4):
        fatura("1", rng.choice(alicilar), [(iade_az, 20.0, rng.choice(depots), None)])
    fatura("3", rng.choice(alicilar), [(iade_az, 2.0, rng.choice(depots), None)])

    for _ in range(rng.randint(45, 60)):
        fatura("1", rng.choice(alicilar), _cizgiler(rng, serbest, depots))
    for _ in range(rng.randint(12, 18)):
        fatura("2", rng.choice(saticilar), _cizgiler(rng, serbest, depots))
    for _ in range(rng.randint(8, 14)):
        adaylar = [u for u in serbest if _kalan_satis(hareketler, u) >= 1.0]
        if not adaylar:
            continue
        urun = rng.choice(adaylar)
        miktar = round(min(rng.uniform(1.0, 8.0), _kalan_satis(hareketler, urun)), 2)
        fatura("3", rng.choice(alicilar), [(urun, miktar, rng.choice(depots), None)])

    # Q04: iptal faturalar. ASSUMPTION: iptal edilen faturanın stok hareketi kalmaz, bu yüzden
    # GENELTOPLAM'ın satırlarla tutarlılığı yalnızca satırı olan faturalar için aranır.
    for ay in ("2026-06", "2026-08", "2026-09", "2026-09"):
        tip = rng.choice(("1", "1", "2"))
        cari = rng.choice(alicilar if tip == "1" else saticilar)
        fatura(tip, cari, ay=ay, iptal="E", toplam=_tutar(rng))
    for _ in range(rng.randint(2, 4)):
        fatura("1", rng.choice(alicilar), iptal="E", toplam=_tutar(rng))

    # Q07: faturasız hareketler — transfer çıkış+giriş çifti, sayım tek giriş; FISNO NULL.
    for _ in range(rng.randint(10, 16)):
        urun = rng.choice(products)
        kaynak, hedef = rng.sample(depots, 2)
        miktar, tarih = _miktar(rng, urun), gun()
        for depo, yon in ((kaynak, "C"), (hedef, "G")):
            hareketler.append(
                _row(
                    sthar_ad,
                    {
                        "STHAR_ID": len(hareketler) + 1,
                        "STOK_KODU": urun["STOK_KODU"],
                        "DEPO_KODU": depo["DEPO_KODU"],
                        "STHAR_GCKOD": yon,
                        "STHAR_GCMIK": miktar,
                        "STHAR_NF": None,
                        "STHAR_TARIH": tarih,
                        "STHAR_HTUR": "T",
                        "FISNO": None,
                        "CARI_KODU": None,
                    },
                )
            )
    for _ in range(rng.randint(6, 12)):
        urun = rng.choice(products)
        hareketler.append(
            _row(
                sthar_ad,
                {
                    "STHAR_ID": len(hareketler) + 1,
                    "STOK_KODU": urun["STOK_KODU"],
                    "DEPO_KODU": rng.choice(depots)["DEPO_KODU"],
                    "STHAR_GCKOD": "G",
                    "STHAR_GCMIK": _miktar(rng, urun),
                    "STHAR_NF": None,
                    "STHAR_TARIH": gun(),
                    "STHAR_HTUR": "D",
                    "FISNO": None,
                    "CARI_KODU": None,
                },
            )
        )

    for _ in range(rng.randint(6, 12)):
        caharlar.append(
            _row(
                cahar_ad,
                {
                    "CAHAR_ID": len(caharlar) + 1,
                    "CARI_KODU": rng.choice(caris)["CARI_KOD"],
                    "TARIH": gun(),
                    "BA": rng.choice(("B", "A")),
                    "TUTAR": _tutar(rng),
                    "FISNO": None,
                    "ACIKLAMA": rng.choice((None, "Havale ile tahsilat", "Emanet mal iadesi", "Fazla tahakkuk düzeltmesi")),
                },
            )
        )

    # Q09: teslim tarihi belirsiz satırlar; dört ayrı cari hem belirsiz hem belirli satır görür.
    for cari in rng.sample(alicilar, 4):
        birinci, ikinci = rng.sample(serbest, 2)
        siparis(cari, [(birinci, _miktar(rng, birinci), True), (ikinci, _miktar(rng, ikinci), False)])
    for _ in range(rng.randint(12, 18)):
        secim = rng.sample(serbest, rng.randint(1, min(4, len(serbest))))
        siparis(rng.choice(alicilar), [(u, _miktar(rng, u), rng.random() < 0.35) for u in secim])

    return faturalar, hareketler, caharlar, siparisler, sip_satirlari


def _cizgiler(rng: random.Random, urunler: list[dict], depolar: list[dict], adet: int | None = None) -> list[tuple]:
    secim = rng.sample(urunler, adet or rng.randint(1, min(4, len(urunler))))
    return [(urun, _miktar(rng, urun), rng.choice(depolar), None) for urun in secim]


def _miktar(rng: random.Random, urun: dict) -> float:
    if urun["OLCU_BR1"] == "KG":
        return round(rng.uniform(0.5, 35.0), 2)
    return float(rng.randint(1, 40))


def _fiyat(rng: random.Random, urun: dict) -> float:
    taban = urun["BIRIM_FIYAT"] or round(rng.uniform(10.0, 200.0), 2)
    return round(max(0.5, taban * rng.uniform(0.75, 1.15)), 2)


def _tutar(rng: random.Random) -> float:
    return round(rng.uniform(100.0, 25000.0), 2)


def _kdvli(tutar: float, urun: dict) -> float:
    return round(tutar * (1 + urun["KDV_ORANI"] / 100.0), 2)


def _teslim(rng: random.Random, tarih: str) -> str:
    gun = dt.date.fromisoformat(tarih) + dt.timedelta(days=rng.randint(3, 25))
    return min(gun, dt.date.fromisoformat(MONTHS[-1] + "-28")).isoformat()


def _kalan_satis(hareketler: list[dict], urun: dict) -> float:
    """İade edilebilecek kalan satış miktarı; iade hareketi satışın önüne geçmesin."""
    kalan = 0.0
    for hareket in hareketler:
        if hareket["STOK_KODU"] != urun["STOK_KODU"]:
            continue
        if hareket["STHAR_HTUR"] == "S":
            kalan += hareket["STHAR_GCMIK"]
        elif hareket["STHAR_HTUR"] == "I":
            kalan -= hareket["STHAR_GCMIK"]
    return round(kalan, 2)


def _some_indices(rng: random.Random, count: int, chance: float) -> set[int]:
    """Satır konumları; hiç boş kalmaz, böylece NULL/pasif haller her tohumda gerçekten vardır."""
    indices = {rng.randrange(count)}
    indices.update(i for i in range(count) if rng.random() < chance)
    return indices


def _row(names: list[str], values: dict) -> dict:
    """Satır anahtarları tam olarak tablonun şema sütunlarıdır, şema sırasıyla."""
    fark = set(values) ^ set(names)
    if fark:
        raise KeyError(f"şema ile uyuşmayan alanlar: {sorted(fark)}")
    return {name: values[name] for name in names}
