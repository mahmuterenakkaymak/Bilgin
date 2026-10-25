# NL2SQL (Bilgin) - Run 6: users and roles, admin-only rules, schema map template export/import

> Drafted 2026-10-25 from Eren's request: "Kullanıcı rol-yetki yönetimi. Sadece admin kullanıcı iş kuralı girebilir.
> Veritabanı haritası için arayüzden Excel şablonunu sistem oluşturup export edecek; şablon doldurulup arayüzden import
> edilecek. Bunu da admin kullanıcı yapabilecek." Builds on Run 1-5. Product name **Bilgin** (package and CLI stay
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
database map. The database map gets a full round trip in the UI: the system **generates an Excel template** from the
current schema, the admin downloads it, fills in meanings (descriptions, coded values, personal-data marks), uploads
it back, sees what will change, and applies it.

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
  the schema map round trip. Every forbidden call returns 403 from the server whatever the UI shows.
- From the UI an admin downloads `veritabani-haritasi.xlsx`, fills it, uploads it, reviews the change report and
  applies it; the dataset's `schema.json` changes (previous version kept as a timestamped backup), the index is marked
  stale and the UI offers the rebuild.

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
- **Schema map template export** (admin): `GET /api/schema-map/template.xlsx` builds a workbook with openpyxl
  (already a dependency) from the session dataset's current `schema.json`:
  - Sheet `Nasıl doldurulur`: 6-10 Turkish lines (what each sheet is, which columns to fill, what not to change,
    personal-data classes and what they do).
  - Sheet `Tablolar`: `TABLO | MODÜL | AÇIKLAMA | ANAHTAR KELİMELER`, one row per table, filled from the schema.
  - Sheet `Kolonlar`: `TABLO | KOLON | TİP | AÇIKLAMA | DEĞERLER | KİŞİSEL VERİ | KAPALI | REFERANS | NULL`, one row per
    column, filled from the schema. `KİŞİSEL VERİ` has a data-validation list of the PII classes
    (`nl2sql/policy/pii.py` CLASSES) plus empty; `KAPALI` and `NULL` have `E/H` lists. `TABLO`, `KOLON`, `TİP`,
    `REFERANS`, `NULL` are structure (greyed, locked cells, sheet protection without password) - meaning columns are
    editable. Headers must be in `profiles/excel_headers.json` (add `KİŞİSEL VERİ`/`KAPALI`/`ANAHTAR KELİMELER`
    synonyms there) so the existing reader maps the template **deterministically, with no LLM call**.
  - A hidden sheet `_bilgin` with the dataset name, schema hash and template version, so an upload for another
    dataset or an outdated schema is detected.
- **Schema map import** (admin), two steps, never one:
  1. `POST /api/schema-map/preview {filename, content_b64}` (base64 JSON body - no `python-multipart` dependency;
     limit `MAP_MAX_BYTES` = 5 MB, `.xlsx` only, checked by content (zip + `[Content_Types].xml`), not by name).
     Reads with the existing `excel.read_workbook` + `fallback_mapping` + `convert` path, then validates and diffs
     against the current schema with `merge.py`: returns `{preview_id, dataset_ok, schema_hash_ok, changes:
     {descriptions, values, pii_added, pii_removed, deny_added, deny_removed, keywords, modules}, errors:[{sheet,
     row, column, message}], warnings:[...]}`. Errors (unknown table or column, invalid PII class, structure cell
     changed, wrong dataset) block applying; a schema-hash mismatch is a warning. Nothing is written in this step;
     the parsed result waits under `data/map_previews/<preview_id>.json` for 30 minutes.
  2. `POST /api/schema-map/apply {preview_id}`: copies the current `schema.json` to
     `schema.json.bak-<timestamp>`, writes the merged schema (structure from the current schema, meaning from the
     workbook), marks the index stale, records `{username, ts, preview_id, counts}` in `logs/map_changes.jsonl`, and
     returns the counts. If PII or deny marks changed, the response carries
     `login_script_changed: true` and the UI says, in Turkish, that the read-only login script must be regenerated
     and re-run by the database administrator, with a download link (`GET /api/schema-map/login-script.sql`, admin,
     generated by `make-login-script` code with the `__DEGISTIR__` placeholder, never a real password).
- **UI** (`web/`): login screen (`#login-form`, `#login-username`, `#login-password`, `#login-submit`, error line);
  header user chip and `#logout`; a `user` sees the rules screen with forms disabled and a one-line note
  ("İş kurallarını yalnız yönetici değiştirebilir."); admin-only nav items `Veritabanı haritası` (`#nav-map`) and
  `Kullanıcılar` (`#nav-users`). Map screen: "Şablonu indir" button, file input, "Önizle" -> change report (counts,
  error table with sheet/row/column, warnings), "Uygula" enabled only without errors, then the stale-index banner and
  rebuild button already used by the rules screen. Users screen: table, add form, role select, activate/deactivate,
  password reset. All Turkish, same tokens, phone layout and dark mode as Run 5. Add the new pages to
  `.hybrid/visual.json` (login, admin map screen with a preview, user's read-only rules screen).
- **CLI keeps working** for one operator on the machine: `ask`, `eval`, `import-map` etc. need no login.

**Out (not this run):** network exposure, TLS, SSO/LDAP, per-table or per-column permissions for users, row-level
filtering per user, password reset by e-mail, multiple datasets per server, editing structure (tables/columns) from
the template.

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
- **M20 - Schema map round trip:** template export (sheets, validation lists, locked structure, hidden `_bilgin`
  sheet), header dictionary additions, preview (validation + diff, no write), apply (backup, write, stale index,
  change log, login-script flag), UI map screen. Tests: export -> read back unchanged gives zero changes; editing
  a description / adding a PII mark shows exactly that change and applying it writes it; unknown column, invalid
  class, changed structure cell, wrong dataset and a non-xlsx file are errors; a non-admin gets 403 on all of it;
  wwi_real-style qualified names (`Sales.Orders`) round-trip. README Run 6 section, smoke + visual flows.

## 4. Contracts to keep

- Every `/api/*` response for a forbidden or missing session is JSON `{"detail": "<Türkçe cümle>"}` with 401/403/404;
  the UI shows the sentence. The 422 rules body stays `{"errors": [...]}`.
- The template's structure columns are never applied from the workbook; meaning columns only.
- Passwords, password hashes and session tokens never appear in logs, the ask log, the audit log, API responses
  (except the cookie itself) or test snapshots.
