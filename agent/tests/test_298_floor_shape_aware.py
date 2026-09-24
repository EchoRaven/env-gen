"""#298 (Chunk B) — the measured no-reference floor picks a layout by data shape:
grid / detail / list. All keep the #297 invariants (structured, measured, built)."""
import sys
from pathlib import Path
THIS = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS.parent / "env_generator" / "llm_generator"))
from multi_agent.runtime.frontend_scaffold import _project_page_component, _floor_shape  # noqa: E402
from multi_agent.runtime.frontend_audit import _is_generic_fallback_page  # noqa: E402
from multi_agent.runtime.frontend_page_projector import _STRUCTURED_MARKER  # noqa: E402

_DESIGN = {"design_system": {"theme": {"default": "dark"}, "palette": {
    "bg": "#000000", "surface": "#121212", "text": "#ffffff",
    "text_2": "rgba(255,255,255,0.75)", "accent_red": "#EA445A", "border": "#2a2a2a"}}}


# ---- _floor_shape unit table --------------------------------------------------
def test_floor_shape_detail_on_path_param():
    assert _floor_shape({"route": "/v/x", "name": "video"}, "/api/videos/{id}", "VideoPage") == "detail"


def test_floor_shape_grid_on_gallery_keyword():
    assert _floor_shape({"route": "/explore", "name": "explore"}, "/api/explore", "ExplorePage") == "grid"


def test_floor_shape_list_default():
    assert _floor_shape({"route": "/messages", "name": "messages"}, "/api/messages", "MessagesPage") == "list"


def test_floor_shape_detail_wins_over_grid_keyword():
    # a single-resource gallery endpoint is a detail page
    assert _floor_shape({"route": "/g/x", "name": "gallery"}, "/api/gallery/{id}", "GalleryItemPage") == "detail"


# ---- integration: each shape renders + stays structured/measured/built --------
def _mk(page):
    return _project_page_component(page["component"], page, nav_routes=[("H", "/")], design=_DESIGN)


def test_grid_page_renders_grid():
    out = _mk({"route": "/explore", "component": "ExplorePage",
               "apis_used": ["GET /api/explore"], "name": "explore"})
    assert "grid-cols" in out                         # responsive grid, not a row list
    assert 'data-projected="ref"' in out and _STRUCTURED_MARKER in out
    assert "backgroundColor: '#000000'" in out
    assert 'data-fallback="1"' not in out
    assert "/api/explore" in out
    assert not _is_generic_fallback_page(out)


def test_detail_page_renders_single_item():
    out = _mk({"route": "/videos/:id", "component": "VideoDetailPage",
               "apis_used": ["GET /api/videos/{id}"], "name": "video_detail"})
    assert "grid-cols" not in out                     # not a grid
    assert "rows.map" not in out                      # single item, not a list
    assert 'data-projected="ref"' in out and _STRUCTURED_MARKER in out
    assert "backgroundColor: '#000000'" in out
    assert not _is_generic_fallback_page(out)


def test_list_page_renders_row_list():
    out = _mk({"route": "/messages", "component": "MessagesPage",
               "apis_used": ["GET /api/messages"], "name": "messages"})
    assert "grid-cols" not in out
    assert "rows.map" in out                           # row list
    assert 'data-projected="ref"' in out and _STRUCTURED_MARKER in out
    assert not _is_generic_fallback_page(out)


def test_no_palette_still_data_fallback():
    out = _project_page_component("ExplorePage",
            {"route": "/explore", "component": "ExplorePage",
             "apis_used": ["GET /api/explore"], "name": "explore"},
            nav_routes=[], design={})
    assert 'data-fallback="1"' in out
    assert _is_generic_fallback_page(out)
