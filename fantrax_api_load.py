"""Fetch Fantrax API data for every league in leagues.json and (optionally) load it to Supabase.

DRY RUN IS THE DEFAULT. Without --load this script fetches, validates and prints row counts,
and never opens a database connection. A live load needs --load AND the owner's go-ahead
(CLAUDE.md: anything that touches Supabase).

Live load, per league, in ONE transaction:
  upsert fantrax_api.leagues row -> delete that league's child rows -> insert fresh rows.
Other leagues are never touched, and nothing is TRUNCATEd. If any step fails the league is
rolled back and the previous data stays. A league is skipped (not loaded) when validation fails
or when teams / rosters / standings come back empty, so a bad API response cannot wipe a league.

Env: FANTRAX_USER_AGENT (always), SUPABASE_PASSWORD (only with --load),
     SUPABASE_HOST / SUPABASE_USER / SUPABASE_DB / SUPABASE_PORT (optional overrides).
Exit codes: 0 ok, 1 a league failed validation or load, 2 schema missing (apply sql/ first).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import fantrax_api as fa

SCHEMA = "fantrax_api"

# table -> (columns, primary-key columns, json columns)
TABLES: dict[str, tuple[list[str], list[str], set[str]]] = {
    "leagues": (["league_id", "sport", "name", "season", "scoring_type", "scoring",
                 "roster_rules", "start_date", "end_date"], ["league_id"], {"scoring", "roster_rules"}),
    "teams": (["league_id", "team_id", "name", "division"], ["league_id", "team_id"], set()),
    "rosters": (["league_id", "team_id", "player_id", "period", "position", "status",
                 "contract", "salary"], ["league_id", "team_id", "player_id"], set()),
    "standings": (["league_id", "team_id", "rank", "record", "win_pct", "games_back",
                   "total_points_for"], ["league_id", "team_id"], set()),
    "draft_picks": (["league_id", "year", "round", "original_team_id", "current_team_id"],
                    ["league_id", "year", "round", "original_team_id"], set()),
    "draft_results": (["league_id", "division", "round", "pick", "team_id", "player_id", "picked_at"],
                      ["league_id", "division", "pick"], set()),
    "players": (["player_id", "sport", "name", "team", "position"], ["sport", "player_id"], set()),
}
CHILD_TABLES = ["teams", "rosters", "standings", "draft_picks", "draft_results"]  # replaced per league
REQUIRED_NONEMPTY = ["teams", "rosters", "standings"]  # draft tables may be empty before a draft


def validate_league(lid: str, tables: dict[str, list[dict]]) -> list[str]:
    """Return a list of problems; empty list means safe to load."""
    errs = []
    for name in REQUIRED_NONEMPTY:
        if not tables.get(name):
            errs.append(f"{lid}: {name} is empty (refusing to replace existing data with nothing)")
    for name in ["leagues", *CHILD_TABLES]:
        _cols, key, _j = TABLES[name]
        seen, dups = set(), 0
        for r in tables.get(name, []):
            k = tuple(r.get(c) for c in key)
            if any(v is None for v in k):
                errs.append(f"{lid}: {name} has a null key column {key}")
                break
            dups += k in seen
            seen.add(k)
        if dups:
            errs.append(f"{lid}: {name} has {dups} duplicate primary keys {key}")
    team_ids = {t["team_id"] for t in tables.get("teams", [])}
    for name, col in [("rosters", "team_id"), ("standings", "team_id")]:
        orphans = {r[col] for r in tables.get(name, [])} - team_ids
        if orphans:
            errs.append(f"{lid}: {name}.{col} has {len(orphans)} ids not in teams")
    return errs


def _values(name: str, row: dict) -> tuple:
    cols, _key, jcols = TABLES[name]
    from psycopg2.extras import Json
    return tuple(Json(row.get(c)) if c in jcols and row.get(c) is not None else row.get(c) for c in cols)


def _insert_sql(name: str, upsert: bool = False) -> str:
    cols, key, _j = TABLES[name]
    sql = (f"INSERT INTO {SCHEMA}.{name} ({', '.join(cols)}) "
           f"VALUES ({', '.join(['%s'] * len(cols))})")
    if upsert:
        sets = [f"{c} = EXCLUDED.{c}" for c in cols if c not in key]
        if name == "leagues":  # only table with a fetched_at to refresh on upsert
            sets.append("fetched_at = now()")
        sql += f" ON CONFLICT ({', '.join(key)}) DO UPDATE SET {', '.join(sets)}"
    return sql


def _batch(cur, sql: str, rows: list[tuple]) -> None:
    from psycopg2.extras import execute_batch
    execute_batch(cur, sql, rows, page_size=500)


def load_league(cur, lid: str, tables: dict[str, list[dict]]) -> dict[str, int]:
    """Replace one league's data. Caller owns the transaction (commit / rollback)."""
    counts = {}
    lg = tables["leagues"]
    _batch(cur, _insert_sql("leagues", upsert=True), [_values("leagues", r) for r in lg])
    counts["leagues"] = len(lg)
    for name in CHILD_TABLES:  # children first deleted, then reinserted, all inside the transaction
        cur.execute(f"DELETE FROM {SCHEMA}.{name} WHERE league_id = %s", (lid,))
    for name in CHILD_TABLES:
        rows = tables.get(name, [])
        if rows:
            _batch(cur, _insert_sql(name), [_values(name, r) for r in rows])
        counts[name] = len(rows)
    return counts


def load_players(cur, rows: list[dict]) -> int:
    if rows:
        _batch(cur, _insert_sql("players", upsert=True), [_values("players", r) for r in rows])
    return len(rows)


def connect():
    import psycopg2
    pw = os.environ.get("SUPABASE_PASSWORD")
    if not pw:
        raise RuntimeError("SUPABASE_PASSWORD is required for --load")
    return psycopg2.connect(
        host=os.environ.get("SUPABASE_HOST", "aws-1-us-east-2.pooler.supabase.com"),
        port=int(os.environ.get("SUPABASE_PORT", "5432")),
        dbname=os.environ.get("SUPABASE_DB", "postgres"),
        user=os.environ.get("SUPABASE_USER", "postgres.rlwidfirrdwolaywjpca"),
        password=pw, sslmode="require", gssencmode="disable",
    )


def schema_present(cur) -> bool:
    cur.execute("SELECT to_regclass(%s)", (f"{SCHEMA}.leagues",))
    return cur.fetchone()[0] is not None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--config", default=str(Path(__file__).parent / "leagues.json"))
    ap.add_argument("--league", help="only this league_id")
    ap.add_argument("--load", action="store_true", help="write to Supabase (default: dry run)")
    ap.add_argument("--players", action="store_true", help="also load the player id map per sport")
    ap.add_argument("--out", help="also write fetched tables as JSON into this directory")
    args = ap.parse_args(argv)

    leagues = json.loads(Path(args.config).read_text())["leagues"]
    if args.league:
        leagues = [l for l in leagues if l["league_id"] == args.league]
    if not leagues:
        print("no leagues to process", file=sys.stderr)
        return 1

    mode = "LOAD" if args.load else "DRY RUN (no database connection)"
    print(f"mode: {mode}")
    api = fa.FantraxApi()
    fetched: dict[str, dict[str, list]] = {}
    for lg in leagues:
        print(f"fetching {lg['key']} ({lg['league_id']}, {lg.get('sport')})")
        fetched[lg["league_id"]] = fa.fetch_league(api, lg["league_id"], lg.get("sport"))
    players: list[dict] = []
    if args.players:
        for sport in sorted({l["sport"] for l in leagues if l.get("sport")}):
            players += fa.norm_players(api.get("getPlayerIds", sport=sport), sport)

    if args.out:
        out = Path(args.out)
        out.mkdir(parents=True, exist_ok=True)
        for lid, t in fetched.items():
            for name, rows in t.items():
                (out / f"{lid}_{name}.json").write_text(json.dumps(rows, indent=1))

    failed, ok_leagues = [], []
    for lid, t in fetched.items():
        errs = validate_league(lid, t)
        print(f"\n{lid}: " + ", ".join(f"{n}={len(r)}" for n, r in t.items()))
        if errs:
            failed.append(lid)
            for e in errs:
                print(f"  INVALID: {e}")
        else:
            ok_leagues.append(lid)
            print("  validation: ok")
    if players:
        print(f"\nplayers: {len(players)}")

    if not args.load:
        print("\ndry run complete; nothing written.")
        return 1 if failed else 0

    conn = connect()
    try:
        with conn.cursor() as cur:
            if not schema_present(cur):
                print(f"schema {SCHEMA} not found; apply sql/fantrax_api_schema.sql first", file=sys.stderr)
                return 2
        for lid in ok_leagues:
            try:
                with conn.cursor() as cur:
                    counts = load_league(cur, lid, fetched[lid])
                conn.commit()
                print(f"loaded {lid}: " + ", ".join(f"{n}={c}" for n, c in counts.items()))
            except Exception as exc:  # roll back this league only; keep going with the rest
                conn.rollback()
                failed.append(lid)
                print(f"FAILED {lid}, rolled back: {type(exc).__name__}: {exc}", file=sys.stderr)
        if players:
            try:
                with conn.cursor() as cur:
                    n = load_players(cur, players)
                conn.commit()
                print(f"loaded players: {n}")
            except Exception as exc:
                conn.rollback()
                failed.append("players")
                print(f"FAILED players, rolled back: {type(exc).__name__}: {exc}", file=sys.stderr)
    finally:
        conn.close()
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
