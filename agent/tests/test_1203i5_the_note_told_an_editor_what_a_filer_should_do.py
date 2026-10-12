"""#1203i5: the stale-image note told an editor what to do, and 78% of its readers are filers.

`#1202qs` attaches " — NOTE: app/ has changed since the running image was built, so this
response may come from the OLD code" to a failing `test_api`, and then said what to do:
"Re-run validation (it rebuilds) before changing code or the contract to match what you just
saw." That is written for a reader who EDITS.

Measured over the last 13 runs -- 439 of these notes:

    browser_test_user   167     run_validation calls:  0
    api_test_user       151     run_validation calls:  0
    mcp_test_user        23     run_validation calls:  0
    backend              84                            1
    verifier             16                           71
    orchestrator          2                           11

341 of 439 (78%) went to DETECT-ONLY test-users, whose whole job is to FILE, not to edit,
and who called `run_validation` exactly ZERO times across those runs while the verifier --
16 notes -- called it 71 times. 43 of the 341 are followed within 120 log lines by that same
test-user filing a bug.

★ This is NOT #1203gq's missing-tool shape, and that was checked rather than assumed:
`run_validation` IS in their pool -- `create_verification_tools` returns `RunValidationTool`
and the `api_test_user` profile takes the `verification_tools` bundle. The defect is the
copy, not the capability. (The log line "Tools registered for LLM: 120 -> ..." lists only 15
and is truncated, so it cannot answer that question either way -- the config and the bundle
can.)

The sibling note three functions up already has the right wording for this audience --
#1202qz: "re-check before filing it as a defect" -- and this one, whose audience is 78%
filers, carried the editor-facing half alone. Both halves now ride, because the note reaches
both kinds of reader.
"""
import io
import urllib.error
import urllib.request
from types import SimpleNamespace

from env_generator.llm_generator.tools import runtime_tools as RT


class _Reg:
    def get_endpoints(self):
        return {}


def _run(monkeypatch, verdict, code=401):
    def _raise(req, timeout=30):
        raise urllib.error.HTTPError(req.full_url, code, "err", {}, io.BytesIO(b'{"detail":"x"}'))
    monkeypatch.setattr(urllib.request, "urlopen", _raise)
    monkeypatch.setattr(RT, "_contract_says_public_1202qp", lambda *a, **k: None)
    import env_generator.llm_generator.multi_agent.runtime.chain_executor as CE
    monkeypatch.setattr(CE, "build_currency_1202ex", lambda base: {"verdict": verdict})
    tool = RT.TestAPITool()
    tool.set_agent(SimpleNamespace(_hubs=SimpleNamespace(registryhub=_Reg(), base_dir="/tmp/x")))
    return tool.execute(method="GET", url="http://localhost:8008/api/videos")


def test_the_note_names_filing(monkeypatch):
    """The action 78% of its readers can actually take."""
    msg = _run(monkeypatch, "changed").error_message
    assert "before filing this as a defect" in msg, msg


def test_the_note_still_names_editing(monkeypatch):
    """The original audience is still served — a lane must not rewrite to match old code."""
    msg = _run(monkeypatch, "changed").error_message
    assert "before changing code or the contract" in msg, msg


def test_the_note_still_names_the_rebuild(monkeypatch):
    msg = _run(monkeypatch, "changed").error_message
    assert "Re-run validation (it rebuilds)" in msg, msg


def test_the_note_still_says_what_is_wrong(monkeypatch):
    msg = _run(monkeypatch, "changed").error_message
    assert "may come from the OLD code" in msg, msg


def test_a_current_image_still_adds_nothing(monkeypatch):
    """The whole note is conditional; widening the advice must not make it unconditional."""
    msg = _run(monkeypatch, "current").error_message
    assert "OLD code" not in msg, msg
    assert "before filing this as a defect" not in msg, msg


def test_both_sibling_notes_tell_a_filer_what_to_do():
    """★ The two notes in this file reach the same audience through the same tool, so a
    filer must find its instruction in either. #1202qz had it; #1202qs did not."""
    import inspect
    qz = inspect.getsource(RT._young_stack_note_1202qz) if hasattr(
        RT, "_young_stack_note_1202qz") else None
    qs = inspect.getsource(RT._stale_image_note_1202qs)
    assert "filing" in qs, "the stale-image note does not mention filing"
    if qz is not None:
        assert "filing" in qz, "the young-stack note lost its filing guidance"


def test_the_capability_premise_holds():
    """★ Pin the fact that made this a COPY defect rather than #1203gq's missing-tool one:
    `run_validation` really is in the bundle these agents take. If that stops being true,
    the diagnosis in this file's docstring changes and so does the fix."""
    from env_generator.llm_generator.tools.verification_tools import (
        create_verification_tools,
    )
    names = {getattr(t, "NAME", type(t).__name__) for t in create_verification_tools()}
    assert "run_validation" in names, names
