"""Synthetic Netsis-like dataset; part 1 builds the master cards the transaction tables point at."""

from __future__ import annotations

import random

from nl2sql import config
from nl2sql.schema_map import doc

# ASSUMPTION: T03 is part 1, so generate() returns the five master tables only; T04 adds the invoice,
# movement and order tables on top of these same cards.

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


def generate(seed: int = config.SEED) -> dict[str, list[dict]]:
    """Dataset for one seed; the same seed always replays the same rows."""
    rng = random.Random(seed)
    columns = {table["name"]: [c["name"] for c in table["columns"]] for table in doc.load_schema()["tables"]}
    groups = _groups(rng, columns["TBLSTGRUP"])
    products = _products(rng, columns["TBLSTSABIT"], groups)
    depots = _depots(columns["TBLDEPO"])
    reps = _reps(rng, columns["TBLPLASIYER"])
    caris = _caris(rng, columns["TBLCASABIT"], reps)
    return {
        "TBLSTGRUP": groups,
        "TBLSTSABIT": products,
        "TBLDEPO": depots,
        "TBLPLASIYER": reps,
        "TBLCASABIT": caris,
    }


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
