r"""#1203m9: the kickoff documents handed a lane a path FastAPI cannot route.

`RegistryHub._canonical_path` exists for PROPOSAL #38 A2 -- the registry stores
`/api/notes/{id}`, never the raw `/api/notes/:id`, "so the route projector stamps a real path
param (not a literal `:id` static route) and the verifier tests `/api/notes/1` against a
matching route instead of getting a 405". The milestone spec's endpoint table and the
briefing's "API endpoints to implement" rendered the raw declaration.

MEASURED: 281 occurrences across 37 runs' briefings; time-sliced, 27 in 9 modern runs (r151,
r157, r159, r161, r162, r167, r169, r170, r182). The DELIVERED harm is zero -- those 9 runs
shipped 0 literal `:param` backend routes and 0 literal `:param` frontend API URLs, so this
is a prose fix under #1203j2's standard and nothing more.

Screen routes are deliberately untouched: React Router's syntax IS `:param` and r185 ships
`<Route path="/video/:id/comments">`.
"""
from __future__ import annotations

import ast
import inspect
import textwrap

import pytest

from env_generator.llm_generator.multi_agent.runtime.kickoff import authoring
from env_generator.llm_generator.multi_agent.runtime.kickoff.authoring import (
    _canon_api_path_1203m9)
from env_generator.llm_generator.multi_agent.runtime.registryhub import RegistryHub


@pytest.mark.parametrize("raw,want", [
    ("/api/videos/:id/comments", "/api/videos/{id}/comments"),   # r182/r170
    ("/api/users/:username/follow", "/api/users/{username}/follow"),
    ("/api/videos/:video_id/comments", "/api/videos/{video_id}/comments"),  # r157/r169
])
def test_an_express_path_is_rendered_as_fastapi_routes_it(raw, want):
    assert _canon_api_path_1203m9(raw) == want


def test_an_already_canonical_path_is_untouched():
    assert _canon_api_path_1203m9("/api/videos/{video_id}") == "/api/videos/{video_id}"


def test_a_fastapi_path_converter_survives():
    """r167 ships `/api/users/{id:int}/follow` — a legal converter, not an Express path.

    My first detector matched the colon inside the braces and called it a violation.
    """
    assert _canon_api_path_1203m9("/api/users/{id:int}/follow") == "/api/users/{id:int}/follow"


@pytest.mark.parametrize("raw", [None, "", "?", " ? "])
def test_the_unknown_marker_is_preserved(raw):
    """Both call sites printed `?` for a missing path; canonicalising it would print `/?`."""
    assert _canon_api_path_1203m9(raw) == "?"


def test_it_never_raises():
    for junk in (123, [], {}, object()):
        assert isinstance(_canon_api_path_1203m9(junk), str)


def test_it_delegates_to_the_registry_rather_than_a_second_regex():
    """#1032: one owner for the canonical form.

    Asserted on the AST, not on the source text: this helper's own docstring quotes
    `RegistryHub._canonical_path`, so `"_canonical_path" in getsource(...)` is satisfied by
    the comment and would stay green with the delegation ripped out. Pin the CALL instead
    (#1202w1: a name is not a use) and, separately, that no rewriting happens inline.
    """
    tree = ast.parse(textwrap.dedent(inspect.getsource(_canon_api_path_1203m9)))
    calls = [n for n in ast.walk(tree)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
             and n.func.attr == "_canonical_path"]
    assert calls, "the canonical form is no longer obtained from its owner"
    # no second implementation: nothing in the body may rewrite the path itself
    for n in ast.walk(tree):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute):
            assert n.func.attr not in ("sub", "replace", "translate"), \
                "a second rewriting implementation appeared beside the delegation"
    # and the owner still does the job this delegates to it
    assert RegistryHub._canonical_path("/api/notes/:id") == "/api/notes/{id}"


def test_both_api_renders_go_through_it_and_the_screen_route_does_not():
    """The call sites, not the helper. Screen routes must keep React Router's `:param`."""
    src = inspect.getsource(authoring)
    assert src.count("_canon_api_path_1203m9(ep.get(\"path\"))") == 2, \
        "an API endpoint render stopped canonicalising (or a third one appeared unguarded)"
    # the screens section still renders its route raw
    assert 's.get("path") or s.get("route")' in src
    _screen = src[src.index("## Screens to implement"):]
    assert "_canon_api_path_1203m9" not in _screen[:600], \
        "a screen route is being rewritten to FastAPI syntax; React Router cannot match that"
