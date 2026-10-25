# Bilgin: Teknik Doküman

*ERP verisine Türkçe soru soran, yerel çalışan yapay zekâ veri analisti · 25 Ekim 2026 · hazırlayan: Claude (Eren'in projesi için)*

---

## 1. Özet

Bilgin, bir ERP kullanıcısının SQL bilmeden Türkçe soru sorup kendi veritabanından cevap almasını sağlar. Soruyu
T-SQL'e çevirir, sorguyu **salt-okunur** çalıştırır, sonucu tablo, grafik ve doğal Türkçe bir cümleyle gösterir.
Her şey müşterinin kendi makinesinde çalışır; ne veri ne soru bir bulut servisine gider.

Bugünkü durum, tek cümleyle: Microsoft'un gerçek **WideWorldImporters** veritabanında (SQL Server, salt-okunur giriş)
26 iş sorusunun **24'ünü** doğru cevaplıyor, soru başına **~4 saniyede**. Bu sonuç hem 256K bağlamlı geliştirme
modelinde hem de 24 GB'lık bir müşteri kutusuna sığan **Qwen3.8-27B (16K bağlam)** modelinde aynı. Yanlış iki soru,
sorunun iki türlü okunabilmesinden geliyor, SQL becerisinden değil.

## 2. Problem ve yaklaşım

ERP'deki veri, onu soracak insanın erişemediği yerde durur: rapor bir IT talebine, talep günlere dönüşür. Genel amaçlı
"veriyle sohbet" araçları ise iki yerden tökezler: veriyi buluta taşırlar ve sayıyı modele hesaplatırlar.

Bilgin'in dört ilkesi bu iki sorunun cevabı:

| İlke | Ne demek |
|---|---|
| **Veri evde kalır** | Model, veritabanı ve arayüz müşterinin makinesinde. Bulut LLM API'si yok. |
| **SQL tek doğruluk kaynağı** | Her sayı veritabanında, SQL ile hesaplanır. Model sayı üretmez; cümledeki her sayı kodla doğrulanır. |
| **Model dil katmanıdır** | Model soruyu anlar, SQL'i yazar, sonucu anlatır. Toplam, oran, ortalama gibi hesaplar yapmaz. |
| **Güvenlik veritabanında** | Asıl sınır salt-okunur SQL girişi ve kolon bazlı DENY'dır; uygulama içi kontroller ikinci katmandır. |

## 3. Mimari

```
Soru (Türkçe)
  -> Ajan döngüsü (yerel LLM, araç çağrıları)
       araçlar: şema arama · tablo detayı · örnek değerler · SQL deneme · SQL gönderme · netleştirme sorusu
  -> Politika (sqlglot ağacı: tek SELECT, izin listesi, TOP sınırı, kişisel veri filtresi, kapalı kolon)
  -> Yürütücü (salt-okunur bağlantı, satır ve süre bütçesi) -> kişisel veri maskesi -> denetim kaydı
  -> Rapor: grafik seçimi (kod) + olgular (kod) + Türkçe anlatım (LLM) + sayı bekçisi (kod)
  -> Web arayüzü / komut satırı / JSON API
```

**Bağlam stratejisi.** İki mod var. `full_rules` tüm şemayı ve iş kurallarını modele verir; `rag` yalnızca ilgili
tabloları hibrit arama (yoğun vektör + BM25, RRF ile birleşik) ve join grafiğiyle getirir. Küçük şemada `full_rules`
daha hızlı, büyük şemada `rag` bağlamı küçültür. `auto` mod token bütçesine göre seçer.

**İş kuralları katmanı.** "Ciro", "net satış", "geciken teslimat" gibi terimlerin şirkete özgü tanımı ayrı bir kural
dosyasında durur: tanım, SQL ipucu, ilgili tablolar ve doğrulama işaretleri. Model bu tanımları okur; değerlendirme
de kuralın SQL'e gerçekten girip girmediğini işaretlerle kontrol eder.

**Rapor katmanı.** Sonuç tablosundan grafik türünü ve "en yüksek, toplam, değişim" gibi olguları kod çıkarır. Model
bunları 1-3 cümlelik Türkçe bir cevaba çevirir. Sayı bekçisi cümledeki her sayının sonuçta ya da olgularda birebir
geçtiğini doğrular; teknik kolon adı (`StateProvinceName`, `TOPLAM_CIRO` gibi) da reddedilir. Geçmeyen cümle bir kez
daha istenir, yine geçmezse koddan kurulan kalıp cümle gösterilir. Kullanıcıya doğrulanmamış bir sayı gitmez.

**Netleştirme.** Soru iki türlü okunabiliyorsa model cevap yerine seçenekli bir "Netleştirelim" kartı açabilir.
Gerçek veritabanı testinde bu kendiliğinden bir kez devreye girdi (bkz. 7).

**Arayüz.** React + ECharts, tamamen yerel (dış URL yok). Soru kutusu, cevap kartı (cümle, uyarılar, tablo, grafik,
CSV/Excel indirme, "nasıl hesapladım" bölümü), kayıtlı sorular ve geçmiş, iş kuralı düzenleme ekranı, telefon
düzeni ve karanlık mod.

## 4. Güvenlik katmanları

| Katman | Ne yapar | Neden |
|---|---|---|
| **Salt-okunur SQL girişi** | Yalnız izin listesindeki tablolarda SELECT; kişisel veri ve kapalı kolonlarda kolon bazlı DENY; yordam çalıştırma ve tanım görme yok; bağlantı `ApplicationIntent=ReadOnly`. | Asıl sınır. Uygulama atlatılsa bile veritabanı reddeder. |
| **Politika (sqlglot)** | Tek SELECT, yazma/DDL yok, sistem şemaları yok, TOP sınırı, kişisel veri kolonunda filtre/sıralama yok. | Hatayı sorgu gitmeden yakalar ve modele *neden* yanlış olduğunu söyler. |
| **Kişisel veri maskesi** | Kimlik no, IBAN, telefon, ad soyad, maaş vb. sınıfına göre maskelenir; tek kişilik gruplarda toplam da maskelenir. | Sayısal özet serbest, kişiye ulaşan değer kapalı. |
| **Denetim kaydı** | Her sorgu, kaynağı ve maskelenen kolonların *adı* yazılır, değeri yazılmaz. | İz sürülebilirlik. |

Bağlantı dizesi yalnız ortam değişkeninde durur; kodda, yapılandırmada ve repoda yoktur.

## 5. Ölçüm yöntemi

Her veri kümesi bir **altın soru seti** taşır: Türkçe soru, doğru SQL, etiketler (tuzak, kural gerektiren, çok
tablolu, değer gerektiren). Değerlendirme modelin sonucunu altın SQL'in sonucuyla karşılaştırır; SQL metni değil,
**dönen satırlar** eşleşmeli. Tuzak soruları kasıtlıdır: faturalanmamış sipariş, kredi notu düşümü, geri sipariş,
teslimi onaylanmamış fatura, iki satın alma grubu, geç teslimat.

`eval --compare` modelleri ve modları aynı setle koşar, `--repeat N` her hücreyi N kez tekrarlayıp gürültüyü
(min-max) gösterir. Grafikler ve tablolar bu raporlardan **kodla** üretilir.

## 6. Sonuçlar

### 6.1 Gerçek WideWorldImporters (SQL Server, 26 soru, 2 tekrar)

| Model | Mod | Doğru (ort.) | min-max | Cevap % | sn/soru | Tepe istem | Taşma |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Flash-Next (Strata) | full_rules | 24.0/26 | 24-24 | 100 | 4.3 | 9,088 | 0 |
| Flash-Next (Strata) | rag | 24.5/26 | 24-25 | 100 | 9.9 | 6,760 | 0 |
| Qwen3.8-27B 24K | full_rules | 24.0/26 | 24-24 | 100 | 4.4 | 9,084 | 0 |
| Qwen3.8-27B 24K | rag | 23.0/26 | 23-23 | 100 | 7.8 | 5,024 | 0 |
| Qwen3.8-27B 16K | full_rules | 24.0/26 | 24-24 | 100 | 4.1 | 9,086 | 0 |
| Qwen3.8-27B 16K | rag | 23.0/26 | 23-23 | 100 | 7.7 | 5,309 | 0 |

![Doğru cevap](img/real-compare/score.png)

![Soru başına süre](img/real-compare/speed.png)

![Tepe istem boyutu](img/real-compare/context.png)

**Okuma:**
- `full_rules` modunda üç model aynı: 24/26, 4,1-4,4 sn. 27B'yi 16K yerine 24K bağlamla çalıştırmak bir şey katmıyor.
- `rag` modunda 27B bir soru geride: müşteri bakiyesi sorusunu (Q10) her tekrarda yanlış yaptı.
- Yedi tuzak sorusunun yedisi de doğru.
- Yanlış iki soru (Q01, Q25) bütün modellerde aynı ve ikisi de **soru belirsizliği**:
  - Q01: "her ülkenin şehir sayısı" şehri olmayan 189 ülkeyi de kapsıyor gibi okunuyor; modeller 0'lı satırları da
    döndürüyor, altın cevap yalnız ABD'yi istiyor.
  - Q25: "faturanın kesildiği müşteri" fatura müşterisi mi sipariş müşterisi mi, belli değil. Soru fatura müşterisi
    açıkça yazılarak sorulduğunda model altın cevapla aynı sonucu veriyor.

**Donanım önerisi.** 24 GB VRAM'li bir müşteri kutusu için: **Qwen3.8-27B, 4-bit, 16K bağlam, `full_rules`**.
Bu boyuttaki bir şemada geliştirme modeliyle aynı doğruluk ve hız. Şema pencereye sığmayacak kadar büyürse `rag`'a
geçilir; bedeli soru başına ~3,5 saniye ve bu sette bir soruluk doğruluk. (Modelin ve gömme modelinin lisansı ticari
kullanımdan önce ayrıca doğrulanmalı; gömme tarafında ürün hedefi MIT lisanslı bir model.)

### 6.2 Sentetik ERP (83 tablo, 40 soru, 15 iş kuralı)

Türk ERP'lerine benzeyen kodlu tablo adlarıyla kurgusal bir veritabanı; çoğu tablo modeli şaşırtmak için konmuş boş
tablolardır. Geliştirme modeliyle tek koşum:

| Mod | Doğru | Tepe istem |
|---|---:|---:|
| full (şema, kural yok) | 23/40 | 23,6K |
| full_rules | **31/40** | 26,0K |
| rag | **30/40** | **6,5K** |

En büyük kazanç modelden değil **iş kuralları katmanından** geldi: aynı model, kurallarla 8 soru daha fazla doğru
yaptı. `rag` aynı doğruluğa dört kat daha küçük bağlamla yaklaşıyor.

## 7. Arayüzden örnekler (gerçek veritabanı)

Cümleler arayüzün döndürdüğü haliyle, değiştirilmeden:

| Soru | Model | Cevap | Süre |
|---|---|---|---|
| Kredi notları hariç, faturalanan satışların KDV hariç toplam cirosu ne kadardır? | 27B 16K | Kredi notları hariç faturalanan satışların KDV hariç toplam cirosu 172.261.341,2'dir. | 9,8 sn |
| Bu yıl (2016) en çok ciro yapan 5 stok kalemi; adı ve cirosu nedir? | Flash-Next | Bu yıl en çok ciro yapan 5 stok kalemi Air cushion machine (Blue) 1.441.341, 10 mm Anti static bubble wrap (Blue) 50m 946.440, 20 mm Double sided bubble wrap 50m 853.200, 32 mm Anti static bubble wrap (Blue) 50m 750.750 ve 32 mm Double sided bubble wrap 50m 744.800 olarak sıralandı. | 24,4 sn |
| Kredi notları hariç, her tedarikçinin ürünlerinden elde edilen toplam ciro tedarikçi adına göre nedir? | 27B 24K | Kredi notları hariç tutulduğunda tedarikçi başına toplam ciro şöyle görünüyor: Litware, Inc. 100.664.171,55; Fabrikam, Inc. 46.441.244; Northwind Electric Cars 14.802.215; The Phone Company 5.763.945,45; Graphic Design Institute 3.172.130; A Datum Corporation 1.142.515,2 ve Contoso, Ltd. 275.120. | 18,4 sn |

![Arayüz: en çok ciro yapan 5 stok kalemi (Flash-Next)](img/real-shots/flash-next-Q12.png)

## 8. Gerçek veritabanının öğrettikleri

Sentetik veride görünmeyen, gerçek SQL Server'a ilk bağlantıda çıkan bulgular. Her biri bugün düzeltildi ya da
kayıt altında:

1. **Modelin hafızasından yazılan şema güvenilmez.** İlk WWI şeması belgelerden ve modelin bilgisinden yazılmıştı:
   175 kolonun 44'ü gerçek veritabanında yoktu. Gerçek şema, veritabanının kendi meta verisinden ve Microsoft'un
   kolon açıklamalarından yeniden kuruldu. Ders: müşteri veritabanında şema **her zaman canlı veritabanından okunur**.
2. **Bir kolon adı iş tanımını taşımayabilir.** Gerçek veride fatura satırının `ExtendedPrice`'ı KDV **dahil**.
   KDV hariç ciro `ExtendedPrice - TaxAmount`. Kural katmanı tam bunun için var; model bu tuzağı doğru geçti.
3. **Kolon bazlı DENY `COUNT(*)`'ı kırar.** Kişisel veri kolonları kapatılmış bir tabloda SQL Server `COUNT(*)`'ı
   reddediyor. Politika katmanı artık bu tablolarda `COUNT(*)`'ı anahtar kolonla sayıma çeviriyor; aynı satırları sayar.
4. **Satır düzeyi güvenlik sessizce sıfır döndürür.** Örnek veritabanındaki bir satış bölgesi kuralı salt-okunur
   girişe 0 müşteri gösteriyordu. Hata vermediği için fark etmesi zor; kurulum adımlarına eklendi.
5. **Gerçek tutarlar ondalık tipte gelir.** JSON çıktısı `Decimal` tipinde çöküyordu; düzeltildi.
6. **Cevap cümlesi teknik dil konuşmamalı.** İlk cevaplarda kolon adları geçiyordu ("StateProvinceName olarak
   Texas…"). Anlatım kuralları değişti ve kod bu adları cümleden reddediyor.

## 9. Geliştirme yöntemi

Proje "bulut beyin, yerel eller" düzeniyle yazıldı. Bulut model planı ve görev listesini yazar, kilometre taşı
sonlarında kodu gözden geçirir. Görevleri yerel model (Qwen3.8-Flash-Next) yazar ve test eder. Deterministik bir
orkestratör döngüyü yönetir: kabul komutu, var olan testlerin zayıflatılmasını engelleyen bekçi, proje geneli test ve
smoke kontrolleri, ekran görüntüsüyle görsel inceleme.

| Run | Kapsam | Sonuç |
|---|---|---|
| 1 | Test veritabanı, politika, yürütücü, ajan, ölçüm, komut satırı | 30/30 görev ilk denemede |
| 2 | 83 tablo, iş kuralları, 40 soru, hibrit arama, join grafiği, A/B ölçüm | 76 görev |
| 3 | Excel eşleme, canlı şema okuma ve fark raporu, kişisel veri maskesi, salt-okunur giriş betiği, `auto` mod | 44 görev, 38'i ilk denemede |
| 4 | Veri kümesi yapısı, WWI, model profilleri, bağlam bütçesi, model karşılaştırma | 39 görev, 37'si ilk denemede |
| 5 | Soru-cevap oturumu, rapor katmanı, netleştirme, tablo özetleri, web arayüzü, kural ekranı | T163-T222 |

Toplam 222 görev kapandı; test sayısı **4210**, hepsi yeşil. Gerçek veritabanı bağlantısı ve sonrasındaki düzeltmeler
elle yapıldı.

## 10. Açık işler

1. **Q01 ve Q25'i netleştirmek.** Soru metni tek okumaya indirilecek; gerçek veride hedef 26/26.
2. **Kendi ERP verisinde deneme.** Demo verisiyle dolu bir ERP veritabanı, salt-okunur giriş, canlı şema okuma,
   Excel açıklamaları ve 20-30 gerçek kullanıcı sorusu.
3. **Ölçüm tekrarı.** 27B için daha fazla tekrar ve 16 GB VRAM'e sığan daha düşük bit seçeneğinin ölçümü.
4. **Lisans kontrolü.** Ticari dağıtımdan önce model ve gömme modelinin lisansları.
