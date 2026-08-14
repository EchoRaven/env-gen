r"""#695: two PR tools stayed in the catalogue after PR-mode was declared dead.

`#35` removed `codehub_open_pr` and `codehub_resolve_conflict` from the agent-facing bundle with
an explicit reason — "the pipeline is commit-only (committed work auto-integrates via
merge_agent_branch_to_main; PR-mode is dead)" — and kept the classes for the live-monitor shim.
It left two tools from the same surface behind:

    codehub_list_prs            lists PRs that cannot be opened
    codehub_suggest_reviewers   PR-bound in its own parameter descriptions —
                                "The branch being submitted as a PR",
                                "endpoint IDs touched by this PR"

That they are dead is not inferred from the mode alone; the store says so. `codehub_pull_requests`
sits at `_meta.version` 1 — created, never written — in 146 of 146 runs, so `list_prs` has never
had anything to return.

And they were not free. Across the 253 kept logs the pair appears 700 times, every occurrence the
same catalogue line — `list_inline_comments, codehub_list_prs, codehub_suggest_reviewers` — with
no call form anywhere in the corpus. Listed 700 times, invoked zero. That is #257 economics: a
tool in the catalogue is re-sent with the prompt on every step of every agent holding the bundle,
so a permanently-empty tool is paid for continuously and used never.

The classes stay, exactly as #35 kept open_pr's. Only the offer is withdrawn.
"""
import inspect

import pytest

from env_generator.llm_generator.multi_agent import tool_bundles as tb


def _bundle_src() -> str:
    src = inspect.getsource(tb._bundle_codehub_tools)
    return src


# --- the four PR names are all withheld together -------------------------------------------------

@pytest.mark.parametrize("name", [
    "codehub_open_pr",           # #35
    "codehub_resolve_conflict",  # #35
    "codehub_list_prs",          # #695
    "codehub_suggest_reviewers", # #695
])
def test_no_pr_tool_is_in_the_include_set(name):
    """Each must appear only inside a comment, never as an included name."""
    src = _bundle_src()
    assert f'"{name}",' not in src, f"{name} is still surfaced"


def test_the_names_are_still_mentioned_so_the_decision_is_findable():
    src = _bundle_src()
    for name in ("codehub_open_pr", "codehub_list_prs", "codehub_suggest_reviewers"):
        assert name in src, "removing the name entirely would lose the rationale"


# --- the live surface is untouched ---------------------------------------------------------------

@pytest.mark.parametrize("name", [
    "codehub_commit",
    "codehub_record_check",
    "codehub_get_diff",
    "codehub_get_blob",
    "codehub_get_file_content",
    "codehub_list_checks",
    "codehub_list_inline_comments",
    "codehub_resolve_merge_conflict",
    "codehub_revert_commit",
    "codehub_register_repo",
    "codehub_record_commit",
    "hub_snapshot",
])
def test_every_other_tool_is_still_offered(name):
    assert f'"{name}",' in _bundle_src()


def test_the_admin_bundle_is_untouched():
    """force_merge/create_release live in the orchestrator-only bundle and are unrelated."""
    src = inspect.getsource(tb._bundle_codehub_admin_tools)
    assert '"codehub_force_merge"' in src and '"codehub_create_release"' in src


# --- the classes must survive, as #35 required ---------------------------------------------------

@pytest.mark.parametrize("cls", ["CodeHubListPRsTool", "CodeHubSuggestReviewersTool"])
def test_the_tool_classes_still_exist(cls):
    from env_generator.llm_generator.tools import hub_tools
    assert hasattr(hub_tools, cls), "#35 keeps the class for the live-monitor shim"


# --- provenance -----------------------------------------------------------------------------------

def test_the_store_evidence_is_recorded():
    flat = " ".join(_bundle_src().replace("#", " ").split())
    assert "_meta.version 1" in flat
    assert "146 of 146 runs" in flat


def test_the_catalogue_cost_is_recorded():
    flat = " ".join(_bundle_src().replace("#", " ").split())
    assert "appears 700 times" in flat
    assert "no call form anywhere" in flat


def test_it_names_the_economics_it_appeals_to():
    flat = " ".join(_bundle_src().replace("#", " ").split())
    assert "257 economics" in flat


def test_it_says_how_to_revive_the_surface():
    flat = " ".join(_bundle_src().replace("#", " ").split())
    assert "revive all four names together" in flat


def test_it_defers_to_the_existing_decision_rather_than_making_a_new_one():
    flat = " ".join(_bundle_src().replace("#", " ").split())
    assert "the same argument 35 makes" in flat


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
