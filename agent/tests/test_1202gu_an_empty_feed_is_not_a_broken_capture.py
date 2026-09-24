"""#1202gu — "fix that capture" is the wrong instruction when the collection is EMPTY.

r100, live: 38 of 73 chain steps 404'd, every one of them carrying

    SUBSTITUTED ${videoId} save failed at step '/api/videos' (response lacked the save path)
    — the ladder sent an UNRELATED id — fix that capture, not this endpoint.

The capture was correct. The chain declares `save: {videoId: "items.0.id"}` on a step with
`expect=[200]`, the step returned 200, and `GET /api/videos` answers `{"items": [...], ...}`.
What went wrong is that the projected read is owner-scoped —
`db.query(Video).filter(author_id == _fw_owner_val(...))` — so the verifier's fresh actor owns
no rows, `items` came back EMPTY, and `items.0.id` therefore resolved to nothing.

Telling the lane to "fix that capture" sends it to re-author a chain that is already right,
and hides the actual cause. The framework holds every fact needed to tell the two apart: it
has the 200, it has the payload it just failed to dig, and the container it was digging into
is present and empty. Same shape as #1202gb, #1202fr, #1202gs and #1202gt: an actionable fact
held, a category reported.

An EMPTY collection and a MISSING path are different defects with different owners — empty is
a data/scoping question for the backend, missing is a capture/envelope question for whoever
authored the chain — so the note has to name which one it is.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime.chain_executor import _save_miss_reason_1202gu  # noqa: E402

# The real r100 shapes: the envelope the projector emits, and the save the verifier authored.
_EMPTY = {"items": [], "total": 0}
_FULL = {"items": [{"id": 7, "caption": "x"}], "total": 1}


def test_an_empty_collection_is_named_as_empty():
    why = _save_miss_reason_1202gu(_EMPTY, "items.0.id")
    assert "empty" in why.lower(), why
    assert "items" in why, "the note does not say WHICH collection was empty: %s" % why


def test_an_empty_collection_does_not_blame_the_capture():
    why = _save_miss_reason_1202gu(_EMPTY, "items.0.id")
    assert "capture is correct" in why.lower(), (
        "does not say the chain is fine, so the lane still re-authors it: %s" % why)
    assert "fix" not in why.lower(), (
        "still issues a fix-the-capture instruction on an empty feed: %s" % why)


def test_a_genuinely_missing_path_still_reads_as_a_capture_problem():
    """#647 — the old wording is right for the case it was written for; keep it."""
    why = _save_miss_reason_1202gu({"videos": [{"id": 7}]}, "items.0.id")
    assert "empty" not in why.lower(), why
    assert "items" in why


def test_a_present_but_wrong_field_is_not_called_empty():
    why = _save_miss_reason_1202gu(_FULL, "items.0.sound_id")
    assert "empty" not in why.lower(), (
        "a populated collection whose ROW lacks the field was called empty: %s" % why)


def test_a_non_indexed_save_path_is_handled():
    """`user.id` has no numeric index — must not crash, must not claim emptiness."""
    why = _save_miss_reason_1202gu({"user": {}}, "user.id")
    assert isinstance(why, str) and "empty" not in why.lower(), why


def test_a_hostile_payload_never_raises():
    for bad in (None, [], "text", 3, {"items": "not-a-list"}):
        assert isinstance(_save_miss_reason_1202gu(bad, "items.0.id"), str)


def test_the_recorder_uses_it():
    """A mechanism nobody calls is this codebase's most repeated failure."""
    src = (LLM / "multi_agent" / "runtime" / "chain_executor.py").read_text(encoding="utf-8")
    at = src.index('entry["save_failed"] = [f.split("<-", 1)[0] for f in _save_failed]')
    # #943: anchor on the landmark that ENDS the block, never a byte count — a window sized
    # in bytes breaks the moment a comment inside it grows.
    block = src[src.rindex("if _save_failed:", 0, at):src.index("entry[\"note\"]", at)]
    assert "_save_miss_reason_1202gu" in block, (
        "the save-failure note still reports the category only:\n%s" % block)
