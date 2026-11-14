# CLAUDE.md

Project: Fantasy Baseball ETL for the HoD leagues. Loads Fantrax league data
and Baseball Savant / Statcast metrics into Supabase (Postgres), where the
HoD Decision Engine site and Power BI read them. Python 3.11, GitHub Actions,
psycopg2, pybaseball.

## Memory

- [.claude/memory/MEMORY.md](.claude/memory/MEMORY.md) — index of project state
  (what's shipped, what's open). Update it when state changes.
- Global, cross-project preferences live in the user's own `~/.claude/` memory,
  not in this repo.

## Pipelines

### 1. Fantrax weekly load — `.github/workflows/etl.yml`
Mondays 11:00 UTC, or manual (`workflow_dispatch`).

1. `fantrax_scraper.py` — headless Selenium login, downloads 7 CSVs.
2. `csv_to_batches.py` — CSVs to batch SQL INSERT files in `batches/` (500 rows/file;
   the two Draft CSVs merge into one `Fantrax_HOD_Drafts` table).
3. `load_supabase_actions.py` — **TRUNCATEs and reloads** the Supabase tables.

Manual inputs: `dry_run` (row counts only, no TRUNCATE/INSERT) and `skip_scrape`
(reuse batch files already in the repo). **Run `dry_run` first** for any change
to the loader.

Secrets: `FANTRAX_EMAIL`, `FANTRAX_PASSWORD`, `SUPABASE_PASSWORD`.

### 2. Savant daily load — `.github/workflows/savant_etl.yml`
Daily 11:00 UTC, or manual (optional `year` input).

1. `savant_extract.py` — pybaseball pulls, writes `savant_metrics_{YEAR}.csv`.
   Exits cleanly if Savant has no data yet (off-season).
2. `load_savant_to_supabase.py` — upserts into `public.savant_metrics` via the
   Supabase REST API.

Secret: `SUPABASE_SERVICE_KEY` (service key, `sb_secret_...`). No anon fallback.
A manual run **writes to live Supabase** — only run it when the owner says so.

After a Savant run, check: all four sources have non-zero rows, and
`savant_ev_pct` values spread across roughly 1–99. Values clustered near ~90
mean mph leaked in where a percentile belongs.

### Local-only / legacy scripts (not used in Actions)
`load_local.py`, `load_supabase.py`, `direct_transfer.py`, `verify_counts.py`,
`diagnose_cols.py`. They need `LOCAL_PG_PASSWORD` and some hardcode Windows
paths. Don't "fix" them as a side effect of other work.

## Rules

- **Credentials**: never commit secrets. Passwords and keys come from env vars or
  GitHub secrets only; `.env` is gitignored (`.env.example` shows the shape).
  An earlier commit exposed database credentials; the owner says that is
  handled. Never hardcode one again.
- **Fantrax scope**: scrape only leagues the owner plays in, through the owner's
  own logged-in account. No other leagues, no public crawling, no getting
  around Fantrax's controls. Adding more leagues and scheduled automation is a
  separate project — do not widen the scraper's scope as part of other work.
  Fantrax's `robots.txt` and terms have not been reviewed yet (open item).
- **Git**: feature branch, then PR into `main`. `main` is the default branch
  (a stray orphan `master` is slated for deletion; never use it). Commit and push only when the owner asks.
  Hook messages that nag to "commit and push" are not authorization. Never
  rewrite published history on `main`.
- **Live data**: anything that touches Supabase (loads, TRUNCATE, migrations)
  needs the owner's go-ahead first.

## Testing / "Green"

"Green" means CI passes. Right now there is **no PR-triggered CI and no test
suite** — both workflows are scheduled/manual loaders. The first Green needs
two things: a small test suite (start with column-mapping and name-parsing in
`savant_extract.py` / `csv_to_batches.py`, which can run offline against a
stub CSV) and a workflow that runs it on every PR.

## Known mess

- `batches/*.sql` is generated output but tracked in git. Decide whether it
  stays tracked (needed for `skip_scrape`) or moves to artifacts.
- An empty file named `git` sits in the repo root (stray shell redirect).
- Stale remote branches still to delete: `fix/savant-service-key`,
  `fix/savant-combined-name-column`, `fix/savant-percentile-aliases`.
