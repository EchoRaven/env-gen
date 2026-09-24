r"""#1202f: #1195 merges by shared source file — only when the records agree about the page.

#1195 folds a ROUTE-LESS `register_ui_page` into an existing record with the same `path`,
because a route-less registration of a component file that is already registered is the same
page named twice. Swept across all 114 generated environments to check that outside netflix:

    environments where a merge would happen      58  (netflix 20, tiktok 20,
                                                      instagram 14, googlemaps 3, smoke 1)
    merge pairs                                 189
    pairs whose `component` disagrees             0
    pairs whose `apis_used` conflicts             0

So the merge is safe in the corpus, and widespread enough to matter. This adds the guard that
makes it safe by CONSTRUCTION rather than by observation: sharing a file is evidence the two
records are the same page, but a different component name — or a different declared API
surface — says they are not, and folding one into the other would drop a registration the
projector still needs.

Changes nothing that happens today (189 of 189 agree). That is the point: a fact about the
corpus is not a guarantee about the next run.
"""

import sys
import tempfile
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS_DIR.parent / "env_generator" / "llm_generator"))

from multi_agent.runtime.registryhub import RegistryHub  # noqa: E402


def _hub():
    return RegistryHub(Path(tempfile.mkdtemp()))


def test_the_same_page_named_twice_still_merges():
    hub = _hub()
    hub.register_ui_page(name="landing", route="/", path="src/pages/Landing.jsx",
                         component="LandingPage", apis_used=["GET /api/x"],
                         components=[], actor="lane")
    hub.register_ui_page(name="landing_page", route="", path="src/pages/Landing.jsx",
                         component="LandingPage", components=[], actor="lane")
    pages = hub.list_ui_pages()
    assert list(pages) == ["landing"]
    assert "landing_page" in (pages["landing"].get("metadata") or {}).get(
        "merged_route_aliases", [])


def test_a_different_component_on_the_same_file_does_not_merge():
    hub = _hub()
    hub.register_ui_page(name="a", route="/a", path="src/pages/Shared.jsx",
                         component="AlphaPage", components=[], actor="lane")
    hub.register_ui_page(name="b", route="", path="src/pages/Shared.jsx",
                         component="BetaPage", components=[], actor="lane")
    assert sorted(hub.list_ui_pages()) == ["a", "b"]


def test_a_conflicting_api_surface_does_not_merge():
    hub = _hub()
    hub.register_ui_page(name="a", route="/a", path="src/pages/Shared.jsx",
                         apis_used=["GET /api/one"], components=[], actor="lane")
    hub.register_ui_page(name="b", route="", path="src/pages/Shared.jsx",
                         apis_used=["GET /api/two"], components=[], actor="lane")
    assert sorted(hub.list_ui_pages()) == ["a", "b"]


def test_a_missing_component_on_either_side_still_merges():
    """The corpus is full of records that simply do not carry `component`; absence is not
    disagreement."""
    hub = _hub()
    hub.register_ui_page(name="a", route="/a", path="src/pages/Shared.jsx",
                         components=[], actor="lane")
    hub.register_ui_page(name="b", route="", path="src/pages/Shared.jsx",
                         component="SharedPage", components=[], actor="lane")
    assert list(hub.list_ui_pages()) == ["a"]
