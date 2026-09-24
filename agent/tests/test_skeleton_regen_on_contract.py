"""Guard: FIX #203 — regenerate the backend skeleton when the CONTRACT changes,
not only when the app-source hash changes.

r10/r11 live: after the interaction endpoints validated (like/save/follow 201)
and business_chain passed, delivery walled on #173 placeholder_stub_handler.
When the lane (belatedly) REGISTERED the missing backing tables mid-run, the
stubs did NOT clear — because the skeleton-regen gate fired only on an
app-SOURCE change (`_app_sig != _fwval_healed_sig`), and registering a table
changes the CONTRACT (registry), not app/backend/*.py. So main.py stayed frozen
with `{items:[]}` stubs while the tables existed → the projector never
re-emitted real handlers → guaranteed wall. The gate must ALSO regen when the
tables/endpoints contract version moves.
"""

import sys
import unittest
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(AGENT_DIR))
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

from multi_agent.runtime.framework_validation import (  # noqa: E402
    _should_regen_skeleton,
)


class SkeletonRegenGateTests(unittest.TestCase):
    def test_app_source_change_triggers(self):
        self.assertTrue(_should_regen_skeleton(
            app_sig="B", healed_sig="A", build_wedged=False,
            contract_sig=(1, 1), healed_contract_sig=(1, 1)))

    def test_contract_change_triggers_even_if_source_same(self):
        # THE FIX: a new table (contract version bump) with unchanged app source
        self.assertTrue(_should_regen_skeleton(
            app_sig="A", healed_sig="A", build_wedged=False,
            contract_sig=(2, 1), healed_contract_sig=(1, 1)))

    def test_endpoint_change_triggers(self):
        self.assertTrue(_should_regen_skeleton(
            app_sig="A", healed_sig="A", build_wedged=False,
            contract_sig=(1, 2), healed_contract_sig=(1, 1)))

    def test_no_change_no_regen(self):
        self.assertFalse(_should_regen_skeleton(
            app_sig="A", healed_sig="A", build_wedged=False,
            contract_sig=(1, 1), healed_contract_sig=(1, 1)))

    def test_build_wedged_forces_regen(self):
        self.assertTrue(_should_regen_skeleton(
            app_sig="A", healed_sig="A", build_wedged=True,
            contract_sig=(1, 1), healed_contract_sig=(1, 1)))

    def test_none_app_sig_forces_regen(self):
        self.assertTrue(_should_regen_skeleton(
            app_sig=None, healed_sig="A", build_wedged=False,
            contract_sig=(1, 1), healed_contract_sig=(1, 1)))

    def test_first_run_healed_contract_none_triggers(self):
        # first regen (nothing healed yet) must fire
        self.assertTrue(_should_regen_skeleton(
            app_sig="A", healed_sig=None, build_wedged=False,
            contract_sig=(1, 1), healed_contract_sig=None))


if __name__ == "__main__":
    unittest.main()
