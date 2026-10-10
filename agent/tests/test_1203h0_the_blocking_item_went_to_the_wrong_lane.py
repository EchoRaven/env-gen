"""#1203h0: one predicate for "whose auth failure is this", instead of two copies of it.

`auth_note_1203g1` decides whose fault an auth failure is and says it in English -- its
`all(s >= 400)` branch reads "credentials / backend, NOT a wiring bug". That condition is now
held in one place and CALLED by the branch that words it, so the sentence and any future
consumer of the verdict cannot drift apart.

★ A DRAFT WENT FURTHER AND WAS WITHDRAWN. It also filed a second P0 against the backend, on
the premise that the gate's unconditional `assignee="frontend"` meant the lane that can fix a
4xx login never heard about it. Measured afterwards -- which is the mistake: over the 627
browser-walkthrough tasks on disk, 49 (7%, 18 runs) carry this verdict while assigned to
frontend, and in ALL 18 of those runs the backend already held a task naming the same 401,
filed through business_chain remediation or a test-user's `bug_create`. r172's workhub has
four, including "POST /auth/login returns 401 for newly signed-up tenant user". A second task
would have added noise -- the double-dispatch risk that draft's own notes had flagged.

So these tests pin the predicate and its agreement with the prose, and nothing about routing.
There is no behavioural change here, and saying otherwise would be the overstatement the
measurement just removed.
"""
import ast
from pathlib import Path

import pytest

from env_generator.llm_generator.multi_agent.runtime.test_user_runner import (
    auth_fault_owner_1203h0 as _owner,
    auth_note_1203g1 as _note,
)

RUNNER = (Path(__file__).resolve().parents[1]
          / "env_generator/llm_generator/multi_agent/runtime/test_user_runner.py")
HEAL = (Path(__file__).resolve().parents[1]
        / "env_generator/llm_generator/multi_agent/runtime/heal_pipeline.py")


@pytest.mark.parametrize("statuses,owner", [
    ([401], "backend"),            # r172, netflix-r30: the API refused it
    ([401, 409], "backend"),       # netflix-r30's pair
    ([403], "backend"),
    ([500], "backend"),
    ([], "frontend"),              # nothing was sent: the submit is unwired
    ([200], "frontend"),           # 2xx that stored no token: post-login handling
    ([200, 401], "frontend"),      # not ALL 4xx — a mixed shape is not the API refusing
])
def test_the_owner_follows_the_statuses(statuses, owner):
    assert _owner(ok_auth=False, auth_status=statuses) == owner, statuses


def test_a_passing_auth_step_has_no_owner():
    """Nothing to route when auth worked — the field must not name a lane out of nowhere."""
    assert _owner(ok_auth=True, auth_status=[401]) == ""
    assert _owner(ok_auth=True, auth_status=[]) == ""


def test_the_prose_and_the_routing_cannot_DRIFT():
    """The anti-drift assertion, and the reason the predicate is shared rather than restated.

    #1203e5's lesson is this shape: a structured verdict flattened to prose exactly where the
    component that routes on it would have read it. If the note ever words "NOT a wiring bug"
    for a case the router sends to frontend, a lane is told two different things.
    """
    for statuses in ([401], [403], [401, 409], [500]):
        n = _note(ok_auth=False, token=None, navigated=False, landed=False,
                  path="/login", url="u", auth_status=statuses)
        assert "NOT a wiring bug" in n, (statuses, n)
        assert _owner(ok_auth=False, auth_status=statuses) == "backend", statuses
    for statuses in ([], [200]):
        n = _note(ok_auth=False, token=None, navigated=False, landed=False,
                  path="/login", url="u", auth_status=statuses)
        assert "NOT a wiring bug" not in n, (statuses, n)
        assert _owner(ok_auth=False, auth_status=statuses) == "frontend", statuses


def test_the_note_branch_calls_the_shared_predicate():
    """Source-level: the branch must CALL it, not restate `all(s >= 400 ...)`.

    A second copy of the condition is how the two drift apart; `lifecycle`'s rule in this repo
    is "Imported, not re-listed".
    """
    tree = ast.parse(RUNNER.read_text(encoding="utf-8"))
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "auth_note_1203g1")
    calls = [ast.unparse(n.func) for n in ast.walk(fn) if isinstance(n, ast.Call)]
    assert any("auth_fault_owner_1203h0" in c for c in calls), calls


