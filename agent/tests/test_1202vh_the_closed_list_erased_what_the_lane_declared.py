"""#1202vh — a closed field list silently discarded four documented declaration fields.

`kickoff_declare_ui_page` accepts `purpose`, `must_have`, `reference` and `reach`, all
four documented in the frontend prompt. The task builder copied exactly four keys into
the task metadata and the kickoff finaliser copied exactly five into the ui_page record,
so none of them ever reached the registry. Across the corpus's 1699 ui_page declarations
in 140 runs: purpose 1698 (99%), must_have 764 (51%), reference 321, reach 108,
reference_image 27, path 8, critical 7 — erased, on every page of every run.

Not inert: `_is_map_page` reads `must_have` to decide whether a screen is a map surface,
and that branch was dead on 2702 of 2702 registered pages.
"""
import pathlib

import pytest

from env_generator.llm_generator.multi_agent.runtime.kickoff.schema_tolerance import (
    _declared_extras_1202vh as extras,
)
from env_generator.llm_generator.multi_agent.runtime.frontend_audit import _is_map_page

# r135's real declaration, trimmed.
_DECL = {
    "id": "login_modal", "route": "/login", "component": "LoginModalPage",
    "purpose": "Centered dark login modal over the black shell.",
    "components": ["auth_modal"],
    "apis_used": ["POST /auth/login", "GET /auth/me"],
    "must_have": ["Use QR code", "Use phone or email", "Continue with Google"],
}


def test_the_declared_extras_survive():
    out = extras(_DECL)
    assert out["purpose"] == _DECL["purpose"]
    assert out["must_have"] == _DECL["must_have"]


@pytest.mark.parametrize("key", ["id", "route", "component", "components", "apis_used"])
def test_keys_mapped_explicitly_are_not_duplicated(key):
    assert key not in extras(_DECL)


def test_a_declaration_cannot_set_its_own_lifecycle_status():
    """`status` is the framework's, decided by the auditor. A declaration that could set
    it would flip itself to `implemented` before any code existed."""
    assert "status" not in extras({**_DECL, "status": "implemented"})


def test_private_and_empty_keys_are_dropped():
    out = extras({**_DECL, "_internal": "x", "reach": [], "critical": None})
    assert "_internal" not in out and "reach" not in out and "critical" not in out


def test_a_nested_object_is_not_carried():
    """Every reader of `metadata` assumes it is JSON-flat."""
    assert "design_tokens" not in extras({**_DECL, "design_tokens": {"red": "#FE2C55"}})


def test_values_are_bounded():
    out = extras({**_DECL, "reference": "x" * 9000,
                  "reach": [f"r{i}" for i in range(500)]})
    assert len(out["reference"]) <= 2000
    assert len(out["reach"]) <= 60


def test_the_extras_are_capped_in_number():
    out = extras({**_DECL, **{f"k{i}": f"v{i}" for i in range(80)}})
    assert len(out) <= 24


def test_the_map_reader_looks_where_the_value_actually_lands():
    """The extras ride through `register_ui_page(**metadata)`, so they end up one level
    down. Carrying the field without moving the reader would have left the branch exactly
    as dead as before — the whole point of the ticket."""
    page = {"route": "/search", "metadata": {"must_have": ["Map pins for each result"]}}
    assert _is_map_page("search_results", page) is True


def test_the_top_level_spelling_still_works():
    assert _is_map_page("search_results",
                        {"route": "/search", "must_have": ["Map pins"]}) is True


def test_a_substring_match_still_does_not_qualify():
    """`sitemap`/`roadmap` are not maps — the word-boundary rule is not relaxed."""
    assert _is_map_page("sitemap",
                        {"route": "/sitemap",
                         "metadata": {"must_have": ["A sitemap of every page"]}}) is False


def test_neither_producer_re_enumerates():
    """Both drop points were closed lists, and the second would have discarded the first
    one's fix one step later. Anchored to landmarks, never a byte window (#943)."""
    root = pathlib.Path(__file__).resolve().parents[1] / (
        "env_generator/llm_generator/multi_agent/runtime")
    st = (root / "kickoff/schema_tolerance.py").read_text()
    block = st[st.index('"ui_page": name,'):st.index('"depends_on": _page_deps,')]
    assert "_declared_extras_1202vh(p)" in block

    rk = (root / "kickoff/run_kickoff.py").read_text()
    blk = rk[rk.index("if kind == \"implement_page\":"):]
    blk = blk[:blk.index("# Step 4:")]
    assert "**_pextra," in blk
    assert "_pextra = {" in blk


# ── the sibling entity ────────────────────────────────────────────────────────────
_COMPONENT_DECL = {
    "id": "auth_modal", "component": "AuthModal", "kind": "modal",
    "children": ["QrPanel"], "apis_used": ["POST /auth/login"],
    "purpose": "Login modal over the shell, all auth method rows visible.",
}


def test_a_component_declaration_keeps_its_purpose():
    """1682 declarations across 85 runs all carry `purpose`; it reached 0 of 2123
    registered components."""
    assert extras(_COMPONENT_DECL) == {
        "purpose": _COMPONENT_DECL["purpose"]}


@pytest.mark.parametrize("key", ["children", "kind", "component", "apis_used", "id"])
def test_a_components_own_mapped_keys_do_not_ride_through_twice(key):
    """`children` is copied explicitly and `kind` is stored as `comp_kind`. Letting
    either through again would put two spellings of one fact on the record — which is
    the defect #1202ru/rv already cost a run."""
    assert key not in extras(_COMPONENT_DECL)


def test_comp_kind_cannot_be_set_from_a_declaration():
    assert "comp_kind" not in extras({**_COMPONENT_DECL, "comp_kind": "sneaky"})


def test_neither_component_producer_re_enumerates():
    root = pathlib.Path(__file__).resolve().parents[1] / (
        "env_generator/llm_generator/multi_agent/runtime")
    st = (root / "kickoff/schema_tolerance.py").read_text()
    blk = st[st.index('"kind": "implement_component",'):st.index('"kind": "implement_page",')]
    assert "_declared_extras_1202vh(c)" in blk

    rk = (root / "kickoff/run_kickoff.py").read_text()
    b = rk[rk.index("hubs.workhub.update_ui_component("):]
    b = b[:b.index('agent="orchestrator")') + 24]
    assert "_declared_extras_1202vh(_c)" in b
