r"""#1202id: a bare 404 does not say whether the ROW is wrong or the TABLE is empty.

210 failing steps across this corpus are a 404 on a path whose id is a LITERAL the chain
hardcoded — against 25 already attributed to a capture failure by #592. Those 210 carry
only `{"detail":"not found"}`, and a lane reading that cannot tell apart two completely
different problems:

    GET /api/transit-stops/1 -> 404      the table HAS rows; id 1 is not one of them
    POST /api/videos/1/save  -> 404      `saves` has ZERO rows; nothing was seeded, so
                                         NO id could ever succeed

The first is a mis-authored step; the second is a seeding defect, and chasing it as an
endpoint bug is how a lane spends a milestone rewriting a correct handler.

The evidence was recorded and unread: #1202dj stores live per-table row counts at
`backend_health`. Measured on r107 while this was written — `saves` 0, `likes` 0, against
`users` 9 and `sounds` 8.
"""
from __future__ import annotations

import pytest

from env_generator.llm_generator.multi_agent.runtime import chain_executor as CE

EPS = [
    {"method": "POST", "path": "/api/videos/{id}/save"},
    {"method": "GET", "path": "/api/users/{username}"},
    {"method": "GET", "path": "/api/sounds/{id}"},
]


@pytest.fixture
def counts(monkeypatch):
    data = {"saves": 0, "users": 9, "sounds": 8}
    import env_generator.llm_generator.multi_agent.runtime.seed_audit as SA
    monkeypatch.setattr(SA, "recent_live_counts_1202dj", lambda *a, **k: dict(data))
    return data


def test_an_empty_table_is_named_as_a_seed_defect(counts):
    n = CE._seed_shape_note_1202id("POST", "/api/videos/1/save", ".", {}, EPS)
    assert "0 LIVE ROWS" in n and "SEED defect" in n
    assert "not this endpoint" in n


def test_a_populated_table_points_at_the_id_instead(counts):
    n = CE._seed_shape_note_1202id("GET", "/api/users/liampatel", ".", {"users": 1}, EPS)
    assert "9 LIVE ROW" in n
    assert "the id this step names" in n
    assert "seeded id is 1" in n, "naming a working id is the actionable half"


def test_not_measured_is_never_reported_as_empty(monkeypatch):
    """`{}` means the stack was down when the audit ran — #1202dj's own invariant."""
    import env_generator.llm_generator.multi_agent.runtime.seed_audit as SA
    monkeypatch.setattr(SA, "recent_live_counts_1202dj", lambda *a, **k: {})
    assert CE._seed_shape_note_1202id("POST", "/api/videos/1/save", ".", {}, EPS) == ""


def test_an_unmatched_path_says_nothing(counts):
    assert CE._seed_shape_note_1202id("GET", "/api/nowhere/1", ".", {}, EPS) == ""


def test_a_table_absent_from_the_counts_says_nothing(counts):
    eps = EPS + [{"method": "GET", "path": "/api/widgets/{id}"}]
    assert CE._seed_shape_note_1202id("GET", "/api/widgets/1", ".", {}, eps) == ""


def test_it_never_raises(counts):
    for bad in (None, [], [None], "x"):
        assert CE._seed_shape_note_1202id("GET", "/api/users/x", ".", {}, bad) == ""


# --- the resolver the first draft got wrong -----------------------------------------

def test_the_resource_comes_from_the_TEMPLATE_not_the_value():
    """The first draft reused `_resource_from_path`, which returns the trailing SEGMENT
    VALUE — 'liampatel' for /api/users/liampatel — and answered a question nobody asked."""
    ep = CE._match_endpoint_template_1202id("GET", "/api/users/liampatel", EPS)
    assert ep is not None
    assert CE._template_resource_1202id(ep) == "users"


def test_the_template_resource_skips_param_and_api_segments():
    assert CE._template_resource_1202id({"path": "/api/videos/{id}/save"}) == "save"
    assert CE._template_resource_1202id({"path": "/api/{id}"}) is None


def test_the_matcher_requires_the_method():
    assert CE._match_endpoint_template_1202id("DELETE", "/api/users/x", EPS) is None


def test_the_matcher_requires_the_same_segment_count():
    assert CE._match_endpoint_template_1202id("GET", "/api/users/x/y", EPS) is None


# --- reachability and non-duplication -----------------------------------------------

def test_it_is_wired_and_only_for_unsubstituted_404s():
    """#592 already explains a 404 whose id the LADDER filled; doubling up buries both."""
    import ast, inspect
    src = inspect.getsource(CE.execute_chain)
    i = src.index("_seed_shape_note_1202id(")
    guard = src[max(0, src.rindex("if ", 0, i)):i]
    assert "_ladder_filled" in guard and "_unres_vars" in guard
    assert "404" in guard


def test_both_notes_share_one_matcher():
    """#1202ib and #1202id must agree about which endpoint a request hit."""
    import ast, inspect
    for fn in (CE._contract_public_note_1202ib, CE._seed_shape_note_1202id):
        called = {n.func.id for n in ast.walk(ast.parse(inspect.getsource(fn).lstrip()))
                  if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
        assert "_match_endpoint_template_1202id" in called, f"{fn.__name__} matches its own way"


def test_it_cannot_flip_the_verdict():
    import ast, inspect
    fn = ast.parse(inspect.getsource(CE._seed_shape_note_1202id).lstrip()).body[0]
    body = fn.body[1:] if (fn.body and isinstance(fn.body[0], ast.Expr)) else fn.body
    for node in body:
        for n in ast.walk(node):
            if isinstance(n, ast.Name) and n.id in {"ok", "expect", "autofilled", "status"}:
                raise AssertionError(f"the note helper touches {n.id!r}")
