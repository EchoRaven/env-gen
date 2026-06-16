"""Tool NAMEs must be unique across the tools/ package (Cutover 18)."""

import importlib
import pkgutil
import sys
import unittest
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
AGENT_DIR = THIS_DIR.parent
sys.path.insert(0, str(AGENT_DIR))
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))


class NoDuplicateToolNamesTests(unittest.TestCase):
    def test_no_two_modules_define_the_same_tool_name(self) -> None:
        import tools
        seen: dict = {}  # NAME -> first module path
        for _, modname, _ in pkgutil.iter_modules(tools.__path__):
            if modname.startswith("_"):
                continue
            try:
                mod = importlib.import_module(f"tools.{modname}")
            except Exception:
                continue
            for attr in dir(mod):
                obj = getattr(mod, attr)
                if not isinstance(obj, type):
                    continue
                name = getattr(obj, "NAME", None)
                if not isinstance(name, str) or not name:
                    continue
                # Ignore tool re-exports (class defined elsewhere)
                if obj.__module__ != f"tools.{modname}":
                    continue
                if name in seen and seen[name] != mod.__name__:
                    self.fail(f"duplicate tool NAME {name!r} in "
                              f"{seen[name]} and {mod.__name__}")
                seen.setdefault(name, mod.__name__)


if __name__ == "__main__":
    unittest.main()
