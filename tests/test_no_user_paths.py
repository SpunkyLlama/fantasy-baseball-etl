"""No tracked source file may hardcode a user's home folder.

Paths come from environment variables (FANTRAX_SOURCES_DIR, FANTRAX_BATCHES_DIR)
with a default relative to where the script runs, so no account or user name ends
up in a public repository.
"""
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Built from pieces so this file does not match itself.
HOME = re.compile("(" + "C:" + r"[\\/]+Users" + "|" + "/Us" + "ers/" + ")", re.I)

SKIP_DIRS = {"tests", "batches", ".git", "__pycache__"}
SUFFIXES = {".py", ".yml", ".yaml", ".md", ".txt", ".toml", ".cfg"}


def tracked_text_files():
    # Only what git tracks: local scratch files (HANDOFF.md and the like) are not
    # in the public repository, so they are not this test's business.
    names = subprocess.run(
        ["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.splitlines()
    for name in names:
        path = ROOT / name
        if path.suffix in SUFFIXES and not SKIP_DIRS & set(Path(name).parts):
            yield path


def find_user_paths(text: str):
    return [m.group(0) for m in HOME.finditer(text)]


def test_detector_catches_a_windows_and_a_unix_home_path():
    assert find_user_paths(r"C:\Users\Someone\Documents")
    assert find_user_paths("C:/Users/Someone/Documents")
    assert find_user_paths("/Users/someone/work")
    assert not find_user_paths("batches/Fantrax_HOD_Drafts_000.sql")


def test_no_source_file_hardcodes_a_user_path():
    hits = {
        str(p.relative_to(ROOT)): find_user_paths(p.read_text(errors="ignore"))
        for p in tracked_text_files()
    }
    hits = {k: v for k, v in hits.items() if v}
    assert hits == {}, f"hardcoded user paths: {hits}"
