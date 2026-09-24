"""#1202gk — handing an API helper to something that calls it is using it.

`_has_real_api_call` accepted two shapes, and both require the helper to be INVOKED
syntactically in the page file: `getVideos(...)` or `feed.get(...)`. React's other idiom
passes it instead — `useApiList(getVideos, [])` — and the hook does the fetching.

tiktok-r98's ExploreGridPage imports `getVideos` from services/api, hands it to
`useApiList`, and renders `videos.items`. It is a real page that really loads data, and
`ui_page_unwired` called it "a STATIC MOCK (no api call)" and blocked delivery on it, with
/live and /messages alongside.

This is the third syntactic shape of one behaviour, and the second widening for the same
reason: the docstring already records that the direct-call-only check "false-flagged every
page using [the service-object pattern] as a placeholder stub".

Measured over the 1922 page files on this machine: 766 read as call-less, and 20 of those
(across 4 runs) pass an imported service helper into a call. Narrow by construction — the
name must be imported from services/api AND appear as an argument.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(
    0, str(Path(__file__).resolve().parents[1] / "env_generator" / "llm_generator"))

from multi_agent.runtime.frontend_audit import _has_real_api_call  # noqa: E402

IMPORT = "import { getVideos } from '../services/api.js';\n"


def test_a_helper_passed_to_a_hook_counts(): 
    """r98's exact shape."""
    assert _has_real_api_call(
        IMPORT + "const videos = useApiList(getVideos, []);") is True


def test_a_direct_call_still_counts():
    assert _has_real_api_call(IMPORT + "const v = await getVideos();") is True


def test_the_service_object_shape_still_counts():
    src = "import { feed } from '../services/api';\nfeed.get();"
    assert _has_real_api_call(src) is True


def test_a_bare_import_is_still_not_a_call():
    """The rule the original check exists to enforce: importing is not using."""
    assert _has_real_api_call(IMPORT + "export default function P(){return <div/>;}") is False


def test_a_property_read_is_still_not_a_call():
    assert _has_real_api_call(
        "import { feed } from '../services/api';\nconst n = feed.length;") is False


def test_a_name_not_imported_from_the_service_does_not_count():
    """The widening is anchored on the services/api import, not on any identifier."""
    assert _has_real_api_call("const videos = useApiList(getVideos, []);") is False


def test_a_page_with_no_service_import_at_all_is_unchanged():
    assert _has_real_api_call("export default function P(){return <div>mock</div>;}") is False


def test_fetch_still_counts():
    assert _has_real_api_call("await fetch('/api/videos');") is True
