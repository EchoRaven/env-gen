"""#1121: agents address coordination documents by NAME; the tool only knew ids.

Measured over the 85-run corpus: 235 `workhub_get_document` failures across 31 runs
(36%), and the id handed over is a friendly name far more often than a typo —
'kickoff' ×81, plus 'project', 'ui_pages', 'remediation_seed_data', and a tail of
task_* ids passed to a DOCUMENT lookup. The reply was nine words naming neither what
went wrong nor what to call instead.

Resolving a name blindly would be a guess: a kickoff document is unique in only 36 of
85 runs (2 in 12 runs, 3 in 3, 4 in 17, absent in 17), while `project` is unique in all
85. So resolve only when exactly one document answers, and otherwise hand back the ids
that do exist — the answer #634 and #1116 already give for a bad argument.
"""
import asyncio
import shutil
import tempfile
from pathlib import Path

import pytest

from env_generator.llm_generator.multi_agent.runtime.hub_registry import HubRegistry
from env_generator.llm_generator.tools.hub_tools import WorkHubGetDocumentTool


@pytest.fixture
def tool():
    tmp = Path(tempfile.mkdtemp(prefix="doc_1121_"))
    try:
        reg = HubRegistry(tmp)
        yield WorkHubGetDocumentTool(hub_workspace=reg), reg.workhub
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _kickoff(workhub, milestone_index):
    return workhub.create_meeting(
        agenda="kickoff", attendees=["frontend"],
        milestone_index=milestone_index, agent="orchestrator")["id"]


def _run(tool, doc_id):
    """The tool is a coroutine; drive it without depending on pytest-asyncio."""
    return asyncio.run(tool._run(document_id=doc_id))


def test_a_unique_name_resolves(tool):
    t, wh = tool
    real = _kickoff(wh, 1)

    r = _run(t, "kickoff")
    assert r.success, "the one document answering to 'kickoff' was still refused"
    assert r.data.get("id") == real


def test_the_resolution_is_reported_so_the_agent_learns_the_id(tool):
    t, wh = tool
    real = _kickoff(wh, 1)

    r = _run(t, "kickoff")
    rendered = str(r)
    assert real in rendered, "the real id never reached the caller"
    assert "is a name, not an id" in rendered, (
        "the resolution happened silently; the agent will keep using the name"
    )


def test_an_ambiguous_name_is_refused_and_names_the_candidates(tool):
    """Two kickoffs happen in 12 of 85 corpus runs; picking one would be a guess."""
    t, wh = tool
    a, b = _kickoff(wh, 1), _kickoff(wh, 2)

    r = _run(t, "kickoff")
    assert not r.success, "an ambiguous name must not resolve to one arbitrary document"
    msg = r.error_message
    assert a in msg and b in msg, "the candidates were not named: %r" % msg
    assert "milestone 1" in msg and "milestone 2" in msg, (
        "nothing in the message distinguishes the candidates: %r" % msg
    )


def test_an_unknown_id_lists_what_does_exist(tool):
    """A task id passed to a document lookup — the corpus's second shape."""
    t, wh = tool
    real = _kickoff(wh, 1)

    r = _run(t, "task_229c5ff088")
    assert not r.success
    assert "addressed by id" in r.error_message
    assert real in r.error_message, "the available documents were not offered"


def test_an_empty_run_says_so(tool):
    t, _wh = tool
    r = _run(t, "kickoff")
    assert not r.success
    assert "no coordination documents yet" in r.error_message


def test_a_real_id_is_untouched(tool):
    """The ordinary path must not pay for any of this."""
    t, wh = tool
    real = _kickoff(wh, 1)
    r = _run(t, real)
    assert r.success and r.data.get("id") == real
    assert not r.notices, "a direct id lookup should carry no notice: %r" % r.notices


def test_matching_is_exact_not_fuzzy(tool):
    """Handing back the wrong meeting reads as success, so near-misses must not match."""
    t, wh = tool
    _kickoff(wh, 1)
    for near in ("kick", "kickoffs", "KICKOFF ROUND", "ickoff"):
        r = _run(t, near)
        if r.success:
            assert near.strip().lower() == "kickoff", "fuzzy match on %r" % near


def test_case_is_ignored(tool):
    t, wh = tool
    real = _kickoff(wh, 1)
    r = _run(t, "KickOff")
    assert r.success and r.data.get("id") == real
