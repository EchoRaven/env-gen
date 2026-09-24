"""FIX #146 — declared-route vs implemented-route drift is not "unwired".

run-69 M3 STUCK (live): ui_page `messages_page` declared route `/messages`,
the lane wired MessagesPage at `/direct` (a legitimate choice — real
Instagram uses /direct). The page was fully built and reachable, yet
`deliverability_ui_page_unwired` blocked delivery on the stale registry
string for 7 no-change cycles → FAIL-FAST killed M3 (the remediation
interrupt landed at 16:17:50, the abort fired 16:19:53).

Fix: when the declared route is not wired BUT the declared COMPONENT is
demonstrably rendered by some other wired route (element={<Component ...}),
accept the page as wired-with-drift — the app is the authority on where its
screens live. A genuinely absent route (component rendered nowhere) still
flags.
"""
import sys
import tempfile
import unittest
from pathlib import Path

AGENT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AGENT / "env_generator" / "llm_generator"))

from multi_agent.runtime.frontend_audit import audit_ui_page  # noqa: E402


_MESSAGES_PAGE = (
    "import MessageItem from '../components/MessageItem';\n"
    "export default function MessagesPage(){\n"
    "  const load = () => fetch('/api/messages');\n"
    "  return <div onClick={load}><MessageItem/></div>;\n"
    "}\n"
)


def _scaffold(tmp, app_jsx, extra_files=None):
    src = Path(tmp) / "frontend" / "src"
    (src / "pages").mkdir(parents=True, exist_ok=True)
    (src / "App.jsx").write_text(app_jsx, encoding="utf-8")
    for rel, content in (extra_files or {}).items():
        p = src / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    return src


class RouteDriftTests(unittest.TestCase):
    def test_component_wired_at_other_route_not_flagged(self):
        # declared /messages; implemented at /direct — the run-69 shape
        app = ('<Route path="/direct" element={<MessagesPage />} />')
        with tempfile.TemporaryDirectory() as tmp:
            src = _scaffold(tmp, app, {
                "pages/MessagesPage.jsx": _MESSAGES_PAGE,
                "components/MessageItem.jsx": "export default () => <li/>;\n"})
            _ok, missing = audit_ui_page(src, {
                "name": "messages_page", "component": "MessagesPage",
                "route": "/messages", "apis_used": []})
            self.assertFalse(
                [m for m in missing if "not wired" in m],
                f"route drift must not flag unwired: {missing}")

    def test_component_rendered_nowhere_still_flags(self):
        app = ('<Route path="/" element={<HomePage />} />')
        with tempfile.TemporaryDirectory() as tmp:
            src = _scaffold(tmp, app, {
                "pages/MessagesPage.jsx": _MESSAGES_PAGE,
                "pages/HomePage.jsx": "export default () => <div/>;\n"})
            _ok, missing = audit_ui_page(src, {
                "name": "messages_page", "component": "MessagesPage",
                "route": "/messages", "apis_used": []})
            self.assertTrue(
                [m for m in missing if "not wired" in m],
                f"genuinely unrouted page must still flag: {missing}")

    def test_exact_route_still_passes(self):
        app = ('<Route path="/messages" element={<MessagesPage />} />')
        with tempfile.TemporaryDirectory() as tmp:
            src = _scaffold(tmp, app, {
                "pages/MessagesPage.jsx": _MESSAGES_PAGE,
                "components/MessageItem.jsx": "export default () => <li/>;\n"})
            _ok, missing = audit_ui_page(src, {
                "name": "messages_page", "component": "MessagesPage",
                "route": "/messages", "apis_used": []})
            self.assertFalse([m for m in missing if "not wired" in m], missing)


if __name__ == "__main__":
    unittest.main()
