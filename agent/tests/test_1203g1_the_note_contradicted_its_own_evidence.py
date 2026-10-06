"""#1203g1 — the auth note claimed "not wired" while printing `token=True` beside it.

The browser walk's auth step reported, verbatim:

    submit sent NO /auth request (token=True url=http://localhost:8033/login)
      — the form is not wired to the API

A token in storage is proof that something obtained one, so "not wired" is false on its face.
It happened in r119, r124 and r164 (r164's `task_68ca737566`); `token=False` -- where the claim
is sound -- accounts for the other 80 across 41 runs.

#612 wrote the rule this restores. Its own words: "REPORT THE OBSERVATION, NOT A GUESS AT ITS
CAUSE ... the causal clause was an inference the harness had no basis for, and it is
load-bearing: it lands in the failure ledger and sends the frontend lane to re-wire a form that
is already wired." It removed the unconditional claim from the ladder and left it unconditional
INSIDE the empty-`auth_status` branch.

Two things also come out of looking: the watcher matched `"/auth/" in url`, which does not match
`/oauth/token` -- the framework's own OAuth2 token endpoint -- and `_drive_auth_form` returns a
pre-existing token BEFORE clicking, so a token already in storage means the form was never
submitted at all. Both are stated in the new note instead of being guessed about.
"""
import inspect

import pytest

from env_generator.llm_generator.multi_agent.runtime import test_user_runner as R
from env_generator.llm_generator.multi_agent.runtime.test_user_runner import auth_note_1203g1


def _note(**kw):
    base = dict(ok_auth=False, token=None, navigated=False, landed=False,
                path="/login", url="http://localhost:8033/login", auth_status=[])
    base.update(kw)
    return auth_note_1203g1(**base)


# ------------------------------------------------------------------ the defect

def test_a_stored_token_is_never_called_unwired():
    """r164's task_68ca737566, exactly."""
    out = _note(token="eyJ0eXAi", auth_status=[])
    assert "not wired" not in out, out
    assert "NOT evidence the form is unwired" in out
    assert "a token IS stored" in out


def test_no_token_and_no_request_still_reads_unwired():
    """The claim is sound in this shape -- 80 of the 83 corpus occurrences -- and must stay."""
    out = _note(token=None, auth_status=[])
    assert "submit sent NO /auth request" in out
    assert "the form is not wired to the API" in out


def test_the_stored_token_note_names_what_the_lane_can_check():
    out = _note(token="t", auth_status=[])
    assert "/auth/" in out and "/oauth/" in out      # the only surfaces watched
    assert "navigate away after storing the token" in out
    # and the HARNESS limitation, because it is the likeliest reading
    assert "returns a pre-existing token WITHOUT submitting the form" in out


def test_the_note_carries_the_url_it_observed():
    out = _note(token="t", url="http://localhost:9/login", auth_status=[])
    assert "http://localhost:9/login" in out


# ----------------------------------------------------- the rest of the ladder is untouched

def test_a_working_auth_flow_says_nothing():
    assert _note(ok_auth=True, token="t", navigated=True, landed=True) == ""


def test_1126_post_login_destination_still_wins_over_the_new_branch():
    """`token and navigated and not landed` is ABOVE the new branch and must stay there:
    that case has a diagnosis, and the new branch would blur it into "check two things"."""
    out = _note(token="t", navigated=True, landed=False, path="/", auth_status=[])
    assert "login SUCCEEDED (token stored)" in out
    assert "a token IS stored" not in out


def test_a_4xx_auth_response_is_not_a_wiring_bug():
    out = _note(token=None, auth_status=[401])
    assert "the form IS wired" in out and "NOT a wiring bug" in out


def test_a_200_without_a_token_is_response_shape():
    out = _note(token=None, auth_status=[200])
    assert "response shape or post-login handling" in out


@pytest.mark.parametrize("auth_status,token", [
    ([], None), ([], "t"), ([200], None), ([401], None), ([400, 401], "t"), ([200, 500], "t"),
])
def test_every_failing_shape_yields_a_non_empty_note(auth_status, token):
    """A failing auth step with no note is the #1202wc shape: a hold nobody can act on."""
    assert _note(token=token, auth_status=auth_status).strip() != ""


# ------------------------------------------------------- the watcher's observed surface

def test_the_watcher_covers_the_frameworks_own_auth_surface():
    """`/oauth/token` is served by the framework's own AS and `"/auth/" in url` misses it."""
    pref = R._AUTH_OBSERVED_PREFIXES_1203G1
    for u in ("http://x/auth/login", "http://x/oauth/token",
              "http://x/api/auth/me", "http://x/api/oauth/token"):
        assert any(p in u for p in pref), u


def test_the_watcher_ignores_discovery_documents_and_business_paths():
    pref = R._AUTH_OBSERVED_PREFIXES_1203G1
    for u in ("http://x/.well-known/jwks.json", "http://x/api/feed", "http://x/health"):
        assert not any(p in u for p in pref), u


def test_the_watcher_list_is_imported_not_relisted():
    """`lifecycle` on this exact constant: "Six modules re-listed this surface and all six
    omitted the same three." The prefixes must come from the framework's own list.

    Asserted over the AST -- an `ImportFrom` that actually names the constant -- rather than a
    byte window before the definition (#943), and against the constant's VALUE, so a module
    that imports it and then ignores it still goes red."""
    import ast
    tree = ast.parse(inspect.getsource(R))
    imported = {a.asname or a.name
                for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) for a in n.names}
    assert "FRAMEWORK_AUTH_SURFACE_PREFIXES_1202vl" in {
        a.name for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) for a in n.names}, (
        "the auth surface must be imported, not re-listed; imported: %s" % sorted(imported))
    from env_generator.llm_generator.multi_agent.runtime.lifecycle import (
        FRAMEWORK_AUTH_SURFACE_PREFIXES_1202vl as fw)
    assert set(R._AUTH_OBSERVED_PREFIXES_1203G1) == {
        p for p in fw if "well-known" not in p}


def test_the_watcher_is_what_the_listener_uses():
    """Structural: the constant must be read inside the response handler, not merely defined.
    Anchored over the AST so a renamed-but-unused constant goes red."""
    import ast
    src = inspect.getsource(R)
    tree = ast.parse(src)
    found = False
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_on_auth_resp":
            names = {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}
            assert "_AUTH_OBSERVED_PREFIXES_1203G1" in names, sorted(names)
            found = True
    assert found, "_on_auth_resp not found -- the watcher moved"


# -------------------------------------------------------------- wiring into the walk

def test_the_import_has_no_fallback_copy():
    """The first version guarded this import with `except Exception:` and a hand-written copy of
    the prefixes -- and the import was wrong, so the copy was silently in use. A fallback here
    re-creates the drift the import prevents, and hides it; the user's standing rule is that a
    fallback which masks a failure should not exist. Pinned over the AST."""
    import ast
    tree = ast.parse(inspect.getsource(R))
    for node in ast.walk(tree):
        if isinstance(node, ast.Try):
            for h in node.handlers:
                body = ast.dump(ast.Module(body=node.body, type_ignores=[]))
                if "FRAMEWORK_AUTH_SURFACE_PREFIXES_1202vl" in body:
                    raise AssertionError(
                        "the auth-surface import is wrapped in try/except; a fallback copy "
                        "would mask a wrong import exactly as it did before")
    assert R._AUTH_OBSERVED_PREFIXES_1203G1, "the constant resolved empty"


def test_the_walk_uses_the_extracted_function():
    """The ladder must not be duplicated back inline.

    Over the AST, counting STRING CONSTANTS rather than source text: the first version of this
    test counted occurrences in the module source and read 3 for a phrase that appears once in
    code and twice in the comments explaining it. Every string carrying a ladder phrase must
    live inside `auth_note_1203g1`."""
    import ast
    tree = ast.parse(inspect.getsource(R))
    ladder = next(n for n in ast.walk(tree)
                  if isinstance(n, ast.FunctionDef) and n.name == "auth_note_1203g1")
    inside = {id(n) for n in ast.walk(ladder)}
    for phrase in ("the form is not wired to the API",
                   "the form IS wired but /auth returned",
                   "login SUCCEEDED (token stored)",
                   "NOT evidence the form is unwired"):
        holders = [n for n in ast.walk(tree)
                   if isinstance(n, ast.Constant) and isinstance(n.value, str)
                   and phrase in n.value]
        assert holders, phrase
        for h in holders:
            assert id(h) in inside, (
                "%r is built outside auth_note_1203g1 -- the ladder was duplicated" % phrase)
    assert "_auth_note = auth_note_1203g1(" in inspect.getsource(R)


def test_the_note_reaches_the_lane_through_format_feedback():
    """End-to-end on the consumer, not just the helper: `format_feedback` is what the P0 body
    is built from, and 205 corpus tasks carry this line -- so the note must survive it."""
    report = {"ran": True, "summary": "s", "steps": [
        {"step": "auth flow stores a token + navigates into the app", "ok": False,
         "note": _note(token="t", auth_status=[])}], "pages": []}
    body = R.format_feedback(report)
    assert "[FAIL] auth flow stores a token" in body
    assert "NOT evidence the form is unwired" in body
