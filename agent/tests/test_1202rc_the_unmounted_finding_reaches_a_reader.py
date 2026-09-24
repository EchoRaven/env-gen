r"""#1202rc: the declared-but-unmounted finding reaches a reader.

`declared_but_unmounted_952` has been in `run_chains`' return value since #952 and read by
nothing. chain_executor.py says so itself, in the #1202ex wiring note: put a verdict "beside it
in a dict" and "it would go the way of `declared_but_unmounted_952` -- a key nothing outside
this file ever reads".

What that cost, twice:

  tiktok-r128  The verifier re-derived the finding by hand and filed
               "POST /api/v1/admin/init-tenant returns 404 for created tenant" as a P1. The
               debugger triaged it, the backend lane claimed it, and every one of that run's
               #952 reports had fired while build currency read "changed" -- the container
               predated the handler.

  tiktok-r129  80 reports in one milestone, 78 of them `PATCH /api/videos/{id}`, 64 under a
               stale build. business_chain stayed GREEN throughout, because a `missing` step
               leaves the chain passing (#927) -- so the branch that says "everything passes"
               is exactly where an unreachable handler hides.

The line is deduped by endpoint, carries #1132's three causes, and names none of them as THE
cause: the source-vs-live comparison cannot see which one it is, and a tool that hands over a
verdict it cannot support is how #1202qp's 401 hint rewrote a contract.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "env_generator" / "llm_generator")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from multi_agent.runtime.chain_executor import unmounted_summary_1202rc  # noqa: E402
from multi_agent.runtime.validation_runner import _unmounted_lines_1202rc  # noqa: E402

R129 = [{"method": "PATCH", "path": "/api/videos/1"},
        {"method": "PATCH", "path": "/api/videos/1"},
        {"method": "PATCH", "path": "/api/videos/9"},
        {"method": "POST", "path": "/api/comments/2/like"}]
STALE = {"verdict": "changed", "detail": "app/ has changed since the image was built"}
CURRENT = {"verdict": "current"}


def test_nothing_unmounted_says_nothing():
    assert unmounted_summary_1202rc([], STALE) == ""
    assert unmounted_summary_1202rc(None, None) == ""


def test_the_endpoint_appears_once_however_many_steps_hit_it():
    """r129 logged 78 lines for one handler; a reader needs it once."""
    line = unmounted_summary_1202rc(R129, CURRENT)
    assert line.count("PATCH /api/videos/1") == 1
    assert "3 endpoint(s)" in line


def test_all_three_causes_are_offered():
    line = unmounted_summary_1202rc(R129, CURRENT)
    for cause in ("router was never included", "duplicate filter", "predates the handler"):
        assert cause in line


def test_a_stale_build_is_called_out():
    line = unmounted_summary_1202rc(R129, STALE)
    assert "BUILD CURRENCY" in line and "rebuild and recreate" in line


def test_a_current_build_gets_no_rebuild_advice():
    """Telling a lane to rebuild when the image is current sends it after nothing."""
    line = unmounted_summary_1202rc(R129, CURRENT)
    assert "BUILD CURRENCY" not in line


def test_it_names_no_single_cause_as_the_answer():
    line = unmounted_summary_1202rc(R129, STALE).lower()
    assert "the router was never included -- add" not in line
    assert "three causes look identical" in line


# --- it reaches the check the verifier reads ---------------------------------------------

def test_the_passing_branch_carries_it_too():
    """#927 keeps the chain passing over a `missing` step, so success is where it hides."""
    chain = {"declared_but_unmounted_952": R129, "build_currency_1202ex": STALE}
    lines = _unmounted_lines_1202rc(chain)
    assert len(lines) == 1 and "PATCH /api/videos/1" in lines[0]


def test_a_clean_run_adds_no_line():
    assert _unmounted_lines_1202rc({"declared_but_unmounted_952": []}) == []
    assert _unmounted_lines_1202rc({}) == []


def test_both_validation_branches_call_it():
    src = (ROOT / "env_generator" / "llm_generator" / "multi_agent" / "runtime"
           / "validation_runner.py").read_text(encoding="utf-8")
    # landmark slices, not byte windows (#943): each branch runs to the next branch keyword
    fail = src[src.index('_add("business_chain", False,'):src.index('elif _chain.get(')]
    ok = src[src.index('elif _chain.get('):src.index("except Exception as _chain_exc")]
    assert "_unmounted_lines_1202rc(" in fail, "the failing branch does not carry it"
    assert "_unmounted_lines_1202rc(" in ok, "the PASSING branch does not carry it"


def test_the_count_and_the_list_agree():
    """#1034: a cut list beside "N endpoint(s)" reads as the whole set. Caught by that
    ratchet on the first draft of this line, which printed len(seen) next to seen[:8]."""
    many = [{"method": "PATCH", "path": "/api/videos/%d" % i} for i in range(20)]
    line = unmounted_summary_1202rc(many, CURRENT)
    assert "20 endpoint(s)" in line
    assert "more" in line, "the cut must be declared, not silent"
