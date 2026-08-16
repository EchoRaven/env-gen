r"""#882: a failed kickoff-finalized check silently turned the wake-storm guard off.

Triage of the nine silent decision-driving swallows #881 listed. Classified:

| | |
|---|---|
| benign by design | `run_kickoff:1861` (two-path lookup), `material_prep:717` (falls to the non-image path, as its comment says) |
| already logged | `messaging:1653` (warning + plain-text fallback), `orchestrator:2075` (error) |
| **silent, fails OPEN** | `messaging:170` ← this, `codehub/service:1175`, `visual_fidelity:3639`, `workflow_policies:516` |
| **silent, fails CLOSED** | `workflow_policies:1977` — `has_retro = False` makes the gate **block** |

★ **The most useful thing in that table is the last two rows.** The same codebase makes *opposite*
choices for the same shape, both silently: eight sites fail open, one fails closed, and nothing at
any of them says which. Reading the handler is the only way to know whether a hub hiccup means
"ship it" or "block it".

**This site is the sharpest of the open ones.** `_pre_finalize = False` on error reads as *kickoff
IS finalized*, which turns the F2b retention guard OFF and re-enables the wake-storm it exists to
prevent — the one that cost r3 **146 idle stop-cycles** of model quota.

The permissive default is kept: a hub hiccup must not wedge every lane. What was missing is that it
was **indistinguishable from a healthy "kickoff is done"**.
"""
import inspect

import pytest

from env_generator.llm_generator.multi_agent.agents.runtime import messaging as m


def _span():
    src = inspect.getsource(m)
    start = src.index("#882: a FAILED check here")
    end = src.index("_pre_finalize = False", src.index("_said_kf_882 = True", start))
    return src[start:end]


def test_the_site_is_findable():
    """Non-vacuity."""
    assert "kickoff_finalized_signal" in inspect.getsource(m)
    assert "#882: a FAILED check here" in inspect.getsource(m)


def test_the_handler_is_no_longer_bare():
    span = _span()
    assert "except Exception as _kf_exc:" in inspect.getsource(m)
    assert "_logger.warning" in span


def test_it_says_which_way_it_failed():
    """★ The point of the whole triage: a reader must not have to open the handler to learn
    whether a hiccup means ship-it or block-it."""
    span = _span()
    assert "F2b retention is OFF" in span
    assert "permissive default" in span and "NOT evidence" in span


def test_it_names_the_cost():
    span = _span()
    assert "wake-storm" in span
    assert "146" in span


def test_it_says_it_once_per_agent():
    """This runs on every inbox message; a per-message warning is #845's defect."""
    src = inspect.getsource(m)
    assert src.count("_said_kf_882") >= 2


def test_the_permissive_default_survives():
    """Failing open is deliberate — a hub hiccup must not wedge every lane. Only the silence was
    the defect."""
    src = inspect.getsource(m)
    start = src.index("#882: a FAILED check here")
    end = src.index("if _pre_finalize:", start)      # the branch the default feeds
    assert "_pre_finalize = False" in src[start:end]


def test_the_guard_it_protects_still_exists():
    """Non-vacuity for the premise: if F2b's retention branch goes away, this warning is naming a
    consequence that no longer happens."""
    src = inspect.getsource(m)
    assert "if _pre_finalize:" in src
    assert "without \nwakeup" in src or "without" in src and "wakeup" in src


def test_the_fail_closed_sibling_is_still_the_odd_one_out():
    """★ Pins the inconsistency the triage found, so it is a recorded state rather than a memory.
    `workflow_policies`' retro gate treats a failed lookup as 'no retro' and BLOCKS, opposite to
    every other site in the census."""
    from env_generator.llm_generator.multi_agent import workflow_policies as wp
    src = inspect.getsource(wp)
    # anchor on the EXCEPT-arm occurrence, not the first `has_retro = False` in the file — there
    # are several, and the first is an ordinary initialisation. Anchoring on the bare token was
    # this test reaching for the same shortcut the session keeps punishing.
    i = src.index("except Exception:\n            has_retro = False")
    tail = src[i:src.index("gen_label", i)]
    assert "if has_retro:" in tail, tail
    assert "return None" in tail, "the fail-closed direction changed"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
