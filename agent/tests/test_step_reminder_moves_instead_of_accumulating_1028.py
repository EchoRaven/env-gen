r"""#1028: a byte-identical 122-token block was appended once per step, forever.

Found by widening #1027: of the 8 sites in `step_runner` that append a user message into the
per-step conversation, only hub_pulse had a dedup. The step-reminder block is the one that
actually fires in every netflix run.

    source          execution_pipeline_defaults.step_reminders  (agents_config.yaml:37/69)
    reaches         EVERY agent — configurable_agent reads
                    `self._execution_pipeline_cfg.get("step_reminders")`
    rendered        488 chars / ~122 tokens, and BYTE-IDENTICAL on every call
    expiry          `advance_step_reminders` consumes only TTL-bound items, and `ttl_steps`
                    appears **0 times** in agents_config — nothing ever expires
    reclaimed       nothing. `_mask_old_observations` truncates TOOL output bodies only, and
                    it skips entirely while history fits the working budget (666,400 chars
                    for this model), which it does

So a wake accumulated one identical copy per step, none of it maskable.

★ Plain dedup — hub_pulse's fix and #1027's — would be WRONG here, which is why this is a
separate ticket rather than the same patch. The block exists to be read "before doing anything
in this step"; suppressing it after step 1 defeats its purpose. **Moving** it keeps exactly one
copy, always last, which is precisely what
`_build_step_reminder_prompt`'s docstring already claims it does ("injected at the start of
every step"). Intent preserved, N-1 duplicates gone.

Removal is by IDENTITY, not equality: `messages` legitimately holds other user turns and an
`==` removal could delete a different message that compares equal.
"""
import inspect

import pytest

from env_generator.llm_generator.multi_agent.agents.runtime import step_runner as sr


def _block():
    s = inspect.getsource(sr)
    i = s.index("if step_reminder_prompt:")
    return s[i:s.index("advance_step_reminders", i)]


# --- the mechanism -------------------------------------------------------------------------

def test_the_previous_copy_is_removed_before_appending():
    b = _block()
    assert "_last_step_reminder_msg" in b
    assert "del messages[" in b


def test_removal_is_by_identity_not_equality():
    """`messages.remove(x)` uses __eq__ and could delete a different, equal message."""
    b = _block()
    assert "is _prev_reminder" in b
    assert "messages.remove(" not in b


def test_the_fresh_copy_is_appended_last():
    b = _block()
    assert b.index("del messages[") < b.index("messages.append(_reminder_msg)")


def test_the_new_message_is_tracked_for_next_step():
    b = _block()
    i = b.index("messages.append(_reminder_msg)")
    assert "self._last_step_reminder_msg = _reminder_msg" in b[i:]


def test_the_tracker_is_reset_per_wake():
    s = inspect.getsource(sr)
    assert "self._last_step_reminder_msg = None" in s


def test_ttl_advance_still_runs():
    """The move must not skip TTL consumption — that would make TTL reminders immortal."""
    assert "advance_step_reminders" in inspect.getsource(sr)


# --- behaviour, exercised on a real list ------------------------------------------------------

class _Msg:
    """Stand-in with VALUE equality, so an identity-based removal is actually being tested."""
    def __init__(self, text): self.text = text
    def __eq__(self, other): return isinstance(other, _Msg) and other.text == self.text
    def __hash__(self): return hash(self.text)


def _move_to_end(messages, prev, fresh):
    """Mirror of the production expression."""
    if prev is not None:
        for i, m in enumerate(messages):
            if m is prev:
                del messages[i]
                break
    messages.append(fresh)
    return fresh


def test_one_copy_survives_across_many_steps():
    msgs, prev = [], None
    for step in range(200):
        msgs.append(_Msg(f"assistant turn {step}"))
        prev = _move_to_end(msgs, prev, _Msg("REMINDER"))
    assert sum(1 for m in msgs if m.text == "REMINDER") == 1, "duplicates accumulated"
    assert msgs[-1].text == "REMINDER", "the surviving copy must be last (recency is the point)"


def test_an_equal_but_different_message_is_not_deleted():
    """★ The identity requirement, exercised. A user turn that happens to equal the reminder
    must survive — `remove()` would have deleted this one instead."""
    decoy = _Msg("REMINDER")
    msgs = [decoy]
    prev = _move_to_end(msgs, None, _Msg("REMINDER"))
    _move_to_end(msgs, prev, _Msg("REMINDER"))
    assert decoy in msgs and any(m is decoy for m in msgs), "the decoy user turn was deleted"
    assert sum(1 for m in msgs if m.text == "REMINDER") == 2  # decoy + the one live copy


def test_a_missing_previous_copy_is_tolerated():
    """Condensation can rebuild `messages`; the tracked object may simply be gone."""
    msgs = [_Msg("a")]
    stale = _Msg("REMINDER")          # never inserted
    _move_to_end(msgs, stale, _Msg("REMINDER"))
    assert len(msgs) == 2


# --- the premise, so a config change invalidates this loudly ------------------------------------

def test_the_reminder_is_configured_and_never_expires():
    import pathlib
    import yaml
    p = (pathlib.Path(inspect.getfile(sr)).parents[2]
         / "agents" / "agents_config.yaml")
    cfg = yaml.safe_load(p.read_text(encoding="utf-8"))
    rem = (cfg.get("execution_pipeline_defaults") or {}).get("step_reminders") or []
    assert rem, "no pinned reminders — #1028's premise is gone, re-measure before trusting it"
    assert "ttl_steps" not in p.read_text(encoding="utf-8"), (
        "a TTL now exists; reminders can expire and the accumulation story changes")


def test_the_measurement_travels_with_the_fix():
    d = " ".join((__doc__ or "").split())
    assert "488 chars" in d and "0 times" in d
    assert "TOOL output bodies only" in d, (
        "why masking cannot reclaim it must stay attached — it is the reason this matters")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
