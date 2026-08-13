r"""#668: the impl-task denial said "BUILD the real page/component" and knew exactly which one.

`workhub_task complete` refuses an `impl.*` task whose artifact is not yet `implemented`, and
the refusal is well-argued: these auto-complete when the code-truth audit confirms the artifact
is real, so completing one by hand is a false-complete that wedges the run. What it never said
is what the audit is looking FOR.

Measured over the 249 run logs:

    2576 denials across 80 runs, median 20 per run, 456 in the worst
    the SAME task refused up to 146 times — impl.component.title_detail_modal x146,
    impl.component.hero_billboard x120, impl.page.browse_home x120

A lane retrying one task 146 times against a correct message is a lane that believes it has
finished and cannot see what the audit disagrees about. The answer was already in hand: the
denial fetches the registry record to read `status`, and that record carries the criteria —

    ui_page      path, component, route, apis_used, components (required children)
    ui_component component, apis_used
    table        schema.columns

Additive and best-effort: "" when the record says nothing, so the message is never worse. Same
shape as #663 and #661 — the framework held the specific fact and emitted the generic sentence.
"""
import pytest

from env_generator.llm_generator.tools.hub_tools import (
    _impl_artifact_expectation_668 as expectation,
)

_PAGE = {"route": "/", "component": "LandingPage",
         "path": "app/frontend/src/pages/LandingPage.jsx",
         "apis_used": "[]", "components": "['landing_hero_collage', 'site_footer']"}
_COMP = {"component": "TopNavBar", "apis_used": "['GET /api/profiles']"}
_TABLE = {"schema": {"columns": [{"name": "id"}, {"name": "user_id"}]}}


# --- each artifact kind names its own criteria ---------------------------------------------------

def test_a_page_names_its_file_component_and_route():
    out = expectation(_PAGE)
    assert "app/frontend/src/pages/LandingPage.jsx" in out
    assert "`LandingPage`" in out
    assert "route `/`" in out


def test_a_page_names_the_children_the_audit_requires():
    out = expectation(_PAGE)
    assert "landing_hero_collage" in out and "site_footer" in out


def test_a_component_names_itself_and_the_apis_it_must_call():
    out = expectation(_COMP)
    assert "`TopNavBar`" in out
    assert "GET /api/profiles" in out


def test_a_table_names_its_columns():
    out = expectation(_TABLE)
    assert "`id`" in out and "`user_id`" in out


def test_it_says_where_the_criteria_came_from():
    """The lane must know this is the registry's own record, not the tool's opinion."""
    assert "from the registry record" in expectation(_COMP)


def test_it_tells_the_lane_that_retrying_cannot_help():
    """The behaviour the 146 retries need corrected."""
    out = expectation(_COMP)
    assert "retrying the completion cannot change the artifact's status" in out


# --- the list forms are parsed, not dumped --------------------------------------------------------

def test_a_stringified_list_is_unpacked():
    """The store round-trips these as repr strings, not JSON arrays."""
    out = expectation({"component": "X", "apis_used": "['GET /a', 'POST /b']"})
    assert "`GET /a`" in out and "`POST /b`" in out
    assert "[" not in out.split("calling")[1][:40]


def test_a_real_list_works_too():
    assert "`GET /a`" in expectation({"component": "X", "apis_used": ["GET /a"]})


def test_an_empty_list_contributes_nothing():
    out = expectation({"component": "X", "apis_used": "[]"})
    assert "calling" not in out


def test_long_lists_are_capped():
    out = expectation({"component": "X", "components": [f"c{i}" for i in range(20)]})
    assert "c5" in out and "c19" not in out


# --- it must never make the denial worse ---------------------------------------------------------

@pytest.mark.parametrize("rec", [None, {}, "not a dict", 42, [], {"status": "defined"}])
def test_a_record_with_nothing_useful_adds_nothing(rec):
    assert expectation(rec) == ""


def test_malformed_fields_do_not_raise():
    for rec in ({"schema": "not a dict"}, {"schema": {"columns": "x"}},
                {"apis_used": {"a": 1}}, {"components": 5}, {"path": None}):
        expectation(rec)


def test_an_unparseable_list_string_is_not_dropped_silently():
    out = expectation({"component": "X", "apis_used": "[broken"})
    assert "X" in out


def test_it_is_deterministic():
    assert expectation(_PAGE) == expectation(_PAGE)


# --- wiring -------------------------------------------------------------------------------

def _denial_block():
    """The denial's return statement, bounded by the call that follows it — not a fixed width."""
    import inspect
    from env_generator.llm_generator.tools import hub_tools as ht
    src = inspect.getsource(ht)
    i = src.index("complete denied: impl task")
    return src[i:src.index("self._hubs.workhub.complete_task(", i)]


def test_the_denial_appends_it():
    assert "_impl_artifact_expectation_668(_blocked_rec)" in _denial_block()


def test_the_record_is_captured_where_the_status_is_read():
    import inspect
    from env_generator.llm_generator.tools import hub_tools as ht
    src = inspect.getsource(ht)
    i = src.index("_blocked_status = _s")
    assert "_blocked_rec = _rec" in src[i:src.index("except Exception:", i)]


def test_the_original_argument_is_still_made():
    """#668 adds specifics; it must not weaken the do-not-complete-manually reasoning."""
    tail = _denial_block()
    assert "AUTO-COMPLETED by the framework" in tail
    assert "false-complete that wedges" in tail


def test_the_measurement_is_recorded():
    import inspect
    from env_generator.llm_generator.tools import hub_tools as ht
    flat = " ".join(inspect.getsource(ht._impl_artifact_expectation_668).replace("#", " ").split())
    assert "2576 denials across 80 runs" in flat
    assert "146 times" in flat


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
