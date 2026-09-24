"""#1202gh — a stand-in that binds a production method must provide what that method reads.

#1202fw shipped dead with SEVEN passing tests. Its stand-in defined `self.logger`; the
Orchestrator's attribute is `self._logger` (144 uses to that one typo). The bound method
raised AttributeError on every real call, its own guard swallowed-and-announced it, and the
tests went on passing because the stand-in supplied exactly the attribute production lacks.

That is the third time this session the same trap has fired: a fixture the producer would
never emit (#1202fu), a hub record with a spelling no store writes (#1202fz), and now a
stand-in object with an attribute the real class does not have. #1202fx and #1202fz guard
the first two shapes; this guards the third.

The rule is narrow on purpose: it only looks at classes that BIND a real production method
(`_m = Module.Class.method`), and only at plain `self.<name>` reads inside that method. A
stand-in is free to add whatever else it likes.
"""
import ast
import re
import sys
import unittest
from pathlib import Path

TESTS = Path(__file__).resolve().parent
REPO = TESTS.parent / "env_generator" / "llm_generator"
sys.path.insert(0, str(TESTS.parent))
sys.path.insert(0, str(REPO))


def _bound_methods(tree):
    """{class_name: [(module_alias, cls, method), ...]} for `x = Mod.Cls.method` bindings."""
    out = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        for stmt in node.body:
            if not (isinstance(stmt, ast.Assign) and isinstance(stmt.value, ast.Attribute)):
                continue
            v = stmt.value
            if not isinstance(v.value, ast.Attribute) or not isinstance(v.value.value, ast.Name):
                continue
            out.setdefault(node.name, []).append(
                (v.value.value.id, v.value.attr, v.attr, node))
    return out


def _self_reads(fn_src: str) -> set:
    """Plain `self.<name>` reads, excluding ones the method assigns itself."""
    reads = set(re.findall(r"\bself\.([A-Za-z_][A-Za-z0-9_]*)", fn_src))
    writes = set(re.findall(r"\bself\.([A-Za-z_][A-Za-z0-9_]*)\s*=(?!=)", fn_src))
    return reads - writes


def _provided(cls_node: ast.ClassDef) -> set:
    names = set()
    for node in ast.walk(cls_node):
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) \
                and node.value.id == "self":
            names.add(node.attr)
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    names.add(t.id)
    # A stand-in usually supplies behaviour as a METHOD (`def _lane_time_1202fk(...)`),
    # not an attribute assignment — the first draft of this detector missed those and
    # flagged a correct stand-in. Validate the detector on the known case before trusting
    # a finding: it must report nothing for #1202fw's own (now-correct) fixture.
    for stmt in cls_node.body:
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
            names.add(stmt.name)
    return names


class StandInsMatchTheRealClass(unittest.TestCase):
    def test_a_bound_method_finds_the_attributes_it_reads(self):
        import importlib
        offenders = []
        for path in sorted(TESTS.glob("test_*.py")):
            if path.name == Path(__file__).name:
                continue
            try:
                src = path.read_text(encoding="utf-8")
                tree = ast.parse(src)
            except Exception:
                continue
            aliases = {}
            for n in ast.walk(tree):
                if isinstance(n, ast.ImportFrom) and n.module:
                    for a in n.names:
                        aliases[a.asname or a.name] = f"{n.module}.{a.name}"
            for _cls, binds in _bound_methods(tree).items():
                for mod_alias, real_cls, method, cls_node in binds:
                    target = aliases.get(mod_alias)
                    if not target:
                        continue
                    try:
                        mod = importlib.import_module(target)
                        fn = getattr(getattr(mod, real_cls), method)
                        import inspect
                        need = _self_reads(inspect.getsource(fn))
                    except Exception:
                        continue
                    have = _provided(cls_node)
                    missing = sorted(n for n in need - have if not n.startswith("__"))
                    if missing:
                        offenders.append(
                            f"{path.name}:{cls_node.lineno} {cls_node.name} binds "
                            f"{real_cls}.{method} but never provides {missing}")
        if offenders:
            self.fail(
                "\n=== a stand-in is missing what the bound method reads ===\n"
                "The method will raise AttributeError on every real call; a guarded caller\n"
                "turns that into a mechanism that silently never runs (#1202fw shipped that\n"
                "way with seven passing tests).\n" + "\n".join("  " + o for o in offenders))


if __name__ == "__main__":
    unittest.main()
