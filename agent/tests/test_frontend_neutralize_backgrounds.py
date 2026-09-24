"""FIX #75b — neutralize EXTERNAL stock-photo backgrounds on content/authed pages
(outlook run-62: OutlookInboxPage renders a full-bleed Unsplash mountain in the reading pane).

Adversarial-review-hardened: the token is case-sensitive lowercase ``url(`` with a
``(?<![\\w$.])`` lookbehind so it can NEVER corrupt ``new URL("http…")`` / ``avatarUrl("http…")``
(which would break the Vite build → no delivery), only a url() in a background CONTEXT is
rewritten, and the scan covers .css/.scss (the lane often factors the bg into a shared class).
LOCAL-ONLY (agent/tests/ gitignored).
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import multi_agent.runtime.frontend_scaffold as fs  # noqa: E402


def _mk(tmp_path, rel, content):
    p = tmp_path / "src" / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return p


# ── the BLOCKER the adversarial review caught: never corrupt a URL() constructor / *Url() ──
def test_does_not_corrupt_url_constructor_or_url_helpers(tmp_path):
    src = (
        'const u = new URL("https://api.example.com/v2");\n'
        'const a = avatarUrl("https://cdn.example.com/a.png");\n'
        'const b = buildImageUrl("//cdn/x.png");\n'
        'export default function InboxPage(){ return <img src={u.href} />; }\n')
    p = _mk(tmp_path, "pages/InboxPage.jsx", src)
    out = fs.neutralize_frontend_external_backgrounds(tmp_path)
    after = p.read_text(encoding="utf-8")
    assert after == src, "no CSS background here → file must be byte-identical"
    assert 'new URL("https://api.example.com/v2")' in after
    assert 'avatarUrl("https://cdn.example.com/a.png")' in after
    assert out["neutralized"] == []


def test_neutralizes_inline_background_on_content_page(tmp_path):
    src = (
        'export default function OutlookInboxPage(){\n'
        '  return <div style={{ backgroundColor: "#203651", backgroundImage: '
        '\'url("https://images.unsplash.com/photo-1464822759023")\' }} />;\n}\n')
    p = _mk(tmp_path, "pages/OutlookInboxPage.jsx", src)
    out = fs.neutralize_frontend_external_backgrounds(tmp_path)
    after = p.read_text(encoding="utf-8")
    assert "images.unsplash.com" not in after
    assert "linear-gradient(160deg, #203651" in after  # sampled the reading-pane surface
    assert "pages/OutlookInboxPage.jsx" in out["neutralized"]


def test_preserves_landing_hero(tmp_path):
    src = (
        'export default function LandingHero(){\n'
        '  return <div style={{ backgroundImage: '
        '\'url("https://images.unsplash.com/photo-1550684848")\' }}>\n'
        '    <a href="/login">Sign in</a></div>;\n}\n')
    p = _mk(tmp_path, "components/LandingHero.jsx", src)
    out = fs.neutralize_frontend_external_backgrounds(tmp_path)
    assert "images.unsplash.com" in p.read_text(encoding="utf-8")  # intended hero kept
    assert out["neutralized"] == []


def test_img_tag_is_never_touched(tmp_path):
    src = ('export default function Feed(){ return <img '
           'src="https://images.unsplash.com/photo-1" className="w-full" />; }\n')
    p = _mk(tmp_path, "pages/FeedPage.jsx", src)
    fs.neutralize_frontend_external_backgrounds(tmp_path)
    assert p.read_text(encoding="utf-8") == src  # <img src> has no url() → untouched


def test_css_class_background_is_neutralized(tmp_path):
    """The mm34 case the review demonstrated: the lane factors the full-bleed external bg into
    a shared CSS class in index.css — the .jsx-only scan would miss it entirely."""
    css = (".outlook-bg { background-image: "
           "url('https://images.unsplash.com/photo-1464822759023'); }\n"
           "body { @apply bg-zinc-900; }\n")
    p = _mk(tmp_path, "index.css", css)
    out = fs.neutralize_frontend_external_backgrounds(tmp_path)
    after = p.read_text(encoding="utf-8")
    assert "images.unsplash.com" not in after
    assert "linear-gradient(" in after
    assert "index.css" in out["neutralized"]


def test_css_hero_selector_preserved(tmp_path):
    css = (".hero-banner { background-image: "
           "url('https://images.unsplash.com/hero'); }\n")
    p = _mk(tmp_path, "hero.css", css)
    fs.neutralize_frontend_external_backgrounds(tmp_path)
    assert "images.unsplash.com" in p.read_text(encoding="utf-8")  # hero-named rule kept


def test_font_src_url_not_touched(tmp_path):
    """A @font-face src url() is not a background context → must be left alone (not a photo)."""
    css = ("@font-face { font-family: X; src: "
           "url('https://fonts.example.com/x.woff2') format('woff2'); }\n")
    p = _mk(tmp_path, "fonts.css", css)
    fs.neutralize_frontend_external_backgrounds(tmp_path)
    assert "fonts.example.com" in p.read_text(encoding="utf-8")


def test_tailwind_arbitrary_bg_becomes_class(tmp_path):
    src = ('export default function DashboardPage(){ return <div '
           'className="min-h-screen bg-[url(\'https://images.unsplash.com/x\')] p-4" />; }\n')
    p = _mk(tmp_path, "pages/DashboardPage.jsx", src)
    fs.neutralize_frontend_external_backgrounds(tmp_path)
    after = p.read_text(encoding="utf-8")
    assert "images.unsplash.com" not in after
    assert "bg-slate-" in after  # arbitrary url bg → plain class (no space-in-arbitrary-value)


def test_idempotent(tmp_path):
    src = ('export default function OutlookInboxPage(){ return <div style={{ backgroundImage: '
           '\'url("https://images.unsplash.com/x")\' }} />; }\n')
    p = _mk(tmp_path, "pages/OutlookInboxPage.jsx", src)
    fs.neutralize_frontend_external_backgrounds(tmp_path)
    first = p.read_text(encoding="utf-8")
    out2 = fs.neutralize_frontend_external_backgrounds(tmp_path)
    assert p.read_text(encoding="utf-8") == first  # second pass no-op
    assert out2["neutralized"] == []


def test_data_uri_and_relative_bg_untouched(tmp_path):
    src = ('export default function InboxPage(){ return <div style={{ backgroundImage: '
           '\'url("/assets/local.png")\' }} />; }\n')
    p = _mk(tmp_path, "pages/InboxPage.jsx", src)
    fs.neutralize_frontend_external_backgrounds(tmp_path)
    assert "/assets/local.png" in p.read_text(encoding="utf-8")  # relative → self-contained → kept


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
