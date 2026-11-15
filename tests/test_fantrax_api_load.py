"""Offline tests for fantrax_api_load.py: no network, no database."""
import json

import pytest

import fantrax_api_load as ld


def good_tables(lid="L1"):
    return {
        "leagues": [{"league_id": lid, "sport": "MLB", "name": "N", "season": 2026,
                     "scoring_type": "X", "scoring": {"a": 1}, "roster_rules": {"b": 2},
                     "start_date": None, "end_date": None}],
        "teams": [{"league_id": lid, "team_id": "t1", "name": "A", "division": "D"},
                  {"league_id": lid, "team_id": "t2", "name": "B", "division": "D"}],
        "rosters": [{"league_id": lid, "team_id": "t1", "player_id": "p1", "period": 1,
                     "position": "OF", "status": "ACTIVE", "contract": "1st", "salary": 2.0}],
        "standings": [{"league_id": lid, "team_id": "t1", "rank": 1, "record": "1-0-0",
                       "win_pct": 1.0, "games_back": 0.0, "total_points_for": 5.0}],
        "draft_picks": [], "draft_results": [],
    }


# ── validation ────────────────────────────────────────────────────────────────

def test_good_tables_validate_even_with_no_draft_yet():
    assert ld.validate_league("L1", good_tables()) == []


@pytest.mark.parametrize("name", ["teams", "rosters", "standings"])
def test_empty_core_table_is_refused(name):
    t = good_tables()
    t[name] = []
    assert any(f"{name} is empty" in e for e in ld.validate_league("L1", t))


def test_duplicate_primary_key_is_refused():
    t = good_tables()
    t["rosters"] = t["rosters"] * 2
    assert any("duplicate primary keys" in e for e in ld.validate_league("L1", t))


def test_null_key_and_orphan_team_are_refused():
    t = good_tables()
    t["rosters"][0]["player_id"] = None
    assert any("null key" in e for e in ld.validate_league("L1", t))
    t = good_tables()
    t["standings"][0]["team_id"] = "ghost"
    assert any("not in teams" in e for e in ld.validate_league("L1", t))


# ── SQL shape and per-league scoping ──────────────────────────────────────────

class FakeCur:
    def __init__(self, present=True, fail_on=None):
        self.executed, self.present, self.fail_on = [], present, fail_on

    def execute(self, sql, params=None):
        if self.fail_on and self.fail_on in sql:
            raise RuntimeError("boom")
        self.executed.append((sql, params))

    def fetchone(self):
        return ("fantrax_api.leagues" if self.present else None,)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


@pytest.fixture
def recorded(monkeypatch):
    calls = []
    monkeypatch.setattr(ld, "_batch", lambda cur, sql, rows: calls.append((sql, rows)))
    return calls


def test_load_league_upserts_league_then_deletes_only_that_league_then_inserts(recorded):
    cur = FakeCur()
    counts = ld.load_league(cur, "L1", good_tables())
    assert counts["rosters"] == 1 and counts["teams"] == 2
    assert "ON CONFLICT (league_id) DO UPDATE" in recorded[0][0] and "fetched_at = now()" in recorded[0][0]
    deletes = [(s, p) for s, p in cur.executed]
    assert [p for _s, p in deletes] == [("L1",)] * 5
    assert all(s.startswith("DELETE FROM fantrax_api.") and "WHERE league_id = %s" in s for s, _p in deletes)
    assert not any("TRUNCATE" in s.upper() for s, _p in deletes)
    inserted = [s.split()[2] for s, _r in recorded[1:]]
    assert inserted == ["fantrax_api.teams", "fantrax_api.rosters", "fantrax_api.standings"]  # empty drafts skipped


def test_json_columns_are_wrapped_not_stringified():
    from psycopg2.extras import Json
    vals = ld._values("leagues", good_tables()["leagues"][0])
    assert isinstance(vals[5], Json) and isinstance(vals[6], Json)
    assert ld._values("leagues", {"league_id": "x"})[5] is None  # missing json stays NULL


def test_players_upsert_sql_has_no_fetched_at():
    assert "fetched_at" not in ld._insert_sql("players", upsert=True)
    assert "ON CONFLICT (sport, player_id)" in ld._insert_sql("players", upsert=True)


# ── main(): dry run vs load ───────────────────────────────────────────────────

CONFIG = {"leagues": [{"league_id": "L1", "key": "a", "sport": "MLB"},
                      {"league_id": "L2", "key": "b", "sport": "NBA"}]}


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    p = tmp_path / "leagues.json"
    p.write_text(json.dumps(CONFIG))
    monkeypatch.setenv("FANTRAX_USER_AGENT", "T/1")
    monkeypatch.setattr(ld.fa, "FantraxApi", lambda *a, **k: object())
    return str(p)


def patch_fetch(monkeypatch, bad=()):
    def fake(api, lid, sport=None):
        t = good_tables(lid)
        if lid in bad:
            t["rosters"] = []
        return t
    monkeypatch.setattr(ld.fa, "fetch_league", fake)


def test_dry_run_never_connects_and_writes_nothing(cfg, monkeypatch, capsys):
    patch_fetch(monkeypatch)
    monkeypatch.setattr(ld, "connect", lambda: pytest.fail("dry run must not connect"))
    assert ld.main(["--config", cfg]) == 0
    assert "DRY RUN" in capsys.readouterr().out


def test_dry_run_flags_invalid_league_with_nonzero_exit(cfg, monkeypatch):
    patch_fetch(monkeypatch, bad={"L2"})
    monkeypatch.setattr(ld, "connect", lambda: pytest.fail("no connect"))
    assert ld.main(["--config", cfg]) == 1


class FakeConn:
    def __init__(self, cur):
        self.cur, self.commits, self.rollbacks, self.closed = cur, 0, 0, False

    def cursor(self):
        return self.cur

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        self.closed = True


def test_load_stops_with_code_2_when_schema_missing(cfg, monkeypatch, recorded):
    patch_fetch(monkeypatch)
    conn = FakeConn(FakeCur(present=False))
    monkeypatch.setattr(ld, "connect", lambda: conn)
    assert ld.main(["--config", cfg, "--load"]) == 2
    assert recorded == [] and conn.commits == 0 and conn.closed


def test_load_skips_invalid_league_but_loads_the_good_one(cfg, monkeypatch, recorded):
    patch_fetch(monkeypatch, bad={"L2"})
    conn = FakeConn(FakeCur())
    monkeypatch.setattr(ld, "connect", lambda: conn)
    assert ld.main(["--config", cfg, "--load"]) == 1
    deleted = {p for s, p in conn.cur.executed if s.startswith("DELETE")}
    assert deleted == {("L1",)} and conn.commits == 1  # L2 untouched


def test_failure_rolls_back_that_league_and_continues(cfg, monkeypatch, recorded):
    patch_fetch(monkeypatch)
    cur = FakeCur()
    real = ld.load_league
    def flaky(c, lid, t):
        if lid == "L1":
            raise RuntimeError("boom")
        return real(c, lid, t)
    monkeypatch.setattr(ld, "load_league", flaky)
    conn = FakeConn(cur)
    monkeypatch.setattr(ld, "connect", lambda: conn)
    assert ld.main(["--config", cfg, "--load"]) == 1
    assert conn.rollbacks == 1 and conn.commits == 1 and conn.closed


def test_load_requires_password(monkeypatch):
    monkeypatch.delenv("SUPABASE_PASSWORD", raising=False)
    with pytest.raises(RuntimeError, match="SUPABASE_PASSWORD"):
        ld.connect()
