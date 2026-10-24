"""The system prompts: the rules that decide whether a run is worth measuring.

Four of them are load-bearing. The dialect and the reference date are what make "geçen ay"
land on August 2026 instead of the real calendar; the no-arithmetic rule is what keeps the
model out of the calculator's job, since every number here has to come out of SQL; and the
submit_sql rule is what turns a confident paragraph into a scoreable answer.

The three Run 2 prompts share those rules and differ only in how much of the schema they hand
over (PLAN R2-5) - and that difference is exactly what the A/B measures.
"""

from __future__ import annotations

from nl2sql import config
from nl2sql.schema_map import doc
from nl2sql.schema_map.rules import rules_text

_INTRO = """Sen doğal dilde sorulan iş sorularını Netsis veritabanının şeması üzerinde tek bir T-SQL \
SELECT sorgusuna çeviren bir veritabanı asistanısın.

"""

# Kural 1 aracın adını {schema_tool} ile alır: rag modunda get_schema yok, kolonların kaynağı
# get_table_details.
_RULES = """KURALLAR
1. Yalnızca T-SQL yaz: tek bir SELECT. Birden çok ifade, veri değiştiren her türlü komut ve \
şemada olmayan tablo veya kolon adı yasak; kolonlarını bilmediğin tablo için uydurma ad yazmak \
yerine {schema_tool} çağır.
2. Referans tarih: {as_of}. "geçen ay", "bu yıl", "son üç ay" gibi ifadeler daima bu tarihe göredir; \
bugünün tarihini kullanma. Tarih sınırlarını açık aralıkla yaz (TARIH >= 'YYYY-MM-DD' AND TARIH < \
'YYYY-MM-DD'); MONTH, YEAR veya DATEPART ile parçalama.
3. Sayıları asla sen hesaplamazsın. Toplam, fark, oran, yüzde, miktar x birim fiyat gibi her işlem \
sorgunun içinde SQL tarafından yapılır; araç sonucunda gördüğün sayıları toplayıp çıkararak yeni sayı \
üretmeyin, gerekiyorsa bunu yapan yeni bir sorgu yaz. Sonucu zihinden kontrol etmeye çalışma.
4. Sorgu hata verirse mesajı oku, sorguyu düzelt ve yeniden dene; reddedilen bir sorguda hangi \
tabloya neden izin verilmediğini mesaj söyler.
5. Cevabı yazıyla verme: son sözünü her zaman submit_sql ile bildir. submit_sql çağrılmadan biten \
çalışma başarısız sayılır; run_sql yalnızca deneme içindir.

"""

_SEARCH_FIRST = """6. Aşağıdaki liste yalnız tablo adlarını sayıyor: kolon adlarını, tabloların birbirine \
nasıl bağlandığını, iş terimlerinin ne anlama geldiğini ve kolonlardaki gerçek değerleri tahmin etme; \
search_schema (ilgili tablolar), get_table_details (kolonlar), find_join_path (join koşulları), \
search_rules (iş kuralları) ve sample_values (kolondaki değerler) araçlarını çağırıp öğren.

7. 3 veya daha fazla tabloyu birleştirmeden ÖNCE find_join_path çağır; join koşullarını uydurma, \
yolun verdiği birleştirmeyi kullan.
"""


# R5-10: açıklama sormak serbest bir davranış değil, iki koşula bağlı. Kuralı olan bir terimde
# soru sorulursa ölçümün kendisi boşa gider, o yüzden önce kural mı var diye bakmak gerekiyor.
# Seçeneklerin sayısı config.CLARIFY_MAX_OPTIONS'tan gelir; red de o sınara göre yazılır.
CLARIFY_RULES = f"""
AÇIKLAMA SORMA (ask_clarification)
- Bir iş teriminin ne anlama geldiği yukarıda tanımlıysa SORMA, tanımı kullan.
- Tanımsız bir terimde iki okunuş FARKLI sayı veriyorsa (örn. "satış" brüt mü net mi, iptaller dahil
  mi) tahmin etme ve ask_clarification çağır; iki okunuş aynı sayıya çıkıyorsa sormaya değmez.
- Arama araçların varsa sormadan önce search_rules çağır; terimin kuralı gerçekten yoksa sor.
- En fazla {config.CLARIFY_MAX_OPTIONS} kısa ve birbirini dışlayan seçenek yaz; hiçbirini sen seçme,
  cevabı kullanıcıya bırak.
"""


def _rules(as_of: str, schema_tool: str = "get_schema") -> str:
    return _RULES.format(as_of=as_of, schema_tool=schema_tool)


def system_prompt(as_of: str, compact_schema: str) -> str:
    """The turn-one system message: rules plus the one-line-per-table schema the model starts from."""
    return f"{_INTRO}{_rules(as_of)}ŞEMA ÖZETİ (ayrıntısı için get_schema)\n{compact_schema}\n"


def full_prompt(as_of: str, schema: dict) -> str:
    """`full` mode: every table in full detail in the prompt, so the model never has to look for one."""
    return (
        f"{_INTRO}{_rules(as_of)}"
        f"ŞEMA (bütün tablolar, tüm kolonları ve kod anlamları ile)\n{doc.full_text(schema)}\n"
    )


def full_rules_prompt(as_of: str, schema: dict, rules: list[dict]) -> str:
    """`full_rules` mode: `full` plus every business rule written out."""
    return f"{full_prompt(as_of, schema)}\nİŞ KURALLARI\n{rules_text(rules)}\n"


def rag_prompt(as_of: str, schema: dict) -> str:
    """`rag` mode: the same rules, a search-first rule and only the table names."""
    return (
        f"{_INTRO}{_rules(as_of, 'get_table_details')}{_SEARCH_FIRST}\n"
        f"TABLO ADLARI (modül: tablolar)\n{doc.name_list(schema)}\n"
    )
