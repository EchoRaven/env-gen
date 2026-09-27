"""#1202vv: the notice that a meeting CLOSED does not need to re-send the meeting.

#679 measured the sender side for task lifecycle events and deliberately left `task_created`
untouched — #274's wedge verbatim, the first delivery is the one the recipient needs. The
meeting pair has the same two halves and only the first was ever considered.

Measured over the corpus, `meeting_closed` payloads:

    269 events, 10.8M chars of `document`, of which `document["metadata"]` is 10.66M — 98.6%,
    mean 39,631 chars. Every other key in the record together is ~370 chars.
    Median payload 31,931, p90 74,926, fanning out to 3 recipients: ~182K chars per run,
    and the single largest message any agent's inbox receives.

It is a re-send, on #679's own argument: 264 of the 269 go to exactly the agents that already
received `meeting_created` for that meeting, and 268 of 269 had `meeting_decision_added`
delivered incrementally — a median of 27 per meeting.

Recoverable, which is the condition #274's wedge failed: `meeting_id` is a valid key of the
documents store in 269 of 269 corpus cases, so `workhub_get_document(document_id=<meeting_id>)`
returns the whole record.

Narrow on purpose: one key is replaced and the record's shape is untouched, so a reader doing
`payload["document"]["status"]` still works — which the #679-era meeting test does, and which
is why its small mock document passes through byte-identical.
"""
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime.hubs.workhub import service as SVC   # noqa: E402

_TRIM = SVC._closed_meeting_document_1202vv
_CAP = SVC._MEETING_METADATA_CHARS_1202vv


def _doc(metadata):
    return {"id": "doc_meeting_1", "title": "Milestone kickoff", "kind": "meeting",
            "status": "closed", "attendees": ["backend", "verifier"],
            "closed_at": 1.0, "closed_by": "orchestrator", "metadata": metadata}


def test_a_small_record_passes_through_byte_identical():
    """Below the threshold nothing changes, so every existing reader and test is untouched."""
    d = _doc({"agenda": "short"})
    assert _TRIM(d, "doc_meeting_1") == d
    assert _TRIM(d, "doc_meeting_1") is d or _TRIM(d, "doc_meeting_1") == d


def test_a_large_metadata_becomes_a_pointer():
    big = {"agenda": "x" * (_CAP + 1), "requirements": ["y" * 500], "decisions": ["z" * 500]}
    out = _TRIM(_doc(big), "doc_meeting_1")
    note = (out.get("metadata") or {}).get("_body_omitted") or ""
    assert note, "the metadata must be replaced by a stated omission, not dropped"
    assert "workhub_get_document" in note, "the pointer must name the tool"
    assert "doc_meeting_1" in note, "the pointer must carry the id that resolves"
    assert str(len(str(big))) in note, "the omission must say how much was omitted"
    assert len(str(out)) < len(str(_doc(big))) // 2, "the notice must actually be smaller"


def test_every_other_field_survives():
    """The shape is what existing readers key on — `payload["document"]["status"]` among
    them. Only `metadata` is traded."""
    big = {"agenda": "x" * (_CAP + 1)}
    src = _doc(big)
    out = _TRIM(src, "doc_meeting_1")
    assert sorted(out) == sorted(src), "the record's key set must not change"
    for k, v in src.items():
        if k == "metadata":
            continue
        assert out[k] == v, f"{k} was altered"


def test_the_store_still_holds_everything():
    """The notice is trimmed; the record is not. A trim that mutated the document would make
    the pointer point at the same hole."""
    big = {"agenda": "x" * (_CAP + 1)}
    src = _doc(big)
    _TRIM(src, "doc_meeting_1")
    assert src["metadata"] == big, "the source record must not be mutated"


def test_a_missing_or_odd_record_is_returned_untouched():
    assert _TRIM(None, "m") is None
    assert _TRIM("not a dict", "m") == "not a dict"
    assert _TRIM({"id": "m"}, "m") == {"id": "m"}          # no metadata at all
    assert _TRIM({"id": "m", "metadata": None}, "m") == {"id": "m", "metadata": None}


def test_the_emit_site_uses_it():
    """AST, not a source window (#943): the notice-building call must be the one that reaches
    the emit, or the helper is dead code."""
    import ast
    import inspect

    fn = next(n for n in ast.walk(ast.parse(inspect.getsource(SVC)))
              if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
              and "meeting_closed" in ast.unparse(n))
    body = ast.unparse(fn)
    assert "_closed_meeting_document_1202vv" in body, (
        "close_meeting must build its notice through the helper")


def test_the_threshold_is_the_one_the_helper_uses():
    """A constant that two places spell separately drifts (#1032)."""
    import ast
    import inspect

    src = inspect.getsource(SVC._closed_meeting_document_1202vv)
    nums = [n.value for n in ast.walk(ast.parse(src.strip()))
            if isinstance(n, ast.Constant) and isinstance(n.value, int) and n.value > 100]
    assert not nums, f"the helper must read the named constant, not a literal: {nums}"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
