"""#1202vo — "All gates point here instead of redefining it" was false, in the same shape
as #1202vl one module over.

`contract.FIXED_ENDPOINT_KINDS` carries that sentence in its own comment. The reserved-path
guard in `registryhub.register_endpoint` re-listed the seven kinds inline. They are
identical TODAY, which is the only reason nothing is broken: a kind added to the canonical
set would simply not reach the guard, and a lane could then overwrite a framework endpoint
carrying it.

#1202vl is the same claim one module over, where the drift had already happened —
`/.well-known/` was added on the lifecycle side and not on registryhub's copy.
"""
import pathlib

import pytest

from env_generator.llm_generator.multi_agent.runtime.kickoff.contract import (
    FIXED_ENDPOINT_KINDS,
)

_RH = pathlib.Path(
    __file__).resolve().parents[1] / (
    "env_generator/llm_generator/multi_agent/runtime/registryhub.py")
_CT = pathlib.Path(
    __file__).resolve().parents[1] / (
    "env_generator/llm_generator/multi_agent/runtime/kickoff/contract.py")


def _guard_block():
    """The reserved-path guard, bounded by its OWN landmarks — never a byte window.

    #943: a window sized in bytes breaks the moment a comment grows, and this file is one
    that comments heavily. The guard opens at its env flag and closes at the reserved-PATH
    test that follows the reserved-KIND one."""
    src = _RH.read_text()
    start = src.index('_os.environ.get("ENVGEN_RESERVED_PATH_GUARD")')
    end = src.index("_reserved_path = ", start)
    return src[start:end]


def test_the_guard_imports_the_canonical_set():
    block = _guard_block()
    assert "from .kickoff.contract import FIXED_ENDPOINT_KINDS" in block
    assert "_reserved_kind = _old_kind in _fixed_kinds_1202vo" in block


def test_the_guard_no_longer_re_lists_the_seven_kinds():
    """The literal set must not sit in the comparison any more. It may still appear once,
    as the fail-closed fallback, and that is checked separately below."""
    block = _guard_block()
    assert '_old_kind in {\n' not in block, "the inline set literal is back"


def test_the_fallback_is_the_historical_set_not_an_empty_one():
    """An empty set makes `_reserved_kind` always False, which DISARMS the guard silently —
    the one failure mode worse than the drift this closes."""
    block = _guard_block()
    fallback = block[block.index("except Exception:"):]
    for kind in ("auth", "oauth", "infra", "spine", "control_plane", "control", "health"):
        assert f'"{kind}"' in fallback, kind
    assert "frozenset()" not in fallback
    assert "set()" not in fallback


@pytest.mark.parametrize("kind", [
    "auth", "oauth", "infra", "spine", "control", "control_plane", "health",
])
def test_every_historical_kind_is_in_the_canonical_set(kind):
    """The import must not narrow what the guard used to treat as reserved."""
    assert kind in FIXED_ENDPOINT_KINDS


def test_a_business_kind_is_not_reserved():
    assert "custom" not in FIXED_ENDPOINT_KINDS
    assert "business" not in FIXED_ENDPOINT_KINDS


def test_the_canonical_comment_is_now_true():
    """If the claim is ever removed the import is no longer load-bearing by contract, and
    a future edit could re-inline with nothing objecting."""
    assert "All gates point here instead of redefining it" in _CT.read_text()


def test_the_response_key_set_is_deliberately_separate():
    """registryhub has a THIRD kind set — the kinds that skip response-key canonicalisation.
    It carries `custom` and lacks `control`/`health` because it answers a different
    question, so it must NOT be folded into the canonical one."""
    src = _RH.read_text()
    lit = '"auth", "oauth", "infra", "spine", "control_plane", "custom"'
    i = src.index(lit)
    # Bounded by landmarks, never a byte window (#943): the response-key branch opens at
    # the `_rk = ` read and this literal sits inside its condition.
    around = src[src.rindex("_rk = ", 0, i):i + len(lit)]
    assert "response_key" in around
    assert "custom" not in FIXED_ENDPOINT_KINDS
