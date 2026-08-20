r"""#834: the enrichment guard's OR suppressed the fallback in 88% of runs.

The design phase runs the `design_analyst` AGENT first, then checks its output and — per #85a —
falls back to the single-shot enrich if the doc *"parses but was never ENRICHED"*. That guard read:

    enriched == a document-level scale is non-empty  OR  any component carries build_notes

#85a was written for run-5/6, where the analyst produced **nothing**: build_notes 0 *and* scales
empty. Either signal meant the same thing, so the OR was correct.

★ **The analyst has since improved asymmetrically.** `extract_palette` / `measure_layout` reliably
fill the DOCUMENT-level scales; nothing fills the PER-COMPONENT fields. r151's analyst log shows
20 `decompose_reference` + 20 `extract_palette` calls and no enrichment step, finishing with *"The
design system is complete."* Its doc has `type_scale` and `radius_scale` populated and
**build_notes 0 of 331** — so the OR short-circuits on the scales, the doc is declared enriched,
and the fallback never runs.

Measured across the corpus:

    docs parsed                                     151
    judged ENRICHED by the old OR                   144
      ...carrying NO per-component field at all     133   <- the fallback was suppressed here
    genuinely per-component enriched                 11

★★ **This is upstream of everything else in the thread.** #813 (the per-screen call), #815 (the
join), #816 (invalid JSON input) and #819 (the wholesale handler) all instrument a fallback that,
in 88% of runs, **was never invoked**. It also answers offline the question two items declared
needed a live run.

The fix requires the per-component half specifically. Scales alone are a document the lane can
style from; they are not the per-component build guidance the frontend prompt directs it to read
on every component. **Cost is real and deliberate:** 133 runs would newly invoke the single-shot
enrich, one call per screen — which is exactly what #85a intended by *"not ship hollow"*.
"""
import json
import pathlib

import pytest

from env_generator.llm_generator.multi_agent.runtime.design_prep import (
    design_system_is_enriched)


_GEN = pathlib.Path(__file__).resolve().parents[1] / "generated"


def _doc(components=None, scales=None):
    return {"design_system": scales or {},
            "screens": [{"name": "s", "components": components or []}]}


def test_scales_alone_are_no_longer_enough():
    """★ The whole defect: a doc with measured scales and zero per-component guidance used to
    pass, so the fallback that produces that guidance never ran."""
    assert design_system_is_enriched(
        _doc(components=[{"id": "a"}],
             scales={"type_scale": [{"role": "h1", "size_px": 44}],
                     "radius_scale": {"card": 4}})) is False


def test_a_component_with_build_notes_passes():
    assert design_system_is_enriched(_doc(components=[{"id": "a", "build_notes": "dark bar"}]))


def test_a_component_with_typography_passes():
    assert design_system_is_enriched(_doc(components=[{"id": "a", "typography": {"size": 14}}]))


def test_an_empty_doc_fails():
    assert design_system_is_enriched(_doc()) is False
    assert design_system_is_enriched({}) is False
    assert design_system_is_enriched(None) is False


@pytest.mark.parametrize("bad", [{"screens": "nope"}, {"screens": [None, 3]},
                                 {"screens": [{"components": "nope"}]}])
def test_malformed_docs_do_not_raise(bad):
    """This decides whether an expensive fallback runs; a crash here would take the design phase
    with it."""
    assert design_system_is_enriched(bad) in (True, False)


# --- against the corpus ---------------------------------------------------------------------

def _docs():
    if not _GEN.is_dir():
        return []
    out = []
    for r in sorted(_GEN.iterdir()):
        f = r / "design" / "design_system.json"
        if f.is_file():
            try:
                out.append((r.name, json.loads(f.read_text(encoding="utf-8"))))
            except Exception:
                pass
    return out


def test_the_corpus_is_being_exercised():
    docs = _docs()
    if not docs:
        pytest.skip("no corpus")
    assert len(docs) >= 100, len(docs)


def test_r151s_hollow_doc_is_now_caught():
    """The run that motivated this: type_scale and radius_scale populated, build_notes 0 of 331,
    and the old guard called it enriched."""
    docs = dict(_docs())
    ds = docs.get("netflix-web-r151")
    if ds is None:
        pytest.skip("r151 not present")
    comps = [c for s in ds.get("screens", []) for c in (s.get("components") or [])]
    assert comps and not any(c.get("build_notes") for c in comps), "non-vacuity: it IS hollow"
    assert (ds.get("design_system") or {}).get("type_scale"), "non-vacuity: scales ARE populated"
    assert design_system_is_enriched(ds) is False


def test_only_the_genuinely_enriched_docs_pass():
    """11 of 151, matching the count of docs that carry a per-component field."""
    docs = _docs()
    if not docs:
        pytest.skip("no corpus")
    passing = [n for n, d in docs if design_system_is_enriched(d)]
    for n, d in docs:
        per = any(c.get("build_notes") or c.get("typography")
                  for s in (d.get("screens") or []) if isinstance(s, dict)
                  for c in (s.get("components") or []) if isinstance(c, dict))
        assert (n in passing) == per, n
    # The equivalence asserted in the loop above is the REAL guard — it is exact and holds
    # per document. This band is only a smoke check that the guard has not gone
    # all-permissive or all-rejecting, so it tracks a corpus that keeps growing: netflix-web
    # r172 arrived genuinely enriched and took the count 30 -> 31. Raise it when a NEW
    # enriched run legitimately pushes past it; never to make a real over-permissiveness
    # regression go quiet — that shows up in the loop, not here.
    assert 5 <= len(passing) <= 40, len(passing)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
