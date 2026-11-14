# MEMORY.md — project state index

Last updated: 2026-11-14

## Shipped
- Savant ETL runs with the service key (PR #2 merged), combined-name column fix (#3),
  percentile column aliases (#4).
- `CLAUDE.md` and this memory index (PR #5).
- First Green (PR #6): 43 offline pytest tests plus `.github/workflows/tests.yml`,
  which runs on every PR and on pushes to `main`. The PR's check passed on
  Python 3.11. Details and how to run locally are in `CLAUDE.md`.
- Live Savant ETL run 2026-11-14 (run 43640273764, owner-approved): 1,317 rows
  upserted, 0 errors. All sources non-zero; `savant_ev_pct` in the DB runs 1–100
  with quartiles 24/47/73, so it is a percentile, not mph.
- Non-null counts per column in the Savant extract log (PR #10). Second live run
  2026-11-14 (run 43646213135, owner-approved): 1,317 rows, 0 errors. Hitters 245
  of 611 and pitchers 339 of 706 have percentiles/expected stats, the same players
  for both, so the blanks are Savant's (apparently unqualified players), not a
  loading bug. Details in `CLAUDE.md`.
- `savant_metrics` has no `season` column, so omitting it from `COL_MAP` is
  correct (see `CLAUDE.md`, Known mess).

## Open
- Delete remote branches in the GitHub web UI (git push and the REST API both
  failed from the cloud session): `master` (owner approved), plus the stale
  branches listed in `CLAUDE.md`.
- Check downstream (Decision Engine, Power BI) treats a null Savant percentile
  or expected stat as "not qualified", not zero (about 60% of rows are null).
- Test gaps: Selenium scraper, Supabase load step, standings parser, date helpers.
- Read Fantrax's Terms of Service (browser; the page is JS-rendered). `robots.txt`
  is done: generic rule allows, named AI crawlers are disallowed (details in
  `CLAUDE.md`). Also review the official Fantrax API on the `/developer` page.
- Decide: keep `batches/` tracked? Remove stray `git` file?
- Decide whether to turn off Pages on this repo.
