"""#1202fc: the lane-clobber refusal must name WHO tried, not only WHAT was hit.

#1202cw's own note says the `refused` bucket "should stay empty -- a name
appearing there is a projector clobbering lane work without having said why".
netflix-r41 (live) put seven page files in it, and the line named every FILE and
no ACTOR, so acting on the alarm meant reading 52 call sites in frontend_scaffold
alone (20 of which declare clobber_ok=) and guessing.
"""
import logging
import sys
import tempfile
import unittest
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS_DIR.parent))
sys.path.insert(0, str(THIS_DIR.parent / "env_generator" / "llm_generator"))

from multi_agent.runtime import path_routed_workspace as prw  # noqa: E402


class _Capture(logging.Handler):
    def __init__(self):
        super().__init__(level=logging.WARNING)
        self.msgs = []

    def emit(self, record):
        self.msgs.append(record.getMessage())


def _lane_owned_file():
    """A non-empty file under an app/ path the guard treats as lane-owned."""
    d = Path(tempfile.mkdtemp())
    f = d / "app" / "frontend" / "src" / "pages" / "TrendingPage.jsx"
    f.parent.mkdir(parents=True)
    f.write_text("export default function TrendingPage() { return <div/> }",
                 encoding="utf-8")
    return f


class TestRefusalNamesTheActor(unittest.TestCase):

    def setUp(self):
        prw._LANE_CLOBBERS_1202CW["refused"].clear()
        prw._LANE_CLOBBERS_1202CW["declared"].clear()
        self.cap = _Capture()
        self.log = logging.getLogger(prw.__name__)
        self.log.addHandler(self.cap)

    def tearDown(self):
        self.log.removeHandler(self.cap)

    def test_the_message_names_the_calling_site(self):
        f = _lane_owned_file()
        if not prw.path_is_lane_owned_1202cw(f):
            self.skipTest("this path shape is not lane-owned on this build")
        prw.framework_write_1202cw(f, "framework version")
        self.assertTrue(self.cap.msgs, "the refusal must still be reported")
        msg = self.cap.msgs[0]
        self.assertIn("TrendingPage.jsx", msg, "the target is still named")
        self.assertIn(__name__.rsplit(".", 1)[-1], msg,
                      "the ACTOR must be named: " + msg)

    def test_the_lane_version_still_stands(self):
        f = _lane_owned_file()
        if not prw.path_is_lane_owned_1202cw(f):
            self.skipTest("this path shape is not lane-owned on this build")
        before = f.read_text(encoding="utf-8")
        self.assertFalse(prw.framework_write_1202cw(f, "framework version"))
        self.assertEqual(f.read_text(encoding="utf-8"), before)

    def test_the_site_lookup_never_raises(self):
        """A diagnostic must never be the reason a write path fails."""
        self.assertIsInstance(prw._calling_site_1202fc(), str)
        self.assertTrue(prw._calling_site_1202fc())

    def test_it_does_not_name_the_guard_itself(self):
        site = prw._calling_site_1202fc()
        self.assertNotIn("path_routed_workspace", site)


if __name__ == "__main__":
    unittest.main()
