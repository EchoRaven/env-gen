"""#1202ex: chains must say whether they judged the code that is on disk.

#952 lists three causes for a declared-but-unmounted route, notes their fixes
differ, and ends: "Nothing here measures build currency, so (3) cannot be ruled
out from this line."  (3) is "the running container predates this handler".
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS_DIR.parent))
sys.path.insert(0, str(THIS_DIR.parent / "env_generator" / "llm_generator"))

from multi_agent.runtime.chain_executor import build_currency_1202ex  # noqa: E402
from multi_agent.runtime.validation_runner import _app_source_fingerprint  # noqa: E402

EXEC_SRC = (THIS_DIR.parent / "env_generator" / "llm_generator" / "multi_agent"
            / "runtime" / "chain_executor.py").read_text(encoding="utf-8")


def _project(built=True, edit_after=False):
    d = Path(tempfile.mkdtemp())
    (d / "docker").mkdir()
    (d / "app").mkdir()
    (d / "app" / "main.py").write_text("x = 1", encoding="utf-8")
    compose = d / "docker" / "docker-compose.yml"
    compose.write_text("services: {}", encoding="utf-8")
    if built:
        (d / "docker" / ".last_build_fingerprint").write_text(
            _app_source_fingerprint(compose) or "", encoding="utf-8")
    if edit_after:
        (d / "app" / "main.py").write_text("x = 2", encoding="utf-8")
    return d


class TestBuildCurrency(unittest.TestCase):

    def test_a_matching_image_rules_the_stale_container_out(self):
        """The exact half: a match proves the image was built from this source."""
        self.assertEqual(build_currency_1202ex(_project())["verdict"], "current")

    def test_a_source_edited_after_the_build_reads_as_changed(self):
        got = build_currency_1202ex(_project(edit_after=True))
        self.assertEqual(got["verdict"], "changed")
        self.assertIn("rebuild", got["detail"])

    def test_never_built_is_unknown_not_changed(self):
        """No recorded build is an absence of evidence, not evidence of staleness."""
        self.assertEqual(build_currency_1202ex(_project(built=False))["verdict"], "unknown")

    def test_a_missing_project_is_unknown_and_says_why(self):
        got = build_currency_1202ex("/nonexistent-1202ex")
        self.assertEqual(got["verdict"], "unknown")
        self.assertIn("compose", got["detail"])

    def test_it_never_raises(self):
        """A diagnostic that can fail the thing it diagnoses is worse than none."""
        for bad in (None, 42, object(), b"\xff"):
            self.assertIn(build_currency_1202ex(bad)["verdict"],
                          ("unknown", "current", "changed"))

    def test_952_no_longer_claims_the_cause_cannot_be_ruled_out(self):
        """The whole point: that sentence was the gap."""
        # Scoped to the warning itself. A whole-file search finds the sentence in
        # build_currency_1202ex's docstring, which QUOTES it -- the same
        # comment-trips-the-assertion shape #943 exists to stop.
        i = EXEC_SRC.index("#952 DECLARED BUT UNMOUNTED")
        j = EXEC_SRC.index('_u["declared_as"]', i)
        warning = EXEC_SRC[i:j]
        self.assertNotIn("cannot be ruled out", warning)
        self.assertIn("BUILD CURRENCY", warning)

    def test_the_verdict_is_measured_before_any_chain_is_judged(self):
        """Measured after the fact it would describe a different app."""
        measured = EXEC_SRC.index("_currency_1202ex = build_currency_1202ex(project_dir)")
        judged = EXEC_SRC.index("results = [execute_chain(", measured - 4000)
        self.assertLess(measured, judged)

    def test_the_verdict_reaches_the_caller(self):
        self.assertIn('"build_currency_1202ex": _currency_1202ex', EXEC_SRC)


class TheVerdictReachesTheReader(unittest.TestCase):
    """A verdict in a dict nothing reads is the `declared_but_unmounted_952` shape:
    that key has no consumer outside chain_executor. `broken` is what the gate reports
    and the lane is handed, so the caveat has to land there."""

    def _project(self, stale):
        import json
        d = Path(tempfile.mkdtemp())
        (d / "docker").mkdir()
        (d / "app").mkdir()
        (d / "shared" / "hubs").mkdir(parents=True)
        (d / "app" / "main.py").write_text("x = 1", encoding="utf-8")
        compose = d / "docker" / "docker-compose.yml"
        compose.write_text("services: {}", encoding="utf-8")
        (d / "docker" / ".last_build_fingerprint").write_text(
            _app_source_fingerprint(compose) or "", encoding="utf-8")
        if stale:
            (d / "app" / "main.py").write_text("x = 2", encoding="utf-8")
        (d / "shared" / "hubs" / "registryhub_verification_chains.json").write_text(
            json.dumps({"c": {"name": "c", "steps": [
                {"action": "create", "method": "POST", "path": "/api/x",
                 "body": {"a": 1}, "expect": [201]}]}}), encoding="utf-8")
        return d

    def _run(self, stale):
        from multi_agent.runtime import chain_executor as ce

        def fake_http(method, url, *, token=None, body=None, timeout=10,
                      form=False, headers=None):
            return {"status": 400,
                    "body_text": '{"detail":"a create needs at least one field"}',
                    "error": None}

        real = ce._http
        try:
            ce._http = fake_http
            return ce.run_chains("http://x", self._project(stale), [])
        finally:
            ce._http = real

    def test_a_stale_image_puts_the_caveat_first_in_broken(self):
        """Also the regression guard for the crash this test found: the warning on the
        `changed` path referenced a local logger bound LATER in run_chains, so the only
        path the fix exists for raised UnboundLocalError while `current` passed."""
        res = self._run(stale=True)
        self.assertEqual(res["build_currency_1202ex"]["verdict"], "changed")
        self.assertTrue(res["broken"][0].startswith("[build currency #1202ex]"))
        self.assertIn("Rebuild", res["broken"][0])

    def test_a_current_image_adds_no_caveat(self):
        """Good news needs no line -- a caveat on every run is a caveat nobody reads."""
        res = self._run(stale=False)
        self.assertEqual(res["build_currency_1202ex"]["verdict"], "current")
        self.assertEqual(len(res["broken"]), 1)
        self.assertNotIn("build currency", res["broken"][0])


if __name__ == "__main__":
    unittest.main()
