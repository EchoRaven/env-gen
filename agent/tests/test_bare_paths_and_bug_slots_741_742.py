r"""#741/#742: 216 bugs in the corpus end up owned by nobody, and both causes are readable.

`resolve_owning_agent` tries three things in order — the endpoint, the table, then the files.
Measured over the 1467 bugs in the 148-run corpus (`bug_artifacts` lives at
`payload.metadata.bug_artifacts` on a workhub `task_created` event, not at `payload.*`):

    resolved to a lane     1251
    owned by NOBODY         216      of which 131 carry no affected_files at all

**#742 — the endpoint slot.** Of the 1129 bugs that set `affected_endpoint`:

    449  match a registered endpoint exactly
    339  have nothing path-shaped after the method
    308  carry prose inside the path
     20  differ only in the parameter NAME (/titles/{title_id} vs /titles/{id})
     13  name a path that is not registered

So **57% of the values a parser depends on are not parseable**, and the tool contract explains
why: `bug_artifacts` was advertised as the bare string "failing_test, stack_trace,
affected_endpoint, affected_files, expected, actual, ..." — slot names with no shape for any of
them. Same fix as #732/#733: a model writes what the description names, so the description now
states the exact form of the two slots that are PARSED and says to put uncertainty in
`description` instead.

**#741 — the file slot.** #626 routes by path SEGMENT, which cannot help a path written relative
to the app root, and those dominate what is left: `src/App.jsx` (11), `src/pages/
BrowseHomePage.jsx` (5), `src/api.js` (3), `custom_routes.py` (2). An extension is an
independent signal; as a strict fallback it routes 25 more bugs (22 frontend, 3 backend).

`.js`/`.ts`/`.mjs` are deliberately excluded — a Node backend uses them, and a wrongly-routed
bug burns the wrong lane's cycle, which is worse than the 7 extra routes it would buy.
"""
import inspect

import pytest

from env_generator.llm_generator.multi_agent.runtime import bug_triage as bt
from env_generator.llm_generator.tools.bug_tools import BugCreateTool


# --- #741: the extension fallback ----------------------------------------------------------

@pytest.mark.parametrize("path,lane", [
    ("src/App.jsx", "frontend"),
    ("src/pages/BrowseHomePage.jsx", "frontend"),
    ("components/Card.tsx", "frontend"),
    ("styles/main.css", "frontend"),
    ("theme.scss", "frontend"),
    ("Widget.vue", "frontend"),
    ("Widget.svelte", "frontend"),
    ("custom_routes.py", "backend"),
    ("schema.sql", "database"),
])
def test_a_bare_path_is_routed_by_its_extension(path, lane):
    assert bt.find_owning_agent_for_file(path) == lane


@pytest.mark.parametrize("path", ["src/api.js", "server.ts", "index.mjs"])
def test_ambiguous_extensions_are_left_unrouted(path):
    """A Node backend uses these too; a wrong route costs more than an unowned bug."""
    assert bt.find_owning_agent_for_file(path) is None


def test_the_segment_rule_still_wins():
    """#626 must not be weakened: a segment is a stronger signal than an extension."""
    assert bt.find_owning_agent_for_file("app/backend/schema.sql") == "backend"
    assert bt.find_owning_agent_for_file("app/database/seed.py") == "database"
    assert bt.find_owning_agent_for_file("app/frontend/src/db/x.py") == "frontend"


def test_the_626_cases_are_unchanged():
    assert bt.find_owning_agent_for_file(
        "app/frontend/src/pages/TitleDetailPage.jsx") == "frontend"
    assert bt.find_owning_agent_for_file("app/backend/custom_routes.py") == "backend"
    assert bt.find_owning_agent_for_file("BackendStatus.jsx") == "frontend", (
        "#626's guard: a FILE named like a lane must not masquerade as one — and now the "
        "extension routes it correctly rather than leaving it unowned")


@pytest.mark.parametrize("path", ["", None, "README", "docker-compose.yml", "Dockerfile",
                                  "frontend nginx".replace(" ", "_") + ".unknown"])
def test_an_unroutable_path_is_still_none(path):
    assert bt.find_owning_agent_for_file(path) is None


def test_the_case_is_normalised():
    assert bt.find_owning_agent_for_file("src/App.JSX") == "frontend"


def test_it_flows_through_the_resolver():
    """The fallback is worthless if `resolve_owning_agent` never reaches it."""
    class _Reg:
        registryhub = type("R", (), {"list_endpoints": staticmethod(lambda: {})})()
        schema_hub = None
    assert bt.resolve_owning_agent(_Reg(), {"affected_files": ["src/App.jsx"]}) == "frontend"


def test_no_ambiguous_extension_leaked_into_the_table():
    for bad in ("js", "ts", "mjs", "cjs", "json", "md", "yml", "yaml"):
        assert bad not in bt._LANE_BY_EXTENSION_741, bad


# --- #742: the tool contract ------------------------------------------------------------------

def _slot(name):
    return BugCreateTool.PARAMETERS["properties"]["bug_artifacts"]["properties"][name]


def test_the_parsed_slots_are_published_with_their_shape():
    props = BugCreateTool.PARAMETERS["properties"]["bug_artifacts"]["properties"]
    for k in ("failing_test", "stack_trace", "affected_endpoint", "affected_table",
              "affected_files", "expected", "actual"):
        assert k in props, k


def test_the_endpoint_slot_states_the_exact_form():
    d = _slot("affected_endpoint")["description"]
    assert "<METHOD>" in d and "registered path" in d


def test_the_files_slot_says_repo_relative():
    d = _slot("affected_files")["description"]
    assert "repo-relative" in d
    assert _slot("affected_files")["type"] == "array"


def test_the_description_forbids_the_two_shapes_that_actually_occur():
    """339 values were not path-shaped and 308 carried prose. Both are named."""
    d = BugCreateTool.PARAMETERS["properties"]["bug_artifacts"]["description"]
    assert "no query string, no parentheses, no prose" in d
    assert "the parameter name must be the registered one" in d


def test_it_says_where_uncertainty_goes():
    """The prose had to go somewhere; a rule that only forbids leaves the model stuck."""
    d = BugCreateTool.PARAMETERS["properties"]["bug_artifacts"]["description"]
    assert "Put uncertainty in `description`, never inside these two." in d


def test_it_still_says_at_least_one_is_required():
    """The original contract's only real rule must survive the rewrite."""
    d = BugCreateTool.PARAMETERS["properties"]["bug_artifacts"]["description"]
    assert "At least one of" in d
    assert "bug_artifacts" in BugCreateTool.PARAMETERS["required"]


def test_it_says_WHY_the_form_matters():
    d = BugCreateTool.PARAMETERS["properties"]["bug_artifacts"]["description"]
    assert "PARSED, not just read" in d


# --- provenance ------------------------------------------------------------------------------------

def test_the_741_measurement_is_recorded():
    src = inspect.getsource(bt)
    assert "routes **25 more bugs**" in src
    assert "216 that currently end up owned by nobody" in src


def test_741_records_why_js_is_excluded():
    src = " ".join(inspect.getsource(bt).replace("#", " ").split())
    assert "a Node backend uses" in src
    assert "worse than the 7 extra routes it would buy" in src


def test_the_742_measurement_is_recorded():
    src = inspect.getsource(BugCreateTool)
    assert "339  have nothing path-shaped after the method" in src
    assert "216 bugs end up with NO owner at all" in src


def test_742_names_its_precedents():
    src = inspect.getsource(BugCreateTool)
    assert "Same fix shape as #732/#733" in src


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
