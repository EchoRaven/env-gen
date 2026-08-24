"""chain_executor: tolerate the two recurring verifier chain-authoring slips
that 422-block business_chain forever (observed live on the smoke-notes run,
2026-06-19/20):

1. OpenAPI path-param style — the verifier authors "/api/notes/{id}" instead of
   the chain's "${id}" substitution form, so the literal "{id}" reaches the
   backend int path param → 422.
2. REVERSED save mapping — the contract is save:{var_name: response_dotted_path},
   but the verifier inverts it: save:{"id": "note_id"} (meaning "save var note_id
   from response field id"). The forward dig (response."note_id") misses, so a
   later "${note_id}" step sends the literal token → 422.

Both are now absorbed deterministically in chain_executor so a verifier slip can
no longer permanently break the chain.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for p in (str(ROOT), str(LLM_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

from multi_agent.runtime import chain_executor as ce  # noqa: E402
from multi_agent.runtime.chain_executor import _subst, execute_chain, _dig  # noqa: E402


# --------------------------- _dig leaf fallback -----------------------------

def test_dig_leaf_fallback_resolves_resource_prefixed_path():
    # verifier prefixes the save-path with a wrong wrapper/resource key
    # (save {note_id: 'note.id'}); the canonical response is {item:{id}}.
    assert _dig({"item": {"id": 42}}, "note.id") == 42
    assert _dig({"item": {"id": 7}}, "data.id") == 7
    assert _dig({"items": [{"id": 9}]}, "post.id") == 9


def test_dig_normal_paths_unaffected():
    assert _dig({"item": {"id": 5}}, "item.id") == 5   # canonical envelope path
    assert _dig({"item": {"id": 9}}, "id") == 9         # bare leaf via envelope
    assert _dig({"id": 3}, "id") == 3                    # flat
    assert _dig({"a": {"b": 1}}, "a.b") == 1             # genuine nested NOT overridden


def test_dig_missing_leaf_returns_none():
    # no leaf match anywhere → honest None (not a wrong-field grab)
    assert _dig({"item": {"id": 1}}, "note.slug") is None


# ----------------------------- _subst --------------------------------------

def test_subst_bare_brace_openapi_style():
    # "{id}" (no leading $) is the common OpenAPI path-param confusion — accepted
    # only in bare (path) mode.
    assert _subst("/api/notes/{id}", {"id": "5"}, bare=True) == "/api/notes/5"


def test_subst_dollar_brace_still_works():
    assert _subst("/api/notes/${id}", {"id": "5"}, bare=True) == "/api/notes/5"
    # ${var} works without bare too (bodies use this form).
    assert _subst("${id}", {"id": "5"}) == "5"


def test_subst_dollar_brace_leaves_no_bare_brace_behind():
    # ${id} must be consumed by the ${} pass so the bare {id} pass can't
    # double-fire on a leftover "{id}".
    assert _subst("/api/notes/${id}", {"id": "5"}, bare=True) == "/api/notes/5"
    assert "{id}" not in _subst("/x/${id}/y/${id}", {"id": "7"}, bare=True)


def test_subst_bare_brace_NOT_applied_to_bodies():
    # NIT 2: a JSON body string leaf containing a literal "{rand}"/"{id}" must NOT
    # be rewritten — bare-brace substitution is path-only (bare defaults False).
    body = {"caption": "use {id} as a placeholder", "n": "{rand}"}
    assert _subst(body, {"id": "5", "rand": "999"}) == body
    # but ${rand} in a body IS substituted (canonical form).
    assert _subst({"email": "u${rand}@x.com"}, {"rand": "999"}) == {"email": "u999@x.com"}


def test_subst_unknown_var_untouched():
    # A brace token with no matching variable is left as-is (no crash).
    assert _subst("/api/notes/{missing}", {"id": "5"}, bare=True) == "/api/notes/{missing}"


def test_subst_var_namespaced_form():
    # ${var.<name>} (a var-namespaced form some verifiers author) resolves the
    # same as ${<name>} — live: login email "${var.user_email}", note path
    # "/api/notes/${var.note_id}".
    assert _subst("${var.user_email}", {"user_email": "u@x.com"}) == "u@x.com"
    assert _subst("/api/notes/${var.note_id}", {"note_id": "42"}, bare=True) == "/api/notes/42"
    # bare {var.<name>} on a path too
    assert _subst("/api/notes/{var.id}", {"id": "9"}, bare=True) == "/api/notes/9"
    # unknown namespaced var left literal (honest failure, not silent-wrong)
    assert _subst("${var.nope}", {"id": "5"}) == "${var.nope}"
    # body: ${var.x} substituted, but a bare {var.x} literal in a body is NOT
    assert _subst({"e": "${var.id}", "lit": "{var.id}"}, {"id": "5"}) == {"e": "5", "lit": "{var.id}"}


def test_subst_substring_var_not_eaten():
    # var "id" must not eat "{userid}"/"{idx}" — the closing brace must follow.
    assert _subst("/api/{userid}/{idx}", {"id": "5"}, bare=True) == "/api/{userid}/{idx}"


# --------------------------- execute_chain ---------------------------------

class _FakeHTTP:
    """Records requested paths and returns canned responses by (method, path-stem).

    path-stem = path with any trailing /<numeric-id> dropped, so /api/notes/5
    maps to the same handler as /api/notes/{id}."""

    def __init__(self, responses):
        self._responses = responses
        self.calls = []  # (method, full_url)

    def __call__(self, method, url, token=None, body=None, **_kw):
        self.calls.append((method, url))
        # strip base → path
        path = "/" + url.split("/", 3)[3] if url.count("/") >= 3 else url
        stem = path.rstrip("/")
        # collapse a trailing numeric segment to {id}
        parts = stem.split("/")
        if parts and parts[-1].isdigit():
            parts[-1] = "{id}"
            stem = "/".join(parts)
        key = (method.upper(), stem)
        return self._responses.get(key, {"status": 404, "body_text": "{}"})


def _run(monkeypatch_target_responses, chain):
    fake = _FakeHTTP(monkeypatch_target_responses)
    orig = ce._http
    ce._http = fake
    try:
        return fake, execute_chain("http://x", chain)
    finally:
        ce._http = orig


def test_reversed_save_mapping_resolves_note_id():
    # save:{"id":"note_id"} is REVERSED; response is the canonical {item:{id:..}}
    # envelope. The later ${note_id} step must resolve to the created id.
    responses = {
        ("POST", "/api/notes"): {"status": 201, "body_text": '{"item": {"id": 42}}'},
        ("GET", "/api/notes/{id}"): {"status": 200, "body_text": '{"item": {"id": 42}}'},
    }
    chain = {"name": "flow_notes_crud", "steps": [
        {"action": "create", "method": "POST", "path": "/api/notes",
         "body": {"title": "t"}, "expect": [201, 200], "save": {"id": "note_id"}},
        {"action": "read", "method": "GET", "path": "/api/notes/${note_id}",
         "expect": [200]},
    ]}
    fake, result = _run(responses, chain)
    # the GET must have been issued against the substituted id, not the literal
    assert ("GET", "http://x/api/notes/42") in fake.calls
    assert result["broken"] == [], result["broken"]


def test_openapi_brace_path_resolves():
    # save is correct ({"id":"item.id"}) but the path uses "{id}" not "${id}".
    responses = {
        ("POST", "/api/notes"): {"status": 201, "body_text": '{"item": {"id": 7}}'},
        ("GET", "/api/notes/{id}"): {"status": 200, "body_text": '{"item": {"id": 7}}'},
    }
    chain = {"name": "notes_crud_chain", "steps": [
        {"action": "create", "method": "POST", "path": "/api/notes",
         "body": {"title": "t"}, "expect": [201, 200], "save": {"id": "item.id"}},
        {"action": "read", "method": "GET", "path": "/api/notes/{id}",
         "expect": [200]},
    ]}
    fake, result = _run(responses, chain)
    assert ("GET", "http://x/api/notes/7") in fake.calls
    assert result["broken"] == [], result["broken"]


def test_scalar_expect_does_not_crash_runner():
    # verifier wrote expect: 201 (scalar) instead of [201]; iterating the int
    # crashed the WHOLE runner -> business_chain failed for every chain (smoke #10).
    responses = {
        ("POST", "/api/notes"): {"status": 201, "body_text": '{"item": {"id": 3}}'},
        ("GET", "/api/notes/{id}"): {"status": 200, "body_text": '{"item": {"id": 3}}'},
    }
    chain = {"name": "scalar_expect", "steps": [
        {"action": "create", "method": "POST", "path": "/api/notes",
         "body": {"t": "x"}, "expect": 201, "save": {"note_id": "item.id"}},  # scalar
        {"action": "read", "method": "GET", "path": "/api/notes/${note_id}",
         "expect": 200},  # scalar
    ]}
    fake, result = _run(responses, chain)  # must not raise
    assert ("GET", "http://x/api/notes/3") in fake.calls
    assert result["broken"] == [], result["broken"]


def test_correct_forward_mapping_is_not_disturbed():
    # save:{"note_id":"id"} is CORRECT; reversed tolerance must NOT fire/override.
    responses = {
        ("POST", "/api/notes"): {"status": 201, "body_text": '{"id": 99}'},
        ("GET", "/api/notes/{id}"): {"status": 200, "body_text": '{"id": 99}'},
    }
    chain = {"name": "ok", "steps": [
        {"action": "create", "method": "POST", "path": "/api/notes",
         "body": {"title": "t"}, "expect": [201], "save": {"note_id": "id"}},
        {"action": "read", "method": "GET", "path": "/api/notes/${note_id}",
         "expect": [200]},
    ]}
    fake, result = _run(responses, chain)
    assert ("GET", "http://x/api/notes/99") in fake.calls
    assert result["broken"] == [], result["broken"]


def test_reversed_fallback_does_not_clobber_earlier_correct_var():
    # NIT 1: step 1 correctly sets note_id=10; a later reversed slip
    # save:{"id":"note_id"} with response {id:99} must NOT overwrite note_id.
    responses = {
        ("POST", "/api/notes"): {"status": 201, "body_text": '{"id": 10}'},
        ("POST", "/api/notes/{id}/tag"): {"status": 201, "body_text": '{"id": 99}'},
        ("GET", "/api/notes/{id}"): {"status": 200, "body_text": '{"id": 10}'},
    }
    chain = {"name": "noclobber", "steps": [
        # correct forward mapping → note_id = 10
        {"action": "create", "method": "POST", "path": "/api/notes",
         "body": {"t": "x"}, "expect": [201], "save": {"note_id": "id"}},
        # later reversed slip returning a DIFFERENT id; must not clobber note_id
        {"action": "tag", "method": "POST", "path": "/api/notes/${note_id}/tag",
         "body": {"x": "y"}, "expect": [201], "save": {"id": "note_id"}},
        # read must still target the ORIGINAL note_id=10
        {"action": "read", "method": "GET", "path": "/api/notes/${note_id}",
         "expect": [200]},
    ]}
    fake, result = _run(responses, chain)
    assert ("GET", "http://x/api/notes/10") in fake.calls
    assert ("GET", "http://x/api/notes/99") not in fake.calls
    assert result["broken"] == [], result["broken"]


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
