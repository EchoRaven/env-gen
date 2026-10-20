"""#1203pi: a test whose every assertion lives inside a loop over a SEARCH result.

The shape:

```python
def test_nothing_in_here_does_x():
    for node in ast.walk(fn):           # or re.finditer(pattern, src), or path.rglob(...)
        assert not <violation>(node)
```

With zero hits the loop body never runs and the test passes having asserted nothing. For a
NEGATIVE property that is often the honest answer -- nothing matched, so nothing violates. The
danger is the other one: when the thing being searched moves, is renamed, or changes shape, the
search quietly finds nothing and the test stops guarding while staying green. It is the same
failure as a mutation spec whose `find` anchor dies
(`feedback_a_later_patch_can_destroy_an_earlier_mutations_anchor`), one level up.

MEASURED, and the measurement is why the baseline is allowed rather than fixed: every entry
below EXECUTES its assertion today. A line tracer ran each one and recorded the assert line in
all of them -- **zero are vacuous now**. So this is a latent risk, not a present defect, and the
cheap protection is to stop NEW ones arriving rather than to churn the files over a hazard none
of them currently has.

The baseline grew once, from 34 to 47, and not because anything regressed: the first version of
this scan counted only `ast.Assert`, so every `unittest.TestCase` test was invisible to it --
637 of the repo's 2363 test files. Fixing that surfaced 14 more instances of this shape, one of
them in the file that introduced the ranking this ratchet came out of (now fixed rather than
baselined). #1203ow's lesson, again: filter by ROLE, not by spelling.

A harness note worth keeping, because it nearly produced a false finding. Re-tracing the 14 by
importing their modules directly reported FOUR as vacuous. They were not: imported without the
suite's conftest the tests FAIL, so no assertion line runs, and "failed" looks exactly like
"asserted nothing". Run under pytest with the real node id -- `file.py::Class::method` for a
`unittest` method, which is also what made a first attempt report "no tests ran" -- all of them
execute their assertion. Several use `subTest`, which is a legitimate way to write this shape.

The scan narrowed three times, and each step removed a family of false positives, which is the
reusable part: 682 tests have every assertion inside SOME loop; 179 of those iterate something
COMPUTED rather than a literal tuple; 34 of those iterate a SEARCH over source or the tree, which
is the only form that can silently return nothing. A ratchet built on the first number would have
been noise.

To clear an entry rather than carry it: add one assertion that the search found its target, e.g.
`assert nodes, "re-aim this test"`, which turns a silent pass into a loud failure.
"""

import ast
import os
import re
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(os.path.dirname(_HERE))
_TEST_DIRS = (os.path.join(_ROOT, "agent", "tests"), os.path.join(_ROOT, "tests"))

# A loop whose iterable SEARCHES source or the tree, so "no hits" is reachable.
_SEARCH = re.compile(r"finditer|findall|ast\.walk|\.glob\(|\.rglob\(|\.iterdir\(|re\.search")

# (file, test) pairs that carry the shape today. Every one was traced and DOES execute its
# assertion -- see the module docstring. Shrink this list, never grow it.
_BASELINE = frozenset([
    ("test_1141_tool_batching_is_a_hyperparameter.py",
     "test_every_use_carries_a_fallback"),
    ("test_1180_own_cap_is_not_blamed_on_the_provider.py",
     "test_no_message_claims_both_things"),
    ("test_1192_ticker_reports_the_real_tick_count.py",
     "test_no_budget_write_hardcodes_a_zero_tick_count"),
    ("test_1202kh_no_api_route_could_ever_be_public.py",
     "test_the_projector_applies_the_same_read_only_filter"),
    ("test_1202ko_silence_in_the_meeting_is_not_silence_from_the_lane.py",
     "test_the_escape_actually_consults_it"),
    ("test_1202kp_the_backfill_had_a_caller_and_was_still_unreachable.py",
     "test_the_probe_only_runs_when_reconciling"),
    ("test_1202kq_the_same_route_defect_has_a_quieter_symptom.py",
     "test_it_never_touches_the_score_or_the_verdict"),
    ("test_1202ks_the_read_scope_decision_failed_open.py",
     "test_writes_do_not_silently_become_strict"),
    ("test_1202ra_the_verdict_is_sampled_under_the_lease.py",
     "test_no_sample_is_taken_outside_a_lease"),
    ("test_1202y8_the_page_that_fetches_is_a_page_that_calls.py",
     "test_axios_is_not_handled"),
    ("test_1202zd_register_returns_what_the_table_has.py",
     "test_the_returning_clause_is_derived_and_not_a_literal"),
    ("test_1202ze_the_gate_clears_while_the_smoke_failed.py",
     "test_the_helper_cannot_change_the_verdict"),
    ("test_1203a6_a_request_with_no_response_is_not_an_unwired_form.py",
     "test_the_flow_record_carries_the_grounds"),
    ("test_1203a6_a_request_with_no_response_is_not_an_unwired_form.py",
     "test_the_verdict_itself_is_unchanged"),
    ("test_1203c6_the_api_count_included_the_ui.py",
     "test_api_failed_is_not_read_from_the_rebound_name"),
    ("test_1203fw_the_framework_served_register_and_the_apps_wanted_signup.py",
     "test_both_keep_register_s_created_status"),
    ("test_1203gf_docker_up_was_one_undivided_number.py",
     "test_no_extra_check_was_added_to_the_twenty_six"),
    ("test_1203gg_the_stall_was_in_four_untimed_steps.py",
     "test_the_lock_wait_uses_the_elapsed_the_code_already_keeps"),
    ("test_1203gh_the_wait_never_said_how_long.py",
     "test_the_duration_log_cannot_raise_into_the_caller"),
    ("test_1203gh_the_wait_never_said_how_long.py",
     "test_the_free_path_reports_how_long_it_waited"),
    ("test_1203gv_the_reset_left_the_defect_count_behind.py",
     "test_the_reset_lives_behind_the_restore_guard"),
    ("test_1203hv_the_count_was_flat_while_the_page_changed.py",
     "test_it_is_its_own_if_not_nested_in_1138s"),
    ("test_1203hx_the_chains_came_down_and_nothing_saw_it.py",
     "test_each_depth_signal_keeps_its_own_if"),
    ("test_1203id_the_counter_said_retry_and_meant_exception.py",
     "test_the_recorder_is_not_called_above_the_guards"),
    ("test_1203ip_typed_inputs_are_filled_with_their_own_type.py",
     "test_the_runner_no_longer_states_the_unfillable_rule_itself"),
    ("test_1203it_the_login_went_to_oauth_and_the_probe_looked_at_auth.py",
     "test_the_predicate_reads_the_imported_name"),
    ("test_1203iu_nobody_was_listening_for_the_page_throwing.py",
     "test_the_sibling_does_not_read_the_error_itself"),
    ("test_1203ix_what_the_loop_saw_was_never_recorded.py",
     "test_the_note_does_not_read_the_counts"),
    ("test_1203iz_a_flow_passed_and_nobody_logged_in.py",
     "test_nothing_assigns_ok_from_the_flag"),
    ("test_1203iz_a_flow_passed_and_nobody_logged_in.py",
     "test_the_note_does_not_read_the_flag"),
    ("test_1203kf_which_of_the_three_causes.py",
     "test_the_binding_this_inference_rests_on_is_still_outside_the_loop_1203kf"),
    ("test_1203mh_the_warning_said_every_screen.py",
     "test_the_false_claim_is_in_no_literal"),
    ("test_1203mj_the_warning_called_its_finding_inert.py",
     "test_the_withdrawn_phrase_is_only_ever_quoted_never_asserted"),
    ("test_1203nn_the_file_that_had_never_existed.py",
     "test_no_such_file_matches_the_producers_output_shape"),
    ("test_1203nn_the_file_that_had_never_existed.py",
     "test_the_reason_is_empty_when_a_suite_exists"),
    ("test_1203no_which_of_the_two_numbers_lied.py",
     "test_the_priority_is_still_P1"),
    ("test_1203np_the_card_that_plays_nothing.py",
     "test_it_is_not_nested_inside_a_failed_checks_branch"),
    ("test_1203nq_the_remap_the_asset_check_never_read.py",
     "test_the_googlemaps_icons_stay_unannotated"),
    ("test_1203ns_the_comment_that_shipped_with_no_text.py",
     "test_only_reachable_two_column_tables_matter_and_the_fill_skips_them"),
    ("test_1203nz_one_rendering_judged_as_five_screens.py",
     "test_the_judging_of_a_collision_is_evidenced"),
    ("test_280_ui_flow_failed_has_owner.py",
     "test_ui_flow_failed_owner_spec_is_well_formed"),
    ("test_empty_page_is_distinct_from_no_probe_688.py",
     "test_fill_uses_the_shared_renderer"),
    ("test_failed_repair_says_so_770.py",
     "test_neither_site_raises"),
    ("test_gate_says_when_the_matrix_is_skipped_671.py",
     "test_it_is_surfaced_beside_task_suite_exists"),
    ("test_hub_sync_stage_is_inert_702.py",
     "test_its_wired_siblings_do_have_call_sites"),
    ("test_the_denial_probe_asks_the_contract_1202ib.py",
     "test_it_cannot_flip_the_verdict"),
    ("test_verdict_key_semantics_720.py",
     "test_the_live_field_is_built_from_results_not_merged"),
])


_ASSERT_METHOD = re.compile(r"^assert[A-Z]")


def _asserts_in(scope):
    """Every assertion in `scope`, BOTH styles.

    #1203pg: the first version counted only `ast.Assert`, so every `unittest.TestCase` test was
    invisible -- 637 of this repo's 2363 test files, and 14 more instances of this very shape,
    one of them in the file that introduced the ranking this ratchet came out of. Same mistake
    as #1203ow's twelve ratchets filtering by file name: a filter keyed on spelling, not role.
    """
    out = []
    for n in ast.walk(scope):
        if isinstance(n, ast.Assert):
            out.append(n)
        elif (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
              and _ASSERT_METHOD.match(n.func.attr or "")):
            out.append(n)
    return out


def _is_vacuous_shape(tree):
    """The (name) of every test in `tree` whose assertions could all be skipped."""
    out = []
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if not fn.name.startswith("test"):
            continue
        # a parametrized test's loop belongs to pytest, not to the test
        if "parametrize" in " ".join(ast.unparse(d) for d in fn.decorator_list):
            continue
        asserts = _asserts_in(fn)
        loops = [n for n in ast.walk(fn) if isinstance(n, (ast.For, ast.AsyncFor))]
        if not asserts or not loops:
            continue
        in_loop = {id(n) for L in loops for n in _asserts_in(L)}
        if len(in_loop) != len(asserts):
            continue                     # something asserts unconditionally; not this shape
        if not any(_SEARCH.search(ast.unparse(L.iter)) for L in loops):
            continue                     # iterates a literal or a constant, cannot be empty
        out.append(fn.name)
    return out


def _scan():
    found = set()
    for d in _TEST_DIRS:
        if not os.path.isdir(d):
            continue
        for name in sorted(os.listdir(d)):
            if not (name.startswith("test_") and name.endswith(".py")):
                continue
            path = os.path.join(d, name)
            try:
                with open(path, encoding="utf-8", errors="replace") as fh:
                    tree = ast.parse(fh.read())
            except (SyntaxError, OSError):
                continue
            for fn in _is_vacuous_shape(tree):
                found.add((name, fn))
    return found


class TheScanWorks(unittest.TestCase):
    """#947/#1039: a detector that reaches nothing must not read as a clean result."""

    def test_it_sees_the_tree(self):
        self.assertTrue(_scan(), "the scan found nothing at all -- it is not reaching the tests")

    def test_it_fires_on_the_shape(self):
        src = ("import ast\n"
               "def test_a(tree):\n"
               "    for n in ast.walk(tree):\n"
               "        assert not bad(n)\n")
        self.assertEqual(_is_vacuous_shape(ast.parse(src)), ["test_a"])

    def test_an_unconditional_assertion_clears_it(self):
        """The documented way out: assert the search found its target."""
        src = ("import ast\n"
               "def test_a(tree):\n"
               "    nodes = list(ast.walk(tree))\n"
               "    assert nodes, 're-aim this test'\n"
               "    for n in nodes:\n"
               "        assert not bad(n)\n")
        self.assertEqual(_is_vacuous_shape(ast.parse(src)), [])

    def test_it_fires_on_the_shape_in_unittest_style(self):
        """The sixth blind spot, pinned: `self.assertX` is an assertion too."""
        s = ("import ast, unittest\n"
             "class T(unittest.TestCase):\n"
             "    def test_a(self):\n"
             "        for n in ast.walk(self.tree):\n"
             "            self.assertFalse(bad(n))\n")
        self.assertEqual(_is_vacuous_shape(ast.parse(s)), ["test_a"])

    def test_an_unconditional_unittest_assertion_clears_it(self):
        s = ("import ast, unittest\n"
             "class T(unittest.TestCase):\n"
             "    def test_a(self):\n"
             "        nodes = list(ast.walk(self.tree))\n"
             "        self.assertTrue(nodes, 're-aim this test')\n"
             "        for n in nodes:\n"
             "            self.assertFalse(bad(n))\n")
        self.assertEqual(_is_vacuous_shape(ast.parse(s)), [])

    def test_a_literal_iterable_is_not_the_shape(self):
        """A tuple written in the test cannot be empty, and 682 tests loop over one."""
        src = ("def test_a():\n"
               "    for k in ('a', 'b'):\n"
               "        assert k\n")
        self.assertEqual(_is_vacuous_shape(ast.parse(src)), [])

    def test_a_parametrized_test_is_not_the_shape(self):
        src = ("import ast, pytest\n"
               "@pytest.mark.parametrize('x', [1, 2])\n"
               "def test_a(x, tree):\n"
               "    for n in ast.walk(tree):\n"
               "        assert not bad(n)\n")
        self.assertEqual(_is_vacuous_shape(ast.parse(src)), [])


def new_instances(found, baseline):
    """Entries that carry the shape but are not allowed. Pure, so the DIRECTION is testable.

    #1203pg found this: the first version compared the sets inline, and with both differences
    empty -- which is the healthy state -- `found - baseline` and `baseline - found` produce
    the same answer. A mutation that reversed the comparison was MISSED, and so was one that
    deleted the staleness check outright. An unobservable direction is not a checked direction.
    """
    return sorted(set(found) - set(baseline))


def stale_entries(found, baseline):
    """Allowances that no longer carry the shape (#1203oa: a parked list rots)."""
    return sorted(set(baseline) - set(found))


class TheComparisonsPointTheRightWay(unittest.TestCase):
    """Synthetic inputs, because the real ones are both empty when all is well."""

    def test_a_new_instance_is_reported(self):
        self.assertEqual(new_instances({("f.py", "t_new"), ("a.py", "t_ok")},
                                       {("a.py", "t_ok")}),
                         [("f.py", "t_new")])

    def test_a_stale_allowance_is_not_reported_as_new(self):
        """The reversed comparison: a baseline entry that is gone must not read as an arrival."""
        self.assertEqual(new_instances({("a.py", "t_ok")},
                                       {("a.py", "t_ok"), ("gone.py", "t_old")}),
                         [])

    def test_a_stale_allowance_is_reported_as_stale(self):
        self.assertEqual(stale_entries({("a.py", "t_ok")},
                                       {("a.py", "t_ok"), ("gone.py", "t_old")}),
                         [("gone.py", "t_old")])

    def test_a_new_instance_is_not_reported_as_stale(self):
        self.assertEqual(stale_entries({("a.py", "t_ok"), ("f.py", "t_new")},
                                       {("a.py", "t_ok")}),
                         [])

    def test_the_two_are_not_the_same_function(self):
        """If both ever return the same thing on the same input, one of them is wrong."""
        found, base = {("a.py", "t1")}, {("b.py", "t2")}
        self.assertNotEqual(new_instances(found, base), stale_entries(found, base))

    def test_a_healthy_tree_is_empty_both_ways(self):
        """Why the direction was unobservable in the first place, pinned so it stays explicit."""
        same = {("a.py", "t1")}
        self.assertEqual(new_instances(same, same), [])
        self.assertEqual(stale_entries(same, same), [])


class TheBaselineOnlyShrinks(unittest.TestCase):

    def test_no_new_test_can_be_vacuous_if_its_search_finds_nothing(self):
        new = new_instances(_scan(), _BASELINE)
        self.assertEqual(new, [], (
            "these tests assert only inside a loop over a search result, so they pass having "
            "asserted nothing if the search stops matching. Add one assertion that the search "
            "found its target (`assert nodes, 're-aim this test'`): %s" % new))

    def test_the_baseline_is_not_stale(self):
        """#1203oa: a parked list rots. An entry that no longer exists is a stale allowance."""
        gone = stale_entries(_scan(), _BASELINE)
        self.assertEqual(gone, [], (
            "these baseline entries no longer carry the shape -- delete them from _BASELINE "
            "so the list keeps meaning what it says: %s" % gone))


if __name__ == "__main__":
    unittest.main()
