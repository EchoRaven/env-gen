"""#1202mo: "the contract is already complete" must mean THIS milestone's contract.

`#1202er` skips a kickoff attendee's corrective turns when the contract already
exists, so a resume does not pay two LLM turns to re-declare what an earlier
process settled. Its predicate was `bool(endpoints) and bool(tables)` — "is there
any contract at all" — which is True for every milestone after the first.

Measured in tiktok-r123, from each registry record's creation time against the
run's release boundaries: M2 added 14 NEW endpoints, M3 added 8 more and 12
tables. Both kickoffs were told the contract was already complete.

The fix narrows the question to what #1202er's own docstring said it was for —
"This is the resume case" — namely: did an EARLIER kickoff for this SAME milestone
already close having produced a contract?

Replayed against the real meeting documents on disk, each kickoff seeing only the
meetings that existed when it opened:
    r123 resume M1  -> True   (earlier closed M1 meeting)     skip, as before
    r123 M2         -> False                                   was True
    r123 M3         -> False                                   was True
    r124 resume M1  -> True   (earlier closed M1 meeting)     skip, as before
"""
import ast
import sys
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for _p in (str(ROOT), str(LLM_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from multi_agent.agents.runtime import messaging as MS  # noqa: E402

OWNER = next(c for c in vars(MS).values()
             if isinstance(c, type) and "_contract_already_complete_1202er" in vars(c))


class _Store:
    def __init__(self, d):
        self._d = d

    def value(self):
        return self._d


def _agent(documents, endpoints=None, tables=None):
    """A stand-in carrying exactly the two hubs the predicate reads, in the
    shapes the real stores hold (records keyed by id, a `_meta` entry)."""
    eps = {"_meta": {}, **(endpoints if endpoints is not None else {"GET /api/videos": {}})}
    tbl = {"_meta": {}, **(tables if tables is not None else {"videos": {}})}
    hubs = types.SimpleNamespace(
        registryhub=types.SimpleNamespace(
            get_endpoints=lambda: {k: v for k, v in eps.items() if k != "_meta"},
            list_tables=lambda: {k: v for k, v in tbl.items() if k != "_meta"}),
        workhub=types.SimpleNamespace(
            stores=types.SimpleNamespace(documents=_Store({"_meta": {}, **documents}))))
    return types.SimpleNamespace(_hubs=hubs)


def _meeting(ms, status="closed", artifacts=("contract", "task_tree", "predicates")):
    return {"kind": "kickoff", "status": status,
            "metadata": {"milestone_index": ms, "produced_artifacts": list(artifacts)}}


def _ask(agent, meeting_id, ms):
    return OWNER._contract_already_complete_1202er(
        agent, meeting_id=meeting_id, milestone_index=ms)


class ItAnswersAboutThisMilestone(unittest.TestCase):

    def test_a_resume_of_a_milestone_whose_kickoff_already_closed_skips(self):
        """The case #1202er exists for, and it must keep working."""
        agent = _agent({"doc_old_m1": _meeting(1), "doc_new_m1": _meeting(1, "open")})
        self.assertTrue(_ask(agent, "doc_new_m1", 1))

    def test_M2_is_not_complete_because_M1_is(self):
        """The defect. r123's M2 added 14 endpoints the registry did not have."""
        agent = _agent({"doc_m1": _meeting(1), "doc_m2": _meeting(2, "open")})
        self.assertFalse(_ask(agent, "doc_m2", 2),
                         "M2 was told M1's contract is its own")

    def test_M3_after_two_closed_milestones_is_still_not_complete(self):
        agent = _agent({"doc_m1": _meeting(1), "doc_m2": _meeting(2),
                        "doc_m3": _meeting(3, "open")})
        self.assertFalse(_ask(agent, "doc_m3", 3))

    def test_a_fresh_first_milestone_is_not_complete(self):
        agent = _agent({"doc_m1": _meeting(1, "open")}, endpoints={}, tables={})
        self.assertFalse(_ask(agent, "doc_m1", 1))


class WhatItMustNotCountAsEvidence(unittest.TestCase):

    def test_the_current_meeting_does_not_vouch_for_itself(self):
        agent = _agent({"doc_m1": _meeting(1)})
        self.assertFalse(_ask(agent, "doc_m1", 1))

    def test_an_earlier_meeting_that_never_closed_is_not_a_settled_contract(self):
        agent = _agent({"doc_old": _meeting(1, "open"), "doc_new": _meeting(1, "open")})
        self.assertFalse(_ask(agent, "doc_new", 1))

    def test_a_closed_meeting_that_produced_no_contract_is_not_enough(self):
        agent = _agent({"doc_old": _meeting(1, artifacts=("task_tree",)),
                        "doc_new": _meeting(1, "open")})
        self.assertFalse(_ask(agent, "doc_new", 1))

    def test_an_empty_registry_never_counts_as_complete(self):
        """#1202er's own rule: this must not become a way for an empty kickoff to
        advance, whatever the meeting history says."""
        agent = _agent({"doc_old": _meeting(1), "doc_new": _meeting(1, "open")},
                       endpoints={}, tables={})
        self.assertFalse(_ask(agent, "doc_new", 1))

    def test_a_non_kickoff_document_is_ignored(self):
        doc = _meeting(1)
        doc["kind"] = "design"
        agent = _agent({"doc_design": doc, "doc_new": _meeting(1, "open")})
        self.assertFalse(_ask(agent, "doc_new", 1))

    def test_an_unknown_milestone_runs_the_corrective_turns(self):
        """Costs a turn; never skips a declaration a milestone needs."""
        agent = _agent({"doc_old": _meeting(1), "doc_new": _meeting(1, "open")})
        self.assertFalse(_ask(agent, "doc_new", None))

    def test_a_malformed_store_answers_false_rather_than_raising(self):
        hubs = types.SimpleNamespace(
            registryhub=types.SimpleNamespace(get_endpoints=lambda: {"x": 1},
                                              list_tables=lambda: {"y": 1}),
            workhub=None)
        self.assertFalse(OWNER._contract_already_complete_1202er(
            types.SimpleNamespace(_hubs=hubs), meeting_id="m", milestone_index=1))


class TheCallSitePassesTheScope(unittest.TestCase):
    """A milestone-scoped predicate called without its milestone is the old,
    blind predicate with extra steps — and silently so, because both kwargs
    default to None and None answers False."""

    def test_the_kickoff_handler_passes_meeting_and_milestone(self):
        src = (LLM_DIR / "multi_agent" / "agents" / "runtime" / "messaging.py"
               ).read_text(encoding="utf-8")
        calls = [n for n in ast.walk(ast.parse(src))
                 if isinstance(n, ast.Call)
                 and getattr(n.func, "attr", None) == "_contract_already_complete_1202er"]
        self.assertTrue(calls, "the predicate is no longer called at all")
        for c in calls:
            kw = {k.arg for k in c.keywords}
            self.assertEqual(kw, {"meeting_id", "milestone_index"},
                             "call at line %d does not pass the milestone scope" % c.lineno)


if __name__ == "__main__":
    unittest.main()
