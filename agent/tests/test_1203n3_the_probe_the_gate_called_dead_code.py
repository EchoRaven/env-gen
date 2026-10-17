r"""#1203n3: the one gate that never read the `kind` tag parked probes are tagged with.

`_tag_parked_probe_1202dw` stamps `metadata.kind='infra'` on a parked `__`-probe AT
REGISTRATION, and its own argument for doing so is that

    Every one of those gates ALREADY exempts `metadata.kind` in FIXED_ENDPOINT_KINDS. The
    exemption could not fire because the parked registration carried `metadata: {}`.

`contract.py` says it from the other side -- "All gates point here instead of redefining it
... every gate that points there skips it". `scan_dead_endpoints` did not point there. Its
only two exemptions were `status != "defined"` and #1202kf's framework surface (method+path),
so a probe tagged exactly for this purpose was still called the lane's dead code.

MEASURED on r164: all five of its `__noop*` registrations carry `{"kind": "infra", ...}`, and
the dead-artifact finding named two of them anyway -- while they sat at `status=defined`,
before something moved them to implemented/deprecated and the status rule started hiding them.

WHAT IT REMOVES, by the standard #1202kf set for itself -- across the modern corpus's
dead-endpoint entries this drops **4 of 34**, in 3 runs, and every one is a parked probe
(`/__noop__` x2, `/__noop_orchestrator_status_check`, `/__noop_orchestrator_read__`); the
other 30, in 11 runs, are untouched. In two of those three runs the probes were the ENTIRE
finding:

    instagram-core-r174   1 dead artifact(s) (Cutover 19 gate) — endpoints=1: endpoints:/__noop__
    tiktok-web-r164       2 dead artifact(s) ... /__noop__, /__noop_orchestrator_read__

`deliverability_dead_artifacts` sits in `failed_checks`, so a BLOCKING delivery check was
failing on nothing but an agent's parked probes.
"""
import unittest

from env_generator.llm_generator.multi_agent.runtime.coverage_audit import (
    scan_dead_endpoints,
    _KINDS_1203N3,
)


class _Registry:
    def __init__(self, eps, consumers=None):
        self.eps, self._c = eps, consumers or {}

    def get_endpoints(self):
        return self.eps

    def get_consumers(self, ep_id):
        return self._c.get(ep_id, [])


class _Hubs:
    def __init__(self, eps, consumers=None):
        self.registryhub = _Registry(eps, consumers)


def _ep(path, method="GET", status="defined", kind=None):
    md = {} if kind is None else {"kind": kind}
    return {"method": method, "path": path, "status": status, "metadata": md}


def _dead(eps, consumers=None):
    return sorted(o["path"] for o in scan_dead_endpoints(_Hubs(eps, consumers)))


class TheTaggedProbeIsNotDeadCode(unittest.TestCase):
    def test_r164s_infra_probe(self):
        eps = {"GET /__noop__": _ep("/__noop__", kind="infra")}
        self.assertEqual(_dead(eps), [])

    def test_every_fixed_kind_is_exempt(self):
        for kind in sorted(_KINDS_1203N3):
            with self.subTest(kind=kind):
                self.assertEqual(_dead({"GET /x": _ep("/x", kind=kind)}), [])

    def test_the_tag_is_read_case_insensitively(self):
        self.assertEqual(_dead({"GET /x": _ep("/x", kind="INFRA")}), [])

    def test_a_probe_beside_a_real_finding_leaves_the_finding(self):
        eps = {"GET /__noop__": _ep("/__noop__", kind="infra"),
               "GET /api/videos": _ep("/api/videos")}
        self.assertEqual(_dead(eps), ["/api/videos"])


class TheRealFindingsSurvive(unittest.TestCase):
    def test_an_untagged_business_endpoint_is_still_dead(self):
        self.assertEqual(_dead({"GET /api/videos": _ep("/api/videos")}), ["/api/videos"])

    def test_a_missing_metadata_key_is_still_dead(self):
        ep = {"method": "GET", "path": "/api/videos", "status": "defined"}
        self.assertEqual(_dead({"GET /api/videos": ep}), ["/api/videos"])

    def test_a_kind_that_is_not_in_the_fixed_set(self):
        self.assertEqual(_dead({"GET /api/x": _ep("/api/x", kind="business")}), ["/api/x"])

    def test_an_endpoint_with_a_consumer_is_not_dead(self):
        eps = {"GET /api/videos": _ep("/api/videos")}
        self.assertEqual(_dead(eps, {"GET /api/videos": ["frontend"]}), [])

    def test_a_non_defined_status_is_still_skipped(self):
        for st in ("implemented", "deprecated", "draft"):
            with self.subTest(status=st):
                self.assertEqual(_dead({"GET /api/x": _ep("/api/x", status=st)}), [])


class TheConstantIsNotRedefinedHere(unittest.TestCase):
    """#1032/#772: one owner for the rule, imported rather than copied."""

    def test_it_matches_the_contract_modules_set(self):
        from env_generator.llm_generator.multi_agent.runtime.kickoff.contract import (
            FIXED_ENDPOINT_KINDS,
        )
        self.assertEqual(_KINDS_1203N3,
                         frozenset(str(k).lower() for k in FIXED_ENDPOINT_KINDS))

    def test_infra_is_in_it(self):
        self.assertIn("infra", _KINDS_1203N3)

    def test_the_gate_tests_membership_against_the_shared_set(self):
        """Asserted on the AST, not on the source text: my first version checked that
        `"infra"` does not appear in the source and was fed by the explanatory comment that
        quotes `{"kind": "infra", ...}` -- the exact trap this repo has recorded before."""
        import ast
        import inspect
        from env_generator.llm_generator.multi_agent.runtime import coverage_audit
        tree = ast.parse(inspect.getsource(coverage_audit.scan_dead_endpoints).lstrip())
        names = [getattr(c.comparators[0], "id", None)
                 for c in ast.walk(tree) if isinstance(c, ast.Compare)
                 and c.comparators and isinstance(c.ops[0], ast.In)]
        self.assertIn("_KINDS_1203N3", names,
                      "the kind test does not go through the shared set")


class ItNeverRaises(unittest.TestCase):
    def test_a_registry_without_the_accessor(self):
        class _Bare:
            registryhub = object()
        self.assertEqual(scan_dead_endpoints(_Bare()), [])

    def test_no_registryhub(self):
        class _None:
            registryhub = None
        self.assertEqual(scan_dead_endpoints(_None()), [])

    def test_a_metadata_that_is_not_a_mapping(self):
        ep = {"method": "GET", "path": "/api/x", "status": "defined", "metadata": "nope"}
        self.assertEqual(_dead({"GET /api/x": ep}), ["/api/x"])


if __name__ == "__main__":
    unittest.main()
