r"""#661: the empty-state task asserted "add seed rows" without checking, and named no table.

`empty_state` was the last unmined field on the judge's screen record, and it is the single
strongest failure predictor in the corpus:

    99 empty-state screens across 48 runs, 19 of them blocking
    similarity min 0.03, median 0.35, max 0.60 — NOT ONE ever cleared the 0.65 bar
    worst screens: genre_category 18, my_list 17, browse_by_languages 12, games 10

The framework does act on it: one P1 backend task per milestone. But the task listed only SCREEN
names — leaving the lane to map screen -> table, which the framework already knows — and it
asserted the cause unconditionally: *"Add realistic seed rows (>=3) for each screen's backing
table(s)"*.

When the tables are in fact seeded, that advice is wrong and expensive. A page that renders
empty over a populated table is a read-path bug — the query's filters, owner-scoping (#566y /
#598), or route precedence — and sending the backend to add rows burns a round on the wrong
lane while the real defect sits untouched.

`audit_seed_data` is the checker that tells the two apart, it already exists, and it is
reachable from here (`orch.hubs.schema_hub` is the registryhub). The task now runs it and says
which case this is: name the under-seeded tables, or state plainly that seeding is NOT the
problem and point at the read path.

Best-effort by construction: if the audit raises, the original wording is used. A diagnosis that
fails must never cost the reminder.
"""
import inspect
import re

import pytest

from env_generator.llm_generator.multi_agent.runtime import visual_fidelity as vf


def _block():
    """The reminder body, bounded by the construct that follows it — no fixed-width window."""
    src = inspect.getsource(vf)
    i = src.index("#661: NAME THE TABLES")
    return src[i:src.index("msg_type=\"task_ready\"", i)]


# --- the three branches exist ------------------------------------------------------------------

def test_it_runs_the_existing_seed_audit():
    body = _block()
    assert "from .seed_audit import audit_seed_data" in body
    assert "_asd(orch.hubs)" in body


def test_the_under_seeded_branch_names_the_tables():
    body = _block()
    assert 'flags these registered tables as under-seeded' in body
    assert '", ".join(_thin)' in body


def test_the_seeded_branch_says_it_is_NOT_a_seeding_problem():
    """The branch that matters — it redirects the lane off the wrong track."""
    body = _block()
    assert "probably NOT a seeding problem" in body
    assert "read-path bug" in body


def test_the_seeded_branch_names_the_real_suspects():
    """#634: naming the condition without naming where to look still costs a round."""
    body = _block()
    for suspect in ("filters", "owner-scoping", "precedence"):
        assert suspect in body, suspect


def test_the_seeded_branch_still_leaves_the_door_open():
    """It must not forbid seeding outright — only require confirming first."""
    body = _block()
    # the literal is split across source lines, so match the contiguous halves
    assert "Only add seed rows " in body
    assert "if you first confirm the backing table is genuinely empty." in body


# --- it must never cost the reminder --------------------------------------------------------

def test_the_audit_is_best_effort():
    body = _block()
    assert "except Exception:" in body
    assert body.index("try:") < body.index("_asd(orch.hubs)") < body.index("except Exception:")


def test_a_failed_audit_falls_back_to_the_original_wording():
    body = _block()
    assert "if not _seed_checked:" in body
    i = body.index("if not _seed_checked:")
    fallback = body[i:body.index("elif _thin:", i)]
    assert "Add realistic seed rows" in fallback


def test_the_flag_is_set_before_the_diagnosis_runs():
    """`_seed_reminder_sent` must latch even if the audit throws — else it retries every round."""
    body = _block()
    src = inspect.getsource(vf)
    j = src.index("self._seed_reminder_sent = True")
    assert j < src.index("#661: NAME THE TABLES")


# --- the diagnosis reaches both channels ---------------------------------------------------------

def test_the_task_description_uses_the_diagnosis():
    src = inspect.getsource(vf)
    i = src.index("Visual gate: screen(s) render an EMPTY state")
    assert '_diag' in src[i:src.index("assignee=", i)]


def test_the_urgent_message_uses_the_diagnosis_too():
    src = inspect.getsource(vf)
    i = src.index("Seed-data task assigned")
    assert '_diag' in src[i:src.index("msg_type=", i)]


def test_neither_channel_still_hardcodes_the_old_assertion():
    src = inspect.getsource(vf)
    i = src.index("Visual gate: screen(s) render an EMPTY state")
    tail = src[i:src.index("tags=[\"visual_fidelity\", \"seed_data\"]", i)]
    assert "Add seed rows for their backing" not in tail


# --- the screens are still named -----------------------------------------------------------------

def test_the_screen_list_is_still_reported():
    """The diagnosis is additive — losing the screen names would be a regression."""
    src = inspect.getsource(vf)
    i = src.index("Visual gate: screen(s) render an EMPTY state")
    tail = src[i:src.index("assignee=", i)]
    assert '", ".join(_empty)' in tail


def test_the_measurement_is_recorded():
    body = _block()
    flat = " ".join(body.replace("#", " ").split())
    assert "99 empty-state screens across 48 runs" in flat
    assert "median 0.35" in flat


def test_the_wrong_lane_cost_is_recorded():
    """The reason this is worth changing, not just the fact that it changed."""
    flat = " ".join(_block().split())
    assert "burns a round on the wrong lane" in flat


# --- the checker it leans on still has the shape assumed ------------------------------------------

def test_audit_seed_data_still_returns_flagged_tables_with_a_table_key():
    from env_generator.llm_generator.multi_agent.runtime.seed_audit import SeedReport
    r = SeedReport(flagged_tables=[{"table": "titles", "reason": "missing_seed"}])
    assert [t["table"] for t in r.flagged_tables] == ["titles"]


def test_the_hub_registry_still_exposes_schema_hub():
    """`audit_seed_data` reads `hub_registry.schema_hub`; the reminder passes `orch.hubs`."""
    src = inspect.getsource(vf).replace("#", " ")
    assert "orch.hubs.schema_hub" in src or "_asd(orch.hubs)" in src
    from env_generator.llm_generator.multi_agent.runtime import hub_registry as hr
    assert "self.schema_hub = self.registryhub" in inspect.getsource(hr)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
