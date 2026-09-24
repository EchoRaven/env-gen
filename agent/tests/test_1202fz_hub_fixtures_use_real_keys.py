"""#1202fz -- extend #1202fx's fixture guard from validation records to every hub record
type, and pin the two-spelling split that #1202fy walked into.

#1202fx guarded validation records only, which would not have caught #1202fy: WorkHub tasks
write `_updated_at`, and `_bug_reference_time_1023` read `updated_at` — a key that appears
on 0 of 542 tasks. The split is real and system-wide:

    workhub_tasks / registryhub_ui_pages / registryhub_endpoints / workhub_documents
        -> `_updated_at`, `_updated_by`
    codehub_checks
        -> `updated_at`

Two spellings of the same idea in one system, on records that otherwise look alike. This
test does two things: it pins that split so a reader can look it up instead of guessing,
and it fails any test fixture that hands a record type a spelling its producer never writes
(none do today — this is prevention, and it found none precisely because the audit that
produced #1202fy cleaned the live ones first).
"""
import ast
import unittest
from pathlib import Path

TESTS = Path(__file__).resolve().parent
MA = TESTS.parent / "env_generator" / "llm_generator" / "multi_agent"

# Identity keys that mark a dict literal as a record of this type, and the writer that
# stamps its last modification. Read from the producers, not restated from a ledger, so
# this keeps holding on a machine with no generated/ tree.
TYPES = {
    "workhub task": ({"status", "assignee"}, "_updated_at"),
    "registryhub ui_page": ({"route", "component"}, "_updated_at"),
    "registryhub endpoint": ({"method", "path", "provider"}, "_updated_at"),
}
_WRONG_FOR_UNDERSCORE_STORES = {"updated_at", "updated_by"}


def _producer_writes(rel: str, key: str) -> bool:
    src = (MA / rel).read_text(encoding="utf-8")
    return f'"{key}"' in src


class TheTwoSpellingsAreWhatTheProducersWrite(unittest.TestCase):
    def test_hub_records_are_stamped_with_the_underscore_spelling(self):
        for rel in ("runtime/registryhub.py", "runtime/hubs/workhub/service.py"):
            p = MA / rel
            if not p.is_file():
                continue
            self.assertTrue(
                _producer_writes(rel, "_updated_at"),
                f"{rel} no longer stamps _updated_at — the split this pins has moved")

    def test_codehub_checks_keep_the_bare_spelling(self):
        self.assertTrue(
            _producer_writes("runtime/hubs/codehub/service.py", "updated_at"),
            "CodeHub checks no longer carry updated_at — #1202fu's reader depends on it")

    def test_the_task_reference_time_reads_the_spelling_tasks_actually_have(self):
        """#1202fy in one assertion."""
        import sys
        sys.path.insert(0, str(TESTS.parent))
        sys.path.insert(0, str(TESTS.parent / "env_generator" / "llm_generator"))
        from multi_agent.runtime.delivery_gate import _bug_reference_time_1023
        self.assertEqual(_bug_reference_time_1023({"_updated_at": 500.0}), 500.0)


class FixturesUseTheSpellingTheirProducerWrites(unittest.TestCase):
    def test_no_fixture_stamps_a_hub_record_with_the_bare_spelling(self):
        offenders = []
        for path in sorted(TESTS.glob("*.py")):
            if path.name == Path(__file__).name:
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if not isinstance(node, ast.Dict):
                    continue
                keys = {k.value for k in node.keys
                        if isinstance(k, ast.Constant) and isinstance(k.value, str)}
                for label, (identity, _stamp) in TYPES.items():
                    if identity <= keys and (keys & _WRONG_FOR_UNDERSCORE_STORES):
                        offenders.append(
                            f"{path.name}:{node.lineno}: a {label} fixture carries "
                            f"{sorted(keys & _WRONG_FOR_UNDERSCORE_STORES)}")
        if offenders:
            self.fail(
                "\n=== a hub-record fixture uses a spelling its producer never writes ===\n"
                "These stores stamp `_updated_at` / `_updated_by`; only codehub_checks use\n"
                "the bare form. A fixture that supplies the bare one lets a consumer reading\n"
                "the wrong field pass here and read nothing in production (#1202fy).\n"
                + "\n".join("  " + o for o in offenders))


if __name__ == "__main__":
    unittest.main()
