"""
Savant ETL: savant_extract.py -> CSV -> load_savant_to_supabase.py -> POST payload.

These pin bugs the pipeline has already had (column renames, the combined
"last_name, first_name" column, pitcher columns silently dropped, duplicate
traded players, NaN breaking the upload) so they can't quietly come back.
"""
import json

import pandas as pd
import pytest

# The 18 columns savant_extract.py writes for the fixture data.
EXTRACT_COLUMNS = {
    "player_name", "player_type", "season",
    "savant_exit_velocity", "savant_k_percent", "savant_bb_percent",
    "savant_barrel_pct_rank",
    "savant_pa", "savant_est_ba", "savant_est_slg", "savant_est_woba",
    "savant_est_woba_minus_woba_diff",
    "savant_sprint_speed",
    "savant_avg_hit_speed", "savant_ev95percent", "savant_max_hit_speed",
    "savant_brl_percent",
    "savant_xera",
}

# The 16 columns the loader sends to public.savant_metrics (COL_MAP values).
DB_COLUMNS = {
    "player_name", "player_type",
    "savant_ev_pct", "savant_k_pct", "savant_bb_pct",
    "savant_pa", "savant_xba", "savant_xslg", "savant_xwoba", "savant_xwoba_diff",
    "savant_sprint_speed", "savant_avg_ev", "savant_ev95_pct", "savant_max_ev",
    "savant_brl_pct", "savant_xera",
}


def row(df, name, ptype):
    hit = df[(df.player_name == name) & (df.player_type == ptype)]
    assert len(hit) == 1, f"expected exactly one {ptype} row for {name}, got {len(hit)}"
    return hit.iloc[0]


# ── savant_extract.py ─────────────────────────────────────────────────────────

def test_names_flip_to_first_last_and_sources_merge_on_one_row(run_extract, savant_frames):
    df = run_extract(savant_frames)
    judge = row(df, "Aaron Judge", "H")
    # A value from each of the four batter sources landed on the SAME row,
    # which only happens if every source's name format was normalised.
    assert judge.savant_exit_velocity == 99      # percentile ranks
    assert judge.savant_est_woba == pytest.approx(0.440)   # expected stats
    assert judge.savant_sprint_speed == pytest.approx(27.1)  # sprint speed
    assert judge.savant_avg_hit_speed == pytest.approx(95.5)  # exit velo/barrels
    assert not any("," in n for n in df.player_name)


def test_extract_writes_exactly_the_expected_columns(run_extract, savant_frames):
    df = run_extract(savant_frames)
    assert set(df.columns) == EXTRACT_COLUMNS


def test_current_savant_percentile_names_are_mapped(run_extract, savant_frames):
    # Savant now says `exit_velocity` / `brl_percent` on the percentile endpoint.
    # If these aliases regress, the EV percentile silently vanishes.
    judge = row(run_extract(savant_frames), "Aaron Judge", "H")
    assert judge.savant_exit_velocity == 99
    assert judge.savant_barrel_pct_rank == 99


def test_ev_percentile_is_a_percentile_not_mph(run_extract, savant_frames):
    df = run_extract(savant_frames)
    # mph values sit around 90+; a percentile column must be able to reach low values
    # and must never exceed 100.
    assert df.savant_exit_velocity.dropna().between(1, 100).all()


def test_pitchers_use_shared_column_names_so_they_reach_the_loader(run_extract, savant_frames):
    # Past bug: pitcher columns had unique names the loader's COL_MAP didn't know,
    # so pitcher data was silently dropped.
    skenes = row(run_extract(savant_frames), "Paul Skenes", "P")
    assert skenes.savant_xera == pytest.approx(2.31)
    assert skenes.savant_exit_velocity == 80
    assert skenes.savant_k_percent == 88


def test_traded_player_duplicates_collapse_keeping_last(run_extract, savant_frames):
    f = savant_frames["statcast_batter_expected_stats"]
    dupe = f.iloc[[0]].copy()
    dupe["pa"] = 999  # the "fuller" later line
    savant_frames["statcast_batter_expected_stats"] = pd.concat([f, dupe], ignore_index=True)
    df = run_extract(savant_frames)
    judge = df[(df.player_name == "Aaron Judge") & (df.player_type == "H")]
    assert len(judge) == 1
    assert judge.iloc[0].savant_pa == 999  # the LAST occurrence won, not the first
    assert df.duplicated(["player_name", "player_type"]).sum() == 0


def test_one_failed_source_does_not_abort_the_run(run_extract, savant_frames):
    savant_frames["statcast_batter_exitvelo_barrels"] = RuntimeError("Savant 503")
    df = run_extract(savant_frames)
    judge = row(df, "Aaron Judge", "H")
    assert judge.savant_exit_velocity == 99          # other sources still present
    assert "savant_avg_hit_speed" not in df.columns  # the failed source is simply absent


def test_legacy_first_name_last_name_columns_still_work(run_extract, savant_frames):
    savant_frames["statcast_sprint_speed"] = pd.DataFrame({
        "last_name": ["Judge", "Soto"],
        "first_name": ["Aaron", "Juan"],
        "sprint_speed": [27.1, 26.4],
    })
    judge = row(run_extract(savant_frames), "Aaron Judge", "H")
    assert judge.savant_sprint_speed == pytest.approx(27.1)


def test_rows_without_a_player_name_are_dropped(run_extract, savant_frames):
    f = savant_frames["statcast_batter_percentile_ranks"]
    blank = pd.DataFrame({"player_name": [None, "  "], "exit_velocity": [1, 2],
                          "k_percent": [1, 2], "bb_percent": [1, 2], "brl_percent": [1, 2]})
    savant_frames["statcast_batter_percentile_ranks"] = pd.concat([f, blank], ignore_index=True)
    df = run_extract(savant_frames)
    assert df.player_name.notna().all()
    assert (df.player_name.str.strip() != "").all()


def test_off_season_with_no_data_does_not_crash(run_extract):
    # savant_etl.yml runs daily all year; the script is supposed to exit cleanly
    # when Savant has nothing yet.
    df = run_extract({})
    assert len(df) == 0


# ── load_savant_to_supabase.py ────────────────────────────────────────────────

def test_end_to_end_payload_has_exactly_the_db_columns(run_extract, run_loader, savant_frames):
    csv_df = run_extract(savant_frames)
    calls, run = run_loader
    run(csv_df)
    rows = [r for c in calls for r in json.loads(c["data"])]
    assert len(rows) == 3  # 2 hitters + 1 pitcher
    for r in rows:
        assert set(r) == DB_COLUMNS


def test_end_to_end_values_land_in_the_right_db_columns(run_extract, run_loader, savant_frames):
    csv_df = run_extract(savant_frames)
    calls, run = run_loader
    run(csv_df)
    rows = {(r["player_name"], r["player_type"]): r
            for c in calls for r in json.loads(c["data"])}
    assert rows[("Aaron Judge", "H")]["savant_ev_pct"] == 99
    assert rows[("Aaron Judge", "H")]["savant_xwoba"] == pytest.approx(0.440)
    assert rows[("Paul Skenes", "P")]["savant_xera"] == pytest.approx(2.31)
    assert rows[("Paul Skenes", "P")]["savant_ev_pct"] == 80


def test_nan_becomes_json_null_not_bare_nan(run_extract, run_loader, savant_frames):
    csv_df = run_extract(savant_frames)  # hitters have no xERA -> NaN in the CSV
    calls, run = run_loader
    run(csv_df)

    def reject(const):
        raise AssertionError(f"payload contains bare {const}; Supabase rejects it (PGRST102)")

    rows = [r for c in calls for r in json.loads(c["data"], parse_constant=reject)]
    judge = next(r for r in rows if r["player_name"] == "Aaron Judge")
    assert judge["savant_xera"] is None


def test_upload_is_chunked_by_50_and_uses_upsert_headers(run_loader):
    df = pd.DataFrame({"player_name": [f"Player {i}" for i in range(120)],
                       "player_type": "H", "savant_pa": 100})
    calls, run = run_loader
    run(df)
    sizes = [len(json.loads(c["data"])) for c in calls]
    assert sizes == [50, 50, 20]
    h = calls[0]["headers"]
    assert h["Prefer"] == "resolution=merge-duplicates"
    assert h["apikey"] == "test-key"
    assert h["Authorization"] == "Bearer test-key"
    assert calls[0]["url"].endswith("/rest/v1/savant_metrics")


def test_loader_dedupes_before_upload(run_loader):
    df = pd.DataFrame({"player_name": ["A B", "A B", "C D"], "player_type": ["H", "H", "H"],
                       "savant_pa": [1, 2, 3]})
    calls, run = run_loader
    run(df)
    rows = [r for c in calls for r in json.loads(c["data"])]
    assert len(rows) == 2
    assert next(r for r in rows if r["player_name"] == "A B")["savant_pa"] == 2  # keep last


def test_http_failure_retries_three_times_then_exits_nonzero(run_loader):
    df = pd.DataFrame({"player_name": ["A B"], "player_type": ["H"], "savant_pa": [1]})
    calls, run = run_loader
    with pytest.raises(SystemExit) as exc:
        run(df, status=500)
    assert "failed rows" in str(exc.value)
    assert len(calls) == 3


def test_missing_service_key_exits_before_any_request(run_loader):
    calls, run = run_loader
    with pytest.raises(SystemExit) as exc:
        run(pd.DataFrame({"player_name": ["A B"], "player_type": ["H"]}), key=None)
    assert "SUPABASE_SERVICE_KEY" in str(exc.value)
    assert calls == []


def test_missing_csv_exits_with_a_clear_message(run_loader):
    calls, run = run_loader
    with pytest.raises(SystemExit) as exc:
        run(write_csv=False)
    assert "not found" in str(exc.value)
    assert calls == []
