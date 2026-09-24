"""#1202hb — two live gaps in fixes that were already working, found in r102.

(1) `#1202gb`'s server_detail carries the compose stream prefix. r102, verbatim:

    backend-1  | DataError on GET /api/explore -> 400: orig=invalid input syntax for
    type integer: "persist-probe"

`#1202gw` learned that `compose logs` prefixes every line and added
`_strip_stream_prefix_1202gw`, but only the traceback path used it; the integrity-detail path
still repeats the plumbing back at the reader.

(2) `#1202gu` distinguishes an EMPTY collection from an absent save path, but the wording
lives in TWO places. It changed the SAVE step's own note; the note that reaches the STARVING
step downstream — the one a reader actually sees on the 404 — still says, in r102:

    SUBSTITUTED ${soundId} save failed at step 'list_feed_authed' (response lacked the save
    path) — the ladder sent an UNRELATED id — fix that capture, not this endpoint.

Same shape as #1202gt's first cut, which attached its fact to one branch of two.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime.chain_executor import (  # noqa: E402
    _strip_stream_prefix_1202gw, _sf_hint_1202hb)

_R102_DETAIL = ('backend-1  | DataError on GET /api/explore -> 400: orig=invalid input '
                'syntax for type integer: "persist-probe"')


def test_the_integrity_detail_loses_the_stream_prefix():
    out = _strip_stream_prefix_1202gw(_R102_DETAIL)
    assert out.startswith("DataError"), out
    assert "backend-1" not in out and "|" not in out, out


def test_the_integrity_path_strips_it():
    src = (LLM / "multi_agent" / "runtime" / "chain_executor.py").read_text(encoding="utf-8")
    at = src.index("def _integrity_detail_1202gb")
    body = src[at:src.index("\ndef ", at + 10)]
    assert "_strip_stream_prefix_1202gw" in body, (
        "the integrity detail still repeats `backend-1  | ` back at the reader")


def test_the_starving_step_is_told_the_collection_was_empty():
    hint = _sf_hint_1202hb("soundId", "list_feed_authed",
                           "`items` came back EMPTY (0 rows), so `items.0.id` had nothing to "
                           "read -- the capture is correct; the READ returned no data for this "
                           "actor, which is a scoping/seed question, not a chain one")
    assert "EMPTY" in hint, hint
    assert "fix that capture" not in hint, (
        "an empty upstream read still sends the reader to re-author a correct chain: %s" % hint)
    assert "soundId" in hint and "list_feed_authed" in hint


def test_a_genuinely_missing_path_keeps_the_capture_wording():
    """#647 — the old wording is right for the case it was written for."""
    hint = _sf_hint_1202hb("soundId", "list_feed_authed",
                           "the response lacks the save path `items.0.id`")
    assert "capture" in hint, hint
    assert "EMPTY" not in hint


def test_no_reason_falls_back_to_the_original_sentence():
    hint = _sf_hint_1202hb("soundId", "list_feed_authed", "")
    assert "soundId" in hint and "list_feed_authed" in hint and "capture" in hint


def test_the_starving_branch_uses_it():
    src = (LLM / "multi_agent" / "runtime" / "chain_executor.py").read_text(encoding="utf-8")
    at = src.index("save_failed_by_var.get(_uv)")
    block = src[at:src.index("recorded.append(", at)]
    assert "_sf_hint_1202hb(" in block, (
        "the starving step still builds its own sentence:\n%s" % block)
