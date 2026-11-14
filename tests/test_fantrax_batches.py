"""
Fantrax ETL: csv_to_batches.py writes batch SQL; load_supabase_actions.py reads it.

The two halves live in different files and only agree through the batch-file
format. The round-trip tests here are the contract between them.
"""
import pytest

import csv_to_batches as c2b
import load_supabase_actions as lsa


# ── sql_val: CSV cell -> SQL literal ──────────────────────────────────────────

@pytest.mark.parametrize("raw, expected", [
    ("", "NULL"),
    ("   ", "NULL"),
    ("null", "NULL"),
    ("NULL", "NULL"),
    ("42", "42"),
    ("-7", "-7"),
    ("20,878,000", "20878000"),     # Fantrax salary formatting -> bigint
    ("12.5", "12.5"),
    ("-0.5", "-0.5"),
    ("3,356.167", "3356.167"),      # Fantrax standings formatting
    ("Smith, J.", "'Smith, J.'"),   # comma inside a name stays a string
    ("Aaron Judge", "'Aaron Judge'"),
    ("O'Brien", "'O''Brien'"),      # quote doubling
    ("100%", "'100%'"),             # stays a string here; the loader converts it
])
def test_sql_val(raw, expected):
    assert c2b.sql_val(raw) == expected


@pytest.mark.parametrize("team, league", [
    ("Bombers (T)", "Topps"),
    ("Sox (R)", "Rawlings"),
    ("  Padded (T)  ", "Topps"),
    ("No Suffix", ""),
])
def test_derive_league(team, league):
    assert c2b._derive_league(team) == league


# ── loader-side parser ────────────────────────────────────────────────────────

def test_parse_row_values_handles_each_literal_type():
    got = lsa._parse_row_values("NULL, 'it''s', -3, 4.5, '0.94%', 'a, b'")
    assert got == [None, "it's", -3, 4.5, 0.94, "a, b"]


def test_old_positional_inserts_without_a_column_list_return_no_cols(tmp_path):
    f = tmp_path / "old.sql"
    f.write_text("INSERT INTO fantrax.\"T\" VALUES (1, 'a');\n", encoding="utf-8")
    cols, rows = lsa.parse_batch_file_with_cols(f)
    assert cols == []
    assert rows == [[1, "a"]]


# ── round trip: write_batch_files -> parse_batch_file_with_cols ───────────────

@pytest.fixture
def batches(tmp_path, monkeypatch):
    d = tmp_path / "batches"
    monkeypatch.setattr(c2b, "BATCHES_DIR", d)
    return d


def test_round_trip_preserves_columns_and_values(batches):
    headers = ["Player", "Team", "Salary", "Ros", "Note", "Owner", "Pts"]
    rows = [["Judge, Aaron", "NYY", "20,878,000", "100%", "", "O'Brien", "3,356.167"]]
    assert c2b.write_batch_files("T_roundtrip", headers, rows) == 1

    cols, parsed = lsa.parse_batch_file_with_cols(batches / "T_roundtrip_000.sql")
    assert cols == headers
    assert parsed == [["Judge, Aaron", "NYY", 20878000, 100.0, None, "O'Brien", 3356.167]]


def test_rows_split_into_500_row_files_in_order(batches):
    headers = ["n"]
    rows = [[str(i)] for i in range(1001)]
    assert c2b.write_batch_files("T_chunks", headers, rows) == 1001

    files = sorted(batches.glob("T_chunks_*.sql"))
    assert [f.name for f in files] == ["T_chunks_000.sql", "T_chunks_001.sql", "T_chunks_002.sql"]
    counts = [len(lsa.parse_batch_file(f)) for f in files]
    assert counts == [500, 500, 1]
    flat = [r[0] for f in files for r in lsa.parse_batch_file(f)]
    assert flat == list(range(1001))


def test_short_rows_are_padded_and_long_rows_truncated(batches):
    headers = ["a", "b", "c"]
    c2b.write_batch_files("T_pad", headers, [["1"], ["1", "2", "3", "4", "5"]])
    _, parsed = lsa.parse_batch_file_with_cols(batches / "T_pad_000.sql")
    assert parsed == [[1, None, None], [1, 2, 3]]


def test_rewriting_a_table_removes_its_stale_batch_files(batches):
    c2b.write_batch_files("T_stale", ["n"], [[str(i)] for i in range(600)])
    assert len(list(batches.glob("T_stale_*.sql"))) == 2
    c2b.write_batch_files("T_stale", ["n"], [["1"]])
    assert [f.name for f in batches.glob("T_stale_*.sql")] == ["T_stale_000.sql"]


def test_other_tables_batch_files_are_left_alone(batches):
    c2b.write_batch_files("T_keep", ["n"], [["1"]])
    c2b.write_batch_files("T_other", ["n"], [["1"]])
    assert (batches / "T_keep_000.sql").exists()
