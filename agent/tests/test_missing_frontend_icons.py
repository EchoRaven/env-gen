"""FIX #169 — stage the icons the FRONTEND references but that were never staged (gmrun7).

gmrun7 referenced 56 local assets in its JSX; 8 were MISSING (404): a bookmark_border,
directions_transit, local_atm, terrain, logout, smartphone, local_activity icon, and the
Layers thumbnail placeholders/ph-map-thumb.svg. The lane referenced Material-Symbol icons
beyond the 63 the design-input staged → broken/blank icons all over the UI ("很多小图标有
问题"). #168 covers SEED photo_url; this covers FRONTEND-referenced icons/placeholders.
Fetch the real Material Symbol by name (best-effort, egress like the design-input prep),
falling back to a neutral placeholder SVG so an icon ALWAYS resolves. LOCAL-ONLY.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import pytest  # noqa: E402

from multi_agent.runtime import frontend_scaffold as fs  # noqa: E402
from multi_agent.runtime.frontend_scaffold import stage_missing_frontend_assets  # noqa: E402


def _fe(tmp_path, files, staged_icons=()):
    root = tmp_path / "app" / "frontend"
    src = root / "src"
    src.mkdir(parents=True, exist_ok=True)
    (root / "public" / "assets" / "icons").mkdir(parents=True, exist_ok=True)
    (root / "public" / "assets" / "placeholders").mkdir(parents=True, exist_ok=True)
    for rel, txt in files.items():
        p = src / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(txt)
    for ic in staged_icons:
        (root / "public" / "assets" / "icons" / ic).write_text("<svg/>")
    return tmp_path


def _pub(tmp_path):
    return tmp_path / "app" / "frontend" / "public" / "assets"


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    # default: the fetch FAILS, so tests exercise the placeholder fallback deterministically
    monkeypatch.setattr(fs, "_fetch_material_symbol", lambda name: None)


def test_missing_icon_gets_placeholder(tmp_path):
    _fe(tmp_path, {"HomeMap.jsx":
                   'const a = "/assets/icons/bookmark_border_24.svg";\n'
                   '<img src="/assets/icons/terrain_24.svg"/>'})
    staged = stage_missing_frontend_assets(tmp_path)
    assert set(staged) == {"icons/bookmark_border_24.svg", "icons/terrain_24.svg"}
    p = _pub(tmp_path) / "icons" / "terrain_24.svg"
    assert p.exists()
    body = p.read_text()
    assert body.lstrip().startswith("<svg") and "</svg>" in body  # a valid SVG, not broken


def test_missing_placeholder_thumb_generated(tmp_path):
    _fe(tmp_path, {"HomeMap.jsx": '<img src="/assets/placeholders/ph-map-thumb.svg"/>'})
    staged = stage_missing_frontend_assets(tmp_path)
    assert "placeholders/ph-map-thumb.svg" in staged
    assert (_pub(tmp_path) / "placeholders" / "ph-map-thumb.svg").exists()


def test_existing_icon_not_overwritten(tmp_path):
    _fe(tmp_path, {"H.jsx": '<img src="/assets/icons/map_24.svg"/>'},
        staged_icons=["map_24.svg"])
    (_pub(tmp_path) / "icons" / "map_24.svg").write_text("<svg>REAL</svg>")
    staged = stage_missing_frontend_assets(tmp_path)
    assert "icons/map_24.svg" not in staged
    assert "REAL" in (_pub(tmp_path) / "icons" / "map_24.svg").read_text()


def test_real_material_symbol_fetched_when_available(tmp_path, monkeypatch):
    real = ('<svg xmlns="http://www.w3.org/2000/svg" height="24" viewBox="0 -960 960 960" '
            'width="24"><path d="M200-120v-640"/></svg>')
    monkeypatch.setattr(fs, "_fetch_material_symbol",
                        lambda name: real if name == "bookmark_border" else None)
    _fe(tmp_path, {"H.jsx": '<img src="/assets/icons/bookmark_border_24.svg"/>'})
    stage_missing_frontend_assets(tmp_path)
    got = (_pub(tmp_path) / "icons" / "bookmark_border_24.svg").read_text()
    assert "M200-960" not in got  # sanity: it's the fetched body
    assert got == real  # the REAL Material Symbol, not the placeholder


def test_symbol_name_strips_size_suffix(tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr(fs, "_fetch_material_symbol",
                        lambda name: (seen.append(name), None)[1])
    _fe(tmp_path, {"H.jsx": '<img src="/assets/icons/directions_transit_24.svg"/>'})
    stage_missing_frontend_assets(tmp_path)
    assert "directions_transit" in seen  # queried WITHOUT the _24 size suffix


def test_no_refs_empty(tmp_path):
    _fe(tmp_path, {"H.jsx": 'export default function H(){ return <div/>; }'})
    assert stage_missing_frontend_assets(tmp_path) == []


def test_any_assets_dir_is_backstopped_707(tmp_path):
    """#707 widened the scope from icons|placeholders to ANY /assets/<dir>/.

    The old rule ("photos are #168's job") could not see the directory that
    actually breaks: measured over the delivered corpus, 20 broken local image
    references across 8 of 27 released runs, 19 of them `/assets/avatars/…` — a
    profile picker needing avatars that were never in assets[], each run inventing
    its own naming. "The directory the lane invents is precisely the one nobody
    staged."

    The worry behind the old test — a placeholder hiding a seeding bug behind a
    grey square — is answered by #707 logging every placeholder it writes, and by
    this being the LAST rung of the ladder in frontend_agent.j2 rule 5b."""
    _fe(tmp_path, {"H.jsx": '<img src="/assets/photos/x.jpg"/>'})
    assert stage_missing_frontend_assets(tmp_path) == ["photos/x.jpg"]
