r"""#730: the lane declared the query parameters. Nothing read them.

I traced the largest functional defect — four of five identical-content route groups are pages
fetching an unfiltered `/api/titles` — back to "the contract does not declare query params", and
changed the backend prompt (#729) to ask for them. The diagnosis was wrong.

r148's `GET /api/titles` record:

    "schema": {"query": {"kind": "string?", "limit": "integer?"}, ...}

The lane declared them. It used `query`, which is the natural word for query parameters. Every
consumer in the framework reads `schema.request` — validation_runner:597,
database_scaffold:350, scaffolder:517, #708b's filter hint — and **nothing reads
`schema.query`**. The declaration was written, stored, and invisible.

    r146   schema.query 0   schema.request 10
    r147   schema.query 0   schema.request 10
    r148   schema.query 3   schema.request  6

So r148 is the first run to use the synonym, and my "3 -> 1 -> 0 decline" in #729 was counting
only one of the two spellings. The decline is real for `request`; the information was not lost,
it moved.

Normalising on WRITE is one place instead of four, and it recovers a declaration whichever word
the lane picks. `request` wins on conflict because it is what the consumers already act on.
#729's prompt guidance stays — it makes the canonical spelling explicit — but as a preference,
not as the fix.
"""
import json
from pathlib import Path

import pytest

from env_generator.llm_generator.multi_agent.runtime.registryhub import (
    _merge_query_alias_730 as merge,
)


# --- the real shape ------------------------------------------------------------------------------

def test_r148s_actual_record_is_recovered():
    out = merge({"query": {"kind": "string?", "limit": "integer?"}, "response_key": "items"})
    assert out["request"] == {"kind": "string?", "limit": "integer?"}


def test_the_lanes_own_wording_survives():
    """Folding must not erase what the lane wrote — the record should still show its choice."""
    out = merge({"query": {"kind": "string?"}})
    assert out["query"] == {"kind": "string?"}


def test_other_schema_keys_are_untouched():
    out = merge({"query": {"a": "1"}, "response_key": "items", "auth_required": False})
    assert out["response_key"] == "items" and out["auth_required"] is False


# --- conflicts and degenerate input ------------------------------------------------------------------

def test_an_existing_request_key_wins():
    out = merge({"query": {"kind": "a"}, "request": {"kind": "b", "genre": "c"}})
    assert out["request"] == {"kind": "b", "genre": "c"}


def test_query_only_keys_are_still_merged_in():
    out = merge({"query": {"kind": "a", "limit": "1"}, "request": {"kind": "b"}})
    assert out["request"] == {"kind": "b", "limit": "1"}


@pytest.mark.parametrize("schema", [
    {}, {"response_key": "items"}, {"query": {}}, {"query": None},
    {"query": "notadict"}, None, "junk", 42, [],
])
def test_degenerate_input_passes_through(schema):
    merge(schema)


def test_a_non_dict_request_is_left_alone():
    """Something else is going on; do not guess."""
    out = merge({"query": {"a": 1}, "request": "weird"})
    assert out["request"] == "weird"


def test_it_never_raises():
    class _Bad(dict):
        def get(self, *a, **k):
            raise RuntimeError("boom")
    merge(_Bad())


# --- it is wired on the write path ----------------------------------------------------------------

def test_register_endpoint_normalises():
    import inspect
    from env_generator.llm_generator.multi_agent.runtime import registryhub as rh
    src = inspect.getsource(rh.RegistryHub.register_endpoint)
    assert "_merge_query_alias_730(" in src


# --- the evidence, re-derived from disk ---------------------------------------------------------------

@pytest.mark.parametrize("run,q,r", [
    ("netflix-web-r146", 0, 10), ("netflix-web-r147", 0, 10), ("netflix-web-r148", 3, 6)])
def test_the_two_spellings_reproduce(run, q, r):
    root = Path(__file__).resolve().parents[2] / "generated" / run / "shared" / "hubs"
    if not root.is_dir():
        pytest.skip(f"{run} not on disk")
    d = json.loads((root / "registryhub_endpoints.json").read_text())
    recs = [v for k, v in d.items() if not k.startswith("_") and isinstance(v, dict)]
    assert sum(1 for v in recs if (v.get("schema") or {}).get("query")) == q
    assert sum(1 for v in recs if (v.get("schema") or {}).get("request")) == r


def test_nothing_else_reads_the_query_key():
    """If a reader for `schema.query` ever appears, this fold becomes redundant and should go."""
    import re, inspect
    from env_generator.llm_generator.multi_agent.runtime import registryhub as rh
    own = inspect.getsource(rh._merge_query_alias_730)      # the fold itself reads it by design
    root = Path(__file__).resolve().parents[1] / "env_generator" / "llm_generator"
    pat = re.compile(r'schema[^\n]{0,20}\.get\("query"\)|\["schema"\]\["query"\]')
    hits = []
    for f in root.rglob("*.py"):
        body = f.read_text(errors="ignore").replace(own, "")
        if pat.search(body):
            hits.append(f.name)
    assert not hits, f"a schema.query reader now exists, so this fold is redundant: {hits}"


# --- provenance -------------------------------------------------------------------------------------

def test_the_wrong_diagnosis_is_recorded():
    d = " ".join((merge.__doc__ or "").split())
    assert "730" in d


def test_the_call_site_records_what_it_replaced():
    import inspect
    from env_generator.llm_generator.multi_agent.runtime import registryhub as rh
    src = inspect.getsource(rh.RegistryHub.register_endpoint)
    i = src.index("#730")
    block = " ".join(src[i:src.index('"schema":', i)].replace("#", " ").split())
    assert "the lane DID declare, in a synonym" in block
    assert "one place instead of four" in block


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
