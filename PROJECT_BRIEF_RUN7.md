# NL2SQL (Bilgin) - Run 7: conversations - follow-up questions in one session

> Drafted 2026-10-25 from Eren's request: "Rapor ya da soru-cevap fark etmez, girdikten sonra 2.-3. cümle ile
> düzenlenebilmeli. 'Son satışın tutarı ne?' -> 'Bu müşteriye başka ne sattık?' Tek session'da üst üste soru-cevap
> olmalı." Runs after Run 6 (users, roles, sessions, per-user history, onboarding a new database from a template),
> before Run 8 (English, Windows service). Product name **Bilgin** (package and CLI stay `nl2sql`). Never write the
> names of a specific commercial ERP product or of the owner's company in code, docs, UI text or test data.

## 0. Input from earlier runs

- Read `.hybrid/report.json`, `REVIEW.md`, `README.md` (Run 3-6 sections), `docs/BILGIN-TEKNIK-DOKUMAN.md` and
  `PROJECT_BRIEF_RUN6.md` first. Today every question is independent: `ask_payload(session, question, mode, choice)`
  (`nl2sql/app/ask.py`) runs the agent loop (`nl2sql/agent/loop.py`) with no memory of the previous answer; the UI
  shows one answer card at a time; history replay (`POST /api/replay/{audit_id}`) reruns a stored SQL without the
  model. Clarification (`needs_clarification` + `choice`) is the only two-step exchange.
- Kept: the LLM never owns a number (number guard, facts by code), no technical column names in sentences, every
  execution through the policy and the read-only executor, PII masked before the model sees a row, nothing leaves the
  machine, tests never call a real model or a real SQL Server, tests over sets assert structure not counts.
- Run 6 made `create_app(..., users=None)` the single-user mode for the existing tests; keep it, and keep the
  existing tests unedited.

## 1. Goal

A user talks to Bilgin in a **conversation**: the second and third question can lean on the earlier ones, whether the
earlier turn was a plain answer or a report (table + chart).

- **Follow-up on an entity:** "Son satışın tutarı ne?" -> "Bu müşteriye başka ne sattık?" (the customer comes from the
  previous result) -> "Bunlardan hangisi en çok ciro yaptı?" (the set comes from the previous result).
- **Refining a report:** "2016 aylık ciro" -> "Sadece Texas" -> "Bunu geçen yılla karşılaştır" -> "Grafiği çubuk yap".
- **Starting over** is explicit ("Yeni konuşma") or automatic when the new question clearly stands alone.

"Done" =
- In the UI the answers of one conversation stack as a thread (question, answer card, question, answer card, ...);
  the input stays under the last answer; "Yeni konuşma" starts a clean one. A reload keeps the open conversation.
- A follow-up's answer shows, in its evidence, how it was read: "Önceki cevaptan: müşteri 832 (Tailspin Toys
  (Head Office))" - which earlier turn and which values it used.
- A new **follow-up golden set** on `wwi_real` (chains of 2-3 questions, golden SQL per turn) is measured by `eval`:
  turn accuracy and chain accuracy, Flash-Next `full_rules` at least 80 % of turns on the first build.

## 2. Scope

**In (Run 7):**

- **Conversation store** (app SQLite DB from Run 6, table `conversations(id, username, dataset, created_at,
  updated_at, title)` and `turns(id, conversation_id, n, question, choice, status, sql, columns_json, summary_json,
  answer_text, audit_id, created_at)`). `summary_json` keeps what the next turn needs and nothing more: the column
  names, the row count, and **at most `CONV_KEEP_ROWS` (5) rows after PII masking** plus the facts - never the full
  result. A conversation belongs to one user and one dataset; another user's conversation is 404 (as in Run 6).
- **API:** `POST /api/ask {question, mode?, choice?, conversation_id?}` - without `conversation_id` a new
  conversation starts; the payload gains `conversation_id`, `turn` and `context` (see below).
  `GET /api/conversations` (own, newest first, title = first question), `GET /api/conversations/{id}` (turns with
  their stored answer cards, no re-run), `DELETE /api/conversations/{id}`. History (Run 6) groups by conversation;
  replaying a turn reruns its stored SQL as today. CLI: `ask "..." --conversation ID` and `ask --new`, `--json`
  carries `conversation_id`.
- **Follow-up context for the agent** (`nl2sql/agent/context.py` or next to the loop): for turn n > 1 the agent gets
  a compact block of the last `CONV_TURNS` (3) turns - each question, its SQL, its columns and the kept rows - inside
  the same token budget (`nl2sql/agent/budget.py`): older turns are dropped first, then rows, never the current
  question; `context_overflow` stays the only failure. The prompt tells the model: resolve "bu / bunlar / o müşteri /
  aynı dönem / sadece X / bunu" from these turns, reuse the earlier SQL as the starting point when the user refines
  a report, and never copy a number from an earlier turn into the answer - every number in the new answer must come
  from the new result (the number guard already enforces this; earlier turns' values are **not** added to the
  guard's allowed set, except values the user typed in the current question).
- **How the follow-up was read (`context`)**: the agent submits, with its SQL, a short structured note -
  `{uses_turns: [n], entities: [{column, value}], refines_sql_of: n|null}` - validated by code (the referenced turn
  exists, each `value` appears in that turn's kept rows or SQL). The UI shows it as one line in the evidence. An
  invalid note is dropped (the answer still stands) and logged.
- **Standalone vs follow-up:** the model decides, but the decision is visible (`context.uses_turns` empty = stood
  alone). Deterministic hints are passed to it: demonstratives and ellipsis markers (`bu, bunlar, şu, o, aynı, sadece,
  bunu, peki, ya ...`), a question with no table-like noun. When the question clearly stands alone the context block
  is still available, the model just does not use it. "Yeni konuşma" in the UI and `--new` on the CLI always start
  clean.
- **Clarification inside a conversation**: a follow-up that is ambiguous ("bu müşteri" while the last result had 5
  customers) asks with the candidates from the kept rows as options; the chosen option becomes the entity.
- **Report refinements**: "sadece X", "geçen yılla karşılaştır", "aylık / çeyreklik göster", "ilk 10", "grafiği
  çizgi / çubuk yap". The last one changes only the chart (code picks the chart from the user's wish if the shape
  allows it, otherwise says why in one sentence) without a new SQL; the others produce a new SQL from the previous
  one. Chart wishes are recognised by code (a small keyword table), not by the model.
- **UI** (`web/`): thread view (`#thread`, one `.turn` per turn with its question bubble and answer card; the latest
  turn's card is full, earlier cards collapse to sentence + small table and expand on click), input under the last
  turn (`#question`), "Yeni konuşma" (`#new-conversation`), conversation list in the sidebar above history
  (`#conversation-list`, click opens the thread from the store without re-running), the evidence line "Önceki
  cevaptan: ...". Reload restores the open conversation (`conversation_id` in the URL hash `#/c/<id>`). Phone layout
  and dark mode as before; add visual flows: a 3-turn conversation, a refinement that changes the chart, "Yeni
  konuşma".
- **Follow-up golden set** (`real_datasets/wwi_real/followups.jsonl`, `dataset.json` `files.followups`): 8-12 chains of
  2-3 turns written for the real WideWorldImporters data, each turn `{question, sql, uses_turns, tags}` - entity
  follow-ups (customer, product, supplier, invoice), set follow-ups ("bunlardan"), period and filter refinements,
  one chain that must stand alone in the middle ("Peki toplam müşteri sayısı?"), one chart-only refinement (golden
  `sql` = previous). The golden SQL of every turn must run through the policy on the real DB by hand once (the fake
  model replays it). `eval --followups` runs chains turn by turn with the conversation context and reports turn
  accuracy, chain accuracy (all turns right) and "context used correctly" (the `uses_turns` note matches the golden).
  `--llm fake` gives 100 %.

**Out (not this run):** long-term memory across conversations, sharing a conversation between users, editing an earlier
turn in place, voice input, a conversation spanning two datasets.

## 3. Milestones

- **M21 - Conversation core:** store tables and migration, `conversation_id`/`turn` in the payload and the ask log,
  context block and trimming inside the budget, the `context` note and its validation, the guard keeping earlier
  turns' numbers out, CLI `--conversation/--new`, conversations API with per-user ownership. Tests: a 3-turn chain
  with a scripted fake model sees exactly the last turns' questions, SQL and kept rows (never more than
  `CONV_KEEP_ROWS`, masked); trimming drops oldest first and never the current question; a number from turn 1 in
  turn 2's answer is rejected; an invalid context note is dropped; another user's conversation is 404.
- **M22 - Refinements and clarification:** report refinements (new SQL from the previous one), chart-only refinement
  by code, ambiguous follow-up -> options from the kept rows, standalone detection hints. Tests per refinement kind
  with the fake model; chart-only refinement makes no agent call and no new SQL.
- **M23 - UI, golden set, eval:** thread view, conversation list, `#/c/<id>` restore, evidence line, follow-up golden
  set on `wwi_real` with `eval --followups` (turn / chain / context metrics in report.json, report.md and the
  console), README Run 7 section ("Konuşma: ardışık sorular"), smoke + visual flows. Integration test: a conversation
  through the API with TestClient and the fake model, reload of the thread from the store, replay of one turn.

## 4. Contracts to keep

- A turn's stored summary never holds more than `CONV_KEEP_ROWS` masked rows; full results are never stored.
- Every number in a follow-up answer comes from that turn's own result or the current question.
- Reopening a conversation from the list re-renders stored cards and runs nothing; only "replay" or a new question
  executes SQL.
- Single-question use (no `conversation_id`) behaves exactly as in Run 6.
