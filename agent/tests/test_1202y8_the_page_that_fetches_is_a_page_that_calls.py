r"""#1202y8: the page that issues its own fetch is a page that calls.

`page_api_endpoints_1202wd` read the api-client imports and nothing else, so r140's
LoginPage -- which posts to `/auth/login` and `/auth/register` with `fetch` and imports
nothing from `services/api` -- resolved to `[]`. That answer is now load-bearing: #1202xv
fills `apis_used` FROM it and #1202y1 reports the registry AGAINST it, so a page the reader
cannot see is a page the registry may describe however it likes, unchallenged.

Corpus, measured with the module's own parser: 202 fetch call sites carrying a literal
absolute path, on 179 pages across 51 of the 179 runs -- 7% of all pages.

★ WHAT IS DELIBERATELY NOT ADMITTED. A literal path is not evidence on its own. 16 of the
202 name a path NO backend serves (`/api/users` x4, `/api/videos` x3, r140's `/__noop__`
x2), and admitting those would INVENT endpoints -- worse than missing them, because the
drift check compares the registry against this answer. So the rule is METHOD AND PATH must
both be a route in the code: 186 of 202 admitted (92%), zero invented. The 16 turned away
are the unimplemented-endpoint check's question, not this one.

★ AND `axios` IS NOT HANDLED, on purpose: measured at ZERO call sites across all 179
frontends. A branch for it would be a mechanism that never fires -- the shape this codebase
keeps finding in itself.
"""
import os
import sys

_AGENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_AGENT, "env_generator", "llm_generator"))

from multi_agent.runtime.frontend_audit import (  # noqa: E402
    page_api_endpoints_1202wd as eps)

_BACKEND = """from fastapi import FastAPI
app = FastAPI()

@app.post("/auth/login")
def login():
    return {}

@app.post("/auth/register")
def register():
    return {}

@app.get("/api/feed")
def feed():
    return {}
"""

_CLIENT = ("export async function getFeed() { return request('/api/feed'); }\n")


def _app(tmp_path, pages, components=None, backend=_BACKEND, client=_CLIENT):
    app = tmp_path / "app"
    (app / "backend").mkdir(parents=True)
    (app / "backend" / "main.py").write_text(backend, encoding="utf-8")
    src = app / "frontend" / "src"
    (src / "pages").mkdir(parents=True)
    (src / "components").mkdir()
    (src / "services").mkdir()
    (src / "services" / "api.js").write_text(client, encoding="utf-8")
    for n, b in (pages or {}).items():
        (src / "pages" / ("%s.jsx" % n)).write_text(b, encoding="utf-8")
    for n, b in (components or {}).items():
        (src / "components" / ("%s.jsx" % n)).write_text(b, encoding="utf-8")
    return str(app)


_LOGIN = """import { useState } from 'react';
export default function LoginPage() {
  const onSubmit = async () => {
    await fetch('/auth/login', { method: 'POST', body: JSON.stringify({}) });
    await fetch('/auth/register', { method: 'POST' });
  };
  return <form onSubmit={onSubmit} />;
}
"""


def test_the_r140_login_page_resolves(tmp_path):
    """The live shape, by name: two posts, no client import, previously `[]`."""
    got = eps(_app(tmp_path, {"LoginPage": _LOGIN}), "LoginPage")
    assert set(got) == {"POST /auth/login", "POST /auth/register"}, got


def test_a_fetch_without_a_method_is_a_get(tmp_path):
    page = "export default function P() { fetch('/api/feed'); return null; }\n"
    assert eps(_app(tmp_path, {"P": page}), "P") == ["GET /api/feed"]


def test_a_path_the_backend_does_not_serve_is_not_invented(tmp_path):
    """★ The rule that makes this safe. `/api/users` is requested by four corpus pages and
    implemented by none; inventing it would put a phantom endpoint into `apis_used`."""
    page = "export default function P() { fetch('/api/users'); return null; }\n"
    assert eps(_app(tmp_path, {"P": page}), "P") == []


def test_a_wrong_method_on_a_real_path_is_not_invented(tmp_path):
    """METHOD AND path, not path alone: the backend serves POST /auth/login, not GET."""
    page = "export default function P() { fetch('/auth/login'); return null; }\n"
    assert eps(_app(tmp_path, {"P": page}), "P") == []


def test_a_query_string_is_stripped(tmp_path):
    page = "export default function P() { fetch('/api/feed?limit=24&sort=new'); return null; }\n"
    assert eps(_app(tmp_path, {"P": page}), "P") == ["GET /api/feed"]


def test_a_template_path_is_skipped(tmp_path):
    """Its concrete value is not in the source; matching `/api/feed/${id}` against a route
    with a `{param}` placeholder would be a guess."""
    page = ("export default function P() { fetch(`/api/feed/${id}`); return null; }\n")
    assert eps(_app(tmp_path, {"P": page}), "P") == []


def test_a_relative_path_is_skipped(tmp_path):
    page = "export default function P() { fetch('api/feed'); return null; }\n"
    assert eps(_app(tmp_path, {"P": page}), "P") == []


def test_the_client_path_still_works(tmp_path):
    """Nothing about the original answer changes."""
    page = ("import { getFeed } from '../services/api';\n"
            "export default function P() { getFeed(); return null; }\n")
    assert eps(_app(tmp_path, {"P": page}), "P") == ["GET /api/feed"]


def test_both_sources_are_unioned(tmp_path):
    page = ("import { getFeed } from '../services/api';\n"
            "export default function P() {\n"
            "  getFeed();\n"
            "  fetch('/auth/login', { method: 'POST' });\n"
            "  return null;\n}\n")
    assert set(eps(_app(tmp_path, {"P": page}), "P")) == {
        "GET /api/feed", "POST /auth/login"}


def test_a_fetching_page_does_not_borrow_its_childs_endpoints(tmp_path):
    """★ r89's dilution rule still holds: a page that calls is the answer. A page whose
    only call is a raw fetch must NOT also collect the chrome it renders."""
    page = ("import Modal from '../components/Modal';\n"
            "export default function P() {\n"
            "  fetch('/auth/login', { method: 'POST' });\n"
            "  return <Modal />;\n}\n")
    child = ("import { getFeed } from '../services/api';\n"
             "export default function Modal() { getFeed(); return null; }\n")
    got = eps(_app(tmp_path, {"P": page}, {"Modal": child}), "P")
    assert got == ["POST /auth/login"], got


def test_a_backendless_app_does_not_crash(tmp_path):
    """No backend to read routes from -> nothing admitted, no exception."""
    app = tmp_path / "app"
    src = app / "frontend" / "src"
    (src / "pages").mkdir(parents=True)
    (src / "services").mkdir()
    (src / "services" / "api.js").write_text(_CLIENT, encoding="utf-8")
    (src / "pages" / "P.jsx").write_text(
        "export default function P() { fetch('/api/feed'); return null; }\n",
        encoding="utf-8")
    assert eps(str(app), "P") == []


def test_it_reuses_the_modules_own_fetch_parser():
    """★ #1032: a second parser for the same syntax is the copy that drifts. The quote-aware
    span reader and the literal splitter already exist for exactly this."""
    import ast
    import inspect
    import multi_agent.runtime.frontend_audit as F

    body = inspect.getsource(F.page_api_endpoints_1202wd)
    tree = ast.parse(body.lstrip())
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    for required in ("_BARE_FETCH_RE", "_balanced_call_span", "_leading_string_literal"):
        assert required in names, "must reuse %s" % required


def test_axios_is_not_handled():
    """★ Measured at ZERO call sites across 179 frontends, so a branch for it would be a
    mechanism that never fires. Pinned so a later "while we are here" does not add one
    without new evidence.

    Asserted against the CODE, not the text: the comment explaining the omission naturally
    contains the word, so a substring test on the source would fail on its own rationale.
    """
    import ast
    import inspect
    import multi_agent.runtime.frontend_audit as F

    tree = ast.parse(inspect.getsource(F.page_api_endpoints_1202wd).lstrip())
    # every docstring in the tree, not just the outer one -- the nested reader carries its
    # own, and it is the nested one that explains the omission. (My first draft compared
    # against `ast.get_docstring(tree)` alone and failed on that explanation.)
    docs = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Module)):
            d = ast.get_docstring(node, clean=False)
            if d:
                docs.add(d)
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if node.value in docs:
                continue
            assert "axios" not in node.value.lower(), (
                "if axios is being added, bring the corpus count that justifies it")
        if isinstance(node, (ast.Name, ast.Attribute)):
            assert "axios" not in (getattr(node, "id", "")
                                   + getattr(node, "attr", "")).lower()
