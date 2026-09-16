"""#1202pc: when several pages claim one reference image, the gate judges the one it is named for.

Nothing enforces one claim per image at registration, and 77 of 143 runs carry collisions (342
extra claims). `map_reference_screens` took the FIRST declaring page and stopped. tiktok-r126:
four pages claimed `explore_grid.png`; the gate judged `/videos` (VideosPage, 0.29) while
`/explore` (ExploreGridPage) was registered and wired.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime.visual_fidelity import map_reference_screens  # noqa: E402


def _route_for(tmp_path, pages, image="explore_grid.png"):
    ref = tmp_path / image
    ref.write_bytes(b"\x89PNG")            # the mapper skips a reference that is not a file
    screens = map_reference_screens([ref],
                                    known_routes={p["route"] for p in pages},
                                    classifications={}, ui_pages=pages)
    return [s["route"] for s in screens if s["name"] == Path(image).stem][0]


def test_r126_the_exactly_named_page_wins_a_contested_image(tmp_path):
    pages = [
        {"name": "VideosPage", "route": "/videos", "reference_image": "explore_grid.png"},
        {"name": "SoundsPage", "route": "/sounds", "reference_image": "explore_grid.png"},
        {"name": "ExploreGridPage", "route": "/explore", "reference_image": "explore_grid.png"},
        {"name": "LiveStreamsPage", "route": "/live", "reference_image": "explore_grid.png"},
    ]
    assert _route_for(tmp_path, pages) == "/explore"


def test_a_single_claim_is_bound_exactly_as_before(tmp_path):
    pages = [{"name": "VideosPage", "route": "/videos", "reference_image": "explore_grid.png"},
             {"name": "ExploreGridPage", "route": "/explore"}]
    assert _route_for(tmp_path, pages) == "/videos"      # the declaration still outranks the name guess
