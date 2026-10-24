"""The tools the model may ask for, and the short text each one answers with.

The model never sees a Result object: it sees the columns, the first rows and the total row
count, or one line naming the failure kind and why. That is deliberate - the row count is what
tells it a query was too broad, and the error kind is what tells it whether to rewrite the SQL
(policy/sql) or give up (timeout). ``dispatch`` is the whole boundary between the conversation
and the database, so it is also where a missing argument stops instead of reaching the executor.
"""

from __future__ import annotations

import re

from nl2sql import config
from nl2sql.engine.result import Budget
from nl2sql.graph.graph import GraphError, join_text
from nl2sql.index.search import expanded_hits
from nl2sql.schema_map import doc
from nl2sql.schema_map.rules import rule_text

# Reddi anlatan satırların sabit başlangıçları; döngü bunları okuduğu için metin değişirse burada da değişir.
ERROR_PREFIX = "Hata"
BLANK_SQL_PREFIX = "Sorgu boş"
UNKNOWN_TOOL_PREFIX = "Bilinmeyen araç"
IDENTIFIER = re.compile(r"^[A-Za-z0-9_]+$")
REFUSALS = (ERROR_PREFIX, BLANK_SQL_PREFIX, UNKNOWN_TOOL_PREFIX)

# Bağlamı eksik bir çağrının cevabı (T72): ToolContext search ile graph'ı None doğurur, yani
# rag'in arama araçları onlarsız da çağrılabilir. dispatch kötü bir çağrıda yükseltmez, o yüzden
# burada AttributeError yerine red satırı dönüyor ve döngü onu başarısız adım sayıyor.
NO_SEARCH = f"{ERROR_PREFIX}: arama indeksi yok."
NO_GRAPH = f"{ERROR_PREFIX}: join graph yok."

GET_SCHEMA = {
    "type": "function",
    "function": {
        "name": "get_schema",
        "description": (
            "Veritabanı şemasını okur. tables boş bırakılırsa tüm tabloların tek satırlık özetini, "
            "adları verilirse o tabloların kolonlarını, tiplerini, foreign key bağlantılarını ve "
            "kod anlamlarını döndürür."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "tables": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": 'Ayrıntısı istenen tablo adları, örn. ["TBLSTHAR", "TBLFATUIRS"].',
                }
            },
        },
    },
}

RUN_SQL = {
    "type": "function",
    "function": {
        "name": "run_sql",
        "description": (
            "Tek bir T-SQL SELECT sorgusunu çalıştırır ve kolonları, ilk satırları ile toplam satır "
            "sayısını döndürür. Cevap olarak kabul edilmez; son sözünü submit_sql ile ver."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "sql": {"type": "string", "description": "Çalıştırılacak tek bir T-SQL SELECT."},
            },
            "required": ["sql"],
        },
    },
}

SUBMIT_SQL = {
    "type": "function",
    "function": {
        "name": "submit_sql",
        "description": (
            "Sorunun cevabı olarak kesinleşen T-SQL sorgusunu gönderir; sorgu çalıştırılır ve sonucu "
            "gösterilir. Bu araç çağrılmadan çalışma tamamlanmış sayılmaz."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "sql": {"type": "string", "description": "Cevap olarak gönderilen tek bir T-SQL SELECT."},
            },
            "required": ["sql"],
        },
    },
}

# Aşağıdakiler `rag` modunun arama araçlarıdır (PLAN R2-5): hangi modun hangi araçları gördüğüne
# nl2sql.agent.modes karar verir, yani burada liste halinde durmaları gerekmiyor.
SEARCH_SCHEMA = {
    "type": "function",
    "function": {
        "name": "search_schema",
        "description": (
            "Sorunun anlamına en yakın tabloları arar ve her biri için adını, açıklamasını, modülünü "
            "ve kolon adlarını döndürür. Hangi tabloda olduğunu bilmediğin bir soruda ilk durak budur."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": 'Aramaya verilecek ifade, örn. "stok hareketleri satış iade".',
                },
            },
            "required": ["query"],
        },
    },
}

GET_TABLE_DETAILS = {
    "type": "function",
    "function": {
        "name": "get_table_details",
        "description": (
            "Adları verilen tabloların kolonlarını, tiplerini, foreign key bağlantılarını ve kod "
            "anlamlarını döndürür. Kolon adlarını uydurmak yerine buradan öğren."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "tables": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": 'Ayrıntısı istenen tablo adları, örn. ["TBLSTHAR", "TBLFATUIRS"].',
                }
            },
            "required": ["tables"],
        },
    },
}

FIND_JOIN_PATH = {
    "type": "function",
    "function": {
        "name": "find_join_path",
        "description": (
            "Verilen tabloları birbirine bağlayan join koşullarını bulur; hangi kolon çiftlerinin "
            "eşitleneceğini ve bağlantının güvenini söyler, güveni düşük olanları uyarıyla birlikte "
            "listeler. Birden fazla tabloyu birleştirmeden önce çağır."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "tables": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": 'Birbirine bağlanacak tablo adları, örn. ["TBLFATUIRS", "TBLCASABIT"].',
                }
            },
            "required": ["tables"],
        },
    },
}

SEARCH_RULES = {
    "type": "function",
    "function": {
        "name": "search_rules",
        "description": (
            "İş terimlerinin (ciro, net satış, iade oranı, geçen ay) bu veritabanında ne anlama "
            "geldiğini arar ve ilgili kural bloklarını döndürür. Soruda böyle bir terim varsa "
            "submit_sql öncesi neyin kastedildiğini buradan doğrula."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": 'Aramaya verilecek ifade, örn. "ağustos net ciro".',
                },
            },
            "required": ["query"],
        },
    },
}

SAMPLE_VALUES = {
    "type": "function",
    "function": {
        "name": "sample_values",
        "description": (
            "Bir kolondaki farklı değerlerden en fazla 20 örneği döndürür; 'İSTANBUL' mu 'istanbul' "
            "mu, kod 'A' mı 'H' mı gibi yazım ve kod sorularını tahmin etme, buradan bak."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "table": {"type": "string", "description": "Tablo adı, örn. \"TBLCARISUBE\"."},
                "column": {"type": "string", "description": "Kolon adı, örn. \"IL\"."},
            },
            "required": ["table", "column"],
        },
    },
}

TOOLS = [GET_SCHEMA, RUN_SQL, SUBMIT_SQL]
TOOL_NAMES = [tool["function"]["name"] for tool in TOOLS]


def dispatch(name: str, args: dict, ctx_or_executor, schema: dict | None = None) -> str:
    """Run one tool call and return the model-readable answer; never raises for a bad call."""
    # ASSUMPTION: modes buradan import ediliyor: modes, tools'u üst satırdan import ettiği için
    # burada da üstte import edilse ikisi birbirini hiç kuramaz.
    from nl2sql.agent import modes

    ctx = ctx_or_executor
    if not isinstance(ctx, modes.ToolContext):
        ctx = modes.ToolContext(executor=ctx, schema=schema or {})  # Run 1 biçimi: (executor, schema)
    known = [tool["function"]["name"] for tool in modes.get_mode(ctx.mode).tools]
    if name not in known:
        return _unknown(name, known)
    if name == "get_schema":
        # ASSUMPTION: şema özeti kap dışı: 83 tablonun özeti TOOL_RESULT_MAX_CHARS'ı aşıyor ve
        # özetin tamamı Run 1'den beri sözleşme; kap, aşağıdaki arama ve çalıştırma cevaplarında.
        return _get_schema(ctx.schema, args.get("tables"))
    if name in ("run_sql", "submit_sql"):
        answer = _run(name, str(args.get("sql") or ""), ctx.executor)
    elif name == "search_schema":
        answer = _search_schema(ctx, str(args.get("query") or ""))
    elif name == "get_table_details":
        answer = doc.table_detail(ctx.schema, _table_names(args.get("tables")))
    elif name == "search_rules":
        answer = _search_rules(ctx, str(args.get("query") or ""))
    elif name == "find_join_path":
        answer = _find_join_path(ctx, _table_names(args.get("tables")))
    elif name == "sample_values":
        answer = _sample_values(ctx, str(args.get("table") or ""), str(args.get("column") or ""))
    else:
        return _unknown(name, known)
    return cap_text(answer, config.TOOL_RESULT_MAX_CHARS)


def cap_text(text: str, limit: int) -> str:
    """Cevabı modele gitmeden önce kırp (R2-6); N kırpılan karakter sayısıdır."""
    if len(text) <= limit:
        return text
    return f"{text[:limit]}… (kırpıldı: {len(text) - limit} karakter)"


def _unknown(name: str, known: list[str]) -> str:
    return f"{UNKNOWN_TOOL_PREFIX}: {name}. Kullanabileceklerin: {', '.join(known)}."


def _search_schema(ctx, query: str) -> str:
    if ctx.search is None:
        return NO_SEARCH
    # R3-9: vuruşların join komşuları da cevaba girer; graphı olmayan bağlam genişletemez.
    hits = expanded_hits(ctx.search, query, ctx.graph, ctx.schema, config.SEARCH_K)
    if not hits:
        return "Eşleşen tablo yok."
    tables = {table["name"]: table for table in ctx.schema.get("tables", [])}
    return "\n".join(
        _hit_line(tables.get(hit.title), hit.title)
        + (" (komşu)" if hit.meta.get("komşu") else "")
        for hit in hits
    )


def _hit_line(table: dict | None, name: str) -> str:
    """Bir tablo sonucu: başlık satırı ile kolon adları, yani modelin aradığı iki bilgi birden."""
    if table is None:
        return name
    module = f" [{table['module']}]" if table.get("module") else ""
    columns = ", ".join(column["name"] for column in table.get("columns", []))
    return f"{name} — {table.get('description', '')}{module}: {columns}"


def _search_rules(ctx, query: str) -> str:
    if ctx.search is None:
        return NO_SEARCH
    hits = ctx.search.search(query, collection="rules", k=config.RULES_K)
    if not hits:
        return "Eşleşen kural yok."
    known = {rule["id"]: rule for rule in ctx.rules}
    return "\n\n".join(
        rule_text(known.get(hit.doc_id.removeprefix("rule:"), {"term": hit.title})) for hit in hits
    )


def _find_join_path(ctx, tables: list[str]) -> str:
    if ctx.graph is None:
        return NO_GRAPH
    try:
        path = ctx.graph.find_join_path(tables)
    except GraphError as error:
        return f"{ERROR_PREFIX}: {error}"
    return join_text(path)


def _sample_values(ctx, table: str, column: str) -> str:
    """R2-7: kolon adı burada süzülür; tablo adı ön denetimden geçmez, policy'ye kadar gider.

    Tablonun varlığını policy, yokluğunu allowlist söyler ve red de denetlendiği için
    uydurma bir tablo deneme izi bırakır; kolon ise şemada yoksa veritabanına hiç gitmez.
    """
    if not IDENTIFIER.match(column):
        return f"{ERROR_PREFIX}: Geçersiz kolon adı: {column}. Yalnız harf, rakam ve alt çizgi kullanın."
    columns = _column_names(ctx.schema, table)
    if columns and column.upper() not in columns:
        return f"{ERROR_PREFIX}: {column} kolonu {table} tablosunda yok. Kolonlar: {', '.join(columns)}."
    sql = (
        f"SELECT DISTINCT TOP {config.SAMPLE_VALUES_N} [{column}] FROM [{table}]"
        f" WHERE [{column}] IS NOT NULL ORDER BY [{column}]"
    )
    result = ctx.executor.execute(sql, Budget(max_rows=config.SAMPLE_VALUES_N))
    if result.error is not None:
        return f"{ERROR_PREFIX} ({result.error.kind}): {result.error.message}"
    values = [_cell(row[0]) for row in result.rows]
    if not values:
        return "Değer yok."
    return f"Değerler ({len(values)}): " + ", ".join(values)


def _column_names(schema: dict, table: str) -> list[str]:
    """Tablonun kolon adları; tablo şemada yoksa boş liste, yani kolon denetimi yapılmaz."""
    for candidate in schema.get("tables", []):
        if candidate["name"].upper() == table.strip().upper():
            return [column["name"] for column in candidate.get("columns", [])]
    return []


def answer_is_ok(answer: str) -> bool:
    """Kabul edilmiş bir cevap mı; red döngüde başarısız sayılır ve modele yeniden denetir."""
    return not answer.startswith(REFUSALS)


def _get_schema(schema: dict, tables) -> str:
    names = _table_names(tables)
    return doc.table_detail(schema, names) if names else doc.compact_text(schema)


def _table_names(tables) -> list[str]:
    """Model the list as a bare string as often as an array; both mean the same thing."""
    values = [tables] if isinstance(tables, str) else (tables or [])
    return [str(value).strip() for value in values if str(value).strip()]


def _run(name: str, sql: str, executor) -> str:
    # ASSUMPTION: submit_sql de sorguyu policy'den geçirip çalıştırır (policy'nin tek kapısı
    # executor), böylece reddedilen bir cevap modele geri söylenir; dispatch yalnız metin
    # döndürdüğü için döngü reddi REFUSALS başlangıçlarından, kabulü onların yokluğundan anlar.
    if not sql.strip():
        return f"{BLANK_SQL_PREFIX}: tek bir T-SQL SELECT yazın."
    result = executor.execute(sql, Budget())
    if result.error is not None:
        return f"{ERROR_PREFIX} ({result.error.kind}): {result.error.message}"
    answer = _answer(result)
    if name == "submit_sql":
        return "Sorgu cevap olarak alındı ve çalıştırıldı.\n" + answer
    return answer


def _answer(result) -> str:
    lines = [f"Kolonlar: {', '.join(result.columns)}"]
    if not result.rows:
        return "\n".join([*lines, "Sonuç boş (0 satır)."])
    lines += [" | ".join(_cell(value) for value in row) for row in result.rows]
    lines.append(f"Satır sayısı: {result.row_count}")
    if result.truncated:
        lines.append(f"İlk {len(result.rows)} satır gösteriliyor (toplam {result.row_count}).")
    return "\n".join(lines)


def _cell(value) -> str:
    """One value as the model reads it: NULL for missing, two decimals for money."""
    if value is None:
        return "NULL"
    if isinstance(value, float):
        return f"{value:.2f}" if abs(value - round(value, 2)) < 1e-6 else repr(round(value, 6))
    return str(value)
