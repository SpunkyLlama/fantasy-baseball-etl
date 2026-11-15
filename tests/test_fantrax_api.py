"""Offline tests for fantrax_api.py (no network). Shapes taken from the live API, 2026-11-15."""
import pytest

import fantrax_api as fa


class FakeResp:
    def __init__(self, status=200, payload=None):
        self.status_code, self._p = status, payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._p


class FakeSession:
    def __init__(self, resps):
        self.headers, self.calls, self._r = {}, [], list(resps)

    def get(self, url, params=None, timeout=None):
        self.calls.append((url, params))
        return self._r.pop(0)


def test_user_agent_required(monkeypatch):
    monkeypatch.delenv("FANTRAX_USER_AGENT", raising=False)
    with pytest.raises(RuntimeError):
        fa.FantraxApi(session=FakeSession([]))


def test_sends_user_agent_sleeps_and_caches():
    s, sleeps = FakeSession([FakeResp(payload={"a": 1})]), []
    api = fa.FantraxApi("T/1", session=s, sleep=sleeps.append)
    assert api.get("getStandings", leagueId="x") == {"a": 1}
    assert api.get("getStandings", leagueId="x") == {"a": 1}  # cached, no 2nd call
    assert len(s.calls) == 1 and s.headers["User-Agent"] == "T/1"
    assert sleeps == [fa.CALL_DELAY]


def test_retries_then_succeeds_and_raises_on_4xx():
    s = FakeSession([FakeResp(503), FakeResp(payload={"ok": 1})])
    assert fa.FantraxApi("T/1", session=s, sleep=lambda _: None).get("e") == {"ok": 1}
    with pytest.raises(RuntimeError):
        fa.FantraxApi("T/1", session=FakeSession([FakeResp(403)]), sleep=lambda _: None).get("e")


def test_norm_rosters_with_and_without_contracts():
    data = {"period": 187, "rosters": {"t1": {"teamName": "A", "rosterItems": [
        {"contract": {"smallId": "0", "name": "1st"}, "id": "05tzn", "position": "P",
         "salary": 7480000.0, "status": "RESERVE"},
        {"id": "03qyv", "position": "OF", "status": "ACTIVE"}]}}}
    r = fa.norm_rosters("L", data)
    assert r[0] == {"league_id": "L", "team_id": "t1", "period": 187, "player_id": "05tzn",
                    "position": "P", "status": "RESERVE", "contract": "1st", "salary": 7480000.0}
    assert r[1]["contract"] is None and r[1]["salary"] is None  # non-contract league


def test_norm_league_and_teams():
    info = {"leagueName": "N", "seasonYear": 2026, "scoringSystem": {"type": "HEAD_TO_HEAD_POINTS_BASED"},
            "teamInfo": {"t1": {"division": "Topps", "name": "Chief (T)", "id": "t1"}}}
    lg = fa.norm_league("L", info, "NBA")
    assert lg["scoring_type"] == "HEAD_TO_HEAD_POINTS_BASED" and lg["sport"] == "NBA"
    assert fa.norm_teams("L", info) == [{"league_id": "L", "team_id": "t1", "name": "Chief (T)", "division": "Topps"}]


def test_norm_standings_and_picks_and_results():
    st = fa.norm_standings("L", [{"teamName": "A", "totalPointsFor": 9161.33, "teamId": "t1",
                                  "gamesBack": 0.0, "rank": 1, "points": "18-2-0", "winPercentage": 0.9}])
    assert st[0]["record"] == "18-2-0" and st[0]["rank"] == 1
    pk = fa.norm_draft_picks("L", {"futureDraftPicks": [
        {"currentOwnerTeamId": "b", "round": 1, "year": 2027, "originalOwnerTeamId": "a"}]})
    assert pk == [{"league_id": "L", "year": 2027, "round": 1, "original_team_id": "a", "current_team_id": "b"}]
    dr = fa.norm_draft_results("L", {"draftPicks": [
        {"division": "Topps", "round": 1, "pick": 1, "teamId": "t", "time": 1769480235000, "playerId": "02yc4"}]})
    assert dr[0]["picked_at"].startswith("2026-01-27") and dr[0]["player_id"] == "02yc4"


def test_empty_responses_do_not_crash():
    assert fa.norm_rosters("L", {}) == [] and fa.norm_standings("L", None) == []
    assert fa.norm_draft_picks("L", None) == [] and fa.norm_draft_results("L", {}) == []


def test_norm_players_tags_sport():
    r = fa.norm_players({"050w9": {"name": "Henderson, Gunnar", "team": "BAL", "position": "SS"}}, "MLB")
    assert r == [{"player_id": "050w9", "sport": "MLB", "name": "Henderson, Gunnar", "team": "BAL", "position": "SS"}]


def test_leagues_config_valid():
    import json
    from pathlib import Path
    lg = json.loads((Path(fa.__file__).parent / "leagues.json").read_text())["leagues"]
    ids = [l["league_id"] for l in lg]
    assert len(ids) == len(set(ids)) and all(l["sport"] for l in lg)


def test_utf8_body_with_text_plain_content_type():
    """Regression: Fantrax sends text/plain without a charset; names with emoji must survive."""
    import requests

    class Raw(requests.Response):
        pass

    r = Raw()
    r.status_code = 200
    r.headers["Content-Type"] = "text/plain"
    r.encoding = "ISO-8859-1"  # what requests assigns to text/plain with no charset
    r._content = '{"leagueName": "H\U0001F3C0Ps \u2014 Est. 2026"}'.encode("utf-8")
    api = fa.FantraxApi("T/1", session=FakeSession([r]), sleep=lambda _: None)
    assert api.get("getLeagueInfo", leagueId="x")["leagueName"] == "H\U0001F3C0Ps \u2014 Est. 2026"
