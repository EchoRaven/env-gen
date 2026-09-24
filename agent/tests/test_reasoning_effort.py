import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "env_generator" / "llm_generator"
for p in (str(ROOT), str(SRC)):
    if p not in sys.path:
        sys.path.insert(0, p)

from multi_agent.runtime.reasoning_effort import (  # noqa: E402
    normalize_effort,
    resolve_effort,
    read_effort_map,
    write_effort_map,
    VALID_EFFORTS,
    DEFAULT_EFFORT,
)


def test_normalize_known_and_unknown():
    assert normalize_effort("high") == "high"
    assert normalize_effort("HIGH") == "high"
    assert normalize_effort("  low ") == "low"
    assert normalize_effort("bogus") == DEFAULT_EFFORT  # fail-soft
    assert normalize_effort(None) == DEFAULT_EFFORT
    assert set(VALID_EFFORTS) == {"minimal", "low", "medium", "high"}


def test_write_then_read_roundtrip(tmp_path):
    write_effort_map(tmp_path, {"orchestrator": "high", "knowledge": "low"})
    assert read_effort_map(tmp_path) == {"orchestrator": "high", "knowledge": "low"}


def test_read_missing_file_is_empty(tmp_path):
    assert read_effort_map(tmp_path) == {}


def test_resolve_precedence(tmp_path):
    # file > profile_default > DEFAULT
    write_effort_map(tmp_path, {"design": "minimal"})
    assert resolve_effort(tmp_path, "design", "high") == "minimal"      # file wins
    assert resolve_effort(tmp_path, "backend", "medium") == "medium"    # profile default
    assert resolve_effort(tmp_path, "backend", None) == DEFAULT_EFFORT  # global default
    write_effort_map(tmp_path, {"design": "bogus"})
    assert resolve_effort(tmp_path, "design", "high") == DEFAULT_EFFORT  # file value normalized


def test_resolve_rereads_after_change(tmp_path):
    write_effort_map(tmp_path, {"backend": "low"})
    assert resolve_effort(tmp_path, "backend", "high") == "low"
    write_effort_map(tmp_path, {"backend": "high"})
    assert resolve_effort(tmp_path, "backend", "low") == "high"  # mtime re-read picks up change
