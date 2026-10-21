"""#1203rd -- a criterion must defer to the framework saying its precondition did not hold.

`verify_1015.py`'s `kz` check asks whether delivered design-system components carry verbatim
`copy`. netflix-local-r46 came back FALSIFIED -- 0 of 530 -- and the run log already explained
why, in the framework's own words:

    ...has nothing measured behind it (#1203kz). THIS RUN NEVER ASKED: the design system was
    ADOPTED from 'netflix-local-r41' and the design_analyst was not spawned (#1202hj)

#1202hj's adoption reuses a donor run's `design_system.json` and skips the analyst, so no
pass ever authored copy. The claim was never exercised, which is N-A by this script's own
definition -- not a failed prediction. A false FALSIFIED is worse than a false N-A: it sends a
reader after a defect that is not there, which is what it did to me until I read the log line
sitting next to it.

THE THIRD INSTANCE OF ONE SHAPE IN ONE SESSION: #1203ov's criterion read a key no artifact
ever holds, `verify_shipped_fixes` told the reader to consult a log it already had, and this
one ignored an announcement written for exactly its question. In every case the fix is to read
the observable the framework actually emits.

The check is inline in a 795-line `main()`, so it is driven through `main()` with `say`
captured -- not by re-implementing the branch, which would be a copy of the rule.
"""
import importlib.util
import json
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "verify_1015.py"

ADOPTED_LINE = ("the design system was ADOPTED from 'netflix-local-r41' and the "
                "design_analyst was not spawned (#1202hj)\n")


def _kz(adopted_line=None, with_copy=False, n=5):
    """Run the real `main()` on a synthetic run and return its `kz` verdict."""
    spec = importlib.util.spec_from_file_location("v1015_1203rd", SCRIPT)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)

    d = Path(tempfile.mkdtemp())
    (d / "design").mkdir(parents=True)
    comp = {"name": "c%d"}
    comps = [{"name": "c%d" % i, **({"copy": "Get Started"} if with_copy else {})}
             for i in range(n)]
    (d / "design" / "design_system.json").write_text(
        json.dumps({"screens": [{"components": comps}]}), encoding="utf-8")
    lg = d / "run.log"
    lg.write_text(adopted_line or "nothing of interest\n", encoding="utf-8")

    got = []
    m.say = lambda t, v, det="": got.append((t, v, det))
    try:
        m.main(["verify_1015.py", str(d), "--log", str(lg)])
    except SystemExit:
        pass
    except Exception:
        # `main()` ends in a summary that the captured `say` does not feed; the kz verdict
        # is recorded before that point, which is all this test reads.
        pass
    return next(((v, det) for t, v, det in got if t == "kz"), (None, ""))


def test_an_adopting_run_is_not_a_failed_prediction():
    """★ r46's case. The framework said the precondition did not hold; the verdict must agree."""
    verdict, detail = _kz(adopted_line=ADOPTED_LINE)
    assert verdict == "N-A", (verdict, detail)
    assert "ADOPTED" in detail
    assert "netflix-local-r41" in detail, "say WHICH donor -- the log names it"
    assert "1202hj" in detail, "name the mechanism so the reader can look it up"


def test_without_the_announcement_the_verdict_is_unchanged():
    """THE COUNTER-PROOF. Adoption is common from r178 onward but the announcement is recent,
    so a run that does not SAY it keeps its old verdict -- the criterion must never infer
    adoption it cannot read."""
    verdict, _detail = _kz(adopted_line=None)
    assert verdict == "FALSIFIED"


def test_copy_present_still_confirms_even_on_an_adopting_run():
    """The N-A arm must be reached only when there is nothing to show. A run that adopted AND
    carries copy is a working claim, not an unexercised one."""
    verdict, _detail = _kz(adopted_line=ADOPTED_LINE, with_copy=True)
    assert verdict == "CONFIRMED"


def test_copy_present_confirms_without_the_announcement():
    verdict, _detail = _kz(adopted_line=None, with_copy=True)
    assert verdict == "CONFIRMED"
