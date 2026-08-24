"""FIX #85a — the single-shot enrich fallback must ALSO fire on an UNENRICHED agent doc
(instagram run-5/run-6 identical live signature, 2026-07-06).

Run-6 forensics: the design_analyst's planning step was MALFORMED-degraded (10 failed
plan() calls), its thinking drowned in resident-protocol bureaucracy (inbox/kickoff/wake
cycles), and its one rational strategy — writing measure_and_enrich.py to batch-enrich 98
components — was a silent dead end (its 49 tools include NO execution tool). It never
touched design_system.json: build_notes 0/98, type_scale/radius_scale/iconography all
empty, in BOTH runs. The orchestrator's fallback only fired on a MALFORMED doc, so a
parseable-but-hollow doc sailed through. `design_system_is_enriched(ds)` now gives a
deterministic completeness verdict the orchestrator uses to trigger the existing
single-shot enrich channel. LOCAL-ONLY (agent/tests/ gitignored).
"""

import inspect
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime.design_prep import design_system_is_enriched  # noqa: E402


def _ds(build_notes="", type_scale=None):
    return {
        "design_system": {"palette": {"bg": "#0b0f14"}, "theme": {"default": "dark"},
                          "type_scale": type_scale or [], "radius_scale": {},
                          "shadow_scale": [], "iconography": {}},
        "assets": [{"id": "logo", "file": "icons/logo.svg"}],
        "screens": [{"name": "home", "reference": "home.png", "layout": "",
                     "components": [
                         {"id": "nav", "region": [0, 0, 1, 0.1], "colors": {"bg": "#0b0f14"},
                          "assets": [], "role": "nav", "state": "", "crop": None,
                          "build_notes": build_notes}]}],
    }


def test_hollow_agent_doc_is_not_enriched():
    # the exact run-5/run-6 signature: parseable, measured, but zero enrichment
    assert design_system_is_enriched(_ds()) is False


def test_build_notes_coverage_counts_as_enriched():
    assert design_system_is_enriched(_ds(build_notes="dark rail, 24px icons")) is True


def test_type_scale_alone_is_NOT_enriched_834():
    """#834 removed exactly this, and measured what it cost.

    #85a accepted "document scales non-empty OR any build_notes" because run-5/6
    produced NEITHER, so both signals meant the same thing. The analyst then
    improved asymmetrically: extract_palette/measure_layout reliably fill the
    DOCUMENT-level scales while nothing fills the PER-COMPONENT fields. Over the
    corpus, 144 of 151 docs were judged enriched and 133 of those carried no
    per-component build_notes or typography at all — so the single-shot fallback,
    whose entire purpose is to produce them, was suppressed in 88% of runs. That
    is the root of the 1-in-49,286 build_notes rate, upstream of every evaporation
    point #813/#815/#816/#819 instrument, none of which can fire while the
    fallback never runs.

    Scales alone are a document the lane can style from; they are not the
    per-component build guidance the frontend prompt tells it to read."""
    assert design_system_is_enriched(
        _ds(type_scale=[{"role": "body", "size_px": 14, "weight": 400}])) is False


def test_non_dict_is_not_enriched():
    assert design_system_is_enriched(None) is False
    assert design_system_is_enriched([]) is False


def test_orchestrator_falls_back_on_unenriched_doc():
    from multi_agent.orchestrator import Orchestrator
    src = inspect.getsource(Orchestrator._compile_reference_materials)
    assert "design_system_is_enriched" in src
    # the enrich fallback must consider enrichment, not only parseability
    accept = src.index("load_valid_design_system(dsp)")
    check = src.index("design_system_is_enriched(")
    assert accept < check
