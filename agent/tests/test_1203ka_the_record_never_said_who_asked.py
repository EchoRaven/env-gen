"""#1203ka: a chain result recorded WHAT was asked and never WHO asked it.

`execute_chain` decides the actor per step — `token = variables.get(step["auth"]) if
step["auth"] else None` — and then dropped it. Two steps differing ONLY by actor landed in
`registryhub_verification_chains.json` as the same request.

instagram-core-r174's `login_light` is the shape: step 5 `GET /api/me` expect [401] and step 6
`GET /api/me` expect [200], both `ok: true`. The distinction is not implicit — #266's
auto-bearer puts `auth="token"` on an /api/ path and #91 POPS it back off for a pure-{401}
probe so the probe really goes anonymous. That decision was load-bearing and unrecorded.

Measured over 199 runs: replaying `unsatisfiable_expectation_pairs` (keyed on
`_request_identity`, which reads `auth`) over these RESULT records flags 660 pairs, 147 of them
across 24 modern runs; over the AUTHORED chains in the same files it flags zero. All 1320
implicated steps carry `ok: true`, which one request answering two ways cannot do. The
predicate was right; the record was lying to it by omission.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime import chain_executor as CE  # noqa: E402


def _chain_1203ka():
    """The r174 shape: a login, then the same path read anonymously and then authenticated.

    The writes sit BEFORE the pair on purpose — #586 skips a pair with a write BETWEEN its two
    steps, so a login placed in the middle would make the assertions below vacuous.

    The second register exists because `normalize_steps` canonicalises an auth ref NO step
    produces down to the one token that exists (measured: `auth="tokenB"` with no source
    becomes `auth="token"`, and #586 is then RIGHT to flag the pair). A cross-user probe is
    only a different actor if some step actually mints that actor.
    """
    steps, errs = CE.normalize_steps([
        {"action": "register", "method": "POST", "path": "/auth/register",
         "body": {"email": "a@b.c", "password": "x"}, "expect": [200, 201],
         "save": {"token": "token"}},
        {"action": "register_intruder", "method": "POST", "path": "/auth/register",
         "body": {"email": "i@b.c", "password": "y"}, "expect": [200, 201],
         "save": {"tokenB": "token"}},
        {"action": "viewer_requires_auth", "method": "GET", "path": "/api/me", "expect": [401]},
        {"action": "read_primary_viewer", "method": "GET", "path": "/api/me", "expect": [200]},
        # a CROSS-USER probe keeps its own actor. It is here so the recorded value has to COME
        # FROM the step: a patch that hardcoded "token" would satisfy every other assertion.
        {"action": "intruder_denied", "method": "GET", "path": "/api/me",
         "auth": "tokenB", "expect": [403]},
    ])
    assert not errs, errs
    return steps


def test_normalisation_really_makes_the_two_reads_different_actors_1203ka():
    """Non-vacuity for everything below: #91/#266 must actually have split the actors."""
    steps = _chain_1203ka()
    assert "auth" not in steps[2], (
        "#91 must strip the bearer off a pure-{401} probe, else this fixture tests nothing")
    assert steps[3].get("auth") == "token", (
        "#266's auto-bearer must put an actor on the /api/ read, else this fixture tests nothing")
    assert steps[4].get("auth") == "tokenB", (
        "the cross-user probe must keep its OWN actor, else the hardcoding mutation survives")


def _run_1203ka(monkeypatch):
    def _fake(method, url, *, token=None, body=None, timeout=None, headers=None, **kw):
        if "/auth/register" in url:
            # the intruder's register must mint a DIFFERENT token, or "a different actor" is
            # a claim this fixture cannot make
            _t = "TB" if "i@b.c" in str(body) else "T"
            return {"status": 201,
                    "body_text": '{"access_token": "%s", "token": "%s", "id": 1}' % (_t, _t),
                    "error": None, "headers": {}}
        if token == "TB":
            return {"status": 403, "body_text": '{"detail":"forbidden"}', "error": None,
                    "headers": {}}
        if token:
            return {"status": 200, "body_text": '{"id": 1, "email": "a@b.c"}', "error": None,
                    "headers": {}}
        return {"status": 401, "body_text": '{"detail":"Not authenticated"}', "error": None,
                "headers": {}}
    monkeypatch.setattr(CE, "_http", _fake)
    return CE.execute_chain("http://127.0.0.1:1", {"name": "login_light",
                                                   "steps": _chain_1203ka()})


def test_the_result_records_which_actor_made_each_request_1203ka(monkeypatch):
    out = _run_1203ka(monkeypatch)
    recorded = out.get("steps") or []
    assert len(recorded) == 5, recorded
    by_action = {str(s.get("action")): s for s in recorded}

    anon = by_action["viewer_requires_auth"]
    authed = by_action["read_primary_viewer"]
    # the chain itself has to have passed, or this is a record of something else
    assert anon.get("ok") is True and authed.get("ok") is True, recorded
    assert anon.get("status") == 401 and authed.get("status") == 200, recorded

    # SAME convention as the authored step: present means that actor, absent means anonymous.
    assert "auth" not in anon, (
        "#1203ka: the anonymous probe must stay absent, matching the normalized step "
        "(test_235_auth_bootstrap_synonyms pins that reading)")
    assert by_action["intruder_denied"].get("auth") == "tokenB", (
        "#1203ka: the recorded actor must be the STEP's actor, not a constant — a cross-user "
        "probe mislabelled as the owner is worse than an unrecorded one")
    assert authed.get("auth") == "token", (
        "#1203ka: the record must say WHO asked. Without it the two reads of /api/me are the "
        "same request in the store, and the framework's own #586 predicate reads them as a "
        "chain demanding two answers from one call — 660 such false pairs across 199 runs.")


def test_the_framework_can_re_judge_its_own_record_1203ka(monkeypatch):
    """The payoff, and its own non-vacuity: #586 over the RESULT must agree with #586 over the
    declaration — and must stop agreeing the moment the actor is dropped again."""
    out = _run_1203ka(monkeypatch)
    recorded = out.get("steps") or []

    # over the AUTHORED steps the predicate is clean, which is the answer the result must match
    assert CE.unsatisfiable_expectation_pairs(_chain_1203ka()) == []
    assert CE.unsatisfiable_expectation_pairs(recorded) == [], (
        "#1203ka: with the actor recorded, re-judging the result agrees with the declaration")

    # NON-VACUITY: drop the actor back out and the false pair returns. Without this the test
    # above would pass just as well on a predicate that can never flag anything.
    stripped = [{k: v for k, v in s.items() if k != "auth"} for s in recorded]
    assert CE.unsatisfiable_expectation_pairs(stripped) != [], (
        "the fixture must be able to produce the false pair, or it proves nothing about the fix")
