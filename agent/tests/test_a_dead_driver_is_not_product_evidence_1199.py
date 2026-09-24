r"""#1199: the browser driver dying is not evidence about the product.

#1154 already established the category — *"A CONNECTION-LEVEL FAILURE IS NOT EVIDENCE ABOUT
THE PRODUCT"* — and listed the markers that mean it: ERR_CONNECTION_REFUSED, ECONNREFUSED,
ERR_CONNECTION_RESET, ERR_EMPTY_RESPONSE, ERR_NAME_NOT_RESOLVED. The driver's own death was
not among them, and it is the one that actually happens.

r26: 214 of 232 navigation failures are `Page.goto: Connection closed while reading from the
driver` — 92% — and every one was scored as product evidence. The log says what that cost, in
its own words:

    #743 1 P0 BUG task(s) are still open at the delivery cut: validation:ui_flow:login
        could not be re-recorded because browser driver closes during nav
    Cannot resolve owner for P0 bug task_e5896caa4b. title='UI validation blocked:
        browser cannot navigate to frontend (driver...'
    Anti-stall escalation: delivery is still blocked by the same browser-driver closure
        on `validation:ui_flow:login_page`

Three hours of escalation, a P0 with no resolvable owner, and delivery blocked — over a
product that was fine. #1198 stops the driver from staying dead; this stops its death from
being read as a defect.

Two shapes have to match, because the record is written twice over: Playwright's own transport
string, and the agent's paraphrase of it ("browser driver closes during nav",
"browser-driver closure", "browser_navigate closed the driver"). The paraphrase pattern is
narrow on purpose — "driver" is not a word a product failure uses, and it must sit beside a
closure verb.

#1154's fold-back still governs everything here: when NOTHING passed in the same pass, the
discounted records are folded back into failures, because then the app really may be dead.
"""

import sys
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS_DIR.parent / "env_generator" / "llm_generator"))

from multi_agent.runtime import delivery_gate as dg  # noqa: E402


def _is_unreachable(text: str) -> bool:
    return (any(m in text for m in dg._UNREACHABLE_1154)
            or bool(dg._DRIVER_GONE_RE_1199.search(text)))


# ------------------------------------------------- verbatim from r22-r26's logs and records

DRIVER_DEATHS = [
    "browser_navigate FAILED (7ms): Navigation failed: Page.goto: Connection closed while "
    "reading from the driver",
    "validation:ui_flow:login could not be re-recorded because browser driver closes during nav",
    "delivery is still blocked by the same browser-driver closure on validation:ui_flow:login_page",
    "/login route could not be observed because browser_navigate closed the driver.",
    "UI validation blocked: browser cannot navigate to frontend (driver closed)",
    "asyncio: pipe closed by peer or os.write(pipe, data) raised exception.",
]


def test_every_shape_the_corpus_actually_produced_is_discounted():
    for text in DRIVER_DEATHS:
        assert _is_unreachable(text), text


# ------------------------------------------------------- what must STAY product evidence

PRODUCT_FAILURES = [
    "login form did not submit; button click had no effect",
    "GET /api/titles returned 500",
    "page rendered blank with console error: Cannot read properties of undefined",
    "request_failed 404 for /api/my-list",
    "the browser showed a fallback placeholder instead of real data",
    "the page closed the modal but never saved",
]


def test_a_real_defect_is_not_laundered_into_infrastructure_noise():
    """The whole value of #1154 is that the list is NARROW."""
    for text in PRODUCT_FAILURES:
        assert not _is_unreachable(text), text


# ------------------------------------------------------------------ the fold-back holds

def _breadth(records):
    return dg._ui_evidence_breadth_739(records)


def test_a_driver_death_is_discounted_only_when_something_else_passed():
    dead = {"name": "validation:ui_flow:login", "status": "failed",
            "detail": "Page.goto: Connection closed while reading from the driver"}
    alive = {"name": "validation:ui_flow:browse", "status": "passed", "detail": "ok"}

    with_pass = _breadth([dead, alive])
    assert with_pass["failed_records"] == 0
    assert int(with_pass.get("unreachable_records") or 0) == 1

    # Nothing passed: the origin may genuinely be down, so it must still block (#1154).
    alone = _breadth([dead])
    assert alone["failed_records"] == 1
    assert int(alone.get("unreachable_records") or 0) == 0


# ------------------------------------------------- the last unowned gate check (#1199)

def test_every_gate_check_seen_unowned_in_the_recent_corpus_now_has_an_owner():
    """A check in neither `_GATE_OWNER` nor `_COVERED_ELSEWHERE` takes the
    `if not spec: uncovered.append(name); continue` path — nothing is dispatched and the run
    logs "NO remediation owner". #1040 measured what that costs when it lands on a common
    blocker: 26 runs, on the most frequent one, with a working fix unreachable behind the
    lookup.

    Time-sliced (ranking by raw frequency puts already-fixed gaps first — the 157 hits on
    deliverability_dead_artifacts all predate its row): across r20-r26 exactly one gate tick
    logged no owner, for `deliverability_seed_quality`.
    """
    src = (Path(__file__).resolve().parents[1]
           / "env_generator/llm_generator/multi_agent/runtime/remediation_dispatcher.py"
           ).read_text(encoding="utf-8")
    assert '"deliverability_seed_quality": (' in src
    # Its sibling stays distinct — the two branches name different audits.
    assert '"deliverability_authored_seed_quality": (' in src
