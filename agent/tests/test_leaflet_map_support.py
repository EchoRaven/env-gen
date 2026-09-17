"""F3 — Leaflet + OSM interactive-map support for a Google Maps clone.

The clone's primary surface is a real pan/zoom map. Three pieces:
1. The external-image localizer (#75b/#111) must NOT rewrite a Leaflet XYZ tile URL
   (https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png ends in .png → today it's
   localized to a placeholder → the map is DOA). Exempt map-tile URLs.
2. leaflet + react-leaflet get reproducible pins in _COMMON_FRONTEND_LIBS (else the
   bare-import auto-adder pins them to "latest").
3. The frontend prompt carries a concrete <map_surface_template> so the lane builds a
   real MapContainer + TileLayer + Markers (with the default-marker-icon fix).
LOCAL-ONLY (agent/tests/ gitignored).
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime.frontend_scaffold import (  # noqa: E402
    localize_frontend_external_images, _COMMON_FRONTEND_LIBS)

TILE_URL = "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"


def _mk_fe(tmp_path, jsx):
    fe = tmp_path / "app" / "frontend"
    (fe / "src").mkdir(parents=True)
    (fe / "public").mkdir(parents=True)
    (fe / "src" / "MapPage.jsx").write_text(jsx)
    return fe


def test_leaflet_tile_url_is_not_localized(tmp_path):
    jsx = (
        "import { MapContainer, TileLayer } from 'react-leaflet';\n"
        "export default () => (<MapContainer center={[37.77,-122.42]} zoom={13}>"
        f"<TileLayer url=\"{TILE_URL}\" /></MapContainer>);\n")
    fe = _mk_fe(tmp_path, jsx)
    localize_frontend_external_images(fe)
    out = (fe / "src" / "MapPage.jsx").read_text()
    assert TILE_URL in out, "the OSM tile URL must survive — the map depends on live tiles"
    assert "/assets/" not in out, "the tile template must NOT be placeholder-localized"


def test_stock_photo_is_not_replaced_by_a_placeholder(tmp_path):
    """#1202qo: an unmatched stock photo stays as it is - no generated glyph hides it."""
    jsx = "export default () => <img src=\"https://images.unsplash.com/photo-123.jpg\" />;\n"
    fe = _mk_fe(tmp_path, jsx)
    localize_frontend_external_images(fe)
    out = (fe / "src" / "MapPage.jsx").read_text()
    assert "images.unsplash.com/photo-123.jpg" in out and "/assets/placeholders" not in out


def test_other_tile_hosts_and_templates_exempt(tmp_path):
    for i, url in enumerate((
            "https://tile.openstreetmap.org/10/163/395.png",
            "https://a.basemaps.cartocdn.com/light_all/{z}/{x}/{y}.png",
            "https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png")):
        jsx = f"const u = '{url}';\n"
        fe = _mk_fe(tmp_path / f"case{i}", jsx)
        localize_frontend_external_images(fe)
        out = (fe / "src" / "MapPage.jsx").read_text()
        assert url in out, f"map tile URL must be exempt: {url}"


def test_leaflet_deps_pinned():
    assert _COMMON_FRONTEND_LIBS.get("leaflet"), "leaflet needs a reproducible pin"
    assert _COMMON_FRONTEND_LIBS.get("react-leaflet"), "react-leaflet needs a reproducible pin"


def test_map_template_in_frontend_prompt():
    j2 = (LLM / "multi_agent" / "prompts" / "v3" / "frontend_agent.j2").read_text()
    assert "map_surface_template" in j2, "the frontend prompt must carry the Leaflet map pattern"
    assert "react-leaflet" in j2 and "TileLayer" in j2
    assert "tile.openstreetmap.org" in j2, "the template must name the OSM tile URL"
    # the notorious invisible-marker fix must be mentioned
    assert "L.Icon.Default" in j2 or "divIcon" in j2


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
