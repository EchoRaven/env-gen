"""#1202wd: name the endpoints a page reaches, instead of only that it reaches one.

`_page_api_declaration_drift_1202rr` fired 93 times across r135/r136/r137 -- the fifth most
frequent of ~390 gate evaluations -- saying a page "declares `apis_used: []` while its own
source calls an API" and never which API, so the remediation asked the lane to work out what
the framework had just measured.

Nothing could name them, because these frontends delegate in TWO ways and every framework
predicate here answers yes/no. MEASURED on r136:

    LiveDiscoverPage (9 lines) -> LiveDiscoverContent (95) -> getFeed -> getVideoFeed
      -> request('/api/videos/feed')

and on the way a third problem surfaced: `_fe_res_1202uv`'s backtick pattern is
```[^`]*```, which stops at the first INNER backtick, so r135's own feed call --
``request(`/api/feed/foryou${params.toString() ? `?${params}` : ''}`)`` -- matched nothing at
all. 298 of the corpus's 2515 real `request(` call sites (11%) were invisible to the shipped
#1202uv artifact too, across 85 of 157 runs.

Resolution is 128 of the corpus's 260 flagged pages (49%) across 89 runs, averaging 1.7
endpoints. It REPORTS only: `apis_used` staying empty is what keeps the check firing, and
writing a half-resolved list into the registry would silence it while the contradiction stood.
"""
import os
import sys

import pytest

_AGENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_AGENT, "env_generator", "llm_generator"))

from multi_agent.runtime.frontend_audit import page_api_endpoints_1202wd  # noqa: E402
from multi_agent.runtime.scaffolder import _request_calls_1202wd  # noqa: E402


# --------------------------------------------------------------------- scanner

def test_a_template_literal_inside_a_template_literal_is_read_whole():
    src = ("const data = await request(`/api/feed/foryou"
           "${params.toString() ? `?${params}` : ''}`);")
    got = list(_request_calls_1202wd(src))
    assert len(got) == 1, got
    assert got[0][0].startswith("/api/feed/foryou"), got[0][0]
    assert got[0][0].count("`") == 2, (
        "the nested literal must be carried through, not truncated: %r" % got[0][0])


def test_plain_quotes_still_work_and_carry_their_options():
    src = "await request('/api/auth/login', { method: 'POST', body })"
    got = list(_request_calls_1202wd(src))
    assert len(got) == 1 and got[0][0] == "/api/auth/login", got
    assert "POST" in got[0][1], got[0][1]


def test_a_variable_path_yields_nothing_rather_than_a_guess():
    src = "export const post = (path, body) => request(path, { method: 'POST', body });"
    assert list(_request_calls_1202wd(src)) == []


def test_the_definition_of_request_is_not_a_call():
    src = "async function request(path, opts) { return fetch(path, opts); }"
    assert list(_request_calls_1202wd(src)) == []


def test_two_calls_in_one_body_are_both_found():
    src = ("await request(`/api/a/${id}`);\n"
           "await request('/api/b', { method: 'DELETE' });")
    got = [p for p, _o in _request_calls_1202wd(src)]
    assert got == ["/api/a/${id}", "/api/b"], got


# ------------------------------------------------------------------- resolver

def _frontend(tmp_path, files):
    src = tmp_path / "frontend" / "src"
    for rel, text in files.items():
        p = src / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    return tmp_path


API = """
async function request(path, opts) { return fetch(path, opts); }
export async function getVideoFeed(params) {
  return request(`/api/videos/feed${params ? `?${params}` : ''}`);
}
export async function getFeed(params) {
  return getVideoFeed(params);
}
export async function likeVideo(id) {
  return request(`/api/videos/${id}/like`, { method: 'POST' });
}
"""


def test_the_chain_through_a_wrapper_and_an_export_hand_off_resolves(tmp_path):
    """Both delegations at once: page -> content component, then getFeed -> getVideoFeed."""
    root = _frontend(tmp_path, {
        "services/api.js": API,
        "pages/LiveDiscoverPage.jsx":
            "import LiveDiscoverContent from '../components/LiveDiscoverContent';\n"
            "export default function LiveDiscoverPage() "
            "{ return <LiveDiscoverContent />; }\n",
        "components/LiveDiscoverContent.jsx":
            "import { getFeed } from '../services/api';\n"
            "export default function LiveDiscoverContent() "
            "{ getFeed(); return <div/>; }\n",
    })
    assert page_api_endpoints_1202wd(root, "LiveDiscoverPage") == ["GET /api/videos/feed"]


def test_a_sibling_import_is_followed_too(tmp_path):
    """r135's AppShell reaches the feed through `./TikTokFeed`, not `../components/X`."""
    root = _frontend(tmp_path, {
        "services/api.js": API,
        "pages/ForYouFeedPage.jsx":
            "import AppShell from '../components/AppShell';\n"
            "export default function ForYouFeedPage() { return <AppShell />; }\n",
        "components/AppShell.jsx":
            "import TikTokFeed from './TikTokFeed';\n"
            "export default function AppShell() { return <TikTokFeed />; }\n",
        "components/TikTokFeed.jsx":
            "import { getVideoFeed } from '../services/api';\n"
            "export default function TikTokFeed() { getVideoFeed(); return <div/>; }\n",
    })
    assert page_api_endpoints_1202wd(root, "ForYouFeedPage") == ["GET /api/videos/feed"]


def test_a_page_that_calls_does_not_inherit_its_chromes_endpoints(tmp_path):
    """★ r89: three unrelated pages resolved to the SAME four endpoints, three of them
    `/auth/*` from a LoginModal that 7 of its 16 pages import. A wrong entry in a blocker
    costs more than a missing one, so a file that calls the API is the answer."""
    root = _frontend(tmp_path, {
        "services/api.js": API + (
            "export async function login(b) "
            "{ return request('/api/auth/login', { method: 'POST', body: b }); }\n"),
        "pages/FriendsPage.jsx":
            "import LoginModal from '../components/LoginModal';\n"
            "import { getFeed } from '../services/api';\n"
            "export default function FriendsPage() "
            "{ getFeed(); return <LoginModal />; }\n",
        "components/LoginModal.jsx":
            "import { login } from '../services/api';\n"
            "export default function LoginModal() { login(); return <form/>; }\n",
    })
    got = page_api_endpoints_1202wd(root, "FriendsPage")
    assert got == ["GET /api/videos/feed"], (
        "the modal's /api/auth/login belongs to the modal, not to this page: %r" % got)


def test_an_unresolvable_page_says_nothing(tmp_path):
    root = _frontend(tmp_path, {
        "services/api.js": API,
        "pages/StaticPage.jsx": "export default function StaticPage() "
                                "{ return <div>hello</div>; }\n",
    })
    assert page_api_endpoints_1202wd(root, "StaticPage") == []


def test_a_missing_api_client_is_not_an_error(tmp_path):
    root = _frontend(tmp_path, {"pages/P.jsx": "export default function P(){return <i/>;}\n"})
    assert page_api_endpoints_1202wd(root, "P") == []


def test_a_cycle_terminates(tmp_path):
    root = _frontend(tmp_path, {
        "services/api.js": API,
        "pages/A.jsx": "import B from '../components/B';\n"
                       "export default function A(){ return <B/>; }\n",
        "components/B.jsx": "import A from '../pages/A';\n"
                            "export default function B(){ return <A/>; }\n",
    })
    assert page_api_endpoints_1202wd(root, "A") == []


@pytest.mark.parametrize("method,expect", [("POST", "POST"), ("DELETE", "DELETE")])
def test_the_declared_method_is_carried(tmp_path, method, expect):
    root = _frontend(tmp_path, {
        "services/api.js":
            "async function request(p, o) { return fetch(p, o); }\n"
            "export async function act(id) { return request(`/api/x/${id}`, "
            "{ method: '%s' }); }\n" % method,
        "pages/P.jsx": "import { act } from '../services/api';\n"
                       "export default function P(){ act(); return <i/>; }\n",
    })
    assert page_api_endpoints_1202wd(root, "P") == ["%s /api/x/{}" % expect]
