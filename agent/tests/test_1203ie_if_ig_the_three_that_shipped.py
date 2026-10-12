"""#1203ie / #1203if / #1203ig — the three defects that were still reaching a release.

#1203ie  `#1202w0` measures list endpoints whose `total` their own cursor cannot reach --
         "the rest of the data is unreachable through the app" -- and published it only to a
         log line and an artifact. 24 runs carry it (r142..r184, two domains), 10 distinct
         endpoints, never self-resolving; tiktok-web-r184's release-v1.1.0 ships two. #1203i9
         proved the contract prose does not move the lane. Now published in the gate result on
         #1139's exact terms: evidence the orchestrator can file a fix from, NEVER a
         failed_check (#1023: "a new blocking check cannot be validated without a full run,
         and this codebase has paid for false blocks repeatedly").

#1203if  An unchanged-payload 400 (#1203i8) kills the CONVERSATION, not one call: r184's
         frontend lost 49 consecutive calls across four phases. The cause is unknown after six
         eliminations, so nothing is asserted about which image is at fault -- the images are
         dropped ONCE and re-sent, and the original error is re-raised unchanged if that also
         fails. Plus the part census the six investigations lacked.

#1203ig  #1203hy correctly refuses `delivered` when no release was cut -- but r184 cut the
         release five seconds LATER, and nothing came back, so the ledger ended with M4
         `active` beside a real 1.3.0 tag. 4-of-4 reported as 3.
"""
import json
import logging
import os
import sys

import pytest

_AGENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _AGENT)

from env_generator.llm_generator.multi_agent.runtime.delivery_gate import (  # noqa: E402
    list_totals_unreachable_1203ie as totals,
)
from utils.llm import (  # noqa: E402
    _nontext_shape_1203if as census,
    _strip_inline_images_1203if as strip,
)


# ---------------------------------------------------------------- #1203ie
def _artifact(tmp_path, *records):
    d = tmp_path / "logs"
    d.mkdir(parents=True, exist_ok=True)
    with open(d / "list_total_unreachable_1202w0.jsonl", "w", encoding="utf-8") as fh:
        for r in records:
            fh.write(json.dumps(r) + "\n")
    return tmp_path


# verbatim from r184's artifact
R184 = {"at": 1.0, "count": 2,
        "endpoints": ["/api/videos/feed total=5 is not the collection size",
                      "/api/comments total=3 is not the collection size"]}


def test_the_newest_record_is_what_the_gate_sees(tmp_path):
    """Validation appends one record per pass, so the LAST is the current state. A union
    would keep naming endpoints the lane has since fixed."""
    old = {"at": 0.0, "count": 1, "endpoints": ["/api/stale total=1"]}
    got = totals(_artifact(tmp_path, old, R184))
    assert len(got) == 2
    assert any("/api/videos/feed" in g for g in got)
    assert not any("/api/stale" in g for g in got), "a fixed endpoint is still being named"


def test_an_empty_or_absent_artifact_is_silent(tmp_path):
    assert totals(tmp_path) == []                      # no logs/ at all
    assert totals(_artifact(tmp_path)) == []           # file exists, no records
    assert totals(None) == []


def test_a_corrupt_line_does_not_lose_the_good_one(tmp_path):
    d = tmp_path / "logs"
    d.mkdir(parents=True)
    with open(d / "list_total_unreachable_1202w0.jsonl", "w", encoding="utf-8") as fh:
        fh.write(json.dumps(R184) + "\n")
        fh.write("{not json\n")
    assert len(totals(tmp_path)) == 2


def test_it_is_evidence_and_never_a_failed_check():
    """★ THE GUARD, and the whole reason this shape was chosen. #1023's rule is explicit;
    if a later edit adds this key to `failed_checks` it would block every one of the 24 runs
    that carry the finding."""
    import pathlib
    src = pathlib.Path(
        _AGENT, "env_generator/llm_generator/multi_agent/runtime/delivery_gate.py"
    ).read_text(encoding="utf-8")
    assert '"list_totals_unreachable_1203ie": list_totals_unreachable_1203ie(' in src
    # the key must not be appended to failed_checks anywhere
    for ln in src.splitlines():
        if "failed_checks" in ln and "1203ie" in ln:
            raise AssertionError("the #1203ie evidence became a blocking check: %r" % ln)


# ---------------------------------------------------------------- #1203if
IMG = {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}}
TXT = {"type": "text", "text": "hi"}


def test_the_images_are_replaced_by_placeholders_not_removed():
    msgs = [{"role": "user", "content": [TXT, IMG, IMG]}]
    out, n = strip(msgs)
    assert n == 2
    parts = out[0]["content"]
    assert len(parts) == 3, "a part was deleted instead of replaced — positions shifted"
    assert all(p["type"] == "text" for p in parts)
    assert "#1203if" in parts[1]["text"]


def test_the_callers_payload_is_never_mutated():
    """`_retry_with_backoff` may still hold it and the original exception is re-raised on
    failure, so the un-pruned payload has to stay intact."""
    msgs = [{"role": "user", "content": [TXT, IMG]}]
    before = json.dumps(msgs)
    strip(msgs)
    assert json.dumps(msgs) == before


def test_nothing_to_drop_returns_the_original_and_zero():
    msgs = [{"role": "user", "content": [TXT]}, {"role": "user", "content": "plain"}]
    out, n = strip(msgs)
    assert n == 0 and out is msgs


@pytest.mark.parametrize("bad", [None, "str", 42, [{"role": "user"}], [None]])
def test_hostile_payloads_do_not_raise(bad):
    out, n = strip(bad)
    assert n == 0
    assert census(bad)                      # returns prose, never raises


def test_the_census_names_types_and_positions():
    """The six #1202w0-era investigations all had to ASSUME the non-text parts were images,
    because `nontext:N` carries no types and no positions. This is that missing line."""
    msgs = [{"role": "system", "content": "s"},
            {"role": "user", "content": [TXT, IMG, IMG]},
            {"role": "user", "content": [{"type": "input_audio", "input_audio": {}}]}]
    out = census(msgs)
    assert "3 non-text part(s)" in out
    assert "msg1:image_urlx2" in out
    assert "msg2:input_audiox1" in out, out


def test_the_census_says_so_when_there_are_no_images():
    """The case that would be NEW information: a payload refused 'for an image' that carries
    none. All six eliminated causes assumed images."""
    assert "no non-text part" in census([{"role": "user", "content": [TXT]}])


# ---------------------------------------------------------------- #1203ig
def _ig_block(src: str) -> str:
    """The #1203ig block, sliced between LANDMARKS rather than by a byte count.

    The first version took `[:2600]` after the marker and the comment alone is longer than
    that, so the assertions were reading prose and the code was out of frame — #943's rule
    ("no fixed-width source windows in tests, use landmark anchors") exists for exactly
    this, and I had written tests about it the same day."""
    start = src.index("#1203ig: RECONCILE THE MILESTONE")
    end = src.index("milestone_reconcile_1203ig", start)
    return src[start:end]


def _ig_code(src: str) -> str:
    """The same block with COMMENT lines removed.

    An absence assertion has to read the code, not the prose: the block's comment names
    `self._current_milestone_index` while explaining that it does not exist, so asserting
    that string is absent from the raw text fails on my own explanation. Third time this
    session (the #1203ia and #1203ic tests each hit it once)."""
    return "\n".join(ln for ln in _ig_block(src).splitlines()
                      if not ln.strip().startswith("#"))


def test_the_reconcile_asks_hys_own_question_and_uses_real_locals():
    """★ Two guards in one. The predicate must be hy's (#1032: one owner), and the first
    draft reached for `self._current_milestone_index` / `self._m_idx`, neither of which
    exists — it would have been inert at every call, exactly like the
    `locals().get("safe_messages")` draft of #1203i8."""
    import pathlib
    src = pathlib.Path(
        _AGENT, "env_generator/llm_generator/multi_agent/orchestrator.py"
    ).read_text(encoding="utf-8")
    blk = _ig_block(src)
    assert "_milestone_release_state_1203hy(str(_ver)) == \"yes\"" in blk, (
        "the reconcile no longer asks #1203hy's predicate")
    assert "mark_status(\n" in blk or "mark_status(" in blk
    code = _ig_code(src)
    assert "_current_milestone_index" not in code, "the non-existent attribute came back"
    assert "getattr(self, \"_m_idx\"" not in code, "the non-existent attribute came back"
    # and it must only ever write `delivered`, never any other status
    assert blk.count('"delivered"') >= 1
    for forbidden in ('"active"', '"pending"', '"failed"'):
        assert forbidden not in code, "the reconcile writes a status other than delivered"


def test_the_reconcile_cannot_fire_without_a_release():
    """The unsafe direction — recording a delivery that never shipped — is what #1203hy
    exists to prevent, so it must stay closed: the only accepted state is "yes"."""
    import pathlib
    src = pathlib.Path(
        _AGENT, "env_generator/llm_generator/multi_agent/orchestrator.py"
    ).read_text(encoding="utf-8")
    code = _ig_code(src)
    assert '== "yes"' in code
    assert '!= "no"' not in code, (
        "'not no' would also accept `unknown`, which hy deliberately leaves alone")


# ---------------------------------------------------------------- #1203ii
def test_the_evidence_has_a_consumer_not_just_a_key():
    """★ #1203ii — THE HALF I ALMOST SHIPPED WITHOUT.

    #1203ie copies #1139: put the finding in the gate result. #1148's docstring is the
    warning about stopping there, about #1139 itself:

        "#1139 detects it and stops there — the finding is placed in the gate result
         (`never_matching_filters`) and NOTHING reads that key. It is #1041's shape
         exactly: the evidence exists, the party who can act on it is never told."

    So a gate-result key with no reader is the very family this session spent its time on.
    Pinned over the AST: the dispatcher must exist, must call #1203ie's reader, must create a
    task, and must be AWAITED from the orchestrator — `#706b` is on record that a hook present
    at one of two call sites reads as correct in unit tests and never runs.
    """
    import ast
    import pathlib

    rd = pathlib.Path(
        _AGENT, "env_generator/llm_generator/multi_agent/runtime/remediation_dispatcher.py"
    ).read_text(encoding="utf-8")
    tree = ast.parse(rd)
    fn = next((n for n in ast.walk(tree)
               if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
               and n.name == "dispatch_list_totals_unreachable_1203ii"), None)
    assert fn is not None, "#1203ie's finding has no dispatcher — nothing reads the key"
    # Pinned on the IMPORT node, not on `ast.dump(fn)`: the dump includes the docstring,
    # which names the reader while explaining it — swapping the import for #1139's reader
    # left this green as a mutation. Fourth time this round an assertion read my own prose.
    imported = {a.name for n in ast.walk(fn) if isinstance(n, ast.ImportFrom)
                for a in n.names}
    assert "list_totals_unreachable_1203ie" in imported, (
        "the dispatcher does not import #1203ie's reader (found: %s), so it cannot be "
        "about this finding" % sorted(imported))
    calls = {n.func.attr for n in ast.walk(fn)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
    assert "create_task" in calls, "the dispatcher tells nobody"

    orch = pathlib.Path(
        _AGENT, "env_generator/llm_generator/multi_agent/orchestrator.py"
    ).read_text(encoding="utf-8")
    otree = ast.parse(orch)
    awaited = [n for n in ast.walk(otree)
               if isinstance(n, ast.Await)
               and isinstance(n.value, ast.Call)
               and isinstance(n.value.func, ast.Attribute)
               and n.value.func.attr == "dispatch_list_totals_unreachable_1203ii"]
    assert awaited, (
        "the dispatcher is never awaited from the orchestrator — defined and unreachable, "
        "which is exactly the shape #1041/#1148 describe")


def test_the_dispatch_is_a_task_and_never_a_blocking_check():
    """#1148's reasoning, carried over: "a task is worked, a check is a wall, and a new wall
    cannot be validated without a run"; #1023 adds that false blocks have been paid for
    repeatedly. Blocking this would have blocked all 24 runs that carry the finding."""
    import pathlib
    rd = pathlib.Path(
        _AGENT, "env_generator/llm_generator/multi_agent/runtime/remediation_dispatcher.py"
    ).read_text(encoding="utf-8")
    blk = rd.split("async def dispatch_list_totals_unreachable_1203ii")[1]
    blk = blk.split("async def dispatch_never_matching_filters_1148")[0]
    code = "\n".join(ln for ln in blk.splitlines() if not ln.strip().startswith("#"))
    assert "failed_checks" not in code, "the dispatch turned the finding into a blocker"
    assert 'priority="P1"' in code, "severity changed without the docstring's reasoning"
    assert 'assignee="backend"' in code, "the owner of a handler's `total` is the backend"
