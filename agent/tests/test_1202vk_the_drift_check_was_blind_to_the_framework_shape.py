"""#1202vk — #1202rr could not see the call shape the framework itself generates.

`_page_api_declaration_drift_1202rr` flags a page whose source calls an API while its
registration says `apis_used: []`. It recognised `api.get(` / `axios.get(` / `fetch(` /
`apiGet(` — and the framework's own projected frontend uses none of those. It routes every
call through `services/api.js` named exports.

Over the corpus's 508 pages that declare `apis_used: []` with a locatable source file, the
old patterns catch 118 across 53 runs; delegating to the shared predicate takes the check
to 260 pages across 89 runs.

★ The first draft of this ticket reimplemented the shape instead of reusing
`frontend_audit._has_real_api_call`, which already existed and is a strict superset: it
also handles the service-object method (`feed.get()`) and #1202gk's hand-off to a hook
(`useApiList(getVideos, [])`). It also carried a filter restricting the answer to exports
whose body names `request`/`fetch`/`axios`, and the corpus proved that filter wrong —
r102's `getVideos`, r100's `getUser` and r119's `getVideos` all issue requests through
module-local wrappers (`authed`, `publicRequest`, `authedGet`), so it rejected real API
functions. Measured over the same pages: mine 123, the shared one 142, and mine caught
nothing it missed. Two copies of one rule drift (#1032), so there is one.
"""
import pathlib
from types import SimpleNamespace as NS

import pytest

from env_generator.llm_generator.multi_agent.runtime.deliverability import (
    _api_client_calls_1202vk as calls,
    _page_api_declaration_drift_1202rr as drift,
)

_SRC = pathlib.Path(
    __file__).resolve().parents[1] / (
    "env_generator/llm_generator/multi_agent/runtime/deliverability.py")

_IMPORT = "import { listTitles } from '../services/api';\n"


@pytest.mark.parametrize("body, why", [
    (_IMPORT + "export default function P(){ listTitles(); return <div/>; }",
     "the direct call — the shape the framework's own client generates"),
    ("import { feed } from '../services/api';\n"
     "export default function P(){ feed.get(); return <div/>; }",
     "the service-object method; run v11 false-flagged every page using it"),
    ("import { getVideos } from '../services/api';\n"
     "export default function P(){ const d = useApiList(getVideos, []); return <div/>; }",
     "#1202gk's hand-off to a hook; tiktok-r98's ExploreGridPage was called a STATIC MOCK"),
])
def test_every_shape_the_shared_predicate_knows_is_seen(body, why):
    assert calls(body) is True, why


def test_importing_without_using_is_not_a_call():
    assert calls(_IMPORT + "export default function P(){ return <div/>; }") is False


def test_an_unrelated_module_is_not_an_api_client():
    assert calls("import { fmt } from '../utils/format';\n"
                 "export default function P(){ fmt(1); return <div/>; }") is False


def test_a_request_through_a_local_wrapper_still_counts():
    """r102/r100/r119 route through `authed(...)` / `publicRequest(...)` / `authedGet(...)`
    rather than naming `request` or `fetch`. A filter keyed on those three names rejected
    real API functions — the first draft's mistake, pinned here so it is not re-made."""
    assert calls("import { getVideos } from '../services/api';\n"
                 "export default function P(){ getVideos(); return <div/>; }") is True


def _project(tmp_path, page_src):
    src = tmp_path / "frontend/src"
    (src / "pages").mkdir(parents=True)
    (src / "services").mkdir(parents=True)
    (src / "services/api.js").write_text(
        "export async function getForYouFeed({ cursor, limit = 5 } = {}) {\n"
        "  return (await authed(`/api/feed/foryou`)).items || [];\n}\n"
        "export const listTitles = (p) => request('/api/titles');\n")
    (src / "pages" / "MoviesPage.jsx").write_text(page_src)
    return tmp_path


def test_the_gate_predicate_reports_the_page(tmp_path):
    d = _project(tmp_path, _IMPORT + "export default function MoviesPage(){ listTitles(); return <div/>; }")
    rh = NS(list_ui_pages=lambda: {"movies_page": {"component": "MoviesPage",
                                                   "route": "/movies", "apis_used": []}})
    out = drift(NS(registryhub=rh), d)
    assert out and "movies_page" in out[0]


def test_a_page_that_declares_its_apis_is_not_reported(tmp_path):
    d = _project(tmp_path, _IMPORT + "export default function MoviesPage(){ listTitles(); return <div/>; }")
    rh = NS(list_ui_pages=lambda: {"movies_page": {"component": "MoviesPage",
                                                   "route": "/movies",
                                                   "apis_used": ["GET /api/titles"]}})
    assert drift(NS(registryhub=rh), d) == []


def test_the_original_patterns_still_fire(tmp_path):
    """#1202rr's own shape must keep working — this widens, it does not replace."""
    d = _project(tmp_path, "export default function MoviesPage(){ fetch('/api/titles'); return <div/>; }")
    rh = NS(list_ui_pages=lambda: {"movies_page": {"component": "MoviesPage",
                                                   "route": "/movies", "apis_used": []}})
    assert drift(NS(registryhub=rh), d)


def test_there_is_one_implementation_not_two():
    """The ticket's whole correction: delegate, do not reimplement. A future edit that
    inlines a regex here would recreate the drift #1032 cost."""
    src = _SRC.read_text()
    block = src[src.index("def _api_client_calls_1202vk"):
                src.index("def _page_api_declaration_drift_1202rr")]
    assert "_has_real_api_call" in block
    assert "re.compile" not in block and "_re.compile" not in block
    assert "_requesting_exports_1202vk" not in src, (
        "the request-name filter was measurably wrong and must not come back")


def test_a_crash_in_the_probe_announces_itself(monkeypatch):
    """#1202ah: a silent False makes a CRASHED probe read as a page that calls nothing —
    the one answer indistinguishable from a pass."""
    import env_generator.llm_generator.multi_agent.runtime.message_format as mf
    from env_generator.llm_generator.multi_agent.runtime import frontend_audit as fa
    seen = []
    monkeypatch.setattr(mf, "warn_once_1201", lambda site, what, exc: seen.append(site))
    monkeypatch.setattr(fa, "_has_real_api_call",
                        lambda _t: (_ for _ in ()).throw(RuntimeError("boom")))
    assert calls(_IMPORT + "listTitles();") is False
    assert seen == ["_api_client_calls_1202vk"]
