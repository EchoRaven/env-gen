"""Design-Prep Task 7 — use-real-assets advisory audit.

audit_asset_usage(frontend_dir, design_system) flags each component the design_system maps to a
real asset that NO frontend file actually references (by file basename). Advisory only — it feeds
remediation text, never a hard delivery block. LOCAL-ONLY (agent/tests/ gitignored).
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime.frontend_audit import audit_asset_usage  # noqa: E402


def _ds():
    return {
        "assets": [{"id": "logo", "file": "ig.svg", "staged_path": "public/assets/ig.svg"},
                   {"id": "heart", "file": "icons/heart.png"}],
        "screens": [{"name": "home", "components": [
            {"id": "top-nav", "assets": ["logo"]},
            {"id": "post-actions", "assets": ["heart"]},
        ]}],
    }


def _mk_frontend(tmp_path, files):
    fe = tmp_path / "app" / "frontend"
    (fe / "src").mkdir(parents=True)
    for rel, content in files.items():
        p = fe / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
    return fe


def test_flags_mapped_asset_not_referenced(tmp_path):
    # TopNav uses the logo; nobody references heart.png → only 'heart' is flagged
    fe = _mk_frontend(tmp_path, {
        "src/components/TopNav.jsx": "export default () => <img src='/assets/ig.svg'/>;",
        "src/components/PostActions.jsx": "export default () => <button>like</button>;",
    })
    out = audit_asset_usage(fe, _ds())
    flagged = {(u["component"], u["asset"]) for u in out["unused_mapped"]}
    assert flagged == {("post-actions", "heart")}
    entry = out["unused_mapped"][0]
    assert entry["file"] == "icons/heart.png"


def test_no_flags_when_all_referenced(tmp_path):
    fe = _mk_frontend(tmp_path, {
        "src/components/TopNav.jsx": "import logo from '/assets/ig.svg';",
        "src/components/PostActions.jsx": "const h='/assets/icons/heart.png';",
    })
    out = audit_asset_usage(fe, _ds())
    assert out["unused_mapped"] == []


def test_empty_or_missing_is_safe(tmp_path):
    assert audit_asset_usage(tmp_path / "nope", _ds())["unused_mapped"] == []
    fe = _mk_frontend(tmp_path, {"src/App.jsx": "x"})
    assert audit_asset_usage(fe, {})["unused_mapped"] == []       # no design_system → nothing to flag


def test_advisory_appears_in_visual_remediation(tmp_path):
    """The advisory is wired into the visual-fidelity remediation text when a mapped asset is
    unused, and is ABSENT when there is no design_system."""
    import json
    from multi_agent.runtime.visual_fidelity import remediation_text

    out = tmp_path / "out"
    (out / "design").mkdir(parents=True)
    (out / "design" / "design_system.json").write_text(json.dumps(_ds()))
    _mk_frontend(out, {"src/App.jsx": "export default () => <div/>;"})  # references neither asset

    result = {"screens": [{"name": "home", "route": "/", "similarity": 0.4, "passed": False,
                           "dimensions": {}, "deviations": []}]}
    text = remediation_text(result, str(out))
    # A1: a FAILING screen's mapped assets are mandated FIRST inside its own
    # section (and not repeated in the tail advisory) — the audit output still
    # reaches the remediation text, now screen-scoped.
    assert "USE THE REAL STAGED ASSETS FIRST" in text
    assert "/assets/ig.svg" in text

    # no design_system → no asset guidance at all
    text2 = remediation_text(result, str(tmp_path / "empty"))
    assert "Real assets not used" not in text2
    assert "USE THE REAL STAGED ASSETS FIRST" not in text2


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
