"""Auth pages project a REAL functional login/register form (youtube run #20):
the kickoff-derived login_page had no apis_used → fell to the inert <h2>Login</h2>
stub → the test-user signup/login walkthrough found no submit button → shipped a
login UI a user can't use. The framework universally owns /auth/login + /auth/register,
so any login/signup page must project a working email+password+submit form.

LOCAL-ONLY (agent/tests/ gitignored).
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for p in (str(ROOT), str(LLM_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

import tempfile  # noqa: E402

from multi_agent.runtime.frontend_scaffold import (  # noqa: E402
    _project_page_component, _is_auth_page, _is_register_mode,
    _ensure_framework_auth_pages, scaffold_pages_from_contract)
from multi_agent.runtime.kickoff.run_kickoff import (  # noqa: E402
    derive_frontend_pages_from_endpoints)


class AuthPageProjectionTests(unittest.TestCase):
    def test_detects_auth_pages(self):
        self.assertTrue(_is_auth_page("LoginPage", {"route": "/login"}))
        self.assertTrue(_is_auth_page("SignupPage", {"route": "/signup"}))
        self.assertTrue(_is_auth_page("X", {"id": "login_page"}))
        self.assertTrue(_is_auth_page("MyLoginScreen", {}))
        self.assertFalse(_is_auth_page("VideosPage", {"route": "/videos"}))
        self.assertFalse(_is_auth_page("HomePage", {"route": "/"}))

    def test_login_page_is_functional_form(self):
        src = _project_page_component("LoginPage", {"route": "/login", "id": "login_page"})
        self.assertIn("/auth/login", src)
        self.assertIn("/auth/register", src)
        self.assertIn('type="submit"', src)
        self.assertIn('type="email"', src)
        self.assertIn('type="password"', src)
        self.assertIn("onSubmit", src)
        self.assertIn("access_token", src)
        self.assertIn("useState(false)", src)  # login mode

    def test_signup_page_register_mode(self):
        src = _project_page_component("SignupPage", {"route": "/signup", "id": "signup_page"})
        self.assertIn("useState(true)", src)  # register mode
        self.assertIn("/auth/register", src)
        self.assertIn('type="submit"', src)

    def test_register_mode_detection(self):
        self.assertTrue(_is_register_mode("SignupPage", {"route": "/signup"}))
        self.assertFalse(_is_register_mode("LoginPage", {"route": "/login"}))

    def test_non_auth_page_unchanged(self):
        src = _project_page_component("VideosPage", {"route": "/videos",
                                                     "apis_used": ["GET /api/videos"]})
        self.assertNotIn("/auth/login", src)
        self.assertIn("fetch(", src)  # still the data template

    def test_derive_includes_login_and_signup(self):
        pages = derive_frontend_pages_from_endpoints([])
        routes = {p["route"] for p in pages}
        self.assertIn("/login", routes)
        self.assertIn("/signup", routes)
        # both are detected as auth pages → functional forms
        for p in pages:
            if p["route"] in ("/login", "/signup"):
                self.assertTrue(_is_auth_page(p["component"], p))


class FrameworkOwnsAuthTests(unittest.TestCase):
    def test_ensure_drops_lane_auth_pages_and_adds_both(self):
        out = _ensure_framework_auth_pages(
            [{"route": "/login", "component": "MyBrokenLogin"},
             {"route": "/videos", "component": "VideosPage"}])
        routes = [p["route"] for p in out]
        self.assertEqual(routes[:2], ["/login", "/signup"])  # framework auth first
        self.assertIn("/videos", routes)
        # the lane's /login page was dropped (framework LoginPage wins the route)
        login = next(p for p in out if p["route"] == "/login")
        self.assertEqual(login["component"], "LoginPage")

    def _lane_frontend(self):
        d = Path(tempfile.mkdtemp())
        src = d / "src"
        (src / "pages").mkdir(parents=True)
        # lane shipped a BROKEN login (no form) + a real videos page, no /signup
        (src / "pages" / "LoginPage.jsx").write_text(
            "export default function LoginPage(){return <div>broken</div>}")
        (src / "pages" / "VideosPage.jsx").write_text(
            "export default function VideosPage(){return null}")
        (src / "App.jsx").write_text(
            "import LoginPage from './pages/LoginPage.jsx';\n"
            "import VideosPage from './pages/VideosPage.jsx';\n"
            "export default function App(){return (<BrowserRouter><Routes>"
            "<Route path='/login' element={<LoginPage/>}/>"
            "<Route path='/videos' element={<VideosPage/>}/>"
            "</Routes></BrowserRouter>)}")
        return d, src

    def test_broken_lane_login_is_overwritten_functional(self):
        d, src = self._lane_frontend()
        scaffold_pages_from_contract(d, [
            {"id": "videos_page", "route": "/videos", "component": "VideosPage"},
            {"id": "login_page", "route": "/login", "component": "LoginPage"}])
        lp = (src / "pages" / "LoginPage.jsx").read_text()
        self.assertIn("/auth/login", lp)
        self.assertIn('type="submit"', lp)

    def test_signup_page_and_route_injected(self):
        d, src = self._lane_frontend()
        scaffold_pages_from_contract(d, [
            {"id": "login_page", "route": "/login", "component": "LoginPage"}])
        self.assertTrue((src / "pages" / "SignupPage.jsx").exists())
        self.assertIn("/signup", (src / "App.jsx").read_text())

    def test_real_lane_page_not_clobbered(self):
        # a NON-auth page the lane wrote is preserved
        d, src = self._lane_frontend()
        (src / "pages" / "VideosPage.jsx").write_text(
            "export default function VideosPage(){return <div>RICH LANE UI</div>}")
        scaffold_pages_from_contract(d, [
            {"id": "videos_page", "route": "/videos", "component": "VideosPage"}])
        self.assertIn("RICH LANE UI", (src / "pages" / "VideosPage.jsx").read_text())


if __name__ == "__main__":
    unittest.main()
