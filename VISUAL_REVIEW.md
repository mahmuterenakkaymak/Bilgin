# Visual review — M18 (Run 6 web UI + login, `scripts/visual_serve.py`)

## Real problems
1. **Chart · both widths** — the bars are mostly anonymous: only 2 of 5 products have an x-label at 390 and 3 of 5 at 1366, because ECharts' default `axisLabel.interval="auto"` silently drops overlapping category labels. `chart.py::_cartesian` never sets `axisLabel`, so the middle bars of the golden answer carry no name and the chart reads as broken next to a table that names all five.
2. **Ambiguous answer · both widths** — a 1-row/1-column result is rendered as a table, and `.result-table` is `width:100%`, so the answer **191.722,79** sits right-aligned alone at the far edge of an empty box. The number the whole clarification flow exists to produce is the smallest thing on the page.
3. **Ambiguous answer · both widths** — after choosing "KDV hariç ciro (hareket satırından)" the card says only "Satır sayısı 1."; nothing records which of the three readings produced the figure. `App` keeps `state.choice` and the payload echoes it, `AnswerCard` never shows it. For a product whose promise is "sonucu ve nasıl hesapladığını gösterir", this is the worst omission in the run.
4. **Chart · both widths** — "Satış miktarı" is printed twice within 40px (centred bold title + y-axis name): `chartFormat.js::withNames` sets both from the same column. M17 asked for a title; this is the same fix taken twice, and it is the classic unfinished-chart tell.
5. **Rules · 390px** — `#rule-errors` renders at the top of a form that is ~1400px tall while Kaydet sits at the bottom, so the rejected tap produces no visible change where the user is looking. The summary and the field errors are all correct — they are just off screen.

## Craft ideas (cheap, clearly better)
6. Saved rows are three identical "Eylül 2026'da en çok satan 5 ürün h…" lines with nothing to tell them apart, while history rows already carry "şimdi / 1 dk önce" — `saved.py` already stores `created_at`, so the saved list is one column behind its own sibling.
7. The health state is a bare 10px dot floating between Sistem and the user chip (tooltip-only), and the phone header already spends three rows on pills of equal weight; one word ("Hazır") makes it readable and lets the chip + Çıkış join the nav row.

## Checked, not problems
Header chip does not overflow at 390 (matches the CSS note); logout clears answer, history and fields; the login gate, deep link and wrong-password error read well at both widths; dark mode repaints the chart tokens; the black band and the header mid-page in full-page shots are a Playwright sticky-header artifact, not a page bug. The 401 console errors are the pre-login `/api/auth/me` probe, which is the gate working.
