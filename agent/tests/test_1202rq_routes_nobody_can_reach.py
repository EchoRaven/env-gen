r"""#1202rq: routes that exist and nothing can navigate to.

`deliverability_ui_page_unwired` asks whether a declared page got a route. Nothing asked the
other half — whether anything in the app can reach that route. tiktok-r131 wired 12 routes and
shipped ZERO navigation affordances: no <a>, no <Link>, no navigate() anywhere under src. Every
page existed and only the address bar could open it.

An unprimed agent doing an ordinary task hit exactly this and said so: "nothing in the app is a
real link — creator names and avatars are not clickable, which is why there's no path to a
profile." It had been asked to look up creators, and there was no way to reach one.

Only the ZERO case is flagged, and the corpus is why a threshold would be wrong: r129 carries
16 navigation sites, r130 carries 46, r131 carries 0. A page reachable from only one other page
is a design choice; an app where nothing at all is clickable was never wired together.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "env_generator" / "llm_generator")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from multi_agent.runtime.deliverability import _unreachable_routes_1202rq as gate  # noqa: E402

ROUTES = "".join('<Route path="/p%d" element={<P%d/>} />' % (i, i) for i in range(5))


def _app(tmp_path, app_jsx, extra=None):
    src = tmp_path / "app" / "frontend" / "src"
    src.mkdir(parents=True)
    (src / "App.jsx").write_text(app_jsx, encoding="utf-8")
    for rel, body in (extra or {}).items():
        f = src / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(body, encoding="utf-8")
    return tmp_path / "app"


def test_the_r131_shape_is_caught(tmp_path):
    out = gate(_app(tmp_path, ROUTES))
    assert out and "NO navigation affordance" in out[0]


def test_a_single_Link_anywhere_clears_it(tmp_path):
    """The zero case only — one real affordance means the app was wired."""
    assert gate(_app(tmp_path, ROUTES,
                     {"components/Nav.jsx": '<Link to="/p1">One</Link>'})) == []


def test_an_anchor_clears_it(tmp_path):
    assert gate(_app(tmp_path, ROUTES, {"components/Nav.jsx": '<a href="/p1">One</a>'})) == []


def test_useNavigate_clears_it(tmp_path):
    """A programmatic push is navigation too — an onClick router call is common and valid."""
    assert gate(_app(tmp_path, ROUTES,
                     {"pages/P.jsx": "const n = useNavigate(); n('/p1');"})) == []


def test_a_tiny_app_is_not_judged(tmp_path):
    """Two routes is too small to conclude the app was never wired."""
    assert gate(_app(tmp_path, '<Route path="/a" /><Route path="/b" />')) == []


def test_the_catch_all_and_root_do_not_count_as_routes(tmp_path):
    jsx = '<Route path="/" /><Route path="*" /><Route path="/x" />'
    assert gate(_app(tmp_path, jsx)) == []


def test_no_app_jsx_is_not_a_finding(tmp_path):
    (tmp_path / "app" / "frontend" / "src").mkdir(parents=True)
    assert gate(tmp_path / "app") == []


def test_it_can_be_switched_off(tmp_path, monkeypatch):
    monkeypatch.setenv("ENVGEN_ROUTE_REACHABILITY_GATE", "0")
    assert gate(_app(tmp_path, ROUTES)) == []


def test_the_gate_is_reachable_from_the_blocker_list():
    src = (ROOT / "env_generator" / "llm_generator" / "multi_agent" / "runtime"
           / "deliverability.py").read_text(encoding="utf-8")
    assert src.count("blockers.extend(_unreachable_routes_1202rq") == 1
