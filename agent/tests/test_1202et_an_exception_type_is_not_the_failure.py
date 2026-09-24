r"""#1202et: two failures reported by exception type with the message thrown away.

Found by searching for siblings of the pattern this whole batch is about — the framework
holds the actionable fact and reports its category. The detector's first version flagged 51
sites and every one was a false positive: `f"{type(exc).__name__}: {exc}"` carries both, and
my exclusion regex missed the closing brace. Corrected, and checked against a known-good
site first, it found four, of which two are real:

    delivery_gate.py   `logger.warning("#1017 could not name the failed UI records: %s",
                        type(_e).__name__)`

        A block whose entire job is to NAME the failed records, reporting that naming
        failed and not which name it choked on.

    container_runtime.py  `f"{rt} compose version failed ({type(exc).__name__}) — assuming v2"`

        This decides the compose provider and then assumes v2. "TimeoutExpired" alone
        cannot separate a slow host from a missing binary from a permission error.

The other two are correct as they stand: runhub branches ON the type (classification, not
reporting), and framework_validation's comment says it deliberately names the type rather
than defaulting to a value that would read as real.
"""
from pathlib import Path

import pytest

THIS_DIR = Path(__file__).resolve().parent
RT = THIS_DIR.parent / "env_generator" / "llm_generator" / "multi_agent" / "runtime"
DG = (RT / "delivery_gate.py").read_text(encoding="utf-8")
CR = (RT / "container_runtime.py").read_text(encoding="utf-8")


def test_the_naming_failure_names_what_it_choked_on():
    i = DG.index("#1017 could not name the failed UI records")
    seg = DG[i:DG.index("failed_checks.append", i)]
    assert "type(_e).__name__, _e" in seg, "the message is still discarded"


def test_the_compose_probe_reports_why_it_failed():
    i = CR.index("compose version failed")
    seg = CR[CR.rindex("except Exception", 0, i):CR.index("low = text.lower()", i)]
    assert "{exc}" in seg, "only the exception type reaches the caller"
    assert "assuming v2" in seg, "the fallback itself must not change"


def test_the_compose_probe_still_resolves_the_binary():
    """#936b: this file must not hardcode a container binary."""
    i = CR.index("compose version failed")
    seg = CR[CR.rindex("except Exception", 0, i):i]
    assert '"docker"' not in seg


def test_neither_site_swallows_the_type():
    """Type AND message — the type is what makes a log greppable."""
    assert "type(_e).__name__" in DG
    assert "type(exc).__name__" in CR
