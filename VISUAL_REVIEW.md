# VISUAL_REVIEW — M28 (web UI in English), 2026-10-28

**Run caveat.** This server and bundle are current (the login refusal comes back as "The username or password is wrong." and `bilgin/web/static` was built at 03:18, two minutes before the first frame), but the 1366 pass lost its last shots on `saved-and-history-sidebar`, `admin-map-onboard` and `conversation-three-turns` to shared-server state, not to the UI: `#sidebar-toggle` is `display:none` at desktop width, and `#map-apply` was already disabled by the `ornek_fatura` the 390 pass had created. The 401 lines are the boot `/api/auth/me` probe, the 429 the card-refresh throttle, the 409 the duplicate username.

## Real problems

- **Every English page (`en-login`, `en-ask-chart`, `en-map-screen`, both widths).** The EN pill is pressed and the page is Turkish: only the boot language's catalog is ever fetched (`main.jsx:21`), so `makeT("en")` finds an empty catalog and silently falls back to Turkish, while the server's own lines (the login refusal, the fan-out warning, "This name is already a dataset") do come back in English. The milestone's whole deliverable is invisible in the running app, and the tests cannot see it because `web/src/test-setup.js` registers both catalogs.
- **Masthead at 1366.** Run 8 put `Bağlantılar` and `TR|EN` in the same row, and "Hazır sor" is now cut mid-word behind the fade mask with the scrollbar hidden — on an ordinary laptop a destination looks unreachable and nothing says the row scrolls.
- **Pie chart (`conversation-three-turns` turn 3, both widths).** Five outer labels stack on top of each other ("…Beacon Ceramic Mug: 3.764," with an orphan "62" under them): the chart's own numbers cannot be read, and since T377 removed the legend nothing else carries the names either.
- **Connections and users rows at 390.** A row is a column of four bare "—" with no column names — the CSS-generated labels never appear — so an untested connection reads as a broken render instead of "no server, no last check, no last error".
- **Hazır sorular (admin).** 4746 px of near-identical cards at 390; the twelve "Onay bekliyor" rows, the only actionable ones, sit interleaved with the approved ones under five role headings.

## Craft ideas

- **Users rows.** Two dropdowns per row with nothing naming them, and a lone "—" where a never-signed-in user's last sign-in belongs: captions plus `Hiç giriş yapmadı` cost nothing and make the table readable.
- **Map screen's 1·2·3 ladder.** Only step 1 ever gets its ✓; steps 2 and 3 keep their numbered badges after the file is checked and the dataset created, so the ladder reads as decoration instead of progress.

Not filed (harness or deliberate): the "Satır sayısı N." headlines and the fake replay's mismatched tables, the 401 boot probe, the pale dark-mode Sor button, "4 satır indirildi" with no CSV counterpart, the horizontally scrolled nav at 390, and the 64 px truncated bar category names (`chart.py:41-58`, chosen twice before to stop overlap).
