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

# --- #1203r3: DRIVE the probe ------------------------------------------------------------
#
# Every assertion above reads `inspect.getsource(v._mcp_test_user)`, and the text-assertion
# ratio put this file at 1.00 -- the highest in the corpus among guards over the three
# end-stage blocking modules. The function needs nothing but a directory: its signature is
# `_mcp_test_user(project_dir: Path, business_eps: list) -> dict`, so a tempdir drives it.
#
# One property its own docstring states is checked NOWHERE above: "`server_found` stays
# False -- the probe must not claim to have seen something it did not". A mutation that sets
# it True while leaving the note alone passes every source-text assertion in this file.
#
# And the branch where `mcp_server/` EXISTS but is incomplete has no coverage here at all.

import tempfile
from pathlib import Path


def _probe(make=None, eps=None):
    """Run the real probe against a fresh tree; `make` may create files inside it."""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        if make:
            make(root)
        return v._mcp_test_user(root, eps if eps is not None else
                                [{"path": "/api/items", "method": "GET"},
                                 {"path": "/api/items", "method": "POST"}])


def test_a_missing_server_is_reported_as_this_moment_not_as_never_built():
    out = _probe()
    assert "AT THIS MOMENT" in out["note"], out["note"]
    assert "MCP surface not built" not in out["note"], out["note"]


def test_the_probe_does_not_claim_to_have_seen_what_it_did_not():
    """The docstring's own rule, which no assertion above enforces."""
    out = _probe()
    assert out["server_found"] is False, out
    assert out["complete"] is False, out
    assert out["tools_found"] == 0, out


def test_the_expected_tool_count_follows_the_contract():
    assert _probe(eps=[])["tools_expected"] == 0
    assert _probe(eps=[{"path": "/a", "method": "GET"}])["tools_expected"] == 1
    assert _probe()["tools_expected"] == 2


def test_a_present_but_empty_server_is_a_different_verdict():
    """The second branch, which had no coverage at all: the directory exists, so the
    timing note would be a lie, and the probe must say what is actually missing."""
    out = _probe(make=lambda root: (root / "mcp_server").mkdir())
    assert "AT THIS MOMENT" not in out["note"], out["note"]
    assert "main.py" in out["note"], out["note"]
    assert out["server_found"] is False, out


def test_the_note_is_never_empty_when_something_is_wrong():
    for out in (_probe(), _probe(make=lambda root: (root / "mcp_server").mkdir())):
        assert out["note"].strip(), "a failing probe produced no note: %r" % out
