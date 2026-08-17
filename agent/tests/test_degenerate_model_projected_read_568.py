r"""#568 (netflix r133, live cross-user leak): #528/#566w hand every standard-CRUD read on a
REGISTERED resource to the projected handler, on the stated premise that the projected read is
"schema-safe and 200/404 by construction". That premise fails when the projected MODEL is
DEGENERATE — only its primary key survived — because there is then no column to serialize and,
crucially, no owner FK to filter on.

r133 ground truth (registryhub_tables.json): `my_list` was registered with `schema.columns == []`
while its siblings `ratings` and `continue_watching` registered in full. The model came out as

    class MyList(Base):
        __tablename__ = "my_list"
        id = Column(Integer, primary_key=True)

so the projection emitted

    @app.get("/api/my-list")
    def _projected_get_api_my_list_9(db=..., user=...):
        rows = db.query(MyList).limit(100).all()          # nothing to scope BY
        return {"items": [{"id": getattr(r, "id", None)} for r in rows], "total": len(rows)}

and user B's GET /api/my-list returned user A's row -- while the lane's OWN handler
(`filter(MyList.profile_id == prof.id)`) sat shadowed and never ran. #566y could not help: it
needs an owner FK to exist in the model. The run did not self-heal over ~25 min, because the
symptom the lane is shown ("GET -> 200, expected 403") points at authorization, not at a model
that lost its columns.

Fix: `_DEGENERATE_RESOURCES` — the lane keeps the route for GET on a resource whose projected
model is PK-only. Keyed off the PARSED MODEL, so any cause of a degenerate model is covered.
"""
import py_compile
import re
import tempfile

from env_generator.llm_generator.multi_agent.runtime.backend_skeleton import render_skeleton_main

# `my_list` mirrors r133: registered, but with NO columns. Its siblings are complete.
_TABLES = {
    "users": {"columns": [{"name": "id", "type": "serial", "primary_key": True},
                          {"name": "email", "type": "text"}]},
    "profiles": {"columns": [{"name": "id", "type": "serial", "primary_key": True},
                             {"name": "user_id", "type": "int", "references": "users.id"}]},
    "my_list": {"columns": []},                                    # <- the r133 defect
    "continue_watching": {"columns": [
        {"name": "id", "type": "serial", "primary_key": True},
        {"name": "profile_id", "type": "int", "references": "profiles.id"},
        {"name": "title_id", "type": "int", "references": "titles.id"},
        {"name": "progress_seconds", "type": "int"}]},
    "titles": {"columns": [{"name": "id", "type": "serial", "primary_key": True},
                           {"name": "name", "type": "text"}]},
}

_ENDPOINTS = [
    {"method": "GET", "path": "/api/my-list", "auth_required": True},
    {"method": "GET", "path": "/api/my-list/{id}", "auth_required": True},
    {"method": "GET", "path": "/api/continue-watching", "auth_required": True},
    {"method": "GET", "path": "/api/titles", "auth_required": False},
]


def _render():
    return render_skeleton_main(tables=_TABLES, endpoints=_ENDPOINTS)


def _override_fn(src):
    """Slice `_custom_route_overrides_projected` (and the sets it reads) out of the rendered
    template and exec it standalone — the #528 harness idiom."""
    ns = {}
    for name in ("_NESTED_CHILD_RESOURCES", "_OWNER_SCOPED_RESOURCES", "_DEGENERATE_RESOURCES"):
        m = re.search(rf"^{name} = set\((.*)\)$", src, re.M)
        assert m, f"{name} not emitted into main.py"
        ns[name] = set(eval(m.group(1)))
    m = re.search(r"^def _custom_route_overrides_projected\(method, path\):\n"
                  r"(?:(?:[ \t].*)?\n)+?(?=^\S)", src, re.M)
    assert m, "override function not found in the rendered template"
    exec(compile(m.group(0), "<tmpl>", "exec"), ns)
    return ns["_custom_route_overrides_projected"], ns


def test_degenerate_resource_is_emitted_and_recognised():
    _fn, ns = _override_fn(_render())
    assert "my_list" in ns["_DEGENERATE_RESOURCES"]
    # a fully-registered sibling must NOT be treated as degenerate
    assert "continue_watching" not in ns["_DEGENERATE_RESOURCES"]
    assert "titles" not in ns["_DEGENERATE_RESOURCES"]


def test_a_table_that_genuinely_declares_only_a_pk_is_NOT_degenerate():
    """DECLARED-nothing (schema unknown) vs DECLARED-a-single-PK (schema known and complete).
    Only the first is degenerate — conflating them would hand a correct projected read back to
    the lane and silently undo #528/#566w for every minimal table."""
    tables = dict(_TABLES)
    tables["flags"] = {"columns": [{"name": "id", "type": "serial", "primary_key": True}]}
    src = render_skeleton_main(
        tables=tables,
        endpoints=_ENDPOINTS + [{"method": "GET", "path": "/api/flags", "auth_required": False}])
    fn, ns = _override_fn(src)
    assert "flags" not in ns["_DEGENERATE_RESOURCES"]
    assert fn("GET", "/api/flags") is False, "a minimal but KNOWN schema still projects"


def test_r133_leak_lane_keeps_the_read_for_a_degenerate_resource():
    fn, _ns = _override_fn(_render())
    assert fn("GET", "/api/my-list") is True, "lane must keep the route it can serve safely"
    assert fn("GET", "/api/my-list/{id}") is True


def test_a_complete_resource_still_projects_its_read_unchanged():
    """#566w must not be undone: a schema-complete kebab resource still projects."""
    fn, _ns = _override_fn(_render())
    assert fn("GET", "/api/continue-watching") is False
    assert fn("GET", "/api/continue-watching/{id}") is False


def test_writes_are_untouched_for_a_degenerate_resource():
    """Only READS change hands. Write projection (owner fill, #566s/#566t/#566u) stays."""
    fn, _ns = _override_fn(_render())
    for verb in ("POST", "PUT", "PATCH", "DELETE"):
        assert fn(verb, "/api/my-list") is False
        assert fn(verb, "/api/my-list/{id}") is False


def test_no_degenerate_tables_means_the_guard_is_inert():
    good = {k: v for k, v in _TABLES.items() if k != "my_list"}
    src = render_skeleton_main(tables=good, endpoints=[
        e for e in _ENDPOINTS if "my-list" not in e["path"]])
    fn, ns = _override_fn(src)
    assert ns["_DEGENERATE_RESOURCES"] == set()
    assert fn("GET", "/api/continue-watching") is False


def test_rendered_main_compiles():
    """MANDATORY for a template change: a bad emit breaks EVERY app's generation."""
    src = _render()
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as fh:
        fh.write(src)
        path = fh.name
    py_compile.compile(path, doraise=True)
