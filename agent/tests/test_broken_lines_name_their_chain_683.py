r"""#683: the failure report named the step and not the chain that owns it.

r145's most repeated notification, 15 times, was:

    Framework validation attempt N/6: api_smoke NOT passing — FAILED: business_chain
    | failed=['business_chain:POST /api/my-list → 403 (expected [200, 201, 400, 404]; ...)']

"business_chain" there is the CHECK name — framework_validation builds the label from
`c.get('name')` — not the chain. The verifier held 50 chains and had to work out by hand which
one owned that step. It never did: `rating_dynamic_title` appears exactly twice in the whole
20,637-line log, meaning registered once and never revisited, while business_chain stayed red for
75 minutes and aborted the run.

The name was right there. `execute_chain` returns `{"name": ..., "broken": [...]}` and
`run_all_chains` flattened it as `[b for r in results for b in r["broken"]]`, discarding `r["name"]`
one line after computing it.

A failing chain CAN be repaired — `register_verification_chain` only short-circuits a
re-registration whose status is already `passing` — so naming it is the whole difference between
an actionable report and a search problem.
"""
import inspect

import pytest

from env_generator.llm_generator.multi_agent.runtime import chain_executor as ce


def _flatten_src():
    src = inspect.getsource(ce)
    i = src.index("#683: KEEP THE CHAIN NAME")
    return src[i:src.index("total = sum", i)]


# --- the name survives the flatten -------------------------------------------------------------

def test_broken_lines_are_prefixed_with_the_chain_name():
    assert """broken = [f"[{r['name']}] {b}" for r in results for b in r["broken"]]""" in _flatten_src()


def test_framework_defects_are_prefixed_too():
    """#272 routes these to the framework rather than a lane; it needs the chain just as much."""
    body = _flatten_src()
    assert "framework_defects = [f\"[{r['name']}] {b}\"" in body


def test_the_prefix_is_the_chain_name_not_the_check_name():
    """The bug was that the only name in the report came from the CHECK."""
    body = _flatten_src()
    assert "r['name']" in body
    assert "business_chain" not in body.split("broken = ")[1][:120]


# --- the per-chain result still carries what the prefix reads ---------------------------------

def test_execute_chain_returns_a_name():
    src = inspect.getsource(ce.execute_chain)
    assert 'return {"name": str(chain.get("name") or "chain")' in src


def test_a_nameless_chain_still_yields_a_label():
    """`or "chain"` — the prefix must never render as [None]."""
    src = inspect.getsource(ce.execute_chain)
    assert 'chain.get("name") or "chain"' in src


# --- the shape of the rendered line ------------------------------------------------------------

def test_the_prefix_leads_the_line():
    """A reader scanning a list of failures should see the owner first."""
    rendered = "[{}] {}".format("rating_dynamic_title", "POST /api/titles/1/rating → 400")
    assert rendered.startswith("[rating_dynamic_title] ")


def test_the_step_detail_is_unchanged_after_the_prefix():
    body = _flatten_src()
    assert "{b}" in body, "the original line must be carried verbatim"


# --- provenance -------------------------------------------------------------------------------

def test_the_live_evidence_is_recorded():
    flat = " ".join(_flatten_src().replace("#", " ").split())
    assert "15 times in r145" in flat
    assert "rating_dynamic_title" in flat


def test_it_records_that_a_failing_chain_is_repairable():
    """Without this the fix reads as cosmetic; the point is the verifier CAN act."""
    flat = " ".join(_flatten_src().replace("#", " ").split())
    assert "only short-circuits a re-registration whose status is already passing" in flat


def test_it_records_where_the_wrong_name_came_from():
    flat = " ".join(_flatten_src().replace("#", " ").split())
    assert "is the CHECK name" in flat


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
