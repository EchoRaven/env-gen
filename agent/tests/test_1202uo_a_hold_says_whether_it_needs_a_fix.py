r"""#1202uo: the delivery-hold ledger recorded "waiting as designed" and "blocked" as one thing.

`delivery_hold.jsonl` (#1202tk) exists to answer the single most consequential question this
system has: the gate was green and nothing shipped -- why? It wrote every hold under one name.
But several of the thirteen hold points are the release WORKING: the test-user squad runs in
the background and delivery defers a tick by design (single-flight), the visual capture
re-shoots, the pre-cut smoke runs on the release tree.

MEASURED on the only run in the ledger that DELIVERED:

    r132   27 holds   27 gate,  0 post-gate
    r133  108 holds   95 gate, 13 post-gate = 12 designed waits + 1 real block
    r134   36 holds   36 gate,  0 post-gate
    r135    2 holds    2 gate,  0 post-gate

So reading r133's ledger as "thirteen things stopped delivery" is 92% wrong for the one run
that succeeded. I misread it exactly that way half an hour before writing this, and concluded
"the squad is 12 of 13 post-gate holds" -- of a run that shipped.

Each classification was checked at its own CALL SITE, not guessed from the name: `squad_wait`
is a wait condition, `squad_not_ready` is #179's defer-without-burning-an-attempt, and
`visual_final_recapture` says in its own comment "delivery capture, not a remediation round".

Same distinction as #1202tn, where the idle breaker treated "stuck" and "nothing to do" as one
state. The set is a membership test so anything added later defaults to `blocking` -- the safe
direction, since an unclassified hold should read as needing attention until someone says
otherwise.

LOCAL-ONLY (gitignored)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for p in (str(ROOT), str(LLM_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

from multi_agent.orchestrator import (  # noqa: E402
    _WAITING_HOLDS_1202UO,
    _note_delivery_hold_1202tk,
)


class _Orch:
    def __init__(self, out):
        self.output_dir = str(out)
        self._current_milestone_version = "1.0.0"


def _record(tmp_path, *holds):
    orch = _Orch(tmp_path)
    for h in holds:
        _note_delivery_hold_1202tk(orch, h, "d")
    lines = (Path(tmp_path) / "logs" / "delivery_hold.jsonl").read_text().splitlines()
    return [json.loads(x) for x in lines if x.strip()]


def test_a_designed_defer_is_recorded_as_waiting(tmp_path):
    """★ The defect: a background squad run counted as a reason delivery failed."""
    rows = _record(tmp_path, "squad_inflight", "squad_launched_background")
    assert [r["kind"] for r in rows] == ["waiting", "waiting"], rows


def test_a_real_hold_is_recorded_as_blocking(tmp_path):
    rows = _record(tmp_path, "gate_failed_checks", "squad_defects",
                   "browser_ui_unusable", "route_consolidation")
    assert [r["kind"] for r in rows] == ["blocking"] * 4, rows


def test_r133s_ledger_now_separates(tmp_path):
    """★ The measurement restated as an assertion: r133's own post-gate holds, in the
    proportions the run actually produced, must come out 12 waiting and 1 blocking."""
    holds = (["squad_launched_background"] * 2 + ["squad_inflight"] * 9
             + ["fresh_smoke"] + ["squad_defects"])
    rows = _record(tmp_path, *holds)
    kinds = [r["kind"] for r in rows]
    assert kinds.count("waiting") == 12 and kinds.count("blocking") == 1, kinds


def test_an_unknown_hold_defaults_to_blocking(tmp_path):
    """★ The direction that matters. A hold added later and never classified must read as
    needing attention, not as the system quietly working."""
    rows = _record(tmp_path, "some_hold_added_next_year")
    assert rows[0]["kind"] == "blocking", rows


def test_every_waiting_entry_is_a_real_hold_point():
    """★ #1202tr's lesson: an exemption list is an unchecked claim. Each name here must be one
    the orchestrator actually records, or the set is guarding spelling rather than behaviour."""
    src = (LLM_DIR / "multi_agent" / "orchestrator.py").read_text(encoding="utf-8")
    for name in _WAITING_HOLDS_1202UO:
        assert f'_note_delivery_hold_1202tk(self, "{name}"' in src, (
            f"{name!r} is exempted but is not a hold this orchestrator ever writes")


def test_the_existing_fields_are_untouched(tmp_path):
    """The ledger is read by post-mortems; adding a field must not move the others."""
    rows = _record(tmp_path, "gate_failed_checks")
    assert set(rows[0]) == {"at", "hold", "kind", "detail", "milestone"}, rows[0]
    assert rows[0]["hold"] == "gate_failed_checks" and rows[0]["detail"] == "d"
    assert rows[0]["milestone"] == "1.0.0"


def test_it_never_raises(tmp_path):
    """#1202tk is explicit that an observability write must never stop a delivery."""

    class _Bad:
        @property
        def output_dir(self):
            raise RuntimeError("no dir")

    _note_delivery_hold_1202tk(_Bad(), "gate_failed_checks", "x")
