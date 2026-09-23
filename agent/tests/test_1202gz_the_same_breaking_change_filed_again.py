"""#1202gz — the breaking-change task is the one filer in the codebase with no dedupe.

`_record_breaking_change` opens a P0 per affected consumer agent every time it runs, with no
check for an identical outstanding task. Every other filer routes through
`state_changed_1202ad` for exactly this reason; #1202bn's own comment records the cost —
"of 838 cancelled tasks, 462 (55%, across 79 of 144 runs) were cancelled as duplicates".

r101, live: four `Fix breaking change in GET /api/videos` P0s inside 75 seconds (00:58:56,
00:59:21, 00:59:35, 01:00:10) while the lane flipped `auth_required` back and forth, and
17% of that run's 36 breaking tasks are VERBATIM duplicates — one payload for `/api/explore`
filed three times. Measured the same way on r96/r97/r98: 16-28%.

Deduped on what makes the task different: the endpoint, the breaking payload, and the
consumer being told. A payload that CHANGES still files — the lane needs to know the shape
changed again — and a different consumer still gets its own copy, because the fix differs
per caller.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime.registryhub import _breaking_task_is_new_1202gz  # noqa: E402

_S: set = set()

_BRK = {"is_breaking": True, "removed_response_fields": [], "type_changed_fields": ["caption"],
        "required_added_in_request": [], "method_changed": False, "path_changed": False,
        "response_key_changed": False, "auth_added": False}


def test_the_same_finding_for_the_same_consumer_files_once():
    assert _breaking_task_is_new_1202gz(_S, "GET /api/videos", _BRK, "frontend") is True
    assert _breaking_task_is_new_1202gz(_S, "GET /api/videos", _BRK, "frontend") is False


def test_a_changed_payload_files_again():
    """The shape changed a second time — that is news, not a duplicate."""
    assert _breaking_task_is_new_1202gz(_S, "GET /api/x", _BRK, "frontend") is True
    other = {**_BRK, "type_changed_fields": ["caption", "sound_id"]}
    assert _breaking_task_is_new_1202gz(_S, "GET /api/x", other, "frontend") is True


def test_each_consumer_gets_its_own_copy():
    """The fix differs per caller, so backend and frontend are not duplicates of each other."""
    assert _breaking_task_is_new_1202gz(_S, "GET /api/y", _BRK, "frontend") is True
    assert _breaking_task_is_new_1202gz(_S, "GET /api/y", _BRK, "backend") is True


def test_a_different_endpoint_is_not_a_duplicate():
    assert _breaking_task_is_new_1202gz(_S, "GET /api/a", _BRK, "frontend") is True
    assert _breaking_task_is_new_1202gz(_S, "GET /api/b", _BRK, "frontend") is True


def test_hostile_inputs_never_raise():
    for ep in (None, "", 3):
        assert isinstance(_breaking_task_is_new_1202gz(_S, ep, _BRK, "frontend"), bool)
    for brk in (None, "x", []):
        assert isinstance(_breaking_task_is_new_1202gz(_S, "GET /api/z", brk, "frontend"), bool)


def test_the_filer_uses_it():
    """A dedupe nobody calls is this codebase's most repeated failure."""
    import ast
    src = (LLM / "multi_agent" / "runtime" / "registryhub.py").read_text(encoding="utf-8")
    assert "_breaking_task_is_new_1202gz(" in src, "the dedupe has no caller"
    # #1202sr moved the title off a literal (it now names WHICH change), so anchor on the
    # filer's own identity instead — that is what makes this block the filer.
    at = src.index('source="registryhub_breaking_change"')
    block = src[src.rindex("for consumer_agent in recipient_agents", 0, at):at]
    assert "_breaking_task_is_new_1202gz(" in block, (
        "the filer still opens a P0 per pass without asking:\n%s" % block)
