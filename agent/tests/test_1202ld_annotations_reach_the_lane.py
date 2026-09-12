"""#1202ld: the gate computed these and NOTHING read them.

#1202kr (contract says public / a chain demands a denial), #1202ky (contract says public / the
materials call the table owner-private) and #1202lb (several failing chains are one endpoint)
all append to the `detail` string `_validate_delivery_gate` returns for
`business_chain_failing`.

That string reaches nobody. `dispatch_gate_level_checks(self, failed_checks)` says so in its
own comment -- "the gate-level failed_checks carry names only" -- and the lane-facing task body
is built in the dispatcher from the static `_GATE_OWNER` template plus `_extra`. Measured
across 310 run logs and every workhub_tasks.json in the corpus, the base text of that detail --
"verification chain(s) have NOT passed" -- appears ZERO times, and so do all three annotations.
#1202kr has been dead this way since it shipped; #1202ky and #1202lb were written into the same
dead field on the same day, hours after I recorded the rule that saying a thing is not the same
as it being heard.

They compute correctly. Replayed against the real ledgers of the last two runs, which both died
on `business_chain_failing`:
    tiktok-r119 -> "#1202kr ... core_social_business_flow:GET /api/messages" (one of its two
                   failing chains)
    tiktok-r117 -> "#1202ky ... GET /api/notifications" (its death cause)
    netflix-local-r41 -> silent
In both runs the framework already held the answer and put it somewhere with no reader.

WHAT IS VERIFIED: the annotations are produced from an orch-shaped object over a REAL
RegistryHub; the helper is appended to `_extra` for `business_chain_failing` rather than
replacing #798's broken-step list; it is silent when there is nothing to say; and it never
raises.

WHAT IS NOT: that the lane acts on them. This moves them onto the channel #799 established for
framework-computed facts; whether a lane then does the right thing is r120's evidence, not a
claim this test can make.
"""
from __future__ import annotations

import ast
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(_ROOT), str(_ROOT / "env_generator" / "llm_generator")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from multi_agent.runtime import remediation_dispatcher as rd  # noqa: E402
from multi_agent.runtime.registryhub import RegistryHub  # noqa: E402

_RD = Path(rd.__file__)


class _Hubs:
    def __init__(self, root):
        self.base_dir = str(root)
        self.registryhub = RegistryHub(Path(root) / "shared" / "hubs")


class _Orch:
    def __init__(self, root):
        self.hubs = _Hubs(root)


class TheAnnotationsAreProduced(unittest.TestCase):
    """Built over a REAL RegistryHub, not a stand-in for one."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="ld_"))
        (self.root / "shared" / "hubs").mkdir(parents=True)
        (self.root / "design").mkdir(parents=True)
        self.orch = _Orch(self.root)
        self.rh = self.orch.hubs.registryhub

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def _materials(self, visibility="owner"):
        (self.root / "design" / "reference_spec.json").write_text(
            json.dumps({"entities": [{"name": "notifications", "visibility": visibility}]}),
            encoding="utf-8")

    def _contract_public_notifications(self):
        self.rh.register_endpoint(method="GET", path="/api/notifications",
                                  schema={"auth_required": False, "response_key": "items"},
                                  agent="backend", status="implemented", kind="business")

    def _failing_chain(self):
        self.rh.register_verification_chain(
            name="notifications_page", agent="verifier",
            steps=[{"method": "GET", "path": "/api/notifications", "expect": [401]}])
        self.rh.record_chain_result(
            "notifications_page",
            {"broken": ["GET /api/notifications"],
             "steps": [{"method": "GET", "path": "/api/notifications",
                        "status": 200, "ok": False, "expect": [401]}]},
            agent="verifier")

    def test_the_r117_shape_is_named(self):
        """★ r117's death cause, which the gate already knew and filed nowhere."""
        self._materials("owner")
        self._contract_public_notifications()
        self._failing_chain()
        said = rd.contract_and_surface_annotations_1202ld(self.orch)
        self.assertIn("#1202ky", said)
        self.assertIn("/api/notifications", said)

    def test_silent_when_there_is_nothing_to_say(self):
        self._materials("public")
        self._contract_public_notifications()
        self._failing_chain()
        self.assertEqual(rd.contract_and_surface_annotations_1202ld(self.orch).strip(), "")

    def test_silent_with_no_chains_at_all(self):
        self.assertEqual(rd.contract_and_surface_annotations_1202ld(self.orch), "")

    def test_it_never_raises(self):
        class _Broken:
            hubs = None
        self.assertEqual(rd.contract_and_surface_annotations_1202ld(_Broken()), "")
        self.assertIsInstance(rd.contract_and_surface_annotations_1202ld(object()), str)


class ItReachesTheTaskBody(unittest.TestCase):
    """Reachability, not presence (#1202ka) -- and this whole fix exists because the previous
    channel had no reader."""

    def _dispatch_fn(self):
        tree = ast.parse(_RD.read_text(encoding="utf-8"))
        return next(n for n in ast.walk(tree)
                    if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and n.name == "dispatch_gate_level_checks")

    def test_the_helper_is_called_in_the_dispatcher(self):
        called = [n for n in ast.walk(self._dispatch_fn()) if isinstance(n, ast.Call)
                  and getattr(n.func, "id", "") == "contract_and_surface_annotations_1202ld"]
        self.assertTrue(called, "the annotations still never reach the task body")

    def test_it_APPENDS_rather_than_replacing_798s_broken_steps(self):
        """#798's broken-step list is the most useful line in that task; clobbering it to add
        these would trade one dead annotation for another."""
        src = _RD.read_text(encoding="utf-8")
        self.assertIn("_extra += contract_and_surface_annotations_1202ld(orch)", src)

    def test_extra_is_what_the_task_body_is_built_from(self):
        """If `_extra` ever stops reaching the description, this fix is dead again."""
        src = _RD.read_text(encoding="utf-8")
        self.assertIn("{how}{_extra}", src,
                      "the task body no longer interpolates _extra — re-check this channel")


if __name__ == "__main__":
    unittest.main()
