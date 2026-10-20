r"""#643: 74% of the design system is written into a void.

Measured over the 45 delivered `design/design_system.json` files:

    82 distinct keys written under `design_system`
    61 of them (74%) read by NO runtime code
    28% of every key-instance written

These are not typos — they are whole specifications that land nowhere:

    motion               written in 27 of 45 runs   read by nobody
    collapse_checklist                24 of 45      read by nobody
    brand_boundary                     8 of 45      read by nobody
    spacing_scale_px / spacing_scale  13 combined   read by nobody (only `spacing` is read)

The tail is free-form synonym invention, the same shape as #360's rejected tool arguments:
`spacing`/`spacing_scale`/`spacing_scale_px`, `font_stack`/`font_family`/`font_families`,
`grid`/`grids`, and one `collapse_checklist_塌缩点`. Only the first of each group is consumed.

Consuming the extras would be feature work. What is wrong is that the analyst cannot TELL: it
spends a section on `motion` in three runs out of five and gets no signal that nothing reads it.
#360 solved the identical problem for tool arguments by dropping them loudly; this reports at the
write boundary.

Getting the measurement right took two corrections, both caught before shipping: the file is
NESTED (`{"design_system": {...}}`), so a top-level scan reported "0 of 45" for `palette`, which
is present in all 45; and a reader-grep for `"key"` alone misses `'key'`, which would have called
four consumed keys unconsumed.
"""
import subprocess

import json

from pathlib import Path

import pytest

from env_generator.llm_generator.multi_agent.runtime.design_prep import (
    _CONSUMED_DESIGN_KEYS_643 as CONSUMED,
    unconsumed_design_keys_643 as unconsumed,
)


# --- what it reports ------------------------------------------------------------------------------

def test_a_key_nothing_reads_is_reported():
    assert unconsumed({"design_system": {"palette": {}, "motion": {}}}) == ["motion"]


def test_a_fully_consumed_document_reports_nothing():
    assert unconsumed({"design_system": {"palette": {}, "theme": "dark", "type_scale": {}}}) == []


def test_the_measured_offenders_are_all_caught():
    doc = {"design_system": {k: {} for k in
                             ("motion", "collapse_checklist", "brand_boundary",
                              "spacing_scale", "spacing_scale_px")}}
    assert unconsumed(doc) == ["brand_boundary", "collapse_checklist", "motion",
                               "spacing_scale", "spacing_scale_px"]


def test_the_consumed_member_of_a_synonym_group_survives():
    """`spacing` is read; `spacing_scale` and `spacing_scale_px` are not."""
    doc = {"design_system": {"spacing": {}, "spacing_scale": {}, "spacing_scale_px": {}}}
    assert unconsumed(doc) == ["spacing_scale", "spacing_scale_px"]


def test_a_non_ascii_variant_is_caught_too():
    """One run wrote `collapse_checklist_塌缩点`."""
    assert unconsumed({"design_system": {"collapse_checklist_塌缩点": []}}) \
        == ["collapse_checklist_塌缩点"]


def test_the_result_is_sorted_and_stable():
    doc = {"design_system": {"zeta": 1, "alpha": 2, "palette": {}}}
    assert unconsumed(doc) == ["alpha", "zeta"]


# --- the file is nested ---------------------------------------------------------------------------

def test_it_reads_the_NESTED_document():
    """The artifact is {"design_system": {...}, "assets": ..., "screens": ...}. Scanning the top
    level reported "palette present in 0 of 45 runs" — it is in all 45."""
    assert unconsumed({"design_system": {"palette": {}}, "assets": {}, "screens": []}) == []


def test_a_flat_document_still_works():
    assert unconsumed({"palette": {}, "motion": {}}) == ["motion"]


def test_junk_input_never_raises():
    for bad in (None, [], "x", {"design_system": "not a dict"}, {"design_system": None}):
        assert unconsumed(bad) == []


# --- the list must not rot ---------------------------------------------------------------------

# #1203pz: WHAT THE LIST CLAIMS, PINNED AGAINST THE ARTIFACTS INSTEAD OF AGAINST ITS OWN TEXT.
#
# The check below grepped every claimed key as a quoted string anywhere under
# `env_generator/`. It fails only for a key whose name appears in NO .py file at all -- and
# these are ordinary words describing UI, so that never happens: `hero` matches a page-name
# vocabulary in completeness_audit and a backdrop synonym table in delivery_gate, `spacing`
# matches a prompt string and a comment about TAILWIND's spacing keys, `player` a page-name
# synonym table, `fonts` the `public/assets/fonts` directory path. In the limit it is
# satisfied by `_CONSUMED_DESIGN_KEYS_643` ITSELF, which lives under `env_generator/` and
# spells every key as a quoted string. Its docstring said "If a name here stops being read,
# this becomes a second fiction -- so the claim is checked against the source, not trusted":
# the check could not tell being READ from being MENTIONED, which is #826's shape -- and
# four of the keys it passes are read by nothing at all.
#
# A SMARTER GREP DOES NOT FIX IT, and both ends were tried before settling this:
#   * three access mechanisms (`.get("k")`, `["k"]`, a literal in an iterated tuple) with no
#     restriction on the receiver -> 17 of 21 pass, but `fonts` passes on the strength of a
#     DIRECTORY name (`public/assets/fonts`) and nothing reads a `fonts` design key;
#   * the same, restricted to document-shaped receivers (`ds`/`doc`/`sds`/`eds`/`_inner`) ->
#     10 of 21, rejecting `geometry`, `grid`, `header` and `notes`, which are genuinely read
#     off differently-named locals.
# A syntactic test cannot separate "reads the design key `fonts`" from "names a directory
# `fonts`". So the pin moves to the produced ARTIFACTS, where a word in a comment or a
# synonym table cannot satisfy it.
#
# MEASURED over the 104 design documents in this corpus, at ALL FOUR levels a key can live at
# (document root, inside `design_system`, per screen, per component -- a single-level check
# falsely reports 0 for five of them: `brand` 2343 at component level, `geometry` 8971,
# `layout` 1477 per screen, `layout_metrics` 575, `screens` 104 at the root):
#
#     never produced at ANY level   font_stack, fonts, grid, header, hero, player, spacing
#     of those, read by nothing     fonts, hero, player, spacing
#     of those, read but starved    font_stack, grid, header   (dead reader paths)
#
# Today that costs nothing: none of the seven appears at the level `unconsumed_design_keys_643`
# inspects, so the blind spot is latent. The point is that the guard can now fail.
_LEVELS_1203PZ = ("document root", "design_system", "screen", "component")

# Claimed consumed and never produced anywhere in the corpus. An entry here is a DECLARED
# fiction rather than a silent one; each says which half is missing.
_NEVER_PROVIDED_1203PZ = {
    "fonts": "no reader and no producer -- `font_stack` is the one that is read",
    "hero": "no reader and no producer; the name survives only in a page-name vocabulary",
    "player": "no reader and no producer; the name survives in a page-name synonym table",
    "spacing": "no reader and no producer; the name survives in a prompt string",
    # #1203q2 CORRECTS THE THREE ENTRIES BELOW. They first read "READ by <module> and never
    # produced -- a starved reader", from an AST scan that counted `.get("k")` and `["k"]` on
    # ANY receiver. That is the over-permissive end this file's own comment already warns
    # about, and re-checking each site by hand shows only ONE of the three is a design_system
    # reader:
    #   font_stack  frontend_scaffold `_inner.get("font_stack")` where `_inner` IS the
    #               design_system -- genuine, and it defaults to "" so the custom font-family
    #               is simply never emitted;
    #   grid        scaffolder `_ol.get("grid")` reads the return of
    #               `wire_owned_list_shell_535()` -- a LOCAL dict, not a design doc;
    #   header      no design_system reader at all. Its matches are `message.header` in
    #               team_runtime/reasoning, a synonym-table value, a negative-terms tuple and
    #               substring tests on component text.
    # So grid and header belong with the four that nothing reads. Writing a per-key rationale
    # off a scan whose imprecision I had just documented is how the wrong words got in.
    "font_stack": "READ by frontend_scaffold (`_inner.get`) and never produced -- the one "
                  "genuine starved reader; it defaults to \"\" so no font-family is emitted",
    "grid": "no design_system reader (scaffolder reads `grid` off a LOCAL dict) and no producer",
    "header": "no design_system reader (only `message.header`, synonym tables and substring "
              "tests) and no producer",
}


def _design_docs_1203pz():
    root = Path(__file__).resolve().parents[2] / "generated"
    return sorted(root.glob("*/design/design_system.json")) if root.is_dir() else []


def _keys_at_every_level_1203pz(doc):
    """Every key the document mentions, at any of the four levels #1203pz measures."""
    seen = set()
    if not isinstance(doc, dict):
        return seen
    seen.update(doc)
    inner = doc.get("design_system")
    inner = inner if isinstance(inner, dict) else {}
    seen.update(inner)
    screens = doc.get("screens") or inner.get("screens") or []
    if isinstance(screens, list):
        for sc in screens:
            if not isinstance(sc, dict):
                continue
            seen.update(sc)
            for comp in (sc.get("components") or []):
                if isinstance(comp, dict):
                    seen.update(comp)
    return seen


def test_every_key_claimed_as_consumed_is_really_PRODUCED():
    """★ THE PIN THAT CAN FAIL. Corpus-dependent by nature, like
    tests/test_verify_1018_measures_something.py -- it skips when the corpus is gone rather
    than passing vacuously, because "I could not look" is not "I looked and found nothing"
    (#883)."""
    docs = _design_docs_1203pz()
    if len(docs) < 10:
        pytest.skip("needs the generated/ corpus (%d design doc(s) on this disk)" % len(docs))
    produced = set()
    for p in docs:
        try:
            produced |= _keys_at_every_level_1203pz(json.loads(p.read_text(encoding="utf-8")))
        except Exception:
            continue
    missing = sorted(k for k in CONSUMED
                     if k not in produced and k not in _NEVER_PROVIDED_1203PZ)
    assert not missing, (
        "claimed consumed and produced by NOTHING in %d design document(s), and not declared "
        "in _NEVER_PROVIDED_1203PZ: %s" % (len(docs), missing))


def test_the_declared_fictions_are_still_fictions():
    """The other direction: if one of the seven starts being produced, the allowance is stale
    and must shrink. #1203oa -- a parked measurement rots."""
    docs = _design_docs_1203pz()
    if len(docs) < 10:
        pytest.skip("needs the generated/ corpus")
    produced = set()
    for p in docs:
        try:
            produced |= _keys_at_every_level_1203pz(json.loads(p.read_text(encoding="utf-8")))
        except Exception:
            continue
    stale = sorted(k for k in _NEVER_PROVIDED_1203PZ if k in produced)
    assert not stale, (
        "these are declared never-produced but the corpus now has them: %s" % stale)


def test_every_declared_fiction_is_a_claimed_key():
    """An allowance for a key that is not even claimed would be noise."""
    assert set(_NEVER_PROVIDED_1203PZ) <= set(CONSUMED), (
        sorted(set(_NEVER_PROVIDED_1203PZ) - set(CONSUMED)))


def test_each_declared_fiction_says_which_half_is_missing():
    """#983: an allowance that names nothing is a waiver, not a record."""
    for k, why in _NEVER_PROVIDED_1203PZ.items():
        assert "read" in why.lower() or "producer" in why.lower(), (k, why)


def test_the_four_levels_are_all_checked():
    """A single-level check reported 12 never-produced keys instead of 7, because `brand` and
    `geometry` live on COMPONENTS and `layout_metrics` on SCREENS. Driven on a synthetic
    document so the property does not depend on the corpus."""
    doc = {"screens": [{"layout_metrics": {}, "components": [{"brand": {}}]}],
           "design_system": {"theme": "dark"}}
    got = _keys_at_every_level_1203pz(doc)
    for k in ("screens", "design_system", "theme", "layout_metrics", "brand"):
        assert k in got, (k, sorted(got))


def test_an_unreadable_document_does_not_count_as_produced():
    assert _keys_at_every_level_1203pz(None) == set()
    assert _keys_at_every_level_1203pz("garbage") == set()


def test_the_warning_fires_at_the_write_boundary():
    import inspect
    from env_generator.llm_generator.multi_agent.runtime import design_prep
    src = inspect.getsource(design_prep._write_design_system)
    i = src.index("#643: say which sections will be ignored")
    assert src.index("unconsumed_design_keys_643(ds)", i) < src.index('design_system.json', i)


def test_it_never_blocks_the_write():
    import inspect
    from env_generator.llm_generator.multi_agent.runtime import design_prep
    src = inspect.getsource(design_prep._write_design_system)
    block = src[src.index("_ignored = unconsumed"):src.index('(design_dir / "design_system.json")')]
    assert "except Exception" in block and "return" not in block


def test_the_measurement_is_recorded():
    import inspect
    from env_generator.llm_generator.multi_agent.runtime import design_prep
    flat = " ".join(inspect.getsource(design_prep).replace("#", " ").split())
    assert "61 of them (74%) are read by no runtime code" in flat
    assert "`motion` in **27 of 45 runs**" in flat


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
