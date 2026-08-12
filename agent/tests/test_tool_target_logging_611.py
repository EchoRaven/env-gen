r"""#611: the log recorded that a tool was called, never WHAT it was called on.

The fallback branch of `_log_tool_details` printed `args=['method','url']` — the argument KEYS
only. Of the ten highest-volume tools in the arc, **nine** land in that fallback:
`workhub_task`, `workhub_get_task`, `workhub_add_meeting_decision`, `list_generated_files`,
`test_api`, `workhub_list_documents`, `workhub_get_document`, `workhub_cancel_task` (only
`check_inbox` and `read` have bespoke branches).

Not cosmetic — it blocked two analyses in the session that found #604–#610:

  * does an agent re-fetch the SAME task? `workhub_get_task` is 5.80M tokens over 427 calls and
    the log never records a task_id.
  * does an agent re-hit the SAME tokenless endpoint after being told not to? The "requires
    AUTH, a tokenless request is SUPPOSED to be rejected" hint fires **535 times** arc-wide and
    nothing records which endpoint.

It is also, mechanically, part of the answer to "why can't the framework's own agents root-cause
their own runs" — the artifact does not say what was touched.

Costs nothing the model sees: this is a log line, not context. Values are truncated, and
credential-shaped keys are redacted because the log lands on disk.
"""
import inspect
import re

import pytest

from env_generator.llm_generator.multi_agent.agents.runtime import tooling as t


class _Log:
    def __init__(self):
        self.lines = []

    def info(self, msg, *a):
        self.lines.append(msg % a if a else msg)

    warning = error = debug = info


class _Agent(t.AgentTooling if hasattr(t, "AgentTooling") else object):
    def __init__(self):
        self.agent_id = "backend"
        self._logger = _Log()


def _log(tool, args):
    a = _Agent()
    t.AgentTooling._log_tool_details(a, tool, args)
    return a._logger.lines[-1]


# --- the target is now recorded -----------------------------------------------------------

def test_test_api_now_records_the_endpoint():
    line = _log("test_api", {"method": "GET", "url": "http://localhost:8000/api/my-list"})
    assert "method=GET" in line and "/api/my-list" in line


def test_a_hub_id_is_recorded():
    assert "task_id=task_37b7abe372" in _log("workhub_get_task", {"task_id": "task_37b7abe372"})
    assert "document_id=doc_1" in _log("workhub_get_document", {"document_id": "doc_1"})


def test_the_most_specific_key_wins_over_a_generic_name():
    line = _log("workhub_task", {"name": "generic", "task_id": "T1", "action": "complete"})
    assert line.index("task_id=T1") < line.index("action=complete") < line.index("name=generic")


def test_at_most_three_targets_are_logged():
    line = _log("x", {k: k for k in ("task_id", "document_id", "meeting_id", "url", "path")})
    assert len(re.findall(r"\w+=", line)) <= 3


# --- safety ----------------------------------------------------------------------------------

def test_credential_shaped_values_are_redacted():
    for k in ("password", "api_key", "auth_token", "secret", "cookie", "authorization"):
        line = _log("x", {k: "hunter2", "url": "/x"})
        assert "hunter2" not in line, k


def test_a_long_value_is_truncated():
    line = _log("x", {"url": "http://h/" + "y" * 500})
    assert len(line) < 400


def test_a_non_scalar_value_is_skipped_not_dumped():
    line = _log("x", {"path": {"deep": ["structure"] * 50}, "id": "keep"})
    assert "structure" not in line and "id=keep" in line


def test_a_tool_with_no_recognised_target_falls_back_to_the_old_behaviour():
    line = _log("mystery_tool", {"zzz": 1})
    assert "args=['zzz']" in line


def test_empty_values_are_not_logged_as_targets():
    line = _log("x", {"task_id": "", "url": None, "path": [], "id": "real"})
    assert "id=real" in line and "task_id=" not in line.replace("id=real", "")


# --- the bespoke branches are untouched ----------------------------------------------------------

def test_read_and_check_inbox_keep_their_own_lines():
    assert "READ:" in _log("read", {"file_path": "a.py"})
    assert "CHECK_INBOX" in _log("check_inbox", {"limit": 20})


def test_the_reason_it_matters_is_recorded_next_to_the_code():
    src = " ".join(inspect.getsource(t.AgentTooling._log_tool_details).replace("#", " ").split())
    assert "535 times" in src and "5.80M tokens over 427 calls" in src


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
