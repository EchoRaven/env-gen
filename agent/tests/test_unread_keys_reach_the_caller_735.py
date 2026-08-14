r"""#735: the agent never learned. The warning went to a log a human reads afterwards.

The user's question — "so can it declare freely now, instead of us fixing one possible problem
per run?" — and the honest answer before this change was no.

    #731   warns about an unread schema key ... into the run LOG
    register_endpoint   returns the stored record, which says success

So an invented word was still dropped silently FROM THE CALLER'S POINT OF VIEW. Publishing the
vocabulary (#732/#733) removes the need to guess, but it does not close the loop: a lane that
invents anyway learns nothing, and the cadence stays "run once, a human reads the log, fix one
word" — exactly what was objected to.

A note on the RETURN closes it inside a single tool call. Not a rejection: the registration
stands and the key is kept, because #730's `query` showed an invented word can be the better one.
What changes is WHEN the caller finds out — the same turn instead of the next run.

That is the accurate scope: not "declare anything and it works", which would need the framework
to map arbitrary words semantically and is the thing that cannot be built. It is "declare
anything and find out immediately what the framework actually reads."
"""
import pathlib
import tempfile

import pytest

from env_generator.llm_generator.multi_agent.runtime.registryhub import (
    RegistryHub, _KNOWN_SCHEMA_KEYS_731 as KNOWN,
)


def _hub():
    d = tempfile.TemporaryDirectory()
    return RegistryHub(pathlib.Path(d.name)), d


# --- the caller is told --------------------------------------------------------------------------

def test_an_invented_key_comes_back_named():
    h, d = _hub()
    try:
        rec = h.register_endpoint("GET", "/api/a", schema={"filters": {"kind": "s"}},
                                  agent="backend")
        assert rec.get("_unread_schema_keys") == ["filters"]
    finally:
        d.cleanup()


def test_the_note_lists_what_the_framework_does_read():
    h, d = _hub()
    try:
        rec = h.register_endpoint("GET", "/api/a", schema={"filters": {}}, agent="backend")
        note = rec.get("_note") or ""
        assert "READ BY NOTHING" in note
        for slot in ("request", "response_key"):
            assert slot in note
    finally:
        d.cleanup()


def test_the_note_says_what_to_do():
    h, d = _hub()
    try:
        rec = h.register_endpoint("GET", "/api/a", schema={"zzz": 1}, agent="backend")
        assert "Re-register with the value under one of those names" in (rec.get("_note") or "")
    finally:
        d.cleanup()


def test_several_inventions_are_all_named():
    h, d = _hub()
    try:
        rec = h.register_endpoint("GET", "/api/a", schema={"zzz": 1, "aaa": 2}, agent="backend")
        assert rec["_unread_schema_keys"] == ["aaa", "zzz"]
    finally:
        d.cleanup()


# --- and stays quiet when there is nothing to say -----------------------------------------------------

def test_published_slots_produce_no_note():
    h, d = _hub()
    try:
        rec = h.register_endpoint("GET", "/api/b",
                                  schema={"request": {"kind": "s"}, "response_key": "items"},
                                  agent="backend")
        assert "_unread_schema_keys" not in rec and "_note" not in rec
    finally:
        d.cleanup()


def test_a_folded_synonym_produces_no_note_and_is_folded():
    """`query` is known AND folded — telling the caller off for it would be wrong twice."""
    h, d = _hub()
    try:
        rec = h.register_endpoint("GET", "/api/c", schema={"query": {"kind": "s"}},
                                  agent="backend")
        assert "_note" not in rec
        assert (rec.get("schema") or {}).get("request") == {"kind": "s"}
    finally:
        d.cleanup()


@pytest.mark.parametrize("schema", [None, {}, {"_private": 1}])
def test_degenerate_schemas_are_quiet(schema):
    h, d = _hub()
    try:
        rec = h.register_endpoint("GET", "/api/d", schema=schema, agent="backend")
        assert "_note" not in rec
    finally:
        d.cleanup()


def test_a_non_dict_schema_is_rejected_upstream_not_here():
    """`schema="junk"` never reaches the note: register_endpoint already raises on it. My first
    version listed it as a degenerate case to stay quiet on, which asserted the wrong contract —
    the framework refuses a non-dict schema outright, and that is correct."""
    h, d = _hub()
    try:
        with pytest.raises(Exception):
            h.register_endpoint("GET", "/api/z", schema="junk", agent="backend")
    finally:
        d.cleanup()


# --- it is a note, not a refusal ---------------------------------------------------------------------

def test_the_registration_still_succeeds():
    h, d = _hub()
    try:
        rec = h.register_endpoint("GET", "/api/e", schema={"zzz": 1}, agent="backend")
        assert rec.get("path") == "/api/e"
        assert (rec.get("schema") or {}).get("zzz") == 1, "the invented key must be KEPT"
    finally:
        d.cleanup()


def test_the_stored_record_is_not_polluted():
    """The note is on the RETURN. Persisting it would put framework chatter in the contract."""
    h, d = _hub()
    try:
        h.register_endpoint("GET", "/api/f", schema={"zzz": 1}, agent="backend")
        stored = h.get_endpoints().get("GET /api/f") or {}
        assert "_note" not in stored and "_unread_schema_keys" not in stored
    finally:
        d.cleanup()


# --- provenance -----------------------------------------------------------------------------------

def test_the_scope_is_stated_honestly():
    d = __doc__ or ""
    assert "not \"declare anything and it works\"" in d.replace("“", '"').replace("”", '"')
    assert "find out immediately" in d


def test_why_it_is_not_a_rejection_is_recorded():
    import inspect
    from env_generator.llm_generator.multi_agent.runtime import registryhub as rh
    src = inspect.getsource(rh.RegistryHub.register_endpoint)
    i = src.index("#735")
    block = " ".join(src[i:src.index("_unread = sorted", i)].replace("#", " ").split())
    assert "an invented word can be the better one" in block
    assert "same turn and losing a run" in block


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
