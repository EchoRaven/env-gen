"""PROPOSAL #13: backend route code-truth auditor (twin of frontend_audit).

Pins the BINDING include-chain scoping the reviewer required:
  * a route in main.py's @app surface OR in a module main.py include_router()s
    → flips defined→implemented;
  * the same decorator in an ORPHAN (never-included) module → stays defined;
  * multi-route-module backends (video_routes + channel_routes, run #18 shape)
    all resolve;
  * param-path + include prefix tolerance;
  * a registered endpoint with NO served handler regresses implemented→defined;
  * fixed-kind (auth/oauth/spine) endpoints are never touched.
"""

import sys
import tempfile
import unittest
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(AGENT_DIR))
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

from multi_agent.runtime.backend_audit import served_routes, sync_endpoint_statuses  # noqa: E402


class _FakeRegistry:
    """Minimal registryhub: get_endpoints + register_endpoint upsert (merges status)."""

    def __init__(self):
        self._eps = {}

    def seed(self, method, path, status, **md):
        self._eps[f"{method.upper()} {path}"] = {
            "method": method.upper(), "path": path, "status": status,
            "metadata": dict(md)}

    def get_endpoints(self):
        return {k: dict(v) for k, v in self._eps.items()}

    def register_endpoint(self, method, path, schema=None, provider="", agent="",
                          status="defined", **md):
        key = f"{method.upper()} {path}"
        old = self._eps.get(key, {})
        self._eps[key] = {**old, "method": method.upper(), "path": path,
                          "status": status or old.get("status") or "defined",
                          "metadata": {**(old.get("metadata") or {}), **md}}
        return self._eps[key]


def _mkbackend(files: dict) -> Path:
    proj = Path(tempfile.mkdtemp(prefix="bea_"))
    be = proj / "app" / "backend"
    be.mkdir(parents=True)
    for name, content in files.items():
        (be / name).write_text(content, encoding="utf-8")
    return proj


_MAIN = (
    "from fastapi import FastAPI\n"
    "from custom_routes import router as _c\n"
    "from oauth_routes import build_router\n"
    "app = FastAPI()\n"
    "@app.get('/api/videos')\n"
    "def v(): ...\n"
    "@app.get('/api/videos/{videoId}')\n"
    "def one(): ...\n"
    "app.include_router(build_router())\n"   # Call arg → skipped (AS router)
    "app.include_router(_c)\n"               # Name arg → custom_routes included
)
_CUSTOM = ("from fastapi import APIRouter\nrouter = APIRouter()\n"
           "@router.get('/api/studio/analytics')\ndef a(): ...\n")
_ORPHAN = ("from fastapi import APIRouter\nrouter = APIRouter()\n"
           "@router.get('/api/orphan')\ndef o(): ...\n")  # never include_router'd


class ServedRoutesTests(unittest.TestCase):
    def test_main_routes_included_module_and_orphan_exclusion(self):
        proj = _mkbackend({"main.py": _MAIN, "custom_routes.py": _CUSTOM,
                           "append_routes.py": _ORPHAN, "oauth_routes.py": "def build_router(): ...\n"})
        served = served_routes(proj / "app" / "backend")
        self.assertIn(("GET", "/api/videos"), served)            # main @app
        self.assertIn(("GET", "/api/videos/{}"), served)         # param-normalized
        self.assertIn(("GET", "/api/studio/analytics"), served)  # included module
        self.assertNotIn(("GET", "/api/orphan"), served)         # ORPHAN excluded

    def test_multi_route_modules_all_resolve(self):
        # run #18 shape: video_routes + channel_routes both included.
        main = ("from fastapi import FastAPI\n"
                "from video_routes import router as vr\n"
                "from channel_routes import router as cr\n"
                "app = FastAPI()\napp.include_router(vr)\napp.include_router(cr)\n")
        proj = _mkbackend({
            "main.py": main,
            "video_routes.py": "from fastapi import APIRouter\nrouter=APIRouter()\n@router.get('/api/videos/{id}')\ndef g(): ...\n",
            "channel_routes.py": "from fastapi import APIRouter\nrouter=APIRouter()\n@router.get('/api/channels/me')\ndef m(): ...\n",
        })
        served = served_routes(proj / "app" / "backend")
        self.assertIn(("GET", "/api/videos/{}"), served)
        self.assertIn(("GET", "/api/channels/me"), served)

    def test_include_router_prefix_applied(self):
        main = ("from fastapi import FastAPI\nfrom widgets import router as w\n"
                "app = FastAPI()\napp.include_router(w, prefix='/api')\n")
        proj = _mkbackend({"main.py": main,
                           "widgets.py": "from fastapi import APIRouter\nrouter=APIRouter()\n@router.get('/widgets')\ndef g(): ...\n"})
        served = served_routes(proj / "app" / "backend")
        self.assertIn(("GET", "/api/widgets"), served)


class SyncEndpointStatusesTests(unittest.TestCase):
    def _proj(self):
        return _mkbackend({"main.py": _MAIN, "custom_routes.py": _CUSTOM,
                           "append_routes.py": _ORPHAN, "oauth_routes.py": "def build_router(): ...\n"})

    def test_served_flip_to_implemented(self):
        proj = self._proj()
        reg = _FakeRegistry()
        reg.seed("GET", "/api/videos", "defined")
        reg.seed("GET", "/api/studio/analytics", "defined")   # in included custom_routes
        reg.seed("GET", "/api/videos/{vid}", "implementing")  # param-tolerant match to {videoId}
        out = sync_endpoint_statuses(proj, reg)
        eps = reg.get_endpoints()
        self.assertEqual(eps["GET /api/videos"]["status"], "implemented")
        self.assertEqual(eps["GET /api/studio/analytics"]["status"], "implemented")
        self.assertEqual(eps["GET /api/videos/{vid}"]["status"], "implemented")
        self.assertIn("GET /api/videos", out["implemented"])

    def test_unserved_regresses_and_orphan_stays_defined(self):
        proj = self._proj()
        reg = _FakeRegistry()
        reg.seed("POST", "/api/nonexistent", "implemented")  # no handler anywhere → regress
        reg.seed("GET", "/api/orphan", "defined")            # only in orphan module → stays defined
        out = sync_endpoint_statuses(proj, reg)
        eps = reg.get_endpoints()
        self.assertEqual(eps["POST /api/nonexistent"]["status"], "defined")  # regressed (the lie)
        self.assertEqual(eps["GET /api/orphan"]["status"], "defined")        # orphan never counts
        self.assertIn("POST /api/nonexistent", out["regressed"])
        self.assertIn("GET /api/orphan", out["pending"])

    def test_fixed_kind_endpoints_untouched(self):
        proj = self._proj()
        reg = _FakeRegistry()
        # an auth endpoint marked implemented but with no business route module handler
        # must NOT be regressed — it's the fixed AS surface.
        reg.seed("POST", "/auth/login", "implemented", kind="auth")
        sync_endpoint_statuses(proj, reg)
        self.assertEqual(reg.get_endpoints()["POST /auth/login"]["status"], "implemented")


if __name__ == "__main__":
    unittest.main()
