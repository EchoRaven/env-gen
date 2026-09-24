r"""#1202ei: the agent is told a control errored, not what the error was.

`evaluate_control` can classify a control's effect as "console_error" -- clicking it made
the page log one. `exercise_controls` captured that message and puts it on the record:

    "console_errors": list(console_errs)[:3],

and `BrowserExerciseControlsTool` then builds the agent-facing projection by picking
fields, with `console_errors` not among them. So the text reached nothing: inside
control_exercise it is read exactly once, at

    if record.get("console_errors"):   ->  return "console_error"

as a BOOLEAN, to choose the very label that withholds it. The comment above the
projection says it exists "so the agent can judge sound-but-ambiguous ones" -- and a
control whose only symptom is a console error is precisely the ambiguous case.

Same shape as #973 / #978 / #1202df / #1202ea / #1202ee: the framework holds the
actionable fact and reports its category.
"""
import sys
from pathlib import Path

import pytest

THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS_DIR.parent / "env_generator" / "llm_generator"))

GEN = THIS_DIR.parent / "env_generator" / "llm_generator"
AUDIT = (GEN / "tools" / "browser" / "control_audit.py").read_text(encoding="utf-8")
EXERCISE = (GEN / "multi_agent" / "runtime" / "control_exercise.py").read_text(encoding="utf-8")


def _projection():
    i = AUDIT.index('report["records"] = [')
    return AUDIT[i:AUDIT.index("return ToolResult.ok(report)", i)]


def test_the_message_reaches_the_agent():
    assert '"console_errors"' in _projection()


def test_the_other_fields_are_untouched():
    """Additive only -- nothing an existing reader depends on may move."""
    proj = _projection()
    for f in ("label", "effect", "navigated_to", "network", "off_contract", "dom_changed"):
        assert f'"{f}"' in proj


def test_a_control_with_no_errors_reports_an_empty_list():
    """A missing key and a null read differently downstream; neither is 'no errors'."""
    assert 'r.get("console_errors") or []' in _projection()


def test_the_effect_label_still_exists_to_be_explained():
    """If this classification went away the fix would be pointless."""
    assert '"console_error"' in EXERCISE
    assert 'if record.get("console_errors"):' in EXERCISE


def test_the_source_record_really_carries_the_text():
    """The premise: the message was captured and available at the boundary."""
    assert '"console_errors": list(console_errs)' in EXERCISE
