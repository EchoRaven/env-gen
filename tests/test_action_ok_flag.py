"""Guard: hub_reader threads the authoritative tool-success `ok` flag to the UI.

The Env Forge agent drawer used to derive ✓/✗ from a substring heuristic on the
result text, so a PASSING lint (whose data is {"errors": [], ...}) rendered as a
red ✗. The engine now persists `metadata.ok`; this pins that _parse_action_entry
surfaces it (and stays None for pre-flag logs so the UI can fall back).
"""

from app.hub_reader import _parse_action_entry

_LINT_OK = "{'errors': [], 'tool': 'ruff', 'message': 'Python lint OK: custom_routes.py'}"


def _entry(metadata):
    return {"timestamp": "2026-06-16T16:52:55", "event_type": "tool_call",
            "content": "lint({'path': 'app/backend/custom_routes.py'})",
            "metadata": metadata}


def test_passing_lint_is_ok_true_despite_errors_substring():
    a = _parse_action_entry(_entry({"result": _LINT_OK, "ok": True}))
    assert a["ok"] is True
    assert a["tool"] == "lint"
    assert "errors" in a["result"]   # the misleading substring remains in the text…
    assert a["ok"] is True           # …but the authoritative flag is the truth the UI uses.


def test_failure_is_ok_false():
    a = _parse_action_entry(_entry({"result": "Error: path not found", "ok": False}))
    assert a["ok"] is False


def test_old_log_without_ok_is_none():
    # Pre-flag logs carry no `ok`; reader returns None so the UI falls back to its heuristic.
    a = _parse_action_entry(_entry({"result": _LINT_OK}))
    assert a["ok"] is None


def test_string_metadata_has_no_ok():
    e = _entry("plain text result")  # metadata as a bare string (old shape)
    a = _parse_action_entry(e)
    assert a["ok"] is None
