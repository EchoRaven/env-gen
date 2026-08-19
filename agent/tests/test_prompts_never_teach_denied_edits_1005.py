"""#1005: a prompt must not teach a lane to edit a file the write guard denies it.

#1004 fixed one remediation message that pointed the backend lane at `app/backend/main.py` —
a file in `_BACKEND_FRAMEWORK_OWNED`, which `is_framework_owned()` uses to deny every lane
write. Sweeping the prompts for the same class found something worse: the backend lane's own
worked example.

    "scenario": "Verifier reports issue on PR #42: 'list_posts: no tenant scoping…'"
    "actions": [
        "edit(file_path='app/backend/main.py', old_string='db.query(Post).all()', …)",
        "edit(file_path='app/backend/main.py', old_string='db.query(User).delete()', …)",
    ]

That is the canonical "here is how you do your job" demonstration, and it demonstrates an
edit that is structurally impossible. The framework's own projector says where the work
belongs — "the lane implements the real handler in custom_routes.py" (route_projector:1698) —
so the projected handler in main.py is a reachability stub, not the place to fix logic.

Swept **every** template, not just the active version: v3 is what agents_config selects today,
but v4 carried the identical example and would have resurrected the defect on cutover. That is
the #1000 → #1003 mistake — fixing a sibling and believing the class was closed — repeating
one turn later, which is why this test ignores versions entirely.
"""

import pathlib
import re

import pytest

from env_generator.llm_generator.multi_agent.agents.runtime.auto_commit import (
    _BACKEND_FRAMEWORK_OWNED, _FRONTEND_FRAMEWORK_OWNED)

_PROMPTS = (pathlib.Path("env_generator/llm_generator/multi_agent/prompts"))
_MUTATORS = re.compile(r"(?:edit|write|apply_patch)\(file_path='([^']+)'")


def _templates():
    return sorted(_PROMPTS.rglob("*.j2"))


def test_the_sweep_has_a_denominator():
    """An empty glob reports every prompt as clean — items 366/381/391/398/414."""
    assert len(_templates()) >= 10


def test_no_prompt_demonstrates_an_edit_the_guard_denies():
    offenders = []
    for tpl in _templates():
        for m in _MUTATORS.finditer(tpl.read_text(encoding="utf-8", errors="replace")):
            path = m.group(1)
            name = path.rsplit("/", 1)[-1]
            if path.startswith("app/backend/") and name in _BACKEND_FRAMEWORK_OWNED:
                offenders.append((tpl.name, path))
            elif path.startswith("app/frontend/") and name in _FRONTEND_FRAMEWORK_OWNED:
                offenders.append((tpl.name, path))
    assert offenders == [], f"a prompt teaches an impossible edit: {sorted(set(offenders))}"


def test_every_version_is_covered_not_just_the_active_one():
    """v4 carried the identical example while v3 was live. A version-scoped test would have
    passed and the defect would have returned on cutover."""
    names = {t.parent.name for t in _templates()}
    assert len(names) >= 2, f"expected multiple prompt versions on disk, saw {names}"


def test_the_backend_example_names_the_lane_owned_file():
    hits = [t for t in _templates() if t.name == "backend_agent.j2"]
    assert hits, "backend_agent.j2 not found"
    for t in hits:
        body = t.read_text(encoding="utf-8", errors="replace")
        if "db.query(Post).all()" in body:
            assert "custom_routes.py" in body


def test_the_premise_still_holds():
    assert "main.py" in _BACKEND_FRAMEWORK_OWNED
    assert "custom_routes.py" not in _BACKEND_FRAMEWORK_OWNED


def test_the_control_is_an_impossible_edit():
    """Planted control: the PRE-FIX example line."""
    pre_fix = "edit(file_path='app/backend/main.py', old_string='db.query(Post).all()')"
    m = _MUTATORS.search(pre_fix)
    assert m and m.group(1).rsplit("/", 1)[-1] in _BACKEND_FRAMEWORK_OWNED, (
        "the control was supposed to name a denied file; if it does not, this fix is "
        "unmotivated")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
