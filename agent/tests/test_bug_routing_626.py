r"""#626: 69 P0 bugs were filed with no owner, and the router had the answer all along.

Joining every `bug_found` event to its workhub task across 40 runs:

    314 P0 bugs filed
    111 (35%) never fixed — 65 pending, 46 cancelled
     69 of the open ones have NO ASSIGNEE

They sat a median of 46 minutes (max 117) and every affected run released with them still open.
An unassigned task is nobody's job by construction — and assignment is also what wakes a fixer
("assigned task_created -> for-self wakeup"), so None is the one value guaranteed to wake no one.

Two causes, both mechanical:

1. `find_owning_agent_for_file` matched a PREFIX anchored at position 0 ("frontend/"), but every
   generated project nests code under `app/`. 55 of the 69 carry perfectly usable
   `affected_files` such as `app/frontend/src/pages/TitleDetailPage.jsx` — and the prefix rule
   routed **0** of them. Segment matching routes **44** (33 frontend, 11 backend).

2. The keyword fallback returns None when NEITHER vocabulary matches (46 of 59 — "Landing page
   (/) crashes with 'Cn is not a function'" contains no framework word) and also when BOTH do
   (13). Ambiguity is not unknown, and unknown is not nobody.
"""
import pytest

from env_generator.llm_generator.multi_agent.runtime.bug_triage import find_owning_agent_for_file


# --- the path resolver ------------------------------------------------------------------------

@pytest.mark.parametrize("path,owner", [
    ("app/frontend/src/pages/TitleDetailPage.jsx", "frontend"),
    ("app/backend/custom_routes.py", "backend"),
    ("agent/app/backend/Dockerfile", "backend"),
    ("app/database/init/01_init.sql", "database"),
    ("app/backend/migrations/003_x.sql", "backend"),   # first segment wins
])
def test_a_nested_path_still_names_its_owner(path, owner):
    assert find_owning_agent_for_file(path) == owner


@pytest.mark.parametrize("path,owner", [
    ("backend/main.py", "backend"),
    ("frontend/src/App.jsx", "frontend"),
    ("/frontend/src/App.jsx", "frontend"),
    ("migrations/001.sql", "database"),
])
def test_the_pre_626_shapes_still_resolve(path, owner):
    assert find_owning_agent_for_file(path) == owner


def test_the_first_lane_segment_wins():
    """`app/frontend/src/db/client.js` is the frontend's, not the database lane's."""
    assert find_owning_agent_for_file("app/frontend/src/db/client.js") == "frontend"


def test_a_filename_cannot_masquerade_as_a_lane():
    """Segment EQUALITY, not substring — otherwise BackendStatus.jsx routes to the backend."""
    assert find_owning_agent_for_file("app/frontend/src/components/BackendStatus.jsx") == "frontend"
    assert find_owning_agent_for_file("src/components/BackendStatus.jsx") is None


def test_windows_separators_resolve_too():
    assert find_owning_agent_for_file(r"app\frontend\src\App.jsx") == "frontend"


@pytest.mark.parametrize("path", ["", None, "README.md", "docker/docker-compose.yml"])
def test_an_unplaceable_path_is_still_None(path):
    assert find_owning_agent_for_file(path) is None


def test_it_is_case_insensitive_on_the_segment():
    assert find_owning_agent_for_file("App/Frontend/src/App.jsx") == "frontend"


# --- never unassigned -----------------------------------------------------------------------

def test_the_triage_owner_exists_and_is_the_debugger():
    from env_generator.llm_generator.tools import bug_tools
    assert bug_tools._TRIAGE_OWNER_626 == "debugger"


def test_a_bug_that_no_rule_places_still_gets_an_owner():
    """The measured shape: a title with no framework vocabulary and no routable file."""
    import inspect
    from env_generator.llm_generator.tools import bug_tools
    src = inspect.getsource(bug_tools.BugCreateTool)
    i = src.index("#626: AMBIGUOUS IS NOT UNKNOWN")
    block = src[i:src.index("task = self._hubs.workhub.create_task", i)]
    assert "_owner = _TRIAGE_OWNER_626" in block


def test_the_fallback_runs_AFTER_both_resolvers():
    """It must never pre-empt a real owner — resolver first, keywords second, triage last."""
    import inspect
    from env_generator.llm_generator.tools import bug_tools
    src = inspect.getsource(bug_tools.BugCreateTool)
    assert (src.index("resolve_owning_agent(self._hubs")
            < src.index('_owner = "frontend"')
            < src.index("_owner = _TRIAGE_OWNER_626")
            < src.index("assignee=_owner"))


def test_an_explicitly_resolved_owner_is_not_overwritten():
    """The fallback is guarded by `if not _owner`, so a resolved lane survives it."""
    import inspect
    from env_generator.llm_generator.tools import bug_tools
    src = inspect.getsource(bug_tools.BugCreateTool)
    i = src.index("_owner = _TRIAGE_OWNER_626")
    # a semantic boundary, not a character window: the nearest guard above the fallback must sit
    # BELOW the keyword rule, i.e. the fallback is inside its own `if not _owner:` block.
    assert src.rindex("if not _owner:", 0, i) > src.index('_owner = "frontend"')


# --- what justified it -------------------------------------------------------------------------

def test_the_measurement_is_recorded():
    import inspect
    from env_generator.llm_generator.multi_agent.runtime import bug_triage
    flat = " ".join(inspect.getsource(bug_triage).replace("#", " ").split())
    assert "routed **0** of them" in flat and "routes **44**" in flat


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
