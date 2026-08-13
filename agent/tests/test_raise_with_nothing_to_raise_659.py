r"""#659: `raise last_error` when there is no last error — a TypeError that names nothing.

Two retry helpers end with a bare `raise last_error`:

    agent/utils/llm.py          (the LLM call retry loop)
    agent/utils/base_agent.py   (the generic agent retry helper)

`last_error` starts as None and is only assigned inside the loop body. When the attempt budget
resolves to 0 the body never runs, so the function ends at `raise None`:

    TypeError: exceptions must derive from BaseException

which names neither the call that failed nor why. Reaching it takes only a config value:
`utils/config.py` defaults `retry_attempts` to 3 but reads it straight out of the LLM config
block (`llm_data.get("retry_attempts", 3)`), and `retry_attempts: 0` is the natural way to write
"do not retry". `max_retries = max_retries or self.config.retry_attempts` then resolves to 0,
`total_attempts` is 0, and every LLM call in the run dies with that message.

Same family as #634/#635/#636/#642/#657: an error whose text misdescribes the condition costs a
whole debugging round. Surfaced by the type checker (`bad-raise`: "Expression `last_error` has
type `Exception | None`, expected `BaseException`") once [tool.pyrefly] let it resolve imports.
"""
import re
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
_SITES = {
    "utils/llm.py": "the retry budget resolved to",
    "utils/base_agent.py": "the budget resolved to",
}


def _src(rel):
    return (_ROOT / rel).read_text(encoding="utf-8")


# --- the premise --------------------------------------------------------------------------------

def test_raising_None_really_is_this_unhelpful():
    """Pins what the old code produced, so the reason for the guard stays legible."""
    last_error = None
    with pytest.raises(TypeError) as ei:
        raise last_error
    assert "must derive from BaseException" in str(ei.value)


def test_the_config_default_is_overridable():
    """The trap needs `retry_attempts` to be settable to 0, not just defaulted to 3."""
    cfg = _src("utils/config.py")
    assert "retry_attempts: int = 3" in cfg
    assert 'llm_data.get("retry_attempts", 3)' in cfg


# --- both sites are guarded ----------------------------------------------------------------------

@pytest.mark.parametrize("rel,needle", sorted(_SITES.items()))
def test_the_site_checks_before_raising(rel, needle):
    src = _src(rel)
    assert "if last_error is None:" in src
    assert needle in src


@pytest.mark.parametrize("rel", sorted(_SITES))
def test_the_guard_precedes_the_raise(rel):
    src = _src(rel)
    assert src.index("if last_error is None:") < src.rindex("raise last_error")


@pytest.mark.parametrize("rel", sorted(_SITES))
def test_the_replacement_is_a_real_exception(rel):
    """It must not swap one non-exception for another."""
    src = _src(rel)
    i = src.index("if last_error is None:")
    block = src[i:src.index("raise last_error", i)]
    assert "raise RuntimeError(" in block


@pytest.mark.parametrize("rel", sorted(_SITES))
def test_the_message_says_how_to_fix_it(rel):
    """#634: naming the condition without naming the remedy still costs a round."""
    src = _src(rel)
    i = src.index("if last_error is None:")
    block = src[i:src.index("raise last_error", i)]
    assert "at least 1" in block


@pytest.mark.parametrize("rel", sorted(_SITES))
def test_the_message_reports_the_resolved_budget(rel):
    """The number is the whole diagnosis — without it the reader cannot tell which knob."""
    src = _src(rel)
    i = src.index("if last_error is None:")
    block = src[i:src.index("raise last_error", i)]
    assert re.search(r"\{(total_attempts|max_tries)\}", block)


# --- a real error still propagates unchanged ------------------------------------------------------

@pytest.mark.parametrize("rel", sorted(_SITES))
def test_a_genuine_last_error_is_still_raised_as_is(rel):
    """The guard must be a NEW branch, not a replacement — swallowing the real cause is worse."""
    assert "raise last_error" in _src(rel)


def test_the_guard_only_fires_on_None():
    """Behavioural check of the shape both sites use."""
    def helper(last_error, budget):
        if last_error is None:
            raise RuntimeError(f"no attempts: budget resolved to {budget}. Set it to at least 1.")
        raise last_error

    with pytest.raises(RuntimeError, match="budget resolved to 0"):
        helper(None, 0)
    with pytest.raises(ValueError, match="the real one"):
        helper(ValueError("the real one"), 3)


def test_the_measurement_is_recorded():
    for rel in _SITES:
        flat = " ".join(_src(rel).replace("#", " ").split())
        assert "retry_attempts: 0" in flat, rel
        assert "must derive from BaseException" in flat, rel


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
