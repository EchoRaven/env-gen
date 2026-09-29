r"""#1202y4: ask the resolver even when the page's own file shows no call.

#1202y1 changed what this check COMPARES -- the registry against the source rather than
against the empty list -- and left the ENTRY condition untouched: the PAGE'S OWN text had
to look like a call before the resolver was consulted at all. For the empty-declaration
case that was fine. For understatement it is the wrong question: what matters is whether
the component TREE reaches more than the registry lists, which is what
`page_api_endpoints_1202wd` answers.

Caught on a live run rather than by reading: a 19-line SignupPage that renders four default
imports and calls nothing itself. The resolver reaches `GET /api/me`,
`GET /api/v1/tenants` and `POST /auth/register` through it; the registration names
`POST /auth/signup`, which is none of them; and the check returned nothing at all.

Corpus: 46 runs hold a page the entry condition turns away while the resolver reaches
endpoints the registry lacks -- one run 10 pages, two others 8 pages each whose single
worst page is short by 11 and 12 endpoints.

The unresolved-and-empty case still needs the own-call signal: with no endpoints resolved
and nothing declared, "this page calls something" is the only evidence there is.
"""
import os
import sys

_AGENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_AGENT, "env_generator", "llm_generator"))

from multi_agent.runtime.deliverability import (  # noqa: E402
    _page_api_declaration_drift_1202rr as drift)


class _RH:
    def __init__(self, pages):
        self._p = pages

    def list_ui_pages(self):
        return self._p


class _Hubs:
    def __init__(self, pages):
        self.registryhub = _RH(pages)


_API = ("export async function getMe() { return request('/api/me'); }\n"
        "export async function register() { return request('/auth/register', "
        "{method:'POST'}); }\n")


def _tree(tmp, pages, components):
    src = tmp / "frontend" / "src"
    (src / "pages").mkdir(parents=True)
    (src / "components").mkdir()
    (src / "services").mkdir()
    (src / "services" / "api.js").write_text(_API, encoding="utf-8")
    for n, b in pages.items():
        (src / "pages" / ("%s.jsx" % n)).write_text(b, encoding="utf-8")
    for n, b in components.items():
        (src / "components" / ("%s.jsx" % n)).write_text(b, encoding="utf-8")
    return str(tmp)


_DELEGATING_PAGE = ("import Modal from '../components/Modal';\n"
                    "export default function SignupPage() { return <Modal />; }\n")
_CALLING_CHILD = ("import { getMe, register } from '../services/api';\n"
                  "export default function Modal() { getMe(); register(); return null; }\n")


def test_a_page_that_calls_nothing_itself_is_still_checked(tmp_path):
    """The live shape: the page delegates, the child calls, the registry names neither."""
    app = _tree(tmp_path, {"SignupPage": _DELEGATING_PAGE}, {"Modal": _CALLING_CHILD})
    out = drift(_Hubs({"signup": {"component": "SignupPage",
                                  "apis_used": ["POST /auth/signup"]}}), app)
    assert out, "a delegating page's understatement must be reported"
    assert "/api/me" in out[0] and "/auth/register" in out[0], out
    assert "/auth/signup" not in out[0], (
        "only what the registry LACKS should be named: %r" % out)


def test_a_delegating_page_whose_registry_is_complete_is_clean(tmp_path):
    app = _tree(tmp_path, {"SignupPage": _DELEGATING_PAGE}, {"Modal": _CALLING_CHILD})
    out = drift(_Hubs({"signup": {"component": "SignupPage",
                                  "apis_used": ["GET /api/me", "POST /auth/register"]}}), app)
    assert out == [], out


def test_the_unresolved_and_empty_case_still_needs_the_own_call(tmp_path):
    """★ With nothing resolved and nothing declared, the page's own call is the only
    evidence; a page that neither calls nor resolves must stay silent."""
    app = _tree(tmp_path,
                {"Quiet": "export default function Quiet() { return null; }\n",
                 "Loud": ("import { getMe } from '../services/api';\n"
                          "export default function Loud() { getMe(); return null; }\n")},
                {})
    assert drift(_Hubs({"q": {"component": "Quiet", "apis_used": []}}), app) == []
    assert drift(_Hubs({"l": {"component": "Loud", "apis_used": []}}), app)


def test_a_page_with_no_component_file_is_not_a_verdict(tmp_path):
    app = _tree(tmp_path, {"Real": "export default function Real() { return null; }\n"}, {})
    assert drift(_Hubs({"g": {"component": "Ghost", "apis_used": []}}), app) == []


def test_the_resolver_is_read_once_per_page():
    """Two calls would walk the same tree twice for the same answer (#1032)."""
    import ast
    import inspect
    import multi_agent.runtime.deliverability as D

    src = inspect.getsource(D._page_api_declaration_drift_1202rr)
    tree = ast.parse(src.lstrip())
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
             and getattr(n.func, "id", "") in ("page_api_endpoints_1202wd", "_r1202y4")]
    assert len(calls) == 1, "the resolver is called %d times per page" % len(calls)


def test_a_declaration_the_resolver_cannot_confirm_never_fires(tmp_path):
    """The hook blind spot, unchanged by this: `declared - source` must never fire."""
    src = tmp_path / "frontend" / "src"
    (src / "pages").mkdir(parents=True)
    (src / "hooks").mkdir()
    (src / "services").mkdir()
    (src / "services" / "api.js").write_text(_API, encoding="utf-8")
    (src / "hooks" / "useThing.js").write_text(
        "import { getMe } from '../services/api';\n"
        "export function useThing() { return getMe(); }\n", encoding="utf-8")
    (src / "pages" / "P.jsx").write_text(
        "import { useThing } from '../hooks/useThing';\n"
        "export default function P() { useThing(); return null; }\n", encoding="utf-8")
    assert drift(_Hubs({"p": {"component": "P", "apis_used": ["GET /api/me"]}}),
                 str(tmp_path)) == []
