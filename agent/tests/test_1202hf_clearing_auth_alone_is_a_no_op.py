"""#1202hf — the lane cleared `auth_required` and nothing changed, because it could not know.

r103, live: #1202gv named the disagreement, backend closed the task without fixing it,
#1202hd re-filed it, and the lane then set `/api/videos` and `/api/explore` to
`schema.auth_required = false` while leaving `owner_scoped_reads: true` on the tables.

That action is INERT. `backend_skeleton` line 2285 reads

    auth = auth or _owner_scoped

so owner scoping forces the auth dependency regardless of the contract's `auth_required` —
you cannot filter by the caller without a caller. (The comment two lines up records why:
"marked owner_scoped_reads but not auth_required projected anonymous + UNSCOPED".) The
projected read still carried `user=Depends(get_current_user)` and the owner filter, so the
feed stayed empty and the logged-out screen stayed impossible.

The lane conflated two different questions — "must you log in" (`auth_required`) and "do you
see other people's rows" (`owner_scoped_reads`) — and the message it was given did not
separate them. It does now, and says plainly that clearing one alone changes nothing.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime.scaffolder import _public_content_task_body_1202hf  # noqa: E402


def test_it_says_clearing_auth_alone_does_nothing():
    body = _public_content_task_body_1202hf(["videos", "comments"])
    low = body.lower()
    assert "auth_required" in body and "owner_scoped_reads" in body
    assert "on its own" in low or "alone" in low, (
        "the two flags are still presented as interchangeable:\n%s" % body)


def test_it_names_the_tables():
    body = _public_content_task_body_1202hf(["videos", "comments"])
    assert "videos" in body and "comments" in body


def test_it_still_states_the_declaration_and_the_choice():
    """#1202gv's original content must survive — the materials' word and the two options."""
    body = _public_content_task_body_1202hf(["videos"])
    assert "PUBLIC" in body
    assert "owner_scoped_reads" in body


def test_it_explains_why_the_flag_forces_auth():
    body = _public_content_task_body_1202hf(["videos"])
    low = body.lower()
    assert "caller" in low, (
        "it does not say WHY clearing auth alone is inert — owner scoping needs a caller "
        "to filter by:\n%s" % body)


def test_hostile_inputs_never_raise():
    for bad in (None, [], "videos", 3):
        assert isinstance(_public_content_task_body_1202hf(bad), str)


def test_the_filer_uses_it():
    src = (LLM / "multi_agent" / "runtime" / "scaffolder.py").read_text(encoding="utf-8")
    at = src.index('title=_title1202gv')
    block = src[at:src.index("assignee=", at)]
    assert "_public_content_task_body_1202hf(" in block, (
        "the task still builds its own body, so the no-op warning never reaches the lane:\n%s"
        % block)
