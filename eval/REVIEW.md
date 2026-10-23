# Golden sorular — niyet incelemesi

- Soru: 40; her sorunun altında bir `[ ] niyet doğru` kutusu var.
- Doğrular `eval.reference.REFERENCES` üzerinden `generate(42)` verisiyle hesaplanır.

## Etiket sayıları

| Etiket | Soru |
| --- | ---: |
| needs_rule | 35 |
| multi_join | 15 |
| needs_values | 11 |
| distractor | 10 |
| archive | 6 |
| trap:alici_satici | 1 |
| trap:cok_depo | 1 |
| trap:cok_fiyat | 1 |
| trap:fan_out | 1 |
| trap:faturasiz_hareket | 1 |
| trap:iade | 1 |
| trap:iptal | 1 |
| trap:kod_gckod | 1 |
| trap:null_teslim | 1 |

## Sorular

### Q01 — Ankara'da faaliyet gösteren alıcı carilerin kodu ve ünvanı nedir?

- Etiketler: `needs_rule`, `needs_values`
- Kurallar: `alici`
- Tablolar: `TBLCASABIT`
- Sıra: önemsiz
- Tuzak: yok
- Not: Tuzak yok; tek incelik CARI_TIP='H' olanların da alıcı sayılması. IL büyük harfle yazılır.

```sql
SELECT CARI_KOD, CARI_ISIM FROM TBLCASABIT WHERE IL = 'ANKARA' AND CARI_TIP IN ('A', 'H') ORDER BY CARI_KOD
```

Doğru yanıt (1 satır):

```text
CARI_KOD | CARI_ISIM         
-------- + ------------------
CAR00021 | Şimşek Market A.Ş.
```

- [ ] niyet doğru

### Q02 — Eylül 2026'da en çok satan 5 ürün hangileri; kodu, adı ve toplam satış miktarı nedir?

- Etiketler: `trap:cok_depo`
- Kurallar: —
- Tablolar: `TBLSTHAR`, `TBLSTSABIT`
- Sıra: korunur
- Tuzak: cok_depo
- Not: Aynı ürün birden çok depodan çıkabilir; gruplama depoyu içermez. Eşitlik durumunda ürün kodu sıralamayı deterministik yapar.

```sql
SELECT TOP 5 s.STOK_KODU, t.STOK_ADI, SUM(s.STHAR_GCMIK) AS SATIS_MIKTARI FROM TBLSTHAR s JOIN TBLSTSABIT t ON t.STOK_KODU = s.STOK_KODU WHERE s.STHAR_HTUR = 'S' AND s.STHAR_TARIH >= '2026-09-01' AND s.STHAR_TARIH < '2026-10-01' GROUP BY s.STOK_KODU, t.STOK_ADI ORDER BY SATIS_MIKTARI DESC, s.STOK_KODU
```

Doğru yanıt (5 satır):

```text
STOK_KODU | STOK_ADI              | SATIS_MIKTARI
--------- + --------------------- + -------------
STK0013   | Kakaolu Bisküvi 500 g |        160,00
STK0016   | Domates Salçası 700 g |        148,00
STK0005   | Toz Şeker 5 kg        |        141,00
STK0010   | Yumuşatıcı 1 L        |        139,00
STK0015   | Nohut 1 kg            |        119,56
```

- [ ] niyet doğru

### Q03 — Geçen ay satış hareketlerinin net fiyat üzerinden toplam cirosu (KDV hariç) ne kadar?

- Etiketler: `trap:cok_fiyat`, `needs_rule`
- Kurallar: `ciro`
- Tablolar: `TBLSTHAR`
- Sıra: önemsiz
- Tuzak: cok_fiyat
- Not: AS_OF 2026-09-30 için geçen ay Ağustos 2026. Ciro hareketin net fiyatından (STHAR_NF) hesaplanır; kart fiyatı aynı üründe birkaç farklı fiyatı temsil edemez.

```sql
SELECT SUM(s.STHAR_GCMIK * s.STHAR_NF) AS NET_CIRO FROM TBLSTHAR s WHERE s.STHAR_HTUR = 'S' AND s.STHAR_TARIH >= '2026-08-01' AND s.STHAR_TARIH < '2026-09-01'
```

Doğru yanıt (1 satır):

```text
 NET_CIRO
---------
96.516,67
```

- [ ] niyet doğru

### Q04 — Eylül 2026'da her plasiyerin carilerine ait iptal edilmemiş satış faturalarının genel toplamı ne kadar?

- Etiketler: `trap:iptal`, `needs_rule`, `multi_join`
- Kurallar: `plasiyersiz_haric`, `iptal_haric`
- Tablolar: `TBLFATUIRS`, `TBLCASABIT`, `TBLPLASIYER`
- Sıra: önemsiz
- Tuzak: iptal
- Not: IPTAL='E' faturalar hiçbir toplama girmez. Plasiyersiz cariler INNER JOIN ile doğal olarak düşer.

```sql
SELECT p.PLASIYER_KODU, p.AD_SOYAD, SUM(f.GENELTOPLAM) AS FATURA_TOPLAMI FROM TBLFATUIRS f JOIN TBLCASABIT c ON c.CARI_KOD = f.CARI_KODU JOIN TBLPLASIYER p ON p.PLASIYER_KODU = c.PLASIYER_KODU WHERE f.FTIRSIP = 1 AND f.IPTAL = 'H' AND f.TARIH >= '2026-09-01' AND f.TARIH < '2026-10-01' GROUP BY p.PLASIYER_KODU, p.AD_SOYAD ORDER BY p.PLASIYER_KODU
```

Doğru yanıt (4 satır):

```text
PLASIYER_KODU | AD_SOYAD    | FATURA_TOPLAMI
------------- + ----------- + --------------
PLS001        | Emine Aslan |      28.018,64
PLS002        | Ayşe Demir  |      27.568,44
PLS004        | Fatma Şahin |      73.145,40
PLS006        | Elif Koç    |      13.733,05
```

- [ ] niyet doğru

### Q05 — Ağustos 2026'da her ürünün net satış miktarı kaç (satışlardan iadeler düşülmüş)?

- Etiketler: `trap:iade`
- Kurallar: —
- Tablolar: `TBLSTHAR`
- Sıra: önemsiz
- Tuzak: iade
- Not: Satış iadesi (STHAR_HTUR='I') giriş yönüdür ama satıştan düşülür. Alış/transfer/sayım hareketleri net satışa girmez.

```sql
SELECT STOK_KODU, SUM(CASE WHEN STHAR_HTUR = 'S' THEN STHAR_GCMIK ELSE -STHAR_GCMIK END) AS NET_MIKTAR FROM TBLSTHAR WHERE STHAR_HTUR IN ('S', 'I') AND STHAR_TARIH >= '2026-08-01' AND STHAR_TARIH < '2026-09-01' GROUP BY STOK_KODU ORDER BY STOK_KODU
```

Doğru yanıtın ilk 5 satırı (toplam 12 satır):

```text
STOK_KODU | NET_MIKTAR
--------- + ----------
STK0002   |      20,00
STK0005   |      80,00
STK0008   |      12,67
STK0009   |      62,74
STK0010   |      53,00
```

- [ ] niyet doğru

### Q06 — Temmuz 2026'da en az bir stok hareketi olan iptal edilmemiş faturaların GENELTOPLAM toplamı ne kadar?

- Etiketler: `trap:fan_out`, `needs_rule`
- Kurallar: `iptal_haric`
- Tablolar: `TBLFATUIRS`, `TBLSTHAR`
- Sıra: önemsiz
- Tuzak: fan_out
- Not: Başlık tutarı satır sayısıyla çarpılmaması için satırla JOIN yerine EXISTS kullanılır; çok satırlı fatura bir kez sayılır.

```sql
SELECT SUM(f.GENELTOPLAM) AS FATURA_TOPLAMI FROM TBLFATUIRS f WHERE f.IPTAL = 'H' AND f.TARIH >= '2026-07-01' AND f.TARIH < '2026-08-01' AND EXISTS (SELECT 1 FROM TBLSTHAR s WHERE s.FISNO = f.FATIRS_NO)
```

Doğru yanıt (1 satır):

```text
FATURA_TOPLAMI
--------------
    125.694,39
```

- [ ] niyet doğru

### Q07 — Her depoya toplam kaç birim giriş yapıldı?

- Etiketler: `trap:faturasiz_hareket`
- Kurallar: —
- Tablolar: `TBLSTHAR`
- Sıra: önemsiz
- Tuzak: faturasiz_hareket
- Not: Transfer ve sayım girişlerinin FISNO'su NULL olduğu için faturayla INNER JOIN bu hareketleri sessizce düşürür.

```sql
SELECT DEPO_KODU, SUM(STHAR_GCMIK) AS GIRIS_MIKTARI FROM TBLSTHAR WHERE STHAR_GCKOD = 'G' GROUP BY DEPO_KODU ORDER BY DEPO_KODU
```

Doğru yanıt (4 satır):

```text
DEPO_KODU | GIRIS_MIKTARI
--------- + -------------
DEP00     |        213,69
DEP01     |        248,92
DEP02     |        347,59
DEP03     |        398,95
```

- [ ] niyet doğru

### Q08 — Her satıcı cariden yapılan toplam alış tutarı ne kadar?

- Etiketler: `trap:alici_satici`, `needs_rule`
- Kurallar: `satici`, `iptal_haric`
- Tablolar: `TBLFATUIRS`, `TBLCASABIT`
- Sıra: önemsiz
- Tuzak: alici_satici
- Not: CARI_TIP='H' hem alıcı hem satıcıdır; yalnız 'S' arayan sorgu bu carinin alışlarını kaçırır.

```sql
SELECT c.CARI_KOD, c.CARI_ISIM, SUM(f.GENELTOPLAM) AS ALIS_TOPLAMI FROM TBLFATUIRS f JOIN TBLCASABIT c ON c.CARI_KOD = f.CARI_KODU WHERE f.FTIRSIP = 2 AND f.IPTAL = 'H' AND c.CARI_TIP IN ('S', 'H') GROUP BY c.CARI_KOD, c.CARI_ISIM ORDER BY c.CARI_KOD
```

Doğru yanıtın ilk 5 satırı (toplam 9 satır):

```text
CARI_KOD | CARI_ISIM                     | ALIS_TOPLAMI
-------- + ----------------------------- + ------------
CAR00002 | Marmara Gıda ve Market        |     3.479,77
CAR00004 | Akdeniz Gıda ve Market        |     9.047,71
CAR00007 | Yıldız İhtiyaç Maddeleri A.Ş. |    19.861,80
CAR00009 | Mertaş Market A.Ş.            |     9.616,23
CAR00010 | Kuzey Gıda Ltd. Şti.          |    21.832,68
```

- [ ] niyet doğru

### Q09 — Teslim tarihi henüz belirlenmemiş sipariş satırlarının sayısı carilere göre nasıl dağılıyor?

- Etiketler: `trap:null_teslim`, `multi_join`
- Kurallar: —
- Tablolar: `TBLSIPATRA`, `TBLSIPAMAS`, `TBLCASABIT`
- Sıra: önemsiz
- Tuzak: null_teslim
- Not: Belirsizlik NULL demek: WHERE TESLIM_TARIHI IS NULL + COUNT(*); COUNT(TESLIM_TARIHI) tam tersini sayar, tarih koşulu yazmak ise bu satırları eler.

```sql
SELECT c.CARI_KOD, c.CARI_ISIM, COUNT(*) AS BELIRSIZ_SATIR FROM TBLSIPATRA a JOIN TBLSIPAMAS m ON m.SIPARIS_NO = a.SIPARIS_NO JOIN TBLCASABIT c ON c.CARI_KOD = m.CARI_KODU WHERE a.TESLIM_TARIHI IS NULL GROUP BY c.CARI_KOD, c.CARI_ISIM ORDER BY c.CARI_KOD
```

Doğru yanıtın ilk 5 satırı (toplam 12 satır):

```text
CARI_KOD | CARI_ISIM                    | BELIRSIZ_SATIR
-------- + ---------------------------- + --------------
CAR00001 | Anadolu Gıda Ltd. Şti.       |              1
CAR00002 | Marmara Gıda ve Market       |              1
CAR00008 | Zafer İhtiyaç Maddeleri A.Ş. |              1
CAR00009 | Mertaş Market A.Ş.           |              2
CAR00010 | Kuzey Gıda Ltd. Şti.         |              2
```

- [ ] niyet doğru

### Q10 — Satışlarına göre iade oranı %10'un üzerinde olan ürünler hangileri?

- Etiketler: `trap:kod_gckod`, `needs_rule`
- Kurallar: `iade_orani`
- Tablolar: `TBLSTHAR`
- Sıra: önemsiz
- Tuzak: kod_gckod
- Not: İade giriştir (GCKOD='G'), yani yön alanı satış/iade ayrımına yetmez; oran STHAR_HTUR üzerinden kurulur. Satışı olmayan ürün paydada sıfıra bölünmemek için elenir.

```sql
SELECT s.STOK_KODU, SUM(CASE WHEN s.STHAR_HTUR = 'I' THEN s.STHAR_GCMIK ELSE 0 END) * 100.0 / SUM(CASE WHEN s.STHAR_HTUR = 'S' THEN s.STHAR_GCMIK ELSE 0 END) AS IADE_ORANI FROM TBLSTHAR s GROUP BY s.STOK_KODU HAVING SUM(CASE WHEN s.STHAR_HTUR = 'S' THEN s.STHAR_GCMIK ELSE 0 END) > 0 AND SUM(CASE WHEN s.STHAR_HTUR = 'I' THEN s.STHAR_GCMIK ELSE 0 END) > 0.1 * SUM(CASE WHEN s.STHAR_HTUR = 'S' THEN s.STHAR_GCMIK ELSE 0 END) ORDER BY s.STOK_KODU
```

Doğru yanıt (1 satır):

```text
STOK_KODU | IADE_ORANI
--------- + ----------
STK0002   |      37,50
```

- [ ] niyet doğru

### Q11 — Bu yıl içinde iadeler düşülmüş net satış miktarı kaç birim?

- Etiketler: `needs_rule`
- Kurallar: `net_satis`, `bu_yil`
- Tablolar: `TBLSTHAR`
- Sıra: önemsiz
- Tuzak: yok
- Not: Net satış miktar bazlıdır: satış (S) miktarından satış iadesi (I) miktarı düşülür, tutar hesabına girilmez. Alış, transfer ve sayım/devir hareketleri net satışa dahil değildir.

```sql
SELECT SUM(CASE WHEN STHAR_HTUR = 'S' THEN STHAR_GCMIK ELSE 0 END) - SUM(CASE WHEN STHAR_HTUR = 'I' THEN STHAR_GCMIK ELSE 0 END) AS NET_MIKTAR FROM TBLSTHAR WHERE STHAR_TARIH >= '2026-01-01' AND STHAR_TARIH < '2027-01-01'
```

Doğru yanıt (1 satır):

```text
NET_MIKTAR
----------
  2.939,88
```

- [ ] niyet doğru

### Q12 — Geçen ay düzenlenen iptal edilmemiş satış faturalarının KDV dahil genel toplamı ne kadar?

- Etiketler: `needs_rule`
- Kurallar: `brut_satis`, `iptal_haric`, `gecen_ay`
- Tablolar: `TBLFATUIRS`
- Sıra: önemsiz
- Tuzak: yok
- Not: Brüt satış fatura başlığındaki KDV dahil GENELTOPLAM'dır, hareketlerin KDV hariç cirosu değildir. AS_OF 2026-09-30 için geçen ay Ağustos 2026; iptal edilen faturalar hiçbir toplama girmez.

```sql
SELECT SUM(f.GENELTOPLAM) AS BRUT_SATIS FROM TBLFATUIRS f WHERE f.FTIRSIP = 1 AND f.IPTAL = 'H' AND f.TARIH >= '2026-08-01' AND f.TARIH < '2026-09-01'
```

Doğru yanıt (1 satır):

```text
BRUT_SATIS
----------
110.197,76
```

- [ ] niyet doğru

### Q13 — 2025 yılında (arşiv hareketlerinde) en çok satan 5 ürün hangileri; kodu, adı ve toplam satış miktarı nedir?

- Etiketler: `archive`, `needs_rule`
- Kurallar: `arsiv_2025`
- Tablolar: `TBLSTHAR_ARSIV`, `TBLSTSABIT`
- Sıra: korunur
- Tuzak: yok
- Not: 2025 hareketleri TBLSTHAR'da değil TBLSTHAR_ARSIV'de durur; güncel tabloya bakan sorgu 2026'nın şampiyonunu söyler. Sıra miktara göre, eşitlikte ürün koduna göre kurulur.

```sql
SELECT TOP 5 s.STOK_KODU, t.STOK_ADI, SUM(s.STHAR_GCMIK) AS SATIS_MIKTARI FROM TBLSTHAR_ARSIV s JOIN TBLSTSABIT t ON t.STOK_KODU = s.STOK_KODU WHERE s.STHAR_HTUR = 'S' GROUP BY s.STOK_KODU, t.STOK_ADI ORDER BY SATIS_MIKTARI DESC, s.STOK_KODU
```

Doğru yanıt (5 satır):

```text
STOK_KODU | STOK_ADI          | SATIS_MIKTARI
--------- + ----------------- + -------------
STK0018   | Süzme Bal 850 g   |        754,04
STK0014   | Streç Film 30 m   |        186,00
STK0005   | Toz Şeker 5 kg    |        160,00
STK0012   | Kuru Fasulye 1 kg |        156,84
STK0007   | Diş Macunu 100 ml |        148,00
```

- [ ] niyet doğru

### Q14 — Tüm zamanların (2025 arşivi ve güncel hareketlerin) KDV hariç toplam satış tutarı ne kadar?

- Etiketler: `archive`, `needs_rule`
- Kurallar: `arsiv_2025`, `ciro`
- Tablolar: `TBLSTHAR`, `TBLSTHAR_ARSIV`
- Sıra: önemsiz
- Tuzak: yok
- Not: 'Tüm zamanlar' iki kaynağı birden ister; UNION ALL satır yitirmez, UNION aynı satırı tekilleştirir. Faturasız transfer ve sayım satırlarının STHAR_NF'si NULL'dır ama tip filtresi onları zaten dışarıda bırakır.

```sql
SELECT SUM(h.STHAR_GCMIK * h.STHAR_NF) AS TOPLAM_SATIS_TUTARI FROM (SELECT STHAR_GCMIK, STHAR_NF, STHAR_HTUR FROM TBLSTHAR UNION ALL SELECT STHAR_GCMIK, STHAR_NF, STHAR_HTUR FROM TBLSTHAR_ARSIV) AS h WHERE h.STHAR_HTUR = 'S'
```

Doğru yanıt (1 satır):

```text
TOPLAM_SATIS_TUTARI
-------------------
       1.047.743,74
```

- [ ] niyet doğru

### Q15 — Güncel satış liste fiyatı 100 TL'nin üzerinde olan ürünlerin kodu, adı ve güncel liste fiyatı nedir?

- Etiketler: `needs_rule`
- Kurallar: `liste_fiyati`
- Tablolar: `TBLSTSABIT`, `TBLSTOKFIAT`
- Sıra: önemsiz
- Tuzak: yok
- Not: TBLSTOKFIAT ürün başına tarih aralıklı birkaç satır tutar; güncel olan FIYAT_TIPI='S' satırlarının en son geçerlik tarihli olanıdır. Kartın BIRIM_FIYAT'ı da hareketin STHAR_NF'si de liste fiyatının yerine geçmez.

```sql
SELECT t.STOK_KODU, t.STOK_ADI, f.FIYAT AS GUNCEL_LISTE_FIYATI FROM TBLSTSABIT t JOIN TBLSTOKFIAT f ON f.STOK_KODU = t.STOK_KODU WHERE f.FIYAT_TIPI = 'S' AND f.FIYAT > 100.0 AND f.GECERLILIK_TARIHI = (SELECT MAX(g.GECERLILIK_TARIHI) FROM TBLSTOKFIAT g WHERE g.STOK_KODU = f.STOK_KODU AND g.FIYAT_TIPI = 'S') ORDER BY t.STOK_KODU
```

Doğru yanıtın ilk 5 satırı (toplam 12 satır):

```text
STOK_KODU | STOK_ADI           | GUNCEL_LISTE_FIYATI
--------- + ------------------ + -------------------
STK0001   | Makarna 500 g      |              141,65
STK0002   | Türk Kahvesi 100 g |              295,18
STK0004   | Pul Biber 100 g    |              192,62
STK0005   | Toz Şeker 5 kg     |              207,75
STK0007   | Diş Macunu 100 ml  |              111,12
```

- [ ] niyet doğru

### Q16 — Bu yılın brüt satışı (iptal edilmemiş satış faturalarının KDV dahil genel toplamı) ile net cirosu (KDV hariç hareket toplamı) ayrı ayrı ne kadardır?

- Etiketler: `needs_rule`
- Kurallar: `brut_satis`, `ciro`, `iptal_haric`, `bu_yil`
- Tablolar: `TBLFATUIRS`, `TBLSTHAR`
- Sıra: önemsiz
- Tuzak: yok
- Not: İki sayı iki ayrı kaynaktan gelir: brüt satış fatura başlığında KDV dahil, ciro hareket satırında KDV hariç. Faturaları satırlarıyla join edip toplamak başlık tutarını satır sayısıyla katlardı.

```sql
SELECT (SELECT SUM(f.GENELTOPLAM) FROM TBLFATUIRS f WHERE f.FTIRSIP = 1 AND f.IPTAL = 'H' AND f.TARIH >= '2026-01-01' AND f.TARIH < '2027-01-01') AS BRUT_SATIS, (SELECT SUM(s.STHAR_GCMIK * s.STHAR_NF) FROM TBLSTHAR s WHERE s.STHAR_HTUR = 'S' AND s.STHAR_TARIH >= '2026-01-01' AND s.STHAR_TARIH < '2027-01-01') AS NET_CIRO
```

Doğru yanıt (1 satır):

```text
BRUT_SATIS |   NET_CIRO
---------- + ----------
578.821,82 | 508.041,02
```

- [ ] niyet doğru

### Q17 — Bu yıl her ürün grubunda iadeler düşülmüş net satış miktarı kaç birim?

- Etiketler: `needs_rule`, `multi_join`
- Kurallar: `net_satis`, `bu_yil`
- Tablolar: `TBLSTHAR`, `TBLSTSABIT`, `TBLSTGRUP`
- Sıra: önemsiz
- Tuzak: yok
- Not: Kırılım grupta; hareketin kendi sütunlarında grup kodu yoktur, stok kartı üzerinden ürün grubuna iki bağlantı kurulur. Net satış yine miktar bazlıdır ve iade düşülür.

```sql
SELECT g.GRUP_KODU, g.GRUP_ISIMI, SUM(CASE WHEN s.STHAR_HTUR = 'S' THEN s.STHAR_GCMIK ELSE 0 END) - SUM(CASE WHEN s.STHAR_HTUR = 'I' THEN s.STHAR_GCMIK ELSE 0 END) AS NET_MIKTAR FROM TBLSTHAR s JOIN TBLSTSABIT t ON t.STOK_KODU = s.STOK_KODU JOIN TBLSTGRUP g ON g.GRUP_KODU = t.GRUP_KODU WHERE s.STHAR_HTUR IN ('S', 'I') AND s.STHAR_TARIH >= '2026-01-01' AND s.STHAR_TARIH < '2027-01-01' GROUP BY g.GRUP_KODU, g.GRUP_ISIMI ORDER BY g.GRUP_KODU
```

Doğru yanıtın ilk 5 satırı (toplam 7 satır):

```text
GRUP_KODU | GRUP_ISIMI    | NET_MIKTAR
--------- + ------------- + ----------
GRP00     | Gıda          |   1.039,62
GRP01     | İçecek        |      50,00
GRP02     | Temizlik      |     426,00
GRP03     | Kişisel Bakım |     409,71
GRP04     | Kahvaltılık   |      78,00
```

- [ ] niyet doğru

### Q18 — 2025 arşivinde her alıcı carinin KDV hariç toplam satış tutarı ne kadar?

- Etiketler: `archive`, `needs_rule`
- Kurallar: `arsiv_2025`, `alici`, `ciro`
- Tablolar: `TBLSTHAR_ARSIV`, `TBLCASABIT`
- Sıra: önemsiz
- Tuzak: yok
- Not: Arşiv hareketi CARI_KODU ile kartın CARI_KOD'una bağlanır; CARI_TIP='H' olanlar da alıcıdır. Tarih filtresi arşivi baştan sona kapsar ama 2026 sızarsa ayrışsın diye açıkça yazılır.

```sql
SELECT c.CARI_KOD, c.CARI_ISIM, SUM(s.STHAR_GCMIK * s.STHAR_NF) AS SATIS_TUTARI FROM TBLSTHAR_ARSIV s JOIN TBLCASABIT c ON c.CARI_KOD = s.CARI_KODU WHERE s.STHAR_HTUR = 'S' AND s.STHAR_TARIH >= '2025-01-01' AND s.STHAR_TARIH < '2026-01-01' AND c.CARI_TIP IN ('A', 'H') GROUP BY c.CARI_KOD, c.CARI_ISIM ORDER BY c.CARI_KOD
```

Doğru yanıtın ilk 5 satırı (toplam 20 satır):

```text
CARI_KOD | CARI_ISIM                     | SATIS_TUTARI
-------- + ----------------------------- + ------------
CAR00001 | Anadolu Gıda Ltd. Şti.        |     7.024,05
CAR00002 | Marmara Gıda ve Market        |    17.797,65
CAR00003 | Ege Gıda Ltd. Şti.            |    40.201,31
CAR00006 | Başkent Market A.Ş.           |    20.559,50
CAR00007 | Yıldız İhtiyaç Maddeleri A.Ş. |    48.492,99
```

- [ ] niyet doğru

### Q19 — 2025 yılında arşiv hareketlerine göre iade oranı %10'un üzerinde olan ürünler hangileri?

- Etiketler: `archive`, `needs_rule`
- Kurallar: `arsiv_2025`, `iade_orani`
- Tablolar: `TBLSTHAR_ARSIV`
- Sıra: önemsiz
- Tuzak: yok
- Not: Oran miktar bazlıdır; iade bir giriş (STHAR_GCKOD='G') olduğu için yön alanı satışla iadeyi ayırmaz, ayrımı STHAR_HTUR yapar. Satışı olmayan ürün paydada sıfıra bölünmesin diye HAVING ile elenir.

```sql
SELECT s.STOK_KODU, SUM(CASE WHEN s.STHAR_HTUR = 'I' THEN s.STHAR_GCMIK ELSE 0 END) * 100.0 / SUM(CASE WHEN s.STHAR_HTUR = 'S' THEN s.STHAR_GCMIK ELSE 0 END) AS IADE_ORANI FROM TBLSTHAR_ARSIV s WHERE s.STHAR_TARIH >= '2025-01-01' AND s.STHAR_TARIH < '2026-01-01' GROUP BY s.STOK_KODU HAVING SUM(CASE WHEN s.STHAR_HTUR = 'S' THEN s.STHAR_GCMIK ELSE 0 END) > 0 AND SUM(CASE WHEN s.STHAR_HTUR = 'I' THEN s.STHAR_GCMIK ELSE 0 END) > 0.1 * SUM(CASE WHEN s.STHAR_HTUR = 'S' THEN s.STHAR_GCMIK ELSE 0 END) ORDER BY s.STOK_KODU
```

Doğru yanıtın ilk 5 satırı (toplam 12 satır):

```text
STOK_KODU | IADE_ORANI
--------- + ----------
STK0001   |      11,57
STK0003   |      23,68
STK0004   |      13,77
STK0006   |      53,93
STK0007   |      16,22
```

- [ ] niyet doğru

### Q20 — Kampanya döneminde yapılan satışların KDV hariç toplam tutarı kampanya bazında ne kadar?

- Etiketler: `needs_rule`
- Kurallar: `kampanyali_satis`, `ciro`
- Tablolar: `TBLKAMPANYA`, `TBLSTHAR`
- Sıra: önemsiz
- Tuzak: yok
- Not: Kampanya ile hareket arasındaki bağ bir tarih aralığıdır ve BASLANGIC ile BITIS günleri dahildir, o yüzden bu bağlantıda yarım açık değil BETWEEN yazılır. INDIRIM_ORANI STHAR_NF'ye zaten yansımıştır, bir kez daha uygulanmaz.

```sql
SELECT k.KAMPANYA_KODU, k.KAMPANYA_ADI, SUM(s.STHAR_GCMIK * s.STHAR_NF) AS KAMPANYALI_SATIS_TUTARI FROM TBLKAMPANYA k JOIN TBLSTHAR s ON s.STOK_KODU = k.STOK_KODU AND s.STHAR_TARIH BETWEEN k.BASLANGIC AND k.BITIS WHERE s.STHAR_HTUR = 'S' GROUP BY k.KAMPANYA_KODU, k.KAMPANYA_ADI ORDER BY k.KAMPANYA_KODU
```

Doğru yanıt (5 satır):

```text
KAMPANYA_KODU | KAMPANYA_ADI          | KAMPANYALI_SATIS_TUTARI
------------- + --------------------- + -----------------------
KMP001        | Hafta Sonu Kampanyası |               11.855,28
KMP003        | Sezon Sonu Kampanyası |               10.488,26
KMP005        | Kış Kampanyası        |                2.052,16
KMP006        | Kış Kampanyası        |               10.394,06
KMP007        | Kış Kampanyası        |                5.741,28
```

- [ ] niyet doğru

### Q21 — En az bir şubesi olan alıcı carilerin sayısı her plasiyer için kaçtır?

- Etiketler: `multi_join`, `distractor`, `needs_rule`
- Kurallar: `alici`, `plasiyersiz_haric`
- Tablolar: `TBLPLASIYER`, `TBLCASABIT`, `TBLCARISUBE`
- Sıra: önemsiz
- Tuzak: yok
- Not: Bir carinin birden çok şubesi olduğu için COUNT(DISTINCT c.CARI_KOD) gerekir; COUNT(*) şube sayardı. Kartların yedeği TBLCASABIT_YEDEK yalnız birkaç cariyi tutar ve bir kısmının ili eskidir, oradan saymak farklı çıkar. Plasiyersiz cariler INNER JOIN ile düşer.

```sql
SELECT p.PLASIYER_KODU, p.AD_SOYAD, COUNT(DISTINCT c.CARI_KOD) AS SUBELI_ALICI_CARI FROM TBLPLASIYER p JOIN TBLCASABIT c ON c.PLASIYER_KODU = p.PLASIYER_KODU JOIN TBLCARISUBE b ON b.CARI_KOD = c.CARI_KOD WHERE c.CARI_TIP IN ('A', 'H') GROUP BY p.PLASIYER_KODU, p.AD_SOYAD ORDER BY p.PLASIYER_KODU
```

Doğru yanıt (4 satır):

```text
PLASIYER_KODU | AD_SOYAD    | SUBELI_ALICI_CARI
------------- + ----------- + -----------------
PLS001        | Emine Aslan |                 4
PLS002        | Ayşe Demir  |                 2
PLS004        | Fatma Şahin |                 2
PLS006        | Elif Koç    |                 1
```

- [ ] niyet doğru

### Q22 — Eylül 2026'da carilerin illeri bazında iptal edilmemiş satış faturalarının KDV dahil toplamı ve fatura sayısı ne kadardır?

- Etiketler: `distractor`, `needs_rule`
- Kurallar: `brut_satis`, `iptal_haric`
- Tablolar: `TBLFATUIRS`, `TBLCASABIT`
- Sıra: önemsiz
- Tuzak: yok
- Not: İl cari kartının IL alanıdır; şubelerin ili (TBLCARISUBE.IL) ondan farklı olabilir. Eylül'ün onaylanmamış fatura taslakları TBLFATUIRS_TASLAK'ta durur ve toplamı şişirir, iptal edilenler IPTAL='H' ile çıkar.

```sql
SELECT c.IL, SUM(f.GENELTOPLAM) AS BRUT_SATIS, COUNT(*) AS FATURA_SAYISI FROM TBLFATUIRS f JOIN TBLCASABIT c ON c.CARI_KOD = f.CARI_KODU WHERE f.FTIRSIP = 1 AND f.IPTAL = 'H' AND f.TARIH >= '2026-09-01' AND f.TARIH < '2026-10-01' GROUP BY c.IL ORDER BY c.IL
```

Doğru yanıtın ilk 5 satırı (toplam 6 satır):

```text
IL       | BRUT_SATIS | FATURA_SAYISI
-------- + ---------- + -------------
ANKARA   |     985,75 |             1
ANTALYA  |  35.573,14 |             3
BURSA    |  56.746,31 |             6
KONYA    |  58.816,06 |             5
İSTANBUL |  44.327,67 |             4
```

- [ ] niyet doğru

### Q23 — Teslim tarihi henüz belirlenmemiş sipariş satırlarının sayısı ve KDV hariç toplam tutarı ürün grubu bazında nedir?

- Etiketler: `multi_join`, `distractor`, `needs_rule`
- Kurallar: `teslim_bekleyen`
- Tablolar: `TBLSIPATRA`, `TBLSTSABIT`, `TBLSTGRUP`
- Sıra: önemsiz
- Tuzak: yok
- Not: Grup kırılımı için sipariş başlığına inmeye gerek yok: satırın ürünü stok kartından grubuna iki bağlantıyla ulaşır, en kısa yol bu. TBLSIPATRA_TMP aynı satırların ara kaydı ve bir kısmı vazgeçilmiş, oradan saymak farklı çıkar.

```sql
SELECT g.GRUP_KODU, g.GRUP_ISIMI, COUNT(*) AS BEKLEYEN_SATIR, SUM(a.TUTAR) AS BEKLEYEN_TUTAR FROM TBLSIPATRA a JOIN TBLSTSABIT t ON t.STOK_KODU = a.STOK_KODU JOIN TBLSTGRUP g ON g.GRUP_KODU = t.GRUP_KODU WHERE a.TESLIM_TARIHI IS NULL GROUP BY g.GRUP_KODU, g.GRUP_ISIMI ORDER BY g.GRUP_KODU
```

Doğru yanıt (5 satır):

```text
GRUP_KODU | GRUP_ISIMI    | BEKLEYEN_SATIR | BEKLEYEN_TUTAR
--------- + ------------- + -------------- + --------------
GRP00     | Gıda          |              6 |      32.500,00
GRP02     | Temizlik      |              2 |       9.596,94
GRP03     | Kişisel Bakım |              4 |      12.040,82
GRP05     | Kuruyemiş     |              2 |         959,73
GRP07     | Atıştırmalık  |              8 |      11.016,35
```

- [ ] niyet doğru

### Q24 — Kampanya kapsamındaki ürünler için verilen siparişlerin toplam miktarı ve KDV hariç tutarı kampanya bazında ne kadardır?

- Etiketler: `multi_join`
- Kurallar: —
- Tablolar: `TBLKAMPANYA`, `TBLSTSABIT`, `TBLSIPATRA`
- Sıra: önemsiz
- Tuzak: yok
- Not: Burada kampanya bir ürün kümesidir; sipariş satırı kampanya tarih aralığına göre süzülmaz, o yüzden tarih bağı kurulmaz (kampanyalı satıştan farkı bu). TBLKAMPANYA ile TBLSIPATRA'nın en kısa yolu stok kartından geçer, iki bağlantı da fk. Hiç sipariş satırı olmayan kampanyalar INNER JOIN ile düşer.

```sql
SELECT k.KAMPANYA_KODU, k.KAMPANYA_ADI, SUM(a.MIKTAR) AS SIPARIS_MIKTARI, SUM(a.TUTAR) AS SIPARIS_TUTARI FROM TBLKAMPANYA k JOIN TBLSTSABIT t ON t.STOK_KODU = k.STOK_KODU JOIN TBLSIPATRA a ON a.STOK_KODU = t.STOK_KODU GROUP BY k.KAMPANYA_KODU, k.KAMPANYA_ADI ORDER BY k.KAMPANYA_KODU
```

Doğru yanıt (5 satır):

```text
KAMPANYA_KODU | KAMPANYA_ADI          | SIPARIS_MIKTARI | SIPARIS_TUTARI
------------- + --------------------- + --------------- + --------------
KMP001        | Hafta Sonu Kampanyası |          133,00 |      15.139,67
KMP003        | Sezon Sonu Kampanyası |          193,00 |      16.268,00
KMP005        | Kış Kampanyası        |           89,00 |       6.713,83
KMP006        | Kış Kampanyası        |           86,62 |       4.639,56
KMP007        | Kış Kampanyası        |           89,00 |       6.713,83
```

- [ ] niyet doğru

### Q25 — Kampanya döneminde kampanya ürününün satış miktarı ve ürünü satın alan farklı cari sayısı kampanya bazında ne kadardır?

- Etiketler: `multi_join`, `needs_rule`
- Kurallar: `kampanyali_satis`
- Tablolar: `TBLKAMPANYA`, `TBLSTSABIT`, `TBLSTHAR`
- Sıra: önemsiz
- Tuzak: yok
- Not: Kampanyalı satış hareket tarihi BASLANGIC ile BITIS arasına düşen satıştır; iki gün de dahil, o yüzden yarım açık değil BETWEEN. Aynı ürün iki kampanyada geçebilir, aralıklar farklı olduğu için satırları ayrı sayılır. Döneminde satışı kalmayan kampanyalar INNER JOIN ile düşer.

```sql
SELECT k.KAMPANYA_KODU, k.KAMPANYA_ADI, SUM(s.STHAR_GCMIK) AS SATIS_MIKTARI, COUNT(DISTINCT s.CARI_KODU) AS ALICI_CARI_SAYISI FROM TBLKAMPANYA k JOIN TBLSTSABIT t ON t.STOK_KODU = k.STOK_KODU JOIN TBLSTHAR s ON s.STOK_KODU = t.STOK_KODU AND s.STHAR_TARIH BETWEEN k.BASLANGIC AND k.BITIS WHERE s.STHAR_HTUR = 'S' GROUP BY k.KAMPANYA_KODU, k.KAMPANYA_ADI ORDER BY k.KAMPANYA_KODU
```

Doğru yanıt (5 satır):

```text
KAMPANYA_KODU | KAMPANYA_ADI          | SATIS_MIKTARI | ALICI_CARI_SAYISI
------------- + --------------------- + ------------- + -----------------
KMP001        | Hafta Sonu Kampanyası |        125,00 |                 5
KMP003        | Sezon Sonu Kampanyası |        110,00 |                 5
KMP005        | Kış Kampanyası        |         32,00 |                 1
KMP006        | Kış Kampanyası        |         79,51 |                 4
KMP007        | Kış Kampanyası        |         86,00 |                 4
```

- [ ] niyet doğru

### Q26 — Ağustos 2026'da her plasiyerin carilerine kesilen iptal edilmemiş satış faturalarının toplamı, her faturanın kendi tarihindeki USD satış kuruyla kaç dolar eder?

- Etiketler: `multi_join`, `needs_rule`
- Kurallar: `doviz_tl`, `iptal_haric`, `gecen_ay`, `plasiyersiz_haric`
- Tablolar: `TBLFATUIRS`, `TBLCASABIT`, `TBLPLASIYER`, `TBLDOVKUR`
- Sıra: önemsiz
- Tuzak: yok
- Not: Tutarlar TL'dir; dövize çevirirken kura bölünür ve kur faturanın kendi tarihindeki USD satırıdır, ortalama kur kullanılmaz. TBLDOVKUR ile bağ fk değil tarih eşliğidir: her gün ve kod için tek satır olduğu için faturaları çoğaltmaz. AS_OF 2026-09-30 için geçen ay Ağustos 2026.

```sql
SELECT p.PLASIYER_KODU, p.AD_SOYAD, SUM(f.GENELTOPLAM / k.SATIS) AS USD_TUTARI FROM TBLFATUIRS f JOIN TBLCASABIT c ON c.CARI_KOD = f.CARI_KODU JOIN TBLPLASIYER p ON p.PLASIYER_KODU = c.PLASIYER_KODU JOIN TBLDOVKUR k ON k.KUR_TARIH = f.TARIH AND k.DOVIZ_KODU = 'USD' WHERE f.FTIRSIP = 1 AND f.IPTAL = 'H' AND f.TARIH >= '2026-08-01' AND f.TARIH < '2026-09-01' GROUP BY p.PLASIYER_KODU, p.AD_SOYAD ORDER BY p.PLASIYER_KODU
```

Doğru yanıt (4 satır):

```text
PLASIYER_KODU | AD_SOYAD    | USD_TUTARI
------------- + ----------- + ----------
PLS001        | Emine Aslan |     648,47
PLS002        | Ayşe Demir  |     450,89
PLS004        | Fatma Şahin |     249,29
PLS006        | Elif Koç    |     384,81
```

- [ ] niyet doğru

### Q27 — Eylül 2026'da en yüksek satış cirosuna (KDV hariç) sahip 3 depo hangileri; kodu, adı, cirosu ve satılan farklı ürün sayısı nedir?

- Etiketler: `distractor`, `needs_rule`
- Kurallar: `ciro`
- Tablolar: `TBLSTHAR`, `TBLDEPO`
- Sıra: korunur
- Tuzak: yok
- Not: TBLSTHAR_LOG Eylül hareketlerinin düzenlenmiş ve bir kısmı iki kez yazılmış kopyası; oradan hesaplanan ciro gerçek tablodan farklı çıkar. Sıra ciroya göre, eşitlikte depo kodu ile deterministik kurulur.

```sql
SELECT TOP 3 d.DEPO_KODU, d.DEPO_ISIMI, SUM(s.STHAR_GCMIK * s.STHAR_NF) AS CIRO, COUNT(DISTINCT s.STOK_KODU) AS URUN_CESIDI FROM TBLSTHAR s JOIN TBLDEPO d ON d.DEPO_KODU = s.DEPO_KODU WHERE s.STHAR_HTUR = 'S' AND s.STHAR_TARIH >= '2026-09-01' AND s.STHAR_TARIH < '2026-10-01' GROUP BY d.DEPO_KODU, d.DEPO_ISIMI ORDER BY CIRO DESC, d.DEPO_KODU
```

Doğru yanıt (3 satır):

```text
DEPO_KODU | DEPO_ISIMI           |      CIRO | URUN_CESIDI
--------- + -------------------- + --------- + -----------
DEP02     | Ege Bölge Deposu     | 59.722,68 |           8
DEP03     | Transit Depo         | 59.251,69 |           7
DEP01     | Avrupa Yakası Deposu | 43.957,72 |           9
```

- [ ] niyet doğru

### Q28 — Bu yıl her plasiyerin carilerine ait cari hesap hareketlerinin borç ve alacak toplamları ayrı ayrı ne kadardır?

- Etiketler: `multi_join`, `distractor`, `needs_rule`
- Kurallar: `bu_yil`, `plasiyersiz_haric`
- Tablolar: `TBLCAHAR`, `TBLCASABIT`, `TBLPLASIYER`
- Sıra: önemsiz
- Tuzak: yok
- Not: Borç/alacak yönü BA kodundadır; tek toplama almak bakiyeyi verir, iki ayrı toplam hareketin hacmini. TBLCAHAR_LOG aynı hareketlerin log kopyasıdır ve fazladan satır taşır, o yüzden oradan toplanmaz. Plasiyersiz cariler INNER JOIN ile düşer.

```sql
SELECT p.PLASIYER_KODU, p.AD_SOYAD, SUM(CASE WHEN h.BA = 'B' THEN h.TUTAR ELSE 0 END) AS BORC, SUM(CASE WHEN h.BA = 'A' THEN h.TUTAR ELSE 0 END) AS ALACAK FROM TBLCAHAR h JOIN TBLCASABIT c ON c.CARI_KOD = h.CARI_KODU JOIN TBLPLASIYER p ON p.PLASIYER_KODU = c.PLASIYER_KODU WHERE h.TARIH >= '2026-01-01' AND h.TARIH < '2027-01-01' GROUP BY p.PLASIYER_KODU, p.AD_SOYAD ORDER BY p.PLASIYER_KODU
```

Doğru yanıt (5 satır):

```text
PLASIYER_KODU | AD_SOYAD    |       BORC |    ALACAK
------------- + ----------- + ---------- + ---------
PLS001        | Emine Aslan | 150.622,32 | 20.601,04
PLS002        | Ayşe Demir  |  64.185,66 | 22.623,93
PLS003        | Hasan Doğan |  50.789,38 | 32.853,67
PLS004        | Fatma Şahin | 150.501,04 | 40.487,38
PLS006        | Elif Koç    |  55.853,03 |  2.056,13
```

- [ ] niyet doğru

### Q29 — Şubelerinden en az biri kendi ilinden farklı bir ilde olan alıcı carilerin bu yılki KDV hariç satış cirosu ne kadardır?

- Etiketler: `multi_join`, `distractor`, `needs_rule`
- Kurallar: `alici`, `ciro`, `bu_yil`
- Tablolar: `TBLSTHAR`, `TBLCASABIT`, `TBLCARISUBE`
- Sıra: önemsiz
- Tuzak: yok
- Not: Şart şubenin varlığı, sayısı değil; TBLCARISUBE ile JOIN etmek hareketleri şube başına tekrarlar ve ciroyu katardı, o yüzden EXISTS. Karşılaştırılan iki il ayrı tablolarda: cari kartının IL'i ile şubenin IL'i. TBLCASABIT_YEDEK'in ili eski kayıttan gelir.

```sql
SELECT c.CARI_KOD, c.CARI_ISIM, SUM(s.STHAR_GCMIK * s.STHAR_NF) AS CIRO FROM TBLSTHAR s JOIN TBLCASABIT c ON c.CARI_KOD = s.CARI_KODU WHERE s.STHAR_HTUR = 'S' AND s.STHAR_TARIH >= '2026-01-01' AND s.STHAR_TARIH < '2027-01-01' AND c.CARI_TIP IN ('A', 'H') AND EXISTS (SELECT 1 FROM TBLCARISUBE b WHERE b.CARI_KOD = c.CARI_KOD AND b.IL <> c.IL) GROUP BY c.CARI_KOD, c.CARI_ISIM ORDER BY c.CARI_KOD
```

Doğru yanıtın ilk 5 satırı (toplam 13 satır):

```text
CARI_KOD | CARI_ISIM                     |      CIRO
-------- + ----------------------------- + ---------
CAR00001 | Anadolu Gıda Ltd. Şti.        | 44.677,50
CAR00002 | Marmara Gıda ve Market        | 32.397,98
CAR00006 | Başkent Market A.Ş.           | 33.412,87
CAR00007 | Yıldız İhtiyaç Maddeleri A.Ş. |  8.257,97
CAR00008 | Zafer İhtiyaç Maddeleri A.Ş.  |  7.468,60
```

- [ ] niyet doğru

### Q30 — Bu yıl her ürün grubunun KDV hariç satış cirosu ve grubun bu yıl satan farklı ürün sayısı nedir?

- Etiketler: `multi_join`, `distractor`, `needs_rule`
- Kurallar: `ciro`, `bu_yil`
- Tablolar: `TBLSTHAR`, `TBLSTSABIT`, `TBLSTGRUP`
- Sıra: önemsiz
- Tuzak: yok
- Not: Muhasebe fişleri (TBLMUHFIS) gelir satırı taşır ama iptal edilmiş faturaların kayıtları da oradadır ve ürün grubu kırılımı yoktur; ciro hareket satırından gelir. TBLSTSABIT_ESKI eski sürüm kartlardır, grup ağacı güncel karttadır.

```sql
SELECT g.GRUP_KODU, g.GRUP_ISIMI, SUM(s.STHAR_GCMIK * s.STHAR_NF) AS CIRO, COUNT(DISTINCT s.STOK_KODU) AS SATILAN_URUN FROM TBLSTHAR s JOIN TBLSTSABIT t ON t.STOK_KODU = s.STOK_KODU JOIN TBLSTGRUP g ON g.GRUP_KODU = t.GRUP_KODU WHERE s.STHAR_HTUR = 'S' AND s.STHAR_TARIH >= '2026-01-01' AND s.STHAR_TARIH < '2027-01-01' GROUP BY g.GRUP_KODU, g.GRUP_ISIMI ORDER BY g.GRUP_KODU
```

Doğru yanıtın ilk 5 satırı (toplam 7 satır):

```text
GRUP_KODU | GRUP_ISIMI    |       CIRO | SATILAN_URUN
--------- + ------------- + ---------- + ------------
GRP00     | Gıda          | 257.959,25 |            4
GRP01     | İçecek        |  22.452,40 |            1
GRP02     | Temizlik      |  50.180,44 |            2
GRP03     | Kişisel Bakım |  54.742,00 |            2
GRP04     | Kahvaltılık   |  30.615,00 |            1
```

- [ ] niyet doğru

### Q31 — Kuruyemiş ürün grubunun bu yılki KDV hariç satış cirosu ve bu grupta satış yapan farklı ürün sayısı ne kadardır?

- Etiketler: `multi_join`, `needs_values`, `needs_rule`
- Kurallar: `ciro`, `bu_yil`
- Tablolar: `TBLSTHAR`, `TBLSTSABIT`, `TBLSTGRUP`
- Sıra: önemsiz
- Tuzak: yok
- Not: Aranan şey grubun adı: 'Kuruyemiş' yazımı TBLSTGRUP.GRUP_ISIMI'nden alınır, GRP kodu tahmin edilmez. Hareketin kendi sütunlarında grup yoktur, kırılım stok kartından kurulur; ciro yine hareket satırının KDV hariç tutarıdır.

```sql
SELECT g.GRUP_KODU, g.GRUP_ISIMI, SUM(s.STHAR_GCMIK * s.STHAR_NF) AS CIRO, COUNT(DISTINCT s.STOK_KODU) AS SATILAN_URUN FROM TBLSTHAR s JOIN TBLSTSABIT t ON t.STOK_KODU = s.STOK_KODU JOIN TBLSTGRUP g ON g.GRUP_KODU = t.GRUP_KODU WHERE g.GRUP_ISIMI = 'Kuruyemiş' AND s.STHAR_HTUR = 'S' AND s.STHAR_TARIH >= '2026-01-01' AND s.STHAR_TARIH < '2027-01-01' GROUP BY g.GRUP_KODU, g.GRUP_ISIMI ORDER BY g.GRUP_KODU
```

Doğru yanıt (1 satır):

```text
GRUP_KODU | GRUP_ISIMI |      CIRO | SATILAN_URUN
--------- + ---------- + --------- + ------------
GRP05     | Kuruyemiş  | 20.798,02 |            1
```

- [ ] niyet doğru

### Q32 — 'Kış Kampanyası' adıyla yürütülen her kampanyanın kendi kampanya dönemindeki satışların KDV hariç toplamı ne kadardır?

- Etiketler: `needs_values`, `needs_rule`
- Kurallar: `kampanyali_satis`, `ciro`
- Tablolar: `TBLKAMPANYA`, `TBLSTHAR`
- Sıra: önemsiz
- Tuzak: yok
- Not: Kampanya adı benzersiz değil: aynı ad birden çok kampanyada geçebiliyor, o yüzden kırılım KAMPANYA_KODU ile kurulur; ad tek başına gruplamak ayrı kampanyaları tek satırda eritirdi. Kampanya aralığı BASLANGIC ve BITIS günlerini içerir, bu yüzden burada yarım açık değil BETWEEN yazılır. Döneminde satışı kalmayan kampanya INNER JOIN ile düşer.

```sql
SELECT k.KAMPANYA_KODU, k.KAMPANYA_ADI, SUM(s.STHAR_GCMIK * s.STHAR_NF) AS KAMPANYALI_SATIS_TUTARI FROM TBLKAMPANYA k JOIN TBLSTHAR s ON s.STOK_KODU = k.STOK_KODU AND s.STHAR_TARIH BETWEEN k.BASLANGIC AND k.BITIS WHERE k.KAMPANYA_ADI = 'Kış Kampanyası' AND s.STHAR_HTUR = 'S' GROUP BY k.KAMPANYA_KODU, k.KAMPANYA_ADI ORDER BY k.KAMPANYA_KODU
```

Doğru yanıt (3 satır):

```text
KAMPANYA_KODU | KAMPANYA_ADI   | KAMPANYALI_SATIS_TUTARI
------------- + -------------- + -----------------------
KMP005        | Kış Kampanyası |                2.052,16
KMP006        | Kış Kampanyası |               10.394,06
KMP007        | Kış Kampanyası |                5.741,28
```

- [ ] niyet doğru

### Q33 — Merkez Depo ile Ege Bölge Deposu'nun bu yılki KDV hariç satış cirosu ve satış hareketi sayısı depo bazında ne kadardır?

- Etiketler: `distractor`, `needs_values`, `needs_rule`
- Kurallar: `ciro`, `bu_yil`
- Tablolar: `TBLSTHAR`, `TBLDEPO`
- Sıra: önemsiz
- Tuzak: yok
- Not: Hareketin kendi sütununda yalnız DEPO_KODU vardır; 'Merkez Depo' ve 'Ege Bölge Deposu' yazımları TBLDEPO.DEPO_ISIMI'nden süzülür. TBLSTHAR_LOG Eylül hareketlerinin düzenlenmiş ve bir kısmı iki kez yazılmış kopyasıdır, oradan hesaplanan ciro da hareket sayısı da farklı çıkar.

```sql
SELECT d.DEPO_KODU, d.DEPO_ISIMI, SUM(s.STHAR_GCMIK * s.STHAR_NF) AS CIRO, COUNT(*) AS HAREKET_SAYISI FROM TBLSTHAR s JOIN TBLDEPO d ON d.DEPO_KODU = s.DEPO_KODU WHERE d.DEPO_ISIMI IN ('Merkez Depo', 'Ege Bölge Deposu') AND s.STHAR_HTUR = 'S' AND s.STHAR_TARIH >= '2026-01-01' AND s.STHAR_TARIH < '2027-01-01' GROUP BY d.DEPO_KODU, d.DEPO_ISIMI ORDER BY d.DEPO_KODU
```

Doğru yanıt (2 satır):

```text
DEPO_KODU | DEPO_ISIMI       |       CIRO | HAREKET_SAYISI
--------- + ---------------- + ---------- + --------------
DEP00     | Merkez Depo      | 108.118,29 |             35
DEP02     | Ege Bölge Deposu | 149.650,91 |             40
```

- [ ] niyet doğru

### Q34 — Şubesi Çankaya ilçesinde olan alıcı carilerin kodu, ünvanı ve Çankaya'daki şube sayısı nedir?

- Etiketler: `distractor`, `needs_values`, `needs_rule`
- Kurallar: `alici`
- Tablolar: `TBLCASABIT`, `TBLCARISUBE`
- Sıra: önemsiz
- Tuzak: yok
- Not: İlçe yazımı TBLCARISUBE.ILCE alanındadır ve NULL olabilir; NULL şubeler eşitlik koşuluna zaten girmez, ayrıca IS NOT NULL yazmak gerekmez. Sayılan şey şube olduğu için grup caridir ve COUNT(*) şube sayısını verir. TBLCASABIT_YEDEK kartların yalnız birkaç cariyi tutan eski kopyasıdır, oradan sayınca cariler eksik çıkar.

```sql
SELECT c.CARI_KOD, c.CARI_ISIM, COUNT(*) AS SUBE_SAYISI FROM TBLCASABIT c JOIN TBLCARISUBE b ON b.CARI_KOD = c.CARI_KOD WHERE b.ILCE = 'Çankaya' AND c.CARI_TIP IN ('A', 'H') GROUP BY c.CARI_KOD, c.CARI_ISIM ORDER BY c.CARI_KOD
```

Doğru yanıt (2 satır):

```text
CARI_KOD | CARI_ISIM                    | SUBE_SAYISI
-------- + ---------------------------- + -----------
CAR00002 | Marmara Gıda ve Market       |           1
CAR00008 | Zafer İhtiyaç Maddeleri A.Ş. |           2
```

- [ ] niyet doğru

### Q35 — Şubesi İzmir ilinde bulunan alıcı carilerin Eylül 2026'daki iptal edilmemiş satış faturalarının KDV dahil toplamı ve fatura sayısı ne kadardır?

- Etiketler: `multi_join`, `needs_values`, `needs_rule`
- Kurallar: `brut_satis`, `iptal_haric`, `alici`
- Tablolar: `TBLFATUIRS`, `TBLCASABIT`, `TBLCARISUBE`
- Sıra: önemsiz
- Tuzak: yok
- Not: Aranan il şubenin ili (TBLCARISUBE.IL); carinin kendi ili (TBLCASABIT.IL) ondan farklı olabilir. Birden çok şube faturayı tekrarlayacağı için şube ile JOIN yerine EXISTS kurulur. TBLFATUIRS_TASLAK'ın Eylül taslakları onaylanmadığı için brüt satışa girmez.

```sql
SELECT c.CARI_KOD, c.CARI_ISIM, SUM(f.GENELTOPLAM) AS BRUT_SATIS, COUNT(*) AS FATURA_SAYISI FROM TBLFATUIRS f JOIN TBLCASABIT c ON c.CARI_KOD = f.CARI_KODU WHERE f.FTIRSIP = 1 AND f.IPTAL = 'H' AND f.TARIH >= '2026-09-01' AND f.TARIH < '2026-10-01' AND c.CARI_TIP IN ('A', 'H') AND EXISTS (SELECT 1 FROM TBLCARISUBE b WHERE b.CARI_KOD = c.CARI_KOD AND b.IL = 'İZMİR') GROUP BY c.CARI_KOD, c.CARI_ISIM ORDER BY c.CARI_KOD
```

Doğru yanıt (4 satır):

```text
CARI_KOD | CARI_ISIM                    | BRUT_SATIS | FATURA_SAYISI
-------- + ---------------------------- + ---------- + -------------
CAR00011 | Doğu İhtiyaç Maddeleri A.Ş.  |  10.194,16 |             2
CAR00013 | Altın İhtiyaç Maddeleri A.Ş. |   9.941,36 |             1
CAR00021 | Şimşek Market A.Ş.           |     985,75 |             1
CAR00023 | Hilal Temizlik Ürünleri Ltd. |  22.451,11 |             2
```

- [ ] niyet doğru

### Q36 — Eylül 2026'daki iptal edilmemiş satış faturalarının toplamı, her faturanın kendi tarihindeki EUR satış kuruyla kaç Euro eder?

- Etiketler: `needs_values`, `needs_rule`
- Kurallar: `doviz_tl`, `iptal_haric`
- Tablolar: `TBLFATUIRS`, `TBLDOVKUR`
- Sıra: önemsiz
- Tuzak: yok
- Not: Kur TBLDOVKUR'da DOVIZ_KODU='EUR' satırındadır ve faturanın kendi tarihiyle eşleşir; dönem sonu ya da ortalama kur kullanılmaz. Tutarlar TL saklandığı için Euro'ya geçerken kura bölünür. TBLDOVKUR ile bağ fk değil tarih eşliğidir, her gün ve kod tek satır olduğu için faturaları çoğaltmaz.

```sql
SELECT SUM(f.GENELTOPLAM / k.SATIS) AS EUR_TUTARI FROM TBLFATUIRS f JOIN TBLDOVKUR k ON k.KUR_TARIH = f.TARIH AND k.DOVIZ_KODU = 'EUR' WHERE f.FTIRSIP = 1 AND f.IPTAL = 'H' AND f.TARIH >= '2026-09-01' AND f.TARIH < '2026-10-01'
```

Doğru yanıt (1 satır):

```text
EUR_TUTARI
----------
  5.419,17
```

- [ ] niyet doğru

### Q37 — 2025 arşivinde Avrupa Yakası Deposu'nun KDV hariç satış tutarı ve satışa konu olan farklı ürün sayısı ne kadardır?

- Etiketler: `archive`, `needs_values`, `needs_rule`
- Kurallar: `arsiv_2025`, `ciro`
- Tablolar: `TBLSTHAR_ARSIV`, `TBLDEPO`
- Sıra: önemsiz
- Tuzak: yok
- Not: 2025 hareketleri TBLSTHAR_ARSIV'de durur; güncel tabloya bakan sorgu 2026 rakamını söyler. Depo adı TBLDEPO.DEPO_ISIMI'nden süzülür, DEPO_KODU tahmin edilmez. Arşivde faturasız transfer ve sayım satırlarının STHAR_NF'si NULL'dır ama tip filtresi onları zaten dışarıda bırakır.

```sql
SELECT d.DEPO_KODU, d.DEPO_ISIMI, SUM(a.STHAR_GCMIK * a.STHAR_NF) AS SATIS_TUTARI, COUNT(DISTINCT a.STOK_KODU) AS URUN_CESIDI FROM TBLSTHAR_ARSIV a JOIN TBLDEPO d ON d.DEPO_KODU = a.DEPO_KODU WHERE d.DEPO_ISIMI = 'Avrupa Yakası Deposu' AND a.STHAR_HTUR = 'S' GROUP BY d.DEPO_KODU, d.DEPO_ISIMI ORDER BY d.DEPO_KODU
```

Doğru yanıt (1 satır):

```text
DEPO_KODU | DEPO_ISIMI           | SATIS_TUTARI | URUN_CESIDI
--------- + -------------------- + ------------ + -----------
DEP01     | Avrupa Yakası Deposu |    73.403,09 |          12
```

- [ ] niyet doğru

### Q38 — Gıda ürün grubundaki ürünlerin teslim tarihi henüz belirlenmemiş sipariş satırlarının sayısı ve KDV hariç toplam tutarı ne kadardır?

- Etiketler: `multi_join`, `distractor`, `needs_values`, `needs_rule`
- Kurallar: `teslim_bekleyen`
- Tablolar: `TBLSIPATRA`, `TBLSTSABIT`, `TBLSTGRUP`
- Sıra: önemsiz
- Tuzak: yok
- Not: Filtre ürün grubunun adına yazılır; cari ünvanlarındaki 'Gıda' sözcüğü aynı şey değildir, oradan süzülen başka bir cevap verir. Belirsizlik NULL demek, o yüzden IS NULL. TBLSIPATRA_TMP aynı satırların bir kısmı vazgeçilmiş ara kaydıdır, oradan sayılan satır sayısı farklı çıkar.

```sql
SELECT COUNT(*) AS BEKLEYEN_SATIR, SUM(a.TUTAR) AS BEKLEYEN_TUTAR FROM TBLSIPATRA a JOIN TBLSTSABIT t ON t.STOK_KODU = a.STOK_KODU JOIN TBLSTGRUP g ON g.GRUP_KODU = t.GRUP_KODU WHERE g.GRUP_ISIMI = 'Gıda' AND a.TESLIM_TARIHI IS NULL
```

Doğru yanıt (1 satır):

```text
BEKLEYEN_SATIR | BEKLEYEN_TUTAR
-------------- + --------------
             6 |      32.500,00
```

- [ ] niyet doğru

### Q39 — Eylül 2026'daki iptal edilmemiş satış faturalarının KDV dahil genel toplamı ile aynı ayın 600 hesap kodlu muhasebe fişi toplamları ayrı ayrı ne kadardır?

- Etiketler: `needs_values`, `needs_rule`
- Kurallar: `brut_satis`, `iptal_haric`
- Tablolar: `TBLFATUIRS`, `TBLMUHFIS`
- Sıra: önemsiz
- Tuzak: yok
- Not: Satış geliri 600 hesap koduyla izlenir; kod TBLMUHFIS'te aranır. İki sayı eşit değildir: muhasebe satırı KDV hariç gelirdir ve iptal edilen faturaların kaydı da muhasebeye düşer. Fark kapatılmaz, iki sayı yan yana raporlanır.

```sql
SELECT (SELECT SUM(f.GENELTOPLAM) FROM TBLFATUIRS f WHERE f.FTIRSIP = 1 AND f.IPTAL = 'H' AND f.TARIH >= '2026-09-01' AND f.TARIH < '2026-10-01') AS FATURA_TOPLAMI, (SELECT SUM(m.TUTAR) FROM TBLMUHFIS m WHERE m.HESAP_KODU = '600' AND m.TARIH >= '2026-09-01' AND m.TARIH < '2026-10-01') AS HESAP_600_TOPLAMI
```

Doğru yanıt (1 satır):

```text
FATURA_TOPLAMI | HESAP_600_TOPLAMI
-------------- + -----------------
    218.900,04 |        198.438,28
```

- [ ] niyet doğru

### Q40 — 2025 arşivinde Kuruyemiş ürün grubunun iadeler düşülmüş net satış miktarı kaç birimdir?

- Etiketler: `multi_join`, `archive`, `needs_values`, `needs_rule`
- Kurallar: `net_satis`, `arsiv_2025`
- Tablolar: `TBLSTHAR_ARSIV`, `TBLSTSABIT`, `TBLSTGRUP`
- Sıra: önemsiz
- Tuzak: yok
- Not: Arşiv sorusu güncel tabloya bakarsa 2026 rakamı çıkar; 2025 hareketleri TBLSTHAR_ARSIV'dedir. Net satış miktar bazlıdır ve iade düşülür, tutar hesabına girilmez. Grup adı TBLSTGRUP.GRUP_ISIMI'ndeki yazımla süzülür.

```sql
SELECT g.GRUP_ISIMI, SUM(CASE WHEN a.STHAR_HTUR = 'S' THEN a.STHAR_GCMIK ELSE 0 END) - SUM(CASE WHEN a.STHAR_HTUR = 'I' THEN a.STHAR_GCMIK ELSE 0 END) AS NET_MIKTAR FROM TBLSTHAR_ARSIV a JOIN TBLSTSABIT t ON t.STOK_KODU = a.STOK_KODU JOIN TBLSTGRUP g ON g.GRUP_KODU = t.GRUP_KODU WHERE a.STHAR_HTUR IN ('S', 'I') AND g.GRUP_ISIMI = 'Kuruyemiş' GROUP BY g.GRUP_ISIMI ORDER BY g.GRUP_ISIMI
```

Doğru yanıt (1 satır):

```text
GRUP_ISIMI | NET_MIKTAR
---------- + ----------
Kuruyemiş  |      52,17
```

- [ ] niyet doğru

