# NL2SQL (Bilgin) - Run 8: English version of the whole program, template in the program's language, Windows service

> Drafted 2026-10-25 from Eren's request: "Tüm programın İngilizce hali. Şablonun İngilizce hali; program dili neyse
> şablonu ona göre versin. Windows servis olarak kurulum." Runs after Run 6 (users and roles, admin-only rules,
> onboarding a new database from an Excel template) and Run 7 (conversations: follow-up questions in one session) -
> every string Run 7 added (conversation screen, follow-up messages) is translated too. Product name **Bilgin** (package and CLI stay `nl2sql`). Never
> write the names of a specific commercial ERP product or of the owner's company in code, docs, UI text or test data.

## 0. Input from earlier runs

- Read `.hybrid/report.json`, `REVIEW.md`, `README.md` (Run 3-7 sections), `docs/BILGIN-TEKNIK-DOKUMAN.md`,
  `PROJECT_BRIEF_RUN7.md` (conversations; the follow-up golden set gets an English twin as well) and
  `PROJECT_BRIEF_RUN6.md` first. Run 6 adds users (with a role) in the app SQLite DB, sessions, the role matrix on
  every route, the blank Excel template (`GET /api/schema-map/template.xlsx`, sheets `Nasıl doldurulur`,
  `Veri kümesi`, `Tablolar`, `Kolonlar`, `İş kuralları`, `Örnek`), preview/apply of a filled template into a new
  dataset with an automatic index build, and the active-dataset switch. Build on those interfaces.
- The written answer (`nl2sql/report/narrate.py`) is checked by the number guard (`nl2sql/report/guard.py`), which
  today parses Turkish number formats only (`1.234,56`, `%12,3`), and by the technical-column-name check. Number
  display is `nl2sql/report/fmt.py` (`tr_number`). Facts (`nl2sql/report/facts.py`) carry Turkish labels.
- Rules kept: tests over a growing or configurable set assert structure, never a fixed count; tests never call a real
  model or a real SQL Server; every execution goes through the executor; nothing leaves the machine; the LLM never
  owns a number; passwords and connection strings only in environment variables or OS-protected files, never in the
  repo.

## 1. Goal

1. **Bilgin speaks English as well as Turkish, everywhere a person reads it**: the web UI, API messages, the written
   answer, clarification questions and options, warnings, chart labels, facts, exports' headers, the CLI's output and
   help, the eval report text, and the README. A user picks the language; an English question gets an English answer
   with English number formatting, a Turkish question a Turkish one.
2. **The Excel template comes in the program's language**: an admin whose language is English downloads an English
   template (sheet names, headers, instructions, example); Turkish gets the Turkish one. **Either template imports in
   either language.**
3. **Bilgin installs as a Windows service**: starts with Windows, restarts on failure, logs to a fixed place, keeps
   its data outside the code folder, and can be installed, updated and removed with one script each.

"Done" =
- With language `en` the whole UI is English (no Turkish string left in the built bundle outside the Turkish catalog);
  with `tr` nothing changes from Run 6.
- `wwi_real` gets an English golden set (`golden_en.jsonl`: the same 26 questions translated, the same SQL); an eval
  with `--lang en` runs it and its report is in English. English answers pass the number guard with English formats.
- `python -m nl2sql template --lang en --out bilgin-database-template.xlsx` and the UI download produce the English
  template; importing it, and importing the Turkish one, give the same dataset.
- `scripts\install-service.ps1` (run as administrator) installs service `Bilgin`, it starts at boot, `http://127.0.0.1:8777`
  answers after a reboot, `scripts\uninstall-service.ps1` removes it cleanly.

## 2. Scope

**In (Run 8):**

- **Language model of the program** (`nl2sql/i18n/`): supported languages `tr` and `en` (config `LANGUAGES`),
  server default `NL2SQL_LANG` (default `tr`). Resolution order for a web request: the logged-in user's saved
  preference (new `users.lang` column, Run 6 table) -> the UI's `Accept-Language` -> server default. CLI: `--lang` on
  every command -> `NL2SQL_LANG` -> `tr`. One function `t(key, lang, **params)` over message catalogs
  `nl2sql/i18n/tr.json` and `en.json` (flat dotted keys, `{param}` placeholders). Every user-facing string in Python
  goes through it: API `detail` messages, warnings, failure messages, clarification texts, facts labels, template
  sentences, export headers, CLI output and argparse help, eval report text. Code comments, docstrings, log field
  names and prompts to the model are not user-facing and stay as they are.
- **Answer language follows the question**: detect the question's language with a small deterministic heuristic
  (Turkish-specific letters and a short stopword list per language; ties go to the user's language), store it in the
  payload as `answer_lang`. The narration prompt gets an English twin (same rules: no invented numbers, no technical
  column names, natural sentence); the clarification tool asks and words its options in `answer_lang`; the template
  sentence and facts labels come from the catalog in `answer_lang`.
- **Numbers per language** (`fmt.py`, `guard.py`): `format_number(value, lang)` - `tr`: `1.234,56`, `%12,3`;
  `en`: `1,234.56`, `12.3%`. The guard parses the answer language's formats and rejects the other language's (an
  English answer writing `1.234,56` is rejected, and vice versa), with the same tolerance rules as today; the retry
  message is in the answer language. The UI formats table cells, chart axes and tooltips with `Intl.NumberFormat` in
  the UI language (`tr-TR` / `en-US`); dates likewise.
- **Web UI** (`web/src/i18n/tr.json`, `en.json`, a `t()` hook): every visible string, `aria-label` and `title` moves
  into the catalogs; a header language switch (`#lang-toggle`, `TR | EN`) that saves the preference to the user
  (`PUT /api/auth/me {lang}`) and falls back to `localStorage` before login; `<html lang>` follows. Login screen,
  rules screen, map screen, users screen, empty states, errors, loading steps - all of it.
- **Excel template in the program's language**: `GET /api/schema-map/template.xlsx` uses the requesting user's
  language (`?lang=` overrides). English sheet names `How to fill in`, `Dataset`, `Tables`, `Columns`,
  `Business rules`, `Example`; English headers (`TABLE | MODULE | DESCRIPTION | KEYWORDS`, `TABLE | COLUMN | TYPE |
  DESCRIPTION | VALUES | PERSONAL DATA | CLOSED | REFERENCE | NULL`, `ID | TERM | SYNONYMS | DEFINITION | SQL HINT |
  TABLES`); validation lists `Y/N` instead of `E/H`; the instructions sheet and the one-table example written in
  English (the example's coded values and descriptions in English too). The hidden `_bilgin` sheet records the
  language. Import accepts **both** templates regardless of the user's language: `profiles/excel_headers.json` gets
  every English header and sheet name, `E/H` and `Y/N` both read as booleans. Preview errors and warnings come back
  in the user's language. CLI: `python -m nl2sql template --lang tr|en --out FILE`.
- **English golden set and eval**: `real_datasets/wwi_real/golden_en.jsonl` (ids `E01..`, `source_id` pointing to the
  Turkish question, same `sql`, `requires_tables`, `rules`, tags); `dataset.json` `files.golden_en`. `eval --lang en`
  picks it, prints and writes the report in English, and records `lang` in `report.json` and the compare report.
  Business rules gain optional `synonyms_en` (rules editor and template rules sheet carry it) so English questions
  find the same rules; the hybrid search indexes both synonym lists.
- **README**: `README.md` becomes English with a short "Türkçe" link; the Turkish text moves to `README.tr.md`.
  Both describe the same commands.
- **Data outside the code folder** (needed for the service): `NL2SQL_HOME` (default: the repo folder, unchanged for
  development; the service sets `C:\ProgramData\Bilgin`). The app DB (users, sessions, saved questions), logs (ask
  log, audit log, map changes, server log), map previews, eval output and indexes live under it; datasets stay in
  the code folder unless `NL2SQL_DATASETS_DIR` says otherwise, but new datasets created from a template go under
  `NL2SQL_HOME\datasets`. `python -m nl2sql paths` prints every resolved path.
- **Windows service** (`deploy/windows/`, `scripts/install-service.ps1`, `uninstall-service.ps1`,
  `update-service.ps1`):
  - Wrapper: **WinSW** (MIT), one pinned release, downloaded by the install script from its official GitHub release
    and verified against a SHA-256 written in the script; the script stops if the hash differs. No other download.
    Approved by Eren on 2026-10-25 (over pywin32, NSSM and Task Scheduler). If `deploy/windows/WinSW-x64.exe`
    already exists (the operator downloaded it by hand), the script does not download, it only checks the hash.
    The exe is gitignored; tests never download it.
  - Service `Bilgin`, display name "Bilgin - yerel veri analisti" / "Bilgin - local data analyst" (by `NL2SQL_LANG`),
    start type automatic (delayed), restart on failure (3 tries, 10 s / 30 s / 60 s), runs as the virtual account
    `NT SERVICE\Bilgin` (no password to store). Executable: the repo's `.venv\Scripts\python.exe -m nl2sql serve
    --host 127.0.0.1 --port <port> --dataset <name>` (parameters of the install script, defaults 8777 and the active
    dataset). Logs rolled by size under `C:\ProgramData\Bilgin\logs`.
  - Environment of the service: `NL2SQL_HOME`, `NL2SQL_LANG`, `NL2SQL_BACKEND`, `NL2SQL_DATASETS_DIR` in the WinSW XML;
    database connections are **not** asked by the install script and are **not** in the XML: since Run 7 they are
    entered in the admin panel (`Veritabanı bağlantıları`) and stored per dataset, password DPAPI-encrypted at machine
    scope, in the app DB under `NL2SQL_HOME` - so they keep working when the service (virtual account) reads them.
    Only model keys, if a profile needs one, are asked with `Read-Host -AsSecureString` and stored DPAPI-protected
    (machine scope) in `C:\ProgramData\Bilgin\secrets\`, a folder whose ACL allows only Administrators and
    `NT SERVICE\Bilgin`; at startup `serve` reads that folder when `NL2SQL_HOME` points at it. The install script
    offers to copy the existing app DB (users, connections, ready questions) from the development folder into
    `NL2SQL_HOME`, so nothing has to be entered twice. `NL2SQL_DEV_ADMIN_PASSWORD` is never passed
    to the service; the install script refuses to continue while the variable is set at machine level, and creates
    the first admin interactively instead (`user add` with `getpass`).
  - ACLs: `C:\ProgramData\Bilgin` writable by the service account, readable by Administrators; the repo folder
    read-only for the service account.
  - `install-service.ps1` checks: running as administrator, Windows PowerShell 5.1 or 7, the venv exists, the port
    is free, the model endpoint answers (warning only), the active dataset's stored connection passes the Run 7
    read-only guard (warning only, with a pointer to the admin panel); then installs, starts, waits for `/api/health`, prints the URL. `-WhatIf` prints every step and
    the generated XML without changing anything. `update-service.ps1`: stop, `git pull` is **not** done by the script
    (the operator updates the code), rebuild the UI if `web/` changed, start, health check. `uninstall-service.ps1`:
    stop, remove; data in `C:\ProgramData\Bilgin` is kept unless `-RemoveData` is given (and then it asks).
  - The service stays on 127.0.0.1 like `serve`; opening it to the network is out of scope.
- **No commercial ERP product name anywhere, and WWI as the face of the product** (Eren, 2026-10-26: the M22
  screenshots still showed the synthetic ERP dataset as "Sentetik ERP (... benzeri)" with its coded tables):
  - Remove every mention of the commercial ERP product the synthetic dataset imitates from code, comments,
    docstrings, UI text, README files, docs, `pyproject.toml` description, dataset `display_name`s, profile names
    and file names (about 80 mentions in 34 files at the time of writing; a `git grep -i` for the product name over
    the tracked files - `.hybrid/` excluded - must return nothing). The synthetic dataset's display name becomes
    "Sentetik ERP"; its ERP profile file is renamed to a neutral name (e.g. `profiles/erp_tr.json`) with every
    reference updated; its table and column names (`TBLSTHAR`, `CARI_KOD`, ...) stay as they are - they are
    generic coded names, not a brand. Add a test that fails if the name reappears in a tracked file outside
    `.hybrid/` (the name itself stored only as a sha256 in the test, never in clear).
  - Visual review and demo run on the **`wwi` dataset** (the server-less WideWorldImporters copy, SQLite, fake model
    replaying its golden SQL) instead of the synthetic ERP: `.hybrid/visual.json`'s start command, `scripts/
    visual_serve.py` and the smoke scripts serve `--dataset wwi` (`wwi` needs the same fake-model coverage the flows
    use: golden replay, one clarification, one follow-up chain, ready questions - add what is missing to `wwi`'s
    golden/ambiguous/followups files, each SQL run once through the policy on the `wwi` fixture). The synthetic ERP
    stays the main **test** dataset; tests are not moved.
  - `serve` without `--dataset` opens the remembered active dataset (Run 6), else `wwi`, else the first dataset
    with an index - never silently the synthetic ERP. README examples use `wwi` / `wwi_real`.

**Out (not this run):** languages other than Turkish and English, translating database content (descriptions in the
schema stay as the admin wrote them), machine translation of business rules, network exposure / TLS, an MSI
installer, Linux service.

## 3. Milestones

- **M24 - Language core:** `nl2sql/i18n` (catalogs, `t()`, resolution order, `--lang`, `NL2SQL_LANG`), question
  language detection, `users.lang`, per-language number formatting and guard, English narration and clarification
  prompts, facts and template sentence from the catalog. Tests: catalogs have identical key sets and the same
  placeholders per key; a Python AST scan finds no user-facing Turkish literal outside the catalogs in the modules
  that produce API/CLI output (a short allow-list for prompts, comments and test data); English answers with `en`
  formats pass and `tr` formats fail the guard and vice versa; detection on a few dozen Turkish/English questions.
- **M25 - UI, API, CLI and template in English:** web catalogs + `t()` hook + language switch, every screen; API
  messages in the request language; CLI output and help; English template + bilingual import + `template` CLI;
  `synonyms_en`; English golden set and `eval --lang en`; README.md English + README.tr.md. Tests: a scan of the
  built bundle finds no Turkish letters outside the Turkish catalog chunk; each screen renders in both languages
  with the same element ids; the English template round-trips like the Turkish one and both give byte-identical
  `schema.json` for the same content; `eval --lang en --llm fake` scores 26/26 on `golden_en`. Visual flows in both
  languages (login, ask with chart, map screen).
- **M26 - Windows service:** `NL2SQL_HOME` and `paths`, DPAPI secrets folder reader, `deploy/windows/bilgin.xml`
  template, the three scripts with `-WhatIf`, README section "Windows servisi / Windows service". Tests (no real
  service is installed in tests): path resolution under a fake `NL2SQL_HOME`; the generated XML contains the expected
  executable, arguments, environment keys and no secret value; the install script's `-WhatIf` output lists every step
  and refuses when `NL2SQL_DEV_ADMIN_PASSWORD` is set; the secrets reader reads a DPAPI blob written by the test
  (Windows only, skipped elsewhere). The real install/reboot check is Eren's manual test, listed in the README.

## 4. Contracts to keep

- Same element ids, API shapes and payload keys in both languages; only text changes. New payload key `answer_lang`.
- Business data is never translated: table values, names and schema descriptions appear as stored.
- The Turkish experience stays exactly as in Run 6 when the language is `tr`.
- No secret in the repo, the WinSW XML, logs or the `paths` output.
