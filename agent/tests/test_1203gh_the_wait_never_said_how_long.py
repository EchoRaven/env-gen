"""#1203gh -- the stall was a second serialisation wait, and it never said how long.

#1203gf split docker_up into down_v/build/up; #1203gg added lock_wait/stage_assets/
repair_params/localize_seed. A 236s docker_up in r167 still had 195.5s with no owner, and
`lock_wait` measured 0.0s -- which RULED OUT the flock and left exactly one uninstrumented call
in the phase window: `wait_for_stack_leases_1202nx`. It blocks until nobody holds a lease on the
stack, and its own log line names the holders: "visual capture" and "test-user squad".

api_smoke validation needs `down -v` for a clean boot; those two are still using the stack; so it
waits, bounded by ENVGEN_STACK_LEASE_WAIT_SEC (900s default). Its log-line count matches the
stalls the sub-step data shows, run for run:

    r165   9 waits (1 hit the cap)   8 docker_up calls >=200s
    r166   8 waits                   7 stalls
    r167   2 waits                   2 stalls (196s, 656s)   -> exactly 2/2

WHAT THIS IS NOT. It is not lost wall clock, and an earlier framing of mine said it was. During
r167's four stall windows the run's LLM request density was 49 / 62 / 37 / 57 per minute against
a run average of 43 -- the other agents work at full rate throughout. The validation is
serialised behind the squad, not idling, and removing the wait would not make a run faster: it
would tear the stack down while a holder is using it, which is the race #1202nx exists to
prevent. The real serial cost inside docker_up is `build`: 41% of it in r167, median 64s.

So this ticket is diagnosability plus one real defect:

  * the wait is timed as `lease_wait`, completing docker_up's attribution (48% had no owner)
  * the wait ANNOUNCED ITS START AND NEVER ITS LENGTH. Its only line carrying a duration fires
    when it gives up at the cap -- once in three runs -- so a 656s wait left a log line saying it
    had begun and nothing saying what it cost. Attributing the pipeline's largest phase required
    a timing artifact because the line that knew it was waiting never said for how long.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "env_generator" / "llm_generator")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from multi_agent.runtime import validation_runner as VR  # noqa: E402
from multi_agent.runtime import compose_mutex as CM  # noqa: E402

VR_SRC = Path(VR.__file__).read_text(encoding="utf-8")
CM_SRC = Path(CM.__file__).read_text(encoding="utf-8")


def _smoke_fn():
    for n in ast.walk(ast.parse(VR_SRC)):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and "_du_steps_1203gf" in ast.unparse(n):
            return n
    raise AssertionError("the docker_up sub-step collector is gone")


def _labels(fn):
    out = set()
    for call in ast.walk(fn):
        if isinstance(call, ast.Call) and getattr(call.func, "id", None) == "_timed_1203gf" \
           and call.args and isinstance(call.args[0], ast.Constant):
            out.add(call.args[0].value)
        if isinstance(call, ast.Call) and getattr(call.func, "attr", None) == "append" \
           and getattr(getattr(call.func, "value", None), "id", None) == "_du_steps_1203gf":
            for a in call.args:
                if isinstance(a, ast.Tuple) and a.elts and isinstance(a.elts[0], ast.Constant):
                    out.add(a.elts[0].value)
    return out


def test_every_step_in_the_window_is_timed_including_the_lease_wait():
    labels = _labels(_smoke_fn())
    expected = {"down_v", "build", "up",                                   # #1203gf
                "lock_wait", "stage_assets", "repair_params", "localize_seed",  # #1203gg
                "lease_wait"}                                              # #1203gh
    missing = expected - labels
    assert not missing, (
        "untimed steps inside docker_up's phase window: %s — 48%% of docker_up had no owner in "
        "r167 and this is what closed it" % sorted(missing))


def test_the_lease_wait_still_actually_waits():
    """A timer that swallowed the call would remove the serialisation #1202nx exists for."""
    body = ast.unparse(_smoke_fn())
    assert "wait_for_stack_leases_1202nx(" in body
    assert "api_smoke validation (fresh boot)" in body


def test_the_lease_wait_is_not_a_check():
    fn = _smoke_fn()
    added = {c.args[0].value for c in ast.walk(fn)
             if isinstance(c, ast.Call) and getattr(c.func, "id", None) == "_add"
             and c.args and isinstance(c.args[0], ast.Constant)}
    assert "lease_wait" not in added


# --- the wait must say how long, not only that it began -----------------------------------------

def _wait_fn():
    for n in ast.walk(ast.parse(CM_SRC)):
        if isinstance(n, ast.FunctionDef) and n.name == "wait_for_stack_leases_1202nx":
            return n
    raise AssertionError("wait_for_stack_leases_1202nx is gone")


def test_the_free_path_reports_how_long_it_waited():
    """The return-True path is the one taken 8 of 9 times; before #1203gh it logged nothing, so
    a 656s wait was invisible in the log even though the function knew the number."""
    fn = _wait_fn()
    # find the `if not holders:` branch that returns True
    for node in ast.walk(fn):
        if not isinstance(node, ast.If):
            continue
        blk = ast.unparse(node)
        if "return True" not in blk or "holders" not in ast.unparse(node.test):
            continue
        assert "waited" in blk, "the free path still does not say how long: %s" % blk
        assert "start" in blk, blk
        assert "announced" in blk, (
            "the duration must be reported only when a wait actually happened, or every "
            "validation logs a 0s wait: %s" % blk)
        return
    raise AssertionError("no `if not holders: ... return True` branch found")


def test_the_cap_path_still_warns():
    """#1202nx's escape — 'a lease must never wedge a run' — tore the stack down while a holder
    was using it once in r165. Whatever else changes, that warning stays."""
    body = ast.unparse(_wait_fn())
    assert "warn_once_1201" in body, body
    assert "tearing the stack down anyway" in body, body


def test_the_duration_log_cannot_raise_into_the_caller():
    """This runs on the path that makes every validation proceed; a logging failure here must
    not become a validation failure."""
    fn = _wait_fn()
    for node in ast.walk(fn):
        if isinstance(node, ast.If) and "return True" in ast.unparse(node) \
           and "waited" in ast.unparse(node):
            assert any(isinstance(x, ast.Try) for x in ast.walk(node)), ast.unparse(node)
            return
    raise AssertionError("the duration report is not guarded")
