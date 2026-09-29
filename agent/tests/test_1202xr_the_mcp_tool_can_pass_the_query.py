"""#1202xr / #1202xs: the projected MCP tool must be able to pass what its endpoint filters on.

#1202xr. The delivered netflix-local-r30 MCP server defines

    async def get_search() -> str:
        resp = await _request("GET", f"{API_BASE_URL}/api/search")

-- a search tool with no way to say what to search for. The backend handler behind it
declares `q`, `type`, `limit` and `offset` as `Query(...)` parameters; none of them can be
reached through the tool, so the external agent this whole surface exists for can list but
never search, filter or paginate. Measured over the corpus when this was written: 462 of
1,760 projected tools (26%), across 94 runs, drop at least one query parameter their own
backend declares, r137 -- the newest run -- among them.

NEITHER source the projector had models query parameters: no endpoint record in any of the
157 corpus runs carries a `query_params` field, and no `reference_spec.json` endpoint carries
one either. The implemented handlers are the only place the information exists, so
`backend_query_params_1202xr` reads them by AST, the way `ddl_behind_models_1202xk` reads
models.py. That makes the fix ADDITIVE by construction: before the backend exists (kickoff's
first projection pass) the map is empty and the render is byte-identical to what it was.

#1202xs. Same call, a second defect one argument over: `write_mcp_server` accepted
`tool_aliases`, handed them to `mcp_tool_records` and DROPPED them when rendering the file.
The registry therefore recorded the spec's semantic names while the served file defined
derived ones -- googlemaps-r16 registered 41 tools of which 26 name a function its own
mcp_server/app/main.py does not define. `spec_tool_aliases`' docstring claims the gates
"bind by construction"; they could not.

Both fixes change what `project_mcp` WRITES, so the "has the contract moved?" comparison in
`refresh_mcp_1202ju` has to render with the same inputs -- otherwise every
cycle sees a mismatch and rewrites (churn, the thing #934/#1202jn were about). The tests
below pin that the two call sites pass the same keywords, because that is the part a future
edit can silently break without any test of behaviour noticing.
"""
import ast
import json
import os
import sys
import tempfile
from pathlib import Path

_AGENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_AGENT, "env_generator", "llm_generator"))

from multi_agent.runtime.mcp_scaffold import (  # noqa: E402
    backend_query_params_1202xr,
    render_mcp_server,
    render_tool,
    spec_tool_aliases,
    _qp_match_key_1202xr,
    _is_scalar_annotation_1202xr,
)

_RUNTIME = os.path.join(_AGENT, "env_generator", "llm_generator", "multi_agent", "runtime")

_HANDLER = '''
from fastapi import APIRouter, Query, Depends
router = APIRouter()

@router.get("/api/search")
def search_content(q: str = Query(default=""), type: str | None = Query(default=None),
                   limit: int = Query(default=50), db=Depends(get_db)):
    return {"items": []}

@router.get("/api/videos/{video_id}")
def get_video(video_id: int, db=Depends(get_db)):
    return {"item": {}}
'''


def _read(path):
    with open(path, encoding="utf-8") as fh:      # #1202eu
        return fh.read()


def _backend_tree(tmp):
    be = os.path.join(tmp, "app", "backend")
    os.makedirs(be, exist_ok=True)
    with open(os.path.join(be, "custom_routes.py"), "w", encoding="utf-8") as fh:
        fh.write(_HANDLER)
    return tmp


def _tool_fn(src, name):
    """The rendered tool as an AST node -- never a substring of the text."""
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)) and node.name == name:
            return node
    return None


def _arg_names(fn):
    return [a.arg for a in fn.args.args] + [a.arg for a in fn.args.kwonlyargs]


def _request_call(fn):
    for node in ast.walk(fn):
        if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "_request":
            return node
    return None


# ── #1202xr: the reader ───────────────────────────────────────────────────────

def test_the_reader_finds_a_handlers_query_parameters():
    with tempfile.TemporaryDirectory() as tmp:
        got = backend_query_params_1202xr(_backend_tree(tmp))
    key = _qp_match_key_1202xr("GET", "/api/search")
    assert got.get(key) == ["q", "type", "limit"], (
        "the only source of query parameters is the handler; got %r" % got)


def test_a_path_parameter_is_not_mistaken_for_a_query_parameter():
    with tempfile.TemporaryDirectory() as tmp:
        got = backend_query_params_1202xr(_backend_tree(tmp))
    assert _qp_match_key_1202xr("GET", "/api/videos/{video_id}") not in got, (
        "get_video declares no Query(...) parameter, so it must contribute nothing: %r" % got)


def test_the_key_survives_a_path_parameter_spelled_differently():
    """r137 holds `/api/videos/{video_id}/comments` against an older `{id}` record."""
    assert (_qp_match_key_1202xr("GET", "/api/videos/{id}/comments")
            == _qp_match_key_1202xr("get", "/api/videos/{video_id}/comments/"))


def test_no_backend_yet_reads_as_no_parameters_not_as_an_error():
    with tempfile.TemporaryDirectory() as tmp:
        assert backend_query_params_1202xr(tmp) == {}
    assert backend_query_params_1202xr(os.path.join(tempfile.gettempdir(),
                                                    "1202xr-no-such-dir")) == {}


def test_one_unparseable_module_does_not_blind_the_others():
    with tempfile.TemporaryDirectory() as tmp:
        _backend_tree(tmp)
        with open(os.path.join(tmp, "app", "backend", "broken.py"), "w",
                  encoding="utf-8") as fh:
            fh.write("def (((\n")
        got = backend_query_params_1202xr(tmp)
    assert got.get(_qp_match_key_1202xr("GET", "/api/search")) == ["q", "type", "limit"]


# ── #1202xr: the rendering ────────────────────────────────────────────────────

def test_the_query_parameter_becomes_an_argument_and_reaches_the_request():
    src = render_tool({"method": "GET", "path": "/api/search", "summary": "s"},
                      query_params=["q", "limit"])
    fn = _tool_fn(src, "get_search")
    assert fn is not None, src
    assert "q" in _arg_names(fn) and "limit" in _arg_names(fn), _arg_names(fn)
    call = _request_call(fn)
    assert call is not None and any(k.arg == "params" for k in call.keywords), (
        "the argument exists but never reaches the backend:\n%s" % src)


def test_an_unsupplied_query_parameter_is_not_sent():
    """Every query argument is optional, and only what the caller passes is forwarded --
    so a tool with query parameters answers exactly as it did before when given none."""
    fn = _tool_fn(render_tool({"method": "GET", "path": "/api/search"},
                              query_params=["q"]), "get_search")
    assert all(d is not None for d in fn.args.defaults[-1:]), "q must be optional"
    comp = next((n for n in ast.walk(fn) if isinstance(n, ast.DictComp)), None)
    assert comp is not None and comp.generators[0].ifs, (
        "the params dict must drop the values the caller did not pass")


def test_a_query_parameter_python_cannot_name_is_dropped_not_emitted():
    """`def f(from=None)` is a SyntaxError -- the whole server would fail to import."""
    src = render_tool({"method": "GET", "path": "/api/x"},
                      query_params=["from", "class", "not-an-identifier", "limit"])
    ast.parse(src)                      # would raise if any of the three were emitted
    assert _arg_names(_tool_fn(src, "get_x")) == ["limit"]


def test_a_query_parameter_never_shadows_the_path_or_body_argument():
    got = _arg_names(_tool_fn(
        render_tool({"method": "POST", "path": "/api/videos/{id}"},
                    query_params=["id", "body", "limit"]), "post_videos_by_id"))
    assert got == ["id", "body", "limit"], got


def test_no_query_parameters_renders_what_it_rendered_before():
    ep = {"method": "GET", "path": "/api/videos/{id}", "summary": "v"}
    assert render_tool(ep) == render_tool(ep, query_params=[]) == render_tool(
        ep, query_params=None)


# ── #1202xs: the alias reaches the file, not only the registry ────────────────

def test_the_spec_tool_name_is_the_one_the_server_defines():
    eps = {"a": {"method": "GET", "path": "/api/places/{id}", "status": "implemented"}}
    aliases = spec_tool_aliases(
        {"mcp_tools": [{"name": "get_place_details", "endpoint": "GET /api/places/{id}"}]})
    assert aliases, "the alias fixture itself is empty"
    out = render_mcp_server(eps, "app", tool_aliases=aliases)
    assert _tool_fn(out, "get_place_details") is not None, (
        "the registry records this name; the served file must define it")
    assert _tool_fn(out, "get_places_by_id") is None


# ── the writer and the 'has it moved?' comparison must use ONE set of inputs ───

def _call_keywords(path, fn_name, callee):
    """Keyword names of every `callee(...)` call inside `fn_name`, by AST."""
    for node in ast.walk(ast.parse(_read(path))):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == fn_name:
            for c in ast.walk(node):
                if isinstance(c, ast.Call) and getattr(c.func, "id", "") == callee:
                    return {k.arg for k in c.keywords}
    return None


def test_the_writer_renders_with_both_the_aliases_and_the_query_parameters():
    """#1202xu moved the render behind `rendered_as_written_1202xu`; the invariant this has
    always protected is that the writer hands it BOTH inputs (#1202xs was the aliases being
    taken and then not passed)."""
    kw = _call_keywords(os.path.join(_RUNTIME, "mcp_scaffold.py"),
                        "write_mcp_server", "rendered_as_written_1202xu")
    assert kw is not None, "write_mcp_server no longer renders the server"
    assert {"tool_aliases", "query_params"} <= kw, kw


def test_the_moved_check_renders_with_the_same_inputs_as_the_writer():
    """A comparison blind to an input the writer uses calls every cycle a change (churn);
    one that sees an input the writer ignores calls a real change no change."""
    scaffolder = os.path.join(_RUNTIME, "scaffolder.py")
    kw = _call_keywords(scaffolder, "refresh_mcp_1202ju", "rendered_as_written_1202xu")
    assert kw is not None, "the re-projection check no longer renders for comparison"
    # #1202xu: the two sides may differ in HOW they get the query parameters (the writer has
    # already read the tree and passes its one read; the comparison has not and lets the
    # shared function read) -- but they must agree on the aliases, and neither may render
    # outside the shared function.
    assert "tool_aliases" in kw, kw
    assert _call_keywords(scaffolder, "refresh_mcp_1202ju", "render_mcp_server") is None, (
        "the comparison renders on its own again -- that is how the three divergences began")


def test_both_alias_readers_are_the_same_function():
    """#1032: two copies drift. `project_mcp` and the moved-check must not each parse
    reference_spec.json their own way."""
    src = _read(os.path.join(_RUNTIME, "scaffolder.py"))
    tree = ast.parse(src)
    callers = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for c in ast.walk(node):
                if isinstance(c, ast.Call) and getattr(c.func, "id", "") == "_mcp_spec_aliases_1202xs":
                    callers.add(node.name)
    assert {"project_mcp", "refresh_mcp_1202ju"} <= callers, (
        "both must read the aliases through the one helper; found %r" % callers)
    # The helper's own body is the ONE place that may call it: there it is the
    # injected argument, not a second reader.
    helper = next(n for n in ast.walk(tree)
                  if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                  and n.name == "_mcp_spec_aliases_1202xs")
    inside = {id(c) for c in ast.walk(helper)}
    direct = [n for n in ast.walk(tree)
              if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "spec_tool_aliases"
              and id(n) not in inside]
    assert not direct, (
        "spec_tool_aliases is read somewhere else again -- that is the second copy")


# ── the whole projection, over the real corpus shape ──────────────────────────

def test_a_rendered_server_is_valid_python_for_every_shape_the_corpus_holds():
    eps = {}
    for i, (m, p) in enumerate([
            ("GET", "/api/search"), ("GET", "/api/videos/{id}"),
            ("POST", "/api/videos/{id}/comments"), ("DELETE", "/api/videos/{id}/like"),
            ("GET", "/api/v1/tenants"), ("GET", "/api/tenants"), ("GET", "/")]):
        eps[str(i)] = {"method": m, "path": p, "status": "implemented"}
    qp = {_qp_match_key_1202xr("GET", "/api/search"): ["q", "type", "limit", "from"],
          _qp_match_key_1202xr("GET", "/api/videos/{id}"): ["id", "expand"],
          _qp_match_key_1202xr("POST", "/api/videos/{id}/comments"): ["body", "dry_run"]}
    src = render_mcp_server(eps, "app", query_params=qp)
    ast.parse(src)
    names = [n.name for n in ast.walk(ast.parse(src))
             if isinstance(n, (ast.AsyncFunctionDef, ast.FunctionDef))]
    assert len(names) == len(set(names)), "a tool name collides: %r" % names


# ── #1202xr: FastAPI's SECOND query-parameter form ────────────────────────────

_BARE_HANDLER = '''
from fastapi import APIRouter, Depends, Header
from typing import Annotated, Optional
router = APIRouter()

@router.get("/api/titles")
def list_titles(kind: str | None = None, genre: str | None = None,
                limit: int = 50, db=Depends(get_db)):
    return {"items": []}

@router.post("/api/titles")
def create_title(body: dict | None = None,
                 tenant: Annotated[Optional[str], Header(alias="X-Tenant-Id")] = None,
                 db=Depends(get_db)):
    return {"item": {}}
'''


def _bare_tree(tmp):
    be = os.path.join(tmp, "app", "backend")
    os.makedirs(be, exist_ok=True)
    with open(os.path.join(be, "routes.py"), "w", encoding="utf-8") as fh:
        fh.write(_BARE_HANDLER)
    return tmp


def test_a_bare_scalar_default_is_a_query_parameter_too():
    """netflix-r30's `search_titles(q: str = "", kind: str | None = None, limit: int = 50)`
    declares six query parameters and not one `Query(...)`. Reading only the explicit form
    found none of them and left the delivered `get_search()` with no arguments at all."""
    with tempfile.TemporaryDirectory() as tmp:
        got = backend_query_params_1202xr(_bare_tree(tmp))
    assert got.get(_qp_match_key_1202xr("GET", "/api/titles")) == ["kind", "genre", "limit"], got


def test_a_body_is_not_mistaken_for_a_query_parameter():
    """`body: dict | None = None` has the same default shape as `kind: str | None = None`.
    Only the ANNOTATION separates them, which is why the predicate reads that and not the
    default -- 932 `dict` and 305 `dict | None` parameters in the corpus ride on this."""
    with tempfile.TemporaryDirectory() as tmp:
        got = backend_query_params_1202xr(_bare_tree(tmp))
    assert got.get(_qp_match_key_1202xr("POST", "/api/titles")) is None, got


def test_the_annotation_predicate_admits_and_rejects_by_shape():
    import ast as _ast

    def _ann(text):
        return _ast.parse("def f(x: %s = None): pass" % text).body[0].args.args[0].annotation
    for yes in ("str", "int", "str | None", "Optional[int]", "bool", "float | None"):
        assert _is_scalar_annotation_1202xr(_ann(yes)), yes
    for no in ("dict", "dict | None", "Optional[Dict[str, Any]]", "Request",
               "list[str]", "Session", "Annotated[Optional[str], Header()]"):
        assert not _is_scalar_annotation_1202xr(_ann(no)), no
    assert not _is_scalar_annotation_1202xr(None), "an unannotated parameter is not admitted"


def test_the_local_dict_never_shadows_an_argument():
    """A path parameter may legally be named `_params`; then the f-string path would
    interpolate the DICT and the tool would request a URL nobody serves."""
    src = render_tool({"method": "GET", "path": "/api/x/{_params}"},
                      query_params=["limit"])
    ast.parse(src)
    fn = next(n for n in ast.walk(ast.parse(src))
              if isinstance(n, (ast.AsyncFunctionDef, ast.FunctionDef)))
    assigned = {t.id for n in ast.walk(fn) if isinstance(n, ast.Assign)
                for t in n.targets if isinstance(t, ast.Name)}
    assert "_params" not in assigned, (
        "the local reuses the path parameter's name:\n%s" % src)
    call = _request_call(fn)
    kw = next(k for k in call.keywords if k.arg == "params")
    assert isinstance(kw.value, ast.Name) and kw.value.id in assigned


# ── the record and the served function must describe the same tool ────────────

def test_the_record_declares_the_arguments_the_served_tool_takes():
    """#1202xs in its general form: the registry record and the rendered file are two
    halves of one projection. If a half is built from an input the other was not, the
    registry describes a tool that is not the one being served."""
    from multi_agent.runtime.mcp_scaffold import mcp_tool_records

    eps = {"a": {"method": "GET", "path": "/api/videos/{id}", "status": "implemented"}}
    qp = {_qp_match_key_1202xr("GET", "/api/videos/{id}"): ["limit", "id", "body"]}
    rec = mcp_tool_records(eps, query_params=qp)[0]
    fn = _tool_fn(render_mcp_server(eps, "app", query_params=qp), rec["tool_name"])
    assert fn is not None, "the record names a tool the file does not define"
    declared = (list(rec["schema"]["input"]["path_params"])
                + list(rec["schema"]["input"]["query_params"]))
    assert declared == _arg_names(fn), (
        "record says %r, the served function takes %r" % (declared, _arg_names(fn)))


def test_the_writer_registers_and_renders_from_one_read():
    """Two calls to `backend_query_params_1202xr` inside `write_mcp_server` would be two
    reads of a tree an agent is writing to, i.e. two different answers (#1032)."""
    src = _read(os.path.join(_RUNTIME, "mcp_scaffold.py"))
    fn = next(n for n in ast.walk(ast.parse(src))
              if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
              and n.name == "write_mcp_server")
    reads = [c for c in ast.walk(fn) if isinstance(c, ast.Call)
             and getattr(c.func, "id", "") == "backend_query_params_1202xr"]
    assert len(reads) == 1, "expected one read of the backend, found %d" % len(reads)
    for callee in ("rendered_as_written_1202xu", "mcp_tool_records"):
        call = next(c for c in ast.walk(fn) if isinstance(c, ast.Call)
                    and getattr(c.func, "id", "") == callee)
        assert any(k.arg == "query_params" for k in call.keywords), (
            "%s is not given the query parameters" % callee)


def test_query_imported_under_another_name_is_still_a_query_parameter():
    """tiktok-r61 writes `from fastapi import Query as _Q` and then
    `limit: int = _Q(20, ge=1, le=100)`. Matching the bare name `Query` reads that
    handler as declaring nothing."""
    with tempfile.TemporaryDirectory() as tmp:
        be = os.path.join(tmp, "app", "backend")
        os.makedirs(be)
        with open(os.path.join(be, "r.py"), "w", encoding="utf-8") as fh:
            fh.write("from fastapi import Query as _Q, Body as _B\n"
                     "@app.get('/api/feed')\n"
                     "def feed(limit: int = _Q(20), payload: dict = _B(None)):\n"
                     "    return {}\n")
        got = backend_query_params_1202xr(tmp)
    assert got.get(_qp_match_key_1202xr("GET", "/api/feed")) == ["limit"], (
        "the alias must resolve, and Body must NOT ride along: %r" % got)


# ── #1202xt: a write tool must name the fields the contract says it takes ──────

def _doc_of(fn):
    return ast.get_docstring(fn) or ""


def test_a_write_tool_names_its_body_fields():
    """FastMCP builds the input schema from the SIGNATURE, and every projected write takes
    `body: dict | None = None` -- `{"type": "object"}` with no properties. The delivered r137
    exposes `post_auth_signup` whose contract states four fields and whose tool says only
    "POST /api/auth/signup", so an agent has to guess them."""
    ep = {"method": "POST", "path": "/api/auth/signup", "summary": "Create an account",
          "schema": {"request": {"username": "string", "email": "string",
                                 "password": "string", "display_name": "string?"}}}
    doc = _doc_of(_tool_fn(render_tool(ep), "post_auth_signup"))
    for f in ("username", "email", "password", "display_name"):
        assert f in doc, "%r is not named: %r" % (f, doc)
    assert doc.startswith("Create an account"), "the summary must survive: %r" % doc


def test_the_fields_are_named_in_the_contract_s_own_order():
    ep = {"method": "POST", "path": "/api/x",
          "schema": {"request": {"z": "string", "a": "int", "m": "bool"}}}
    doc = _doc_of(_tool_fn(render_tool(ep), "post_x"))
    assert doc.index("z (") < doc.index("a (") < doc.index("m ("), doc


def test_a_contract_value_cannot_break_out_of_the_docstring():
    """The types come from the contract, so a `"` would close the triple quote and a newline
    would split the note."""
    ep = {"method": "POST", "path": "/api/x",
          "schema": {"request": {"a": 'a "quoted"\ntype', "b": {"nested": 1}, "c": ["x"],
                                 "d": True, "": "skipped"}}}
    src = render_tool(ep)
    ast.parse(src)                       # would raise on an unescaped quote
    doc = _doc_of(_tool_fn(src, "post_x"))
    assert '"' not in doc and "\n" not in doc, doc
    assert "b (object)" in doc and "c (array)" in doc, doc


def test_a_read_tool_gets_no_body_note():
    ep = {"method": "GET", "path": "/api/x", "schema": {"request": {"q": "string"}}}
    assert "Body fields" not in _doc_of(_tool_fn(render_tool(ep), "get_x"))


def test_no_request_schema_renders_what_it_rendered_before():
    a = {"method": "POST", "path": "/api/y"}
    b = {"method": "POST", "path": "/api/y", "schema": {"request": {}}}
    assert render_tool(a) == render_tool(b)


def test_the_note_is_not_capped():
    """A truncated field list is worse than none for the one job this has: the corpus's
    largest request schema is 21 fields and only 16 of 1,968 exceed 11, so there is nothing
    to cut (#1034 -- and a cut list would have to say it was cut)."""
    req = {("f%02d" % i): "string" for i in range(21)}
    doc = _doc_of(_tool_fn(render_tool({"method": "POST", "path": "/api/x",
                                        "schema": {"request": req}}), "post_x"))
    for f in req:
        assert f in doc, "%s was dropped: %r" % (f, doc)
    assert "more" not in doc.lower()


# ── #1202xu: the comparison must reproduce what the writer puts on disk ────────

def test_the_scrubber_changes_the_rendered_server():
    """The premise. If the skeleton were free of ticket tags the old comparison would have
    worked; it is not -- r138's live render differs from its scrubbed form on exactly the
    `# #1202sa:` line -- so a comparison that skips the scrub can never say "unchanged"."""
    from multi_agent.runtime.mcp_scaffold import _scrubbed_1202mi

    eps = {"a": {"method": "GET", "path": "/api/x", "status": "implemented"}}
    raw = render_mcp_server(eps, "app")
    assert _scrubbed_1202mi(raw, "main.py") != raw, (
        "this test's premise is gone: the skeleton no longer carries a scrubbed tag, so "
        "#1202xu's mechanism cannot fire and this whole guard needs rethinking")


def test_the_writer_and_the_comparison_call_one_function():
    """#1202xr, #1202xs and #1202xu were each one input the two sides did not share. The
    guard is structural: both must go through `rendered_as_written_1202xu`, by AST."""
    def _calls(path, fn_name):
        for node in ast.walk(ast.parse(_read(path))):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == fn_name:
                return {getattr(c.func, "id", "") for c in ast.walk(node) if isinstance(c, ast.Call)}
        return set()

    ms = os.path.join(_RUNTIME, "mcp_scaffold.py")
    sc = os.path.join(_RUNTIME, "scaffolder.py")
    writer = _calls(ms, "write_mcp_server")
    compare = _calls(sc, "refresh_mcp_1202ju")
    assert "rendered_as_written_1202xu" in writer, (
        "the writer no longer goes through the shared render: %r" % sorted(writer))
    assert "rendered_as_written_1202xu" in compare, (
        "the comparison no longer goes through the shared render: %r" % sorted(compare))
    # And neither side may reach past it to the raw render again.
    assert "render_mcp_server" not in compare, (
        "the comparison renders on its own again -- that is how the three divergences began")


def test_a_freshly_written_server_compares_equal():
    """The end-to-end property the mechanism promises: write, then compare, and get
    'unchanged'. This is what was false -- every call re-projected."""
    import tempfile
    from multi_agent.runtime.mcp_scaffold import (write_mcp_server,
                                                  rendered_as_written_1202xu)

    eps = {"a": {"method": "GET", "path": "/api/x", "status": "implemented"},
           "b": {"method": "POST", "path": "/api/x/{id}", "status": "implemented",
                 "schema": {"request": {"note": "string"}}}}
    with tempfile.TemporaryDirectory() as tmp:
        res = write_mcp_server(Path(tmp), eps, "app")
        on_disk = _read(str(res["main_py"]))
        assert on_disk == rendered_as_written_1202xu(tmp, eps, "app"), (
            "the file just written does not equal what the comparison renders, so "
            "'has the contract moved?' answers yes forever")


# ── #1202xy: a header is not a body field ─────────────────────────────────────

def test_a_contract_marked_header_is_listed_as_a_header():
    """r138's own re-projected server listed `X-Tenant-ID (header string?)` under "Body
    fields". An agent that puts a tenant in the body gets the default tenant."""
    ep = {"method": "POST", "path": "/api/x",
          "schema": {"request": {"email": "string", "X-Tenant-Id": "header string?",
                                 "Authorization": "header string"}}}
    doc = ast.get_docstring(_tool_fn(render_tool(ep), "post_x")) or ""
    assert "Body fields: email (string)" in doc, doc
    assert "Headers: X-Tenant-Id" in doc and "Authorization" in doc, doc
    body_part = doc.split("Headers:")[0]
    assert "X-Tenant-Id" not in body_part, "the header is still named as a body field: %r" % doc


def test_headers_only_still_says_so():
    ep = {"method": "POST", "path": "/api/x",
          "schema": {"request": {"Authorization": "header string"}}}
    doc = ast.get_docstring(_tool_fn(render_tool(ep), "post_x")) or ""
    assert "Headers: Authorization" in doc and "Body fields" not in doc, doc


def test_the_written_server_carries_no_framework_ticket_tag():
    """★ Caught by mutation: `test_a_freshly_written_server_compares_equal` passes even with
    the scrub REMOVED, because both sides go through one function and stay equal to each
    other. Equality is only half of it -- the file on disk must also be SCRUBBED, which is
    the property #1202mi owns and the reason the comparison had to learn about it."""
    import re as _re
    import tempfile
    from multi_agent.runtime.mcp_scaffold import write_mcp_server

    eps = {"a": {"method": "GET", "path": "/api/x", "status": "implemented"}}
    with tempfile.TemporaryDirectory() as tmp:
        res = write_mcp_server(Path(tmp), eps, "app")
        text = _read(str(res["main_py"]))
    tags = sorted(set(_re.findall(r"#\d{3,4}[a-z]{0,3}\b|#1202[a-z]{1,3}\b", text)))
    assert not tags, "framework ticket tags shipped in the generated server: %r" % tags
