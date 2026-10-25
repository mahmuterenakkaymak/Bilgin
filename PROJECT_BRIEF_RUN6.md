# NL2SQL (Bilgin) - Run 6: users and roles, admin-only rules, onboarding a new database from an Excel template

> Drafted 2026-10-25 from Eren's request: "Kullanıcı rol-yetki yönetimi. Sadece admin kullanıcı iş kuralı girebilir.
> Veritabanı haritası için arayüzden Excel şablonunu sistem oluşturup export edecek; şablon doldurulup arayüzden import
> edilecek. Bunu da admin kullanıcı yapabilecek." Clarified: "Eski şemayı düzeltmek için değil. Başka db kullanmak
> istediğimde Bilgin'e uygun formatta Excel şablonu versin, nasıl dolduracağımı göstermek için 1 tabloluk örnek versin
> başka sheet'te. Bu şablonu yükleyince kendisi RAG'i vesaire oluşturacak." Builds on Run 1-5. Product name **Bilgin** (package and CLI stay
> `nl2sql`). Never write the names of a specific commercial ERP product or of the owner's company in code, docs, UI
> text or test data.

## 0. Input from earlier runs

- Read `.hybrid/report.json`, `REVIEW.md`, `README.md` (Run 3-5 sections) and `docs/BILGIN-TEKNIK-DOKUMAN.md` first.
  Run 5 delivered the web UI (`nl2sql/web/app.py` FastAPI, `web/` React + ECharts built into `nl2sql/web/static`),
  saved questions in a local SQLite file (`config.APP_DB_PATH`, `nl2sql/web/saved.py`), the ask log
  (`nl2sql/app/asklog.py`), the rules API (`/api/rules`, `nl2sql/schema_map/rules_edit.py`) and history replay
  (`POST /api/replay/{audit_id}`). Run 3 delivered Excel schema import on the CLI (`nl2sql/schema_map/excel.py`:
  `read_workbook`, `fallback_mapping`, `propose`, `convert`; header dictionary `profiles/excel_headers.json`), live
  schema introspection (`introspect.py`) and diff/merge (`merge.py`). Build on these interfaces; do not write a second
  Excel reader or a second rules writer.
- Real database work after Run 5 (commits 78c98ad, cc93633, 1d96401): `real_datasets/wwi_real` (SQL Server, read-only
  login), COUNT(*) rewrite under column DENY, Decimal JSON, no column names in answer sentences, per-dataset history.
  Keep all of them working; the suite is green at 4215 Python + 136 web tests.
- Rules kept: tests over a growing or configurable set assert structure, never a fixed count; tests never call a real
  model or a real SQL Server; every execution goes through the executor (policy, read-only, PII masking); nothing
  leaves the machine; the LLM never owns a number.

## 1. Goal

Bilgin becomes a multi-user application on one machine: people log in, every request knows who is asking, and what a
person may do depends on their role. Only an **admin** changes the system's knowledge: business rules and the
databases Bilgin knows. **Onboarding a new database needs no command line:** the admin downloads a blank Excel
template in Bilgin's format (with a sheet showing one fully filled example table), describes the new database in it
(tables, columns, meanings, coded values, personal-data marks, relations, optionally business rules), uploads it,
reviews the check report, and applies it. Bilgin then creates a new dataset, builds its search index (RAG: table,
rule and summary embeddings) and its read-only login script by itself, and the admin switches the active dataset to it.

"Done" =
- `python -m nl2sql user add NAME --role admin` creates the first admin (password typed twice through `getpass`,
  never an argument, never a default password). Without at least one user, `serve` refuses to start and says how to
  create one (one Turkish sentence, exit 2) - unless the development bootstrap below applies.
- **Development bootstrap (Eren, for testing):** when the environment variable `NL2SQL_DEV_ADMIN_PASSWORD` is set
  and the users table is empty, `serve` creates user `admin` with role `admin` and that password at startup, and
  prints one warning line ("Geliştirme yöneticisi oluşturuldu: admin - NL2SQL_DEV_ADMIN_PASSWORD ortam
  değişkeninden; canlı kurulumda bu değişkeni tanımlamayın."). The minimum password length does not apply to this
  bootstrap only. No password value appears anywhere in code, config, tests, docs or the repo; tests set the variable
  with `monkeypatch`. It never runs when at least one user exists, so it cannot reset a real admin.
- The UI opens on a login screen; after login the header shows the user and role and a "Çıkış" button.
- A `user` can ask, see and reopen *their own* history, save and export. A `user` sees the rules screen read-only and
  never sees the schema map or user screens. An `admin` can do everything, including users, rules, index rebuild and
  onboarding a new database from the template and switching the active dataset. Every forbidden call returns 403 from the server whatever the UI shows.
- From the UI an admin downloads `bilgin-veritabani-sablonu.xlsx`, fills it for a database Bilgin has never seen,
  uploads it, reviews the check report and applies it; a new dataset folder appears under `real_datasets/<name>/`
  with schema, rules, profile and an empty golden set, its index is built automatically (progress shown in the UI),
  and after "Bu veri kümesine geç" the next question is answered against the new database. Existing datasets
  (`wwi_real`, `synthetic_erp`) are never modified by an upload.

## 2. Scope

**In (Run 6):**

- **Users and passwords** (`nl2sql/auth/`): users live in the same local app SQLite file as saved questions
  (`config.APP_DB_PATH`), table `users(id, username UNIQUE, password_hash, role CHECK(role IN ('admin','user')),
  active, created_at, last_login_at)`. Passwords are hashed with the standard library only: `hashlib.scrypt`
  (n=2**14, r=8, p=1, 16-byte random salt, stored as `scrypt$n$r$p$salt_b64$hash_b64`), compared with
  `hmac.compare_digest`. Minimum password length 10, config constant. **No new dependency** for auth.
- **Sessions**: login `POST /api/auth/login {username, password}` sets an HttpOnly, SameSite=Strict cookie holding a
  random session token (`secrets.token_urlsafe(32)`); tokens are stored hashed (sha256) in a `sessions` table with
  expiry (config `SESSION_HOURS`, default 12) and deleted on logout (`POST /api/auth/logout`). `GET /api/auth/me`
  returns `{username, role}` or 401. Failed logins: same message for unknown user and wrong password
  ("Kullanıcı adı ya da parola hatalı."), and after 5 failures in 15 minutes for a username, 15 minutes lockout
  (config constants). The server stays bound to 127.0.0.1 (unchanged); TLS and network exposure are out of scope.
- **Roles enforced on the server**: one FastAPI dependency `require(role)` used by every route. Matrix:
  | Route | user | admin |
  |---|---|---|
  | `/api/ask`, `/api/replay/{id}`, `/api/export/*`, `/api/saved*`, `/api/history`, `/api/examples`, `/api/health`, `GET /api/rules`, `GET /api/tables` | yes | yes |
  | `POST/PUT/DELETE /api/rules*`, `POST /api/index/rebuild` | 403 | yes |
  | `/api/schema-map/*`, `/api/users*` | 403 | yes |
  | `/`, `/assets/*`, `/api/auth/login` | public | public |
  Every other `/api/*` route without a session is 401. History, replay, saved questions and export are **per user**:
  the ask log and saved table gain a `username` field; a user replaying or exporting another user's `audit_id` gets
  404 (not 403 - do not reveal it exists); an admin may read all. The executor's audit line source becomes
  `<web|cli>:<username>:<audit_id>` (CLI uses the OS user name).
- **User management** (admin): `GET /api/users`, `POST /api/users {username, password, role}`,
  `PUT /api/users/{id} {role?, active?, password?}`. An admin cannot demote or deactivate the **last active admin**
  (409, Turkish message). CLI: `user add NAME --role admin|user`, `user list`, `user passwd NAME`,
  `user set NAME --role ... | --deactivate | --activate`.
- **Blank template for a new database** (admin): `GET /api/schema-map/template.xlsx` builds
  `bilgin-veritabani-sablonu.xlsx` with openpyxl (already a dependency). It does **not** come from an existing
  dataset - it is the empty format any database is described in:
  - Sheet `Nasıl doldurulur`: 10-15 Turkish lines - what each sheet is, which columns are required (TABLO, KOLON,
    TİP), why AÇIKLAMA matters most (the model only knows what is written there), how to write coded values
    (`A=Alıcı; S=Satıcı`), what each personal-data class does (masked, never filterable), what KAPALI means (the
    column is never read), how to write REFERANS (`Şema.Tablo.Kolon`), that schema-qualified names (`Sales.Orders`)
    are fine, and that the Örnek sheet shows one finished table.
  - Sheet `Veri kümesi`: `AD` (folder name, `^[a-z][a-z0-9_]{2,30}$`), `GÖRÜNEN AD`, `BAĞLANTI` (`mssql` | `sqlite`),
    `VARSAYILAN ŞEMA`, `VERİ TARİHİ` (the date "bu yıl / geçen ay" is relative to, ISO), one row.
  - Sheet `Tablolar`: `TABLO | MODÜL | AÇIKLAMA | ANAHTAR KELİMELER`, empty rows with header styling.
  - Sheet `Kolonlar`: `TABLO | KOLON | TİP | AÇIKLAMA | DEĞERLER | KİŞİSEL VERİ | KAPALI | REFERANS | NULL`, empty.
    `KİŞİSEL VERİ` has a data-validation list of the PII classes (`nl2sql/policy/pii.py` CLASSES) plus empty;
    `KAPALI` and `NULL` have `E/H` lists; `TABLO` has a list fed from the Tablolar sheet.
  - Sheet `İş kuralları` (optional): `KİMLİK | TERİM | EŞ ANLAMLILAR | TANIM | SQL İPUCU | TABLOLAR`, empty.
  - Sheet `Örnek`: the same three blocks filled for **one** generic example table (an invoice header table, e.g.
    `Satis.Fatura` with 6-8 columns: key, date, customer code with a REFERANS, a coded type column with DEĞERLER,
    an amount, a personal-data column with a class, one KAPALI column) plus one example business rule that uses it.
    The Örnek sheet is never imported. No real product or company names in the example.
  - Headers must be in `profiles/excel_headers.json` (add the new synonyms) so the existing reader maps the template
    **deterministically, with no LLM call**; workbooks that are not Bilgin's template still go through the existing
    `propose` + `fallback_mapping` path. A hidden sheet `_bilgin` carries the template version.
  - `GET /api/schema-map/template.xlsx?from_db=1` (only when the server has a database connection configured):
    the same template with Tablolar/Kolonlar structure pre-filled by `introspect` (names, types, NULL, REFERANS from
    foreign keys), meaning columns empty for the admin to fill. If the read-only login cannot read metadata
    (VIEW DEFINITION denied), say so in Turkish and fall back to the blank template - never use another login.
- **Import of a filled template** (admin), two steps, never one:
  1. `POST /api/schema-map/preview {filename, content_b64}` (base64 JSON body - no `python-multipart` dependency;
     limit `MAP_MAX_BYTES` = 5 MB, `.xlsx` only, checked by content (zip + `[Content_Types].xml`), not by name).
     Reads with the existing `excel.read_workbook` + `fallback_mapping` + `convert` path into the canonical schema,
     plus the dataset and rules sheets. Returns `{preview_id, dataset: {name, display_name, ...}, counts: {tables,
     columns, pii, deny, references, rules}, errors:[{sheet, row, column, message}], warnings:[...], db_check}`.
     Errors block applying: missing required cell, a column whose TABLO is not in Tablolar, duplicate table/column,
     invalid PII class or E/H value, REFERANS to an unknown column, invalid dataset name, a name that already exists
     under `datasets/` or `real_datasets/`, a rule whose tables are unknown. Warnings: tables with no description,
     columns with an empty AÇIKLAMA (count + first 20). `db_check` (only with a configured connection): `diff-map`
     against the live database - tables/columns in the workbook but not in the DB are errors, DB-only ones a warning.
     Nothing is written in this step; the parsed result waits under `data/map_previews/<preview_id>.json` for 30 min.
  2. `POST /api/schema-map/apply {preview_id}`: creates `real_datasets/<name>/` with `dataset.json` (outputs under
     `data/<name>.db`, `index/<name>/`, `eval_out/<name>/`; builder/generator/references point to a stub like
     `real_datasets/wwi_real/real.py`), `schema.json`, `rules.json` (from the sheet, or empty), `profile.json`
     (empty pairs), empty `golden.jsonl`; writes the read-only login script for it (`make-login-script` code,
     `__DEGISTIR__` placeholder, never a real password); then **builds the index** in a background thread with the
     configured embedder (same code as `build-index`), with `GET /api/schema-map/status/{preview_id}` reporting
     `{phase: writing|indexing|done|failed, message}`; records `{username, ts, name, counts}` in
     `logs/map_changes.jsonl`. Existing dataset folders are never touched; a name clash is an error, not an overwrite.
- **Active dataset** (admin): `GET /api/datasets` lists datasets with an index (name, display name, connection, index
  fresh), `POST /api/datasets/active {name}` reopens the server's session on that dataset (same `open_session` path
  as `serve --dataset`) and is remembered in the app DB for the next start; `serve --dataset` still wins when given.
  The UI header chip shows the active dataset. Datasets live in `datasets/` (built ones) and `real_datasets/`
  (database-backed ones); both are listed.
  After switching to a database-backed dataset the UI shows, once, what the database administrator must do: run the
  generated login script (download link `GET /api/datasets/{name}/login-script.sql`, admin) and set
  `NL2SQL_MSSQL_CONN` for the server.
- **UI** (`web/`): login screen (`#login-form`, `#login-username`, `#login-password`, `#login-submit`, error line);
  header user chip and `#logout`; a `user` sees the rules screen with forms disabled and a one-line note
  ("İş kurallarını yalnız yönetici değiştirebilir."); admin-only nav items `Veritabanı haritası` (`#nav-map`) and
  `Kullanıcılar` (`#nav-users`). Map screen (`Yeni veritabanı`): "Boş şablonu indir" (`#map-template`) and, when a
  connection exists, "Veritabanından doldurulmuş şablon" (`#map-template-db`); file input (`#map-file`), "Kontrol et"
  (`#map-preview`) -> check report (counts, error table with sheet/row/column, warnings, live-DB check), "Oluştur"
  (`#map-apply`) enabled only without errors, then a progress line (writing -> indexing -> done) and "Bu veri
  kümesine geç" (`#map-activate`). A dataset list with the active one marked and a switch button. Users screen: table, add form, role select, activate/deactivate,
  password reset. All Turkish, same tokens, phone layout and dark mode as Run 5. Add the new pages to
  `.hybrid/visual.json` (login, admin map screen with a preview, user's read-only rules screen).
- **CLI keeps working** for one operator on the machine: `ask`, `eval`, `import-map` etc. need no login.

**Out (not this run):** network exposure, TLS, SSO/LDAP, per-table or per-column permissions for users, row-level
filtering per user, password reset by e-mail, more than one active dataset at a time, updating an existing dataset
from a template (an upload always creates a new dataset), connection strings entered in the UI (they stay in
environment variables), golden questions from the template.

## 3. Milestones

- **M18 - Auth core:** users/sessions tables and migration of the existing app DB (saved questions keep working; old
  rows get `username = NULL` and are visible to admins only), scrypt hashing, login/logout/me, lockout, `require`
  dependency, CLI `user ...`, `serve` refuses without users, the `NL2SQL_DEV_ADMIN_PASSWORD` bootstrap (creates
  only on an empty table, warns, never overwrites). Tests: hashing round trip and format, wrong password and
  unknown user give the same message, lockout and expiry with an injected clock, cookie flags, last-admin guard.
- **M19 - Roles everywhere:** apply the matrix to every route (one table-driven test that walks every registered
  route with no session / user / admin and checks 401/403/200 - a route missing from the matrix fails the test),
  per-user history/saved/replay/export (404 for another user's id), username in the ask log and audit source, users
  API. UI: login screen, user chip, logout, read-only rules for users, users screen. Integration test: two users,
  one admin, full flows through TestClient.
- **M20 - New database from a template:** blank template (all sheets, Örnek with one table and one rule, validation
  lists, hidden `_bilgin`), `from_db` pre-fill with the metadata fallback, header dictionary additions, preview
  (validation, optional live-DB diff, no write), apply (new dataset folder, login script, background index build,
  status, change log), datasets list and active-dataset switch, UI screen. Tests: the blank template read back gives
  zero tables and zero errors; the Örnek sheet is never imported; a template filled in code (the Örnek table copied
  into Tablolar/Kolonlar under a new dataset name, plus one rule) previews with the right counts, applies, creates
  the folder with every file, builds an index with the fake embedder and answers a `--llm fake` question after the
  switch; each listed error (missing required cell, orphan column, duplicate, invalid class, unknown REFERANS,
  invalid or existing name, non-xlsx) blocks applying; existing datasets are byte-identical after any upload;
  qualified names (`Sales.Orders`) work; a non-admin gets 403 on all of it. README Run 6 section ("Yeni bir
  veritabanını Bilgin'e tanıtmak"), smoke + visual flows (template download, preview with an error, apply, switch).

## 4. Contracts to keep

- Every `/api/*` response for a forbidden or missing session is JSON `{"detail": "<Türkçe cümle>"}` with 401/403/404;
  the UI shows the sentence. The 422 rules body stays `{"errors": [...]}`.
- An upload only ever creates a new dataset folder; it never writes into an existing one.
- The template carries no connection string; the server's connection stays in `NL2SQL_MSSQL_CONN`.
- Passwords, password hashes and session tokens never appear in logs, the ask log, the audit log, API responses
  (except the cookie itself) or test snapshots.
