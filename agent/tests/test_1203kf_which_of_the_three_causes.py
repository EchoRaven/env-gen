"""#1203kf: a 4xx login note that hedged three causes the walk could already tell apart.

    "the form IS wired but /auth returned [401] (login user not registered / bad
     credentials / backend error) — not a wiring bug"

Three causes, three different owners, in 6 of the modern corpus's remaining `broken` items.
The route loop drives `/signup` BEFORE `/login`, so the signup result is in `out["flows"]`
when the login note is written.

Two of today's findings constrain how the inference may be drawn:

  #1203is  `_sfx` is bound ONCE outside the route loop so both flows type the same values —
           that is what makes signup's outcome say anything about this login.
  #1203iz  a flow's `ok` is `bool(token) or moved`, so a signup that merely navigated reads
           as passed while no account exists. Only a 2xx in its own `auth_status` is
           evidence that the auth surface accepted a registration.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime.test_user_validation import (  # noqa: E402
    login_401_cause_1203kf as CAUSE)


def _signup(status, ok=True):
    return {"flow": "signup", "ok": ok, "auth_status": list(status)}


def test_a_registered_signup_excludes_not_registered_1203kf():
    why = CAUSE("login", [_signup([201])])
    assert "'not registered' is excluded" in why, why
    assert "credentials or the backend" in why, why
    assert "201" in why, "cite the status that carries the exclusion"


def test_a_failed_signup_points_at_signup_first_1203kf():
    why = CAUSE("login", [_signup([409, 500])])
    assert "signup in THIS walk also failed" in why, why
    assert "fix signup first" in why, why
    assert "409" in why and "500" in why, why


def test_a_signup_that_sent_nothing_points_at_signup_too_1203kf():
    why = CAUSE("login", [_signup([])])
    assert "sent no auth request at all" in why, why
    assert "fix signup first" in why, why


def test_a_navigating_signup_is_not_taken_as_registered_1203kf():
    """#1203iz: `ok` is `bool(token) or moved`. A signup that only navigated must NOT buy the
    exclusion — the registration evidence is the 2xx, not the verdict."""
    why = CAUSE("login", [_signup([], ok=True)])
    assert "'not registered' is excluded" not in why, (
        "signup ok=True with no 2xx means it may have navigated without creating anything", why)
    assert "never created" in why, why


def test_the_signup_flow_itself_keeps_the_old_hedge_1203kf():
    """Nothing ran before signup, so there is no evidence to narrow with."""
    why = CAUSE("signup", [])
    assert why == "login user not registered / bad credentials / backend error", why


def test_a_login_with_no_signup_record_keeps_the_old_hedge_1203kf():
    why = CAUSE("login", [{"flow": "home", "auth_status": [200]}])
    assert why == "login user not registered / bad credentials / backend error", why


def test_it_survives_junk_1203kf():
    for flows in (None, [], ["not a mapping"], [{"flow": "signup"}],
                  [{"flow": "signup", "auth_status": ["x", None]}]):
        why = CAUSE("login", flows)
        assert isinstance(why, str) and why, flows


def test_the_binding_this_inference_rests_on_is_still_outside_the_loop_1203kf():
    """#1203is's placement is load-bearing for #1203kf, so pin it where the claim is made.

    If `_sfx` is ever bound INSIDE the route loop, signup and login stop typing the same
    values and "signup registered this account" stops meaning anything here.
    """
    import ast
    src = (LLM / "multi_agent" / "runtime" / "test_user_validation.py").read_text("utf-8")
    tree = ast.parse(src)
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        loops = [n for n in ast.walk(fn)
                 if isinstance(n, ast.For) and "signup" in ast.unparse(n.iter)
                 and "login" in ast.unparse(n.iter)]
        if not loops:
            continue
        inside = {t.id for lp in loops for n in ast.walk(lp)
                  if isinstance(n, ast.Assign) for t in n.targets
                  if isinstance(t, ast.Name)}
        assert "_sfx" not in inside, (
            "#1203is/#1203kf: `_sfx` must stay bound OUTSIDE the (signup, login) loop — "
            "moving it in makes both flows type different values, which makes every login "
            "read 'not registered' (#1203is measured 19 such verdicts) and makes #1203kf's "
            "narrowing wrong")
        return
    raise AssertionError("the (signup, login) route loop was not found — this test is vacuous")


def test_a_re_walked_signup_does_not_narrow_against_itself_1203kf(tmp_path=None):
    """The `label != "login"` guard, pinned on the only shape that can exercise it.

    Found by mutation: dropping that guard left every test above green, because at signup
    time `out["flows"]` is normally empty and `su is None` reaches the same sentence. It
    stops being equivalent the moment a signup entry already exists — a re-walk, or a second
    signup flow — where the unguarded version would tell the SIGNUP note that "signup in THIS
    walk registered the same values", about itself.
    """
    why = CAUSE("signup", [_signup([201])])
    assert why == "login user not registered / bad credentials / backend error", (
        "a signup flow must not be narrowed by a signup record — that is itself", why)
