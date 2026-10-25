# Golden sorular — niyet incelemesi

- Soru: 26; her sorunun altında bir `[ ] niyet doğru` kutusu var.
- Doğrular `datasets/wwi/reference.py:REFERENCES` üzerinden `generate(42)` verisiyle hesaplanır.

## Etiket sayıları

| Etiket | Soru |
| --- | ---: |
| needs_rule | 19 |
| multi_join | 8 |
| needs_values | 7 |
| trap:backorder | 1 |
| trap:credit_note | 1 |
| trap:late_receipt | 1 |
| trap:multi_transaction | 1 |
| trap:not_invoiced | 1 |
| trap:null_delivery | 1 |
| trap:two_buying_groups | 1 |

## Sorular

### Q01 — Her ülkenin adı ve o ülkeye bağlı şehir sayısı kaçtır?

- Etiketler: —
- Kurallar: —
- Tablolar: `Application.Countries`, `Application.Cities`
- Sıra: önemsiz
- Tuzak: yok
- Not: Şehir sayısı şehrin CountryID'si üzerinden ülkede toplanır; her şehir tek bir ülkeye bağlıdır. Ülke başına şehir sayısı INNER JOIN ile gelir, şehirsiz ülke listelenmez.

```sql
SELECT co.CountryName, COUNT(*) AS SEHIR_SAYISI FROM Application.Countries co JOIN Application.Cities ci ON ci.CountryID = co.CountryID GROUP BY co.CountryName ORDER BY co.CountryName
```

Doğru yanıt (4 satır):

```text
CountryName   | SEHIR_SAYISI
------------- + ------------
Canada        |            4
France        |            4
Germany       |            4
United States |            4
```

- [ ] niyet doğru

### Q02 — Henüz fatura kesilmemiş kaç sipariş var?

- Etiketler: `trap:not_invoiced`, `needs_rule`
- Kurallar: `faturalanmamis_siparis`
- Tablolar: `Sales.Orders`
- Sıra: önemsiz
- Tuzak: not_invoiced
- Not: Faturalanmamışlık InvoiceID'nin NULL olmasıdır; IS NULL ile sayılır. Siparişleri saymak ile faturaları saymak aynı şey değildir: faturalanmamış siparişler InvoiceID IS NULL ile ayrılır.

```sql
SELECT COUNT(*) AS FATURALANMAMIS FROM Sales.Orders o WHERE o.InvoiceID IS NULL
```

Doğru yanıt (1 satır):

```text
FATURALANMAMIS
--------------
             8
```

- [ ] niyet doğru

### Q03 — Kredi notları hariç, faturalanan satışların KDV hariç toplam cirosu ne kadardır?

- Etiketler: `trap:credit_note`, `needs_rule`
- Kurallar: `ciro`
- Tablolar: `Sales.InvoiceLines`, `Sales.Invoices`
- Sıra: önemsiz
- Tuzak: credit_note
- Not: Ciro fatura satırının KDV hariç ExtendedPrice'ıdır. Kredi notu satırlarının tutarı negatif olduğu için IsCreditNote = 0 filtresi atlanırsa iadeler satışa eklenir ve ciro şişer.

```sql
SELECT SUM(il.ExtendedPrice) AS CIRO FROM Sales.InvoiceLines il JOIN Sales.Invoices i ON i.InvoiceID = il.InvoiceID WHERE i.IsCreditNote = 0
```

Doğru yanıt (1 satır):

```text
     CIRO
---------
23.118,25
```

- [ ] niyet doğru

### Q04 — Geri sipariş olarak açılmış kaç sipariş var?

- Etiketler: `trap:backorder`, `needs_rule`
- Kurallar: `geri_siparis`
- Tablolar: `Sales.Orders`
- Sıra: önemsiz
- Tuzak: backorder
- Not: Geri sipariş IsBackorder = 1 ile işaretlenir; kendi başına duran siparişlerde bayrak 0'dır. Tüm siparişleri saymak geri siparişleri de katarak sayıyı büyütür.

```sql
SELECT COUNT(*) AS GERI_SIPARIS FROM Sales.Orders o WHERE o.IsBackorder = 1
```

Doğru yanıt (1 satır):

```text
GERI_SIPARIS
------------
           3
```

- [ ] niyet doğru

### Q05 — Her stok kaleminin adı ve şu anki eldeki stok miktarı nedir?

- Etiketler: `trap:multi_transaction`, `needs_rule`
- Kurallar: `eldeki_stok`
- Tablolar: `Warehouse.StockItemHoldings`, `Warehouse.StockItems`
- Sıra: önemsiz
- Tuzak: multi_transaction
- Not: Eldeki stok kalemi başına tek satır tutan StockItemHoldings.QuantityOnHand'dır. Stok hareketleri kalem başına birkaç satır olduğu için hareket tablosuyla JOIN eldeki stoğu satır başına tekrarlar.

```sql
SELECT si.StockItemName, h.QuantityOnHand FROM Warehouse.StockItemHoldings h JOIN Warehouse.StockItems si ON si.StockItemID = h.StockItemID ORDER BY si.StockItemName
```

Doğru yanıtın ilk 5 satırı (toplam 12 satır):

```text
StockItemName             | QuantityOnHand
------------------------- + --------------
Alpine Rechargeable Torch |             38
Beacon Ceramic Mug        |            107
Crestline Wool Scarf      |             43
Dovetail Cutting Board    |            180
Emberly Steel Bottle      |             39
```

- [ ] niyet doğru

### Q06 — Teslimatı henüz onaylanmamış kaç fatura var?

- Etiketler: `trap:null_delivery`
- Kurallar: —
- Tablolar: `Sales.Invoices`
- Sıra: önemsiz
- Tuzak: null_delivery
- Not: Onaylanmamışlık ConfirmedDeliveryTime'ın NULL olmasıdır; COUNT(*) NULL satırları sayar. COUNT(ConfirmedDeliveryTime) ise tam tersini yapar: NULL'ları saymadığı için bu kümede sıfır verir.

```sql
SELECT COUNT(*) AS ONAYSIZ_FATURA FROM Sales.Invoices i WHERE i.ConfirmedDeliveryTime IS NULL
```

Doğru yanıt (1 satır):

```text
ONAYSIZ_FATURA
--------------
            12
```

- [ ] niyet doğru

### Q07 — Sistemde kayıtlı kaç farklı müşteri kartı vardır?

- Etiketler: `trap:two_buying_groups`
- Kurallar: —
- Tablolar: `Sales.Customers`
- Sıra: önemsiz
- Tuzak: two_buying_groups
- Not: Müşteri kartı CustomerID ile sayılır. Aynı ticari ad iki kartta (iki ayrı satın alma grubunda) geçebildiği için ada göre saymak bu iki kartı tek sayardı.

```sql
SELECT COUNT(DISTINCT c.CustomerID) AS MUSTERI_KARTI FROM Sales.Customers c
```

Doğru yanıt (1 satır):

```text
MUSTERI_KARTI
-------------
           10
```

- [ ] niyet doğru

### Q08 — Beklenen teslimat tarihinden sonra teslim alınmış kaç satın alma satırı var?

- Etiketler: `trap:late_receipt`, `needs_rule`
- Kurallar: `geciken_teslimat`
- Tablolar: `Purchasing.PurchaseOrderLines`, `Purchasing.PurchaseOrders`
- Sıra: önemsiz
- Tuzak: late_receipt
- Not: Gecikme ReceivedDate'in siparişin ExpectedDeliveryDate'inden sonra olmasıdır. ReceivedDate NULL ise mal gelmemiştir; NULL > tarih NULL verir, satır gecikmiş sayılmaz. Tüm alınan satırları saymak gecikmeyenleri de katar.

```sql
SELECT COUNT(*) AS GECIKEN_SATIR FROM Purchasing.PurchaseOrderLines pol JOIN Purchasing.PurchaseOrders po ON po.PurchaseOrderID = pol.PurchaseOrderID WHERE pol.ReceivedDate > po.ExpectedDeliveryDate
```

Doğru yanıt (1 satır):

```text
GECIKEN_SATIR
-------------
            1
```

- [ ] niyet doğru

### Q09 — Faturalanan satışların brüt kârı (satır kârlarının toplamı) ne kadardır?

- Etiketler: `needs_rule`
- Kurallar: `brut_kar`
- Tablolar: `Sales.InvoiceLines`
- Sıra: önemsiz
- Tuzak: yok
- Not: Brüt kâr fatura satırındaki LineProfit toplamıdır; LineProfit zaten çıkarılmış kârdır, alış fiyatıyla yeniden hesaplanmaz. Kredi notu satırlarının kârı negatif olduğu için toplamdan kendiliğinden düşer.

```sql
SELECT SUM(il.LineProfit) AS BRUT_KAR FROM Sales.InvoiceLines il
```

Doğru yanıt (1 satır):

```text
 BRUT_KAR
---------
10.326,55
```

- [ ] niyet doğru

### Q10 — Her müşterinin hesap bakiyesi (tüm hesap hareketlerinin toplamı) müşteri numarası ile birlikte ne kadardır?

- Etiketler: `needs_rule`
- Kurallar: `alacak_bakiye`
- Tablolar: `Sales.CustomerTransactions`
- Sıra: önemsiz
- Tuzak: yok
- Not: Bakiye müşteri hesabındaki tüm hareketlerin (fatura borç, ödeme ve kredi notu alacak) AmountForTransaction toplamıdır. RunningTotal hareketten sonraki anlık bakiyedir, asla toplanmaz.

```sql
SELECT ct.CustomerID, SUM(ct.AmountForTransaction) AS BAKIYE FROM Sales.CustomerTransactions ct GROUP BY ct.CustomerID ORDER BY ct.CustomerID
```

Doğru yanıtın ilk 5 satırı (toplam 7 satır):

```text
CustomerID |    BAKIYE
---------- + ---------
         1 |  3.341,48
         2 | -1.167,95
         3 |      0,00
         4 |  1.282,76
         5 |    953,72
```

- [ ] niyet doğru

### Q11 — Geçen ay (Nisan 2016) düzenlenen faturaların, kredi notları hariç, KDV hariç cirosu ne kadardır?

- Etiketler: `needs_rule`
- Kurallar: `ciro`, `gecen_ay`
- Tablolar: `Sales.InvoiceLines`, `Sales.Invoices`
- Sıra: önemsiz
- Tuzak: yok
- Not: AS_OF 2016-05-31 için geçen ay Nisan 2016; aralık yarım açık yazılır. Ciro fatura tarihinde düşer, kredi notları IsCreditNote = 0 ile çıkarılır.

```sql
SELECT SUM(il.ExtendedPrice) AS CIRO FROM Sales.InvoiceLines il JOIN Sales.Invoices i ON i.InvoiceID = il.InvoiceID WHERE i.IsCreditNote = 0 AND i.InvoiceDate >= '2016-04-01' AND i.InvoiceDate < '2016-05-01'
```

Doğru yanıt (1 satır):

```text
    CIRO
--------
1.282,76
```

- [ ] niyet doğru

### Q12 — Bu yıl (2016) en çok ciro yapan 5 stok kalemi; adı ve cirosu (kredi notları hariç) nedir?

- Etiketler: `needs_rule`, `multi_join`
- Kurallar: `ciro`, `bu_yil`
- Tablolar: `Sales.InvoiceLines`, `Sales.Invoices`, `Warehouse.StockItems`
- Sıra: korunur
- Tuzak: yok
- Not: AS_OF 2016-05-31 yılı 2016; aralık yılbaşından yılsonuna yarım açık. Sıra ciroya göre, eşitlikte ürün adı ile deterministik kurulur; kredi notları cirodan çıkarılır.

```sql
SELECT TOP 5 si.StockItemName, SUM(il.ExtendedPrice) AS CIRO FROM Sales.InvoiceLines il JOIN Sales.Invoices i ON i.InvoiceID = il.InvoiceID JOIN Warehouse.StockItems si ON si.StockItemID = il.StockItemID WHERE i.IsCreditNote = 0 AND i.InvoiceDate >= '2016-01-01' AND i.InvoiceDate < '2017-01-01' GROUP BY si.StockItemName ORDER BY CIRO DESC, si.StockItemName
```

Doğru yanıt (5 satır):

```text
StockItemName          |      CIRO
---------------------- + ---------
Juniper Scented Candle | 10.876,99
Beacon Ceramic Mug     |  3.764,62
Crestline Wool Scarf   |  1.743,28
Ironbark Cast Iron Pan |  1.654,24
Emberly Steel Bottle   |  1.086,59
```

- [ ] niyet doğru

### Q13 — Bu yıl her satış temsilcisinin kaç siparişi var; temsilci numarası ile birlikte?

- Etiketler: `needs_rule`
- Kurallar: `bu_yil`
- Tablolar: `Sales.Orders`
- Sıra: önemsiz
- Tuzak: yok
- Not: AS_OF 2016-05-31 yılı 2016; sipariş tarihi OrderDate üzerinden yarım açık süzülür. Kırılım siparişi kredi edilen SalespersonPersonID'dir.

```sql
SELECT o.SalespersonPersonID, COUNT(*) AS SIPARIS FROM Sales.Orders o WHERE o.OrderDate >= '2016-01-01' AND o.OrderDate < '2017-01-01' GROUP BY o.SalespersonPersonID ORDER BY o.SalespersonPersonID
```

Doğru yanıtın ilk 5 satırı (toplam 6 satır):

```text
SalespersonPersonID | SIPARIS
------------------- + -------
                  1 |       5
                  2 |       5
                  3 |       5
                  4 |       2
                  5 |       4
```

- [ ] niyet doğru

### Q14 — Amerika Birleşik Devletleri'ndeki (United States) şehir sayısı kaçtır?

- Etiketler: `needs_values`
- Kurallar: —
- Tablolar: `Application.Cities`, `Application.Countries`
- Sıra: önemsiz
- Tuzak: yok
- Not: Şehir sayısı şehrin CountryID'si üzerinden ülkeye bağlanarak süzülür; ülke adı Application.Countries.CountryName'deki yazımla ('United States') aranır, CountryID tahmin edilmez.

```sql
SELECT COUNT(*) AS SEHIR_SAYISI FROM Application.Cities ci JOIN Application.Countries co ON co.CountryID = ci.CountryID WHERE co.CountryName = 'United States'
```

Doğru yanıt (1 satır):

```text
SEHIR_SAYISI
------------
           4
```

- [ ] niyet doğru

### Q15 — 'Courier Delivery' yöntemini kullanan kaç sipariş var?

- Etiketler: `needs_values`
- Kurallar: —
- Tablolar: `Sales.Orders`, `Application.DeliveryMethods`
- Sıra: önemsiz
- Tuzak: yok
- Not: Siparişin teslimat yöntemi DeliveryMethodID ile Application.DeliveryMethods'e bağlanır; 'Courier Delivery' yazımı yöntem adından süzülür, DeliveryMethodID tahmin edilmez.

```sql
SELECT COUNT(*) AS SIPARIS FROM Sales.Orders o JOIN Application.DeliveryMethods dm ON dm.DeliveryMethodID = o.DeliveryMethodID WHERE dm.DeliveryMethodName = 'Courier Delivery'
```

Doğru yanıt (1 satır):

```text
SIPARIS
-------
      4
```

- [ ] niyet doğru

### Q16 — 'Clothing' stok grubundaki her stok kaleminin adı ve eldeki stok miktarı nedir?

- Etiketler: `multi_join`, `needs_values`, `needs_rule`
- Kurallar: `eldeki_stok`
- Tablolar: `Warehouse.StockItemHoldings`, `Warehouse.StockItems`, `Warehouse.StockItemStockGroups`, `Warehouse.StockGroups`
- Sıra: önemsiz
- Tuzak: yok
- Not: Eldeki stok kalem başına tek satır tutan StockItemHoldings.QuantityOnHand'dır. Kalem birden çok stok grubunda olabildiği için grup filtresi StockItemStockGroups üzerinden kurulur; Clothing'de olmayan kalemler WHERE ile düşer.

```sql
SELECT si.StockItemName, h.QuantityOnHand FROM Warehouse.StockItemHoldings h JOIN Warehouse.StockItems si ON si.StockItemID = h.StockItemID JOIN Warehouse.StockItemStockGroups sig ON sig.StockItemID = h.StockItemID JOIN Warehouse.StockGroups sg ON sg.StockGroupID = sig.StockGroupID WHERE sg.StockGroupName = 'Clothing' ORDER BY si.StockItemName
```

Doğru yanıt (4 satır):

```text
StockItemName             | QuantityOnHand
------------------------- + --------------
Alpine Rechargeable Torch |             38
Beacon Ceramic Mug        |            107
Fjord Fleece Blanket      |              0
Grove Bamboo Utensils     |            156
```

- [ ] niyet doğru

### Q17 — 'Northern Traders Alliance' satın alma grubundaki kaç müşteri kartı var?

- Etiketler: `needs_values`
- Kurallar: —
- Tablolar: `Sales.Customers`, `Sales.BuyingGroups`
- Sıra: önemsiz
- Tuzak: yok
- Not: Müşteri kartı BuyingGroupID ile Sales.BuyingGroups'a bağlanır; 'Northern Traders Alliance' adı gruptan süzülür. BuyingGroupID NULL olan bağımsız müşteriler INNER JOIN ile düşer.

```sql
SELECT COUNT(*) AS MUSTERI FROM Sales.Customers c JOIN Sales.BuyingGroups bg ON bg.BuyingGroupID = c.BuyingGroupID WHERE bg.BuyingGroupName = 'Northern Traders Alliance'
```

Doğru yanıt (1 satır):

```text
MUSTERI
-------
      2
```

- [ ] niyet doğru

### Q18 — Kredi notları düşüldükten sonraki net satış toplamı (KDV hariç) ne kadardır?

- Etiketler: `needs_rule`
- Kurallar: `net_satis`
- Tablolar: `Sales.InvoiceLines`, `Sales.Invoices`
- Sıra: önemsiz
- Tuzak: yok
- Not: Net satış kredi notlarının düşüldüğü hâldir; kredi notu satırlarının ExtendedPrice'ı negatif olduğu için IsCreditNote = 0 FİLTRESİ KONMAZ, toplam kendiliğinden netleşir. IN (0, 1) iki fatura türünü de (satış ve kredi notu) içerir, hiçbirini dışarıda bırakmaz; = 0 yazmak net satışı değil ciroyu verir.

```sql
SELECT SUM(il.ExtendedPrice) AS NET_SATIS FROM Sales.InvoiceLines il JOIN Sales.Invoices i ON i.InvoiceID = il.InvoiceID WHERE i.IsCreditNote IN (0, 1)
```

Doğru yanıt (1 satır):

```text
NET_SATIS
---------
20.953,27
```

- [ ] niyet doğru

### Q19 — Kredi notları hariç, her tedarikçinin ürünlerinden elde edilen toplam ciro tedarikçi adına göre nedir?

- Etiketler: `multi_join`, `needs_rule`
- Kurallar: `ciro`
- Tablolar: `Sales.InvoiceLines`, `Sales.Invoices`, `Warehouse.StockItems`, `Purchasing.Suppliers`
- Sıra: önemsiz
- Tuzak: yok
- Not: Ciro fatura satırının KDV hariç ExtendedPrice'ıdır; kredi notları IsCreditNote = 0 ile çıkarılır. Ürünün tedarikçisi StockItems.SupplierID'dedir; fatura satırı ürünü üzerinden tedarikçiye bağlanır.

```sql
SELECT su.SupplierName, SUM(il.ExtendedPrice) AS CIRO FROM Sales.InvoiceLines il JOIN Sales.Invoices i ON i.InvoiceID = il.InvoiceID JOIN Warehouse.StockItems si ON si.StockItemID = il.StockItemID JOIN Purchasing.Suppliers su ON su.SupplierID = si.SupplierID WHERE i.IsCreditNote = 0 GROUP BY su.SupplierName ORDER BY su.SupplierName
```

Doğru yanıt (4 satır):

```text
SupplierName       |      CIRO
------------------ + ---------
Ashcombe Novelties | 11.793,11
Brightline Toys    |  1.575,89
Cedarvale Foods    |  4.450,38
Dunmore Textiles   |  5.298,87
```

- [ ] niyet doğru

### Q20 — Kredi notları hariç, bu yıl her satış temsilcisine atfedilen faturaların cirosu kişinin tam adıyla nedir?

- Etiketler: `multi_join`, `needs_rule`
- Kurallar: `ciro`, `bu_yil`
- Tablolar: `Sales.Invoices`, `Sales.InvoiceLines`, `Application.People`
- Sıra: önemsiz
- Tuzak: yok
- Not: AS_OF 2016-05-31 yılı 2016; fatura tarihi InvoiceDate üzerinden yarım açık süzülür. Ciro kredi notları hariç fatura satırından gelir; kırılım faturayı kredi edilen SalespersonPersonID'nin kişisi ve tam adıdır.

```sql
SELECT p.FullName, SUM(il.ExtendedPrice) AS CIRO FROM Sales.Invoices i JOIN Sales.InvoiceLines il ON il.InvoiceID = i.InvoiceID JOIN Application.People p ON p.PersonID = i.SalespersonPersonID WHERE i.IsCreditNote = 0 AND i.InvoiceDate >= '2016-01-01' AND i.InvoiceDate < '2017-01-01' GROUP BY p.PersonID ORDER BY p.PersonID
```

Doğru yanıtın ilk 5 satırı (toplam 6 satır):

```text
FullName       |     CIRO
-------------- + --------
Iris Sandoval  | 4.703,02
Lena Ashford   | 5.274,15
Lena Kingsley  | 7.843,23
Lena Lindqvist | 1.167,95
Reese Sandoval |   289,25
```

- [ ] niyet doğru

### Q21 — Kredi notları hariç, her teslimat yöntemiyle gönderilen faturaların cirosu yöntem adına göre nedir?

- Etiketler: `multi_join`, `needs_rule`
- Kurallar: `ciro`
- Tablolar: `Sales.Invoices`, `Sales.InvoiceLines`, `Application.DeliveryMethods`
- Sıra: önemsiz
- Tuzak: yok
- Not: Faturanın teslimat yöntemi DeliveryMethodID'dedir; ciro kredi notları hariç fatura satırından gelir ve yöntem adına göre kırılır.

```sql
SELECT dm.DeliveryMethodName, SUM(il.ExtendedPrice) AS CIRO FROM Sales.Invoices i JOIN Sales.InvoiceLines il ON il.InvoiceID = i.InvoiceID JOIN Application.DeliveryMethods dm ON dm.DeliveryMethodID = i.DeliveryMethodID WHERE i.IsCreditNote = 0 GROUP BY dm.DeliveryMethodName ORDER BY dm.DeliveryMethodName
```

Doğru yanıt (3 satır):

```text
DeliveryMethodName |      CIRO
------------------ + ---------
Cash on Collection | 13.576,00
Courier Delivery   |  5.362,79
Drop Down Delivery |  4.179,46
```

- [ ] niyet doğru

### Q22 — Bu yıl 'Collection' yöntemiyle açılan kaç sipariş var?

- Etiketler: `needs_values`, `needs_rule`
- Kurallar: `bu_yil`
- Tablolar: `Sales.Orders`, `Application.DeliveryMethods`
- Sıra: önemsiz
- Tuzak: yok
- Not: AS_OF 2016-05-31 yılı 2016; sipariş tarihi OrderDate üzerinden yarım açık süzülür. Siparişin teslimat yöntemi DeliveryMethodID ile yöntem tablosuna bağlanır; 'Collection' adı yöntem adından süzülür.

```sql
SELECT COUNT(*) AS SIPARIS FROM Sales.Orders o JOIN Application.DeliveryMethods dm ON dm.DeliveryMethodID = o.DeliveryMethodID WHERE dm.DeliveryMethodName = 'Collection' AND o.OrderDate >= '2016-01-01' AND o.OrderDate < '2017-01-01'
```

Doğru yanıt (1 satır):

```text
SIPARIS
-------
      6
```

- [ ] niyet doğru

### Q23 — Almanya'daki (Germany) eyalet sayısı kaçtır?

- Etiketler: `needs_values`
- Kurallar: —
- Tablolar: `Application.StateProvinces`, `Application.Countries`
- Sıra: önemsiz
- Tuzak: yok
- Not: Eyalet sayısı eyaletin CountryID'si üzerinden ülkeye bağlanarak süzülür; ülke adı CountryName'deki yazımla ('Germany') aranır.

```sql
SELECT COUNT(*) AS EYALET FROM Application.StateProvinces sp JOIN Application.Countries co ON co.CountryID = sp.CountryID WHERE co.CountryName = 'Germany'
```

Doğru yanıt (1 satır):

```text
EYALET
------
     2
```

- [ ] niyet doğru

### Q24 — Beklenen teslimat tarihinden sonra teslim alınmış satın alma satırlarının sayısı tedarikçi adına göre nedir?

- Etiketler: `multi_join`, `needs_rule`
- Kurallar: `geciken_teslimat`
- Tablolar: `Purchasing.PurchaseOrderLines`, `Purchasing.PurchaseOrders`, `Purchasing.Suppliers`
- Sıra: önemsiz
- Tuzak: yok
- Not: Gecikme ReceivedDate'in siparişin ExpectedDeliveryDate'inden sonra olmasıdır; ReceivedDate NULL ise mal gelmemiştir, NULL > tarih NULL verir ve satır gecikmiş sayılmaz. Tedarikçi siparişin SupplierID'sinden gelir.

```sql
SELECT su.SupplierName, COUNT(*) AS GECIKEN FROM Purchasing.PurchaseOrderLines pol JOIN Purchasing.PurchaseOrders po ON po.PurchaseOrderID = pol.PurchaseOrderID JOIN Purchasing.Suppliers su ON su.SupplierID = po.SupplierID WHERE pol.ReceivedDate > po.ExpectedDeliveryDate GROUP BY su.SupplierName ORDER BY su.SupplierName
```

Doğru yanıt (1 satır):

```text
SupplierName       | GECIKEN
------------------ + -------
Ashcombe Novelties |       1
```

- [ ] niyet doğru

### Q25 — Kredi notları hariç, faturaların faturalandığı müşterinin teslimat şehrinin ülkesine göre toplam cirosu nedir?

- Etiketler: `multi_join`, `needs_rule`
- Kurallar: `ciro`
- Tablolar: `Sales.Invoices`, `Sales.InvoiceLines`, `Sales.Customers`, `Application.Cities`, `Application.Countries`
- Sıra: önemsiz
- Tuzak: yok
- Not: Ciro kredi notları hariç fatura satırından gelir. Fatura, satın alma grubunun başına (BillToCustomerID) kesilir; ülke bu faturalanan müşterinin teslimat şehrinin (DeliveryCityID) ülkesidir, kırılım ülke adına göredir.

```sql
SELECT co.CountryName, SUM(il.ExtendedPrice) AS CIRO FROM Sales.Invoices i JOIN Sales.InvoiceLines il ON il.InvoiceID = i.InvoiceID JOIN Sales.Customers c ON c.CustomerID = i.BillToCustomerID JOIN Application.Cities ci ON ci.CityID = c.DeliveryCityID JOIN Application.Countries co ON co.CountryID = ci.CountryID WHERE i.IsCreditNote = 0 GROUP BY co.CountryName ORDER BY co.CountryName
```

Doğru yanıt (4 satır):

```text
CountryName   |     CIRO
------------- + --------
Canada        | 3.341,48
France        | 9.393,85
Germany       | 4.230,54
United States | 6.152,38
```

- [ ] niyet doğru

### Q26 — Kredi notları hariç, her stok grubundaki ürünlerin toplam cirosu grup adına göre nedir?

- Etiketler: `multi_join`, `needs_values`, `needs_rule`
- Kurallar: `ciro`
- Tablolar: `Sales.InvoiceLines`, `Sales.Invoices`, `Warehouse.StockItemStockGroups`, `Warehouse.StockGroups`
- Sıra: önemsiz
- Tuzak: yok
- Not: Ciro kredi notları hariç fatura satırından gelir. Bir ürün birden çok stok grubunda olabildiği için fatura satırı StockItemStockGroups üzerinden her ait olduğu gruba dağılır; bir ürünün cirosu her grubun toplamına ayrı ayrı yazılır.

```sql
SELECT sg.StockGroupName, SUM(il.ExtendedPrice) AS CIRO FROM Sales.InvoiceLines il JOIN Sales.Invoices i ON i.InvoiceID = il.InvoiceID JOIN Warehouse.StockItemStockGroups sig ON sig.StockItemID = il.StockItemID JOIN Warehouse.StockGroups sg ON sg.StockGroupID = sig.StockGroupID WHERE i.IsCreditNote = 0 GROUP BY sg.StockGroupName ORDER BY sg.StockGroupName
```

Doğru yanıt (4 satır):

```text
StockGroupName      |      CIRO
------------------- + ---------
Clothing            |  5.660,22
General Merchandise | 11.903,32
Novelty Items       |  6.908,47
Toys                |  1.986,72
```

- [ ] niyet doğru

