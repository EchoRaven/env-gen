"""#1202fx -- a hand-built validation-record fixture must not carry a key the producers
never emit.

This is the guard for the mistake that produced #1202fu, not for #1202fu itself. My fixture
carried BOTH `recorded_at` and `updated_at`; `_ts757` read `updated_at`, which the fixture
supplied and production never does, so the test passed against code that returned 0.0 for
every real record. The offline measurement said 1 failing record while the live run said 6,
and only the live run could tell me which was true.

A fixture the producer would never emit tests a world that does not exist. This scans the
test tree for dicts that are clearly validation records and fails on any key outside what
the two normalizers actually produce — so the next such fixture fails here, at no cost,
instead of in a paid run.
"""
import ast
import unittest
from pathlib import Path

TESTS = Path(__file__).resolve().parent
MA = TESTS.parent / "env_generator" / "llm_generator" / "multi_agent"

# Keys the two producers emit, read from the producers themselves rather than restated.
def _producer_keys() -> set:
    keys = set()

    def _collect(path: Path, *, func=None, near=None):
        src = path.read_text(encoding="utf-8")
        tree = ast.parse(src)
        if func:
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef) and node.name == func:
                    for n in ast.walk(node):
                        if isinstance(n, ast.Dict):
                            for k in n.keys:
                                if isinstance(k, ast.Constant) and isinstance(k.value, str):
                                    keys.add(k.value)
            return
        line = src[:src.index(near)].count("\n") + 1
        for n in ast.walk(tree):
            if isinstance(n, ast.Dict) and line - 12 <= n.lineno <= line + 12:
                for k in n.keys:
                    if isinstance(k, ast.Constant) and isinstance(k.value, str):
                        keys.add(k.value)

    _collect(MA / "runtime" / "hub_registry.py", func="get_validation_results")
    _collect(MA / "orchestrator.py", near='"recorded_at": c.get("updated_at", 0),')
    return keys


# A fixture may legitimately add fields a CONSUMER invents downstream, or fields that
# belong to the raw CodeHub check a test also builds. Only flag the ones that actively
# mislead: a second spelling of something a producer already emits under another name.
_MISLEADING = {"updated_at", "_updated_at", "created_at", "at", "timestamp", "ts"}


def _is_validation_record(node: ast.Dict) -> bool:
    """A dict literal is a validation record if it names the record's own identity keys."""
    keys = {k.value for k in node.keys
            if isinstance(k, ast.Constant) and isinstance(k.value, str)}
    return {"status", "metadata"} <= keys and ("name" in keys or "task_id" in keys)


class ValidationFixturesAreRealistic(unittest.TestCase):
    def test_no_fixture_carries_a_key_the_producers_do_not_emit(self):
        produced = _producer_keys()
        self.assertIn("recorded_at", produced, "producer scan failed — the guard is blind")
        offenders = []
        for path in sorted(TESTS.glob("*.py")):
            if path.name == Path(__file__).name:
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if not isinstance(node, ast.Dict) or not _is_validation_record(node):
                    continue
                for k in node.keys:
                    if (isinstance(k, ast.Constant) and k.value in _MISLEADING
                            and k.value not in produced):
                        offenders.append(f"{path.name}:{node.lineno}: {k.value!r}")
        if offenders:
            self.fail(
                "\n=== a validation-record fixture carries a key production never has ===\n"
                "The producers emit: " + ", ".join(sorted(produced)) + "\n"
                "A fixture that supplies another spelling lets a consumer reading the wrong\n"
                "field pass here and return 0.0 on every real record (#1202fu).\n"
                + "\n".join("  " + o for o in offenders))


if __name__ == "__main__":
    unittest.main()
