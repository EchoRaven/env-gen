r"""#1202bm: a handler that judges an input invalid and then stores a valid one instead.

netflix-r32, live:

    POST /api/titles/1/rating {"value": "garbage_not_a_rating"}  ->  201
    {"id":20,"profile_id":29,"title_id":1,"value":"thumbs_up"}

The lane wrote why, and the reason is the finding: *"Be tolerant of stale
verifier/client payloads ... Persist a valid default instead of rejecting the multi-step
business flow."* A chain step that 400s blocks delivery, so the handler was made unable
to 400 — and the endpoint now records a positive rating for anything at all, including an
empty body.

The frontend has had a fabricated-fallback gate since #191. The backend had none, and
this is the same defect one layer down: the caller is told 201 for a value the handler
itself refused.

Only the SUBSTITUTING form counts. Alias normalisation ("like" -> "thumbs_up") is correct,
and so is a 400 — the last three tests pin both.
"""
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS_DIR.parent / "env_generator" / "llm_generator"))

from multi_agent.runtime.backend_audit import (  # noqa: E402
    invalid_value_defaults_1202bm)


class InvalidValueSubstitutionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="bm1202_"))
        self.be = self.root / "app" / "backend"
        self.be.mkdir(parents=True)

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def _routes(self, body):
        (self.be / "custom_routes.py").write_text(body, encoding="utf-8")
        return invalid_value_defaults_1202bm(self.root)

    def test_the_r32_shape_is_reported(self):
        found = self._routes(
            'if value not in {"thumbs_down", "thumbs_up", "two_thumbs"}:\n'
            '    value = "thumbs_up"\n')
        self.assertEqual(len(found), 1)
        self.assertIn("thumbs_up", found[0])
        self.assertIn("custom_routes.py", found[0])

    def test_an_intervening_comment_does_not_hide_it(self):
        """r32 explains itself in three comment lines between the test and the assignment."""
        found = self._routes(
            'if value not in {"a", "b"}:\n'
            '    # be tolerant of stale payloads\n'
            '    # so the flow does not fail\n'
            '    value = "a"\n')
        self.assertEqual(len(found), 1)

    def test_raising_is_not_a_finding(self):
        """The correct handling must never be flagged."""
        self.assertEqual(
            self._routes('if value not in {"a", "b"}:\n'
                         '    raise HTTPException(status_code=400, detail="bad value")\n'), [])

    def test_alias_normalisation_is_not_a_finding(self):
        """Mapping a synonym onto a canonical value is right, and is a different shape."""
        self.assertEqual(
            self._routes('value = {"like": "thumbs_up", "up": "thumbs_up"}.get(value, value)\n'),
            [])

    def test_a_sentinel_outside_the_allowed_set_is_not_a_finding(self):
        """Assigning something the branch did NOT just accept is not claiming validity."""
        self.assertEqual(
            self._routes('if status not in {"active", "paused"}:\n'
                         '    status = "unknown"\n'), [])


if __name__ == "__main__":
    unittest.main()
