# Bilgin: Proje Dokümanı

*BusAIness ürünü · çalışma adı NL2SQL · sürüm 0.3 · 24 Ekim 2026 · hazırlayan: Eren*

---

## 1. Özet

Bilgin, ERP kullanıcılarının SQL bilmeden, Türkçe soru sorarak kendi veritabanlarından rapor almasını sağlayan,
**müşterinin kendi sunucusunda çalışan** bir yapay zekâ veri analistidir. Soruyu SQL'e çevirir, sorguyu salt-okunur
çalıştırır ve sonucu gösterir. Veri şirketin dışına hiç çıkmaz.

> *"Bilgin sende kalır."*

## 2. Problem

- KOBİ ve orta ölçekli şirketlerde rapor ihtiyacı bir kuyruğa dönüşür. Basit bir soru ("Eylül'de en çok satan
  5 ürün?") için bile IT'ye ya da ERP danışmanına iş açılır ve cevap günler sürer.
- Bulut tabanlı BI/AI araçları (Power BI Copilot, Tableau vb.) önce bir veri modeli ister ve veriyi buluta taşır.
  KVKK'ya hassas şirketler için bu bir engeldir.
- ERP şemaları şifrelidir (`STHAR_GCKOD`, `TBLFATUIRS`). Genel amaçlı bir LLM bunları ve şirketin iş kurallarını
  ("net satış iadeyi düşer mi?") bilmez.

## 3. Amaç

ERP verisine **Türkçe soru → doğru sayı** yolunu, verinin şirketten çıkmadığı ve sistemin veriyi hiçbir koşulda
değiştiremediği bir şekilde dakikalara indirmek.

## 4. Hedefler

| # | Hedef | Ölçüt | Durum |
|---|---|---|---|
| H1 | Yerel bir model doğru SQL yazabiliyor mu? (Faz 0 eleme kapısı) | 10 altın soruda ≥ 7/10 execution accuracy | ✅ 7/10 (Run 1) |
| H2 | Büyük, kafa karıştırıcı bir şemada doğruluk | 83 tablo, 40 soru; şema + iş kurallarıyla ≥ %75 | ✅ 31/40 = %78 (Run 2) |
| H3 | Küçük donanımda çalışabilme | 16-24K context bütçesine sığmak | ✅ RAG modu: 6,5K token (tam şema 26K) |
| H4 | Müşteri şemasını elle yazmadan almak | Excel haritası ve/veya canlı DB'den otomatik şema; fark raporu | 🔄 Run 3 |
| H5 | Kişisel veriyi korumak | PII maskeleme; ≥ 20 atlatma denemesinin tamamı engelleniyor | 🔄 Run 3 |
| H6 | Kullanıcıya rapor | Web arayüzü; yazılı Türkçe yorum (number guard'lı); grafik | ⏳ Run 4 |
| H7 | Gerçek veride doğruluk | Netsis/Odoo kopyasında Eren'in 20-30 sorusu | ⏳ Run 3 sonrası |

## 5. Kapsam

**İçinde:** Doğal dilden T-SQL'e çeviri, agent döngüsü (şema arama, join yolu, örnek değer, çalıştır, düzelt), iş
kuralları, salt-okunur çalıştırma, güvenlik politikası, PII maskeleme, şema haritası içe aktarma (Excel + canlı DB),
ölçüm (eval) altyapısı, CLI; sonraki aşamada web arayüzü, grafik ve yazılı rapor.

**Dışında (şimdilik):** Veritabanına yazma (INSERT/UPDATE), dashboard/BI modelleme, model fine-tune, bulut LLM,
çok turlu sohbet hafızası, mobil.

## 6. Yöntem

### 6.1 Tasarım ilkeleri

1. **Deterministik çekirdek, LLM dil katmanı.** LLM sadece SQL yazar ya da eşleme önerir. Sayıları veritabanı
   hesaplar, dönüşümleri kod yapar. LLM hiçbir kritik sayının sahibi değildir.
2. **Veri evde kalır.** Model (llama.cpp / Strata), embedding (CPU'da llama-server) ve veritabanı aynı ağda çalışır.
   Bulut API'si yoktur.
3. **Sadece okuma.** Read-only login ve `ApplicationIntent=ReadOnly`. Asıl güvence DB seviyesindeki `DENY`'dir,
   sqlglot politikası ikinci katmandır.
4. **ERP'den bağımsız.** ERP'ye özgü bilgi koda gömülmez. Şema haritası, iş kuralları ve ERP profili
   (`profiles/netsis.json`) veri olarak yüklenir.
5. **Ölçmeden özellik yok.** Her değişiklik altın soru setinde ölçülür. RAG bile ancak sayıyla kazandığında kalır.

### 6.2 Mimari

```
Excel haritası ──(LLM eşleme önerir, kullanıcı onaylar, kod dönüştürür)──┐
Canlı DB ──introspect──────────────────────────────────────────────────┴─► schema.json + rules.json
                                                                                │ build-index
Soru ─► Agent döngüsü ─► LLM (yerel, OpenAI uyumlu)                       hibrit indeks + join grafiği
          │  araçlar: search_schema · search_rules · get_table_details ·
          │           find_join_path · sample_values · run_sql · submit_sql
          ▼
      Executor: politika (tek SELECT, izin listesi, TOP, PII filtreleri) → çalıştır → PII maskeleme → sonuç
```

- **Modlar:** `full_rules` (şema + kurallar prompt'ta; hızlı) ve `rag` (arama araçlarıyla; 4 kat az context).
  `auto` modu context bütçesine göre birini seçer.
- **Arama:** dense (embedding) + BM25 + RRF birleştirmesi, Türkçe harf katlama. Join yolları vektör aramayla değil,
  FK'ler ve ERP profilinden kurulan grafikte en kısa yolla bulunur.
- **İş kuralları:** "ciro", "net satış", "iade oranı" gibi terimlerin tanımı, eşanlamlıları ve SQL ipucu. Ölçümle
  ürünün en değerli katmanı olduğu görüldü.

### 6.3 Güvenlik katmanları

| Katman | Ne yapar |
|---|---|
| DB login | `db_datareader` + hassas tablo ve kolonlara `DENY` (üretilen script) |
| Politika (sqlglot, parse tree) | Tek SELECT; default-deny tablo listesi; `sys.*`, cross-db, `OPENROWSET`, `SELECT INTO`, TVF yasak; `TOP` zorunlu |
| PII | Lineage ile kaynak kolon takibi; TCKN, IBAN, maaş vb. maskelenir; çözülemeyen kolon tamamen maskelenir; PII ile filtreleme yasak |
| Denetim | Kim, hangi SQL, süre, satır sayısı. Sonuç satırları log'a yazılmaz |
| Test | 50+ kötü niyetli SQL ve 20+ PII atlatma vakası her değişiklikte koşar |

### 6.4 Ölçüm (eval) yöntemi

- **Sentetik Netsis benzeri test DB'si:** 83 tablo (21'i veri içeriyor, 62'si şaşırtmaca). Veriye bilerek tuzaklar
  konmuştur: iade, iptal fatura, çok depo, fan-out yapan join, NULL'lar, arşiv tablosu.
- **40 altın soru**, her biri iki yoldan doğrulanır: altın SQL'in sonucu bağımsız bir Python hesabıyla birebir
  tutmalıdır.
- **Execution accuracy:** sonuç kümeleri sıradan ve kolon adlarından bağımsız karşılaştırılır.
- **Ayrıca:** etiket bazında skor, retrieval recall@k (LLM'siz), context ve süre, tekrarlı koşu ile gürültü ölçümü.

### 6.5 Geliştirme yöntemi

Kod, MERGEN'in hibrit hattıyla yazılıyor. Claude (bulut) plan ve review yapıyor, yerel Qwen (Strata) kodluyor,
deterministik bir orkestratör görevleri, testleri ve bütçeyi yönetiyor. Her görevin kabul testi var, her milestone
sonunda tüm proje kontrol ediliyor. Run 3'te bulut limiti dolunca beyin rolünü de yerel model üstlendi; o run'da
33 görev ilk denemede geçti ve review'lar 6 gerçek hata buldu.

## 7. Mevcut durum (24 Ekim 2026)

| Run | Kapsam | Sonuç |
|---|---|---|
| 1 | Faz 0: test DB, politika, executor, agent, eval, CLI | 30/30 görev; Strata 7/10; hataların hepsi iş tanımı belirsizliğinden |
| 2 | Faz 2: 83 tablo, iş kuralları, 40 soru, hibrit arama, join grafiği, A/B eval | `full` 23/40 · `full_rules` **31/40** · `rag` **30/40** (6,5K token); 2144 test |
| 3 | Excel import, canlı şema + fark raporu, PII, login scripti, retrieval iyileştirme, `auto` mod | devam ediyor (115 görevden 99'u bitti) |

**Bulgular:**
- İş kuralları tek başına +8 soru kazandırdı (23 → 31). Ürünün hendeği bu katman.
- RAG skorda `full_rules` ile berabere, ama context'i 4 kat azaltıyor. Küçük donanım ve büyük şema için zorunlu.
- Retrieval henüz zayıf: recall@5 = 0,67, en çok çok tablolu join'lerde kaybediyor.

## 8. Yol haritası

1. **Run 3 tamamlanır** → testler, PII ve politika kontrolü.
2. **Altın soru incelemesi (Eren):** 40 sorunun niyeti ve iş tanımları.
3. **27B karşılaştırması:** aynı A/B eval, Qwen3.8-27B ile 16-24K context'te (müşteri kutusu senaryosu).
4. **Gerçek veri testi:** read-only login, Netsis/Odoo kopyası, Eren'in 20-30 sorusu.
5. **Run 4:** web arayüzü (soru → cevap → rapor), number guard'lı yazılı Türkçe yorum, grafik spec + ECharts,
   Excel/CSV dışa aktarma, iş kuralı tanımlama ekranı.
6. **Odoo profili ve demosu:** public vitrin ve ilk pazar.
7. **Topoloji C (sonra):** LLM kutusu + müşteri tarafında read-only runner ("o kutu senin DB'ne bağlanamaz").

## 9. Konumlandırma

**Bilgin bir BI ürünü değil; ERP için yerel AI veri analistidir.** BI'ın yerine geçmez, ERP'nin yanına takılır.

- **Hedef kitle:** BI ekibi olmayan şirketler. Patron, finans müdürü, satış ve depo sorumlusu.
- **Fark:** veri dışarı çıkmaz · ERP'yi ve iş kurallarını bilir · Türkçe · dakikalar içinde kurulur.
- **Kanal:** ERP iş ortakları ve danışmanlık projelerine eklenti.

## 10. Riskler

| Risk | Önlem |
|---|---|
| Yanlış ama hatasız sonuç | İş kuralları, join grafiği, SQL ve kullanılan tablolar her zaman gösterilir, altın setle sürekli ölçüm |
| Gerçek şemada doğruluk düşer | Excel açıklamaları + iş kuralları; `eval --schema skeleton` ile açıklamaların katkısı ölçülür |
| Ağır sorgu ERP'yi yavaşlatır | Timeout, `TOP`, read-only replika / AG secondary önerisi, RCSI kontrolü |
| Kişisel veri sızıntısı | DB `DENY` + lineage maskeleme + filtre yasağı + atlatma test seti |
| İşveren sözleşmesi (rekabet / IP) | Netsis/Logo tarafında satıştan önce sözleşme okunur; ilk pazar Odoo |
| Marka | "BusAIness Bilgin" olarak ana marka altında tescil; TÜBİTAK "Bilge" ile karışma riski kontrol edilecek |
| Donanım maliyeti | Mod otomatik seçimi; 16 / 24 / 32 GB kademeleri eval ile doğrulanır |

## 11. Açık kararlar

- Lisans modeli: kurulum başına mı, kullanıcı başına mı, abonelik mi?
- İlk müşteri profili ve LLM kutusunun kimin olacağı (müşteri donanımı mı, Bilgin kutusu mu).
- Embedding: EmbeddingGemma (geliştirme) yerine bge-m3 (MIT, ürün hedefi). Retrieval ölçümüyle karar verilecek.
- Python paket adı `nl2sql` mı kalacak, `bilgin` mi olacak.
