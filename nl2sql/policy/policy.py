"""Read-only guardrail: the executor runs nothing that has not passed check().

The rules read the sqlglot parse tree, never the text: comments, brackets, casing and
whitespace are exactly how a second statement or a system object slips past a string
matcher, so only the tree decides. Denial is the default - a table is readable when the
allowlist says so and is not a CTE in scope.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlglot import exp, parse
from sqlglot.errors import SqlglotError

from nl2sql import config

PROTECTED_PREFIXES = ("XP_", "SP_")
SYSTEM_SCHEMAS = frozenset({"sys", "information_schema"})

# Statements that change data or objects; checked everywhere in the tree, because a CTE body
# can hold a DELETE ... OUTPUT and still look like a SELECT from the outside.
MUTATIONS = (
    exp.Insert,
    exp.Update,
    exp.Delete,
    exp.Merge,
    exp.Drop,
    exp.Create,
    exp.Alter,
    exp.Execute,
    exp.Command,
    exp.Grant,
    exp.Transaction,
    exp.TruncateTable,
    exp.Returning,
)


@dataclass(frozen=True)
class PolicyResult:
    ok: bool
    sql: str | None = None
    reason: str | None = None
    tables: set[str] = field(default_factory=set)


def check(sql: str, allowlist: set[str], top_n: int = config.TOP_N, pii: dict | None = None) -> PolicyResult:
    """Single read-only T-SQL SELECT, real tables from the allowlist only, TOP n enforced.

    `pii` is the {(TABLE, COLUMN): class} map of the schema (R3-6). A column whose class is in
    `config.PII_FILTER` may not be used as a filter: the mask hides a value, but WHERE/JOIN/GROUP
    BY/ORDER BY over that same value lets a question be asked about it.
    """
    if not sql or not sql.strip():
        return PolicyResult(ok=False, reason="Boş sorgu.")
    tree, reason = _single_select(sql)
    if tree is None:
        return PolicyResult(ok=False, reason=reason)
    tables: set[str] = set()
    reason = _scan(tree, frozenset(), {name.upper() for name in allowlist}, tables)
    if reason:
        return PolicyResult(ok=False, reason=reason)
    reason = _check_filter(tree, pii or {}, tables)
    if reason:
        return PolicyResult(ok=False, reason=reason)
    return PolicyResult(ok=True, sql=_with_top(tree, top_n), tables=tables)


# ----------------------------------------------------------------- statement shape


def _single_select(sql):
    try:
        statements = [s for s in parse(sql, read="tsql") if s is not None]
    except SqlglotError:
        return None, "SQL çözümlenemedi; tek bir T-SQL SELECT cümlesi yazın."
    if not statements:
        return None, "Boş sorgu."
    if len(statements) > 1:
        return None, "Tek seferde yalnızca bir sorgu çalıştırılabilir."
    tree = statements[0]
    if not isinstance(tree, (exp.Select, exp.Union)):
        return None, f"Yalnızca SELECT çalıştırılabilir; {type(tree).__name__.lower()} yasak."
    if tree.find(exp.Into):
        return None, "SELECT INTO ile yeni tablo oluşturulamaz."
    if tree.find(*MUTATIONS):
        return None, "Veri değiştiren ya da nesne oluşturan ifade yasak; yalnız okuma."
    return tree, None


# ----------------------------------------------------------------- tables in scope


def _scan(node, visible, allowed, tables):
    """İlk ihlalin kısa nedeni; None temiz demek.

    visible: bu kapsamda görünen CTE adları. Bir CTE gerçek bir tablonun adını alabilir;
    o zaman kendi gövdesindeki gerçek tablolar yine allowlist'e ve sistem denetimine
    tabi olduğu için gölgeleme hiçbir şeyi gizleyemez.
    """
    # ASSUMPTION: PLAN names UNION, so EXCEPT/INTERSECT stay denied too - default-deny covers
    # every construct the plan does not name explicitly.
    if isinstance(node, exp.SetOperation) and not isinstance(node, exp.Union):
        return "UNION dışında küme işleci kullanılamaz (EXCEPT, INTERSECT)."
    if isinstance(node, exp.Lateral):
        return "APPLY ile tablo işlevi çağrılamaz."
    if isinstance(node, exp.Anonymous) and str(node.this).upper().startswith(PROTECTED_PREFIXES):
        return "Sistem yordamları (xp_, sp_) çağrılamaz."
    if isinstance(node, (exp.Select, exp.Union, exp.Subquery)):
        visible = visible | _cte_names(node)
    if isinstance(node, exp.Table):
        return _check_table(node, visible, allowed, tables)
    for child in node.iter_expressions():
        reason = _scan(child, visible, allowed, tables)
        if reason:
            return reason
    return None


def _cte_names(node) -> frozenset[str]:
    with_node = node.args.get("with_")
    if not with_node:
        return frozenset()
    return frozenset(cte.alias.upper() for cte in with_node.expressions)


def _check_table(table, visible, allowed, tables):
    name = table.name.upper()
    if _system_part(table):
        return "Sistem kataloğu (sys, INFORMATION_SCHEMA) sorgulanamaz."
    if not isinstance(table.this, exp.Identifier):
        # fn(...), OPENROWSET, OPENQUERY, OPENDATASOURCE ve OPENJSON da bir Table düğümüdür ama
        # adları Identifier değildir. SERVER.db.dbo.T gibi çok parçalı adlar Dot olarak gelir ve
        # içinde işlev barındırmaz: oradaki sorun tablo işlevi değil, veritabanı sınırının aşılması.
        if isinstance(table.this, exp.Dot) and not table.find(exp.Anonymous, exp.Func):
            return f"Tablo adı {name} başka veritabanı ya da sunucu taşıyamaz."
        return (
            "Tablo işlevi ve satır kümesi işlevleri (OPENROWSET, OPENQUERY, OPENDATASOURCE, "
            "OPENJSON, fn(...)) yasak; yalnız izinli tablolar okunabilir."
        )
    if table.catalog or table.db:
        return f"Tablo adı {name} başka veritabanı ya da sunucu taşıyamaz."
    if name in visible:
        return None
    if name.startswith(PROTECTED_PREFIXES):
        return "Sistem yordamları (xp_, sp_) çağrılamaz."
    if name not in allowed:
        return f"İzin verilmeyen tablo: {name}."
    tables.add(name)
    return None


def _system_part(table) -> str:
    parts = (table.catalog, table.db, table.name)
    return next((part for part in parts if part.lower() in SYSTEM_SCHEMAS), "")


# ----------------------------------------------------------------- filter side channels (R3-6)


def _check_filter(tree, marks, tables):
    """Bir pii kolonu filtre olarak kullanılamaz; sınıfı config.PII_FILTER'da olmayanlar serbest."""
    filtered = {pair for pair, cls in marks.items() if cls in config.PII_FILTER}
    if not filtered:
        return None
    names = {column for _, column in filtered}
    aliases = _aliases(tree, tables)
    for node in _filter_nodes(tree):
        for column in node.find_all(exp.Column):
            if column.name.upper() in names:
                guilty = _filter_target(column, aliases, filtered, tables)
                if guilty:
                    return f"Filtrede PII kolon: {guilty}."
    return None


def _filter_nodes(tree):
    """Filtre sayılan yerler: WHERE, JOIN ON, GROUP BY, ORDER BY."""
    yield from tree.find_all(exp.Where, exp.Group, exp.Order)
    for join in tree.find_all(exp.Join):
        on = join.args.get("on")
        if on is not None:
            yield on


def _aliases(tree, tables) -> dict[str, str]:
    """Takma ad -> gerçek tablo. CTE adı gerçek tablo olmadığı için haritaya girmez."""
    return {
        (table.alias or table.name).upper(): table.name.upper()
        for table in tree.find_all(exp.Table)
        if table.name.upper() in tables
    }


def _filter_target(column, aliases, marks, tables) -> str:
    """Kolonun ait olduğu TABLO.KOLON; adı çözülemeyen önek (CTE) sorgunun gerçek tablolarında aranır."""
    name = column.name.upper()
    if column.table:
        table = aliases.get(column.table.upper())
        # Takma adı çözülen bir kolonun kaynağı bilinir: orada pii yoksa arama daha ileri gitmez.
        if table:
            return f"{table}.{name}" if (table, name) in marks else ""
    # ASSUMPTION: ad çözülür, iz sürülmez; adı çakışan kolon sorgunun dokunduğu tabloda pii ise
    # hangisi olduğu bilinemediği için reddedilir (fail closed).
    return next((f"{table}.{name}" for table in sorted(tables) if (table, name) in marks), "")


# ----------------------------------------------------------------- row cap


def _with_top(tree, top_n):
    """Satır sayısını sınırlar: en dıştaki SELECT'e TOP eklenir, UNION dışarıdan sarılır."""
    if isinstance(tree, exp.Select):
        _cap_rows(tree, top_n)
        return tree.sql(dialect="tsql")
    # ASSUMPTION: T-SQL türetilmiş tabloda ORDER BY'yı TOP olmadan reddettiği için UNION'ın
    # sıralaması dış sarmalayıcıya taşınır; sonuç sırası değişmez.
    order = tree.args.pop("order", None)
    inner = exp.Subquery(this=tree, alias=exp.TableAlias(this=exp.Identifier(this="_q")))
    wrapper = exp.select("*").from_(inner)
    wrapper.set("limit", exp.Limit(expression=exp.Literal.number(top_n)))
    if order is not None:
        wrapper.set("order", order)
    return wrapper.sql(dialect="tsql")


def _cap_rows(tree, top_n) -> None:
    """En dıştaki SELECT'i en fazla top_n satırda bırakır; ağacı yerinde değiştirir.

    Mevcut bir TOP/FETCH sayısı ikisinin küçüğüne çekilir; @n gibi çözümlenemeyen bir sayı
    tavana sabitlenir. OFFSET tek başına satır sayısını sınırlamadığı için yanına FETCH NEXT
    eklenir.
    """
    cap = exp.Literal.number(top_n)
    limit = tree.args.get("limit")
    if isinstance(limit, exp.Fetch):
        key = "count"
    elif limit is not None:
        key = "expression"
    else:
        if tree.args.get("offset") is not None:
            fetch = exp.Fetch(direction="NEXT", count=cap, limit_options=exp.LimitOptions(rows=True))
            tree.set("limit", fetch)
        else:
            tree.set("limit", exp.Limit(expression=cap))
        return
    if not _within_cap(limit.args.get(key), top_n):
        limit.set(key, cap)
        # TOP 1000 PERCENT ya da WITH TIES yerine düz bir sayı: tavan geçerli kalsın.
        limit.set("limit_options", None)


def _within_cap(node, top_n) -> bool:
    return isinstance(node, exp.Literal) and not node.is_string and float(node.this) <= top_n
