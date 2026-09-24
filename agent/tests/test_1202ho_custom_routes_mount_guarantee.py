"""#1202ho — lanes invent a loader hook because nothing states the mount is guaranteed.

r105 shipped `app/backend/sitecustomize.py`, lane-authored, whose own docstring says why:

    "The projection framework owns main.py and may regenerate it without an explicit
     include_router(custom_routes.router) line. Python imports sitecustomize automatically
     at interpreter startup, so this hook applies the established extension point without
     editing framework-owned files."

The delivery gate then reported it as a dead artifact — correctly, since nothing imports it —
and the lane had no way to know it was redundant. `deliverability_dead_artifacts` blocked.

Measured over the 145 runs with a backend on this machine:

  * 5 of them carry a lane-authored `sitecustomize.py`, across TWO environments
    (netflix-local r16/r32/r38/r41, tiktok-web r105) — a recurring pattern, not one lane's
    quirk;
  * 22 main.py files lack `import custom_routes`, and every one of the 22 is the 1591-byte
    bootstrap stub with zero projected handlers. Among runs that reached skeleton generation
    the mount is present 123 times out of 123.

So the guarantee holds — and the lane's belief is still a reasonable inference, because a
lane that reads main.py BEFORE the skeleton runs sees exactly the stub, with no import. What
is missing is anyone saying so. The framework notice names `custom_routes.py` as the lane's
file and stops there.
"""
import sys
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(_ROOT), str(_ROOT / "env_generator" / "llm_generator")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from multi_agent.runtime.backend_skeleton import render_skeleton_main
from multi_agent.runtime.framework_notice import build_message

_TABLES = {"users": {"name": "users", "schema": {"columns": [
    {"name": "id", "type": "integer", "primary_key": True},
    {"name": "email", "type": "text"}]}}}


class TheGuaranteeItself(unittest.TestCase):
    def test_the_skeleton_always_mounts_custom_routes(self):
        """The claim the notice is about to make must be true by construction, including for
        a contract with no business endpoints at all."""
        for eps in ([], [{"method": "GET", "path": "/api/users", "schema": {}}]):
            src = render_skeleton_main(eps, _TABLES)
            self.assertIn("import custom_routes", src, eps)


class TheNoticeStatesIt(unittest.TestCase):
    def _backend_messages(self):
        return [build_message(kind, "backend", ["app/backend/main.py"])
                for kind in ("conflict_resolved", "framework_scaffolded")]

    def test_every_backend_message_says_the_file_is_loaded_for_you(self):
        for msg in self._backend_messages():
            self.assertIn("custom_routes", msg)
            low = msg.lower()
            self.assertTrue("import" in low or "mount" in low or "load" in low,
                            "the message names the file but never says it is loaded: " + msg)
            self.assertIn("hook", low,
                          "nothing tells the lane a loader hook is unnecessary: " + msg)

    def test_the_frontend_message_is_unchanged_by_this(self):
        """The guarantee is backend-specific; the frontend lane must not be told about a
        Python import mechanism that means nothing to it."""
        msg = build_message("framework_scaffolded", "frontend", ["src/App.jsx"])
        self.assertNotIn("custom_routes", msg)
        self.assertNotIn("sitecustomize", msg)


if __name__ == "__main__":
    unittest.main()
