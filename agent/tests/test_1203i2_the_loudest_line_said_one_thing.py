"""#1203i2: the framework's loudest warning carried two distinct messages in total.

`#1202wj` announces that FIX #192a's cross-user probe was suppressed by a TOKENLESS 401 --
a real gap, reported deliberately and changing no verdict. It was a bare
`logging.warning` on a path that runs per chain per augmentation, and it became the loudest
line in the framework:

    14791 lines across the last 13 runs      (twice `FIX #150`'s dispatch-full warning,
                                              which is the next loudest)
    2 distinct messages, in total
    r171 alone: the identical sentence 3320 times

`#1202ad` exists for exactly this, and its own comment lists the five prior instances it was
written for -- #1202n (r26, 134 lines / 2 states), #1202p (416 / 4), #1202v (213 / 1),
#1202ab (280 / 9), #1202ac (117 / 1). This one is larger than all five together by an order
of magnitude.

The cost is not only bytes. Ranking the framework's warnings by volume is a diagnostic
instrument -- it is how this defect was found -- and this line dominated that ranking at 2x
the next while saying one thing.

It is a STATE, not a heartbeat: `#1202ad` is deliberately not log-once, so a chain
RE-AUTHORED into a different shape that still has no cross-user denial is news again. The
sentence itself is unchanged, and the verdict was never touched.
"""
import logging
import os
import sys

import pytest

_AGENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_AGENT, "env_generator", "llm_generator"))

from multi_agent.runtime.chain_executor import normalize_steps  # noqa: E402
from multi_agent.runtime.message_format import (  # noqa: E402
    reset_state_memo_1202ad,
    state_changed_1202ad,
)

SITE = "chain_executor.isolation_suppressed_1202wj"


@pytest.fixture(autouse=True)
def _fresh():
    reset_state_memo_1202ad(SITE)
    yield
    reset_state_memo_1202ad(SITE)


def _warned(caplog):
    return [r.getMessage() for r in caplog.records if "#1202wj" in r.getMessage()]


def _chain(first_path="/auth/register", extra=0):
    """A chain whose only denial is a TOKENLESS 401 -- the shape #1202wj reports."""
    steps = [
        {"method": "POST", "path": first_path, "expect": [200, 201],
         "save": {"tokenA": "access_token"}},
        {"method": "GET", "path": "/api/users/me", "expect": [401]},
        {"method": "POST", "path": "/api/items", "expect": [200, 201],
         "save": {"itemA": "id"}, "headers": {"Authorization": "Bearer ${tokenA}"}},
    ]
    for i in range(extra):
        steps.append({"method": "GET", "path": "/api/items/pad%d" % i, "expect": [200]})
    return steps


def test_the_same_chain_is_announced_once_not_three_thousand_times(caplog):
    with caplog.at_level(logging.WARNING):
        for _ in range(25):
            normalize_steps(_chain())
    said = _warned(caplog)
    assert len(said) == 1, "expected one line for 25 augmentations, got %d" % len(said)


def test_the_sentence_is_unchanged(caplog):
    with caplog.at_level(logging.WARNING):
        normalize_steps(_chain())
    said = _warned(caplog)[0]
    for phrase in ("counts as isolation-covered on a TOKENLESS",
                   "no step asks whether one user may reach another's row",
                   "the cross-user probe is suppressed because a 401 was found",
                   "hands any valid token full access"):
        assert phrase in said, (phrase, said)


def test_it_still_names_where_the_chain_starts(caplog):
    with caplog.at_level(logging.WARNING):
        normalize_steps(_chain())
    assert "POST /auth/register" in _warned(caplog)[0]


def test_the_line_cannot_tell_which_chain_it_is_about(caplog):
    """★ MEASURED AND DELIBERATELY NOT FIXED HERE, and it is why the dedup loses nothing.

    The sentence says "a chain starting X". X comes from the first step of `out` AT THAT
    POINT, and `normalize_steps` has already prepended the framework's own auth step -- so
    five chains whose real first steps are `/auth/register`, `/api/v1/auth/register`,
    `/auth/signup`, `/api/auth/login` and `/api/accounts` ALL print "POST /auth/register".
    That is the whole explanation for 14791 lines carrying 2 distinct messages: the printed
    identity is a near-constant.

    So deduplicating on it removes repetitions of a sentence that was already identical for
    every chain -- nothing that was being communicated is lost. Naming the chain properly is
    a change to the MESSAGE and needs the chain's name plumbed into `normalize_steps`, whose
    signature takes `steps` alone; that is a separate patch across its callers, not this one.
    """
    with caplog.at_level(logging.WARNING):
        for first in ("/auth/register", "/api/v1/auth/register", "/auth/signup",
                      "/api/auth/login", "/api/accounts"):
            normalize_steps(_chain(first))
    said = _warned(caplog)
    assert len(said) == 1, "five distinct chains produced %d lines" % len(said)
    assert "POST /auth/register" in said[0], said[0]


def test_a_rotation_of_such_chains_is_still_one_line(caplog):
    """★ WHY THE STATE IS THE PRINTED STEP AND NOTHING MORE. The first version of this patch
    put `(first_step, len(steps))` in the state, so that a chain re-authored into a different
    shape would be "news again" -- #1202ad's state-vs-heartbeat rule. A mutation round killed
    it: chains sharing a first step (the normal case, since `normalize_steps` canonicalises
    the register path) share the site key, so their differing step counts evict each other and
    a ROTATION of them reports on every pass, rebuilding the heartbeat. r171's rotation is how
    it reached 3320 lines.

    The line prints the first step and nothing else -- 3320 lines, one distinct message -- so
    a differently-shaped chain has no different sentence to say. A,B,A is ONE line."""
    a, b = _chain(extra=0), _chain(extra=4)
    with caplog.at_level(logging.WARNING):
        for steps in (a, b, a, b, a):
            normalize_steps(list(steps))
    said = _warned(caplog)
    assert len(said) == 1, "a rotation produced %d lines" % len(said)


def test_the_memo_separates_two_identities_when_there_are_two():
    """★ A HELPER-LEVEL TEST, SAID SO ON PURPOSE -- and the reason no caller-level one exists.

    `site` carries the printed identity because that is the helper's stated rule ("include
    the page/lane/table when the same code reports per-item"). Flattening it to a constant
    survived three mutation rounds, and the honest reason is not a weak test: the printed
    identity is a NEAR-CONSTANT. `normalize_steps` prepends the framework's own auth step, so
    every chain tried here -- `/auth/register`, `/api/v1/auth/register`, `/auth/signup`,
    `/api/auth/login`, `/api/accounts` -- prints `POST /auth/register`, and the whole corpus
    holds 2 distinct messages in 14791 lines. With one identity in play, keying on it and
    keying on a constant ARE the same behaviour, so no fixture through `normalize_steps` can
    tell them apart. Pretending otherwise would be testing the helper and calling it the
    caller -- the mistake that produced the first two drafts of this file.

    The key keeps the identity anyway: it costs nothing and is correct the day a second
    identity appears. What this test pins is the helper contract that makes that true."""
    reset_state_memo_1202ad(SITE)
    assert state_changed_1202ad(SITE + ":POST /auth/register", "suppressed") is True
    assert state_changed_1202ad(SITE + ":POST /auth/login", "suppressed") is True
    assert state_changed_1202ad(SITE + ":POST /auth/register", "suppressed") is False


def test_a_memo_failure_must_not_silence_the_report(caplog, monkeypatch):
    """The memo is best-effort; losing it must lose the DEDUP, never the warning."""
    import builtins
    real = builtins.__import__

    def no_memo(name, *a, **k):
        if "message_format" in name:
            raise ImportError("memo unavailable")
        return real(name, *a, **k)
    monkeypatch.setattr(builtins, "__import__", no_memo)
    with caplog.at_level(logging.WARNING):
        normalize_steps(_chain())
        normalize_steps(_chain())
    assert len(_warned(caplog)) == 2, "a memo failure silenced the report"


def test_the_memo_itself_reports_a_moved_state(caplog):
    """Pin the helper's contract this patch leans on, so a change there turns this red."""
    assert state_changed_1202ad(SITE + ":x", "suppressed") is True
    assert state_changed_1202ad(SITE + ":x", "suppressed") is False
    assert state_changed_1202ad(SITE + ":y", "suppressed") is True


def test_a_chain_with_a_real_cross_user_denial_says_nothing(caplog):
    """The condition is untouched: this fires only for the tokenless-only shape."""
    steps = _chain()
    steps.append({"method": "PUT", "path": "/api/items/${itemA}", "expect": [403],
                  "headers": {"Authorization": "Bearer ${tokenB}"}})
    steps.insert(1, {"method": "POST", "path": "/auth/register", "expect": [200, 201],
                     "save": {"tokenB": "access_token"}})
    with caplog.at_level(logging.WARNING):
        normalize_steps(steps)
    assert _warned(caplog) == [], _warned(caplog)
