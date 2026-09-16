"""#1202pe: a projected page shows "Loading…" only when it actually fetches.

With no GET mapped to the screen, #426 emits an effect with no fetch; `setData` is never called,
rows stay [] forever and the page read "Loading…" for its whole life. 26 judged screens across 10
runs sat on such a page — mean 0.197, 2 of 26 at or above 0.55. tiktok-r126's
FollowingSuggestedCreatorsPage rendered its title and "Loading…", nothing else.

Driven through `_project_page_component`, the function the scaffold actually calls.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime import frontend_scaffold as FS  # noqa: E402


def _rail(role, y0, y1, cols=6):
    return {"id": role.replace(" ", "-"), "role": role,
            "region": [0.0, y0, 1.0, y1], "geometry": {"columns": cols, "rows": 1}}


def _design():
    """A screen shape known to reach the rail/grid branches that emit "Loading…"."""
    return {"design_system": {"palette": {"bg": "#141414", "accent": "#e50914"},
                              "theme": {"default": "dark"}},
            "screens": [{"name": "my_list", "route": "/my-list", "kind": "page",
                         "components": [_rail("poster row alpha", 0.24, 0.37),
                                        _rail("poster row beta", 0.40, 0.53),
                                        _rail("poster row gamma", 0.56, 0.69)]}]}


def _render(get_eps):
    return FS._project_page_component(
        "MyListPage", {"route": "/my-list", "name": "MyListPage"},
        [("Home", "/")], _design(), get_eps)


def test_r126_a_page_that_fetches_nothing_never_says_loading(monkeypatch):
    seen = {}
    real = FS._render_reference_page

    def _spy(name, page, screen, design, nav_routes, get_ep):
        seen["called"] = True
        out = real(name, page, screen, design, nav_routes, get_ep)
        seen["raw_had_loading"] = "Loading…" in out
        return out

    monkeypatch.setattr(FS, "_render_reference_page", _spy)
    src = _render({})
    assert seen.get("called"), "the reference renderer was not reached — fixture drifted"
    assert seen.get("raw_had_loading"), "the renderer no longer emits the line — test is vacuous"
    assert "Loading…" not in src


def test_the_helper_leaves_a_fetching_page_untouched():
    line = FS._LOADING_LINES_1202PE[0]
    page = "x\n" + line + "y\n"
    assert FS._without_loading_when_nothing_fetches_1202pe(page, "/api/creators") == page
    assert FS._without_loading_when_nothing_fetches_1202pe(page, "") == "x\ny\n"
