# REVIEW M24 (T316-T331 + visual review T376-T382; range a283ad4^ -> b70e2c5)

Whole-project checks: 19 suite/smoke commands pass; I re-read the diff against PLAN R7-16..R7-21 and the "ready question / start card / ready seed line / suggest job" contracts.

- **BUG (T383)**: `StartCache` keys on the SQL digest only, but the cached payload embeds title/question/display; a `PUT /api/ready-questions/{id}` edit of those fields shows the old card on the board for up to 300 s.
- **BUG (T384)**: personal-card unpin has a route and an `api.unpinCard`, but no component calls it; after 6 pins "Panoma ekle" 409s for good and only an admin can clean up.
- Visual-review findings already queued: T376 (wwi has no ready seeds -> empty board, two flows die), T377 (phone chart labels/legend), T378 (second "Öneri iste" duplicates), T379 (alias labels), T380 (turn-count wording), T381-T382 (polish).
- ASSUMPTIONs checked and holding: per-dataset personal-card cap (ready.py `_check_cap`), executor-owned policy filter for seeds (seed.py), label read from `executor._pii_schema` (SessionExecutor forwards it), personal pin needs a username (409 AUTH_OFF), open only via POST /open.
- Contracts traced: start card keys vs StartCard/startCards.js (value/label/chart/columns/rows/error/refreshed_at/personal) match; suggest job keys match the screen's poll; ready create body never carries `sql`; ROUTE_ROLES rows match the real routes.
- Risk: an error payload (e.g. DB briefly down) is cached 300 s for every user, refresh limited to 1/30 s per card.
- Risk: `PUT /api/ready-questions/{id}` takes an untyped dict - `position: "x"`, empty `title`, or `business_role: null` on a seed row (created_by NULL, invisible to everyone, cap skipped) are accepted.
- Risk: `SuggestJobs._jobs` and `StartCache._refreshed/_locks` never evict (bounded by use, slow growth).
- Missing tests: edit-then-board freshness (T383), unpin UI (T384), PUT field validation, a second dataset switch not re-seeding, error-card caching.
