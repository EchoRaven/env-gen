r"""#606: a LIST tool should return a listing, not every document's full body.

Third finding on the cost axis, after #604 (check_inbox re-serialising already-read durable
bodies) and #605 (a terminal task action echoing back the work order).

`workhub_list_documents` returned every document's FULL record — logged at up to **204,469 chars
(~51k tokens) in ONE call**, averaging 22.6k. Over the arc's 227 stored documents the `metadata`
field alone is **4.60 MB of the 4.69 MB total** (meeting decisions, data models, contracts all
live there) and a single document reaches **102,405 chars**.

The content path already exists and is the right one: `workhub_get_document(document_id)`.
Elided with #605's shared field-by-field helper, so id/kind/status/title and every other small
field stay byte-identical. Measured on the real store, an id/kind/status/title listing is **99%
smaller** (4.69 MB -> 0.05 MB).
"""
import asyncio
import inspect
import json

import pytest

from env_generator.llm_generator.tools import hub_tools as ht


class _Hub:
    def __init__(self, docs):
        self._docs = docs

    def list_documents(self, kind=None, status=None):
        return self._docs


class _Hubs:
    def __init__(self, docs):
        self.workhub = _Hub(docs)


def _run(docs):
    tool = ht.WorkHubListDocumentsTool.__new__(ht.WorkHubListDocumentsTool)
    tool._hubs = _Hubs(docs)
    tool._agent_id = "orchestrator"
    return asyncio.run(tool._run()).data["documents"]


_BIG = {"id": "doc_1", "kind": "meeting", "status": "closed", "title": "M1 kickoff",
        "created_by": "orchestrator", "metadata": {"decisions": ["x" * 102000]}}


# --- the trim -------------------------------------------------------------------------------

def test_the_bulk_metadata_is_elided_with_a_pointer_to_the_content_tool():
    out = _run({"doc_1": dict(_BIG)})["doc_1"]
    assert "chars omitted" in out["metadata"]
    assert "workhub_get_document(document_id='doc_1')" in out["metadata"]


def test_every_listing_field_is_byte_identical():
    out = _run({"doc_1": dict(_BIG)})["doc_1"]
    for f in ("id", "kind", "status", "title", "created_by"):
        assert out[f] == _BIG[f], f


def test_a_small_document_passes_through_whole():
    small = {"id": "doc_2", "kind": "note", "title": "short", "metadata": {"a": 1}}
    assert _run({"doc_2": dict(small)})["doc_2"] == small


def test_a_LIST_shaped_store_is_handled_too():
    out = _run([dict(_BIG)])
    assert isinstance(out, list) and "chars omitted" in out[0]["metadata"]
    assert "document_id='doc_1'" in out[0]["metadata"]


def test_an_empty_or_missing_store_is_inert():
    assert _run({}) == {}
    assert _run([]) == []
    assert _run(None) == []


def test_junk_entries_do_not_crash():
    out = _run({"a": None, "b": "nope", "c": 7})
    assert set(out) == {"a", "b", "c"}


def test_the_real_store_shape_shrinks():
    """The measured composition: metadata is ~98% of the bytes."""
    out = _run({"doc_1": dict(_BIG)})["doc_1"]
    assert len(json.dumps(out)) < len(json.dumps(_BIG)) / 50


# --- what must NOT change ----------------------------------------------------------------------

def test_the_content_tool_is_untouched():
    src = inspect.getsource(ht.WorkHubGetDocumentTool)
    assert "_elide_large_fields" not in src


def test_it_reuses_the_605_helper_rather_than_a_second_implementation():
    src = inspect.getsource(ht.WorkHubListDocumentsTool)
    assert "_elide_large_fields(" in src
    assert "chars omitted" not in src.replace("_elide_large_fields", "")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
