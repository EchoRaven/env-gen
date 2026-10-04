r"""#1203d5: a HOST fault latched the app's tree as failing, and the reason was prefix-sliced.

`ensure_fresh_smoke_before_cut` is the last of the fourteen delivery conditions: it re-runs
api_smoke on the exact release tree when the backend changed after the last passing smoke.
Two rules this repo had already established were missing from it.

**PIPE-C2.** `orchestrator._fwval_should_attempt` says it outright: "DON'T hard-stop either:
allow one SLOW retry per ``slow_interval`` so a transient environmental failure still
eventually records the gate-required RunHub run." This path instead stamped
`_fresh_smoke_fail_sig = cur` on ANY non-passing result, and `fresh_smoke_decision` then
returns "hold" for that exact signature forever -- re-arming ONLY on a backend source change.
A full disk, a busy port or a dead daemon therefore wedged the release until a lane happened
to edit the backend, which on an otherwise-green gate nobody will. r149 held three times on
`docker_up:HOST FAULT (not a bug in this app): no space left on device` and recovered only
because its lanes went on editing the backend for other reasons.

**#1202de.** The repo already knows whose fault a compose failure is, and that function's
docstring is this bug's precedent: netflix-r43 asked a backend engineer to fix
`pg_wal ... No space left on device`, churned 45 minutes, closed the P0 claiming a change
that exists in no commit on any branch, and the verifier's rerun rubber-stamped the
fabrication. The hold ledger meanwhile told the post-mortem "post-smoke backend edit FAILS a
fresh api_smoke" -- naming a backend edit for a disk that was full.

**#182.** `_salient_error` lives in THIS file, 180 lines below, built so a long validation
detail is never reported by a blind prefix slice. The hold-reason builder used `[:60]`.
Measured over every hold ledger on disk: 9 of the 10 `fresh_smoke` records were cut at 60 --
r149's mid-word (`GET readback does NOT contain i`, `{"detail":"could not `), and r146's
before the failing step was named at all, because a framework notice had been prepended
upstream and spent the entire window (#1202vx recurring in a second place). The ledger field
accepts 400 characters; the shortfall was self-imposed.

★ Honest about the corpus: the three host-fault records are from r149, and I caused that
disk-full myself. The frequency evidence is therefore ~zero; this patch rests on the code's
own latch semantics and on #1202de's recorded 45-minute precedent, not on a count.
"""
import asyncio
import os
import sys
import types

import pytest

_AGENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_AGENT, "env_generator", "llm_generator"))

from multi_agent.runtime import framework_validation as FV  # noqa: E402
# ★ Imported here on purpose: the function under test does a lazy relative import of this
# module, and the first draft of `_stub_validation` below replaced the whole `tools` PACKAGE in
# sys.modules -- so that lazy import pulled the stub, the host-fault classifier raised, and the
# patch silently took its pre-#1203d5 path. The fixture was the bug, not the code (#1203b4's
# rule: a stand-in may replace the outside world, never the patch's own derivation).
from multi_agent.runtime import remediation_dispatcher as _RD  # noqa: E402,F401

DISK = "HOST FAULT (not a bug in this app): no space left on device"


class _Log:
    def __init__(self):
        self.lines = []

    def _rec(self, msg, *a):
        try:
            self.lines.append(str(msg) % a if a else str(msg))
        except Exception:
            self.lines.append(str(msg))

    warning = error = debug = info = _rec


class _Orch:
    def __init__(self, out):
        self.output_dir = str(out)
        self._logger = _Log()
        self.hubs = None


def _run(orch):
    return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(
        FV.ensure_fresh_smoke_before_cut(orch))


@pytest.fixture
def orch(tmp_path, monkeypatch):
    (tmp_path / "app").mkdir()
    o = _Orch(tmp_path)
    # ★ Stand in for the EXTERNAL world only (the tree's hash), never for anything the patch
    # itself must derive -- the mistake recorded in #1203b4.
    # ★ #1203f0 moved what this function reads: `tree_signature_1203f0` (backend AND frontend),
    # because the gate it serves builds both. The stand-in has to follow the target — patching the
    # old name silently stopped intercepting and five of these tests went red. Same lesson as
    # #1203b4: a stand-in may replace the outside world, but it has to replace the CURRENT one.
    monkeypatch.setattr(FV, "tree_signature_1203f0", lambda _p: "SIG-A")
    monkeypatch.setenv("ENVGEN_FRESH_SMOKE_GATE", "1")
    return o


def _stub_validation(monkeypatch, checks, run_id=None):
    """Patch the tool where the function imports it from -- it does a FUNCTION-LOCAL import,
    so patching an attribute on framework_validation would be a no-op (#1203c4's lesson)."""
    calls = []

    class _Res:
        data = {"checks": checks, "runhub_run_id": run_id}
        error_message = ""

    class _Tool:
        def __init__(self, workspace=None):
            calls.append(1)

        async def execute(self):
            return _Res()

    mod = types.ModuleType("tools.validation_tools")
    mod.RunValidationTool = _Tool
    monkeypatch.setitem(sys.modules, "tools.validation_tools", mod)
    return calls


# ------------------------------------------------------------------ host fault

def test_a_host_fault_does_not_stamp_the_tree_as_failing(orch, monkeypatch):
    """★ The defect: the app was never asked, so it must not be recorded as the answer."""
    _stub_validation(monkeypatch, [{"name": "docker_up", "status": "fail", "detail": DISK}])
    assert _run(orch) is False, "an untested tree must still hold the release"
    assert getattr(orch, "_fresh_smoke_fail_sig", None) is None, \
        "the host fault latched the tree as failing"
    assert getattr(orch, "_fresh_smoke_hostfault_sig_1203d5", None) == "SIG-A"


def test_the_ledger_reason_names_the_host_not_a_backend_edit(orch, monkeypatch):
    """What a post-mortem reads. It used to say "post-smoke backend edit FAILS"."""
    _stub_validation(monkeypatch, [{"name": "docker_up", "status": "fail", "detail": DISK}])
    _run(orch)
    why = orch._fresh_smoke_hold_reason_1202wc
    assert "HOST FAULT" in why and "OPERATOR ACTION" in why, why
    assert "backend edit" not in why, why
    assert "NOT recorded as failing" in why, why


def test_the_parked_smoke_is_retried_not_wedged(orch, monkeypatch):
    """★ PIPE-C2: the host condition clears with no source change, so the retry cannot be
    gated on one. Within the window it must NOT re-boot docker; past it, it must."""
    calls = _stub_validation(monkeypatch,
                            [{"name": "docker_up", "status": "fail", "detail": DISK}])
    _run(orch)
    assert len(calls) == 1
    assert _run(orch) is False and len(calls) == 1, "it re-booted docker on the same tick"
    orch._fresh_smoke_hostfault_ts_1203d5 -= FV.HOSTFAULT_RETRY_S_1203D5 + 1
    _run(orch)
    assert len(calls) == 2, "the park never expired -- the release is wedged"


def test_the_park_is_bound_to_the_tree_it_was_taken_on(orch, monkeypatch):
    """A lane edit changes the signature; that tree was never parked and must smoke now."""
    calls = _stub_validation(monkeypatch,
                            [{"name": "docker_up", "status": "fail", "detail": DISK}])
    _run(orch)
    monkeypatch.setattr(FV, "tree_signature_1203f0", lambda _p: "SIG-B")
    _run(orch)
    assert len(calls) == 2, "a changed backend stayed parked under the old tree's latch"


def test_one_unexplained_failure_still_latches_the_tree(orch, monkeypatch):
    """★ Conservative by construction: the app is exonerated only when EVERY failing check is
    host-explainable. A full disk beside a real 500 must not excuse the 500."""
    _stub_validation(monkeypatch, [
        {"name": "docker_up", "status": "fail", "detail": DISK},
        {"name": "business_writes_persist", "status": "fail", "detail": "POST /x -> 500"},
    ])
    assert _run(orch) is False
    assert orch._fresh_smoke_fail_sig == "SIG-A", "a real failure was excused by the disk"
    assert getattr(orch, "_fresh_smoke_hostfault_sig_1203d5", None) is None


def test_an_ordinary_failure_behaves_exactly_as_before(orch, monkeypatch):
    _stub_validation(monkeypatch, [{"name": "auth_register_login", "status": "fail",
                                    "detail": "register=409"}])
    assert _run(orch) is False
    assert orch._fresh_smoke_fail_sig == "SIG-A"
    assert "FAILS a fresh api_smoke" in orch._fresh_smoke_hold_reason_1202wc


def test_a_pass_still_stamps_and_cuts(orch, monkeypatch):
    _stub_validation(monkeypatch, [], run_id="run-7")
    assert _run(orch) is True
    assert orch._fresh_smoke_pass_sig == "SIG-A"


# ------------------------------------------------------------------ the evidence

def test_the_real_error_is_reported_not_the_prefix(orch, monkeypatch):
    """#182's rule, applied here: the operative line sits at the END of a build log."""
    detail = ("pulling cr.io/astral-sh/uv\n" * 8) + "error: 'LoginPage' has already been declared"
    _stub_validation(monkeypatch, [{"name": "docker_up", "status": "fail", "detail": detail}])
    _run(orch)
    why = orch._fresh_smoke_hold_reason_1202wc
    assert "already been declared" in why, why
    assert "astral-sh/uv" not in why, "the blind prefix slice survived: " + why


def test_r149s_readback_line_is_no_longer_cut_mid_word(orch, monkeypatch):
    """r149's own detail, verbatim -- it reached the ledger as "does NOT contain i"."""
    detail = ('POST /api/comments → id=296; GET readback does NOT contain id 296 '
              '(the write is not durable)')
    _stub_validation(monkeypatch, [{"name": "business_writes_persist", "status": "fail",
                                    "detail": detail}])
    _run(orch)
    assert "not durable" in orch._fresh_smoke_hold_reason_1202wc, \
        orch._fresh_smoke_hold_reason_1202wc


def test_a_prepended_notice_no_longer_spends_the_whole_window(orch, monkeypatch):
    """★ r146's shape: #1202vx's notice is prepended upstream and used to consume all 60
    characters, so the failing step was never named at all."""
    detail = ("These verdicts may not be about the build currency you think they are; "
              "the recorded run predates the last merge || "
              "error: GET /api/videos/10 -> 404 (expected 200)")
    _stub_validation(monkeypatch, [{"name": "business_chain", "status": "fail",
                                    "detail": detail}])
    _run(orch)
    assert "/api/videos/10" in orch._fresh_smoke_hold_reason_1202wc, \
        orch._fresh_smoke_hold_reason_1202wc


def test_several_failing_checks_share_the_budget_and_nothing_gets_worse(orch, monkeypatch):
    """The ledger field caps the detail at 400 characters (#1202tk), so the budget is shared
    rather than spent by whichever check comes first -- and floored at the old 60, so the
    many-check case is no worse than before (with 5+ checks the field's own cap still clips
    the tail; 10 of the 10 real records carry exactly one check)."""
    checks = [{"name": "c%d" % i, "status": "fail", "detail": "x" * 500} for i in range(6)]
    _stub_validation(monkeypatch, checks)
    _run(orch)
    why = orch._fresh_smoke_hold_reason_1202wc
    for i in range(6):
        assert "c%d:" % i in why, "check c%d vanished: %s" % (i, why[:200])
    segs = [seg for seg in why.split("): ", 1)[-1].split(", ") if ":" in seg]
    assert segs and all(len(seg.split(":", 1)[1]) >= 60 for seg in segs), \
        "the floor dropped below the pre-#1203d5 60 characters"


def test_no_blind_sixty_character_slice_survives():
    """Pin the shape so the rule cannot quietly come back to this file."""
    import inspect
    s = inspect.getsource(FV.ensure_fresh_smoke_before_cut)
    assert "[:60]" not in s, "a blind prefix slice is back in the hold-reason builder"
    assert "_salient_error(" in s, "#182's extractor is not being used"


def test_the_tool_fault_fallback_is_not_prefix_sliced(orch, monkeypatch):
    """The third slice: when the validation TOOL faults, no check is marked fail and the
    reason comes from `error_message` -- a traceback, whose operative line is last."""
    calls = []

    class _Res:
        data = {"checks": [], "runhub_run_id": None}
        error_message = ("Traceback (most recent call last):\n" + "  File \"x\", line 1\n" * 9
                         + "RuntimeError: compose project name collides with r148")

    class _Tool:
        def __init__(self, workspace=None):
            calls.append(1)

        async def execute(self):
            return _Res()

    mod = types.ModuleType("tools.validation_tools")
    mod.RunValidationTool = _Tool
    monkeypatch.setitem(sys.modules, "tools.validation_tools", mod)

    assert _run(orch) is False
    why = orch._fresh_smoke_hold_reason_1202wc
    assert "collides with r148" in why, why
    # ★ The counter-proof stated rather than assumed: the old blind `[:160]` stopped inside
    # the repeated File lines and never reached the only line that names the cause.
    assert "collides with r148" not in _Res.error_message[:160]


def test_a_real_failure_after_a_host_fault_clears_the_park(orch, monkeypatch):
    """★ No contradictory state: once the tree HAS been tested and it is the app's, the
    host-fault park on that same signature must not survive to claim it too."""
    _stub_validation(monkeypatch, [{"name": "docker_up", "status": "fail", "detail": DISK}])
    _run(orch)
    assert orch._fresh_smoke_hostfault_sig_1203d5 == "SIG-A"
    orch._fresh_smoke_hostfault_ts_1203d5 -= FV.HOSTFAULT_RETRY_S_1203D5 + 1
    _stub_validation(monkeypatch, [{"name": "business_chain", "status": "fail",
                                    "detail": "GET /api/videos/10 -> 404"}])
    _run(orch)
    assert orch._fresh_smoke_fail_sig == "SIG-A"
    assert orch._fresh_smoke_hostfault_sig_1203d5 is None, "both latches claim the same tree"
