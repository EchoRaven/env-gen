"""Pytest collection-isolation for the north-star oracle suite (A2).

The oracle is independent infrastructure for the north-star metric
(docs/north_star_oracle_build_plan.md §9). Oracle runner / per-spec
oracles (runner.py, simple_blog/, ...) are NOT part of the default
agent test suite — running `pytest tests/` from agent/ must NOT
collect them (per R2 round-5 A2: they'd ModuleNotFoundError on the
optional deps like playwright if not installed, breaking the frozen
0-failing baseline).

HOWEVER (R1 round-13 close): the §3 classifier + §2/B-8 ITT recompute
gate tests (test_classifier_acceptance.py, test_itt_recompute.py,
test_conventions_self.py) have no optional-dep footprint and MUST
run under `pytest tests/` so CI actually gates the 90/90 north-star
acceptance. The previous "ignore the whole subtree" approach made
CI silently skip them.

Resolution: whitelist the gate files in `_NORTH_STAR_GATE_WHITELIST`;
everything else under north_star/ remains collection-isolated and is
invoked explicitly by the north-star runner when measurement runs.

Operators wanting to run the FULL oracle suite (including spike
files and per-spec oracles) directly can still do:
  pytest tests/north_star/ --confcutdir=tests
"""

from pathlib import Path


_THIS_DIR = Path(__file__).resolve().parent

# Whitelist: north-star gate tests that MUST run under the default
# `pytest tests/` invocation so CI gates the 90/90 north-star
# acceptance instead of silently skipping the suite (R1 round-13:
# directory invocation was returning "no tests ran" because the
# previous collect_ignore swept the whole subtree). Future spike
# files (e.g. test_calibration.py) stay ignored by default and are
# invoked explicitly by the north-star runner when measurement is
# being taken.
_NORTH_STAR_GATE_WHITELIST = {
    "test_classifier_acceptance.py",  # §3 signature + §7 acceptance fixtures
    "test_itt_recompute.py",          # §2/B-8 ITT recompute apparatus
    "test_conventions_self.py",       # _conventions.py self-tests
}

# Tell pytest to skip-collect everything under this directory EXCEPT
# the gate whitelist above. Non-whitelisted files (runner.py,
# per-spec oracles like simple_blog/, future spike files like
# test_calibration.py) remain importable when explicitly referenced
# — only DEFAULT auto-collection via `pytest tests/` skips them.
collect_ignore = [
    str(p.relative_to(_THIS_DIR))
    for p in _THIS_DIR.rglob("*.py")
    if p.name not in {"__init__.py", "conftest.py"}
    and p.name not in _NORTH_STAR_GATE_WHITELIST
]
