r"""#1202rr: a page whose source calls an API and whose registration says it calls none.

#1202rm catches the all-empty case, where every page declares nothing and every check built on
`apis_used` switches off together. It is blind to the partial one: a page whose own file plainly
contains `api.get(...)` while its registration carries `apis_used: []`. Everything downstream
then reasons from a registry that contradicts the code — #151 skips the page for having no
`apis`, the consumer-wiring audit has nothing to reconcile for it, and its implemented-flip
stops asking whether its endpoints are referenced.

Found by checking that today's gates were not tiktok-shaped. Running them across other domains
turned up googlemaps gmrun4 — a SUCCESSFUL four-milestone delivery — with 4 pages registered as
using no APIs and 2 of them calling one: login_page and signup_page, which of course call the
API. That run passed every gate that existed.

The reverse direction is deliberately NOT flagged. A lane may register the contract it is about
to consume, and Phase A does exactly that; only code-says-yes / registry-says-no destroys
information the rest of the framework reads.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "env_generator" / "llm_generator")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from multi_agent.runtime import deliverability as D  # noqa: E402


class _RH:
    def __init__(self, pages):
        self._p = pages

    def list_ui_pages(self):
        return self._p


class _Hubs:
    def __init__(self, pages):
        self.registryhub = _RH(pages)


def _app(tmp_path, files):
    src = tmp_path / "frontend" / "src"
    for rel, body in files.items():
        f = src / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(body, encoding="utf-8")
    return tmp_path


def test_the_gmrun4_shape_is_caught(tmp_path):
    app = _app(tmp_path, {"pages/LoginPage.jsx":
                          "const r = await api.post('/auth/login', body);"})
    pages = {"login_page": {"component": "LoginPage", "apis_used": []}}
    out = D._page_api_declaration_drift_1202rr(_Hubs(pages), app)
    assert out and "login_page" in out[0]


def test_a_declared_page_is_not_flagged(tmp_path):
    app = _app(tmp_path, {"pages/LoginPage.jsx": "await api.post('/auth/login', b);"})
    pages = {"login_page": {"component": "LoginPage", "apis_used": ["POST /auth/login"]}}
    assert D._page_api_declaration_drift_1202rr(_Hubs(pages), app) == []


def test_a_genuinely_static_page_is_not_flagged(tmp_path):
    """Empty is correct for a page that reads no data; only the contradiction is a finding."""
    app = _app(tmp_path, {"pages/AboutPage.jsx": "export default () => <p>About us</p>;"})
    pages = {"about": {"component": "AboutPage", "apis_used": []}}
    assert D._page_api_declaration_drift_1202rr(_Hubs(pages), app) == []


def test_the_reverse_direction_is_deliberately_ignored(tmp_path):
    """Phase A registers the contract it is about to consume; flagging that would fight the
    normal flow."""
    app = _app(tmp_path, {"pages/FeedPage.jsx": "export default () => <ul/>;"})
    pages = {"feed": {"component": "FeedPage", "apis_used": ["GET /api/videos"]}}
    assert D._page_api_declaration_drift_1202rr(_Hubs(pages), app) == []


def test_components_are_searched_when_the_page_file_is_absent(tmp_path):
    app = _app(tmp_path, {"components/Widget.jsx": "fetch('/api/x')"})
    pages = {"w": {"component": "Widget", "apis_used": []}}
    assert D._page_api_declaration_drift_1202rr(_Hubs(pages), app)


def test_fetch_and_axios_both_count(tmp_path):
    for body in ("fetch('/api/x')", "await axios.get('/api/x')", "apiGet('/api/x')"):
        app = _app(tmp_path / body[:5], {"pages/P.jsx": body})
        pages = {"p": {"component": "P", "apis_used": []}}
        assert D._page_api_declaration_drift_1202rr(_Hubs(pages), app), body


def test_a_missing_component_file_is_not_a_verdict(tmp_path):
    app = _app(tmp_path, {"pages/Other.jsx": "fetch('/api/x')"})
    pages = {"p": {"component": "Ghost", "apis_used": []}}
    assert D._page_api_declaration_drift_1202rr(_Hubs(pages), app) == []


def test_it_names_no_product_vocabulary():
    """Domain-agnostic: it compares a page's source against its own registration."""
    src = (ROOT / "env_generator" / "llm_generator" / "multi_agent" / "runtime"
           / "deliverability.py").read_text(encoding="utf-8")
    i = src.index("def _page_api_declaration_drift_1202rr")
    body = src[i:src.index("def _no_page_declares_an_api_1202rm", i)]
    for word in ("tiktok", "video", "netflix", "maps", "instagram", "follower"):
        assert word not in body.lower().replace("googlemaps gmrun4", "")


def test_it_can_be_switched_off(tmp_path, monkeypatch):
    monkeypatch.setenv("ENVGEN_PAGE_API_DRIFT_GATE", "0")
    app = _app(tmp_path, {"pages/P.jsx": "fetch('/api/x')"})
    assert D._page_api_declaration_drift_1202rr(_Hubs({"p": {"component": "P",
                                                            "apis_used": []}}), app) == []


def test_the_gate_is_reachable_from_the_blocker_list():
    src = (ROOT / "env_generator" / "llm_generator" / "multi_agent" / "runtime"
           / "deliverability.py").read_text(encoding="utf-8")
    assert src.count("blockers.extend(_page_api_declaration_drift_1202rr") == 1
