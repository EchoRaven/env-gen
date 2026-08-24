r"""#854: the static-core guard blocks two agents that never exist and misses two that always do.

`STATIC_CORE_AGENT_TYPES` stops an orchestrator-led dynamic team from re-defining an agent that
already exists — the error says so: *"Use send_message(msg_type='task_ready') to the existing
static agent instead."* So the set should name the agents that actually run.

Measured from `.agent_logs/` directory names across **all 151 corpus runs** — the roster is not a
guess:

    151x orchestrator   151x backend    151x frontend   151x verifier
    151x debugger       151x knowledge  151x design_analyst
     71x browser_test_user   26x api_test_user   1x mcp_test_user

    design: 0        database: 0

| | |
|---|---|
| in the set, never spawned | `design`, `database` |
| spawned in 151 of 151, not in the set | **`debugger`**, **`design_analyst`** |

**Two things are fixed here and one is deliberately not.**

FIXED — the divergence. `agent_spawn_service` carried a second copy under the same name, one member
short (`design`). It now resolves the manager's, so there is one definition (#853's rule). Adding
`design` only tightens the guard for a type spawned 0 times in 151 runs, so it is corpus-neutral.
It resolves lazily via PEP 562 `__getattr__` because a module-level import cycles
(`agent_spawn_service` -> `team_runtime.manager` -> `runtime_control` -> back).

NOT FIXED — the roster. Adding `debugger` and `design_analyst` would make a **blocking** guard fire
on two agents present in every single run, and item 152 is explicit that a blocking gate turns a
false positive into a dead run. Whether those two are meant to be re-definable inside a dynamic
team is an intent question the code does not answer, so it is reported with the measurement and
left to a human. This test PINS the current state so the decision is a deliberate edit, not drift.
"""
import pathlib
import re

import pytest

from env_generator.llm_generator.multi_agent import agent_spawn_service as svc
from env_generator.llm_generator.multi_agent.team_runtime.manager import DynamicAgentManager


_GENERATED = pathlib.Path(__file__).resolve().parents[1] / "generated"


def _roster():
    """Agent types actually spawned, from `.agent_logs/` directory names.

    ★ TWO probe errors here, both worth keeping. First: the original searched log CONTENTS for
    `"agent_type": "..."` and reported zero across 151 runs — the type is in the DIRECTORY NAME,
    not in any JSON field (seventh field-location error this session). Second: extracting only the
    parenthesised suffix keyed `Debugger Agent` as itself, so `debugger` read as absent from a
    corpus where it runs 151 times. The directory names come in three shapes and all three need
    normalising:

        "Backend Engineer Agent"          -> backend
        "design_analyst"                  -> design_analyst
        "API Test-User (api_test_user)"   -> api_test_user

    Neither error changed the finding — the census printed `151x Debugger Agent` either way — but
    the second turned a correct claim into a red test, which is how it was caught."""
    seen = {}
    for d in sorted(_GENERATED.glob("netflix-web-r*")):
        al = d / ".agent_logs"
        if not al.is_dir():
            continue
        for sub in al.iterdir():
            m = re.search(r"\(([a-z_]+)\)\s*$", sub.name)
            if m:
                key = m.group(1)                       # "API Test-User (api_test_user)"
            elif re.fullmatch(r"[a-z_]+", sub.name):
                key = sub.name                         # "design_analyst"
            else:
                key = sub.name.split()[0].lower()      # "Backend Engineer Agent" -> "backend"
            seen[key] = seen.get(key, 0) + 1
    return seen


# `_GENERATED.is_dir()` was too weak a guard: the directory can exist while holding
# none of the runs the roster is measured over, and every test then reported an
# empty measurement as a failure. Require the measurement itself to be non-empty.
pytestmark = pytest.mark.skipif(
    not _GENERATED.is_dir() or not _roster(),
    reason="the run corpus this roster is measured over is not present")


def test_the_roster_probe_sees_the_corpus():
    """Non-vacuity. Without this, every measured claim below passes on an empty dict."""
    r = _roster()
    assert r.get("design_analyst", 0) >= 100, r
    assert len(r) >= 7, r


def test_there_is_one_definition():
    """#853's rule. `agent_spawn_service` had a same-named copy one member short."""
    assert set(svc.STATIC_CORE_AGENT_TYPES) == set(DynamicAgentManager.STATIC_CORE_AGENT_TYPES)


def test_the_public_attribute_survived_the_lazy_wiring():
    """PEP 562 `__getattr__`, because a module-level import cycles. An outside reader must still
    see the constant, and an unknown attribute must still raise."""
    assert "backend" in svc.STATIC_CORE_AGENT_TYPES
    with pytest.raises(AttributeError):
        svc.NO_SUCH_CONSTANT_854


def test_the_phantom_members_are_still_phantom():
    """`design` and `database` are in the guard and were spawned zero times in 151 runs. If a
    future run spawns one, this fails and the roster note in EXPERIMENTS item 177 is out of date."""
    r = _roster()
    assert r.get("design", 0) == 0 and r.get("database", 0) == 0, r


def test_the_missing_members_are_still_missing_and_still_real():
    """★ The reported-not-fixed half, pinned so it cannot drift silently in either direction.

    `debugger` and `design_analyst` run in every corpus run and are absent from a guard whose
    stated job is to name the agents that already exist. Adding them tightens a BLOCKING guard on
    two ever-present agents, so it is a human's call — but if someone makes that call, this test
    fails and forces the note to be updated with it."""
    r = _roster()
    core = set(DynamicAgentManager.STATIC_CORE_AGENT_TYPES)
    for name in ("debugger", "design_analyst"):
        assert r.get(name, 0) >= 100, (name, r)
        assert name not in core, (
            f"{name} was added to the guard — update EXPERIMENTS item 177, which records it as "
            "an open decision rather than a fix")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
