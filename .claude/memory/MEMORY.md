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
- Fantrax `robots.txt`, Terms of Service and API page read 2026-11-14 (rendered in
  headless Chromium). Terms ban automated scraping and non-published access; the
  API page has no usage terms, only a required `User-Agent`, and does not cover
  the stat tables or transactions. Full findings in `CLAUDE.md`, "Fantrax Terms
  and API".

## Open
- Delete remote branches in the GitHub web UI (delete pushes get a 403 and the
  REST route is blocked from the cloud session). `master` is approved for
  deletion (owner re-confirmed 2026-11-15 after learning it is a copy of
  upstream `pybaseball` history, not a one-commit orphan); the other branches
  are all merged. Full list in `CLAUDE.md`, Known mess. Once they are gone,
  remove that list.
- Check downstream (Decision Engine, Power BI) treats a null Savant percentile
  or expected stat as "not qualified", not zero (about 60% of rows are null).
- Test gaps: Selenium scraper, Supabase load step, standings parser, date helpers.
- **Decide the existing weekly Selenium job.** The Terms (8.6(g), 8.6(c), 8.7)
  ban automated scraping and any access except Fantrax's published interfaces,
  with no exception for your own account. Options: keep it as is (accepting the
  account and league-role risk), move what the API covers to the API, or ask
  Fantrax first. Also review the scraper's "XHR API call" code path for Topps
  transactions (unreviewed).
- Ask Fantrax about the gaps the API doesn't document: hitter/pitcher stat
  tables and transaction history. A written "separate agreement" is the Terms'
  own exception.
- Build the multi-league project on the official API (identifying
  `User-Agent`, caching, conservative polling). Store `userSecretId` as a
  GitHub secret.
- Decide: keep `batches/` tracked?
- Decide whether to turn off Pages on this repo.
