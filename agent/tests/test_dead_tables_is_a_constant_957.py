r"""#957 → #1023b → #1199: the dead-table scan is gone.

★ FINAL DISPOSITION (#1199): DELETED. #957's and #1023b's reasoning is kept below as written
(item 48) — it is why the mechanism existed and why removing it is safe.

#957: `scan_dead_tables` called a table dead when `get_table_consumers(name)` was empty.
Corpus-wide, `registryhub_table_consumers.json` holds **0 records in every run**, while
`registryhub_consumers.json` holds 1145 — every one keyed by `endpoint_id`, none by table. So
the scan returned EVERY table, every run: r154's twelve were all reported dead while its
database served 60 titles, 57 title_genres, 16 episodes and five more populated tables. The
count fed a delivery blocker ("N dead artifact(s)"), so it was not inert — it inflated every
pre-validation tick by the whole table count and said nothing about any table.

#1023b: an empty index is not a fact. When NOT ONE table has a registered consumer the index
is unpopulated rather than telling us every table is unused, so the scan reported none instead
of all — suppressing a 100%-false-positive verdict can only remove false blockers, and #566j's
false blocker cost r117/r120 a 75-minute no-deliver abort.

#1199: that left a scan which could only ever return [], plus 650 warnings per run saying so,
and a registration tool offered to every lane that no agent has ever called — re-sent in every
request that carries the bundle. Measured before removing: r26's DELIVERED app has 13 tables
and no dead ones (every table referenced 5+ times), so a repaired detector would have found
nothing there either.

What is deliberately NOT removed: `CoverageReport.dead_tables`, which stays as a permanently
empty list. Deliverability reads it for `dead_count_by_kind`, and it has received [] in every
run since #1023b, so the arithmetic and the report schema are unchanged. RegistryHub keeps
`register_table_consumer`/`get_table_consumers` as well — inert storage whose removal is what
would ripple through a dozen unrelated tests.
"""

import sys
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS_DIR.parent / "env_generator" / "llm_generator"))

import multi_agent.runtime.coverage_audit as ca  # noqa: E402
from multi_agent.runtime.coverage_audit import compute_coverage  # noqa: E402


def test_the_scan_is_gone():
    assert not hasattr(ca, "scan_dead_tables")
    assert "scan_dead_tables" not in getattr(ca, "__all__", ())


def test_dead_tables_stays_on_the_report_as_an_empty_list(tmp_path):
    """The term deliverability counts must keep existing, and keep reading []."""
    from multi_agent.runtime.hub_registry import HubRegistry
    reg = HubRegistry(tmp_path)
    reg.schema_hub.register_table("notifications", schema={"columns": []},
                                  provider="backend", agent="backend")
    report = compute_coverage(reg, tmp_path)
    assert report.dead_tables == []
    assert isinstance(report.dead_tables, list)


def test_the_registration_tool_is_off_the_lane_bundles():
    """A tool nobody should call is still re-sent in every request that offers it."""
    src = Path(__file__).resolve().parents[1] / (
        "env_generator/llm_generator/multi_agent/tool_bundles.py")
    assert "registryhub_register_table_consumer" not in src.read_text(encoding="utf-8")
