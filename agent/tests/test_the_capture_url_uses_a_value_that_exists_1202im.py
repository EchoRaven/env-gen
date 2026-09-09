r"""#1202im: the capture filled every route param with the literal "1".

`_concrete_capture_route` is right for an integer PK — `/title/:id` → `/title/1` loads a
real title — and wrong for every text key. `/@:username` becomes `/@1`, no user is called
"1", so the capture photographs an empty profile and the judge scores that emptiness
against a real profile reference.

tiktok-r108, live: `/@:username` is the app's profile route (the real TikTok convention)
and its users are `bts_official_bighit`, `charlidamelio`, `khaby.lame`. #1202il demotes a
screen that shared ANOTHER screen's capture and cannot help here: an empty profile page is
a distinct image, so it scores low on its own and blocks.

Measured over the corpus by anchoring each param on its route's preceding static segment:
65 routes where "1" is correct, 11 where it cannot be, 134 undecidable. r108's own case is
not in the 11 — `/@:username` has no preceding static segment — so 11 is a floor.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from env_generator.llm_generator.multi_agent.runtime import visual_fidelity as V


def _proj(tmp: Path, seed: dict) -> Path:
    d = tmp / "app" / "backend"
    d.mkdir(parents=True, exist_ok=True)
    (d / "seed_data.json").write_text(json.dumps(seed))
    return tmp


def test_a_text_key_gets_a_value_that_exists(tmp_path):
    """The r108 case: the route is the whole path, so there is no resource segment."""
    p = _proj(tmp_path, {"users": [{"id": 1, "username": "bts_official_bighit"}]})
    assert V._capture_route_1202im("/@:username", p) == "/@bts_official_bighit"


def test_an_integer_key_is_unchanged(tmp_path):
    p = _proj(tmp_path, {"videos": [{"id": 1, "caption": "x"}]})
    assert V._capture_route_1202im("/video/:id", p) == "/video/1"


def test_a_param_less_route_is_untouched(tmp_path):
    p = _proj(tmp_path, {"videos": [{"id": 1}]})
    for r in ("/", "/explore", "/messages"):
        assert V._capture_route_1202im(r, p) == r


def test_the_route_s_own_resource_wins_over_a_same_named_column_elsewhere(tmp_path):
    """`/sounds/:id` must read `sounds`, not whichever table happens to have an `id`."""
    p = _proj(tmp_path, {"videos": [{"id": 900}], "sounds": [{"id": "snd_flowers"}]})
    assert V._capture_route_1202im("/sounds/:id", p) == "/sounds/snd_flowers"


def test_it_falls_back_to_one_when_nothing_is_seeded(tmp_path):
    """Unchanged behaviour wherever this cannot improve on it."""
    p = _proj(tmp_path, {})
    assert V._capture_route_1202im("/@:username", p) == "/@1"


def test_a_missing_seed_file_falls_back(tmp_path):
    assert V._capture_route_1202im("/@:username", tmp_path) == "/@1"


def test_a_corrupt_seed_file_falls_back(tmp_path):
    d = tmp_path / "app" / "backend"
    d.mkdir(parents=True)
    (d / "seed_data.json").write_text("{broken")
    assert V._capture_route_1202im("/@:username", tmp_path) == "/@1"


def test_a_null_column_is_not_used(tmp_path):
    """An empty value would navigate to `/@` — worse than `/@1`.

    Covered on BOTH lookups. There are two: one anchored on the route's resource segment
    and one that searches by column name, each with its own guard, and a counter-proof
    that deletes only the first passes green if only the second is exercised — which is
    exactly what `/@:username` does (it has no resource segment).
    """
    # (b) the column-name search — `/@:username` reaches only this one.
    p = _proj(tmp_path, {"users": [{"id": 1, "username": None}]})
    assert V._capture_route_1202im("/@:username", p) == "/@1"


def test_a_null_column_is_not_used_on_the_anchored_lookup(tmp_path):
    """(a) the resource-anchored lookup: `/users/:username` finds the table by segment."""
    p = _proj(tmp_path, {"users": [{"username": None, "id": 7}]})
    out = V._capture_route_1202im("/users/:username", p)
    assert out == "/users/7", f"a null username must not become the URL (got {out})"


def test_only_the_first_param_is_filled_from_the_seed(tmp_path):
    """`_concrete_capture_route` still handles the rest, so a two-param route stays valid."""
    p = _proj(tmp_path, {"users": [{"id": 1, "username": "ava"}]})
    out = V._capture_route_1202im("/@:username/posts/:postId", p)
    assert out.startswith("/@ava/")


def test_it_never_raises(tmp_path):
    for route in (None, "", "/x/:y", 123):
        V._capture_route_1202im(route, tmp_path)


# --- wiring: the closure that HAS project_dir is where this runs ---------------------

def test_the_capture_closure_stamps_the_route():
    """`capture_route_screenshots` only receives `out_dir`; deriving a project root from
    that is the path assumption #1202hl caught being wrong for months. The closure in
    `run_visual_fidelity` has `project_dir` in scope — that is where this belongs."""
    import ast, inspect
    src = inspect.getsource(V.run_visual_fidelity)
    assert "_capture_route_1202im" in src
    tree = ast.parse(src.lstrip())
    fn = next((n for n in ast.walk(tree)
               if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
               and n.name == "capture"), None)
    assert fn is not None
    called = {n.func.id for n in ast.walk(fn)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert "_capture_route_1202im" in called, "the closure does not resolve the route"


def test_the_goto_sites_prefer_the_stamped_route():
    import inspect
    src = inspect.getsource(V.capture_route_screenshots)
    assert src.count('screen.get("capture_route")') == 2, (
        "both navigation sites must prefer the resolved route")


def test_r108s_profile_route_resolves_against_its_own_seed():
    root = Path(__file__).resolve().parents[2] / "generated/tiktok-web-r108"
    if not (root / "app/backend/seed_data.json").is_file():
        pytest.skip("r108 corpus not on this machine")
    out = V._capture_route_1202im("/@:username", root)
    assert out != "/@1" and out.startswith("/@")
    users = json.loads((root / "app/backend/seed_data.json").read_text())["users"]
    assert out[2:] in {str(u.get("username")) for u in users}
