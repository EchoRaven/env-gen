"""FIX #111 — localize EXTERNAL image URLs (JSX <img src> + seed rows) to staged assets
(runs 24+26 visual autopsy, 2026-07-08).

The sandbox is OFFLINE: an external image host (i.pravatar.cc, images.unsplash.com,
via.placeholder.com — all seen in live artifacts) can NEVER resolve, so every such
<img> renders the broken-image glyph. #75b already neutralizes external CSS
*backgrounds*; this covers the other two carriers:
  (a) frontend source: <img src="https://…">, poster=, and image-ish object props
      (avatar_url: 'https://…'),
  (b) seed_data.json rows whose image-ish string fields carry external URLs — the DB
      rows render as <img src> at runtime and break identically.
Rewrite to a staged real asset under frontend/public/assets/ when a token match exists
(design-prep ingest_assets stages them), else (#1202qo) the URL is left as it is: a generated placeholder hid missing imagery.
Non-image externals (API bases, issuer URLs, <a href> navigation) are NEVER touched.
ENV-AGNOSTIC + LOCAL-ONLY (agent/tests/ gitignored).
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime.frontend_scaffold import (  # noqa: E402
    localize_frontend_external_images, localize_seed_external_images)


def _mk_fe(tmp_path, files=None, assets=None):
    fe = tmp_path / "frontend"
    (fe / "src").mkdir(parents=True)
    (fe / "public" / "assets").mkdir(parents=True)
    for rel, txt in (files or {}).items():
        p = fe / "src" / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(txt, encoding="utf-8")
    for rel in (assets or []):
        p = fe / "public" / "assets" / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"\x89PNG fake")
    return fe


def test_img_src_external_without_a_staged_match_is_left_alone(tmp_path):
    """#1202qo: no generated placeholder; an image nobody staged stays visibly broken."""
    body = 'export default () => <img src="https://i.pravatar.cc/150?img=3" alt="avatar" />;'
    fe = _mk_fe(tmp_path, files={"Feed.jsx": body})
    out = localize_frontend_external_images(fe)
    assert (fe / "src" / "Feed.jsx").read_text(encoding="utf-8") == body
    assert not out.get("localized")
    assert not (fe / "public" / "assets" / "placeholders").exists()

def test_imageish_prop_without_extension_is_matched_by_field_name(tmp_path):
    # unsplash URLs carry NO file extension — the field-name signal must still find a staged asset
    fe = _mk_fe(tmp_path, files={"data.js": (
        "export const user = { avatar_url: 'https://images.unsplash.com/photo-15060?...',"
        " website: 'https://example.com/docs' };")}, assets=["avatar_main_1.png"])
    localize_frontend_external_images(fe)
    src = (fe / "src" / "data.js").read_text(encoding="utf-8")
    assert "https://example.com/docs" in src          # non-image field untouched

def test_href_navigation_and_api_base_untouched(tmp_path):
    body = ('const a = <a href="https://instagram.com/about">about</a>;\n'
            'const base = "https://api.example.com/v1";\n')
    fe = _mk_fe(tmp_path, files={"Nav.jsx": body})
    out = localize_frontend_external_images(fe)
    assert (fe / "src" / "Nav.jsx").read_text(encoding="utf-8") == body
    assert not out.get("localized")


def test_staged_asset_token_match_preferred(tmp_path):
    fe = _mk_fe(tmp_path,
                files={"P.jsx": '<img src="https://cdn.example.com/logo_main.png" />'},
                assets=["logo_header_ab12cd34.png"])
    localize_frontend_external_images(fe)
    src = (fe / "src" / "P.jsx").read_text(encoding="utf-8")
    assert "/assets/logo_header_ab12cd34.png" in src   # token 'logo' matched a real asset


def test_no_placeholder_file_is_ever_generated(tmp_path):
    f = ('<img src="https://via.placeholder.com/300x200" />\n'
         '<img src="https://via.placeholder.com/300x200" />\n')
    fe = _mk_fe(tmp_path, files={"A.jsx": f})
    out = localize_frontend_external_images(fe)
    assert (fe / "src" / "A.jsx").read_text(encoding="utf-8") == f
    assert not (fe / "public" / "assets" / "placeholders").exists()
    assert out.get("unmatched", 0) >= 2 or not out.get("localized")

def test_template_literal_without_a_staged_match_is_left_alone(tmp_path):
    body = "<img src={`https://i.pravatar.cc/150?u=${post?.user_id || '1'}`} alt=\"Avatar\" />"
    fe = _mk_fe(tmp_path, files={"R.jsx": body})
    localize_frontend_external_images(fe)
    assert (fe / "src" / "R.jsx").read_text(encoding="utf-8") == body

def test_jsx_expression_fallback_string_without_match_is_left_alone(tmp_path):
    body = "<img src={post?.image_url || 'https://picsum.photos/400/700'} />"
    fe = _mk_fe(tmp_path, files={"V.jsx": body})
    localize_frontend_external_images(fe)
    assert (fe / "src" / "V.jsx").read_text(encoding="utf-8") == body

def test_nonimage_template_and_nested_backtick_untouched(tmp_path):
    body = ("const u = `https://api.example.com/v1/${id}`;\n"
            "const w = `https://i.pravatar.cc/${a ? `x` : `y`}`;\n")
    fe = _mk_fe(tmp_path, files={"T.js": body})
    localize_frontend_external_images(fe)
    assert (fe / "src" / "T.js").read_text(encoding="utf-8") == body


def test_seed_imageish_fields_matched_or_kept(tmp_path):
    fe = _mk_fe(tmp_path, assets=["avatar_alice.png"])
    be = tmp_path / "backend"
    be.mkdir()
    seed = {"users": [{"username": "alice",
                       "avatar_url": "https://i.pravatar.cc/150/avatar_alice.png",
                       "website": "https://alice.dev"}],
            "posts": [{"caption": "hi",
                       "image_url": "https://images.unsplash.com/photo-99"}],
            "oauth": {"issuer": "https://localhost:3001"}}
    (be / "seed_data.json").write_text(json.dumps(seed), encoding="utf-8")
    localize_seed_external_images(be, fe)
    d = json.loads((be / "seed_data.json").read_text(encoding="utf-8"))
    assert d["users"][0]["avatar_url"] == "/assets/avatar_alice.png"   # a real staged match
    assert d["posts"][0]["image_url"] == "https://images.unsplash.com/photo-99"  # no match: kept
    assert d["users"][0]["website"] == "https://alice.dev"
    assert d["oauth"]["issuer"] == "https://localhost:3001"

def test_graceful_and_idempotent(tmp_path):
    fe = _mk_fe(tmp_path, files={"B.jsx": '<img src="https://cdn.example.com/logo_main.png" />'},
                assets=["logo_header_ab12cd34.png"])
    assert localize_frontend_external_images(fe).get("localized")
    again = localize_frontend_external_images(fe)
    assert not again.get("localized")                  # nothing external left
    # missing dirs never raise
    assert isinstance(localize_frontend_external_images(tmp_path / "nope"), dict)
    assert isinstance(localize_seed_external_images(tmp_path / "nope", tmp_path / "n2"), dict)

def test_wired_into_heal_pipeline():
    import inspect
    from multi_agent.runtime import heal_pipeline
    src = inspect.getsource(heal_pipeline)
    assert "localize_frontend_external_images" in src
    assert "localize_seed_external_images" in src
