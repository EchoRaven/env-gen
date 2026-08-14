r"""#697: WorkHub advertised "plans" and CodeHub advertised GitHub; neither surface has a record.

The symmetric half of #693, which did this for RegistryHub. Same instrument, because it is the
only one that separates a drained queue from a writer that never ran: `JsonStore.update` always
`_save_raw`s and always `_bump_meta`s — no branch skips either — so `_meta.version` counts writes
exactly, and a store still at 1 after a whole run was created and never written by anybody.

Across all 146 kept runs the two hubs split cleanly, nine live against nine never written:

    WorkHub    live   tasks v1543, documents v151, comments v130, attendees v10, blocks v6
               dead   workspaces, databases, decisions, acceptance_criteria, reactions
    CodeHub    live   checks v11821, branches v115, commits v58, releases v4
               dead   pull_requests, review_threads, code_reviews, repos

CodeHub's dead half is deliberate and already documented at the bundle — `#35` withholds
`codehub_open_pr` ("the pipeline is commit-only ... PR-mode is dead") and `#695` withheld the two
PR tools it left behind. The docstring simply did not say so, and "GitHub/GitLab-like" invites a
reader to expect the half that is empty by design.

WorkHub's is more pointed. Four of its five nouns hold up — docs are `documents` (kinds retro
545, kickoff 154, project 146, knowledge 12, general 4), and tasks, attendees and comments are
live. **"plans" is not one of them:** no plans store, no `plan` document kind, and `submit_plan`
appears in 0 of 253 kept run logs despite being bundled and granted to the orchestrator. This
docstring was the only place in the tree claiming the plan surface exists.

Nothing is deleted, for the same reason as #693: the readers exist and an empty store is a
legitimate state.
"""
import json
from pathlib import Path

import pytest

from env_generator.llm_generator.multi_agent.runtime import json_store as js
from env_generator.llm_generator.multi_agent.runtime.hubs.codehub.service import CodeHub
from env_generator.llm_generator.multi_agent.runtime.hubs.workhub.service import WorkHub


# --- WorkHub -------------------------------------------------------------------------------------

def test_workhub_admits_plans_do_not_exist():
    d = " ".join((WorkHub.__doc__ or "").split())
    assert '"plans" is not one of them' in d
    assert "no plans store, no `plan` document kind" in d


def test_workhub_ties_it_to_the_unrun_tool():
    d = " ".join((WorkHub.__doc__ or "").split())
    assert "submit_plan` appears in 0 of 253" in d
    assert "item 19" in d


def test_workhub_names_the_four_nouns_that_do_hold_up():
    d = WorkHub.__doc__ or ""
    for live in ("tasks", "documents", "comments", "attendees"):
        assert live in d


def test_workhub_lists_its_dead_stores():
    d = WorkHub.__doc__ or ""
    for dead in ("workspaces", "databases", "decisions", "acceptance_criteria", "reactions"):
        assert dead in d


def test_workhub_keeps_its_original_sentence():
    assert (WorkHub.__doc__ or "").startswith(
        "Notion/Jira-like workspace for docs, plans, tasks, attendees, and comments.")


# --- CodeHub -------------------------------------------------------------------------------------

def test_codehub_says_what_it_actually_is():
    d = " ".join((CodeHub.__doc__ or "").split())
    assert "commit-and-check, not GitHub" in d


def test_codehub_lists_its_dead_stores():
    d = CodeHub.__doc__ or ""
    for dead in ("pull_requests", "review_threads", "code_reviews", "repos"):
        assert dead in d


def test_codehub_credits_the_existing_decision():
    """The PR half is empty BY DESIGN; the docstring must not read as a bug report."""
    d = " ".join((CodeHub.__doc__ or "").split())
    assert "deliberate and already documented" in d
    assert "#35" in d and "#695" in d


def test_codehub_says_the_classes_are_kept():
    assert "kept for the live-monitor shim" in " ".join((CodeHub.__doc__ or "").split())


def test_codehub_keeps_its_original_sentence():
    assert (CodeHub.__doc__ or "").startswith(
        "GitHub/GitLab-like collaboration kernel for agent code work.")


# --- both cite the instrument, and the instrument holds ------------------------------------------

@pytest.mark.parametrize("cls", [WorkHub, CodeHub])
def test_each_states_the_measurement_basis(cls):
    d = " ".join((cls.__doc__ or "").split())
    assert "146 of 146" in d or "146 runs" in d
    assert "version" in d


def test_version_still_counts_writes_exactly(tmp_path: Path):
    """If this ever stops holding, both docstrings above become unfounded."""
    s = js.JsonStore(tmp_path / "x.json")
    assert s.get_version() == 0
    s.update(lambda m: m.set("a", {}, "t"), change_info={"agent": "t"})
    s.update(lambda m: m.set("b", {}, "t"), change_info={"agent": "t"})
    s.update(lambda m: m.delete("a", "t"), change_info={"agent": "t"})
    assert s.get_version() == 3
    left = [k for k in json.loads((tmp_path / "x.json").read_text()) if not k.startswith("_")]
    assert left == ["b"], "content and write-count are independent, which is the whole point"


def test_a_created_but_unwritten_store_stays_at_its_creation_count(tmp_path: Path):
    s = js.JsonStore(tmp_path / "y.json")
    s.update(lambda m: m, change_info={"agent": "creator"})
    assert s.get_version() == 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
