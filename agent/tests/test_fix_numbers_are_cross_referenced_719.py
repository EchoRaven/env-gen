r"""#719: a finding in the record and a fix in the code are two ends of one thing, joined by hand.

EXPERIMENTS_PENDING writes up a finding; the code carries the fix under a `#NNN`. Nothing connects
them unless someone types the number, so a reader arriving at either end cannot reach the other.
Three of this session's fixes were in exactly that state and it took an audit to notice:

    #714  the phantom-remediation loop is documented in full — "5835 of 21550 deviations, 27%,
          describe a screen the gate never photographed" — with no pointer to the fix acting on it
    #695  documented at item 22, unnumbered
    #697  documented in item 16's never-written list, unnumbered

That is the same shape as every stale-comment defect this session found, applied to the record
itself. The raw audit number was misleading and worth recording as a caution: "12 of 28 findings
appear in all three of doc / code / checker" sounds alarming, but narrowing to what is actionable
gives ZERO findings that emit a runtime warning without a checker signature, and the doc gaps were
missing cross-references rather than missing content.

The guard is deliberately narrow. It does NOT require a doc entry for every number — some fixes
state a contract and change no reachable behaviour, and the experiments file has nothing to track
for them. Those are exempted BY NAME with the reason, so an exemption is a claim someone can check
rather than a silent hole.
"""
import re
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
DOC = ROOT / "EXPERIMENTS_PENDING_2026-08-13.md"
SRC_ROOT = ROOT / "agent" / "env_generator" / "llm_generator"

# This session's range. Older numbers predate the document and are not its business.
FIRST, LAST = 691, 760

# Numbers that deliberately have no entry, with the reason. An exemption must say WHY.
NO_DOC_ENTRY = {
    704: "states a precondition and changes no reachable behaviour — nothing to track",
}


def _source() -> str:
    return "".join(p.read_text(errors="ignore") for p in SRC_ROOT.rglob("*.py"))


def _numbers_in_code():
    return {int(m.group(1)) for m in re.finditer(r"#(\d{3})\b", _source())
            if FIRST <= int(m.group(1)) <= LAST}


def _doc() -> str:
    return DOC.read_text(encoding="utf-8")


# --- the guard ---------------------------------------------------------------------------------

def test_the_document_exists_and_is_substantial():
    assert DOC.is_file() and len(_doc()) > 10_000


def test_the_sweep_finds_this_sessions_numbers():
    nums = _numbers_in_code()
    assert len(nums) >= 15, f"only found {sorted(nums)} — has the range moved?"


def test_every_fix_number_is_reachable_from_the_record():
    doc = _doc()
    orphans = [n for n in sorted(_numbers_in_code())
               if n not in NO_DOC_ENTRY and not re.search(rf"#{n}\b", doc)]
    assert not orphans, (
        "these fixes exist in code with no mention in EXPERIMENTS_PENDING, so a reader of the "
        "record cannot reach them: " + ", ".join(f"#{n}" for n in orphans))


@pytest.mark.parametrize("num,reason", sorted(NO_DOC_ENTRY.items()))
def test_an_exemption_states_its_reason(num, reason):
    assert len(reason) > 20, "an exemption without a reason is a silent hole"
    assert num in _numbers_in_code(), f"#{num} is exempted but no longer in the code"


def test_an_exempted_number_is_not_also_documented():
    """If it earned an entry after all, the exemption is stale and should go."""
    doc = _doc()
    stale = [n for n in NO_DOC_ENTRY if re.search(rf"#{n}\b", doc)]
    assert not stale, f"exempted but now documented — drop the exemption: {stale}"


# --- the three that motivated it are connected now ------------------------------------------------

@pytest.mark.parametrize("num", [714, 695, 697])
def test_the_motivating_gaps_are_closed(num):
    assert re.search(rf"#{num}\b", _doc()), f"#{num} lost its cross-reference again"


def test_714_points_at_the_code_from_the_write_up():
    doc = _doc()
    i = doc.index("describe a screen the gate never photographed")
    assert "#714" in doc[i:i + 2000], "the fix must be reachable from the finding"


# --- provenance -------------------------------------------------------------------------------------

def test_the_misleading_headline_is_recorded():
    """'12 of 28' was the alarming version of a number that narrowed to zero."""
    d = __doc__ or ""
    assert "12 of 28" in d
    assert "ZERO findings that emit a runtime warning without a checker signature" in d


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
