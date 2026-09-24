r"""#1202tc: a task_ready wake that can target the verifier must carry `validation_phase`.

`VerifierValidationTriggerPolicy.allow_task_ready` admits an orchestrator-authored
`task_ready` only when ONE of four things holds: `metadata["validation_phase"]`, a `phase` in
`accepted_phases`, a tag intersecting `accepted_tags`, or a `payload_keywords` substring in
the payload. `_create_message` never sets a phase, so for a framework-built wake that leaves
the flag, the tags, and the prose.

V29 is what the miss costs when nothing else covers it: the gate-check re-dispatch to the
verifier bounced 38 times and the run STUCK-ABORTed having delivered nothing.
`dispatch_gate_level_checks` was fixed then. **Its sibling was not**: `dispatch_failing_checks`
routes `docker_up` to the verifier from `_CHECK_OWNER` and builds the same kind of wake with
`tags=[name, "remediation"]` and prose that says "delivery is blocked on `docker_up`".

Simulated against the REAL `agents_config.yaml` policy and the REAL `_create_message`, not a
stand-in: that wake is REJECTED, every time. `from_agent` is right; the flag is unset; no
phase is set on these messages at all; `{"docker_up", "remediation"}` misses `accepted_tags`;
and the payload carries none of the ten `payload_keywords` — "blocked" is not "blocker". With
the flag set, the same message is ADMITTED.

Measured: 72 such tasks across 49 corpus runs, every one assigned to the verifier.

WHAT IS NOT CLAIMED: that this loses runs. 64 of the 72 ended `completed` (5 cancelled, 2
in_progress, 1 pending), so the verifier reaches the task through its own polling. The bounce
costs the urgency of the wake, and it leaves a log line — "verifier requires explicit
validation-phase trigger" — that describes the policy instead of the missing flag, so it reads
as correct behaviour. `#934`'s shape: a guard installed on one producing branch and not its
sibling.

ALSO CHECKED AND DISSOLVED: `kickoff_driver`'s implementation dispatch builds an unflagged
wake too, but `_IMPL_LANES_1076` is `("backend", "frontend")` — the verifier is never a
target, so there is nothing to fix there.

LOCAL-ONLY (gitignored)."""
from __future__ import annotations

import ast
import sys
import types
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for p in (str(ROOT), str(LLM_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

from multi_agent.workflow_policies import VerifierValidationTriggerPolicy  # noqa: E402
from tools.communication_tools import _create_message  # noqa: E402

_CONFIG = LLM_DIR / "multi_agent" / "agents" / "agents_config.yaml"
_DISPATCHER = LLM_DIR / "multi_agent" / "runtime" / "remediation_dispatcher.py"


def _real_policy():
    """The policy as the SHIPPED config builds it — a hand-made one would test a world that
    does not exist (#1202hh's lesson: the fixture fed the fix its own wrong shape)."""
    raw = {}

    def walk(o):
        nonlocal raw
        if isinstance(o, dict):
            if o.get("kind") == "verifier_validation_trigger":
                raw = o
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    walk(yaml.safe_load(_CONFIG.read_text(encoding="utf-8")))
    assert raw, "the verifier_validation_trigger policy is not in agents_config.yaml"
    return VerifierValidationTriggerPolicy(
        allowed_sender=raw["allowed_sender"],
        accepted_tags=list(raw.get("accepted_tags") or []),
        accepted_phases=list(raw.get("accepted_phases") or []),
        payload_keywords=list(raw.get("payload_keywords") or []),
    )


_DOCKER_WAKE = ("URGENT: delivery is blocked on `docker_up`. Claim task task_ab12 and fix it "
                "NOW, then finish. Detail: ERROR [frontend 4/6] RUN npm run build exit 1")


def _admits(content, tags, flag):
    msg = _create_message("orchestrator", "verifier", content, "task_ready",
                          tags=tags, priority="urgent", persist=True)
    if flag:
        msg.metadata["validation_phase"] = True
    agent = types.SimpleNamespace(agent_id="verifier", _upstream_ready_agents=set())
    return _real_policy().allow_task_ready(agent, msg) is None


def test_the_unflagged_wake_really_is_rejected():
    """The premise. If this ever starts passing, the fix below is unnecessary and should go."""
    assert not _admits(_DOCKER_WAKE, ["docker_up", "remediation"], flag=False)


def test_the_flag_is_what_admits_it():
    assert _admits(_DOCKER_WAKE, ["docker_up", "remediation"], flag=True)


def test_none_of_the_other_three_doors_is_open_for_this_message():
    """Named individually so a config change that opens one is visible here rather than
    silently making the flag redundant."""
    pol = _real_policy()
    text = _DOCKER_WAKE.lower()
    assert not {"docker_up", "remediation"} & pol.accepted_tags
    assert "" not in pol.accepted_phases, "an empty phase would admit every framework message"
    assert not [k for k in pol.payload_keywords if k in text], (
        "a payload keyword now matches; the prose, not the flag, would be carrying this")


def test_the_dispatcher_sets_the_flag_when_the_owner_is_the_verifier():
    src = _DISPATCHER.read_text(encoding="utf-8")
    i = src.index("FAILING-CHECK remediation dispatched to")
    block = src[src.index("_wake_1202tc = _create_message", 0):i]
    assert 'if owner == "verifier":' in block
    assert '_wake_1202tc.metadata["validation_phase"] = True' in block


def test_every_task_ready_site_that_can_target_the_verifier_carries_the_flag():
    """The class, not the instance (#934: the guard went on three branches of four). A site
    whose target is a literal lane other than the verifier needs nothing; a literal
    `"verifier"` or a computed target does."""
    # A site whose target set provably excludes the verifier, with the proof kept as its own
    # test below. Keyed by FILE, not line, because line numbers drift.
    exempt = {"runtime/kickoff_driver.py":
              "targets come from _IMPL_LANES_1076 = (backend, frontend); see the test below"}
    offenders = []
    for path in sorted((LLM_DIR / "multi_agent").rglob("*.py")):
        if str(path.relative_to(LLM_DIR / "multi_agent")) in exempt:
            continue
        src = path.read_text(encoding="utf-8", errors="replace")
        if "task_ready" not in src:
            continue
        try:
            tree = ast.parse(src)
        except SyntaxError:
            continue
        lines = src.split("\n")
        for n in ast.walk(tree):
            if not isinstance(n, ast.Call):
                continue
            kw = {k.arg: k.value for k in n.keywords if k.arg}
            mt = kw.get("msg_type")
            if not (isinstance(mt, ast.Constant) and mt.value == "task_ready"):
                continue
            tgt = kw.get("target_agent_id")
            literal_other = (isinstance(tgt, ast.Constant)
                             and str(tgt.value) not in ("verifier",))
            if literal_other:
                continue                      # cannot reach the verifier
            window = "\n".join(lines[max(0, n.lineno - 8): n.lineno + 30])
            if "validation_phase" not in window:
                offenders.append(f"{path.relative_to(LLM_DIR)}:{n.lineno}")
    assert offenders == [], (
        "these task_ready wakes can target the verifier and never set validation_phase, so "
        "the verifier's own policy rejects them: %s" % offenders)


def test_the_kickoff_dispatch_does_not_reach_the_verifier():
    """Checked rather than assumed — it was the other suspect, and it dissolved."""
    from multi_agent.runtime.kickoff_driver import _IMPL_LANES_1076, _impl_dispatch_targets_1076
    assert "verifier" not in _IMPL_LANES_1076
    assert _impl_dispatch_targets_1076(["backend", "frontend", "verifier"]) == \
        ["backend", "frontend"]
