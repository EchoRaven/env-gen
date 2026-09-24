"""Visual-remediation tasks embed the MEASURED component spec (2026-07-02).

The framework pre-computes design/component_specs/<screen>.json (named components with
measured background/accent hex) but runs 30-38 show the lane reads it ~once per run and
fixes visual tasks by eyeball — advisory mismatches persisted across every run. The
remediation task text now embeds the spec's exact values for each failing screen, so the
fixing lane holds the numbers at the moment it acts. LOCAL-ONLY (agent/tests/ gitignored).
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime.visual_fidelity import remediation_text, _spec_snippet  # noqa: E402

_RESULT = {"screens": [
    {"name": "outlook_inbox", "route": "/inbox", "similarity": 0.55, "passed": False,
     "dimensions": {}, "deviations": [], "fixes": []},
    {"name": "outlook_login", "route": "/login", "similarity": 0.95, "passed": True},
]}


def _specs(tmp_path):
    d = tmp_path / "design" / "component_specs"
    d.mkdir(parents=True)
    (d / "outlook_inbox.json").write_text(json.dumps({
        "reference": "outlook_inbox.png",
        "components": [
            {"name": "top_bar", "region": [0, 0, 1, .05], "background": "#292929",
             "accents": {}, "state": "search empty"},
            {"name": "nav_rail", "background": "#09101a",
             "accents": {"blue": "#2d4edf", "red": "#c53039"}},
        ]}), encoding="utf-8")
    return tmp_path


def test_snippet_contains_measured_hexes(tmp_path):
    s = _spec_snippet(_specs(tmp_path), "outlook_inbox")
    assert "#292929" in s and "#09101a" in s and "blue=#2d4edf" in s
    assert "EXACT hex" in s


def test_remediation_embeds_spec_for_failing_screen(tmp_path):
    txt = remediation_text(_RESULT, _specs(tmp_path))
    assert "#292929" in txt and "outlook_inbox" in txt
    assert txt.index("## outlook_inbox") < txt.index("#292929")


def test_no_output_dir_keeps_old_behaviour():
    txt = remediation_text(_RESULT)
    assert "outlook_inbox" in txt and "#292929" not in txt


def test_missing_spec_file_is_silent(tmp_path):
    assert _spec_snippet(tmp_path, "nope") == ""
    txt = remediation_text(_RESULT, tmp_path)
    assert "MEASURED SPEC" not in txt
