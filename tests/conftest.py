"""
Shared fixtures for the offline test suite.

savant_extract.py and load_savant_to_supabase.py are *scripts*: they do their
work at import time (pull data, write a CSV, call sys.exit). To test them
without refactoring production code, we run them with runpy while

  * a fake `pybaseball` module is installed in sys.modules (no network), and
  * `requests.post` is replaced by a recorder (no Supabase).

Each run happens in a temp directory so CSVs never land in the repo.
"""
import runpy
import sys
import types
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent

PYBASEBALL_FUNCS = [
    "statcast_batter_percentile_ranks",
    "statcast_batter_expected_stats",
    "statcast_sprint_speed",
    "statcast_batter_exitvelo_barrels",
    "statcast_pitcher_percentile_ranks",
    "statcast_pitcher_expected_stats",
]


def make_fake_pybaseball(frames: dict) -> types.ModuleType:
    """Build a stand-in pybaseball. A value may be a DataFrame, or an
    Exception instance (that endpoint then raises, like a real outage)."""
    mod = types.ModuleType("pybaseball")
    for name in PYBASEBALL_FUNCS:
        value = frames.get(name, pd.DataFrame())

        def fn(year, _value=value):
            if isinstance(_value, Exception):
                raise _value
            return _value.copy()

        fn.__name__ = name  # the script prints fn.__name__
        setattr(mod, name, fn)
    mod.cache = types.SimpleNamespace(enable=lambda: None)
    return mod


@pytest.fixture
def savant_frames() -> dict:
    """Small but realistic 2026-shaped Savant data: 2 hitters + 1 pitcher.

    Mirrors the quirks the ETL has already been bitten by:
      * percentile endpoints use `player_name` = "Last, First"
      * the other endpoints use ONE column literally named "last_name, first_name"
      * Savant's current percentile names are `exit_velocity` / `brl_percent`
    """
    names = ["Judge, Aaron", "Soto, Juan"]
    return {
        "statcast_batter_percentile_ranks": pd.DataFrame({
            "player_name": names,
            "exit_velocity": [99, 95],      # a PERCENTILE (1-99), not mph
            "k_percent": [60, 40],
            "bb_percent": [90, 95],
            "brl_percent": [99, 90],
        }),
        "statcast_batter_expected_stats": pd.DataFrame({
            "last_name, first_name": names,
            "pa": [650, 640],
            "est_ba": [0.301, 0.290],
            "est_slg": [0.620, 0.560],
            "est_woba": [0.440, 0.420],
            "est_woba_minus_woba_diff": [0.010, -0.005],
        }),
        "statcast_sprint_speed": pd.DataFrame({
            "last_name, first_name": names,
            "sprint_speed": [27.1, 26.4],
        }),
        "statcast_batter_exitvelo_barrels": pd.DataFrame({
            "last_name, first_name": names,
            "avg_hit_speed": [95.5, 93.0],
            "ev95percent": [58.0, 52.0],
            "max_hit_speed": [118.4, 114.0],
            "brl_percent": [26.0, 17.0],
        }),
        "statcast_pitcher_percentile_ranks": pd.DataFrame({
            "player_name": ["Skenes, Paul"],
            "k_percent": [88],
            "bb_percent": [70],
            "exit_velocity": [80],
        }),
        "statcast_pitcher_expected_stats": pd.DataFrame({
            "last_name, first_name": ["Skenes, Paul"],
            "pa": [700],
            "xera": [2.31],
            "est_woba": [0.270],
            "est_ba": [0.210],
        }),
    }


@pytest.fixture
def run_extract(tmp_path, monkeypatch):
    """Run savant_extract.py offline. Returns the CSV it wrote, as a DataFrame."""
    def _run(frames: dict, year: int = 2026) -> pd.DataFrame:
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("SAVANT_YEAR", str(year))
        monkeypatch.setitem(sys.modules, "pybaseball", make_fake_pybaseball(frames))
        runpy.run_path(str(ROOT / "savant_extract.py"), run_name="savant_extract")
        return pd.read_csv(tmp_path / f"savant_metrics_{year}.csv")
    return _run


class FakeResponse:
    def __init__(self, status_code=201, text=""):
        self.status_code = status_code
        self.text = text


@pytest.fixture
def run_loader(tmp_path, monkeypatch):
    """Run load_savant_to_supabase.py with requests.post recorded, not sent.

    Returns (calls, run). `calls` collects one dict per POST (url, headers,
    data). `run(df, status=201, key="test-key", year=2026)` writes df to the
    CSV the loader expects, then executes the loader.
    """
    import requests
    import time

    calls: list[dict] = []
    state = {"status": 201}

    def fake_post(url, headers=None, data=None, timeout=None):
        calls.append({"url": url, "headers": headers, "data": data})
        return FakeResponse(state["status"], "boom" if state["status"] >= 400 else "")

    monkeypatch.setattr(requests, "post", fake_post)
    monkeypatch.setattr(time, "sleep", lambda s: None)  # skip retry back-off

    def _run(df=None, status=201, key="test-key", year=2026, write_csv=True):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("SAVANT_YEAR", str(year))
        if key is None:
            monkeypatch.delenv("SUPABASE_SERVICE_KEY", raising=False)
        else:
            monkeypatch.setenv("SUPABASE_SERVICE_KEY", key)
        state["status"] = status
        if write_csv and df is not None:
            df.to_csv(tmp_path / f"savant_metrics_{year}.csv", index=False)
        runpy.run_path(str(ROOT / "load_savant_to_supabase.py"),
                       run_name="load_savant_to_supabase")

    return calls, _run
