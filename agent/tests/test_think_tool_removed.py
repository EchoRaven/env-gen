"""Absence-pin: the redundant custom `think` tool is gone (native model reasoning replaces it)."""
import glob
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]  # agent/
SRC = ROOT / "env_generator" / "llm_generator"
for p in (str(ROOT), str(SRC)):
    if p not in sys.path:
        sys.path.insert(0, p)


def test_no_thinktool_symbol_in_tools_package():
    import tools as tools_pkg
    assert not hasattr(tools_pkg, "ThinkTool")
    import tools.reasoning_tools as rt
    assert not hasattr(rt, "ThinkTool")


def test_think_not_referenced_in_v3_prompts():
    bad = []
    for f in glob.glob(str(SRC / "multi_agent" / "prompts" / "v3" / "*.j2")):
        txt = Path(f).read_text()
        if "think(" in txt or '"think"' in txt or "'think'" in txt:
            bad.append(Path(f).name)
    assert bad == [], f"stale think tool refs remain in v3 prompts: {bad}"
