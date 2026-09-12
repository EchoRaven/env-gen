"""#1202ky: put the contract/materials disagreement where the LANE reads it.

#1202kx says it in the run log. That is the #1202io precedent and it is where an operator
looks, but it is not established that a lane reads the log at all. The channel a lane
demonstrably reads is the gate blocker's `detail`, which the orchestrator turns into a task --
that is how #1202kr's text reached workhub_tasks.

#1202kr deliberately does not cover this case. Its own docstring: "r117's /api/notifications is
contract-public but was NOT opened (its table is owner-scoped, so the skeleton forced an actor),
the guard still denies it, and the chain demanding 401 is correct." Correct, and out of scope --
it reads the set that was OPENED, and here the route rightly is not in it. So the case had
nothing said about it anywhere a lane reads.

Measured: `GET /api/notifications` is declared auth_required=False while the materials call
`notifications` owner-private in SEVEN runs (r106, r108, r109, r111, r115, r117, r118).

Verified against the REAL objects -- a real RegistryHub over each run's own hub directory, each
run's own chains, each run's own design/reference_spec.json:
    r117             -> names GET /api/notifications   (the endpoint it died on)
    r118             -> names GET /api/user_settings
    netflix-local-r41-> empty

WHAT IS VERIFIED: it fires on the r117 shape; it is silent when the materials say nothing, when
the materials say public, when the contract already says private, and when no FAILING chain
touches the route; it names both repairs and rejects the third; and it is actually wired into
the business_chain_failing detail rather than merely defined.

WHAT IS NOT: that it changes any verdict. It is appended to a blocker that already fires.
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

from multi_agent.runtime import delivery_gate as dg  # noqa: E402
from multi_agent.runtime.registryhub import RegistryHub  # noqa: E402


class _Hubs:
    def __init__(self, base):
        self.base_dir = str(base)


def _chain(path="/api/notifications", status="failing"):
    return [{"name": "notifications_activity_page", "status": status,
             "steps": [{"method": "GET", "path": path, "expect": [401]}]}]


class TheDisagreementReachesTheBlocker(unittest.TestCase):

    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="ky_"))
        (self.root / "design").mkdir(parents=True)
        (self.root / "shared" / "hubs").mkdir(parents=True)
        self.rh = RegistryHub(self.root / "shared" / "hubs")
        self.rh.register_endpoint(method="GET", path="/api/notifications",
                                  schema={"auth_required": False, "response_key": "items"},
                                  agent="backend", status="implemented", kind="business")

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def _spec(self, visibility="owner"):
        ents = [{"name": "notifications"}]
        if visibility:
            ents[0]["visibility"] = visibility
        (self.root / "design" / "reference_spec.json").write_text(
            json.dumps({"entities": ents}), encoding="utf-8")

    def _run(self, authored=None):
        return dg._contract_materials_disagreement_1202ky(
            self.rh, authored if authored is not None else _chain(), _Hubs(self.root))

    def test_it_names_the_route(self):
        """★ The r117 case."""
        self._spec("owner")
        self.assertIn("/api/notifications", self._run())
        self.assertIn("#1202ky", self._run())

    def test_it_names_both_repairs_and_rejects_the_third(self):
        self._spec("owner")
        said = self._run()
        self.assertIn("auth_required=true", said)
        self.assertIn("materials", said)
        self.assertIn("custom_routes.py", said)   # r117's actual move, named as NOT a repair

    def test_silent_when_the_materials_say_nothing(self):
        """#320's bargain: nothing was overruled, so there is nothing to report."""
        self._spec("")
        self.assertEqual(self._run(), "")

    def test_silent_when_the_materials_say_public(self):
        self._spec("public")
        self.assertEqual(self._run(), "")

    def test_silent_when_the_contract_already_agrees(self):
        self._spec("owner")
        rh2 = RegistryHub(self.root / "shared" / "hubs")
        rh2.register_endpoint(method="GET", path="/api/notifications",
                              schema={"auth_required": True, "response_key": "items"},
                              agent="backend", status="implemented", kind="business")
        self.assertEqual(dg._contract_materials_disagreement_1202ky(
            rh2, _chain(), _Hubs(self.root)), "")

    def test_silent_when_no_failing_chain_touches_it(self):
        """An unexercised disagreement is not this blocker's business."""
        self._spec("owner")
        self.assertEqual(self._run(_chain(status="passing")), "")
        self.assertEqual(self._run(_chain(path="/api/videos")), "")

    def test_no_spec_file_at_all_is_silent_not_a_crash(self):
        self.assertEqual(self._run(), "")


class ItIsActuallyWired(unittest.TestCase):
    """Reachability, not presence: a helper nothing calls says nothing (#1202ka's lesson)."""

    def test_it_is_appended_to_the_business_chain_failing_detail(self):
        tree = ast.parse(Path(dg.__file__).read_text(encoding="utf-8"))
        calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
                 and getattr(n.func, "id", "") == "_contract_materials_disagreement_1202ky"]
        self.assertTrue(calls, "the annotation is defined but never called")
        # and the call must sit in a dict literal that names business_chain_failing
        wired = False
        for d in ast.walk(tree):
            if not isinstance(d, ast.Dict):
                continue
            src = ast.dump(d)
            if "business_chain_failing" in src and "_contract_materials_disagreement_1202ky" in src:
                wired = True
                break
        self.assertTrue(wired, "not wired into the business_chain_failing blocker detail")


if __name__ == "__main__":
    unittest.main()
