"""#357: the ui_flow index is a one-way ratchet — green in, never out.

`_index_ui_flow_records` collapses duplicate records for a flow as "passed if
ANY record passed", and says so in its own docstring:

    "``best_status`` is ``passed`` if any record for that flow passed ... so a
     later passing run can clear an earlier failure"

The intent is legitimate — that IS how the retry loop should work. The defect is
that the rule is blind in the other direction: a later FAILING record can never
clear an earlier pass. Once a flow has been green once, the gate can never see
it regress, which is the entire purpose of a regression gate.

r91's store holds 18 ui_flow records for 4 flows, and the verifier's own trail
shows a flow going success -> failure -> success -> failure -> success. Under
passed-wins every one of those reads as green forever after the first success.

The records already carry the timestamp needed to do this properly:
`get_validation_results` maps `updated_at` onto `recorded_at` for every row. So
LATEST-WINS keeps the legitimate intent (a later pass clears an earlier failure)
and fixes the defect (a later failure clears an earlier pass).

Records with no usable timestamp keep the old passed-wins behaviour, so an old
store cannot start reporting differently just because it lacks the field.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for _p in (str(ROOT), str(LLM_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)


class _Reg:
    def __init__(self, rows):
        self._rows = rows

    def get_validation_results(self, limit=1000):
        return self._rows


def _rec(flow, status, at=None):
    r = {"name": f"validation:ui_flow:{flow}", "status": status,
         "metadata": {"check": "ui_flow", "flow": flow}}
    if at is not None:
        r["recorded_at"] = at
    return r


def _index(rows):
    from multi_agent.runtime.flow_coverage import _index_ui_flow_records
    return _index_ui_flow_records(_Reg(rows))


class ARegressionIsVisible(unittest.TestCase):

    def test_a_later_failure_clears_an_earlier_pass(self):
        self.assertEqual(
            _index([_rec("fyp_feed", "passed", 100), _rec("fyp_feed", "failed", 200)]),
            {"fyp_feed": "failed"})

    def test_record_order_does_not_matter_only_time(self):
        self.assertEqual(
            _index([_rec("fyp_feed", "failed", 200), _rec("fyp_feed", "passed", 100)]),
            {"fyp_feed": "failed"})

    def test_the_r91_flip_flop_ends_where_it_actually_ended(self):
        rows = [_rec("fyp_feed", "passed", 1), _rec("fyp_feed", "failed", 2),
                _rec("fyp_feed", "passed", 3), _rec("fyp_feed", "failed", 4)]
        self.assertEqual(_index(rows), {"fyp_feed": "failed"})


class TheLegitimateRetrySemanticsSurvive(unittest.TestCase):
    """A later PASS must still clear an earlier failure."""

    def test_a_later_pass_clears_an_earlier_failure(self):
        self.assertEqual(
            _index([_rec("signup", "failed", 100), _rec("signup", "passed", 200)]),
            {"signup": "passed"})

    def test_a_single_pass_is_passed(self):
        self.assertEqual(_index([_rec("signup", "passed", 1)]), {"signup": "passed"})

    def test_a_single_failure_is_failed(self):
        self.assertEqual(_index([_rec("signup", "failed", 1)]), {"signup": "failed"})


class FlowsAreIndependent(unittest.TestCase):

    def test_one_flows_regression_does_not_touch_another(self):
        rows = [_rec("a", "passed", 1), _rec("b", "passed", 1), _rec("b", "failed", 2)]
        self.assertEqual(_index(rows), {"a": "passed", "b": "failed"})


class UntimedRecordsKeepTheOldBehaviour(unittest.TestCase):
    """An old store without recorded_at must not start reporting differently."""

    def test_untimed_passed_wins(self):
        self.assertEqual(
            _index([_rec("x", "passed"), _rec("x", "failed")]), {"x": "passed"})

    def test_untimed_failure_only_is_failed(self):
        self.assertEqual(_index([_rec("x", "failed")]), {"x": "failed"})

    def test_a_timed_record_beats_an_untimed_one(self):
        self.assertEqual(
            _index([_rec("x", "passed"), _rec("x", "failed", 500)]), {"x": "failed"})


class NonUiFlowRecordsAreIgnored(unittest.TestCase):

    def test_api_smoke_is_not_indexed(self):
        rows = [{"name": "validation:api_smoke", "status": "failed",
                 "metadata": {"check": "api_smoke"}, "recorded_at": 9}]
        self.assertEqual(_index(rows), {})


if __name__ == "__main__":
    unittest.main()
