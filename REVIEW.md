# REVIEW M29 (T446-T454, range fd96283 -> HEAD; T455 integration test still open/untracked)

Whole-project checks: pytest 6629 passed, 1 red (test_cli_lang top help); vitest 1 red (MapScreen.test.jsx:487). Both are stale pins, not regressions.
- **Stale (T488)**: `TODAY_HELP["top"]` in tests/test_cli_lang.py predates the `paths` (T447), `service-check` (T449), `service-xml` (T450) subcommands. Fix task names the test.
- **Stale (T489)**: MapScreen.test.jsx:487 pins the long nav text that T482 moved to `title`/`aria-label`; M28's memory note said only one of the four pins was exempted. Fix task names the test.
- **BUG (T490)**: install-service.ps1 picks the model profile from the installer's shell env (ASSUMPTION at :257) and seals that profile's key, but the WinSW XML has no `BILGIN_LLM_MODEL`; the service runs the default profile and cannot find the key. Contract installer -> service is one-sided.
- Other ASSUMPTIONs checked: BILGIN_HOME read at import (config.py) is consistent with `home_dir()`/`onboard_dir()` and the T446 callers; $PSScriptRoot default, -CopyAppDb are fine. No wrong ones besides the profile one.
- Risk: dataset `db_path` and `mssql_script` still resolve under the repo (`ROOT/data`, `db/mssql`) while the service account gets ReadAndExecute on the repo; any code path that builds or writes a dataset db (onboard writes `outputs.db: data/<name>.db`) fails under the service. Index/eval_out moved to HOME correctly.
- Risk: `$WinSwSha256` is empty by design, so the install path past `winsw` has never run for real; only -WhatIf is tested. T455 (real serve with BILGIN_HOME) is the only end-to-end cover and is not done.
- Missing test: no test that the service XML env and the install script's profile/key choice agree (added in T490).
