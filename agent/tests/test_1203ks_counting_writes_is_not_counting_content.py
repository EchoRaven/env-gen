"""#1203ks: #693's instrument is sound one way only, and the converse was read twice.

#693 says `_meta.version` counts writes exactly, so a store still at version 1 across every
kept run was never written by anybody. That direction holds. The converse does not:
`ensure_*_document` is itself a write, so version > 1 says the file was TOUCHED and nothing
about whether a record landed — and that is what #1202jh read as an "initialisation baseline"
and #695 quoted as "version 1 in 146 of 146" (corrected in #1203kq / #1203kr).

Re-verified on the instrument that does answer it: across 227 kept run directories all nine
stores #693 calls never-written/no-writer hold ZERO records, while the live ones hold records
in 197-208 runs (max 27-297). The nine also sit at max version 15 with version > 1 in 187
runs APIECE, identically — the lockstep signature of one shared upstream touch rather than
nine independent writers.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime.json_store import JsonStore  # noqa: E402
from multi_agent.runtime.registryhub import RegistryHub  # noqa: E402


def _doc_1203ks():
    """RegistryHub's docstring, whitespace-normalised.

    A sentence inside a docstring WRAPS, so a newline and indentation sit between its words
    and a raw `in` check fails on prose that is present. Third time today; the house pattern
    is this normalisation (see `test_dead_pr_tools_are_not_surfaced_695`).
    """
    return " ".join((RegistryHub.__doc__ or "").split())

_EMPTY_BY_DESIGN = ("examples", "mocks", "reviews", "seed_registrations",
                    "table_consumers", "table_breaking_changes",
                    "projects", "providers", "schemas")


def test_a_write_that_carries_no_record_still_moves_the_version_1203ks(tmp_path):
    """The converse, demonstrated on the primitive #693 reasons about."""
    st = JsonStore(tmp_path / "s.json")
    st.update(lambda d: d)
    v1 = st.get_version()
    for _ in range(4):
        st.update(lambda d: d)
    assert st.get_version() > v1, "a no-op update is still a write to the version"
    assert [k for k in (st.value() or {}) if k != "_meta"] == [], (
        "and it carried no record — which is why version > 1 cannot mean content landed")


def test_the_one_directional_reading_still_holds_1203ks(tmp_path):
    """#693's actual claim: a store nobody ever wrote cannot be above its creation version."""
    st = JsonStore(tmp_path / "t.json")
    before = st.get_version()
    assert [k for k in (st.value() or {}) if k != "_meta"] == []
    assert st.get_version() == before, "reading must not bump it"


def test_the_docstring_states_the_limit_where_the_instrument_is_defined_1203ks():
    """#1032: it was misread twice, so the limit belongs next to the rule, not in the two
    places that misread it."""
    doc = _doc_1203ks()
    assert "Counting writes is not counting CONTENT" in doc, doc[:600]
    assert "ensure_*_document` is itself a write" in doc, doc[:600]
    assert "#1203ks" in doc
    for t in ("#1202jh", "#695"):
        assert t in doc, ("name who misread it, so the next reader can check", t)


def test_the_finding_is_restated_on_the_record_count_1203ks():
    doc = _doc_1203ks()
    assert "hold ZERO records" in doc, doc[:800]
    assert "227 kept run directories" in doc, doc[:800]
    for name in _EMPTY_BY_DESIGN:
        assert name.upper() in doc or name in doc, name
