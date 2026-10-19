r"""#1203or: the lane recorded that a tool was unavailable, in the run where it used it.

#1033 established the rule and the action -- *"a blocker resting on a checkable falsehood must
not read like a real one"* -- after r174 lost a run to a FAILED task asserting that
`workhub_add_meeting_decision` was not exposed, which the verifier had called 4/4 times in r172
and 6/6 in r173. It reads `fail_reason` on tasks whose status is `failed`.

The claim is not written there any more. MEASURED over the 95 corpus runs whose run log can be
paired to their tree, with the SHIPPED detector:

    contradicted capability claims        42, in 24 runs
    ...in the modern era (r140+)          30, in 17 runs
    by agent                              verifier 28, orchestrator 2
    where they live                       eventhub_events 30 / 30
    tools named    run_validation 28, registryhub_register_verification_chain 24,
                   bug_create 20, browser_navigate 7, browser_screenshot 7, browser_click 5

★ AND THESE ARE THE TOOLS THAT DECIDE DELIVERY. Hand-checked on the loudest subset: in r177,
r180, r181, r182, r183, r185, r186, r191 and instagram-r175 the verifier SUCCESSFULLY called
`run_validation` 11-48 times and `registryhub_register_verification_chain` 31-84 times in the
SAME run in which it recorded "required `run_validation()` tool is not available on this
verifier tool surface" -- and wrote `validation:api_smoke: NOT RUN` on that basis.
`validation_*` is the corpus's number-one terminal blocker.

★ THE LOGS LOOKED MISSING AND WERE NOT. The modern runs' logs are NOT under the run's own
`logs/` (37 of 38 r140+ trees have no `generation_*.log` at all) -- they sit beside the repo as
`gm_<run>.log`. A first pass read that absence as "cannot judge" for every modern run, which is
the right reflex (#883) and the wrong fact. Pairing is by the log's own `Output directory:`
line, as `verify_1018.py` already does.

★ PRECISION OVER RECALL, and the first version of the detector had it backwards -- see
`capability_claim_tools_1203or`'s docstring and the negative tests below.
"""
from __future__ import annotations

import asyncio
import collections
import glob
import io
import json
import logging
import os
import re
import subprocess
import tempfile
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path if False else False:
        pass
import sys  # noqa: E402
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime.delivery_gate import (  # noqa: E402
    _claim_author_1203or as author_of,
    capability_claim_tools_1203or as tools_in,
    contradicted_capability_claims_1203or as detect,
    record_contradicted_capability_claims_1203or as record)

_CORPUS = ROOT.parent / "generated"
_OFFERED = {"run_validation", "registryhub_register_verification_chain", "bug_create",
            "browser_fill", "browser_navigate", "grep", "seed_audit_check", "read",
            "view_image", "list_reference_images", "workhub_get_task"}


class TheRuleIsThreeConditionsInOneSegment(unittest.TestCase):

    def test_the_shape_that_costs_the_runs(self):
        """r176's own line, verbatim."""
        t = ("validation:api_smoke: NOT RUN — required `run_validation()` tool is unavailable "
             "in this runtime, and business chains could not be registered")
        self.assertEqual(tools_in(t, _OFFERED), ["run_validation"])

    def test_a_list_of_required_tools_in_backticks(self):
        t = ("Verification complete with blocker: required verifier validation tools "
             "(`registryhub_register_verification_chain`, `run_validation`) are not available "
             "on this tool surface")
        self.assertEqual(tools_in(t, _OFFERED),
                         ["registryhub_register_verification_chain", "run_validation"])

    def test_the_name_may_come_after_the_phrase(self):
        t = ("this runtime surface has not exposed the required verifier tools "
             "`registryhub_register_verification_chain`")
        self.assertEqual(tools_in(t, _OFFERED),
                         ["registryhub_register_verification_chain"])

    def test_a_tool_that_was_never_offered_is_not_a_contradiction(self):
        t = "required `submit_retro` tool is not available in this tool subset"
        self.assertEqual(tools_in(t, _OFFERED), [])

    def test_an_empty_offered_set_judges_nothing(self):
        """#883 / #1023b: an empty container is not a fact. A cold store must not be read as
        'nothing was offered to anybody'."""
        t = "required `run_validation()` tool is not available on this verifier tool surface"
        self.assertEqual(tools_in(t, set()), [])
        self.assertEqual(tools_in(t, None), [])

    def test_hostile_input_never_raises(self):
        for junk in (None, 5, {"a": 1}, [1, 2], ""):
            with self.subTest(text=junk):
                self.assertIsInstance(tools_in(junk, _OFFERED), list)


class TheFalsePositivesTheFirstVersionProduced(unittest.TestCase):
    """★ Each of these is a verbatim corpus string that the proximity rule reported and that
    is not a capability claim at all. They are the reason the rule needs backticks AND an
    outcome word in the SAME segment."""

    def test_a_ui_control_is_not_a_tool(self):
        t = ("Fresh validation after backend/frontend ready messages: run_validation passed "
             "(run_8dfb12df86), then UI flow following_suggested_creators failed because the "
             "required follow control was not present/clickable")
        self.assertEqual(tools_in(t, _OFFERED), [],
                         "the absent thing is a button, and run_validation PASSED")

    def test_a_form_input_is_not_a_tool(self):
        t = ("Email fill succeeded, but Password input became unavailable; browser_fill "
             "placeholder=Password timed out and interactable elements reverted to nav "
             "controls.")
        self.assertEqual(tools_in(t, _OFFERED), [],
                         "the absent thing is an input; browser_fill is what was USED")

    def test_a_list_of_granted_tools_is_not_a_list_of_missing_ones(self):
        t = ("Exact blocker on frontend recovery: this action environment exposes "
             "read/view_image/list_reference_images/workhub_get_task, but does not expose "
             "any write-capable file tool")
        self.assertEqual(tools_in(t, _OFFERED), [],
                         "those four are what the lane HAS; none is backticked as missing")

    def test_unrelated_prose_near_the_phrase(self):
        t = ("progress: reconciled reported endpoint breaking changes this step. Re-registered "
             "api.js consumers; grep output for the handler is not available in this note.")
        self.assertEqual(tools_in(t, _OFFERED), [])


class TheAuthorComesFromWhereTheClaimActuallySits(unittest.TestCase):

    def test_a_messagebus_event_names_its_sender_in_the_payload(self):
        """60 of 60 modern claims are in this shape, which is why a task-shaped reader sees
        almost none of them."""
        rec = {"id": "evt_1", "source_hub": "messagebus", "_updated_by": "messagebus",
               "payload": {"from": "verifier", "to": "orchestrator", "content": "x"}}
        self.assertEqual(author_of(rec, {"verifier", "orchestrator"}), "verifier")

    def test_the_hub_that_relayed_it_is_not_the_author(self):
        """★ Without the lane filter, `_updated_by: messagebus` wins -- which is exactly the
        bug that made an early measurement of this report zero events."""
        rec = {"_updated_by": "messagebus", "payload": {"from": "verifier"}}
        self.assertEqual(author_of(rec, {"verifier"}), "verifier")

    def test_a_task_names_its_creator_or_assignee(self):
        self.assertEqual(author_of({"created_by": "orchestrator"}, {"orchestrator"}),
                         "orchestrator")
        self.assertEqual(author_of({"assignee": "backend"}, {"backend"}), "backend")

    def test_an_unknown_author_is_no_author(self):
        self.assertEqual(author_of({"_updated_by": "messagebus"}, {"verifier"}), "")
        self.assertEqual(author_of(None, {"verifier"}), "")


class TheDetectorReadsTheStoresAndTheFile(unittest.TestCase):

    def _hubs(self, tmp, events):
        hub = Path(tmp) / "shared" / "hubs"
        hub.mkdir(parents=True, exist_ok=True)
        (hub / "eventhub_events.json").write_text(
            json.dumps({"_meta": {"version": 1}, **events}), encoding="utf-8")
        return hub

    def _claim(self, text, who="verifier"):
        return {"id": "evt_x", "_updated_by": "messagebus",
                "payload": {"from": who, "content": text}}

    _TXT = ("## Validation Summary - validation:api_smoke: NOT RUN — required "
            "`run_validation()` tool is not available on this verifier tool surface")

    def test_a_claim_in_an_event_is_found_and_attributed(self):
        with tempfile.TemporaryDirectory() as tmp:
            hub = self._hubs(tmp, {"e1": self._claim(self._TXT)})
            rows = detect(hub, {"verifier": {"run_validation"}})
        self.assertEqual(len(rows), 1, rows)
        self.assertEqual((rows[0]["agent"], rows[0]["tools"], rows[0]["store"]),
                         ("verifier", ["run_validation"], "eventhub_events"))

    def test_a_claim_by_an_agent_that_was_not_offered_it_is_not_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            hub = self._hubs(tmp, {"e1": self._claim(self._TXT)})
            rows = detect(hub, {"verifier": {"read"}})
        self.assertEqual(rows, [])

    def test_the_same_claim_twice_in_one_record_is_one_row(self):
        """A record routinely carries its own sentence twice (a comment and the event that
        mirrors it). A detector that reports one claim twice inflates its own ledger."""
        rec = self._claim(self._TXT)
        rec["payload"]["note"] = self._TXT
        with tempfile.TemporaryDirectory() as tmp:
            hub = self._hubs(tmp, {"e1": rec})
            rows = detect(hub, {"verifier": {"run_validation"}})
        self.assertEqual(len(rows), 1, rows)

    def test_an_empty_offered_map_reports_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            hub = self._hubs(tmp, {"e1": self._claim(self._TXT)})
            self.assertEqual(detect(hub, {}), [])
            self.assertEqual(detect(hub, None), [])

    def test_a_missing_hub_dir_reports_nothing(self):
        self.assertEqual(detect("/nonexistent-1203or", {"verifier": {"run_validation"}}), [])

    def test_the_finding_reaches_a_file(self):
        """#947: a detector that only reaches a logger has not reached anything.

        ★ This also guards the trap this module invites: `delivery_gate` imports neither
        `json` nor `Path` at module level, so a bare use inside the recorder would raise
        NameError into its own `except Exception` and return False in silence."""
        with tempfile.TemporaryDirectory() as tmp:
            rows = [{"store": "eventhub_events", "id": "e1", "agent": "verifier",
                     "tools": ["run_validation"], "claim": "x"}]
            self.assertTrue(record(tmp, rows))
            f = Path(tmp) / "logs" / "contradicted_capability_claims_1203or.jsonl"
            self.assertTrue(f.is_file())
            back = [json.loads(l) for l in f.read_text(encoding="utf-8").splitlines() if l]
            self.assertEqual(back, rows)

    def test_a_long_claim_excerpt_declares_its_own_cut(self):
        """#1034, asserted on the OUTPUT. The ratchet for this is a source scan, which a
        shape that still truncates silently can satisfy -- mutation OR12 walked straight
        through it until this test existed."""
        long_claim = ("validation:api_smoke: NOT RUN — required `run_validation()` tool is "
                      "not available on this verifier tool surface. " + ("padding. " * 40))
        with tempfile.TemporaryDirectory() as tmp:
            hub = self._hubs(tmp, {"e1": self._claim(long_claim)})
            rows = detect(hub, {"verifier": {"run_validation"}})
        self.assertEqual(len(rows), 1, rows)
        excerpt = rows[0]["claim"]
        self.assertIn("chars not shown", excerpt,
                      "the excerpt stops mid-sentence and says nothing about it: %r" % excerpt)
        self.assertLess(len(excerpt), len(" ".join(long_claim.split())))

    def test_a_short_claim_is_quoted_whole_with_no_marker(self):
        short = ("required `run_validation()` tool is not available on this verifier tool "
                 "surface")
        with tempfile.TemporaryDirectory() as tmp:
            hub = self._hubs(tmp, {"e1": self._claim(short)})
            rows = detect(hub, {"verifier": {"run_validation"}})
        self.assertEqual(rows[0]["claim"], short)
        self.assertNotIn("not shown", rows[0]["claim"])

    def test_the_recorder_says_no_when_there_is_nothing_to_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertFalse(record(tmp, []))
            self.assertFalse(record(tmp, None))


class TheOfferedSetComesFromWhatWasOffered(unittest.TestCase):

    def test_it_reads_the_1202zc_store_and_splits_on_the_first_colon(self):
        from utils.llm import (offered_tools_by_agent_1203or as offered,
                               record_stage_tool_set_1202zc as rec)
        rec("verifier:action", ["run_validation", "read"])
        rec("verifier:edit_code", ["edit"])
        rec("backend:action", ["read"])
        got = offered()
        self.assertIn("verifier", got)
        self.assertTrue({"run_validation", "read", "edit"} <= got["verifier"],
                        "the union across that agent's stages: %r" % got["verifier"])
        self.assertNotIn("run_validation", got.get("backend", set()))

    def test_a_label_with_no_agent_is_ignored(self):
        from utils.llm import (offered_tools_by_agent_1203or as offered,
                               record_stage_tool_set_1202zc as rec)
        rec(":stage", ["read"])
        self.assertNotIn("", offered())


class TheNoteReachesTheLane(unittest.TestCase):
    """#1203f6: a finding that stops at a detector has not reached anybody."""

    def _run(self, coro):
        loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(loop)
            return loop.run_until_complete(coro)
        finally:
            asyncio.set_event_loop(None)
            loop.close()

    def _dispatch(self, claim_text, offered_tool="run_validation"):
        from multi_agent.runtime.remediation_dispatcher import RemediationDispatcher
        from utils.llm import record_stage_tool_set_1202zc as rec
        rec("verifier:action", [offered_tool])
        tmp = tempfile.mkdtemp()
        hub = Path(tmp) / "shared" / "hubs"
        hub.mkdir(parents=True, exist_ok=True)
        (hub / "eventhub_events.json").write_text(json.dumps({
            "_meta": {"version": 1},
            "e1": {"id": "evt_1", "_updated_by": "messagebus",
                   "payload": {"from": "verifier", "content": claim_text}}}),
            encoding="utf-8")

        sent = []

        class _Bus:
            async def send(self, m):
                sent.append(m)

        class _WH:
            def list_tasks(self):
                return []

            def create_task(self, **kw):
                return {"id": "t1"}

        orch = types.SimpleNamespace(
            hubs=types.SimpleNamespace(workhub=_WH()), message_bus=_Bus(),
            _logger=logging.getLogger("test_1203or"), output_dir=tmp,
            _current_milestone_version="1.2.0")
        self._run(RemediationDispatcher(orch).dispatch_gate_level_checks(
            ["validation_ui_evidence_failed"]))
        return tmp, sent

    _TXT = ("validation:api_smoke: NOT RUN — required `run_validation()` tool is not "
            "available on this verifier tool surface")

    def test_the_verifier_wake_quotes_its_own_contradicted_claim(self):
        tmp, sent = self._dispatch(self._TXT)
        self.assertTrue(sent, "nothing was dispatched at all")
        # ★ the transported body is `payload`; reading `content` returns "" for every
        # message and would have passed the negative test while hiding a dead wire.
        body = " ".join(str(getattr(m, "payload", "") or "") for m in sent)
        self.assertIn("#1203or", body)
        self.assertIn("run_validation", body)

    def test_it_also_lands_the_evidence_in_a_file(self):
        tmp, sent = self._dispatch(self._TXT)
        f = Path(tmp) / "logs" / "contradicted_capability_claims_1203or.jsonl"
        self.assertTrue(f.is_file(), "the claim was quoted but never recorded")

    def test_no_claim_means_no_note(self):
        tmp, sent = self._dispatch("everything was fine in this wake")
        # ★ the transported body is `payload`; reading `content` returns "" for every
        # message and would have passed the negative test while hiding a dead wire.
        body = " ".join(str(getattr(m, "payload", "") or "") for m in sent)
        self.assertTrue(sent)
        self.assertNotIn("#1203or", body)


class TheNoteSaysWhichRoundToUse(unittest.TestCase):
    """★ The one honest reading of "not available in THIS STEP": a `communicate` round forces
    none of these tools, on purpose -- it is the messaging stage. So the note names the stages
    where the tool IS guaranteed, computed from the force-offer map rather than written down
    (a stage list in prose rots -- #1203oa)."""

    def test_the_validation_tools_are_forced_where_the_work_happens(self):
        from multi_agent.runtime.delivery_gate import forced_stages_1203or as forced
        for tool in ("run_validation", "registryhub_register_verification_chain",
                     "bug_create", "browser_navigate", "deliverability_check",
                     "docker_up", "run_start"):
            with self.subTest(tool=tool):
                st = forced(tool)
                self.assertIn("run_checks", st, "%s: forced in %r" % (tool, st))
                self.assertIn("deliver", st, "%s: forced in %r" % (tool, st))
                self.assertNotIn("communicate", st,
                                 "%s is forced in the messaging stage too, so the note's "
                                 "advice to move rounds would be wrong: %r" % (tool, st))

    def test_an_unknown_tool_is_forced_nowhere(self):
        from multi_agent.runtime.delivery_gate import forced_stages_1203or as forced
        self.assertEqual(forced("no_such_tool_1203or"), [])
        self.assertEqual(forced(""), [])
        self.assertEqual(forced(None), [])

    def test_the_wake_tells_the_lane_which_round_to_run_it_from(self):
        t = TheNoteReachesTheLane()
        t.setUp() if hasattr(t, "setUp") else None
        tmp, sent = TheNoteReachesTheLane._dispatch(
            t, ("validation:api_smoke: NOT RUN — required `run_validation()` tool is not "
                "available on this verifier tool surface"))
        body = " ".join(str(getattr(m, "payload", "") or "") for m in sent)
        self.assertIn("run_checks", body)
        self.assertIn("force-offered", body)


class WhatTheCorpusSays(unittest.TestCase):
    """Measured with the shipped detector, against the agent's SUCCESSFULLY CALLED tools --
    a strict subset of what it was offered, so these counts are a lower bound."""

    _MODERN = {"tiktok-web-r191": 1, "tiktok-web-r186": 1, "tiktok-web-r185": 3,
               "tiktok-web-r182": 3, "tiktok-web-r180": 1, "tiktok-web-r177": 1,
               "instagram-core-r176": 3, "instagram-core-r175": 4, "tiktok-web-r173": 2,
               "tiktok-web-r171": 2, "tiktok-web-r169": 1, "tiktok-web-r168": 1}

    def setUp(self):
        if not _CORPUS.is_dir():
            self.skipTest("no corpus on this disk")

    @staticmethod
    def _paired_logs():
        """run dir -> the logs that name it, by the log's own `Output directory:` line."""
        out = collections.defaultdict(list)
        for f in sorted(glob.glob(str(_CORPUS.parent / "*.log"))):
            try:
                with io.open(f, encoding="utf-8", errors="replace") as fh:
                    head = [next(fh, "") for _ in range(40)]
            except Exception:
                continue
            for l in head:
                m = re.search(r"Output directory:\s*(\S+)", l)
                if m:
                    out[os.path.basename(m.group(1).rstrip("/"))].append(f)
                    break
        return out

    def test_the_modern_runs_still_carry_the_measured_claims(self):
        pair = self._paired_logs()
        self.assertGreater(len(pair), 100,
                           "only %d logs could be paired to a run -- the logs live beside the "
                           "repo as gm_<run>.log and the pairing is what makes this "
                           "measurable at all" % len(pair))
        found, judged = {}, 0
        for run, hits in sorted(self._MODERN.items()):
            d = _CORPUS / run
            logs = pair.get(run, []) + glob.glob(str(d / "logs" / "generation_*.log"))
            if not (d.is_dir() and logs):
                continue
            try:
                out = subprocess.run(
                    ["grep", "-ohE", r"\[[a-z_0-9]+\] ✅ [a-z_0-9]+"] + logs,
                    capture_output=True, text=True, timeout=900).stdout
            except Exception as exc:
                self.skipTest("grep unavailable: %s" % exc)
            did = collections.defaultdict(set)
            for l in out.splitlines():
                m = re.match(r"\[([a-z_0-9]+)\] ✅ ([a-z_0-9]+)", l.strip())
                if m:
                    did[m.group(1)].add(m.group(2))
            if not did:
                continue
            judged += 1
            rows = detect(d / "shared" / "hubs", dict(did))
            if rows:
                found[run] = len(rows)
        # ★ ON4's lesson: a ratchet that looked at nothing SKIPS, and a skip passes.
        self.assertEqual(judged, len(self._MODERN),
                         "only %d of the %d measured runs could be read" % (judged,
                                                                            len(self._MODERN)))
        self.assertEqual(found, self._MODERN)

    def test_the_verifier_used_what_it_said_it_did_not_have(self):
        """The fact the whole ticket rests on, asserted directly rather than via the detector."""
        pair = self._paired_logs()
        checked = []
        for run in ("tiktok-web-r191", "tiktok-web-r185", "tiktok-web-r182",
                    "instagram-core-r175"):
            logs = pair.get(run, [])
            if not logs:
                continue
            try:
                out = subprocess.run(
                    ["grep", "-ohc", r"\[verifier\] ✅ run_validation"] + logs,
                    capture_output=True, text=True, timeout=900).stdout
            except Exception as exc:
                self.skipTest("grep unavailable: %s" % exc)
            n = sum(int(x) for x in out.split() if x.strip().isdigit())
            checked.append((run, n))
            self.assertGreater(n, 10, "%s: the verifier called run_validation %d times" % (run, n))
        self.assertEqual(len(checked), 4, "scanned %r" % checked)


if __name__ == "__main__":
    unittest.main()
