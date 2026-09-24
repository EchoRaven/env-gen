r"""#1202bg: a control whose handler has an empty body looks live and is not.

Measured across the corpus: 24 of 117 delivered frontends carry at least one. The
clearest is tiktok-web-r91's login modal, hand-read in context:

    <LoginOptionRow icon={<Ic.QR />}     label="Use QR code"          onClick={() => {}} />
    <LoginOptionRow icon={<Ic.Google />} label="Continue with Google" onClick={() => {}} />
    <LoginOptionRow icon={<Ic.Apple />}  label="Continue with Apple"  onClick={() => {}} />

Five sign-in routes that render, hover, and answer a click with silence. Every existing
frontend check passes that page — the element is present, the prop is present, the page
renders — which is why this one exists. Run against r32's delivered UI, dead-nav,
fallback-page, bare-fetch and invented-field all report 0.

A real handler must never be flagged, which the last three tests pin.
"""
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS_DIR.parent / "env_generator" / "llm_generator"))

from multi_agent.runtime.frontend_audit import (  # noqa: E402
    noop_handler_findings_1202bg)


class NoopHandlerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.src = Path(tempfile.mkdtemp(prefix="bg1202_")) / "src"
        (self.src / "pages").mkdir(parents=True)

    def tearDown(self) -> None:
        shutil.rmtree(self.src.parent, ignore_errors=True)

    def _page(self, body):
        (self.src / "pages" / "P.jsx").write_text(body, encoding="utf-8")
        return noop_handler_findings_1202bg(self.src)

    def test_the_r91_shape_is_reported(self):
        found = self._page(
            '<LoginOptionRow label="Continue with Google" onClick={() => {}} />\n')
        self.assertEqual(len(found), 1)
        self.assertIn("onClick", found[0])

    def test_the_no_space_spelling_is_reported(self):
        """netflix-local-r21 writes it without spaces."""
        self.assertEqual(len(self._page("<b onClick={()=>{}} />")), 1)

    def test_a_console_log_only_handler_is_reported(self):
        """A debugging stub that reached delivery is still a control that does nothing."""
        found = self._page("<b onClick={() => console.log('clicked')} />")
        self.assertEqual(len(found), 1)

    def test_a_real_handler_is_not_reported(self):
        self.assertEqual(self._page("<b onClick={() => setOpen(true)} />"), [])

    def test_a_named_handler_is_not_reported(self):
        self.assertEqual(self._page("<b onClick={handleSubmit} />"), [])

    def test_a_handler_with_a_body_is_not_reported(self):
        self.assertEqual(
            self._page("<b onClick={() => { setOpen(true); track('x'); }} />"), [])


if __name__ == "__main__":
    unittest.main()
