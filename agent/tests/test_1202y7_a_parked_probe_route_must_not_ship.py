r"""#1202y7: a route the lane parked to satisfy a framework check must not ship.

r140 delivered `GET /__noop_orchestrator_probe__`, and the lane's own docstring says why it
exists: "DB-backed readiness probe used by delivery validation ... so code-truth can
distinguish it from a static placeholder". Asked to prove its endpoints were not static
placeholders, the lane answered with a PUBLIC, UNAUTHENTICATED route running
`SELECT COUNT(*)` over four business tables, and shipped it. r80's `/__list__` is the same
move stated more plainly: "re-implemented here so provider flips to 'backend' and the
business-endpoint audit sees a real handler."

★ The framework already knew. `seed_audit` carries the note (#1202du, corrected by #1202dw:
"an AGENT parks them, the framework does not emit them") and answers it with
`if str(name).startswith("__"): continue` -- an EXEMPTION, so its own audit stops tripping
over them. Exempting a thing from a check is not the same as keeping it out of the product,
and the exemption covers the smaller surface: 7 of 179 runs park a `__` TABLE, 36 park a
`__` ROUTE.

Corpus, measured with the same reader the check calls (`served_routes`, so verdict and
evidence cannot disagree -- #1032): 36 of 179 runs, 20%, 25 distinct paths, and rising --
0 of 83 in July, 10 of 31 in August, 25 of 65 in September, r140 included. Zero false
positives: the widest name in the whole corpus is `/__list__`, which re-implements a
framework audit endpoint.
"""
import os
import sys

import pytest

_AGENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_AGENT, "env_generator", "llm_generator"))

from multi_agent.runtime.deliverability import (  # noqa: E402
    _parked_probe_routes_1202y7 as parked)

# `from <mod> import router` + `include_router(<name>)` is what `served_routes` resolves,
# and what 158 of the 179 corpus backends actually write. (`import <mod>` +
# `include_router(<mod>.router)` resolves to nothing there -- a latent gap with ZERO corpus
# instances, measured, so it is not this test's business.)
_MAIN = """from fastapi import FastAPI
from custom_routes import router as _cr
app = FastAPI()
app.include_router(_cr)
"""


def _backend(tmp_path, routes, main=_MAIN):
    app = tmp_path / "app"
    bd = app / "backend"
    bd.mkdir(parents=True)
    (bd / "main.py").write_text(main, encoding="utf-8")
    body = "from fastapi import APIRouter\nrouter = APIRouter()\n"
    for i, (verb, path) in enumerate(routes):
        body += "\n@router.%s(%r)\ndef h%d():\n    return {}\n" % (verb, path, i)
    (bd / "custom_routes.py").write_text(body, encoding="utf-8")
    return str(app)


def test_the_r140_route_is_reported(tmp_path):
    """The live instance, by name."""
    app = _backend(tmp_path, [("get", "/api/feed"),
                              ("get", "/__noop_orchestrator_probe__")])
    out = parked(app)
    assert out, "the parked probe must block delivery"
    assert "/__noop_orchestrator_probe__" in out[0]
    assert "/api/feed" not in out[0], "only the parked route is named: %r" % out


def test_r80s_list_endpoint_is_reported(tmp_path):
    """★ The widest name in the corpus -- and the one whose docstring says it was written
    to change which provider the audit credits."""
    assert parked(_backend(tmp_path, [("get", "/__list__")]))


def test_an_ordinary_backend_is_clean(tmp_path):
    """No false positive. These are the shapes a real app serves, including the dunder-free
    infrastructure paths the framework itself projects."""
    app = _backend(tmp_path, [("get", "/api/feed"), ("post", "/auth/login"),
                              ("get", "/health"), ("get", "/.well-known/jwks.json"),
                              ("delete", "/api/videos/{video_id}/like"),
                              ("get", "/api/v1/tenants")])
    assert parked(app) == []


def test_a_dunder_in_a_later_segment_is_reported(tmp_path):
    """The predicate reads ANY segment. No corpus path parks below the root today, so this
    costs nothing now and does not quietly depend on that staying true."""
    assert parked(_backend(tmp_path, [("get", "/api/__noop__")]))


def test_a_double_underscore_inside_a_word_is_not_a_prefix(tmp_path):
    """`startswith`, not `in`: a path that merely CONTAINS the characters is untouched."""
    assert parked(_backend(tmp_path, [("get", "/api/a__b")])) == []


def test_the_kill_switch_disables_it(tmp_path, monkeypatch):
    app = _backend(tmp_path, [("get", "/__noop__")])
    assert parked(app)
    monkeypatch.setenv("ENVGEN_PARKED_ROUTE_GATE", "0")
    assert parked(app) == []


def test_a_missing_backend_is_not_a_verdict(tmp_path):
    """`[]` on anything unreadable -- the rule every blocker producer here follows."""
    assert parked(str(tmp_path / "nothing")) == []


def test_the_prose_routes_to_a_check_id():
    """★ #1202tu: a blocker whose prose maps to nothing dispatches NOBODY. The mapping is
    by SUBSTRING, so it is the prose that has to be pinned, not a constant."""
    from multi_agent.runtime.delivery_gate import _deliverability_check_token as tok
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        app = _backend(__import__("pathlib").Path(td), [("get", "/__noop__")])
        prose = parked(app)[0]
    assert tok(prose) == "deliverability_parked_probe_route", tok(prose)


def test_the_check_id_has_a_remediation_owner():
    """★ The other half of #1202tu: a token nobody owns is a blocker with no way out."""
    import multi_agent.runtime.remediation_dispatcher as RD
    src = __import__("inspect").getsource(RD)
    assert '"deliverability_parked_probe_route": (' in src
    i = src.index('"deliverability_parked_probe_route": (')
    assert '"backend"' in src[i:i + 200], "the owner lane must be named"


def test_it_reuses_the_one_route_reader():
    """★ #1032: two copies drift. The verdict and the corpus measurement must come from the
    SAME reader, or the number in the docstring stops describing what ships."""
    import ast
    import inspect
    import multi_agent.runtime.deliverability as D
    tree = ast.parse(inspect.getsource(D._parked_probe_routes_1202y7).lstrip())
    called = {n.func.id for n in ast.walk(tree)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert "served_routes" in called, (
        "must call served_routes, not re-parse decorators: %s" % sorted(called))
    assert not any(isinstance(n, ast.Attribute) and n.attr == "decorator_list"
                   for n in ast.walk(tree)), "that would be the third copy"


def test_it_is_wired_into_the_blocker_list():
    """A check nobody calls is the defect this codebase keeps finding in itself."""
    import inspect
    import multi_agent.runtime.deliverability as D
    src = inspect.getsource(D)
    assert "blockers.extend(_parked_probe_routes_1202y7(app_root))" in src


@pytest.mark.parametrize("path", ["/__noop__", "/__probe_read_only_orchestrator_state__",
                                  "/__noop_orchestrator_read_not_allowed__",
                                  "/__noop_monitoring_probe__"])
def test_every_corpus_shape_is_caught(tmp_path, path):
    """The four families the 179-run sweep turned up, by their real names."""
    assert parked(_backend(tmp_path, [("get", path)]))
