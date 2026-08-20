"""#1011: the ownership map, enforced in the direction it never was.

`is_framework_owned` has one call site that matters — the write guard that stops a LANE from
touching framework files. Nothing ever asked the reverse, so the framework's own writers
overwrite lane files freely. `tools/sweep_write_conflicts.py` measured the cost across all 164
generated projects:

    file                fw     lane   alternations   runs
    LoginPage.jsx      1162    1054       2004        70
    BrowseHomePage.jsx 1185     926       1651        72
    App.jsx             947     940       1620        93   <- documented LANE-OWNED
    seed_data.json      838     749       1286       107
    custom_routes.py    507     987        795       114   <- documented LANE-OWNED

~22,000 alternating overwrites in the top 25 files. Every one of them is already covered by
the existing map (`_*_LANE_OWNED` plus `src/pages/`, `src/components/`, `src/services/`, …), so
this is an enforcement gap, not a coverage gap — and it explains the repair-task volume, the
wall-clock exhaustion, and the appearance that a strong model writes weak code.

`framework_may_write` is deliberately narrow: it blocks only when the file is lane-owned AND
already has content, so first-run scaffolding is untouched.
"""

import pytest

from env_generator.llm_generator.multi_agent.runtime.path_routed_workspace import (
    PathRoutedWorkspace)


@pytest.fixture()
def ws(tmp_path):
    for d in ("app/frontend/src/pages", "app/frontend/src/components",
              "app/frontend/src/services", "app/backend"):
        (tmp_path / d).mkdir(parents=True, exist_ok=True)
    return PathRoutedWorkspace(base_root=tmp_path, code_root=tmp_path)


@pytest.mark.parametrize("rel", [
    "app/frontend/src/App.jsx",
    "app/frontend/src/pages/LoginPage.jsx",
    "app/frontend/src/components/PosterCard.jsx",
    "app/frontend/src/services/api.js",
    "app/backend/custom_routes.py",
    "app/backend/seed_data.json",
])
def test_the_contested_files_are_recognised_as_lane_owned(ws, rel):
    """Every file the corpus sweep found contested must answer True, or the guard is
    decorative."""
    assert ws.is_lane_owned(rel) is True


@pytest.mark.parametrize("rel", [
    "app/frontend/src/main.jsx",
    "app/frontend/package.json",
    "app/backend/main.py",
    "app/backend/models.py",
])
def test_framework_files_are_not_lane_owned(ws, rel):
    assert ws.is_lane_owned(rel) is False


def test_the_framework_may_create_a_missing_lane_file(ws):
    """First-run scaffolding must still work — nothing is being clobbered."""
    assert ws.framework_may_write("app/frontend/src/pages/LoginPage.jsx") is True


def test_the_framework_may_not_overwrite_existing_lane_work(ws, tmp_path):
    p = tmp_path / "app/frontend/src/pages/LoginPage.jsx"
    p.write_text("import AuthForm from '../components/AuthForm';\n", encoding="utf-8")
    assert ws.framework_may_write(p) is False


def test_an_empty_lane_file_is_still_repairable(ws, tmp_path):
    """A lane that wrote nothing has nothing to protect."""
    p = tmp_path / "app/frontend/src/pages/LoginPage.jsx"
    p.write_text("", encoding="utf-8")
    assert ws.framework_may_write(p) is True


def test_framework_owned_files_are_always_writable(ws, tmp_path):
    p = tmp_path / "app/backend/main.py"
    p.write_text("app = FastAPI()\n", encoding="utf-8")
    assert ws.framework_may_write(p) is True


def test_the_two_predicates_do_not_overlap(ws):
    """A path cannot be owned by both sides — that ambiguity is what item 420/428 called an
    ownership vacuum, in reverse."""
    for rel in ("app/frontend/src/App.jsx", "app/backend/custom_routes.py",
                "app/backend/main.py", "app/frontend/src/main.jsx"):
        assert not (ws.is_lane_owned(rel) and ws.is_framework_owned(rel)), rel


def test_the_control_permits_the_clobber(ws, tmp_path):
    """Planted control: without the lane-ownership question, every path looks writable —
    which is how 22,000 overwrites happened."""
    p = tmp_path / "app/frontend/src/pages/LoginPage.jsx"
    p.write_text("real work\n", encoding="utf-8")
    assert ws.is_framework_owned(p) is False, (
        "the control relies on this file NOT being framework-owned; the old code asked only "
        "this question and therefore never objected")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
