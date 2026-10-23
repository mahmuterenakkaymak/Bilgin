"""The three tools the model may ask for, and the short text each one answers with.

The model never sees a Result object: it sees the columns, the first rows and the total row
count, or one line naming the failure kind and why. That is deliberate - the row count is what
tells it a query was too broad, and the error kind is what tells it whether to rewrite the SQL
(policy/sql) or give up (timeout). ``dispatch`` is the whole boundary between the conversation
and the database, so it is also where a missing argument stops instead of reaching the executor.
"""

from __future__ import annotations

from nl2sql.engine.result import Budget
from nl2sql.schema_map import doc

# Reddi anlatan satırın sabit başlangıcı; döngü buradan okuduğu için metin değişirse o da değişir.
ERROR_PREFIX = "Hata"

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

TOOLS = [GET_SCHEMA, RUN_SQL, SUBMIT_SQL]
TOOL_NAMES = [tool["function"]["name"] for tool in TOOLS]


def dispatch(name: str, args: dict, executor, schema: dict) -> str:
    """Run one tool call and return the model-readable answer; never raises for a bad call."""
    if name == "get_schema":
        return _get_schema(schema, args.get("tables"))
    if name in ("run_sql", "submit_sql"):
        return _run(name, str(args.get("sql") or ""), executor)
    return f"Bilinmeyen araç: {name}. Kullanabileceklerin: {', '.join(TOOL_NAMES)}."


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
    # döndürdüğü için döngü reddi ERROR_PREFIX ile, kabulü o sabitin yokluğuyla anlar.
    if not sql.strip():
        return "Sorgu boş: tek bir T-SQL SELECT yazın."
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
