# Tablo özetleri kararı (R5-20)

Özetler aramaya katılmalı mı? Karar ölçümden önce verilmedi: tablo özetleri koleksiyonu
(`summary:<TABLO>`) tablo sırasıyla kaynaştırılınca geri çağırma gerçekten yükseliyor mu, iki
kümede birden yükseliyor mu — cevap ona göre verildi. Sayılar `FakeEmbedder` ile, bellekte kurulan
indeks üzerinden, altın soruların `requires_tables` listesi ölçüt alınarak koştu:

```
python -m nl2sql eval-retrieval --embed fake --summaries on --dataset synthetic_erp
python -m nl2sql eval-retrieval --embed fake --summaries on --dataset wwi
```

## Ölçüm (2026-10-24, k=5, FakeEmbedder)

| Küme | Soru | Özet | hybrid | bm25 | dense |
| --- | ---: | --- | ---: | ---: | ---: |
| synthetic_erp | 40 | yok | 0.55 | 0.63 | 0.49 |
| synthetic_erp | 40 | var | 0.63 | 0.63 | 0.63 |
| wwi | 26 | yok | 0.72 | 0.77 | 0.47 |
| wwi | 26 | var | 0.85 | 0.85 | 0.85 |

Özet satırının üç yöntemi aynı sayıyı taşıyor: özet bacağı aramanın kendi yöntemiyle değil
varsayılanıyla (hybrid) kaynaşıyor, yani `--summaries on` tek bir sıra üretiyor (bkz.
`eval/retrieval._hits`). Karar zaten hybrid'in hybrid'e karşılaştırmasıdır; bm25 ve dense
satırları özetin taban sıralarını yanına koymak için duruyor.

## Kural (PLAN R5-20, ölçümden önce sabitlendi)

`config.TABLE_SUMMARIES` = **True**, iki kümenin *ikisinde de* özetli hybrid recall@5 özetisiz
hybrid recall@5'ten az değilse. Ölçümü ya da özet metnini kararı çevirmek için ayarlamak yok.

## Sonuç

| Küme | Özetli hybrid | Özetisiz hybrid | Koşul |
| --- | ---: | ---: | --- |
| synthetic_erp | 0.63 | 0.55 | ✓ sağladı |
| wwi | 0.85 | 0.72 | ✓ sağladı |

İki kümede de koşul sağlandı → **`config.TABLE_SUMMARIES = True`**. `search_schema` özet bacağıyla
arıyor; `search_schema` cevabının ilk `SEARCH_K` satırı artık `HybridSearch.search_tables(
summaries=True)`dan geliyor, join komşuları onun ardına eklenmeye devam ediyor.
