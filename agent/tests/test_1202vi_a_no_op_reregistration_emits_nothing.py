"""#1202vi — 1875 events for 192 facts, all to zero recipients, on every write.

Lanes re-register the same consumer every pass. The durable store dedups on its key, so
the fact is written once; `_emit` fired on every call. Corpus-wide that is 103471
`consumer_registered` events carrying 17836 distinct registrations (-83%), occupying
20-33% of the events file in the worst runs — a file JsonStore rewrites IN FULL on every
publish by every agent.

Measured on tiktok-r133's real 4.91 MB store: one publish_event is three whole-file
updates, the events one costs 79 ms (46 ms parse + 27 ms serialize), and five concurrent
writers serialize to a 709 ms median. Every byte of this payload is charged to every
broadcast and send_message for the rest of the run.
"""
import pathlib

import pytest

from env_generator.llm_generator.multi_agent.runtime.registryhub import (
    _same_consumer_1202vi as same,
)

_SRC = pathlib.Path(
    __file__).resolve().parents[1] / (
    "env_generator/llm_generator/multi_agent/runtime/registryhub.py")

# r133's real record shape.
_REC = {"id": "POST /auth/login:ui_component:login_modal:frontend",
        "endpoint_id": "POST /auth/login", "file_path": "ui_component:login_modal",
        "agent": "frontend", "metadata": {}, "created_at": 1790295947.45,
        "_updated_by": "frontend", "_updated_at": 1790295947.45}


def test_a_repeat_registration_differing_only_in_timestamps_is_a_no_op():
    later = {**_REC, "created_at": 1790299999.9, "_updated_at": 1790299999.9}
    assert same(_REC, later) is True


def test_the_first_registration_is_never_a_no_op():
    """No prior record — the event that says when this consumer appeared must still fire."""
    assert same(None, _REC) is False
    assert same({}, _REC) is False


@pytest.mark.parametrize("field, value", [
    ("metadata", {"expected_schema": {"id": "int"}}),
    ("agent", "verifier"),
    ("file_path", "ui_page:profiles_page"),
    ("endpoint_id", "GET /api/profiles"),
    ("_updated_by", "backend"),
])
def test_any_real_change_still_emits(field, value):
    assert same(_REC, {**_REC, field: value}) is False


def test_timestamps_must_be_excluded_or_the_check_never_fires():
    """`created_at` and `_updated_at` are rewritten on every call by construction, so a
    naive equality would report 'changed' every time and save nothing."""
    assert same(_REC, {**_REC, "created_at": _REC["created_at"] + 1}) is True
    assert same(_REC, {**_REC, "_updated_at": _REC["_updated_at"] + 1}) is True


def test_a_non_dict_prior_is_treated_as_new():
    assert same("junk", _REC) is False
    assert same(_REC, None) is False


def test_the_durable_write_is_not_skipped():
    """Only the EMIT is conditional. `#693` reads `_meta.version` as a forensic instrument
    across the corpus and `test_update_always_bumps_the_version` ratchets it, so the
    store update must run on every call — including the no-op ones."""
    src = _SRC.read_text()
    block = src[src.index("_prior_1202vi = "):src.index("return consumer",
                                                        src.index("_prior_1202vi = "))]
    update_at = block.index("self._consumers.update(")
    guard_at = block.index("if not _same_consumer_1202vi(")
    assert update_at < guard_at, "the store write must not be inside the guard"
    assert "self._emit(" in block[guard_at:]


def test_the_prior_is_read_before_the_write():
    """Reading after the update would compare the record against itself and the guard
    would fire on the FIRST registration too, losing the one event worth keeping."""
    src = _SRC.read_text()
    block = src[src.index("_prior_1202vi = "):src.index("return consumer",
                                                        src.index("_prior_1202vi = "))]
    assert block.index("_prior_1202vi = ") < block.index("self._consumers.update(")


def test_the_table_consumer_sibling_carries_the_same_guard():
    """0 occurrences in the whole corpus, so there is nothing measured to suppress there.
    It is kept identical only so the two copies of one rule cannot drift apart — which is
    exactly what #1032 cost, and what the `components`-only patch in #1202vh's drop point
    had already cost once."""
    src = _SRC.read_text()
    block = src[src.index("self._table_consumers.update("):]
    block = block[:block.index("return consumer") + 16]
    assert "_same_consumer_1202vi(_prior_1202vi, consumer)" in block
    assert block.index("self._table_consumers.update(") < block.index(
        "if not _same_consumer_1202vi(")
