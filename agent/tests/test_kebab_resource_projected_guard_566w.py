r"""#566w (netflix r130): _custom_route_overrides_projected compared a URL path SEGMENT against
_NESTED_CHILD_RESOURCES / _OWNER_SCOPED_RESOURCES, but those sets are built from TABLE names.
Table names are snake_case (my_list, continue_watching) while the REST path for the same resource
is kebab-case (/api/my-list, /api/continue-watching), so EVERY multi-word resource missed the
#77/#528 "projected read wins" guard and a buggy lane GET shadowed the safe projected read.

Live impact (r130): GET /api/my-list was lane-served and oscillated across remediation cycles --
403 on the caller's OWN row (23x) and 200 on a CROSS-USER row (3x) -- wedging the run at 0 tags.
Single-word resources (profiles) were unaffected, which is why the bug hid for so long.

Fix: _fw_resource_seg() normalizes a path segment into the table-name namespace ('-' -> '_')
and is applied at every membership site.
"""
import os
import py_compile
import re
import tempfile

from env_generator.llm_generator.multi_agent.runtime.backend_skeleton import render_skeleton_main

_TABLES = {
    "users": {"columns": [{"name": "id", "type": "Integer", "primary_key": True}]},
    "profiles": {"columns": [{"name": "id", "type": "Integer", "primary_key": True},
                             {"name": "user_id", "type": "Integer", "foreign_key": "users.id"}]},
    "my_list": {"columns": [{"name": "id", "type": "Integer", "primary_key": True},
                            {"name": "profile_id", "type": "Integer", "foreign_key": "profiles.id"},
                            {"name": "title_id", "type": "Integer", "foreign_key": "titles.id"}]},
    "continue_watching": {"columns": [{"name": "id", "type": "Integer", "primary_key": True},
                                      {"name": "profile_id", "type": "Integer",
                                       "foreign_key": "profiles.id"}]},
    "titles": {"columns": [{"name": "id", "type": "Integer", "primary_key": True}]},
}

_ENDPOINTS = [
    {"method": "GET", "path": "/api/my-list", "auth_required": True},
    {"method": "GET", "path": "/api/continue-watching", "auth_required": True},
    {"method": "GET", "path": "/api/titles", "auth_required": False},
]


def _render():
    return render_skeleton_main(_ENDPOINTS, _TABLES)


def _load_policy(src):
    """exec ONLY the resource sets + the two policy functions out of the rendered main.py."""
    ns = {}
    for pat in (r"^_NESTED_CHILD_RESOURCES = set\(.*?\)$",
                r"^_OWNER_SCOPED_RESOURCES = set\(.*?\)$",
                r"^_DEGENERATE_RESOURCES = set\(.*?\)$"):  # #568
        m = re.search(pat, src, re.M | re.S)
        assert m, pat
        exec(m.group(0), ns)
    m = re.search(r"^def _custom_route_overrides_projected\(.*?(?=\n\S)", src, re.M | re.S)
    assert m, "missing _custom_route_overrides_projected in rendered main.py"
    exec(m.group(0), ns)
    return ns


def test_normalizer_is_nested_for_standalone_exec():
    """#528's harness slices this def out of the template and execs it ALONE, so the
    normalizer must live INSIDE the function (a module-level helper NameErrors there)."""
    src = _render()
    fn = re.search(r"^def _custom_route_overrides_projected\(.*?(?=\n\S)", src, re.M | re.S).group(0)
    assert "def _fw_resource_seg(" in fn, "normalizer must be nested inside the policy fn"
    ns = {"_NESTED_CHILD_RESOURCES": {"my_list"}, "_OWNER_SCOPED_RESOURCES": set(),
          "_DEGENERATE_RESOURCES": set()}  # #568: schema-complete world, guard inert
    exec(fn, ns)  # must not NameError
    assert ns["_custom_route_overrides_projected"]("GET", "/api/my-list") is False


def test_kebab_collection_get_keeps_projected_handler():
    """THE REGRESSION: /api/my-list must NOT be overridable by a lane GET."""
    ns = _load_policy(_render())
    ovr = ns["_custom_route_overrides_projected"]
    assert ovr("GET", "/api/my-list") is False
    assert ovr("GET", "/api/continue-watching") is False
    # snake_case table name is in the set, so the single-word case must still hold
    assert ovr("GET", "/api/titles") is False


def test_kebab_item_get_keeps_projected_handler():
    ns = _load_policy(_render())
    ovr = ns["_custom_route_overrides_projected"]
    assert ovr("GET", "/api/my-list/{id}") is False
    assert ovr("GET", "/api/continue-watching/{id}") is False


def test_lane_still_wins_for_actions_and_writes():
    """The fix must NOT widen the guard: non-CRUD shapes stay lane-overridable."""
    ns = _load_policy(_render())
    ovr = ns["_custom_route_overrides_projected"]
    assert ovr("GET", "/api/search") is True             # unregistered collection -> lane wins
    assert ovr("GET", "/api/my-list/{id}/like") is True  # action verb -> lane wins
    assert ovr("GET", "/api/auth/me") is True            # /me under auth stays custom
    assert ovr("GET", "/api/some-unregistered") is True  # kebab but NOT a table -> lane wins


def test_write_shapes_are_unchanged_by_normalization():
    """POST/PUT/DELETE on a registered collection already kept the projected handler
    (the branch is _is_get-gated, so #566w cannot have moved it). Pin that."""
    ns = _load_policy(_render())
    ovr = ns["_custom_route_overrides_projected"]
    # registered resource, kebab and single-word alike -> unchanged pre-existing behavior
    assert ovr("POST", "/api/my-list") is False
    assert ovr("POST", "/api/titles") is False
    # unregistered path is still lane-owned for writes
    assert ovr("POST", "/api/search") is False


def test_rendered_main_defines_helper_and_compiles():
    """Mandatory render+compile: _MAIN_HEADER/_CUSTOM_ROUTES_INCLUDE are template STRINGS, so a
    typo here is a SyntaxError in every generated app, not in this repo."""
    src = _render()
    assert "def _fw_resource_seg(" in src
    assert "_fw_resource_seg(segs[0]) in _NESTED_CHILD_RESOURCES" in src
    p = os.path.join(tempfile.mkdtemp(), "main.py")
    with open(p, "w") as f:
        f.write(src)
    py_compile.compile(p, doraise=True)


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
