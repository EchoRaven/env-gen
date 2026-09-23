r"""#1202sw: the placeholder-route blocker was the last one that declined delivery with nobody dispatched.

`_deliverability_check_token` maps blocker prose onto a stable check token; anything unmapped
falls into `f"deliverability_other:{blocker[:80]}"`. `dispatch_gate_level_checks` looks the
owner up with `_GATE_OWNER.get(name)` — an exact-key lookup — so a name with prose inside it
can never match: the check blocks delivery and dispatches nobody. `#1202ou` named two
auth-tampering blockers for this reason and `#1202lf` named `unscoped owner read`.

Replaying every `failed_checks` entry in the corpus's `logs/delivery_gate.jsonl` against the
CURRENT tables, exactly one class is left unmapped:

    729 firings / 13 runs   unscoped owner read: …          -> named by #1202lf
      6 firings /  1 run    App.jsx routes N placeholder page(s) — …   <- this one
      6 firings /  2 runs   custom_routes.py reassigns the auth primitive  -> named by #1202ou

The truncation makes it worse than merely unowned, the same way `#1202lf` measured: the name
embeds the COUNT and the component names, so `1 placeholder page(s) — X` and
`2 placeholder page(s) — X, Y` are one defect under two names, and the dispatcher's own
re-fire guard (`guard.get(name) == milestone`) is keyed on that name.

The class is real and not env-specific — `_placeholder_route_blockers_1202w`'s own record
names five instances across three apps: instagram-r76 `DummyToGetRegistryList`, tiktok-r61's
three `*PlaceholderPage`, r69 and r87 `PlaceholderPage`. `#1202hp` removed the largest
false-positive source (an orchestrator probe registration becoming a page); this gives
whatever remains an owner instead of a dead end, which is the division of labour `#1202lf`
recorded with `#1202le`.

LOCAL-ONLY (gitignored)."""
from __future__ import annotations

import ast
import inspect
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for p in (str(ROOT), str(LLM_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

from multi_agent.runtime import remediation_dispatcher as rd  # noqa: E402
from multi_agent.runtime.delivery_gate import _deliverability_check_token as tok  # noqa: E402

_TOKEN = "deliverability_placeholder_route"

# Verbatim from tiktok-r106's gate log, plus the multi-page shape the same producer emits.
_REAL = [
    "App.jsx routes 1 placeholder page(s) — NoopMonitorDoNotUse. A route a user can reach "
    "must render the real thing; four runs of the corpus shipped one of these live.",
    "App.jsx routes 3 placeholder page(s) — ExplorePlaceholderPage, FollowingPlaceholderPage, "
    "LivePlaceholderPage. A route a user can reach must render the real thing;",
]


def test_every_count_maps_to_the_same_token():
    assert {tok(b) for b in _REAL} == {_TOKEN}, (
        "the count and the component list are in the name, so each shape had its own")


def test_it_no_longer_falls_into_the_catch_all():
    for b in _REAL:
        assert not tok(b).startswith("deliverability_other"), b


def test_the_catch_all_still_exists_for_genuinely_new_prose():
    assert tok("some blocker nobody has mapped yet").startswith("deliverability_other:")


def test_the_neighbouring_placeholder_tokens_are_untouched():
    """Three different blockers say "placeholder"; matching the wrong one would re-route a
    backend defect to the frontend."""
    assert tok("GET /api/x is a placeholder stub handler returning a hardcoded empty "
               "collection") == "deliverability_placeholder_stub_handler"
    assert tok("low row count / placeholder seed in table users") == \
        "deliverability_seed_quality"
    assert tok("route /x renders a framework fallback page (`Foo`) — author the REAL page") \
        == "deliverability_frontend_fallback_page"


def _owner_row():
    tree = ast.parse(inspect.getsource(rd))
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
                getattr(t, "id", "") == "_GATE_OWNER" for t in node.targets):
            for k, v in zip(node.value.keys, node.value.values):
                if k.value == _TOKEN:
                    return ast.literal_eval(v)
    raise AssertionError("the token has no row in _GATE_OWNER — it still dead-ends")


def test_the_token_has_a_frontend_owner():
    owner, title, how = _owner_row()
    assert owner == "frontend", "both repairs are edits to the page and its route"
    assert "(blocks delivery)" in title


def test_the_body_names_BOTH_repairs_and_refuses_the_cosmetic_one():
    """#1202gt's hazard: an instruction that names one repair makes the lane do that one even
    when it is wrong. Removing the route is as valid as building the page — and renaming the
    component is neither."""
    _, _, how = _owner_row()
    low = how.lower()
    assert "build the real page" in low
    assert "remove the route" in low and "ui_page" in low
    assert "renaming the component does not fix it" in low


def test_the_token_matches_the_producer_not_a_remembered_string():
    """One fact, two spellings is how these detectors die. Anchor on the producer's own
    format string."""
    from multi_agent.runtime import deliverability
    src = inspect.getsource(deliverability)
    assert 'placeholder page(s)' in src, "the producer's wording changed — re-anchor the token"
    i = src.index("placeholder page(s)")
    assert "App.jsx routes %d" in src[i - 40:i]
