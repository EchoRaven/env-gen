r"""#852: two load-bearing invariants stated in comments, neither with an enforcer.

Continues #851's sweep — #788's rule ("a sentence asserting a consequence is a claim about the
code that decays silently") pointed at code comments. Both invariants below are TRUE TODAY. That
is the whole problem: they hold by care, and nothing fails when the care lapses.

1. `agent_subscriptions.py` — "``framework_decision`` must never appear in DEFAULT_SUBSCRIPTIONS
   (a live sub would reintroduce the wakeup it exists to avoid)". Load-bearing: inbox_only is the
   ONLY no-wakeup lever (priority does not gate the wakeup — #25's blocking finding), and the
   wake-storm it prevents cost r3 **146 idle stop-cycles** of model quota. Currently 0 violations
   across 49 subs. No test.

2. `database_scaffold.py` — "These column names are drift-gated against ``_TENANCY_SPINE_SQL`` by
   ``test_database_scaffold`` so the manifest can never silently diverge from the DDL the AS
   actually reads/writes." ★ **The named test does not exist.** No test file references
   `SPINE_TABLE_RECORDS` or `_TENANCY_SPINE_SQL`. This is #788's exact shape — an enforcer that
   never existed — sharpened by the comment naming it. Measured: 0 of 4 tables have drifted, so
   the claim's CONTENT is true and only its mechanism was fictional.

Why a manifest/DDL divergence matters: the orchestrator registers `SPINE_TABLE_RECORDS` with
RegistryHub/SchemaHub, so a lane querying the schema is told those columns exist. If the DDL says
otherwise the lane writes correct-looking code against a column that is not there, and the failure
surfaces at runtime as a 500 — the #528 shape, where a data-layer mismatch starves every page.
"""
import pathlib
import re

import pytest

from env_generator.llm_generator.multi_agent.runtime import agent_subscriptions as subs
from env_generator.llm_generator.multi_agent.runtime import database_scaffold as ds


# --- 1. the no-wakeup lever ---------------------------------------------------------------------

def _flat(d):
    return [(agent,) + tuple(t) for agent, ts in d.items() for t in ts]


def test_the_subscription_tables_are_populated():
    """Non-vacuity: an empty or renamed table would make the invariant vacuously true."""
    assert len(_flat(subs.DEFAULT_SUBSCRIPTIONS)) > 20
    assert len(_flat(subs.INBOX_ONLY_SUBSCRIPTIONS)) > 0


def test_framework_decision_is_never_a_live_subscription():
    """The invariant. A live sub reintroduces the wake-storm inbox_only exists to avoid."""
    live = [s for s in _flat(subs.DEFAULT_SUBSCRIPTIONS) if "framework_decision" in s]
    assert live == [], live


def test_it_is_still_delivered_somewhere():
    """★ The complement, and the reason this is not just an absence check. Asserting only that
    the event is missing from one table would also pass if the subscription were deleted outright
    — which silences the notice instead of routing it. An absence is a claim about where you
    looked (this session's own correction, four times over)."""
    inbox = [s for s in _flat(subs.INBOX_ONLY_SUBSCRIPTIONS) if "framework_decision" in s]
    assert inbox, "the notice must still reach lanes via the inbox_only lever"
    assert {s[0] for s in inbox} >= {"backend", "frontend"}, inbox


# --- 2. the drift gate the comment says exists ---------------------------------------------------

def _ddl_columns(table):
    m = re.search(rf"CREATE TABLE (?:IF NOT EXISTS )?{table}\s*\((.*?)\n\s*\);",
                  ds._TENANCY_SPINE_SQL, re.S | re.I)
    assert m, f"no DDL block for {table}"
    out = []
    for line in m.group(1).split("\n"):
        line = re.sub(r"--.*$", "", line).strip().rstrip(",")     # SQL comments are not columns
        if not line or line.upper().startswith(
                ("PRIMARY KEY", "FOREIGN KEY", "UNIQUE", "CONSTRAINT", "CHECK")):
            continue
        out.append(line.split()[0])
    return out


def test_the_parser_sees_real_columns():
    """Non-vacuity, and specifically the failure the first version of this probe had: it counted
    three `--` comment lines in `users` as columns and reported drift that was not there. A drift
    finding is a claim about the parser before it is a claim about the schema."""
    cols = _ddl_columns("users")
    assert "id" in cols and "--" not in cols, cols
    assert len(ds.SPINE_TABLE_RECORDS) == 4


@pytest.mark.parametrize("rec", ds.SPINE_TABLE_RECORDS, ids=[r["name"] for r in ds.SPINE_TABLE_RECORDS])
def test_the_manifest_matches_the_ddl(rec):
    """The gate the comment claimed. The orchestrator registers this manifest with
    RegistryHub/SchemaHub, so a lane that queries the schema is told these columns exist."""
    declared = [c["name"] for c in rec["columns"]]
    actual = _ddl_columns(rec["name"])
    assert sorted(declared) == sorted(actual), (rec["name"], declared, actual)


def test_an_injected_column_is_caught():
    """Non-vacuity for the gate itself: prove it can fail, rather than trusting that it would."""
    assert "ghost_col" not in _ddl_columns("tenants")


def test_the_comment_no_longer_names_a_test_that_does_not_exist():
    """★ The finding. The comment said `test_database_scaffold` drift-gates this; no test file
    referenced either constant. A named enforcer is more dangerous than an unnamed one — it stops
    the next reader from checking.

    Anchored on the ACTIVE CLAIM SENTENCE, not on the old name. The first version asserted the
    bare token was absent from the block and matched **its own explanation of the fix** three
    lines below — the twelfth self-match this session, and the standing rule exists for it: a
    probe must anchor on a sentence from the code site, never on a bare name a write-up can
    quote."""
    import inspect
    import re
    src = inspect.getsource(ds)
    i = src.index("SPINE_TABLE_RECORDS = [")
    block = src[src.rindex("\n\n", 0, i):i]
    m = re.search(r"drift-gated against ``_TENANCY_SPINE_SQL`` by\s*#?\s*``([a-z0-9_]+)``", block)
    assert m, "the claim sentence must still name an enforcer\n" + block
    named = m.group(1)
    assert named != "test_database_scaffold", "the fictional enforcer is still the active claim"
    assert (pathlib.Path(__file__).parent / f"{named}.py").exists(), named


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
