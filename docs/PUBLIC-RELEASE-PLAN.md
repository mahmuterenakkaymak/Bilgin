# Parked: public release (make-public) - run when Eren decides to publish (after the employment-contract check)

> Drafted 2026-10-24 from Eren's decisions: the public repository is AGPL-3.0, shows results on a Microsoft sample
> database, and never names or ships anything Netsis-specific. Chained to start right after Run 4. Builds on Run 1-4.

## 0. Input from earlier runs

- Read `.hybrid/report.json`, `REVIEW.md` and the eval reports of Run 3 and Run 4 first.
- Today one dataset is wired through everything: the synthetic Netsis-like world (`TBL...` tables, `profiles/netsis.json`,
  40 golden questions, `rules.json`). It stays as the **private** development set. The public repo needs a dataset
  anyone can download and reproduce.
- Rule kept: tests over a growing or configurable set assert structure, never a fixed count; tests never call a real
  model or a real SQL Server.

## 1. Goal

Make the dataset a configuration (schema, profile, rules, golden set, database), add **WideWorldImporters** (WWI,
Microsoft's SQL Server sample: sales, purchasing, stock, invoices) as a second dataset with its own golden questions,
measure Bilgin on it, and produce a clean public tree that contains no Netsis name or Netsis-like asset.

"Done" =
- `--dataset <name>` on build-db/build-index/ask/eval/serve selects everything that belongs to a dataset; the default
  stays the current synthetic set, so all existing tests keep passing unchanged.
- `--dataset wwi` works end to end on a small seeded SQLite fixture with the WWI table and column names (tests), and
  on a real WWI restore on SQL Server by hand (README steps).
- `python -m nl2sql make-public --out ../bilgin-public` writes a tree with only the generic code, the WWI dataset and
  public docs; a scan step fails the export if any forbidden term or file is found.

**Core rules (unchanged):** deterministic core, LLM as the language layer; read-only; PII masking in the executor;
nothing leaves the machine.

## 2. Scope

**In (Run 5):**

- **Dataset abstraction** (`nl2sql/datasets/`): a dataset = a folder under `datasets/<name>/` with `dataset.json`
  (display name, dialect, connection kind, default schema), `schema.json`, `rules.json`, `profile.json` (join hints,
  ERP-specific knowledge), `golden.jsonl`, optional `ambiguous.jsonl`, a builder for the test database, and a
  reference module that computes each golden answer independently in Python. Move the current synthetic set into
  `datasets/synthetic_erp/` (paths only - content unchanged) and point the old defaults at it. Index meta stores the
  dataset name; the index refuses another dataset's schema. Tests: both datasets load; existing tests unchanged and
  green.
- **Multi-schema names:** WWI uses `Sales.Orders`, `Warehouse.StockItems`, `Application.People`. Schema, policy
  (allowlist entries with schema prefix; still no cross-database, no `sys.*`), introspection (SQL Server
  `TABLE_SCHEMA`), join graph and retrieval handle `schema.table`. Tests for qualified and unqualified references,
  and for a forbidden schema.
- **WWI dataset** (`datasets/wwi/`):
  - `schema.json` for the main reporting tables (about 15-20: Sales.Customers, Sales.Orders, Sales.OrderLines,
    Sales.Invoices, Sales.InvoiceLines, Sales.CustomerTransactions, Warehouse.StockItems,
    Warehouse.StockItemTransactions, Warehouse.StockItemHoldings, Warehouse.StockGroups, Purchasing.Suppliers,
    Purchasing.PurchaseOrders, Purchasing.PurchaseOrderLines, Application.People, Application.Cities,
    Application.StateProvinces, Application.Countries, Application.DeliveryMethods) with English descriptions and a
    Turkish keyword list per table, written by the planner from Microsoft's public WWI documentation (names and types
    only - no rows copied).
  - A seeded SQLite fixture builder with the same table/column names and small fictional data, including traps:
    invoices vs orders (not every order is invoiced), credit notes, back-orders, multiple stock transactions per
    item, NULL delivery dates, a customer in two buying groups.
  - `rules.json` for WWI business terms (ciro/revenue = invoice lines excluding tax unless stated, net sales after
    credit notes, gross profit from `LineProfit`, stock on hand from holdings, late delivery, etc.).
  - `golden.jsonl`: >= 25 Turkish questions over the fixture, each with gold SQL, tags and an independent Python
    reference; the golden-vs-reference check runs for this dataset as for the synthetic one.
  - Profile: WWI's foreign keys are explicit, so the profile only adds hints the FKs do not give.
- **Eval per dataset:** reports name the dataset; `eval --compare --dataset wwi` works with the fake LLM in tests.
  The real numbers on Strata are run by hand after the run (README states the command).
- **PII on WWI:** classes for `Application.People` (FullName, EmailAddress, PhoneNumber, HashedPassword, PhotoPath ->
  denied), customer phone/fax/address; bypass cases re-run on WWI names.
- **Public export** (`make-public`, deterministic):
  - Copies the generic package, tests that do not depend on the synthetic set, `datasets/wwi/`, the web UI, docs
    marked public, LICENSE (AGPL-3.0 full text) and a public README.
  - Excludes `datasets/synthetic_erp/`, any profile or doc tied to a specific vendor ERP, `.hybrid/`, eval outputs,
    logs, `data/`, `index/`.
  - Forbidden-term scan (case-insensitive, config list in one place; at least: the vendor ERP's name, its table
    prefixes used by the synthetic set, personal paths, chat ids, e-mail addresses): any hit fails the export with
    file and line.
  - SPDX header `AGPL-3.0-only` on every exported source file; a `pytest` run inside the exported tree must pass
    (the export's own test).
- **Public README** (`docs/public/README.md`, English with a Turkish summary): what Bilgin is (local AI data analyst
  for ERP databases, data stays home), architecture, safety layers, how to run with WWI, the eval method, honest
  results table (filled with the fake-LLM structure and a placeholder for the real Strata numbers), known limits,
  license, copyright "Mahmut Eren Akkaymak". No vendor ERP name anywhere.

**Out (Run 5) -> later:** PostgreSQL + Odoo dataset (needs a dialect layer and an Odoo demo database), Topology C,
multi-user, package rename to `bilgin` (open decision), publishing (Eren pushes the exported tree by hand).

## 3. Method / architecture

```
datasets/<name>/ {dataset.json, schema.json, rules.json, profile.json, golden.jsonl, builder, reference}
        --dataset--> build-db / build-index / ask / eval / serve   (same agent, executor, policy, PII)
make-public: copy allowlist -> SPDX headers -> forbidden-term scan -> pytest in the export -> ../bilgin-public
```

## 4. Stack and environment

As Run 4. No new dependency.

## 5. Data

Synthetic and fictional only. The WWI fixture copies table and column **names** from Microsoft's public schema, never
rows. The real WWI database is restored by hand on the local SQL Server Express with the read-only login.

## 6. Interfaces

- `--dataset <name>` on build-db, build-index, ask, eval, eval-retrieval, serve
- `make-public --out <dir> [--dry-run]`

## 7. Acceptance tests

1. Both datasets load; every pre-existing test passes unchanged on the default dataset.
2. Qualified names: policy, executor, join graph and retrieval work with `Sales.Orders`; forbidden schema rejected.
3. WWI golden: every question's gold SQL equals its Python reference on the fixture; traps covered by tags.
4. WWI PII: People columns masked or denied; bypass cases pass.
5. `eval --dataset wwi --compare --llm fake` writes a report naming the dataset.
6. `make-public --dry-run` lists files; a planted forbidden term fails the export with file and line; the real export
   has SPDX headers and its own pytest passes.
7. Smoke: build-db/build-index/eval for both datasets with fakes; make-public into a temp dir.

## 8. Milestones

- **M15 - Datasets:** abstraction, move the synthetic set, `--dataset` everywhere, multi-schema names, tests 1-2.
- **M16 - WWI:** schema, fixture builder with traps, rules, golden + references, PII classes, tests 3-5.
- **M17 - Public:** make-public, scan, SPDX, LICENSE, public README, export test, tests 6-7.

Keep it to **at most ~36 tasks**.

## 9. Open questions / risks

- Moving the dataset files must not change any golden answer: the move is paths only, verified by the whole suite.
- The WWI schema is written from public documentation; the real restore may differ in details - `introspect` +
  `diff-map` (Run 3) against the real DB is the check, run by hand.
- Copyright of the WWI sample: Microsoft publishes it under MIT in `sql-server-samples`; re-check before publishing.
