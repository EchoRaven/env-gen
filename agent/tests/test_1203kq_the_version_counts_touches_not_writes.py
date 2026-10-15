"""#1203kq: `_meta.version` is not a write count for a store something else touches.

#697 established that CodeHub's review/PR surface is empty by design, and read the evidence
off `_meta.version` — "all at version 1 in 146 of 146", citing #693 for why that is a write
count. The conclusion is right and the instrument is confounded: `ensure_codehub_document`
bumps the version when it TOUCHES a document, so a store can sit above 1 holding nothing.

Measured over 227 run directories: the four "never written" stores show version > 1 in 186 of
them, and identically — which is the tell, since four unrelated stores cannot be written in
lockstep. In the modern era `codehub_code_reviews.json` is version 2, 3 and 6 in three runs
with ZERO records and `last_modified_by: ensure_codehub_document` in every one.

So this pins the right instrument: count the records.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import pytest  # noqa: E402

from multi_agent.runtime.hubs.codehub.service import CodeHub  # noqa: E402

_EMPTY_BY_DESIGN = ("pull_requests", "review_threads", "code_reviews", "repos")


@pytest.fixture()
def hub(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    return CodeHub(repo, tmp_path / "hubs")


def test_a_touched_store_can_sit_above_version_one_with_no_records_1203kq(hub):
    """The confound itself, reproduced: ensure/touch moves the version, not the content."""
    store = hub.stores.code_reviews
    before = store.get_version()
    for _ in range(3):
        store.update(lambda d: d)          # a no-op write is still a write to the version
    assert store.get_version() > before, "the fixture must move the version"
    assert [k for k in (store.value() or {}) if k != "_meta"] == [], (
        "and it must still hold nothing — which is exactly why the version cannot carry the "
        "claim #697 read off it")


def test_the_record_count_is_the_instrument_1203kq(hub):
    for name in _EMPTY_BY_DESIGN:
        recs = [k for k in (getattr(hub.stores, name).value() or {}) if k != "_meta"]
        assert recs == [], (name, recs)


def test_the_docstring_says_which_instrument_to_use_1203kq():
    """#1032: the correction has to live where the claim does, or the next reader repeats it."""
    doc = CodeHub.__doc__ or ""
    assert "COUNT THE RECORDS" in doc, doc[-400:]
    # The MECHANISM sentence, not just the identifier: the name also appears later in the
    # modern-era evidence line, so `"ensure_codehub_document" in doc` was satisfied by either.
    # Found by a mutation that removed only the explanatory one.
    assert "`ensure_codehub_document` bumps the version" in doc, (
        "say WHAT moves the version, in the sentence that explains why it is not a write "
        "count:\n" + doc[-600:])
    assert "#1203kq" in doc


def test_the_conclusion_is_not_softened_1203kq():
    """The instrument changed; the finding did not."""
    doc = CodeHub.__doc__ or ""
    assert "never written" in doc and "commit-and-check, not GitHub" in doc
    for name in _EMPTY_BY_DESIGN:
        assert name in doc, name
