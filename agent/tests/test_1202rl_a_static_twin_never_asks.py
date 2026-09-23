r"""#1202rl: a page that renders hardcoded rows and never asks the server.

#1202qn finds a page that CALLS the API and answers a failure with substitute rows
(`catch { return fallbackVideos }`). tiktok-r131 shipped the other shape, and #1202qn is
structurally blind to it: nine of twelve pages never called the API at all and rendered a
module of hardcoded rows instead. No catch, no failure, nothing masked — so the detector found
nothing and the pages shipped.

It was found by an unprimed agent doing an ordinary task, not by a scan. Asked "who are the
three most-followed creators", it worked through the UI, then the API, then the database, and
reported that the question has no truthful answer on this platform — and that trusting the
frontend would have produced a confident WRONG one. The mock module held `followers_count:
156000000` for a creator the API reports with 0, live viewer figures unrelated to the seeded
streams, and `jul.spamz.fr`, a creator absent from the database, wearing another user's avatar
file. A confident wrong answer is worse than a blank screen; a blank screen is visibly broken.

The rule is narrow on purpose. A module of constants is fine — copy, nav items, category chips,
icon maps. What is not fine is rendering ROWS from one while making no request of your own.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "env_generator" / "llm_generator")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from multi_agent.runtime.frontend_audit import static_twin_blockers_1202rl as gate  # noqa: E402


def _fe(tmp_path, files):
    src = tmp_path / "src"
    for rel, body in files.items():
        f = src / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(body, encoding="utf-8")
    return src


def test_the_r131_shape_is_caught(tmp_path):
    src = _fe(tmp_path, {"pages/ExploreGridPage.jsx":
                         "import { exploreVideos } from '../data/fallbackData';\n"
                         "export default () => exploreVideos.map(v => <li>{v.likes}</li>);"})
    out = gate(src)
    assert out and "ExploreGridPage.jsx" in out[0]


def test_a_page_that_also_asks_the_server_is_not_a_twin(tmp_path):
    """A module used as a seed for an empty state, beside a real fetch, is legitimate."""
    src = _fe(tmp_path, {"pages/Feed.jsx":
                         "import { fallbackRows } from '../data/fallbackData';\n"
                         "useEffect(() => { api.get('/api/videos').then(setRows); }, []);"})
    assert gate(src) == []


def test_a_constants_module_is_not_a_data_module(tmp_path):
    """Nav items, category chips and icon maps are not rows. Flagging them would block
    every honest app."""
    src = _fe(tmp_path, {"pages/Nav.jsx":
                         "import { NAV_ITEMS } from '../constants/nav';\n"
                         "export default () => NAV_ITEMS.map(n => <a>{n.label}</a>);"})
    assert gate(src) == []


def test_a_clean_page_passes(tmp_path):
    src = _fe(tmp_path, {"pages/Feed.jsx":
                         "useEffect(() => { api.get('/api/videos').then(setRows); }, []);"})
    assert gate(src) == []


def test_components_are_scanned_too(tmp_path):
    """r131's CreatorGrid was a component, not a page."""
    src = _fe(tmp_path, {"components/CreatorGrid.jsx":
                         "import { creators } from '../data/mockData';\n"
                         "export default () => creators.map(c => <b>{c.followers}</b>);"})
    assert gate(src)


def test_the_message_says_why_it_is_not_a_masked_failure(tmp_path):
    """A reader who confuses the two goes looking for a catch block that does not exist."""
    src = _fe(tmp_path, {"pages/P.jsx":
                         "import { rows } from '../data/sampleData';\nexport default () => rows;"})
    out = gate(src)[0]
    assert "request is never made" in out and "#1202qn" in out


def test_it_can_be_switched_off(tmp_path, monkeypatch):
    monkeypatch.setenv("ENVGEN_STATIC_TWIN_GATE", "0")
    src = _fe(tmp_path, {"pages/P.jsx":
                         "import { rows } from '../data/fallbackData';\nexport default () => rows;"})
    assert gate(src) == []


def test_no_src_dir_is_not_a_finding(tmp_path):
    assert gate(tmp_path) == []


def test_the_gate_is_reachable_from_the_blocker_list():
    """#1202 ratchet: a gate nothing calls gates nothing."""
    src = (ROOT / "env_generator" / "llm_generator" / "multi_agent" / "runtime"
           / "deliverability.py").read_text(encoding="utf-8")
    assert src.count("blockers.extend(static_twin_blockers_1202rl") == 1
