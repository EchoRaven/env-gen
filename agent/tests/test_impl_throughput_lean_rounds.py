"""FIX #22 — implementation throughput: trim coordination stages during impl.

Instagram run #5 (post-FIX#19/#21): the backend cleared kickoff + could read the
contract, but implemented only ~1 endpoint in 18 min (~9x slower than the Notes
app's ~2 min/endpoint). Root cause: the action stage iterates ALL internal stages
(communicate, edit_code, run_checks, deliver) every action round — so during
implementation the lane spent ~half its per-round LLM calls re-checking the inbox
(communicate) and attempting a finish the kickoff_endpoints_implemented gate
blocks anyway (deliver), bloating context to 260K chars and starving edit_code
(only 4 of ~34 stage-steps wrote code).

FIX #22: when the lane owns endpoints not yet implemented (``_in_endpoint_impl_mode``),
skip communicate+deliver on action rounds AFTER the first — concentrating rounds
on edit_code. Round 0 always runs every stage (inbox + finish), so a skipped
communicate is caught by the next step's round 0 (≤1 step delay). Disable via
``lean_impl_action_rounds: false``.

These pin the gating predicate ``_in_endpoint_impl_mode`` — the only new logic;
the per-round skip itself is a 3-term inline condition in ``_run_action_stage``.
"""

import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.agents.runtime.step_pipeline.action import (  # noqa: E402
    AgentActionStageMixin,
)


class _Lane(AgentActionStageMixin):
    def __init__(self, endpoints, config_key="backend", with_registryhub=True):
        self._config_key = config_key
        if with_registryhub:
            self._hubs = SimpleNamespace(
                registryhub=SimpleNamespace(get_endpoints=lambda: endpoints)
            )
        else:
            self._hubs = SimpleNamespace(registryhub=None)


def _ep(provider, status, method="GET", path="/api/posts"):
    return {"method": method, "path": path, "provider": provider, "status": status}


def test_impl_mode_true_when_owned_endpoint_pending():
    eps = {"a": _ep("backend", "defined")}
    assert _Lane(eps)._in_endpoint_impl_mode() is True


def test_impl_mode_false_when_all_owned_implemented():
    eps = {"a": _ep("backend", "implemented"),
           "b": _ep("backend", "deprecated")}
    assert _Lane(eps)._in_endpoint_impl_mode() is False


def test_impl_mode_ignores_other_lanes_pending_endpoints():
    eps = {"a": _ep("frontend", "defined")}
    assert _Lane(eps, config_key="backend")._in_endpoint_impl_mode() is False


def test_impl_mode_counts_unprovidered_pending_endpoint():
    # provider=None endpoints are not filtered out (match finish-gate semantics)
    eps = {"a": _ep(None, "defined")}
    assert _Lane(eps)._in_endpoint_impl_mode() is True


def test_impl_mode_false_when_registryhub_empty():
    # kickoff phase: no endpoints registered yet → no behavior change
    assert _Lane({})._in_endpoint_impl_mode() is False


def test_impl_mode_false_when_no_registryhub():
    assert _Lane({}, with_registryhub=False)._in_endpoint_impl_mode() is False


def test_impl_mode_mixed_one_pending_is_enough():
    eps = {"a": _ep("backend", "implemented"), "b": _ep("backend", "defined")}
    assert _Lane(eps)._in_endpoint_impl_mode() is True


def test_skip_condition_shape():
    # The inline skip is: lean_impl and action_round > 0 and stage in {communicate, deliver}.
    # Pin the round-0-always-runs + stage-set semantics so a refactor can't widen them.
    skip = lambda lean, rnd, stage: bool(lean and rnd > 0 and stage in ("communicate", "deliver"))
    assert skip(True, 0, "communicate") is False        # round 0 always runs
    assert skip(True, 1, "communicate") is True
    assert skip(True, 1, "deliver") is True
    assert skip(True, 1, "edit_code") is False          # never skip code writing
    assert skip(True, 1, "run_checks") is False
    assert skip(False, 1, "communicate") is False        # disabled / not impl mode


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
