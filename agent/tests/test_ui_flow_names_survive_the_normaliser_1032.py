r"""#1032: the orchestrator's copy of the validation normaliser dropped `name`, so every
failing UI flow was labelled `?`.

`_ui_evidence_breadth_739` labels a UI record by
`metadata.page / route / name`, else `record["name"].split(":")[-1]`, else `"?"`.

There are TWO normalisers producing those records:

    hub_registry.get_validation_results   sets "name": check.get("name", "")
    orchestrator._get_validation_results  did NOT — and this is the one the gate receives

The orchestrator copy's own docstring says *"#193: same canonical status vocabulary +
nested-metadata flatten as hub_registry.get_validation_results — the two readers must agree."*
They did not agree, on exactly one key.

Consequence, live in r174: six distinct failing flows all resolved to `"?"`, `sorted(set(...))`
collapsed them to one, and #1017 printed

    #1017 validation_ui_evidence_failed on 6 record(s): ?

i.e. #1029 fixed the COUNT and the label was still blank — on the most common live blocker
(`validation_ui_evidence_failed`, 7 of the last 10 STUCK runs). The real names were sitting in
the store the whole time:

    authentication, catalog_to_playback, profile_creation, rating, search_and_filter, sign_out

A duplicated normaliser that drifted on one key — `grep-the-literal-not-the-constant`: a value
duplicated under one NAME is a promise, under two names usually two concepts.

Fixed on both sides deliberately, because either alone would have done it and the pair is
cheap:
  * the orchestrator record carries `name` again, plus #236's check/flow derivation it was
    also missing (hub_registry has it; without it a bare ui_flow record is invisible to
    flow_coverage — the exact failure #236 records).
  * the extractor prefers `metadata.flow`, which #236 sets from the check name precisely to
    identify a flow, so it no longer depends on which copy of the normaliser produced the
    record.
"""
import inspect

import pytest

from env_generator.llm_generator.multi_agent import orchestrator as O
from env_generator.llm_generator.multi_agent.runtime.delivery_gate import (
    _ui_evidence_breadth_739 as breadth)
from env_generator.llm_generator.multi_agent.runtime.hub_registry import (
    _canon_validation_status, _flatten_validation_metadata)

_FLOWS = ("authentication", "catalog_to_playback", "profile_creation")


def _check(flow, status="failure"):
    return {"id": f"check_main_validation:ui_flow:{flow}", "pr_id": "main",
            "name": f"validation:ui_flow:{flow}", "status": status,
            "evidence": {"summary": f"{flow} fails",
                         "metadata": {"check": "ui_flow", "flow": flow}},
            "updated_at": 1.0}


def _orch_record(c, *, with_name):
    """The orchestrator's record shape, with `name` present or absent."""
    ev = c.get("evidence", {}) or {}
    r = {"task_id": c.get("name", "").removeprefix("validation:"),
         "status": _canon_validation_status(c.get("status", "error")),
         "metadata": _flatten_validation_metadata(ev),
         "recorded_at": c.get("updated_at", 0)}
    if with_name:
        r["name"] = c.get("name", "")
    return r


def _old_page(r):
    """The PRE-#1032 label expression, verbatim — the control."""
    meta = r.get("metadata", {}) or {}
    return str(meta.get("page") or meta.get("route") or meta.get("name")
               or str(r.get("name") or "").split(":")[-1] or "?")


# --- the control: the defect, reproduced ---------------------------------------------------

def test_the_control_collapses_every_flow_to_one_questionmark():
    """★ Without this, the tests below would pass on a build that never had the bug."""
    recs = [_orch_record(_check(f), with_name=False) for f in _FLOWS]
    assert sorted({_old_page(r) for r in recs}) == ["?"]


# --- fix A: the record carries `name` again ---------------------------------------------------

def test_the_orchestrator_record_carries_name():
    src = inspect.getsource(O.EnvGenOrchestrator._get_validation_results
                            if hasattr(O, "EnvGenOrchestrator") else O)
    assert '"name": c.get("name", "")' in src, (
        "the orchestrator normaliser dropped `name` again — the two readers must agree")


def test_restoring_name_alone_fixes_the_label():
    recs = [_orch_record(_check(f), with_name=True) for f in _FLOWS]
    assert sorted({_old_page(r) for r in recs}) == sorted(_FLOWS)


def test_the_orchestrator_derives_check_and_flow_like_hub_registry():
    """#236's other half, which this copy was also missing."""
    src = inspect.getsource(O)
    i = src.index("def _get_validation_results")
    block = src[i:src.index("def _get_validation_summary", i)]
    assert 'setdefault("check", _parts[1])' in block
    assert 'setdefault("flow", _parts[2])' in block


# --- fix B: the extractor prefers the semantically correct field --------------------------------

def test_flow_is_preferred_over_the_older_spellings():
    """Anchored on the statement's own end, not a byte count — a fixed-width window moves the
    moment the comment above it grows (I have now made that mistake three times in one day)."""
    src = inspect.getsource(breadth)
    i = src.index("page = str(")
    stmt = src[i:src.index("\n", src.index('or "?")', i))]
    assert 'meta.get("flow")' in stmt
    assert stmt.index('meta.get("flow")') < stmt.index('meta.get("page")'), (
        "flow must be tried FIRST — it is the field #236 sets for exactly this purpose")


def test_the_extractor_names_flows_even_without_a_record_name():
    """Belt and suspenders: works on the orchestrator's OLD shape too."""
    recs = [_orch_record(_check(f), with_name=False) for f in _FLOWS]
    assert breadth(recs)["pages_failed"] == sorted(_FLOWS)


def test_it_still_names_them_when_only_the_record_name_exists():
    """A record with no metadata at all must still be labelled from its name."""
    recs = [{"name": f"validation:ui_flow:{f}", "status": "failure"} for f in _FLOWS]
    assert breadth(recs)["pages_failed"] == sorted(_FLOWS)


def test_passed_and_failed_are_separated():
    recs = [_orch_record(_check("authentication"), with_name=True),
            _orch_record(_check("my_list", status="passed"), with_name=True)]
    out = breadth(recs)
    assert out["pages_failed"] == ["authentication"]
    assert out["pages_passed"] == ["my_list"]
    assert out["failed_records"] == 1 and out["passed_records"] == 1


def test_a_record_with_nothing_to_name_it_still_says_questionmark():
    """The fallback must survive — silently dropping an unlabelled failure would hide it."""
    out = breadth([{"status": "failure", "metadata": {"check": "ui_flow"}}])
    assert out["pages_failed"] == ["?"] and out["failed_records"] == 1


# --- the two normalisers must not drift again ------------------------------------------------

def test_both_normalisers_emit_the_same_key_set():
    """★ The promise in the orchestrator's own docstring, asserted. They drifted on one key
    and it cost the label on the most common live blocker."""
    hub_src = inspect.getsource(
        __import__("env_generator.llm_generator.multi_agent.runtime.hub_registry",
                   fromlist=["x"]))
    i = hub_src.index("def get_validation_results")
    hub_block = hub_src[i:hub_src.index("def get_validation_summary", i)]
    orch_src = inspect.getsource(O)
    j = orch_src.index("def _get_validation_results")
    orch_block = orch_src[j:orch_src.index("def _get_validation_summary", j)]
    for key in ('"task_id"', '"name"', '"status"', '"summary"', '"execution_mode"',
                '"metadata"', '"recorded_by"', '"recorded_at"'):
        assert key in hub_block, f"hub_registry lost {key}"
        assert key in orch_block, f"orchestrator lost {key} — the readers disagree again"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
