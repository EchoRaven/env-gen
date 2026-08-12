r"""#616: "MCP surface not built" is a timing verdict too — the pattern behind #614.

Auditing the last unexamined section of the test-user reports (`mcp`), 41 of 66 say
*"no mcp_server/ — MCP surface not built"*. For **9** of them the directory DOES exist on disk,
and in every one it was written **3 to 10 minutes AFTER the report**:

    r115 +6   r118 +6   r121 +5   r125 +7   r127 +6   r128 +10   r133 +6   r134 +3   r142 +7

The framework scaffolds it (`scaffolder.write_mcp_server`); the probe simply ran first. Together
with #614 — where `POST /api/continue-watching -> 405 missing` turned out to be `main.py` written
8 to 108 minutes after the report — this is no longer two coincidences but a PATTERN: **the test
user runs before the framework has finished scaffolding, and its "missing / not built" verdicts
go stale in the ledger without ever being re-evaluated.**

`server_found` stays False — the probe must never claim to have seen what it did not — but the
note no longer reads as a permanent gap.
"""
import inspect

import pytest

from env_generator.llm_generator.multi_agent.runtime import test_user_validation as v


@pytest.fixture(scope="module")
def src():
    return inspect.getsource(v._mcp_test_user)


def _emitted_note(src):
    """The string actually written into the report — not the comment that quotes the old one."""
    i = src.index('out["note"] = ("no mcp_server/')
    return src[i:src.index("return out", i)]


def test_the_note_no_longer_asserts_the_surface_was_never_built(src):
    assert "MCP surface not built" not in _emitted_note(src)


def test_the_note_is_scoped_to_this_moment(src):
    assert "AT THIS MOMENT" in _emitted_note(src)


def test_the_note_names_who_builds_it_and_what_to_do(src):
    note = _emitted_note(src)
    assert "write_mcp_server" in note
    assert "re-check the tree" in note


def test_server_found_stays_false(src):
    """The probe must not claim to have seen something it did not."""
    assert 'out["server_found"] = True' not in _emitted_note(src)


def test_the_other_branch_is_untouched(src):
    """`mcp_server/ present but no <env>/main.py` is a real structural finding, not timing."""
    assert "mcp_server/ present but no <env>/main.py" in src


def test_the_early_return_is_preserved(src):
    i = src.index('out["note"] = ("no mcp_server/')
    assert "return out" in src[i:i + 600]


def test_the_evidence_is_recorded(src):
    flat = " ".join(src.replace("#", " ").split())
    assert "3 to 10 minutes AFTER the report" in flat
    assert "r134 +3" in flat and "r128 +10" in flat


def test_it_cites_the_sibling_finding(src):
    assert "#614" in src


def test_the_timestamp_claim_is_backed_by_a_CONTROL(src):
    """Unlike `main.py`, the mcp_server mtime separates: newer in 9/9 of the "missing"
    cases and only 1/10 where the probe found it."""
    flat = " ".join(src.replace("#", " ").split())
    assert "9/9" in flat and "1/10" in flat
    assert "96% of runs regardless of verdict" in flat


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
