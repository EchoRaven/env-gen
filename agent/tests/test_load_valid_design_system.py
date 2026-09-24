"""load_valid_design_system detects a malformed/garbage agent-written design_system.json so the
orchestrator can fall back to the single-shot rebuild instead of losing the phase. LOCAL-ONLY.
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime.design_prep import load_valid_design_system  # noqa: E402


def test_valid_doc_loads(tmp_path):
    p = tmp_path / "ds.json"
    p.write_text(json.dumps({"design_system": {"palette": {"bg": "#000"}}, "screens": []}))
    d = load_valid_design_system(p)
    assert d and d["design_system"]["palette"]["bg"] == "#000"


def test_screens_only_is_valid(tmp_path):
    p = tmp_path / "ds.json"
    p.write_text(json.dumps({"screens": [{"name": "home"}]}))
    assert load_valid_design_system(p) is not None


def test_malformed_json_is_none(tmp_path):
    p = tmp_path / "ds.json"
    p.write_text('{"design_system": {"palette": {  <<garbage not json')
    assert load_valid_design_system(p) is None


def test_non_design_shape_is_none(tmp_path):
    p = tmp_path / "ds.json"
    p.write_text(json.dumps({"hello": "world"}))     # parses but not a design doc
    assert load_valid_design_system(p) is None
    p.write_text(json.dumps(["a", "list"]))          # not even a dict
    assert load_valid_design_system(p) is None


def test_missing_file_is_none(tmp_path):
    assert load_valid_design_system(tmp_path / "nope.json") is None


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
