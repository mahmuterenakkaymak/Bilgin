# NL2SQL (Bilgin) - Run 7: conversations; start screen per business role; database connections in the admin panel

> Drafted 2026-10-25 from Eren's request: "Rapor ya da soru-cevap fark etmez, girdikten sonra 2.-3. cümle ile
> düzenlenebilmeli. 'Son satışın tutarı ne?' -> 'Bu müşteriye başka ne sattık?' Tek session'da üst üste soru-cevap
> olmalı." Added the same day: "Açılışa hazır sorulardan / genel geçer sorulardan bir başlangıç ekranı; hazır sorular
> login olan kullanıcının rolüne göre (satışçı mı, satın almacı mı, muhasebeci mi, yönetici mi) değişsin." Runs after Run 6 (users, roles, sessions, per-user history, onboarding a new database from a template),
> before Run 8 (English, Windows service). Product name **Bilgin** (package and CLI stay `bilgin`). Never write the
> names of a specific commercial ERP product or of the owner's company in code, docs, UI text or test data.

## 0. Input from earlier runs

- Read `.hybrid/report.json`, `REVIEW.md`, `README.md` (Run 3-6 sections), `docs/BILGIN-TEKNIK-DOKUMAN.md` and
  `PROJECT_BRIEF_RUN6.md` first. Today every question is independent: `ask_payload(session, question, mode, choice)`
  (`bilgin/app/ask.py`) runs the agent loop (`bilgin/agent/loop.py`) with no memory of the previous answer; the UI
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
- After login the user lands on a **start screen** of ready-question cards chosen for **their business role** (sales,
  purchasing, accounting, management, general). A card shows a number or a small chart with one line and its last
  refresh time; it opens in seconds because it reruns a stored, approved SQL **without the model**; clicking it opens
  the full answer card and the input under it continues the conversation ("Peki geçen ayla kıyasla?"). It is not a BI
  dashboard: no free-form widgets, no drag-and-drop layout - every card is a question Bilgin can answer and continue.

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
- **Follow-up context for the agent** (`bilgin/agent/context.py` or next to the loop): for turn n > 1 the agent gets
  a compact block of the last `CONV_TURNS` (3) turns - each question, its SQL, its columns and the kept rows - inside
  the same token budget (`bilgin/agent/budget.py`): older turns are dropped first, then rows, never the current
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

- **Business role of a user** (separate from the Run 6 permission role admin/user - a sales person can be either):
  new column `users.business_role` with values from config `BUSINESS_ROLES` = `satis` (Satış), `satin_alma` (Satın
  alma), `muhasebe` (Muhasebe), `yonetim` (Yönetim), `genel` (Genel, default). Set by an admin in the users screen and
  the users API (`PUT /api/users/{id} {business_role}`) and on the CLI (`user set NAME --business-role R`); shown in
  the header chip next to the name. A user cannot change their own business role.
- **Ready questions** (app DB table `ready_questions(id, dataset, business_role, title, question, sql, display,
  position, created_by, approved, created_at)`, `display` = `number` | `chart` | `table`): a ready question belongs to
  one dataset and one business role (or `*` = every role). The **SQL is fixed when the question is approved**: an admin
  asks the question once (model writes SQL as usual), checks the answer, and saves it as a ready question with that
  SQL; from then on the card reruns exactly that SQL through the policy and the read-only executor - no model call,
  numbers by SQL only. Admin API: `GET/POST/PUT/DELETE /api/ready-questions` (admin), "Hazır soru yap" button on an
  answer card for admins (pre-fills title, question, SQL, a suggested display from the chart shape, role select).
  A user may also pin **personal** cards from their own answers (same table, `business_role = NULL`, `created_by` =
  them, visible only to them, max `PERSONAL_CARDS` = 6).
- **Start screen** (`#start`, the default route after login): the cards for the user's business role plus `*` cards
  plus their personal cards, in `position` order, then a short "Sorunuzu yazın" input that starts a conversation.
  `GET /api/start` returns the card list with each card's result: `{cards: [{id, title, question, display, value?,
  chart?, rows?, columns?, refreshed_at, error?}]}`. Each card's result is cached per dataset+card for
  `START_CACHE_S` (300 s) - many users opening the start screen run each SQL once, not once per user; a "Yenile"
  button refreshes one card (rate-limited to once per 30 s per card). A card whose SQL fails (e.g. the schema changed)
  shows the Turkish error and, for admins, an "SQL'i yeniden onayla" action; it never breaks the screen. Clicking a
  card opens the full answer card (same payload as `/api/replay`) as turn 1 of a new conversation.
- **Suggested ready questions for a new database**: when a dataset is created from the template (Run 6) or an admin
  asks for it on an existing dataset (`POST /api/ready-questions/suggest {dataset}`), Bilgin proposes 2-4 questions per
  business role from the schema (modules, table descriptions and business rules: e.g. sales -> "Bu ayki ciro", "En çok
  satan 5 ürün"; purchasing -> "Bekleyen satın alma siparişleri"; accounting -> "Vadesi geçmiş alacaklar"; management ->
  "Aylık ciro trendi"). The model writes the question texts only; each suggestion is then asked through the normal
  agent to get its SQL, and lands as `approved = false`. **Nothing unapproved ever runs on the start screen**; the
  admin reviews each one's answer and approves, edits or deletes it.
- **Seed for `wwi_real`**: a checked-in `real_datasets/wwi_real/ready_questions.json` with 2-3 approved questions per
  business role whose SQL is one of the golden SQLs or a hand-checked variant (run once through the policy on the
  real database), loaded into the app DB on first start for that dataset.

- **Database connections managed in the admin panel** (Eren: "Veritabanı bağlantı bilgileri admin panel üzerinden
  doldurulabilsin; bağlantının aktifliğini tüm kullanıcılar yeşil-kırmızı görsün"):
  - **Per dataset**: every database-backed dataset has its own connection, so switching the active dataset (Run 6)
    also switches the database with no restart. App DB table `connections(dataset PRIMARY KEY, server, database,
    auth CHECK(auth IN ('sql','windows')), username, secret_blob, options_json, updated_by, updated_at,
    last_ok_at, last_error)`. `options_json`: `encrypt`, `trust_server_certificate`, `port`, `driver` (default the
    newest installed "ODBC Driver NN for SQL Server"). `ApplicationIntent=ReadOnly` is always added, never optional.
  - **The password is never stored in clear and never leaves the server**: `secret_blob` is the password encrypted
    with Windows DPAPI (`CryptProtectData` via `ctypes`, machine scope, an entropy value derived from the dataset name
    - stdlib only, no new dependency); on non-Windows the UI form is disabled and only the environment variable path
    works. The API is write-only for the secret: `GET /api/connections/{dataset}` returns server, database, auth,
    username, options, `has_secret: true|false`, `last_ok_at`, `last_error` - **never** the password or a connection
    string; `PUT` accepts a new password or keeps the stored one when the field is empty. The password never appears in
    logs, the ask/audit log, error messages (driver errors are scrubbed of `PWD=`/`Password=` before they are stored or
    shown) or test snapshots.
  - **Environment variable still wins**: `BILGIN_MSSQL_CONN_<DATASET>` (upper-case dataset name) or, for the active
    dataset, `BILGIN_MSSQL_CONN` override the stored connection (the Windows service and development keep working);
    the screen shows "Ortam değişkeninden" and the form is read-only for that dataset.
  - **Read-only guard before saving** (admin "Bağlantıyı test et" and on every save): connect with the given values
    and refuse to save - with a Turkish explanation - when the login is too powerful: `IS_SRVROLEMEMBER('sysadmin') = 1`,
    `IS_MEMBER('db_owner') = 1`, or `HAS_PERMS_BY_NAME(DB_NAME(), 'DATABASE', 'INSERT' | 'UPDATE' | 'DELETE' |
    'ALTER' | 'EXECUTE') = 1`. The message points to the dataset's generated read-only login script (download link).
    Windows auth (`auth = windows`) uses the server process's own account; the same guard applies, so the machine's
    sysadmin Windows account is refused. The test also checks that the dataset's tables are visible (a sample of the
    allowlist) and reports the missing ones.
  - **Admin screen** `Veritabanı bağlantıları` (`#nav-connections`, admin only): one row per database-backed dataset
    with status dot, server/database, last success, last error; edit form (`#conn-server`, `#conn-database`,
    `#conn-auth`, `#conn-username`, `#conn-password` type=password with placeholder "değiştirmek için yazın",
    `#conn-encrypt`, `#conn-trust`, `#conn-test`, `#conn-save`); the test result shows guard and table checks line by
    line. The Run 6 "Yeni veritabanı" flow links here after a dataset is created ("Şimdi bağlantıyı girin").
- **Connection status for everyone** (green / red): `GET /api/health` gains `db: {state: "ok"|"down"|"none"|"unknown",
  checked_at, message}` for the active dataset. A background checker runs `SELECT 1` with a 3-second timeout every
  `DB_CHECK_S` (60 s) and after every connection change, plus an on-demand check after a query fails with a connection
  error; requests never wait for it. The header shows a labelled dot visible to **all logged-in users** - "Veritabanı"
  green (ok), red (down), grey (no connection needed: a built SQLite dataset, or not yet configured) - next to the
  existing model/index dot, with a tooltip: users see "Veritabanına bağlanılamıyor, yöneticinize haber verin." and the
  time; admins also see the scrubbed driver message and a link to the connections screen. When the database is down
  the ask box stays usable but a red banner says answers cannot be produced right now, and a question fails fast with
  that message instead of waiting for the agent.

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

- **M24 - Start screen and ready questions per business role:** `users.business_role` (migration, users API/screen,
  CLI), `ready_questions` table and admin API, "Hazır soru yap" on answer cards, personal cards, `GET /api/start` with
  the per-card cache and refresh limit, start screen UI (cards by display kind, last refresh time, click -> answer card
  as turn 1 of a conversation), suggestions for a dataset (unapproved until an admin approves), `wwi_real` seed.
  Tests: each business role sees exactly its cards plus `*` plus its own personal cards; an unapproved suggestion never
  appears on the start screen and never runs; a card makes no agent call (scripted fake asserts zero calls); two users
  of the same role within `START_CACHE_S` execute the card's SQL once (executor call count); a failing card SQL shows
  its error and the other cards still render; a user cannot change their business role or another user's card;
  every card SQL goes through the policy (a card SQL touching a closed column is rejected at approval). Visual flows:
  start screen as sales and as purchasing user (different cards), card -> answer -> follow-up.

- **M25 - Database connections and status:** `connections` table, DPAPI secret store (ctypes, Windows only; skipped
  tests elsewhere), env-var override order, per-dataset connection used by the executor and by the dataset switch,
  read-only guard, connections API (write-only secret) and admin screen, background status checker, `db` block in
  `/api/health`, header "Veritabanı" dot for all users, red banner and fail-fast when down. Tests (no real SQL Server:
  the guard and checker take an injected connector): a stored password round-trips through DPAPI and is never in any
  API response, log line or error text (scan of everything the test produced); a login reported as sysadmin, db_owner
  or with INSERT/EXECUTE is refused with the explanation and nothing is saved; the env var overrides the stored
  connection and makes the form read-only; switching datasets switches connections without a restart; the checker
  flips green -> red -> green on an injected failure/recovery and the health block follows; users get the generic
  tooltip, admins the scrubbed message; a question while down fails fast without an agent call. Visual flows: admin
  connections screen with a test result, header dot green and red as a user.

## 4. Contracts to keep

- A turn's stored summary never holds more than `CONV_KEEP_ROWS` masked rows; full results are never stored.
- Every number in a follow-up answer comes from that turn's own result or the current question.
- Reopening a conversation from the list re-renders stored cards and runs nothing; only "replay" or a new question
  executes SQL.
- Single-question use (no `conversation_id`) behaves exactly as in Run 6.
- A database password entered in the UI is stored only DPAPI-encrypted and is never returned by any API, written to
  any log or shown in any error; Bilgin refuses to save a connection whose login can write or administer.
- A start-screen card only ever runs an approved, stored SQL through the executor; the model is never called to render
  the start screen, and every number on it comes from SQL.
