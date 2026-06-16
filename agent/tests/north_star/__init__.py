# North-star oracle suite — package marker.
#
# This package is the independent functional oracle that drives the
# north-star metric (docs/north_star_oracle_build_plan.md §9). It is
# NOT part of the agent test suite — agents must NEVER read it (it
# is the calibration anchor for measuring whether THEY are producing
# functionally-correct apps).
#
# Per A2 (collection isolation) — the sibling conftest.py instructs
# pytest to collect_ignore this whole directory by default. The oracle
# is invoked explicitly via tests/north_star/runner.py when the
# north-star measurement is being taken, not as part of `pytest tests/`.
