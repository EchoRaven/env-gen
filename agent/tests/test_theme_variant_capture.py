"""FIX #141 — theme-variant capture.

run-64 M2 live evidence: login_dark.png ≡ login_light.png (identical md5,
mean=249 near-white) — the capture never switched the app to dark theme, so a
dark reference variant is judged against LIGHT pixels and is structurally
capped ~0.3. login_dark is a BLOCKING screen → sticky-pass can never complete
→ the visual window always runs to the 3600s anchor (M2: 3648s, 16 judged).

Fix: when a screen carries an explicit scheme (screen['scheme']) or a
dark/light NAME token, the capture (1) emulates prefers-color-scheme, (2)
pre-sets common theme storage keys and reloads so the app BOOTS themed
(class-strategy Tailwind / app-managed themes), and (3) force-toggles the
`dark` class + data-theme post-load. All three are inert on apps that ignore
them — never worse than today's capture.
"""
import re
import sys
import threading
import http.server
import functools
from pathlib import Path

import asyncio

import pytest

AGENT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AGENT))

from env_generator.llm_generator.multi_agent.runtime import visual_fidelity as vf


# ---------------------------------------------------------------------------
# scheme detection
# ---------------------------------------------------------------------------
def test_scheme_from_name_token():
    assert vf.screen_color_scheme({"name": "login_dark"}) == "dark"
    assert vf.screen_color_scheme({"name": "login_light"}) == "light"
    assert vf.screen_color_scheme({"name": "dark_mode_settings"}) == "dark"
    assert vf.screen_color_scheme({"name": "feed-dark"}) == "dark"


def test_scheme_word_boundary_not_substring():
    # 'darkroom' / 'highlights' must NOT match — token needs _/- boundaries
    assert vf.screen_color_scheme({"name": "darkroom"}) is None
    assert vf.screen_color_scheme({"name": "highlights"}) is None
    assert vf.screen_color_scheme({"name": "explore"}) is None


def test_explicit_scheme_key_wins():
    assert vf.screen_color_scheme({"name": "login", "scheme": "dark"}) == "dark"
    # bogus explicit value falls back to the name token
    assert vf.screen_color_scheme({"name": "login_light", "scheme": "sepia"}) == "light"


# ---------------------------------------------------------------------------
# JS builders (pure)
# ---------------------------------------------------------------------------
def test_storage_js_sets_and_clears():
    js = vf._theme_storage_js("dark")
    assert "setItem('theme', 'dark')" in js
    assert "setItem('darkMode', 'true')" in js
    js_light = vf._theme_storage_js("light")
    assert "setItem('darkMode', 'false')" in js_light
    js_clear = vf._theme_storage_js(None)
    assert "removeItem('theme')" in js_clear and "setItem" not in js_clear


def test_class_js_add_remove():
    assert "classList.add('dark')" in vf._theme_class_js("dark")
    assert "classList.remove('dark')" in vf._theme_class_js("light")
    assert "data-theme" in vf._theme_class_js("dark")


# ---------------------------------------------------------------------------
# e2e: a storage-at-boot themed page (the HARD case — requires the
# set-storage-then-reload path; media emulation alone cannot switch it)
# ---------------------------------------------------------------------------
_PAGE = b"""<!doctype html><html><head><style>
  body { background: #ffffff; margin: 0; }
  body.dark { background: #000000; }
</style></head><body><div id="root">hello theme page, enough text to pass the
blank probe. hello theme page. hello theme page. hello theme page.</div>
<script>
  // class-strategy app: theme decided ONCE at boot from localStorage
  if (localStorage.getItem('theme') === 'dark') document.body.classList.add('dark');
</script></body></html>"""


class _Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(_PAGE)

    def log_message(self, *a):
        pass


@pytest.fixture()
def theme_server():
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def _mean_gray(png_path):
    from PIL import Image
    im = Image.open(png_path).convert("L")
    px = list(im.resize((32, 32)).getdata())
    return sum(px) / len(px)


def test_dark_and_light_variants_capture_differently(theme_server, tmp_path):
    screens = [
        {"name": "login_light", "route": "/", "auth": False},
        {"name": "login_dark", "route": "/", "auth": False},
    ]
    shots = asyncio.run(vf.capture_route_screenshots(
        theme_server, screens, token=None, out_dir=tmp_path))
    assert set(shots) == {"login_light", "login_dark"}
    light = _mean_gray(shots["login_light"])
    dark = _mean_gray(shots["login_dark"])
    assert light > 200, f"light variant should be near-white, got {light}"
    assert dark < 60, f"dark variant should be near-black, got {dark}"


def test_theme_does_not_leak_into_next_unthemed_screen(theme_server, tmp_path):
    # dark first, then an unthemed screen: leftover storage keys must be
    # cleared so the unthemed screen boots with the app's own default (light)
    screens = [
        {"name": "login_dark", "route": "/", "auth": False},
        {"name": "home", "route": "/", "auth": False},
    ]
    shots = asyncio.run(vf.capture_route_screenshots(
        theme_server, screens, token=None, out_dir=tmp_path))
    assert _mean_gray(shots["login_dark"]) < 60
    assert _mean_gray(shots["home"]) > 200, "dark theme leaked into unthemed screen"


# ---------------------------------------------------------------------------
# #141b — per-round capture history (diagnosability: run-64 M2's 0.00↔0.40
# oscillation could not be root-caused because each round overwrote the shots)
# ---------------------------------------------------------------------------
def test_capture_history_preserved(theme_server, tmp_path):
    screens = [{"name": "home", "route": "/", "auth": False}]
    asyncio.run(vf.capture_route_screenshots(theme_server, screens, token=None,
                                             out_dir=tmp_path))
    asyncio.run(vf.capture_route_screenshots(theme_server, screens, token=None,
                                             out_dir=tmp_path))
    hist = list((tmp_path / "history").glob("*home.png"))
    assert len(hist) == 2, f"expected 2 history shots, got {[p.name for p in hist]}"
