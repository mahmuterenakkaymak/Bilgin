# NL2SQL (Bilgin) - Run 4: public dataset (WideWorldImporters) and small-model readiness (27B)

> Drafted 2026-10-24 from Eren's priorities: first measure Bilgin on a **public database** anyone can reproduce and
> on the **customer-box model** (Qwen3.8-27B in a 16-24K context); the web UI is Run 5, the public release export is
> Run 6, Odoo/PostgreSQL is later. Chained to start right after Run 3. Builds on Run 1-3.

## 0. Input from earlier runs

- Read `.hybrid/report.json`, `REVIEW.md` and the eval reports of Run 3 first (Excel import, live schema, PII masking,
  retrieval improvements, `--mode auto`). Build on those interfaces.
- Run 2 A/B on Strata (Qwen3.8-Flash-Next, 256K): `full_rules` 31/40 (26K tokens), `rag` 30/40 (6.5K tokens).
  Rules are worth +8 questions; retrieval recall@5 0.67.
- Today one dataset is wired through everything: the synthetic ERP-like world (`TBL...` tables, its profile, 40
  golden questions, `rules.json`). It stays as the **private** development set.
- Today the model is one endpoint in config. The customer-box question (does a 27B dense model in 16-24K context
  still answer?) cannot be measured cleanly yet.
- Rule kept: tests over a growing or configurable set assert structure, never a fixed count; tests never call a real
  model or a real SQL Server.

## 1. Goal

Make the dataset and the model configurations, add **WideWorldImporters** (WWI, Microsoft's SQL Server sample:
sales, purchasing, stock, invoices) as a second dataset with its own golden questions, and make the eval compare
models under a context budget - so the real runs after this one answer: "Flash-Next vs 27B, 16K vs 24K, full_rules
vs rag, on a public DB and on the private set".

"Done" =
- `--dataset <name>` on build-db/build-index/ask/eval/eval-retrieval selects everything that belongs to a dataset;
  the default stays the synthetic set, so all existing tests keep passing unchanged.
- `--dataset wwi` works end to end on a small seeded SQLite fixture with WWI's table and column names (tests), and on
  a real WWI restore on SQL Server by hand (README steps).
- `--model <profile>` selects endpoint, model id, API key variable and **context budget**; the agent never sends a
  prompt above the budget; `eval --compare --models a,b --modes full_rules,rag --dataset X` writes one table
  (model x mode: accuracy, answered, peak tokens vs budget, overflows, seconds per question).

**Core rules (unchanged):** deterministic core, LLM as the language layer; read-only; PII masking in the executor;
nothing leaves the machine.

## 2. Scope

**In (Run 4):**

- **Dataset abstraction** (`bilgin/datasets/`): a dataset = a folder `datasets/<name>/` with `dataset.json` (display
  name, dialect, connection kind, default schema), `schema.json`, `rules.json`, `profile.json` (join hints, ERP
  knowledge), `golden.jsonl`, a builder for the test database and a reference module that computes each golden answer
  independently in Python. Move the current synthetic set into `datasets/synthetic_erp/` (paths only - content
  unchanged) and point the old defaults at it. Index meta stores the dataset name; the index refuses another dataset's
  schema. Tests: both datasets load; every existing test unchanged and green.
- **Multi-schema names:** WWI uses `Sales.Orders`, `Warehouse.StockItems`, `Application.People`. Schema, policy
  (allowlist entries with the schema prefix; still no cross-database, no `sys.*`), introspection (SQL Server
  `TABLE_SCHEMA`), join graph and retrieval handle `schema.table`. Tests for qualified and unqualified references and
  a forbidden schema.
- **WWI dataset** (`datasets/wwi/`):
  - `schema.json` for the main reporting tables (about 15-20: Sales.Customers, Sales.Orders, Sales.OrderLines,
    Sales.Invoices, Sales.InvoiceLines, Sales.CustomerTransactions, Warehouse.StockItems,
    Warehouse.StockItemTransactions, Warehouse.StockItemHoldings, Warehouse.StockGroups, Purchasing.Suppliers,
    Purchasing.PurchaseOrders, Purchasing.PurchaseOrderLines, Application.People, Application.Cities,
    Application.StateProvinces, Application.Countries, Application.DeliveryMethods) with English descriptions and
    Turkish keywords per table, written from Microsoft's public WWI documentation (names and types only, no rows).
  - A seeded SQLite fixture builder with the same names and small fictional data, with traps: orders vs invoices (not
    every order is invoiced), credit notes, back-orders, several stock transactions per item, NULL delivery dates, a
    customer in two buying groups.
  - `rules.json` for WWI business terms (ciro/revenue = invoice lines excluding tax unless stated, net sales after
    credit notes, gross profit from `LineProfit`, stock on hand from holdings, late delivery, ...).
  - `golden.jsonl`: >= 25 Turkish questions with gold SQL, tags and an independent Python reference; the
    golden-vs-reference check runs for this dataset as for the synthetic one.
  - PII classes for `Application.People` (FullName, EmailAddress, PhoneNumber; HashedPassword and PhotoPath denied)
    and customer phone/fax/address; the PII bypass cases re-run on WWI names.
- **Model profiles** (`config/models.json`, read by `bilgin/agent/llm.py`): name -> base URL, model id, API key
  environment variable (never the key itself), context budget in tokens, max output tokens, optional sampling.
  Shipped profiles: `strata` (Flash-Next, http://127.0.0.1:8080/v1, large budget), `qwen27b-24k` and `qwen27b-16k`
  (Qwen3.8-27B on Unsloth Studio, http://127.0.0.1:8888/v1, key in `UNSLOTH_API_KEY`, budgets 24576 / 16384).
  `--model <profile>` on ask/eval/serve; the default stays today's endpoint.
- **Context budget, enforced by code:** before every LLM call the agent counts the prompt tokens (the same estimator
  `--mode auto` uses) and, when over budget, first trims old tool results (keeps the latest, cuts long ones with a
  marker), then stops with `context_overflow` instead of sending - never relies on the server to truncate. `--mode
  auto` uses the profile's budget instead of the global constant. Every run records peak prompt tokens and overflow
  count. Tests with a fake LLM and tiny budgets.
- **Model comparison eval:** `eval --compare --models strata,qwen27b-16k --modes full_rules,rag --dataset wwi
  [--repeat N]` runs every combination and writes `eval_out/compare_<dataset>_<timestamp>.md|json`: per model x mode
  accuracy (mean/min/max over repeats), answered %, peak tokens vs budget, overflows, seconds per question, per-tag
  scores. Before each model's block the eval checks the endpoint and stops with a clear message if it is not up (the
  GPU holds one heavy model at a time - Strata and the 27B are run one after another by hand). Fake LLM tests.
- **README "27B test" section:** how to switch the GPU to creative mode, start Qwen3.8-27B in Unsloth Studio with the
  matching context (`--context-length 16384` / `24576`, `-np 1`), run the WWI and synthetic comparisons, and where the
  report lands.

**Out (Run 4) -> later:** web UI (Run 5), public release export (Run 6), PostgreSQL + Odoo (later), Topology C,
multi-user, package rename.

## 3. Method / architecture

```
datasets/<name>/ {dataset.json, schema.json, rules.json, profile.json, golden.jsonl, builder, reference}
config/models.json {strata, qwen27b-24k, qwen27b-16k, ...}
      --dataset --model--> build-db / build-index / ask / eval   (same agent, executor, policy, PII)
agent: prompt -> token count -> over budget? trim tool results -> still over? stop (context_overflow)
eval --compare --models a,b --modes m1,m2 --dataset d -> model x mode table
```

## 4. Stack and environment

As Run 3. No new dependency. Tests: fake LLM and fake embedder only.

## 5. Data

Synthetic and fictional only. The WWI fixture copies table and column **names** from Microsoft's public schema,
never rows. The real WWI database is restored by hand on the local SQL Server Express with the read-only login.

## 6. Interfaces

- `--dataset <name>` on build-db, build-index, ask, eval, eval-retrieval
- `--model <profile>` on ask, eval; `eval --compare --models a,b --modes m1,m2 [--repeat N]`

## 7. Acceptance tests

1. Both datasets load; every pre-existing test passes unchanged on the default dataset.
2. Qualified names: policy, executor, join graph and retrieval work with `Sales.Orders`; a forbidden schema is
   rejected.
3. WWI golden: every gold SQL equals its Python reference on the fixture; traps covered by tags.
4. WWI PII: People columns masked or denied; bypass cases pass.
5. Model profiles: unknown profile -> clear error; API key read from the named variable; no key in any file.
6. Budget: with a tiny budget the agent trims tool results, then stops with `context_overflow`; peak tokens recorded;
   `--mode auto` follows the profile budget.
7. `eval --compare --models fakeA,fakeB --modes full_rules,rag --dataset wwi --llm fake` writes the model x mode
   table; an unreachable endpoint stops that block with a message.
8. Smoke: build-db/build-index/eval for both datasets with fakes (smokes for later milestones tagged with "from").

## 8. Milestones

- **M11 - Datasets:** abstraction, move the synthetic set, `--dataset` everywhere, multi-schema names, tests 1-2.
- **M12 - WWI:** schema, fixture builder with traps, rules, golden + references, PII classes, tests 3-4.
- **M13 - Models + budget:** profiles, budget enforcement and trimming, auto mode per profile, compare eval, README
  27B section, tests 5-8.

Keep it to **at most ~36 tasks**.

## 9. Open questions / risks

- Moving the dataset files must not change any golden answer: the move is paths only, verified by the whole suite.
- The WWI schema is written from public documentation; the real restore may differ - `introspect` + `diff-map` (Run 3)
  against the real DB is the check, run by hand.
- Copyright of the WWI sample: Microsoft publishes it under MIT in `sql-server-samples`; re-check before publishing.
- A 27B in 16K may only work in `rag` mode; that is a result, not a failure to hide.
