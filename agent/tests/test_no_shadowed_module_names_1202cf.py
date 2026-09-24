"""#1202cf — a module-level name is defined exactly once.

Found the hard way. #1202cb added a regex it called `_LOCAL_DEFAULT_IMPORT`, a name that
already existed 28 lines above it in the same file. Python takes the second binding
silently, so `scaffold_missing_local_pages` — which unpacks
`for name, rel in _LOCAL_DEFAULT_IMPORT.findall(text)` — began receiving a pattern with a
third capture group, and every dangling-page stub stopped being scaffolded. Six tests failed
in three files, none of them near the edit, and the traceback pointed at a missing .jsx
rather than at the shadow.

Nothing about that failure announced itself as a name collision, which is what makes it
worth a ratchet: the framework has ZERO of these today, so any new one is a regression.

LOCAL-ONLY (agent/tests/ gitignored).
"""

import ast
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

# Shipped INTO a generated environment and run against a live service there, not framework
# logic — excluded for the same reason the lint and ghost-tool ratchets exclude it.
_SKIP = ("/tests/", "__pycache__", "bundled_tests")


def _module_level_duplicates(path: Path):
    """Names bound more than once at module TOP LEVEL. Bindings inside `if`, `try` or a
    function are deliberate fallbacks (import-shape safety, platform branches) and are not
    counted — only the flat, unconditional kind that silently wins."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return {}
    seen = defaultdict(list)
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    seen[t.id].append(node.lineno)
    return {n: ls for n, ls in seen.items() if len(ls) > 1}


def _framework_files():
    for f in sorted(LLM.rglob("*.py")):
        if any(s in str(f) for s in _SKIP):
            continue
        yield f


def test_no_module_level_name_is_bound_twice():
    offenders = []
    for f in _framework_files():
        for name, lines in _module_level_duplicates(f).items():
            offenders.append(f"{f.relative_to(LLM)}:{lines} — {name}")
    assert not offenders, (
        "a module-level name is bound twice; the second binding wins silently and every "
        "reader of the first one changes behaviour with nothing logged:\n  "
        + "\n  ".join(offenders))


def test_the_detector_finds_a_planted_shadow(tmp_path):
    """#947-style: prove the scan reaches an artifact before trusting a zero from it. A
    detector that silently matches nothing reads exactly like a clean codebase."""
    f = tmp_path / "m.py"
    f.write_text("import re\nA = re.compile('x')\nB = 1\nA = re.compile('y')\n",
                 encoding="utf-8")
    assert _module_level_duplicates(f) == {"A": [2, 4]}


def test_the_detector_ignores_conditional_fallbacks(tmp_path):
    """The shape this must NOT flag: a try/except ImportError fallback binds the same name
    on purpose, and the framework uses that idiom throughout."""
    f = tmp_path / "m.py"
    f.write_text("try:\n    from x import Y\nexcept Exception:\n    Y = None\n",
                 encoding="utf-8")
    assert _module_level_duplicates(f) == {}


def test_the_scan_actually_covers_the_framework():
    """A path typo would make every assertion above pass over nothing."""
    files = list(_framework_files())
    assert len(files) > 200, len(files)
    assert any(f.name == "frontend_scaffold.py" for f in files)
