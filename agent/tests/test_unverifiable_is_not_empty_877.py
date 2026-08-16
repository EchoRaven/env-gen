r"""#877: #864 collapsed "could not read" into "read back empty".

The last deferral audit. #864 verifies that the milestone roadmap landed, and on a readback
exception it did this:

    except Exception as _ms_read_err:
        _seeded = []                                   # <- a FAILED read
        ...
    if not _seeded:
        logger.error("... store reads back EMPTY")      # <- reported as a CONFIRMED empty store

★ **#864's own comment cites the distinction and #873 named it** — *"no information is not
information saying no"* — and #864 then committed the error it was the reference example for.
Third instance this session of a first cut merging the two (#864 here, #873's design gate, and
#872's judged-vs-unjudged boundary, which got it right only because the code already did).

It matters precisely where it fires: a run whose roadmap is fine but whose readback hiccuped would
be told *"MILESTONE ROADMAP DID NOT LAND"* at the exact moment someone is reading the log to
diagnose a dead run. A misdiagnosis in a diagnostic is worse than no diagnostic.

Two branches now, with different severities, different messages and different payloads
(`read_back: 0` vs `read_back: None, unverifiable: True`). Neither aborts — that half of #864's
deferral survives, and this is why: **a false positive is possible**, which was the deferral's
stated premise all along. Auditing it turned the premise from an assumption into a mechanism.
"""
import inspect
import re

import pytest

from env_generator.llm_generator.multi_agent import orchestrator as orch


def _span():
    src = inspect.getsource(orch)
    start = src.index("#877: \"could not read\" is not")
    end = src.index("for _m_idx, _milestone in enumerate", start)
    return src[start:end]


def test_the_block_is_findable():
    """Non-vacuity."""
    assert "#877: \"could not read\" is not" in inspect.getsource(orch)


def test_a_raised_readback_is_reported_as_unverifiable():
    span = _span()
    assert "UNVERIFIABLE" in span
    assert "readback RAISED" in span


def test_a_confirmed_empty_store_keeps_its_own_message():
    span = _span()
    assert "DID NOT LAND" in span
    assert "reads back " in span


def test_the_empty_branch_no_longer_fires_on_a_failed_read():
    """★ The defect. `if not _seeded` alone caught both cases."""
    span = _span()
    assert "if _read_ok and not _seeded:" in span
    assert re.search(r"_seeded, _read_ok = \[\], False", span)


def test_the_two_payloads_are_distinguishable():
    """A downstream reader of `progress_events.jsonl` must be able to tell them apart without
    parsing prose."""
    span = _span()
    assert '"read_back": 0' in span
    assert '"read_back": None' in span and '"unverifiable": True' in span


def test_the_unverifiable_branch_says_the_roadmap_may_be_fine():
    """★ The whole point: it must not accuse the roadmap. It reports that the CHECK could not run
    — #790/#792's shape one level up."""
    span = _span()
    assert "may be fine" in span
    assert "790" in span or "792" in span


def test_neither_branch_aborts():
    """#864's other half survives the audit: a false positive is possible — this ticket is the
    proof — so aborting would trade a silent failure for a louder wrong one."""
    span = _span()
    assert "raise" not in span
    assert "sys.exit" not in span


def test_observability_cannot_break_the_boot():
    """Both emits are guarded; a throwing progress sink must not become the reason kickoff fails."""
    span = _span()
    assert span.count("except Exception") >= 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
