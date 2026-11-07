# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""T421: İngilizce soru Türkçe anlatılmış bir şemada aynı tablolara iniyor mu (PLAN R8-10).

Ölçüm `eval-retrieval`ın kendisi: wwi şeması + wwi kuralları + FakeEmbedder bellekte, altın
satırların `requires_tables`ı üzerinde hibrit geri çağırması, k=5, eş anlamlı genişletmesi
kapalı. Fark tek yerde: aynı yirmi altı sorunun iki dili iki ayrı kümede duruyor
(`golden.jsonl` / `golden_en.jsonl`). İddia İngilizcenin Türkçenin `%80`inden az olmaması —
şemanın ve indeksin Türkçe tarafı (tablo anahtar kelimeleri, kural eş anlamlıları) İngilizce
soruyu da taşıyor mu, sorusunun sayısal hali.

Veri değişikliği yok, ölçüm söylemedi: İngilizcenin kaçırdığı tablolar (Application.Countries,
Application.Cities, Warehouse.StockGroups) Türkçenin de kaçırdığı tablolar — dilin değil çok
tablolu bağın sorunu. Eş anlamlı listeleri ise o tabloların hiçbirini taşımıyor; İngilizce ad
eklenen kuralın genişletmesi ancak kendi tablosunu yukarı taşıyabilir. Denenen doc tarafı
(şemanın `keywords` alanına İngilizce ad) iki dilde de birden geri çağırmayı düşürdü: uzun doküman
BM25'te kısalıyor, yani İngilizce kelime kazanırken Türkçe kelime kaybediyor.
"""

from bilgin.datasets import load_dataset
from bilgin.eval import retrieval
from bilgin.index.embed import FakeEmbedder
from bilgin.index.search import build_search

# ASSUMPTION: eş anlamlı listesi `datasets/wwi/profile.json`da değil `rules.json`da (`synonyms_en`)
# - profile yalnız join çifti taşır; oraya synonym okumak kod değişikliği ister, ölçüm istemedi.
DATASET = "wwi"
K = 5
RATIO = 0.8

DS = load_dataset(DATASET)
SCHEMA = DS.schema()
SEARCH = build_search(SCHEMA, DS.rules(), FakeEmbedder())
TURKISH = retrieval.run_retrieval(SEARCH, DS.golden(), k=K)
ENGLISH = retrieval.run_retrieval(SEARCH, DS.golden("en"), k=K)
# Altın İngilizce satırın `source_id`si aynı sıradaki Türkçe satırdır (test_golden_en).
SOURCE = {line["id"]: line["source_id"] for line in DS.golden("en")}


def comparison() -> str:
    """Başarısızlığın gövdesi: soru başına bir satır, iki dilin sayısı ve İngilizcenin eksikleri."""
    turkish = {item["id"]: item for item in TURKISH["questions"]}
    lines = [
        "{} en={:.2f}  {} tr={:.2f}  eksik: {}".format(
            item["id"],
            item["hybrid"],
            SOURCE[item["id"]],
            turkish[SOURCE[item["id"]]]["hybrid"],
            ", ".join(item["missing"]["hybrid"]) or "-",
        )
        for item in ENGLISH["questions"]
    ]
    return "\n".join(lines)


# ------------------------------------------------------------------ iki dilin ölçümü yan yana


def test_english_questions_reach_their_tables_as_well_as_the_turkish_ones():
    english = ENGLISH["mean"]["hybrid"]
    turkish = TURKISH["mean"]["hybrid"]

    assert english >= RATIO * turkish, (
        f"İngiliz hibrit geri çağırması {english:.2f}, Türkçe {turkish:.2f}; "
        f"k={K}, küme {DATASET}, embedder {ENGLISH['embedder']}.\n{comparison()}"
    )


def test_the_two_measurements_are_the_same_measurement():
    """Oran boşluk bulmasın: aynı `k`, aynı sahte embedder, her İngilizce sorunun tablosu var."""
    assert ENGLISH["k"] == TURKISH["k"] == K
    assert ENGLISH["embedder"] == TURKISH["embedder"] == FakeEmbedder().id
    assert [item["id"] for item in ENGLISH["questions"]] == sorted(SOURCE)
    assert all(item["requires"] for item in ENGLISH["questions"]), "bulunacak tablosu olmayan soru"
