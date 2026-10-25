# Bilgin: Teknik Doküman

*ERP verisine Türkçe soru soran, yerel çalışan yapay zekâ veri analisti · sürüm 2 · 25 Ekim 2026 (gece) · hazırlayan: Claude (Eren'in projesi için)*

> Sürüm 2'de eklenenler: teknoloji yığını (dil, framework ve kütüphane sürümleri, modeller, altyapı) ve planlanan
> üç geliştirme turu (Run 6: kullanıcılar ve yeni veritabanı şablonu, Run 7: konuşma, başlangıç ekranı ve bağlantı
> yönetimi, Run 8: İngilizce ve Windows servisi). Run 6 bu doküman yazılırken geliştiriliyordu.

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

### 3.1 Teknoloji yığını

**Dil ve çalışma ortamı**

| Katman | Teknoloji | Sürüm | Not |
|---|---|---|---|
| Arka uç dili | Python | 3.11.9 (`requires-python >= 3.11`) | Paket adı `nl2sql`, komut satırı `python -m nl2sql` |
| Ön uç dili | JavaScript (JSX) | Node.js 24.21 ile derlenir | Çalışma anında Node gerekmez; derlenmiş dosyalar Python sunucusundan servis edilir |
| İşletim sistemi | Windows 11 (geliştirme), WSL2 Ubuntu 24.04 (model sunumunun bir kısmı) | | Run 8 ile Windows servisi |

**Arka uç kütüphaneleri** (sürümler `pyproject.toml`'da sabitlenmiş)

| Kütüphane | Sürüm | Ne için |
|---|---|---|
| sqlglot | 30.24.0 | SQL'i ağaç olarak çözümleme: politika (tek SELECT, izin listesi, TOP, kişisel veri filtresi), T-SQL → SQLite çevirisi, kolon izi (maskeleme) |
| FastAPI | 0.162.0 | Web API (`/api/ask`, `/api/replay`, kurallar, dışa aktarma, sağlık) |
| Uvicorn | 0.54.0 | API sunucusu (yalnız 127.0.0.1) |
| openai (Python SDK) | 3.37.0 | Yerel modellerin OpenAI uyumlu uç noktalarına istemci (bulut değil: Strata, Unsloth Studio, llama.cpp) |
| pyodbc | 5.3.0 | SQL Server bağlantısı (ODBC Driver 17/18) |
| openpyxl | 3.1.5 | Excel: şema haritası içe aktarma, şablon üretimi (Run 6), Excel dışa aktarma |
| Standart kütüphane | | `sqlite3` (3.45.1) uygulama veritabanı ve test veritabanları; `hashlib.scrypt` parola hash'i (Run 6); `ctypes` + DPAPI parola şifreleme (Run 7) |
| pytest / httpx | 9.1.1 / 0.28.1 | Testler ve API testleri (FastAPI TestClient) |

Bilinçli olarak **eklenmeyenler**: ORM, vektör veritabanı (LanceDB vb.), LangChain türü çerçeveler, `python-multipart`.
Vektör araması birkaç yüz belgede saf Python ile yapılıyor; `VectorStore` arayüzü ileride değiştirilebilsin diye var.

**Ön uç kütüphaneleri** (`web/package.json`)

| Kütüphane | Sürüm | Ne için |
|---|---|---|
| React / React DOM | 19.3.1 | Arayüz bileşenleri |
| ECharts | 6.1.0 | Grafikler (grafik türünü ve verisini Python tarafı seçer, ECharts yalnız çizer) |
| Vite | 8.3.5 | Derleme; çıktı `nl2sql/web/static` |
| Vitest | 5.0.5 | Ön uç birim testleri |

Arayüz dış URL kullanmaz (yazı tipi, CDN, analitik yok); bir test bunu derlenmiş dosyada kontrol eder.

**Modeller** (hepsi yerel)

| Rol | Model | Sunum | Bağlam |
|---|---|---|---|
| Geliştirme / ana model | Qwen3.8-Flash-Next, UD-IQ4_XS | Strata (llama.cpp tabanlı, OpenAI + Anthropic uyumlu API, `127.0.0.1:8080`) | 256K |
| Müşteri kutusu adayı | Qwen3.8-27B, UD-Q4_K_XL (~17,6 GB) | Unsloth Studio (WSL2, `:8888`) | 16K / 24K denendi |
| Gömme (RAG) | EmbeddingGemma-300M, Q8_0 | llama.cpp `llama-server --embedding` (CPU, `:8891`) | — |

Gömme tarafında ürün hedefi MIT lisanslı bir model (bge-m3); EmbeddingGemma Gemma kullanım koşullarına tabidir.
Testlerde gerçek model hiç çağrılmaz: sahte model (`--llm fake`) altın SQL'i oynatır, sahte gömücü deterministiktir.

**Veritabanları**

| Veritabanı | Kullanım |
|---|---|
| Microsoft SQL Server 2022 Express | Gerçek WideWorldImporters; müşteri ERP'leri bu sınıfta. Bağlantı ODBC Driver 18, `ApplicationIntent=ReadOnly`, salt-okunur giriş |
| SQLite | Sentetik ERP ve WWI kopyası (testler ve demo), uygulamanın kendi verisi (kullanıcılar, oturumlar, kayıtlı sorular, konuşmalar, bağlantılar) |

**Geliştirme ve doğrulama araçları**

| Araç | Ne için |
|---|---|
| Hibrit orkestratör (Python, `local-agent-stack/hybrid`) | Plan → görev → kabul komutu → review döngüsü; test bekçisi, proje geneli kontroller, run zinciri |
| Claude Code CLI | Görevleri yazan yerel modelin çalıştığı araç ortamı; bulut Claude plan ve review'da |
| Playwright 1.64 + Microsoft Edge (headless) | Görsel kontrol: ekran görüntüleri, kullanıcı akışları, PDF üretimi |
| WinSW (MIT) | Run 8: Windows servis sarmalayıcısı, sürüm ve SHA-256 sabit |

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
| 6 | Kullanıcılar ve roller, login, yeni veritabanı şablonu | 35 görev planlandı (T223-T257), geliştiriliyor |
| 7 | Konuşma, başlangıç ekranı, bağlantı yönetimi | planlandı |
| 8 | İngilizce, Windows servisi | planlandı |

Run 1-5'te 222 görev kapandı; test sayısı **4215**, hepsi yeşil. Gerçek veritabanı bağlantısı ve sonrasındaki
düzeltmeler (COUNT(*), ondalık JSON, cevapta kolon adı, geçmişten açma) elle yapıldı.

## 10. Planlanan geliştirmeler (Run 6-8)

Üç tur zincir halinde, sırayla geliştiriliyor. Her turun ayrıntılı tanımı repodaki `PROJECT_BRIEF_RUN6.md`,
`PROJECT_BRIEF_RUN7.md`, `PROJECT_BRIEF_RUN8.md` dosyalarında.

### 10.1 Run 6 - Kullanıcılar, roller ve yeni veritabanı şablonu

- **Giriş ve oturum:** kullanıcılar uygulamanın kendi SQLite dosyasında; parolalar standart kütüphanenin scrypt'iyle
  hash'lenir (yeni bağımlılık yok). Oturum çerezi HttpOnly ve SameSite=Strict; 5 hatalı denemede 15 dakika kilit;
  "kullanıcı yok" ve "parola yanlış" aynı mesajı verir. İlk yönetici komut satırından, parola gizli yazılarak açılır;
  test için bir ortam değişkeniyle geliştirme yöneticisi kendiliğinden açılabilir (parola kodda ve repoda yok).
- **Her adres login'e gider:** hangi adresten girilirse girilsin oturum yoksa login ekranı açılır, uygulamanın hiçbir
  parçası görünmez; giriş sonrası istenen sayfaya dönülür; oturum yarıda düşerse login'e dönüş ve aynı sayfaya geri.
- **Roller:** `user` soru sorar, kendi geçmişini görür, kaydeder, dışa aktarır, iş kurallarını salt-okunur görür.
  `admin` ayrıca iş kurallarını ve kullanıcıları yönetir, yeni veritabanı tanıtır. Kontrol sunucuda yapılır; tablo
  halindeki bir test her API yolunu üç durumla dener.
- **Yeni veritabanını Excel şablonuyla tanıtmak:** admin boş şablonu indirir (Nasıl doldurulur, Veri kümesi, Tablolar,
  Kolonlar, İş kuralları ve tek tablonun doldurulmuş hali olan **Örnek** sayfası) ya da bağlantı varsa yapısı
  veritabanından doldurulmuş şablonu. Doldurup yükler; önce hiçbir şey yazmadan bir kontrol raporu gelir; "Oluştur"
  ile yeni veri kümesi, salt-okunur login betiği ve RAG indeksi kendiliğinden kurulur; admin aktif veri kümesini ona
  geçirir. Var olan veri kümelerine hiçbir yükleme dokunmaz.

### 10.2 Run 7 - Konuşma, başlangıç ekranı ve bağlantı yönetimi

- **Ardışık soru-cevap:** "Son satışın tutarı ne?" → "Bu müşteriye başka ne sattık?" → "Bunlardan hangisi en çok
  ciro yaptı?"; raporu düzenleme: "Sadece Texas", "Geçen yılla karşılaştır", "Grafiği çubuk yap". Model son üç turun
  sorusunu, SQL'ini ve maskelenmiş en fazla 5 satırını görür; tam sonuç saklanmaz. Devam cevabının kanıtında nasıl
  okunduğu yazar ("Önceki cevaptan: müşteri 832"). Önceki turun bir sayısı yeni cevaba kopyalanamaz. Grafik türü
  değişikliği modele gitmez. Ölçüm: gerçek WWI'de 2-3 soruluk konuşma zincirleri.
- **İş rolüne göre başlangıç ekranı:** kullanıcının iş rolü (Satış, Satın alma, Muhasebe, Yönetim, Genel) yetki
  rolünden ayrıdır ve admin tarafından atanır. Girişte o role ait hazır soru kartları gelir: sayı, küçük grafik ya da
  tablo. Kartlar modele gitmez, admin'in onayladığı sabit SQL'i salt-okunur çalıştırır; sonuçlar 5 dakika önbellekte
  tutulur. Karta tıklayınca konuşma oradan devam eder. Yeni bir veritabanında Bilgin her rol için soru önerir;
  onaylanmayan hiçbir öneri çalışmaz. BI panosu değildir: her kart Bilgin'in cevaplayıp sürdürebileceği bir sorudur.
- **Bağlantılar admin panelinden:** her veri kümesinin kendi bağlantısı; veri kümesi değişince bağlantı da değişir.
  Parola DPAPI ile şifreli saklanır, hiçbir API geri döndürmez, loglara girmez. Kaydetmeden önce yetki kilidi:
  sysadmin, db_owner ya da yazma yetkili bir login reddedilir. Ortam değişkeni varsa önceliklidir.
- **Bağlantı durumu herkese:** header'da yeşil / kırmızı / gri "Veritabanı" göstergesi; arka planda dakikada bir
  kontrol; bağlantı yokken soru modeli beklemeden hemen "şu an cevap üretilemiyor" der.

### 10.3 Run 8 - İngilizce ve Windows servisi

- **Programın İngilizcesi:** arayüz, API mesajları, cevap cümlesi, netleştirme, uyarılar, grafik etiketleri, komut
  satırı ve README. Kullanıcı dili seçer (TR | EN); cevabın dili sorunun dilini izler. Sayı biçimi dile göre değişir
  (`1.234,56` / `1,234.56`) ve sayı kontrolü iki biçimi de tanır. Veri çevrilmez: tablo değerleri ve şema açıklamaları
  yazıldığı gibi kalır. Gerçek WWI için İngilizce altın soru seti eklenir.
- **Şablon programın dilinde:** İngilizce kullanıcıya İngilizce şablon (sayfa adları, başlıklar, Y/N listeleri,
  örnek); iki şablon da hangi dilde olursa olsun içeri alınır ve aynı şemayı üretir.
- **Windows servisi:** tek script'le kurulum (yönetici olarak), Windows'la birlikte açılır, çökerse yeniden başlar,
  sanal hesapla (`NT SERVICE\Bilgin`) çalışır, verisi `C:\ProgramData\Bilgin` altında, logları boyuta göre döner.
  Sarmalayıcı WinSW (MIT, sürüm ve SHA-256 sabit). Güncelleme ve kaldırma script'leri; her adımı değiştirmeden
  gösteren `-WhatIf`. Servis yine yalnız yerel makineden erişilir.

## 11. Açık işler (Run 6-8 dışında)

1. **Q01 ve Q25'i netleştirmek.** Soru metni tek okumaya indirilecek; gerçek veride hedef 26/26.
2. **Kendi ERP verisinde deneme.** Demo verisiyle dolu bir ERP veritabanı, Run 6 şablonuyla tanıtma, salt-okunur
   giriş, iş kuralları ve 20-30 gerçek kullanıcı sorusundan bir altın set.
3. **Ölçüm tekrarı.** 27B için daha fazla tekrar ve 16 GB VRAM'e sığan daha düşük bit seçeneğinin ölçümü.
4. **Lisans kontrolü.** Ticari dağıtımdan önce model ve gömme modelinin lisansları; gömme için MIT lisanslı modele geçiş.
5. **Ağa açma.** Bilgin şimdilik yalnız yerel makineden erişiliyor; birden çok bilgisayardan kullanım TLS ve ağ
   güvenliği ayrıca ele alınınca.
