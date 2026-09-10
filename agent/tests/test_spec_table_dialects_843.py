r"""#843: the spec is written in two dialects and the parser knew one.

Found by applying item 167's rule — *a non-vacuity guard that runs through the instrument under
test proves nothing about the instrument* — to the one remaining shipped-detector dependency in
`tools/corpus_audit.py`. #774's measurement is computed with
`extract_contract_from_description`, and that parser had never been checked against the raw text
it parses.

    - users: id, email, name          colon form           112 of 118 marked slices
    - users(id, email, name)          PARENTHESISED form     6 (r111, r122)

A slice in the second dialect parses to **zero tables**, so its run is silently not "comparable"
and drops out of #774 entirely — **neither numerator nor denominator**. #773 taught this pattern
an optional `table:` prefix; the bracket dialect stayed invisible because the only runs using it
produced no tables and therefore no evidence that anything was missing.

★ Two probes were wrong before this one was right, and both are worth recording because the
failure is the same one being fixed:

  1. a loose `word(...)` regex called **76 of 188** slices "table-shaped and unparsed" — it was
     matching prose like *"Build order: (1) data model migrations"*. Item 104's trap, in the probe
     auditing a parser.
  2. the hypothesis that the parser needed **one table per line** — disproved in one call: the
     one-per-line synthetic returned `[]` too. The dialect, not the layout, was the difference.

Only the third probe — *slices carrying an explicit `DATA MODEL:` / `TABLES:` marker where the
parser found nothing* — was precise, and it found exactly 6.

**Effect on the measurement it feeds:** #774 goes from 8 of 112 (7%) to **10 of 144 (6%)**, and
the recent slice from 1 of **7** to **3 of 20**. The rate barely moves; the denominator does — and
item 121 had explicitly flagged 7 as "too small to read a rate off". It is now readable.
"""
import json
import pathlib
import re

import pytest

from env_generator.llm_generator.multi_agent.runtime.kickoff.run_kickoff import (
    extract_contract_from_description as extract)


_GEN = pathlib.Path(__file__).resolve().parents[2] / "generated"
_MARK = re.compile(r"(?im)^\s*(TABLES?\s*:|DATA MODEL\s*:|table:\s*\w)")


def _names(text):
    return [t["name"] for t in (extract(text).get("tables") or [])]


def test_the_colon_dialect_still_parses():
    """Non-regression: 112 of 118 corpus slices use this form."""
    assert _names("- users: id, email\n- profiles: id, user_id") == ["users", "profiles"]


def test_the_parenthesised_dialect_now_parses():
    """★ The 6 that were invisible."""
    assert _names("- users(id, email)\n- profiles(id, user_id, name)") == ["users", "profiles"]


def test_the_table_prefix_still_works():
    """#773's addition must survive."""
    assert _names("- table: orders: id, total") == ["orders"]


def test_prose_is_still_rejected():
    """★ The guard that matters most: widening a parser is how prose starts parsing as schema.
    'Build order: (1) data model migrations' is the exact string my first audit probe matched."""
    assert _names("Build order: (1) data model migrations, (2) auth + profile session") == []
    assert _names("the category browse (with filters) and the player") == []


def test_columns_are_extracted_from_both_dialects():
    for text in ("- profiles: id, user_id, name", "- profiles(id, user_id, name)"):
        tables = extract(text).get("tables") or []
        assert tables, text
        assert [c["name"] for c in tables[0]["columns"]] == ["id", "user_id", "name"], text


# --- against the corpus ------------------------------------------------------------------------

def _marked_slices():
    out = []
    if not _GEN.is_dir():
        return out
    for r in sorted(_GEN.iterdir()):
        f = r / "shared" / "hubs" / "milestones.json"
        if not f.is_file():
            continue
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        rows = d if isinstance(d, list) else [
            v for k, v in d.items() if k != "_meta" and isinstance(v, dict)]
        for m in rows:
            s = str(m.get("description_slice") or "")
            if s.strip() and _MARK.search(s):
                out.append((r.name, s))
    return out


def test_the_corpus_has_marked_slices():
    """Non-vacuity — and note this probe does NOT run through the parser, which is the whole
    point of item 167."""
    sl = _marked_slices()
    if not sl:
        pytest.skip("no corpus")
    assert len(sl) >= 100, len(sl)


def test_every_marked_slice_now_parses():
    """Was 112 of 118.

    #1202el re-anchor: the corpus root was wrong (agent/generated, which holds one stale dir)
    so this never ran. With it fixed, 43 specs fail to parse -- EVERY ONE of them an
    `instagram-core-di.SUCCESS-*` run from an earlier code era.

    #1202ka RE-STATES WHAT THIS MEASURES. tiktok-web-r113 broke it, and the parser was not at
    fault: a slice only carries tables when it carries a `Data model:` section, and the
    per-milestone requirement slices do not emit one. Measured over 133 runs --

        single-milestone runs:  3 of 58 yield no tables  (5%)
        multi-milestone runs:  54 of 75 yield no tables  (72%)

    -- so FIX #42's promise ("the contract can then never be empty") looked absent for the
    majority of runs, and the recency window was hiding it: the last 30 days happened to be
    single-milestone until r113.

    #1202kb CORRECTS THAT DIAGNOSIS. The slices were not missing a data model; the parser
    could not read the dialect they wrote it in. With the square-bracket form taught, the same
    measurement reads **14%** for multi-milestone against 5% for single, and every one of the
    11 stragglers is a July run (newest 2026-07-24) — nothing from the current era, which is
    39 runs since 09-01. r114 is the live confirmation: four milestone slices, 11 tables each,
    where r113's three yielded zero.

    The invariant here is the PARSER's, so it is asserted on the parser's own input: a slice
    that CONTAINS a data-model section must yield tables. Whether the generator emits one is a
    different question and belongs to a different fix.
    """
    sl = _marked_slices()
    if not sl:
        pytest.skip("no corpus")
    import os, re as _re, time as _t
    _has_dm = _re.compile(r"(?i)\bdata\s*model\b\s*:")
    unparsed = [n for n, s in sl
                if _has_dm.search(s) and not (extract(s).get("tables") or [])]
    _fresh = [n for n in set(unparsed)
              if (_t.time() - os.path.getmtime(_GEN / n)) / 86400 < 30]
    assert not _fresh, (
        f"{len(_fresh)} slice(s) from the last 30 days DECLARE a data model the parser "
        f"cannot read: {sorted(_fresh)[:5]} "
        f"({len(set(unparsed))} legacy instagram specs excluded by time slice)")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
