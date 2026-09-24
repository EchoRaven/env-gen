"""FIX #166 — a declared MAP page must render a REAL map library, not a fake <div> (gmrun7).

gmrun7 shipped a Google-Maps clone whose home_map "map" was a blank white
``<div className="bg-[#ffffff]">`` — the frontend never imported leaflet/react-leaflet
(not in package.json, not in any source), so the dominant visual element of the app was a
decorative background. The prompt's <map_surface_template> (a full Leaflet pattern) was
IGNORED — prompt rules alone don't guarantee it, so a GATE must. When a declared ui_page is
a MAP surface (name/route says "map") but NO frontend file uses a map library, block delivery
so the lane builds the real Leaflet map. Egress-robust: a static source check, not a tile
probe (tiles need internet the sandbox lacks). LOCAL-ONLY (agent/tests/ gitignored).
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime.frontend_audit import (  # noqa: E402
    _is_map_page, _frontend_uses_map_lib, ui_page_delivery_blockers)


class _WH:
    def __init__(self, pages):
        self._pages = pages

    def get_ui_pages(self):
        return self._pages

    def get_ui_components(self):
        return {}


def _fe(tmp_path, files):
    fe = tmp_path / "app" / "frontend" / "src"
    for rel, txt in files.items():
        p = fe / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(txt)
    return fe


# ------------------------------ _is_map_page ------------------------------

def test_map_page_detected_by_name_and_route():
    assert _is_map_page("home_map", {"route": "/", "name": "home_map"})
    assert _is_map_page("x", {"route": "/map", "name": "x"})
    assert _is_map_page("explore", {"route": "/", "must_have": ["interactive map", "pins"]})


def test_non_map_page_not_detected():
    assert not _is_map_page("search_results", {"route": "/search"})
    assert not _is_map_page("profile", {"route": "/profile/:id"})
    # 'sitemap' / 'roadmap' contain "map" as a substring but are NOT geo maps
    assert not _is_map_page("sitemap", {"route": "/sitemap"})
    assert not _is_map_page("roadmap", {"route": "/roadmap"})


# --------------------------- _frontend_uses_map_lib ---------------------------

def test_detects_real_leaflet(tmp_path):
    fe = _fe(tmp_path, {"pages/HomeMap.jsx":
                        "import { MapContainer, TileLayer } from 'react-leaflet';\n"
                        "export default function HomeMap(){ return <MapContainer/>; }"})
    assert _frontend_uses_map_lib(fe) is True


def test_fake_map_div_has_no_map_lib(tmp_path):
    # the exact gmrun7 shape
    fe = _fe(tmp_path, {"pages/HomeMap.jsx":
                        "export default function HomeMap(){\n"
                        "  return <div className=\"bg-[#ffffff] w-full h-screen\"/>; }"})
    assert _frontend_uses_map_lib(fe) is False


def test_other_map_libs_accepted(tmp_path):
    for imp in ("import mapboxgl from 'mapbox-gl';",
                "import maplibregl from 'maplibre-gl';",
                "const map = new google.maps.Map(el);"):
        fe = _fe(tmp_path / imp[:8].replace(" ", "_").replace("'", ""), {"M.jsx": imp})
        assert _frontend_uses_map_lib(fe) is True, imp


# --------------------------- delivery-gate integration ---------------------------

def test_map_page_without_map_lib_blocks(tmp_path):
    fe = _fe(tmp_path, {"App.jsx": 'import HomeMap from "./pages/HomeMap";\n'
                        '<Route path="/" element={<HomeMap/>} />',
                        "pages/HomeMap.jsx":
                        "export default function HomeMap(){ return <div className=\"bg-white h-screen\"/>; }"})
    wh = _WH({"home_map": {"route": "/", "name": "home_map",
                           "component": "HomeMap", "must_have": ["map"]}})
    blockers = ui_page_delivery_blockers(fe, wh)
    assert any("map" in b.lower() and ("no map library" in b.lower()
               or "fake" in b.lower() or "real leaflet" in b.lower()) for b in blockers), blockers


def test_map_page_with_leaflet_no_block(tmp_path):
    fe = _fe(tmp_path, {"App.jsx": 'import HomeMap from "./pages/HomeMap";\n'
                        '<Route path="/" element={<HomeMap/>} />',
                        "pages/HomeMap.jsx":
                        "import { MapContainer, TileLayer, Marker } from 'react-leaflet';\n"
                        "import 'leaflet/dist/leaflet.css';\n"
                        "export default function HomeMap(){\n"
                        "  return <MapContainer center={[37.7,-122.4]} zoom={12} className=\"h-screen\">\n"
                        "    <TileLayer url='https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png'/>\n"
                        "  </MapContainer>; }"})
    wh = _WH({"home_map": {"route": "/", "name": "home_map", "component": "HomeMap"}})
    blockers = ui_page_delivery_blockers(fe, wh)
    assert not any("map library" in b.lower() or "fake" in b.lower() for b in blockers), blockers


def test_no_map_page_no_map_block(tmp_path):
    # an app with no map page must never get a map blocker even without a map lib
    fe = _fe(tmp_path, {"App.jsx": 'import S from "./pages/S";\n'
                        '<Route path="/search" element={<S/>} />',
                        "pages/S.jsx":
                        "import {api} from '../services/api';\n"
                        "export default function S(){ const [r,setR]=useState([]);\n"
                        "  useEffect(()=>{api.get('/api/x').then(setR)},[]);\n"
                        "  return <ul>{r.map(x=><li key={x.id}>{x.name}</li>)}</ul>; }"})
    wh = _WH({"search": {"route": "/search", "name": "search_results", "component": "S",
                         "apis_used": ["GET /api/x"]}})
    blockers = ui_page_delivery_blockers(fe, wh)
    assert not any("map library" in b.lower() or "fake map" in b.lower() for b in blockers), blockers
