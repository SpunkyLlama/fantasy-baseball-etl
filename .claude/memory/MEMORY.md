# MEMORY.md — project state index

Last updated: 2026-11-14

## Shipped
- Savant ETL runs with the service key (PR #2 merged), combined-name column fix (#3),
  percentile column aliases (#4).
- `CLAUDE.md` and this memory index (PR #5).
- First Green (PR #6): 43 offline pytest tests plus `.github/workflows/tests.yml`,
  which runs on every PR and on pushes to `main`. The PR's check passed on
  Python 3.11. Details and how to run locally are in `CLAUDE.md`.

## Open
- Delete remote branches in the GitHub web UI (git push and the REST API both
  failed from the cloud session): `master` (owner approved), plus the stale
  branches listed in `CLAUDE.md`.
- Run the Savant ETL once (live Supabase — owner's call), then check the log:
  four sources non-zero, `savant_ev_pct` spread ~1–99.
- Decide whether `season` should be uploaded: the loader's `COL_MAP` omits it
  (see `CLAUDE.md`, Known mess).
- Test gaps: Selenium scraper, Supabase load step, standings parser, date helpers.
- Read Fantrax's Terms of Service (browser; the page is JS-rendered). `robots.txt`
  is done: generic rule allows, named AI crawlers are disallowed (details in
  `CLAUDE.md`). Also review the official Fantrax API on the `/developer` page.
- Decide: keep `batches/` tracked? Remove stray `git` file?
- Decide whether to turn off Pages on this repo.
