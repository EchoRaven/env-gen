"""Guard: an unknown tool name suggests the closest GRANTED tools.

Surfaced by the youtube run — the backend burned ~22 rounds guessing
execute_command / local_bash / shell / run_command / codehub_search_code for
tools it couldn't name, because "Unknown tool: X" gave no hint. `suggest_tools`
nudges the agent to a callable tool it actually has.
"""
from env_generator.llm_generator.multi_agent.agents.runtime.tooling import suggest_tools

# A representative granted tool set for an implementation lane.
GRANTED = {
    "execute_bash", "execute_ipython", "grep", "glob", "find_definition",
    "codehub_get_file_content", "list_generated_files", "edit_code", "finish",
}


def test_shell_confusions_map_to_execute_bash():
    # the exact names the backend guessed in the run
    for guess in ("execute_command", "run_command", "shell", "local_bash"):
        hits = suggest_tools(guess, GRANTED)
        assert hits, f"{guess!r} produced no suggestion"
        assert "execute_bash" in hits, (guess, hits)


def test_search_confusions_map_to_search_tools():
    hits = suggest_tools("codehub_search_code", GRANTED)
    assert hits and ({"grep", "glob", "codehub_get_file_content"} & set(hits)), hits


def test_typo_uses_fuzzy_match():
    hits = suggest_tools("execute_bsh", GRANTED)  # typo of execute_bash
    assert "execute_bash" in hits, hits


def test_only_suggests_granted_tools():
    # a lane WITHOUT execute_bash shouldn't be told to use it
    lean = {"codehub_get_file_content", "edit_code", "finish"}
    hits = suggest_tools("execute_command", lean)
    assert "execute_bash" not in hits and "execute_ipython" not in hits, hits
    # find-intent still points at the read tool it DOES have
    assert suggest_tools("find_file", lean) == ["codehub_get_file_content"]


def test_no_match_returns_empty():
    assert suggest_tools("zzzqqq_nonsense", GRANTED) == []
