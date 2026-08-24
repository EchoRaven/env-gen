"""#1055 — importing the orchestrator by the name every test uses fails.

`tools/docker_tools.py` is imported as `tools.docker_tools` (its siblings all use
the short form: `from utils.tool import ...`, `from workspace import Workspace`).
Line 26 breaks that regime:

    from env_generator.llm_generator.multi_agent.runtime.container_runtime import runtime_bin

Under the short-path regime that ABSOLUTE path builds a SECOND copy of the whole
package tree, and initialising the second copy re-enters `tools.docker_tools`,
which is still executing line 26 — so `DockerRestartTool`, defined further down,
does not exist yet:

    ImportError: cannot import name 'DockerRestartTool' from partially
    initialized module 'tools.docker_tools' (most likely due to a circular import)

Measured 2026-08-24 — the split is exactly by import form, not by module:

    env_generator.llm_generator.multi_agent.orchestrator   OK   (production)
    multi_agent.orchestrator                               FAIL (every test)

so production is unaffected and the SUITE cannot import the orchestrator at all.
Eleven test files are dead on this, including the ones that cover the tool
allowlist, the prompt/tool grant guard, the commit gate, the deliver trigger and
the plateau escape — the gate and permission surfaces.

`container_runtime` imports nothing but stdlib, so the cycle is entirely the
package chain the absolute path drags in. `runtime_bin` is only ever CALLED
(`_rt936()`), never inspected at import time, so resolving it on first call
breaks the cycle and leaves all 9 call sites untouched.

This is the same dual-identity class as #638 and #1053, one level up: there the
same FILE was reachable under two module names; here the same PACKAGE is.
"""
from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"

_PROBE = """
import sys
sys.path.insert(0, {root!r})
sys.path.insert(0, {llm!r})
import importlib
importlib.import_module({mod!r})
print("OK")
"""


def _fresh_import(mod: str, *, paths=("both",)) -> tuple:
    """Import `mod` in a FRESH interpreter (module-level cycles cannot be
    observed in-process once the modules are cached). Returns (rc, output)."""
    src = _PROBE.format(root=str(ROOT), llm=str(LLM_DIR), mod=mod)
    p = subprocess.run([sys.executable, "-c", src], capture_output=True,
                       text=True, timeout=180, cwd=str(ROOT))
    return p.returncode, (p.stdout + p.stderr)


class TheShortFormImportsTheSuiteUses(unittest.TestCase):

    def test_tool_bundles(self):
        rc, out = _fresh_import("multi_agent.tool_bundles")
        self.assertEqual(rc, 0, out[-1500:])

    def test_docker_tools_directly(self):
        rc, out = _fresh_import("tools.docker_tools")
        self.assertEqual(rc, 0, out[-1500:])

    def test_orchestrator(self):
        rc, out = _fresh_import("multi_agent.orchestrator")
        self.assertEqual(rc, 0, out[-1500:])

    def test_tool_surface(self):
        rc, out = _fresh_import("multi_agent.tool_surface")
        self.assertEqual(rc, 0, out[-1500:])

    def test_configurable_agent(self):
        rc, out = _fresh_import("multi_agent.agents.configurable_agent")
        self.assertEqual(rc, 0, out[-1500:])

    def test_no_partially_initialized_module_anywhere(self):
        """Name the symptom so a future re-break is unmistakable."""
        for mod in ("multi_agent.orchestrator", "tools.docker_tools"):
            rc, out = _fresh_import(mod)
            self.assertNotIn("partially initialized", out, f"{mod}: {out[-800:]}")


class ProductionsAbsoluteFormKeepsWorking(unittest.TestCase):
    """The form the runtime actually uses must not regress."""

    def test_absolute_orchestrator_import(self):
        src = ("import sys\nsys.path.insert(0, %r)\nimport importlib\n"
               "importlib.import_module('env_generator.llm_generator.multi_agent.orchestrator')\n"
               "print('OK')\n" % str(ROOT))
        p = subprocess.run([sys.executable, "-c", src], capture_output=True,
                           text=True, timeout=180, cwd=str(ROOT))
        self.assertEqual(p.returncode, 0, (p.stdout + p.stderr)[-1500:])


class RuntimeBinStillResolves(unittest.TestCase):
    """Laziness must not change what the 9 call sites get."""

    def test_rt936_returns_the_same_binary_as_runtime_bin(self):
        src = ("import sys\nsys.path.insert(0, %r)\nsys.path.insert(0, %r)\n"
               "from tools.docker_tools import _rt936\n"
               "from multi_agent.runtime.container_runtime import runtime_bin\n"
               "assert _rt936() == runtime_bin(), (_rt936(), runtime_bin())\n"
               "print('OK')\n" % (str(ROOT), str(LLM_DIR)))
        p = subprocess.run([sys.executable, "-c", src], capture_output=True,
                           text=True, timeout=180, cwd=str(ROOT))
        self.assertEqual(p.returncode, 0, (p.stdout + p.stderr)[-1500:])


if __name__ == "__main__":
    unittest.main()
