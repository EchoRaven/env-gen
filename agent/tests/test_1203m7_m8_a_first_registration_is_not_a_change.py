r"""#1203m7 + #1203m8: where the response key lives, and what a FIRST registration means.

#1203m7 — the breaking-change comparison read `metadata.response_key` only, while the block
twenty lines above it already reads "metadata OR schema" and says why. A lane that declares
the already-canonical `items` in the SCHEMA alone leaves metadata unset (the #1202zw mirror
only fires for a NON-canonical key), so both sides compare None. Measured over the 39 modern
runs' endpoint records: 713 carry the key in both places (34 disagreeing), 128 in metadata
only, and **201 in the schema only** — invisible. Readers are split the same way: 8 sites read
the endpoint top level, 3 the schema, this comparison metadata (#730's shape).

#1203m8 — with no previous version, `old_full` is all Nones and exactly two flags can still
fire: `response_key_changed` (None != "items") and `auth_added`. So declaring an endpoint for
the FIRST time minted a breaking-change record. Of the 955 modern endpoints carrying any
record, **888 (93%)** have an earliest record using only those two flags (447 / 287 / 154),
against 67 using a flag that needs both sides — and **34 of the 441 `Fix breaking change`
P0s** were filed within 2s of one. The rule was already one line below, in the auth-REMOVED
branch: `elif old and ...`.
"""
from __future__ import annotations

import ast
import inspect
import textwrap
from pathlib import Path

from env_generator.llm_generator.multi_agent.runtime.hub_registry import HubRegistry
from env_generator.llm_generator.multi_agent.runtime.registryhub import RegistryHub


def _rh(tmp):
    return HubRegistry(Path(tmp)).hubs.registryhub


def _records(rh):
    return [k for k in (rh._breaking_changes.value() or {}) if k != "_meta"]


def test_a_first_registration_records_nothing(tmp_path):
    rh = _rh(tmp_path)
    ep = rh.register_endpoint("GET", "/api/widgets",
                              schema={"response": {"a": "int"}},
                              provider="backend", agent="backend", response_key="items")
    assert _records(rh) == [], "declaring an endpoint is still reported as breaking it"
    assert ep.get("breaking_change") is None


def test_a_first_registration_that_requires_auth_records_nothing_either(tmp_path):
    """`auth_added` is the other flag that fires against an absent `old`."""
    rh = _rh(tmp_path)
    rh.register_endpoint("GET", "/api/widgets", schema={"response": {"a": "int"}},
                         provider="backend", agent="backend", auth_required=True)
    assert _records(rh) == []


def test_a_real_change_after_it_is_still_reported(tmp_path):
    """The regression direction: the guard must not swallow the second registration."""
    rh = _rh(tmp_path)
    rh.register_endpoint("GET", "/api/widgets", schema={"response": {"a": "int", "b": "str"}},
                         provider="backend", agent="backend", response_key="items")
    ep = rh.register_endpoint("GET", "/api/widgets", schema={"response": {"a": "int"}},
                              provider="backend", agent="backend", response_key="items")
    assert len(_records(rh)) == 1
    assert (ep.get("breaking_change") or {}).get("removed_response_fields") == ["b"]


def test_a_schema_only_response_key_change_is_now_visible(tmp_path):
    """#1203m7's gain: the 201 records whose key never reaches `metadata`.

    `item` -> `items` on purpose -- #1202zw/#46 coerce any OTHER business `/api/` key to the
    canonical envelope on first registration, and exempt exactly these two.
    """
    rh = _rh(tmp_path)
    rh.register_endpoint("GET", "/api/gadgets",
                         schema={"response": {"a": "int"}, "response_key": "item"},
                         provider="backend", agent="backend")
    ep = rh.register_endpoint("GET", "/api/gadgets",
                              schema={"response": {"a": "int"}, "response_key": "items"},
                              provider="backend", agent="backend")
    b = ep.get("breaking_change") or {}
    assert b.get("response_key_changed") is True
    assert b.get("response_key_change_1203m6") == "item -> items"


def test_the_metadata_copy_still_wins_when_the_two_disagree(tmp_path):
    """Precedence is metadata FIRST -- #1202zw calls it "read first by the gate".

    The fixture has to make the two copies disagree AND make the answer depend on the order,
    or it proves nothing: my first version registered the same schema key twice, so both
    orders compared equal and a flipped-precedence mutant survived. 34 of the corpus's 713
    both-places records carry disagreeing copies, so the order is a real decision.

    pass 1: metadata `items`, schema `item`.  pass 2: metadata still `items` (it merges
    forward), schema moved to `items`.
      metadata-first -> items vs items, nothing moved (correct: the key consumers read never
                        changed)
      schema-first   -> item vs items, a breaking change reported for a copy nobody reads
    """
    rh = _rh(tmp_path)
    rh.register_endpoint("GET", "/api/gadgets",
                         schema={"response": {"a": "int"}, "response_key": "item"},
                         provider="backend", agent="backend", response_key="items")
    ep = rh.register_endpoint("GET", "/api/gadgets",
                              schema={"response": {"a": "int"}, "response_key": "items"},
                              provider="backend", agent="backend")
    b = ep.get("breaking_change") or {}
    assert b.get("response_key_changed") in (None, False), \
        "the comparison followed the schema copy instead of the one the gate reads"


def test_the_guard_is_at_the_call_site_and_names_the_previous_version():
    """#1203m8 structurally: the comparator stays pure, the caller does the guarding.

    `detect_breaking_change` is handed two schemas by other callers (its own tests among
    them), so a guard inside it would change what they mean. Asserted on the AST of
    `register_endpoint`: the `if` that records must test `old`.
    """
    tree = ast.parse(textwrap.dedent(inspect.getsource(RegistryHub.register_endpoint)))
    recording = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue
        body = ast.unparse(node)
        if "_record_breaking_change" in body and "elif" not in body[:6]:
            recording.append(node)
    assert recording, "nothing records a breaking change any more"
    guard = ast.unparse(recording[0].test)
    assert "old" in guard, "a first registration can still be reported as a change"
    assert "is_breaking" in guard


def test_the_comparator_itself_was_not_changed(tmp_path):
    """Handed two schemas directly it still answers about the pair, as its callers expect."""
    out = _rh(tmp_path).detect_breaking_change({"response": {"a": "int", "b": "str"}},
                                               {"response": {"a": "int"}})
    assert out["is_breaking"] is True and out["removed_response_fields"] == ["b"]
