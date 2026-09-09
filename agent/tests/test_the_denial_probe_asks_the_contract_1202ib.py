r"""#1202ib: resolve the denial-probe ambiguity for READS, using the contract.

#188 made the note honest -- "an auth/isolation hole, OR a mis-authored probe" -- and #663
resolved it for WRITES by comparing the id sent against the id stored. A GET carries no
body, so #663 returns "" and the ambiguity stood. It stood on 12 of the 14 DENIAL-PROBE
failures across the last seven days (r41/r96/r99/r100/r102/r103), and all 12 were on
FRAMEWORK-PROJECTED routes whose own note says the lane cannot change them: a permanent
failure with nothing anyone could act on.

r103, live: `GET /api/sounds/{id}` and `GET /api/messages` carry schema.auth_required=False
(written by the backend lane) beside metadata.auth_required=True (the registration mirror
#1202ga documented as never refreshed). The projector reads the schema, emits no guard, and
200 is what the route is BUILT to answer.

★ This writes a SENTENCE. It never sets `ok` and waives nothing. The control-plane waiver
  above it says a denial probe on a real business endpoint "keeps its teeth", and these
  tests hold that.
"""
from __future__ import annotations

import json
from pathlib import Path

from env_generator.llm_generator.multi_agent.runtime.chain_executor import (
    _contract_public_note_1202ib as note,
)

PUBLIC = {"method": "GET", "path": "/api/sounds/{id}",
          "schema": {"auth_required": False}, "metadata": {"auth_required": True},
          "_updated_by": "backend"}
GUARDED = {"method": "POST", "path": "/api/videos/{id}/like",
           "schema": {"auth_required": True}, "metadata": {"auth_required": True}}
UNSTATED = {"method": "GET", "path": "/api/quiet", "schema": {}, "metadata": {}}


def test_a_contract_declared_public_read_is_named_as_such():
    n = note("GET", "/api/sounds/298", [PUBLIC])
    assert "CONTRACT SAYS PUBLIC" in n
    assert "auth_required=False" in n


def test_it_names_who_last_wrote_the_contract():
    """The lane that made it public is the one to argue with."""
    assert "backend" in note("GET", "/api/sounds/298", [PUBLIC])


def test_a_guarded_endpoint_keeps_its_teeth():
    """The control-plane waiver says a denial probe on a real business endpoint keeps its
    teeth. A 200 here is still an unexplained hole and must stay unexplained."""
    assert note("POST", "/api/videos/abc/like", [GUARDED]) == ""


def test_an_unstated_endpoint_says_nothing():
    """#1202hi returns None when nothing states it; claiming 'public' from a default would
    invent a contract that does not exist."""
    assert note("GET", "/api/quiet", [UNSTATED]) == ""


def test_an_unknown_path_says_nothing():
    assert note("GET", "/api/nowhere", [PUBLIC, GUARDED]) == ""


def test_the_method_must_match():
    """PUT /api/sounds/{id} is a different endpoint from GET, and may be guarded."""
    assert note("PUT", "/api/sounds/298", [PUBLIC]) == ""


def test_segment_count_must_match():
    assert note("GET", "/api/sounds/298/extra", [PUBLIC]) == ""


def test_a_static_segment_mismatch_does_not_match_a_template():
    ep = dict(PUBLIC, path="/api/sounds/{id}")
    assert note("GET", "/api/videos/298", [ep]) == ""


def test_it_never_raises_on_junk():
    for eps in (None, [], [None], ["x"], [{"path": None}], [{}]):
        assert note("GET", "/api/x", eps) == ""


def test_it_reuses_the_projectors_own_reader():
    """One predicate: the sentence and the generated handler must never disagree.

    Asserted as a CALL over the AST, not as a substring: the import line keeps the name
    in the source even when the call is replaced by a local re-decision, and the
    counter-proof for this test passed green until it was written this way.
    """
    import ast, inspect
    from env_generator.llm_generator.multi_agent.runtime import chain_executor as CE
    tree = ast.parse(inspect.getsource(CE._contract_public_note_1202ib).lstrip())
    called = {n.func.id for n in ast.walk(tree)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert "_stated_auth_1202hi" in called, (
        "auth is re-decided locally here; that is how two readers of one fact drift apart")


def test_it_is_wired_into_the_denial_note():
    """Reachability: a helper nothing calls is the defect it was written to fix."""
    import ast, inspect
    from env_generator.llm_generator.multi_agent.runtime import chain_executor as CE
    src = inspect.getsource(CE.execute_chain)
    names = {n.func.id for n in ast.walk(ast.parse(src.lstrip()))
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert "_contract_public_note_1202ib" in names


def test_it_cannot_flip_the_verdict():
    """The whole safety argument: it only appends text.

    Checked over the AST of the BODY, not the source text -- the docstring says the words
    "ok" and "expect" precisely because that is the promise being made, and a substring
    scan reads the promise as a violation of itself.
    """
    import ast, inspect
    from env_generator.llm_generator.multi_agent.runtime import chain_executor as CE
    fn = ast.parse(inspect.getsource(CE._contract_public_note_1202ib).lstrip()).body[0]
    body = fn.body[1:] if (fn.body and isinstance(fn.body[0], ast.Expr)
                           and isinstance(fn.body[0].value, ast.Constant)) else fn.body
    banned = {"ok", "expect", "autofilled", "status", "res"}
    for node in body:
        for n in ast.walk(node):
            if isinstance(n, ast.Name) and n.id in banned:
                raise AssertionError(f"the note helper touches {n.id!r}")
            if isinstance(n, ast.Return) and n.value is not None:
                assert not isinstance(n.value, ast.NameConstant if hasattr(ast, "NameConstant")
                                      else ast.Constant) or isinstance(
                    getattr(n.value, "value", None), str), "it must only ever return text"


# --- against the records that actually failed ---------------------------------------

def _r103():
    p = Path(__file__).resolve().parents[2] / (
        "generated/tiktok-web-r103/shared/hubs/registryhub_endpoints.json")
    if not p.is_file():
        return None
    raw = json.loads(p.read_text())
    return raw if isinstance(raw, list) else [v for k, v in raw.items() if k != "_meta"]


def test_the_two_r103_endpoints_that_failed_are_explained():
    eps = _r103()
    if eps is None:
        import pytest
        pytest.skip("r103 corpus not on this machine")
    assert "CONTRACT SAYS PUBLIC" in note("GET", "/api/sounds/298", eps)
    assert "CONTRACT SAYS PUBLIC" in note("GET", "/api/messages", eps)
