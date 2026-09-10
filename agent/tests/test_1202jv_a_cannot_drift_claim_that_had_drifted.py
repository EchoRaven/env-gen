"""#1202jv: "can never drift apart" was a claim about the import, not about the copy under it.

`_owner_fk_vocabulary` imports route_projector's `_OWNER_FK_NAMES | _TARGET_FK_NAMES` and
says the two sides "can never drift apart" — true of the import, and the fallback beneath it
had already drifted. It was missing `profile_id`, which the read side gained with the
multi-profile work (#548/#1190).

Production never noticed: the relative import succeeds there. On the isolated path the seed
would not have filled `profile_id`, owner-scoped reads would have matched nothing, and the
failure `_seed_infer_fk`'s own docstring describes would follow — "avachen logged in but saw
0 folders/messages/events".

Found by treating absolute claims as testable: a comment saying two artefacts cannot diverge
is a hypothesis the corpus or the code can check, and #1202ju was the same shape hours earlier
("the MCP surface cannot drift from the endpoints" — it had, by 11 tools).
"""
import sys
import pathlib

_AGENT = pathlib.Path(__file__).resolve().parents[1]
if str(_AGENT) not in sys.path:
    sys.path.insert(0, str(_AGENT))

from env_generator.llm_generator.multi_agent.runtime import backend_skeleton as BS  # noqa: E402
from env_generator.llm_generator.multi_agent.runtime import route_projector as RP  # noqa: E402


def test_the_fallback_equals_the_source_of_truth():
    """★ The whole claim. A divergence here is silent in production and fatal in isolation."""
    truth = frozenset(RP._OWNER_FK_NAMES) | frozenset(RP._TARGET_FK_NAMES)
    assert BS._OWNER_FK_VOCAB_FALLBACK_1202JV == truth, (
        "seed and owner-scoped reads must recognise the SAME owner columns; missing from the "
        f"fallback: {sorted(truth - BS._OWNER_FK_VOCAB_FALLBACK_1202JV)}, extra: "
        f"{sorted(BS._OWNER_FK_VOCAB_FALLBACK_1202JV - truth)}")


def test_the_live_path_returns_the_imported_set():
    truth = frozenset(RP._OWNER_FK_NAMES) | frozenset(RP._TARGET_FK_NAMES)
    assert BS._owner_fk_vocabulary() == truth


def test_the_fallback_is_reachable_and_is_that_set(monkeypatch):
    """Non-vacuity: the equality above is worthless if the fallback is dead code.

    Forces the import to fail the way an isolated import would.
    """
    import builtins
    real = builtins.__import__

    def _boom(name, *a, **k):
        if "route_projector" in name:
            raise ImportError("simulated isolation")
        return real(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", _boom)
    assert BS._owner_fk_vocabulary() == BS._OWNER_FK_VOCAB_FALLBACK_1202JV


def test_profile_id_is_in_both(monkeypatch):
    """The item that had actually drifted, named so a revert is legible."""
    assert "profile_id" in BS._OWNER_FK_VOCAB_FALLBACK_1202JV
    assert "profile_id" in BS._owner_fk_vocabulary()
