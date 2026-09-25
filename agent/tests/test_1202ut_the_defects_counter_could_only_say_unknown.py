r"""#1202ut: a counter I added one session ago could only ever report "unknown".

#1202uh gave the squad's delivery-hold records their own counters, because #1202tk's ledger
named the squad in 12 of r133's 13 post-gate holds and every one of them carried an EMPTY
detail. Two of the three work. The third read

    len(getattr(orch, "_tu_squad_open_p0", None) or ()) or "?"

and `_tu_squad_open_p0` appears EXACTLY ONCE in the whole package -- at that read. Nothing
assigns it, anywhere. So `defects=` was structurally unable to be anything but "?", which is
what every record in the corpus says: 8 of 8 hold lines across r132-r135, including the ones
written after a verdict already existed.

Found by auditing my own fix rather than by a failure, and it is the mechanism-built-never-wired
class the project has hit before. A sweep for the same shape -- attributes read through
`getattr(self|orch, ...)` that nothing ever assigns -- turned up 22 candidates, of which 17
survived filtering out methods and class fields, and of those exactly ONE was a real defect:
this one. The rest are either `getattr(self, "_flag", True)` per-instance opt-outs (a feature
on by default) or #1178's already-documented fallback in the remediation dispatcher, whose
primary path calls the METHOD and works.

`?` BEFORE A VERDICT IS CORRECT and is kept: at `squad_launched_background` there genuinely is
no count yet. The defect is `?` afterwards, when the orchestrator has computed `_p0` three
lines from the hold that reports it.

LOCAL-ONLY (gitignored)."""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for p in (str(ROOT), str(LLM_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

from multi_agent.orchestrator import (  # noqa: E402
    _squad_detail_1202uh,
    _squad_p0_1202ut,
)


class _Orch:
    pass


def test_the_count_reaches_the_ledger_once_a_verdict_exists():
    """★ The defect: 8 of 8 corpus records read `defects=?`, verdict or not."""
    o = _Orch()
    o._tu_squad_last_p0_1202ut = 19
    assert "defects=19" in _squad_detail_1202uh(o)
    o._tu_squad_last_p0_1202ut = 0
    assert "defects=0" in _squad_detail_1202uh(o)


def test_zero_defects_is_reported_as_zero_not_as_unknown():
    """★ The half that the old `or "?"` got wrong even if the attribute HAD been set: a squad
    that ran and found nothing is a fact, and #1202tn's rule cuts the other way here -- the
    ledger must not spell a real zero as 'unknown'."""
    o = _Orch()
    o._tu_squad_last_p0_1202ut = 0
    assert _squad_p0_1202ut(o) == 0
    assert "defects=?" not in _squad_detail_1202uh(o)


def test_before_any_verdict_it_still_says_unknown():
    """At `squad_launched_background` there is genuinely no count yet. Reporting 0 there would
    be the inverse defect -- claiming a clean squad before one ran."""
    assert _squad_p0_1202ut(_Orch()) == "?"
    assert "defects=?" in _squad_detail_1202uh(_Orch())


def test_the_orchestrator_records_it_where_the_number_exists():
    """★ #947/reachability: the read is only alive if something writes. The assignment must sit
    with the `_p0` computation, which is the one place the count exists."""
    src = (LLM_DIR / "multi_agent" / "orchestrator.py").read_text(encoding="utf-8")
    m = re.search(r'_p0 = int\(\(_tu_result\.get\("bugs"\) or \{\}\)\.get\("p0", 0\)\)'
                  r'(?P<after>(?:.|\n){0,400})', src)
    assert m, "the _p0 computation moved; this assertion no longer reads what it names"
    assert "_tu_squad_last_p0_1202ut = _p0" in m.group("after"), m.group("after")[:300]


def test_the_dead_attribute_is_gone():
    """The old name must not survive as a second, still-dead reader."""
    src = (LLM_DIR / "multi_agent" / "orchestrator.py").read_text(encoding="utf-8")
    code = "\n".join(l for l in src.splitlines() if not l.strip().startswith("#"))
    assert "_tu_squad_open_p0" not in code, "the dead read is still in live code"


def test_it_never_raises():
    """An advisory line may never be the reason a delivery fails -- #1202uh's own rule."""

    class _Hostile:
        @property
        def _tu_squad_last_p0_1202ut(self):
            raise RuntimeError("boom")

    assert _squad_p0_1202ut(_Hostile()) == "?"
    assert isinstance(_squad_detail_1202uh(_Hostile()), str)


def test_every_attribute_this_helper_reads_is_one_something_writes():
    r"""★ THE RATCHET, scoped to where the defect actually was.

    A blanket "no getattr without an assignment" rule would be noise: the sweep that found
    this turned up 17 such reads and most are deliberate -- `getattr(self, "_flag", True)` is
    a per-instance opt-out for a feature that is on by default, and #1178's dispatcher
    fallback is documented dead-on-purpose behind a working primary path.

    What is NOT deliberate is an advisory line reporting a number nobody stores. So the rule
    is scoped to this helper: every orchestrator attribute it reads must be assigned somewhere
    in the orchestrator. That is exactly the check that would have failed a session ago, when
    `_tu_squad_open_p0` was read here and written nowhere -- and it would have failed even
    though the unit test was green, because the test fed a stand-in object carrying an
    attribute the real orchestrator never has.
    """
    import inspect

    src = (LLM_DIR / "multi_agent" / "orchestrator.py").read_text(encoding="utf-8")
    helpers = inspect.getsource(_squad_detail_1202uh) + inspect.getsource(_squad_p0_1202ut)
    names = set(re.findall(r'getattr\(\s*orch\s*,\s*["\'](_[a-z0-9_]+)["\']', helpers))
    assert names, "the helper stopped reading orchestrator state; this assertion is now blind"
    for name in sorted(names):
        assert re.search(r'self\.' + re.escape(name) + r'\s*=', src), (
            f"{name!r} is read by the squad hold detail and assigned nowhere in the "
            f"orchestrator -- it can only ever report '?'")
