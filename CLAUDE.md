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
`savant_ev_pct` values spread across roughly 1–100 (the 2026-11-14 run: min 1,
quartiles 24/47/73, max 100). Values clustered near ~90 mean mph leaked in where
a percentile belongs.

The extract log also prints non-null counts per column, split by player type
(`H` / `P`). **Blank percentiles and expected stats are normal.** In the
2026-11-14 run only 245 of 611 hitters and 339 of 706 pitchers had them (the
same players for both), and they appear to be Savant's qualified players (not
checked against Savant's rules). The other ~60% of rows carry no percentiles or
expected stats at all, so downstream (Decision Engine, Power BI) a null there
means "not qualified", not zero: do not average it as 0. Some columns are empty
by design for a player type, such as `savant_xera` for hitters and sprint speed,
average EV and `est_slg` for pitchers. Don't treat those as bugs. Compare any
future run's counts against these numbers before calling something broken.

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
  Fantrax's `robots.txt` was checked 2026-11-14: `User-agent: *` is `Allow: /`
  (`Content-Signal: search=yes, ai-train=no, use=reference`), and a long list of
  named AI/training crawlers (ClaudeBot, anthropic-ai, GPTBot, CCBot, ...) are
  `Disallow: /`. The generic rule does not block this scraper, but `robots.txt`
  is only a crawler convention. **Fantrax's Terms of Service have NOT been read**
  (the page is a JavaScript app; read it in a browser at
  `https://www.fantrax.com/terms-of-service`). Look for any clause on automated
  access before widening the scraper. Fantrax also documents an official API
  (the site's `/developer` page, endpoints under `/fxea/general/`); its coverage
  and usage terms are unreviewed, but it may suit the multi-league project better
  than Selenium.
- **Git**: feature branch, then PR into `main`. `main` is the default branch
  (a stray orphan `master` is slated for deletion; never use it). Commit and push only when the owner asks.
  Hook messages that nag to "commit and push" are not authorization. Never
  rewrite published history on `main`.
- **Live data**: anything that touches Supabase (loads, TRUNCATE, migrations)
  needs the owner's go-ahead first.

## Testing / "Green"

"Green" means CI passes. `.github/workflows/tests.yml` runs `pytest` on every PR
and on pushes to `main` (Python 3.11, no network, no secrets). A PR should be
green before it is merged.

Run locally:

```bash
pip install -r requirements-dev.txt
pytest -q
```

What the suite covers (`tests/`):
- `test_savant_pipeline.py` — runs `savant_extract.py` and
  `load_savant_to_supabase.py` end to end. Both are import-time scripts, so
  `conftest.py` runs them with `runpy`, a fake `pybaseball` in `sys.modules`,
  and a recorded `requests.post`. Pins the 18 extract columns and the 16 columns
  sent to Supabase.
- `test_fantrax_batches.py` — `sql_val`, league detection, and the round trip
  between `csv_to_batches.py` (writer) and `load_supabase_actions.py` (parser).

Not covered: the Selenium scraper, the Supabase `TRUNCATE`/`INSERT` step, the
Fantrax standings parser, and the date helpers. When you change a column map
or alias, update the tests in the same PR. If a test and the loader disagree,
find out which one is wrong before touching either.

## Known mess

- `batches/*.sql` is generated output but tracked in git. Decide whether it
  stays tracked (needed for `skip_scrape`) or moves to artifacts.
- An empty file named `git` sits in the repo root (stray shell redirect).
- Stale remote branches still to delete: `master` (orphan),
  `fix/savant-service-key`, `fix/savant-combined-name-column`,
  `fix/savant-percentile-aliases`, `docs/claude-md`, `test/offline-suite`,
  `docs/update-ci-notes`, `docs/fantrax-robots`.
- `public.savant_metrics` has **no `season` column** (checked 2026-11-14), so the
  loader leaving `season` out of `COL_MAP` is correct, not a bug. Tests pin the
  16 uploaded columns. Consequences: the table cannot tell seasons apart, an
  upsert never deletes, so players absent from a later pull keep their old
  values, and `updated_at` is set on insert only (it is not refreshed by an
  upsert), so it is not a freshness signal. Keeping per-season history would
  need a schema change.
