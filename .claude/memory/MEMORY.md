# MEMORY.md — project state index

Last updated: 2026-11-14

## Shipped
- Savant ETL runs with the service key (PR #2 merged), combined-name column fix (#3),
  percentile column aliases (#4). Offline stub test: 18 CSV columns, 16/16
  loader-mapped columns.
- `CLAUDE.md` written (draft, awaiting owner review).

## Open
- Delete remote `master` (owner approved; git push and the REST API both failed
  from the cloud session — delete in the GitHub web UI: Branches page, trash icon).
- Run the Savant ETL once (live Supabase — owner's call), then check the log:
  four sources non-zero, `savant_ev_pct` spread ~1–99.
- First Green: add tests + a PR-triggered CI workflow.
- Review Fantrax `robots.txt` and terms.
- Delete stale remote branches (list in CLAUDE.md).
- Decide: keep `batches/` tracked? Remove stray `git` file?
- Decide whether to turn off Pages on this repo.
