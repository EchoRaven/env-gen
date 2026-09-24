"""Regression: orchestrator boot-wire dispatches kickoff (NOT raw task_ready).

Charter §5 + §8: the resident orchestrator lane MUST host a kickoff
meeting at M1 start. The previous boot wire shipped
``send_task({"workflow": "full", ...})`` straight into the
orchestrator's resident lane — which then prompted the LLM to
``send_message(to_agent="design", msg_type="task_ready", ...)`` BEFORE
the cross-check suite, arbitration table, and roadmap validator had
ever run. That race is what `runtime.kickoff.run_kickoff.start_kickoff`
closes: opens the meeting, fans out kickoff_request to three attendees,
and lets the orchestrator lane wake on workhub.meeting_decision_added
events to drive synthesis + finalize.

Round 8e.1: design merged into frontend; attendees 4 → 3 (backend,
frontend, verifier). Frontend now owns ui_pages + user_flows + auth +
reference_image_manifest + screens.

Three invariants pinned here (closed-by-construction; each catches one
specific regression shape):

1. orchestrator.py:Orchestrator.run boots via
   ``run_kickoff.start_kickoff(...)`` at the seam where the old
   ``send_task(workflow="full")`` call used to live, AND the dead
   send_task no longer exists in the run() body.
2. ``start_kickoff`` against a mock-hubs registry emits ONE
   ``kickoff_request`` event whose recipients carry exactly the three
   M1 attendees (backend / frontend / verifier).
3. The orchestrator agent's default subscriptions include
   ``("workhub", "meeting_decision_added", "normal")`` — so its tick
   actually wakes to process synthesis attempts.
"""
from __future__ import annotations

import ast
import re
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(LLM_DIR) not in sys.path:
    sys.path.insert(0, str(LLM_DIR))

from multi_agent.runtime.agent_subscriptions import (  # noqa: E402
    DEFAULT_SUBSCRIPTIONS,
)
from multi_agent.runtime.kickoff import run_kickoff  # noqa: E402


ORCHESTRATOR_PY = (
    LLM_DIR / "multi_agent" / "orchestrator.py"
)

KICKOFF_ATTENDEES = ["backend", "frontend", "verifier"]


# ---------------------------------------------------------------------------
# Invariant 1: source-level boot wire
# ---------------------------------------------------------------------------


class OrchestratorBootsViaKickoffCoordinator(unittest.TestCase):
    """The first orchestration call in Orchestrator.run is start_kickoff.

    Uses AST + a regex backstop because regex alone is brittle (renames,
    line wraps) but the AST scan needs the literal call_name fallback to
    catch attribute-call forms like ``self.run_kickoff.start_kickoff(...)``.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.source = ORCHESTRATOR_PY.read_text()
        cls.tree = ast.parse(cls.source)

    def _find_run_method(self) -> ast.AsyncFunctionDef:
        for node in ast.walk(self.tree):
            if isinstance(node, ast.ClassDef) and node.name == "Orchestrator":
                for sub in node.body:
                    if (
                        isinstance(sub, ast.AsyncFunctionDef)
                        and sub.name == "run"
                    ):
                        return sub
        self.fail("Orchestrator.run not found in orchestrator.py")

    def test_first_orchestration_dispatch_is_start_kickoff(self) -> None:
        """The very first kickoff/dispatch call inside Orchestrator.run
        is ``run_kickoff.start_kickoff(...)`` — NOT a legacy
        ``send_task({"workflow": "full", ...})`` or
        ``send_message(msg_type="task_ready", ...)`` against an attendee.
        """
        run_fn = self._find_run_method()
        first_kickoff_or_dispatch_call = None
        # Walk in source order; the first call matching any of our
        # "boot-shaped" patterns wins. We classify it then assert.
        for node in ast.walk(run_fn):
            if not isinstance(node, ast.Call):
                continue
            # Pattern A: <something>.start_kickoff(...)
            if (
                isinstance(node.func, ast.Attribute)
                and node.func.attr == "start_kickoff"
            ):
                first_kickoff_or_dispatch_call = ("start_kickoff", node)
                break
            # Pattern B: legacy send_task({"workflow": "full", ...})
            if (
                isinstance(node.func, ast.Attribute)
                and node.func.attr == "send_task"
                and node.args
                and isinstance(node.args[0], ast.Dict)
            ):
                # Only flag the legacy *initial* send_task — keys carry
                # "workflow": "full". The downstream coord-tick uses
                # "workflow": "resident_tick" and is fine.
                for key, value in zip(node.args[0].keys, node.args[0].values):
                    if (
                        isinstance(key, ast.Constant)
                        and key.value == "workflow"
                        and isinstance(value, ast.Constant)
                        and value.value == "full"
                    ):
                        first_kickoff_or_dispatch_call = (
                            "legacy_send_task", node
                        )
                        break
                if first_kickoff_or_dispatch_call:
                    break
            # Pattern C: legacy send_message(msg_type="task_ready", to_agent=<attendee>)
            if (
                isinstance(node.func, ast.Attribute)
                and node.func.attr == "send_message"
            ):
                kw_map = {
                    kw.arg: kw.value for kw in node.keywords if kw.arg
                }
                msg_type = kw_map.get("msg_type")
                to_agent = kw_map.get("to_agent")
                if (
                    isinstance(msg_type, ast.Constant)
                    and msg_type.value == "task_ready"
                    and isinstance(to_agent, ast.Constant)
                    and to_agent.value in KICKOFF_ATTENDEES
                ):
                    first_kickoff_or_dispatch_call = (
                        "legacy_send_message_task_ready", node
                    )
                    break

        self.assertIsNotNone(
            first_kickoff_or_dispatch_call,
            "Orchestrator.run contains no boot-dispatch call. Either "
            "start_kickoff was removed or this scanner needs an update.",
        )
        kind, node = first_kickoff_or_dispatch_call
        self.assertEqual(
            kind, "start_kickoff",
            f"Orchestrator.run first dispatch is {kind!r} at line "
            f"{node.lineno} — expected start_kickoff. The kickoff "
            f"coordinator must boot before any task_ready / send_task "
            f"hand-off to attendee lanes.",
        )

    def test_no_legacy_workflow_full_send_task_in_run(self) -> None:
        """Belt-and-suspenders: no ``send_task({"workflow": "full"})``
        anywhere in Orchestrator.run. If the boot dispatch ever
        regressed to that shape, invariant 1 would fire first — this
        test pins the absence directly so even out-of-order edits are
        caught.
        """
        run_fn = self._find_run_method()
        offenders = []
        for node in ast.walk(run_fn):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "send_task"
                and node.args
                and isinstance(node.args[0], ast.Dict)
            ):
                for key, value in zip(node.args[0].keys, node.args[0].values):
                    if (
                        isinstance(key, ast.Constant)
                        and key.value == "workflow"
                        and isinstance(value, ast.Constant)
                        and value.value == "full"
                    ):
                        offenders.append(node.lineno)
        self.assertEqual(
            offenders, [],
            f"Legacy send_task(workflow='full', ...) found at lines "
            f"{offenders}. Boot dispatch must be run_kickoff.start_kickoff.",
        )

    def test_kickoff_call_site_targets_three_attendees(self) -> None:
        """Round 8e.1: start_kickoff invoked with attendees=[backend,
        frontend, verifier]. M1 quorum is the three cross-check sections
        (design merged into frontend)."""
        run_fn = self._find_run_method()
        attendees_lists = []
        for node in ast.walk(run_fn):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "start_kickoff"
            ):
                for kw in node.keywords:
                    if kw.arg == "attendees" and isinstance(kw.value, ast.List):
                        names = [
                            elt.value for elt in kw.value.elts
                            if isinstance(elt, ast.Constant)
                            and isinstance(elt.value, str)
                        ]
                        attendees_lists.append(names)
        self.assertTrue(
            attendees_lists,
            "start_kickoff call found, but no inline ``attendees=[...]`` "
            "literal — the test cannot verify the M1 attendee set. "
            "Either inline the list literal or extend this scanner.",
        )
        self.assertIn(
            sorted(KICKOFF_ATTENDEES),
            [sorted(a) for a in attendees_lists],
            f"No start_kickoff call uses the M1 attendee set "
            f"{sorted(KICKOFF_ATTENDEES)}. Got: {attendees_lists}",
        )


# ---------------------------------------------------------------------------
# Invariant 2: end-to-end kickoff_request fan-out
# ---------------------------------------------------------------------------


def _mock_hubs(meeting_id: str = "page_meeting_1") -> SimpleNamespace:
    """Minimal hub registry that satisfies start_kickoff."""
    workhub = MagicMock(name="workhub")
    workhub.create_meeting.return_value = {
        "id": meeting_id,
        "title": "M1 kickoff",
        "metadata": {"decisions": []},
    }
    eventhub = MagicMock(name="eventhub")
    eventhub.publish_event.return_value = {"id": "evt_kickoff_request"}
    return SimpleNamespace(workhub=workhub, eventhub=eventhub)


class StartKickoffFansOutToAllAttendees(unittest.TestCase):
    """Invariant 2: kickoff_request lands on all 4 M1 attendees."""

    def test_kickoff_request_event_recipients_match_attendees(self) -> None:
        hubs = _mock_hubs()
        handle = run_kickoff.start_kickoff(
            hubs=hubs,
            milestone_index=1,
            requirements=["build a tiny social app"],
            attendees=KICKOFF_ATTENDEES,
        )

        # Exactly one event.
        self.assertEqual(
            hubs.eventhub.publish_event.call_count, 1,
            "start_kickoff must emit exactly ONE kickoff_request event",
        )
        kwargs = hubs.eventhub.publish_event.call_args.kwargs
        self.assertEqual(kwargs["event_type"], "kickoff_request")
        self.assertEqual(kwargs["source_hub"], "orchestrator")
        self.assertEqual(kwargs["priority"], "high")
        # Every attendee in recipients — order pinned to attendees order.
        self.assertEqual(
            kwargs["recipients"], KICKOFF_ATTENDEES,
            f"kickoff_request recipients must be {KICKOFF_ATTENDEES}, "
            f"got {kwargs['recipients']!r}",
        )
        # Returned handle ready for the synthesis loop.
        self.assertEqual(handle["meeting_id"], "page_meeting_1")
        self.assertEqual(handle["expected_attendees"], KICKOFF_ATTENDEES)
        self.assertEqual(handle["phase"], "awaiting_decisions")


# ---------------------------------------------------------------------------
# Invariant 3: orchestrator subscribes to meeting_decision_added
# ---------------------------------------------------------------------------


class OrchestratorSubscribesToMeetingDecisionAdded(unittest.TestCase):
    """Invariant 3 (RESTATED 2026-07-21, F2): attendee decisions must REACH the
    orchestrator — but as INBOX_ONLY, not as a resident wakeup.

    When this invariant was written (round 8c) the live subscription WAS the synthesis
    trigger. Round 8f.1 replaced that with ``runtime/kickoff_driver.py``, which polls
    ``try_synthesize`` every KICKOFF_POLL_INTERVAL_SEC (5s) and re-fires facilitation
    itself. The live sub therefore buys at most 5s of latency while costing a full
    large-context LLM step per decision (~88s measured) that can only conclude
    "ineligible during kickoff" — 44 idle wakes in one observed run, kickoff crawling
    past 21 min. What must NOT regress is the decision being invisible, so this now
    pins delivery-by-inbox plus the chairing subs that DO stay live.
    """

    def test_meeting_decisions_reach_the_orchestrator_without_a_wakeup(self) -> None:
        from multi_agent.runtime.agent_subscriptions import (
            INBOX_ONLY_SUBSCRIPTIONS,
        )
        live = DEFAULT_SUBSCRIPTIONS.get("orchestrator") or []
        inbox = INBOX_ONLY_SUBSCRIPTIONS.get("orchestrator") or []
        sub = ("workhub", "meeting_decision_added", "normal")
        self.assertIn(sub, inbox,
                      f"attendee decisions must still be DELIVERED. inbox_only: {inbox}")
        self.assertNotIn(sub, live,
                         "a LIVE sub reintroduces the idle-wake storm the deterministic "
                         f"kickoff driver made unnecessary. live: {live}")

    def test_orchestrator_keeps_the_live_chairing_subscriptions(self) -> None:
        """The driver polls, but CHAIRING is still event-driven — these must stay live
        or kickoff loses its facilitator and runs to the outer timeout."""
        live = DEFAULT_SUBSCRIPTIONS.get("orchestrator") or []
        names = {evt for _hub, evt, _prio in live}
        for required in ("kickoff_facilitate_request", "kickoff_detail_request"):
            self.assertIn(required, names, f"live chairing sub lost: {required}")

    def test_kickoff_request_wired_for_all_four_attendees(self) -> None:
        """Each kickoff attendee lane subscribes to
        (orchestrator, kickoff_request, high) — without this, lanes
        never wake on meeting open."""
        for attendee in KICKOFF_ATTENDEES:
            subs = DEFAULT_SUBSCRIPTIONS.get(attendee) or []
            self.assertIn(
                ("orchestrator", "kickoff_request", "high"),
                subs,
                f"{attendee!r} MUST subscribe to "
                f"(orchestrator, kickoff_request, high). Live: {subs}",
            )

    def test_kickoff_complete_wired_for_attendees_plus_observers(self) -> None:
        """kickoff_complete wakes the four M1 attendees plus the debugger observer — five
        lanes total.

        #1202ch removed `knowledge` from this set with the lane itself. That lane's ONLY
        subscription was this event, and each wake produced
        `{"kind":"summarization_ack","action":"skipped","reason":"no matching trigger"}`
        because `kickoff_complete` is not in its own wake_contract table. The subscription
        was the entire reason it ever ran, and it never did anything with it."""
        expected_observers = set(KICKOFF_ATTENDEES) | {"debugger"}
        for lane in expected_observers:
            subs = DEFAULT_SUBSCRIPTIONS.get(lane) or []
            self.assertTrue(
                any(
                    src == "orchestrator" and evt == "kickoff_complete"
                    for src, evt, _prio in subs
                ),
                f"{lane!r} MUST subscribe to "
                f"(orchestrator, kickoff_complete, ...). Live: {subs}",
            )


# ---------------------------------------------------------------------------
# Invariant 4 (belt + suspenders): the orchestrator prompt v3 carries
# the new kickoff_synthesis_prompt macro the LLM lane reads.
# ---------------------------------------------------------------------------


class OrchestratorPromptCarriesKickoffSynthesisMacro(unittest.TestCase):
    """The orchestrator_agent.j2 file must define the kickoff synthesis macro
    (renamed ``kickoff_synthesis_prompt`` → ``kickoff_facilitation_prompt``) so
    the lane's tick prompt is rendered when waking on meeting_decision_added —
    it is the macro messaging.py / facilitate.py actually render."""

    def test_kickoff_synthesis_prompt_macro_defined(self) -> None:
        path = (
            LLM_DIR / "multi_agent" / "prompts" / "v3"
            / "orchestrator_agent.j2"
        )
        src = path.read_text()
        self.assertTrue(
            re.search(
                r"\{%\s*macro\s+kickoff_facilitation_prompt\s*\(",
                src,
            ),
            "orchestrator_agent.j2 must define a "
            "``kickoff_facilitation_prompt(meeting_id, milestone_index, ...)`` "
            "macro (formerly kickoff_synthesis_prompt) — the LLM lane wakes on "
            "meeting_decision_added and renders it (messaging.py / facilitate.py) "
            "to drive try_synthesize/finalize_kickoff.",
        )

    def test_kickoff_synthesis_prompt_references_helpers(self) -> None:
        path = (
            LLM_DIR / "multi_agent" / "prompts" / "v3"
            / "orchestrator_agent.j2"
        )
        src = path.read_text()
        for symbol in (
            "run_kickoff.try_synthesize",
            "run_kickoff.finalize_kickoff",
        ):
            self.assertIn(
                symbol, src,
                f"orchestrator_agent.j2 must reference {symbol!r} so "
                f"the LLM lane invokes the kickoff coordinator helpers.",
            )


if __name__ == "__main__":
    unittest.main()
