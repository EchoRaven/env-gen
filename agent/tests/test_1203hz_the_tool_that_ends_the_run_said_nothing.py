"""#1203hz: every outcome of `deliver_project` was unobservable — and it ends the run.

The tool has four rejection paths — the self-asserted checklist, GUARD 1 (not the final
milestone), GUARD 2 (the live endpoint / business_chain / deliverability re-check) and GUARD
2c (the visual deferral) — and each returns `ToolResult(success=False, error_message=...)`.
That string goes to the calling LLM and nowhere else; nothing writes it to the run log. The
only line the log gets is `🚀 DELIVER_PROJECT`, emitted by the tool DISPATCHER
(tooling.py:1413) BEFORE execute runs, so it records that the tool was CALLED and says
nothing about what it answered.

Measured over 198 run logs: 911 `🚀 DELIVER_PROJECT` lines across 78 runs, and ZERO
occurrences of any of the four refusal texts. That is not evidence the guards never fire — it
is the absence of evidence either way, and it made a real question unanswerable. Six runs died
on `RuntimeError: Delivery gate failed`; two (r119, r171) died on `business_chain_failing`,
which is PRECISELY what GUARD 2 evaluates. Whether GUARD 2 passed it minutes earlier (a race)
or never ran (it has four silent fail-open paths, each producing an empty blocker list
indistinguishable from "clear") cannot be told from anything on disk.

★ I read that absence as "no refusals happened" while working on #1203hy, stated it, and had
to retract it. The log is now the record.

Purely observational: the ToolResults are unchanged, down to every word of error_message,
because the LLM reads those and other tests anchor on them.
"""
from __future__ import annotations

import ast
import inspect
import logging
import sys
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime.hub_registry import HubRegistry  # noqa: E402
from tools import agent_interaction_tools as _ait  # noqa: E402
from tools.agent_interaction_tools import DeliverProjectTool  # noqa: E402

GOOD = {"no_bugs": True, "requirements_met": True,
        "fully_functional": True, "docker_ok": True}


class _Event:
    def __init__(self): self.set_called = False
    def set(self): self.set_called = True


class _Agent:
    def __init__(self, hubs=None, final=True):
        self._hubs = hubs
        self._is_final_milestone = final
        self._milestone_progress = (2, 4)
        self._project_delivered = False
        self._project_delivered_event = _Event()


def _tool(hubs=None, final=True):
    return DeliverProjectTool(agent=_Agent(hubs, final))


def _hz(caplog):
    return [r.getMessage() for r in caplog.records if "#1203hz" in r.getMessage()]


# ------------------------------------------------------------------ each refusal speaks


def test_a_bad_confirmation_is_recorded(caplog):
    with caplog.at_level(logging.WARNING):
        res = _tool().execute("yes please", "summary", GOOD)
    assert res.success is False
    said = _hz(caplog)
    assert len(said) == 1, said
    assert "REFUSED" in said[0], said[0]
    # the word the caller actually sent, so a wrong-confirmation loop is diagnosable
    assert "yes please" in said[0], said[0]


def test_a_failed_self_asserted_checklist_is_recorded(caplog):
    with caplog.at_level(logging.WARNING):
        res = _tool().execute("CONFIRMED", "summary", {"no_bugs": True})
    assert res.success is False
    said = _hz(caplog)
    assert len(said) == 1, said
    assert "checklist" in said[0], said[0]
    for missing in ("requirements_met", "fully_functional", "docker_ok"):
        assert missing in said[0], said[0]


def test_guard_1_names_itself_and_the_milestone(caplog):
    with caplog.at_level(logging.WARNING):
        res = _tool(final=False).execute("CONFIRMED", "summary", GOOD)
    assert res.success is False
    said = _hz(caplog)
    assert len(said) == 1, said
    assert "GUARD 1" in said[0], said[0]
    assert "2 of 4" in said[0], said[0]


def test_the_accepted_case_is_recorded_too(caplog):
    """The one outcome that ENDS THE RUN must be in the log beside the refusals."""
    t = _tool()                      # no hubs → GUARD 2 cannot evaluate, so it passes
    with caplog.at_level(logging.WARNING):
        res = t.execute("CONFIRMED", "summary", GOOD)
    assert res.success is True
    said = _hz(caplog)
    assert len(said) == 1, said
    assert "ACCEPTED" in said[0], said[0]
    assert t.agent._project_delivered_event.set_called is True


def test_guard_2_names_itself_and_the_live_blockers(tmp_path, caplog):
    hubs = HubRegistry(str(tmp_path))
    rh = hubs.registryhub
    rh.register_endpoint("GET", "/api/items", agent="backend", status="declared")
    with caplog.at_level(logging.WARNING):
        res = _tool(hubs).execute("CONFIRMED", "summary", GOOD)
    assert res.success is False, "an unimplemented endpoint should not deliver"
    said = _hz(caplog)
    assert len(said) == 1, said
    assert "GUARD 2" in said[0], said[0]
    assert "implemented" in said[0], said[0]


# --------------------------------------------------------- it changes nothing but the log


def test_every_refusal_text_is_untouched():
    """The error_message strings go to the LLM; #1203hz must not have reworded one."""
    src = inspect.getsource(DeliverProjectTool.execute)
    for phrase in (
        "Confirmation must be exactly 'CONFIRMED'",
        "Cannot deliver project. Failed checks:",
        "deliver_project is the FINAL delivery and ENDS the run",
        "deliver_project BLOCKED",
        "deliver_project DEFERRED",
    ):
        assert phrase in src, phrase


def test_a_broken_logger_cannot_break_the_tool(monkeypatch):
    """Observability must never be able to fail the delivery it is recording."""
    class _Boom:
        def getLogger(self, *a, **k): raise RuntimeError("no logging today")
    import builtins
    real_import = builtins.__import__

    def fake_import(name, *a, **k):
        if name == "logging":
            return _Boom()
        return real_import(name, *a, **k)
    monkeypatch.setattr(builtins, "__import__", fake_import)
    res = _tool().execute("CONFIRMED", "summary", GOOD)
    assert res.success is True


# ------------------------------------------------------------------------- structural


def test_no_refusal_can_be_added_without_a_line_in_the_log():
    """★ The point of the patch: a future return site that forgets to speak puts the tool
    back where it was. Every `return ToolResult(success=False)` in execute must be
    immediately preceded by a `_say_1203hz` call in the same block."""
    tree = ast.parse(textwrap.dedent(inspect.getsource(DeliverProjectTool.execute)))
    fn = tree.body[0]

    def returns_failure(node):
        return (isinstance(node, ast.Return) and isinstance(node.value, ast.Call)
                and getattr(node.value.func, "id", None) == "ToolResult"
                and any(k.arg == "success" and isinstance(k.value, ast.Constant)
                        and k.value.value is False for k in node.value.keywords))

    def says(node):
        return (isinstance(node, ast.Expr) and isinstance(node.value, ast.Call)
                and getattr(node.value.func, "attr", None) == "_say_1203hz")

    checked = 0
    for parent in ast.walk(fn):
        body = getattr(parent, "body", None)
        for seq in (body, getattr(parent, "orelse", None), getattr(parent, "finalbody", None)):
            if not isinstance(seq, list):
                continue
            for i, st in enumerate(seq):
                if not returns_failure(st):
                    continue
                checked += 1
                assert i > 0 and says(seq[i - 1]), (
                    "a ToolResult(success=False) at line %d is not preceded by "
                    "_say_1203hz" % st.lineno)
    assert checked == 5, "expected 5 refusal returns, found %d" % checked


def test_the_success_return_is_also_announced():
    tree = ast.parse(textwrap.dedent(inspect.getsource(DeliverProjectTool.execute)))
    calls = [n for n in ast.walk(tree)
             if isinstance(n, ast.Call)
             and getattr(n.func, "attr", None) == "_say_1203hz"]
    assert len(calls) == 6, "expected 6 announcements (5 refusals + 1 accept), got %d" % len(calls)
    outcomes = [a.value for c in calls for a in c.args[:1] if isinstance(a, ast.Constant)]
    assert any("ACCEPTED" in str(o) for o in outcomes), outcomes


def test_the_dispatcher_line_is_not_the_outcome():
    """`🚀 DELIVER_PROJECT` lives in the DISPATCHER and fires before execute — the premise
    that made the corpus measurement meaningless. If it ever moves into the tool, the
    reasoning in this file's docstring has to be revisited.

    ★ A plain `not in src` fails on THIS patch's own comment, which quotes the marker to
    explain it — the sub-class of locator bug that has now bitten the byte-window ratchet
    twice today. The predicate has to be the real one: is that string an argument to a CALL
    in this module (a log line), rather than anywhere in its text."""
    tree = ast.parse(inspect.getsource(_ait))
    emitting = []
    for n in ast.walk(tree):
        if not isinstance(n, ast.Call):
            continue
        for lit in ast.walk(n):
            if isinstance(lit, ast.Constant) and isinstance(lit.value, str) \
                    and "DELIVER_PROJECT" in lit.value:
                emitting.append(lit.value[:60])
    assert emitting == [], (
        "the dispatcher's call-time line is now emitted from the tool module; re-read "
        "#1203hz: %r" % (emitting,))
