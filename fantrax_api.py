"""Fantrax official REST API client + normalizers (replaces Selenium where the API covers the data).

Uses only documented endpoints under https://www.fantrax.com/fxea/general/ (see CLAUDE.md,
"Fantrax Terms and API"). Rules: identifying User-Agent on every call, >=1s between calls,
own leagues only, userSecretId (if ever used) comes from the environment and is never logged.

Usage:
    FANTRAX_USER_AGENT="HoD-DecisionEngine/1.0" python fantrax_api.py --out api_out
Reads leagues.json, fetches every league, writes one JSON file per table to --out.
It never touches Supabase; loading is a separate, owner-approved step.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

BASE = "https://www.fantrax.com/fxea/general"
CALL_DELAY = 1.0
RETRIES = 3


class FantraxApi:
    def __init__(self, user_agent: str | None = None, session=None, sleep=time.sleep):
        ua = user_agent or os.environ.get("FANTRAX_USER_AGENT", "")
        if not ua:
            raise RuntimeError("FANTRAX_USER_AGENT is required (Fantrax rejects requests without one)")
        self.session = session or requests.Session()
        self.session.headers.update({"User-Agent": ua, "Accept": "application/json"})
        self._sleep = sleep
        self._cache: dict = {}

    def get(self, endpoint: str, **params):
        params = {k: v for k, v in params.items() if v is not None}
        key = (endpoint, tuple(sorted(params.items())))
        if key in self._cache:
            return self._cache[key]
        for attempt in range(1, RETRIES + 1):
            resp = self.session.get(f"{BASE}/{endpoint}", params=params, timeout=60)
            self._sleep(CALL_DELAY)
            if resp.status_code in (429, 500, 502, 503, 504) and attempt < RETRIES:
                self._sleep(5 * attempt)
                continue
            resp.raise_for_status()
            break
        # Fantrax labels its JSON "text/plain" with no charset, so requests would guess
        # Latin-1 and mangle emoji / accented names. The body is UTF-8.
        resp.encoding = "utf-8"
        data = resp.json()
        self._cache[key] = data
        return data


# ── Normalizers: API JSON -> flat rows keyed by league_id ────────────────────

def norm_league(lid: str, info: dict, sport: str | None = None) -> dict:
    return {
        "league_id": lid,
        "sport": sport,
        "name": info.get("leagueName"),
        "season": info.get("seasonYear"),
        "scoring_type": (info.get("scoringSystem") or {}).get("type"),
        "start_date": info.get("startDate"),
        "end_date": info.get("endDate"),
        "scoring": (info.get("scoringSystem") or {}).get("scoringCategorySettings"),
        "roster_rules": info.get("rosterInfo"),
    }


def norm_teams(lid: str, info: dict) -> list[dict]:
    teams = info.get("teamInfo") or {}
    return [
        {"league_id": lid, "team_id": tid, "name": t.get("name"), "division": t.get("division")}
        for tid, t in teams.items()
    ]


def norm_rosters(lid: str, data: dict) -> list[dict]:
    rows = []
    period = data.get("period")
    for tid, team in (data.get("rosters") or {}).items():
        for it in team.get("rosterItems") or []:
            c = it.get("contract") or {}
            rows.append({
                "league_id": lid, "team_id": tid, "period": period,
                "player_id": it.get("id"), "position": it.get("position"),
                "status": it.get("status"),
                "contract": c.get("name"),  # absent for leagues without contracts
                "salary": it.get("salary"),
            })
    return rows


def norm_standings(lid: str, data: list) -> list[dict]:
    return [
        {"league_id": lid, "team_id": s.get("teamId"), "rank": s.get("rank"),
         "record": s.get("points"), "win_pct": s.get("winPercentage"),
         "games_back": s.get("gamesBack"), "total_points_for": s.get("totalPointsFor")}
        for s in data or []
    ]


def norm_draft_picks(lid: str, data: dict) -> list[dict]:
    return [
        {"league_id": lid, "year": p.get("year"), "round": p.get("round"),
         "original_team_id": p.get("originalOwnerTeamId"),
         "current_team_id": p.get("currentOwnerTeamId")}
        for p in (data or {}).get("futureDraftPicks") or []
    ]


def norm_draft_results(lid: str, data: dict) -> list[dict]:
    rows = []
    for p in (data or {}).get("draftPicks") or []:
        ms = p.get("time")
        rows.append({
            "league_id": lid, "division": p.get("division"), "round": p.get("round"),
            "pick": p.get("pick"), "team_id": p.get("teamId"), "player_id": p.get("playerId"),
            "picked_at": datetime.fromtimestamp(ms / 1000, timezone.utc).isoformat() if ms else None,
        })
    return rows


def norm_players(data: dict, sport: str) -> list[dict]:
    return [
        {"player_id": pid, "sport": sport, "name": p.get("name"), "team": p.get("team"), "position": p.get("position")}
        for pid, p in (data or {}).items()
    ]


def fetch_league(api: FantraxApi, lid: str, sport: str | None = None) -> dict[str, list]:
    info = api.get("getLeagueInfo", leagueId=lid, excludePlayerInfo="true")
    return {
        "leagues": [norm_league(lid, info, sport)],
        "teams": norm_teams(lid, info),
        "rosters": norm_rosters(lid, api.get("getTeamRosters", leagueId=lid)),
        "standings": norm_standings(lid, api.get("getStandings", leagueId=lid)),
        "draft_picks": norm_draft_picks(lid, api.get("getDraftPicks", leagueId=lid)),
        "draft_results": norm_draft_results(lid, api.get("getDraftResults", leagueId=lid)),
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--config", default=str(Path(__file__).parent / "leagues.json"))
    ap.add_argument("--out", default="api_out")
    ap.add_argument("--league", help="only this league_id")
    ap.add_argument("--players", action="store_true", help="also fetch the player id map for each configured sport (~1 MB each)")
    args = ap.parse_args(argv)

    leagues = json.loads(Path(args.config).read_text())["leagues"]
    if args.league:
        leagues = [l for l in leagues if l["league_id"] == args.league]
    if not leagues:
        print("no leagues to fetch", file=sys.stderr)
        return 1

    api = FantraxApi()
    tables: dict[str, list] = {}
    for lg in leagues:
        print(f"fetching {lg['key']} ({lg['league_id']})")
        for name, rows in fetch_league(api, lg["league_id"], lg.get("sport")).items():
            tables.setdefault(name, []).extend(rows)
    if args.players:  # one ~1 MB call per distinct sport among the configured leagues
        for sport in sorted({l["sport"] for l in leagues if l.get("sport")}):
            tables.setdefault("players", []).extend(norm_players(api.get("getPlayerIds", sport=sport), sport))

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    for name, rows in tables.items():
        (out / f"{name}.json").write_text(json.dumps(rows, indent=1))
        print(f"  {name}: {len(rows)} rows")
    return 0


if __name__ == "__main__":
    sys.exit(main())
