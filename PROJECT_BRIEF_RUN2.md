# NL2SQL - Run 2: Phase 2 - retrieval (RAG) + join graph, proven by an A/B eval

> Builds on Run 1 (Phase 0 kill gate + CLI, 30 tasks, all green). Plan rule for this phase: **"if RAG does not raise
> accuracy by a measured number, there is no RAG."** So this run builds retrieval *and* the measurement that can
> reject it.

## 0. What Run 1 taught us (input for this run)

- Real eval on local Strata (Qwen3.8-Flash-Next): **7/10**, 2-6 tool calls, 5-31 s per question, peak prompt
  **4.1K tokens**.
- All 3 failures were **business-definition ambiguity, not SQL skill**: Q03 "net ciro" (model subtracted returns,
  golden did not), Q04 "her plasiyer" (model kept a NULL-plasiyer group via LEFT JOIN), Q10 "iade oranı" (model used
  amount, golden used quantity). -> a **business rules** layer is needed, and must be measurable.
- 10 tables fit in a 4K prompt, so retrieval cannot help on that world. To measure RAG the schema must be big and
  confusing like a real ERP (hundreds of tables, similar names, the same column names everywhere).

## 1. Goal

One command prints a comparison table: the same 40 golden questions answered in three modes -
`full` (Run 1: whole schema in the prompt), `full_rules` (whole schema + all business rules in the prompt) and
`rag` (no schema in the prompt; the model uses search tools) - with score, per-tag scores, peak/median prompt tokens,
tool calls and seconds per mode, plus a retrieval-only metric (recall@k of the right tables, no LLM involved).

"Done" = `eval --compare --llm fake` and `eval-retrieval --embed fake` green in tests; against Strata + the local
embedding server the three-mode report exists in `eval_out/compare/latest/report.md`.

**Core rules (unchanged from Run 1):** LLM only writes SQL, never computes; every execution goes through the
policy inside the executor (including the new `sample_values` tool); golden answers checked against an independent
Python reference; read-only; tests never call a real model or a real embedding server.

## 2. Scope

**In (Run 2):**

- **Bigger, confusing schema (keep the Run 1 world intact).** Grow `schema/schema.json` from 10 to **~80 tables**:
  - The 10 Run 1 tables and their data are **unchanged** (same seed -> same rows; new tables use their own random
    stream), so Q01-Q10 golden SQL and references stay valid and Run 1 tests stay green.
  - ~6 new **data** tables that new questions need, e.g. a price list (`TBLSTOKFIAT`), an archive of old stock
    movements from 2025 (`TBLSTHAR_ARSIV`, same columns as TBLSTHAR - a distractor that is *right* only for 2025
    questions), currency rates (`TBLDOVKUR`), customer addresses/branches (`TBLCARISUBE`), sales campaigns
    (`TBLKAMPANYA`), a general-ledger voucher table (`TBLMUHFIS`).
  - ~65 **schema-only distractor** tables from other modules (Muhasebe, Banka, Çek/Senet, Personel, Üretim, Servis,
    İthalat, Sabit Kıymet...) with Netsis-style coded names and the same frequent column names (CARI_KOD, STOK_KODU,
    TARIH, TUTAR, ACIKLAMA), some near-duplicates of real ones (`TBLSTHAR_LOG`, `TBLFATUIRS_TASLAK`). They exist in
    the DB (created, mostly empty or a few rows), so choosing one gives a wrong answer, not an error.
  - The compact full-schema text must be measured and reported (expected ~20-35K tokens): this is the context cost
    of `full` mode and the reason a 27B model with a 16-24K budget needs retrieval.
  - Fictional tables and data; do not copy a real Netsis schema.
- **Business rules** (`schema/rules.json`): 10-15 term definitions in Turkish (term, synonyms, definition, SQL hint,
  tables), e.g. brüt satış / net satış (iade düşülür, miktar), ciro (KDV hariç, STHAR_NF x miktar; whether returns are
  subtracted is stated explicitly), iade oranı (quantity based), iptal faturalar varsayılan olarak hariç, plasiyersiz
  cariler raporlarda ayrı gösterilmez, "geçen ay"/"bu yıl" relative to AS_OF, alıcı = CARI_TIP A or H. The rules must
  agree with the golden SQL (a test runs every rule's tagged golden questions). Q03/Q04/Q10 question texts stay as they
  are - the rules resolve their ambiguity.
- **40 golden questions** = Q01-Q10 + **30 new** (Q11-Q40), each with golden T-SQL, an independent Python reference,
  `ordered` flag, `review: pending`, and tags: `trap:<name>`, `needs_rule`, `multi_join` (3+ tables, path matters),
  `distractor` (a near-duplicate table exists), `needs_values` (a filter value the model must look up, e.g. a group
  name or city spelling), `archive` (2025 data). Plus `requires_tables` for the retrieval metric. At least 8 questions
  per tag where it makes sense. Eval questions must never appear in any index (no leakage).
- **Retrieval index** (`bilgin/index/`), no new dependencies:
  - `Embedder` interface: `OpenAIEmbedder` (OpenAI-compatible `/v1/embeddings`; env `BILGIN_EMBED_BASE_URL` default
    `http://127.0.0.1:8891/v1`, `BILGIN_EMBED_MODEL`; batching; clear error when unreachable) and `FakeEmbedder`
    (deterministic hashed bag-of-words, for tests).
  - Documents: one per table (name, module, description, columns with descriptions and code values, keywords), one
    per rule. An `examples` collection exists but stays empty in this run (filled from approved history later).
  - Hybrid search: dense cosine (pure Python, brute force - fine for a few hundred docs) + lexical BM25 (pure Python,
    Turkish-aware lowercasing: İ->i, I->ı) fused with reciprocal rank fusion; k from config.
  - `VectorStore` interface with a file store (`index/` folder: docs JSON + vectors) and a content hash of the schema/
    rules; a stale index is rebuilt or refused with a clear message. (A real vector DB such as LanceDB can be plugged
    in behind the interface later; at this scale it would only add an install dependency.)
  - `python -m bilgin build-index [--embed fake|openai]`.
- **Join graph** (`bilgin/graph/`, pure Python): edges from schema `fk` (confidence 1.0) plus inferred edges from an
  **ERP profile** file (`profiles/netsis.json`: column-name pairs such as CARI_KOD<->CARI_KODU, FISNO<->FATIRS_NO,
  STOK_KODU<->STOK_KODU, with confidence 0.5-0.9) - no ERP-specific rule hard-coded in Python. Shortest path weighted
  by confidence; `find_join_path(tables)` returns the join conditions connecting all requested tables (merge of
  pairwise shortest paths) and flags low-confidence edges. Test: the joins of every `multi_join` golden SQL are found.
- **Tools per mode** (agent loop from Run 1 stays; tool set and system prompt depend on the mode):
  - `full`: as Run 1 (`get_schema`, `run_sql`, `submit_sql`).
  - `full_rules`: as `full`, all rules appended to the system prompt.
  - `rag`: `search_schema(query)` (top-k table summaries), `get_table_details(tables)`, `find_join_path(tables)`,
    `search_rules(query)`, `sample_values(table, column)` (DISTINCT TOP 20 through the executor and policy; allowlisted
    table/column only), `run_sql`, `submit_sql`. Only a short table list header in the system prompt, no full schema.
  - Tool results are capped (config, chars) so the context budget stays predictable.
- **Eval A/B**:
  - `eval --mode full|full_rules|rag [--llm fake|openai] [--only Q03] [--tag needs_rule]` -> per-mode report as Run 1.
  - `eval --compare [--llm ...]` runs the three modes on the same questions (or reuses a same-config latest run) and
    writes `eval_out/compare/<ts>/report.md|json`: score per mode, per-tag score per mode, context peak/median, tool
    calls, seconds, per-question flips between modes, and the verdict line: RAG kept only if `rag` >= `full_rules` on
    score **and** its peak context is lower; otherwise the report says so.
  - `eval-retrieval [--embed fake|openai] [--k 5]`: for each question, recall@k of `requires_tables` for
    `search_schema(question)`, and the same for BM25-only and dense-only, so a retrieval problem is separated from a
    generation problem. No LLM.
  - `eval/REVIEW.md` generated for Eren: every question, its tags, golden SQL, first rows of the reference result and
    notes - to review intent (agent-written questions).
- **CLI**: `ask` gets `--mode` (default `rag` when an index exists, else `full`) and prints the retrieval steps too.

**Out (Run 2):** Excel import, INFORMATION_SCHEMA merge, reranker, PII masking, web UI, Topology C, real SQL Server
run, LanceDB/Qdrant, fine-tuning, multi-turn chat, query history into `examples`.

## 3. Method / architecture

```
schema.json + rules.json --build-index--> index/ (docs, vectors, BM25 stats, hash)       profiles/netsis.json
                                               |                                              |
ask/eval --mode rag -> agent loop -> tools: search_schema, search_rules (hybrid search)   join graph
                                          get_table_details, find_join_path, sample_values -> Executor (policy)
```
- New packages: `bilgin/index`, `bilgin/graph`; changes in `agent` (mode-aware tools/prompt), `eval` (modes,
  compare, retrieval metric), `cli`.
- Config at the top of `bilgin/config.py`: k, RRF constant, tool result cap, embed endpoint/model/batch, index path,
  profile path, default mode.

## 4. Stack and environment

- Same as Run 1: Python 3.11, `.venv` with sqlglot 30.24.0, openai 3.37.0, pytest 9.1.1, pyodbc 5.3.0 -
  **no new dependencies** (embedding client via the `openai` SDK; vectors, BM25 and graph in the standard library).
- Local embedding server for real runs (already running, started by hand): llama.cpp `llama-server --embedding`
  with EmbeddingGemma-300M Q8_0 on **CPU**, `http://127.0.0.1:8891/v1`, 768 dims. (EmbeddingGemma is under Gemma
  terms; the product target is bge-m3 (MIT) - the Embedder interface keeps that a config change.)
- LLM for real runs: Strata `127.0.0.1:8080`. Tests: fakes only.

## 5. Data

Synthetic, seeded, fictional. Privacy class: public/synthetic.

## 6. Interfaces

- `python -m bilgin build-db [--seed 42]` (now ~80 tables), `build-index [--embed fake|openai]`
- `python -m bilgin ask "<soru>" [--mode full|full_rules|rag] [--llm ...]`
- `python -m bilgin eval [--mode ...] [--tag ...] [--only ...] [--llm ...]`, `eval --compare`, `eval-retrieval`
- Env (new): `BILGIN_EMBED_BASE_URL`, `BILGIN_EMBED_MODEL`.

## 7. Acceptance tests

1. Run 1 world unchanged: rows of the 10 original tables identical to Run 1 for seed 42; Q01-Q10 references still
   match; all Run 1 tests green.
2. ~80 tables in schema.json and the DB; every distractor exists; compact full-schema token estimate reported.
3. All 40 golden SQLs pass policy, run and equal their Python reference; every tag has its questions; rules agree with
   their tagged golden questions.
4. No eval question text (or near copy) in the index.
5. Hybrid search: with FakeEmbedder, known queries return the right table in top-k; RRF fusion unit tests; Turkish
   case folding (İSTANBUL / istanbul, ILAÇ / ılaç) tests; stale index detected.
6. Join graph: fk + profile edges, confidence weighting, all `multi_join` golden joins found, unknown table -> clear
   error.
7. `sample_values` goes through the policy (forbidden table rejected) and returns at most 20 distinct values.
8. Agent in `rag` mode with FakeLLM: search -> details -> join path -> run -> submit pass path; tool results capped.
9. `eval --compare --llm fake` writes the compare report with all fields and the verdict line;
   `eval-retrieval --embed fake` prints recall@k for hybrid, BM25-only and dense-only.
10. Smoke (clean checkout): build-db, build-index --embed fake, eval --compare --llm fake, eval-retrieval --embed fake
    exit 0. Smokes for commands delivered in a later milestone are tagged with `"from"` in checks.json.

## 8. Milestones

- **M4 - Bigger world + rules + questions:** schema growth (data + distractor tables), rules.json, Q11-Q40 with
  references and tags, REVIEW.md generator, tests 1-3.
- **M5 - Retrieval + graph:** Embedder, file VectorStore, BM25, hybrid search, build-index, join graph + ERP profile,
  eval-retrieval, tests 4-6.
- **M6 - RAG agent + A/B eval:** mode-aware tools and prompts, sample_values, compare report, CLI `--mode`, README
  update, tests 7-10.

Keep it to **at most ~35 tasks**.

## 9. Open questions / risks

- Questions, rules and golden SQL are agent-written; Eren reviews `eval/REVIEW.md`. The Python reference protects
  numbers, not intent.
- EmbeddingGemma vs bge-m3 quality on Turkish ERP terms is unknown; `eval-retrieval` is the place to compare later.
- If `rag` loses to `full_rules`, that is a valid result (the plan says: then no RAG, or RAG only for very large
  schemas) - do not tune the eval to make RAG win.
