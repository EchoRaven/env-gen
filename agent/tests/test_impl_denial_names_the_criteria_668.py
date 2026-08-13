r"""#668: the impl-task denial said "BUILD the real page/component" and knew exactly which one.

`workhub_task complete` refuses an `impl.*` task while its artifact is not `implemented`, and
the refusal is well argued — it explains the auto-complete rule and warns that a manual complete
is a false-complete that wedges the run. What it never said is what the audit is checking.

It had the answer in hand. The same record it fetched to read `status` carries the criteria:

    ui_page      path, component, route, apis_used, required child components
    ui_component component, apis_used
    table        schema columns

Measured over the 249 run logs:

    2576 denials across 80 runs, median 20 per run, 456 in the worst
    the SAME task refused up to 146 times — impl.component.title_detail_modal x146,
    impl.component.hero_billboard x120, impl.page.browse_home x120

A lane retrying one task 146 times against a correct message is a lane that believes it is
finished and cannot see what the audit disagrees about. Naming the file, component, route and
APIs turns "build it" into something checkable.

Third instance of one pattern this session, after #661 (the empty-state task asserted a cause
the framework could check) and #663 (the denial probe discarded the evidence that classified
it): the framework holds the specific fact and emits the generic sentence.
"""
import pytest

from env_generator.llm_generator.tools.hub_tools import (
    _impl_artifact_expectation_668 as expectation,
)

_PAGE = {"route": "/", "component": "LandingPage",
         "path": "app/frontend/src/pages/LandingPage.jsx",
         "apis_used": "[]", "components": "['landing_hero_collage', 'site_footer']"}
_COMPONENT = {"component": "TopNavBar", "apis_used": "['GET /api/profiles']"}
_TABLE = {"schema": {"columns": [{"name": "id"}, {"name": "user_id"}]}}


# --- each artifact kind gets its own criteria -----------------------------------------------

def test_a_page_names_its_file_component_and_route():
    out = expectation(_PAGE)
    assert "app/frontend/src/pages/LandingPage.jsx" in out
    assert "`LandingPage`" in out
    assert "route `/`" in out


def test_a_page_names_the_child_components_it_must_contain():
    out = expectation(_PAGE)
    assert "landing_hero_collage" in out and "site_footer" in out


def test_a_component_names_the_apis_it_must_call():
    out = expectation(_COMPONENT)
    assert "`TopNavBar`" in out
    assert "GET /api/profiles" in out


def test_a_table_names_its_columns():
    out = expectation(_TABLE)
    assert "`id`" in out and "`user_id`" in out


def test_it_tells_the_lane_retrying_cannot_help():
    """The loop is the defect; the message has to say the retry is futile."""
    out = expectation(_COMPONENT)
    assert "retrying the completion cannot change the artifact's status" in out


# --- it must never make the refusal worse ---------------------------------------------------

@pytest.mark.parametrize("rec", [None, {}, "not a dict", 42, [],
                                 {"status": "defined"},          # nothing actionable
                                 {"path": "", "component": "  "}])
def test_it_stays_silent_when_the_record_says_nothing(rec):
    assert expectation(rec) == ""


def test_a_malformed_apis_field_does_not_crash():
    assert expectation({"component": "X", "apis_used": "not-a-list"}) != ""
    assert expectation({"component": "X", "apis_used": {"a": 1}}) != ""
    assert expectation({"component": "X", "apis_used": None}) != ""


def test_a_malformed_schema_does_not_crash():
    for bad in ("[]", None, {"columns": "x"}, {"columns": [1, 2]}):
        expectation({"schema": bad})


def test_a_real_list_works_as_well_as_a_repr_string():
    """Stores round-trip these through str(); both shapes must read."""
    a = expectation({"component": "X", "apis_used": ["GET /a", "POST /b"]})
    b = expectation({"component": "X", "apis_used": "['GET /a', 'POST /b']"})
    assert "GET /a" in a and "GET /a" in b


def test_long_lists_are_capped():
    out = expectation({"component": "X",
                       "apis_used": [f"GET /api/{i}" for i in range(20)]})
    assert out.count("GET /api/") <= 6


def test_it_is_deterministic_and_pure():
    rec = dict(_PAGE)
    before = dict(rec)
    assert expectation(rec) == expectation(rec)
    assert rec == before


# --- wiring -------------------------------------------------------------------------------

def test_the_denial_appends_it():
    import inspect
    from env_generator.llm_generator.tools import hub_tools as ht
    src = inspect.getsource(ht)
    i = src.index("complete denied: impl task")
    tail = src[i:src.index("hub_result = self._hubs.workhub.complete_task", i)]
    assert "_impl_artifact_expectation_668(_blocked_rec)" in tail


def test_the_record_is_captured_where_the_status_is_read():
    import inspect
    from env_generator.llm_generator.tools import hub_tools as ht
    src = inspect.getsource(ht)
    i = src.index("_blocked_status = _s")
    assert "_blocked_rec = _rec" in src[i:src.index("except Exception:", i)]


def test_the_original_reasoning_is_still_there():
    """The auto-complete explanation and the false-complete warning must survive."""
    import inspect
    from env_generator.llm_generator.tools import hub_tools as ht
    src = inspect.getsource(ht)
    i = src.index("complete denied: impl task")
    tail = src[i:src.index("hub_result = self._hubs.workhub.complete_task", i)]
    assert "AUTO-COMPLETED by the framework" in tail
    assert "false-complete that wedges the" in tail


def test_the_measurement_is_recorded():
    import inspect
    from env_generator.llm_generator.tools import hub_tools as ht
    flat = " ".join(inspect.getsource(ht._impl_artifact_expectation_668).replace("#", " ").split())
    assert "2576 denials across 80 runs" in flat
    assert "146 times" in flat


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
