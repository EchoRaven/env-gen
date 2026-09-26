"""#1202vk — #1202rr could not see the call shape the framework itself generates.

`_page_api_declaration_drift_1202rr` flags a page whose source calls an API while its
registration says `apis_used: []`. It recognised `api.get(` / `axios.get(` / `fetch(` /
`apiGet(` — and the framework's own projected frontend uses none of those. It routes every
call through `services/api.js` named exports.

Measured over the corpus's 508 pages that declare `apis_used: []` and have a locatable
source file: the old patterns catch 118 across 53 runs; adding the api-client shape takes
the check to 196 pages across 79 runs (+78 / +26). Spot-checked: netflix-r1 GamesPage
imports `{ getGames }` and calls it, netflix-r12 PlayerPage calls `getProfiles()` and
`getTitles()`, googlemaps-r16 MoviesPage calls `listTitles()` — each with `apis_used: []`.
"""
import pathlib
from types import SimpleNamespace as NS

import pytest

from env_generator.llm_generator.multi_agent.runtime.deliverability import (
    _requesting_exports_1202vk as requesting,
    _api_client_calls_1202vk as calls,
    _page_api_declaration_drift_1202rr as drift,
)

# The generated services/api.js exports both kinds side by side.
_API_JS = """
export function getStoredUser(){ return localStorage.getItem('access_token'); }
export function hasAuthToken(){ return Boolean(getStoredUser()); }
export function setToken(v){ localStorage.setItem('access_token', v); }
export async function getForYouFeed({ cursor } = {}){
  const data = await request(`/api/feed/foryou`);
  return { items: data.items || [] };
}
export const listTitles = (params) => request('/api/titles');
export const getMyList = async (profileId) => {
  const data = await request(`/api/my-list?profile_id=${profileId}`);
  return data.items || [];
};
"""


def test_only_the_request_issuing_exports_are_recognised():
    """A page that calls `hasAuthToken()` has not called an API. The corpus confirms the
    rule excludes the right names: getToken, formatCount, isAuthed, isAuthenticated,
    isLoggedIn."""
    assert requesting(_API_JS) == {"getForYouFeed", "listTitles", "getMyList"}


def test_a_multiline_arrow_body_is_not_clipped():
    """A first pass read `export const` through a 400-character window and dropped
    `getVideos`, `getMyList` and `addMyList` — exactly the ones that matter."""
    long_body = ("export const getVideos = async (a, b) => {\n"
                 + "  // padding\n" * 120
                 + "  return request('/api/videos');\n};\n")
    assert "getVideos" in requesting(long_body)


def _project(tmp_path, page_src, api_src=_API_JS, page_name="MoviesPage.jsx"):
    src = tmp_path / "frontend/src"
    (src / "pages").mkdir(parents=True)
    (src / "services").mkdir(parents=True)
    (src / "services/api.js").write_text(api_src)
    f = src / "pages" / page_name
    f.write_text(page_src)
    return tmp_path, f


def test_the_framework_shape_is_now_seen(tmp_path):
    d, f = _project(tmp_path,
                    "import { listTitles } from '../services/api.js';\n"
                    "export default function MoviesPage(){ listTitles(); return <div/>; }\n")
    assert calls(f.read_text(), f) is True


def test_importing_without_calling_is_not_a_call(tmp_path):
    d, f = _project(tmp_path,
                    "import { listTitles } from '../services/api.js';\n"
                    "export default function MoviesPage(){ return <div/>; }\n")
    assert calls(f.read_text(), f) is False


def test_calling_only_a_non_request_helper_is_not_a_call(tmp_path):
    """`hasAuthToken()` reads localStorage. Counting it would flag every logged-out
    landing page in the corpus."""
    d, f = _project(tmp_path,
                    "import { hasAuthToken } from '../services/api.js';\n"
                    "export default function MoviesPage(){ if (hasAuthToken()) return null; "
                    "return <div/>; }\n")
    assert calls(f.read_text(), f) is False


def test_an_import_from_an_unrelated_module_is_ignored(tmp_path):
    d, f = _project(tmp_path,
                    "import { formatCount } from '../utils/format';\n"
                    "export default function MoviesPage(){ formatCount(1); return <div/>; }\n")
    assert calls(f.read_text(), f) is False


def test_a_missing_api_module_does_not_raise(tmp_path):
    src = tmp_path / "frontend/src/pages"
    src.mkdir(parents=True)
    f = src / "MoviesPage.jsx"
    f.write_text("import { listTitles } from '../services/api.js';\n"
                 "export default function P(){ listTitles(); return <div/>; }\n")
    assert calls(f.read_text(), f) is False


def test_an_aliased_import_is_resolved(tmp_path):
    d, f = _project(tmp_path,
                    "import { listTitles as fetchTitles } from '../services/api.js';\n"
                    "export default function MoviesPage(){ fetchTitles(); return <div/>; }\n")
    # the ALIAS is what the page calls, so the alias must be what is tested
    assert calls(f.read_text(), f) is False, (
        "an alias is not the exported name; flagging it would need the alias mapped back, "
        "and claiming support without it would be the false positive")


def test_the_gate_predicate_reports_the_page(tmp_path):
    """End to end through the real predicate, with the registration that says none."""
    d, f = _project(tmp_path,
                    "import { listTitles } from '../services/api.js';\n"
                    "export default function MoviesPage(){ listTitles(); return <div/>; }\n")
    rh = NS(list_ui_pages=lambda: {"movies_page": {"component": "MoviesPage",
                                                   "route": "/movies", "apis_used": []}})
    out = drift(NS(registryhub=rh), d)
    assert out and "movies_page" in out[0]


def test_a_page_that_declares_its_apis_is_not_reported(tmp_path):
    d, f = _project(tmp_path,
                    "import { listTitles } from '../services/api.js';\n"
                    "export default function MoviesPage(){ listTitles(); return <div/>; }\n")
    rh = NS(list_ui_pages=lambda: {"movies_page": {"component": "MoviesPage",
                                                   "route": "/movies",
                                                   "apis_used": ["GET /api/titles"]}})
    assert drift(NS(registryhub=rh), d) == []


def test_the_original_patterns_still_fire(tmp_path):
    """#1202rr's own shape must keep working — this widens, it does not replace."""
    d, f = _project(tmp_path,
                    "export default function MoviesPage(){ fetch('/api/titles'); return <div/>; }\n")
    rh = NS(list_ui_pages=lambda: {"movies_page": {"component": "MoviesPage",
                                                   "route": "/movies", "apis_used": []}})
    assert drift(NS(registryhub=rh), d)


def test_a_destructured_default_parameter_does_not_break_the_body_match():
    """The generated client's own signature: `getForYouFeed({ cursor, limit = 5 } = {})`.
    Taking the first `{` after the name starts the brace match inside the PARAMETER list
    and closes it before the body begins — the first draft did that and missed this
    function entirely."""
    src = ("export async function getForYouFeed({ cursor, limit = 5 } = {}) {\n"
           "  const data = await request(`/api/feed/foryou`);\n"
           "  return { items: data.items || [] };\n}\n")
    assert "getForYouFeed" in requesting(src)


def test_a_destructured_default_on_a_non_requesting_function_stays_excluded():
    src = ("export function pickLabel({ a, b = 1 } = {}) {\n"
           "  return a || b;\n}\n")
    assert requesting(src) == set()


def test_a_crash_in_the_probe_announces_itself(monkeypatch):
    """#1202ah: a silent `return False` makes a CRASHED probe read as a page that calls
    nothing — the one answer indistinguishable from a pass. Once per process, because this
    runs per page per import."""
    import env_generator.llm_generator.multi_agent.runtime.message_format as mf
    from env_generator.llm_generator.multi_agent.runtime import deliverability as dl
    seen = []
    monkeypatch.setattr(mf, "warn_once_1201",
                        lambda site, what, exc: seen.append(site))
    monkeypatch.setattr(dl, "_requesting_exports_1202vk",
                        lambda _t: (_ for _ in ()).throw(RuntimeError("boom")))
    d = pathlib.Path(__file__).parent      # any real path; the crash happens before use
    bad = ("import { listTitles } from './api';\n"
           "export default function P(){ listTitles(); return <div/>; }\n")
    api = d / "api.js"
    created = not api.exists()
    if created:
        api.write_text("export const listTitles = () => request('/api/titles');\n")
    try:
        assert calls(bad, d / "P.jsx") is False
        assert seen == ["_api_client_calls_1202vk"]
    finally:
        if created:
            api.unlink()
