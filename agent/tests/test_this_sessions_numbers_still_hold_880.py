r"""#880: the session's load-bearing numbers, re-derived against the code path that consumes them.

#878 caught a shipped fix whose measurement did not reproduce — `_avatar_asset_url_874` read
`design["assets"]` while the probe that justified it scanned the whole document. The check that
found it was a spot audit; this makes it standing.

★ **The rule it encodes: a NON-ZERO is a claim about the instrument too.** *"A zero is a claim
about the instrument"* appears nine times in this session's notes, and #874's error is its mirror
— 139 looked like a finding so it went unquestioned, while 0 looks like a failure so it always
gets checked. The asymmetry was the whole bug.

Each case re-derives a number **from the place the consuming code reads**, not from the artifact
that happens to contain it. Corpus-dependent, so skipped where the corpus is absent.

Audited when written — four claims, three held:

| ticket | claim | re-derived |
|---|---|---|
| #864 / #862 | no `milestones.json` in 7 of 151 | 7/151 ✓ |
| #872 | 70 of 94 non-completed reach the visual gate | 70/94 ✓ |
| #875 | 160 of 458 roles carry a positional cue | 160/458 ✓ |
| #851 | 0 of 151 seeds contain a hard marker | 0 ✓ (probe scanned a superset of the gate's merge) |
| #874 | 139 of 151 stage an avatar-ish asset | **0/151 — reverted as #878** |
"""
import json
import pathlib
import re

import pytest

_G = pathlib.Path(__file__).resolve().parents[1] / "generated"
pytestmark = pytest.mark.skipif(not _G.is_dir(), reason="corpus not present")


def _runs():
    """★ Scoped to r1–r151 — the population these numbers were measured over.

    #880's guard fired the moment r152 appeared, exactly as designed ("if the corpus grows, the
    numbers legitimately move and this file must be re-derived, not adjusted"). Re-deriving over a
    growing corpus would make every number a moving target and the file would stop being a record
    of anything. Scoping keeps each assertion a statement about the measurement that was actually
    made; a NEW measurement over a bigger corpus is a new item, not an edit to this one."""
    def _n(p):
        m = re.search(r"-r(\d+)$", p.name)
        return int(m.group(1)) if m else -1
    return sorted((p for p in _G.glob("netflix-web-r*") if 1 <= _n(p) <= 151), key=_n)


def test_the_corpus_is_the_one_these_numbers_were_taken_from():
    """★ Non-vacuity: the scoped population must still be exactly the 151 runs measured.

    If a run in r1–r151 is deleted this fails, which is right — the numbers would no longer
    describe anything. Runs ABOVE 151 are excluded by `_runs()` rather than folded in, so a new
    run cannot silently move a recorded measurement."""
    assert len(_runs()) == 151, (
        f"the r1-r151 population is now {len(_runs())} runs — these numbers describe 151")
    assert len(list(_G.glob("netflix-web-r*"))) >= 151


def test_864_no_milestones_json_in_seven_runs():
    """`set_roadmap`'s readback consults the milestone store, whose file is this one."""
    missing = [d.name for d in _runs() if not (d / "shared/hubs/milestones.json").exists()]
    assert len(missing) == 7, missing
    assert set(missing) == {f"netflix-web-r{n}" for n in (19, 35, 38, 42, 44, 136, 140)}, missing


def test_872_seventy_of_ninetyfour_reach_the_visual_gate():
    """The census keys on `generation_complete` in the persisted progress log — the same string
    the gate's own terminal events use."""
    def done(d):
        f = d / "logs/progress_events.jsonl"
        return f.exists() and "generation_complete" in f.read_text(errors="ignore")

    nc = [d for d in _runs() if not done(d)]
    vg = [d for d in nc if (d / "design/visual_gate").is_dir()
          and any((d / "design/visual_gate").rglob("*.json"))]
    assert (len(vg), len(nc)) == (70, 94), (len(vg), len(nc))


def test_875_one_sixty_of_four_fiftyeight_roles_carry_a_cue():
    """`_section_title_221` reads a component's `role` string; this counts the same field."""
    Q = re.compile(r"['‘“\"]([^'’”\"]{2,60})['’”\"]")
    CUE = re.compile(r"\bH1\b|page title|heading", re.I)
    two = cue = 0
    for d in _runs():
        for p in d.rglob("design_system*.json"):
            try:
                ds = json.loads(p.read_text())
            except Exception:
                break
            for scr in (ds.get("screens") or []):
                if not isinstance(scr, dict):
                    continue
                for c in (scr.get("components") or []):
                    if not isinstance(c, dict):
                        continue
                    t = str(c.get("role") or "")
                    if len(Q.findall(t)) >= 2:
                        two += 1
                        if CUE.search(t):
                            cue += 1
            break
    assert (cue, two) == (160, 458), (cue, two)


def test_851_no_seed_carries_a_hard_marker():
    """★ The consuming path is `audit_authored_seed`, which the delivery gate feeds a MERGE of
    `seed_data.json` and `seed_dataset.json`. Scanning both files separately covers a superset of
    that merge, so a zero here is conservative — the direction that matters for a blocking gate."""
    from env_generator.llm_generator.multi_agent.runtime.seed_audit import (
        _word_boundary_markers)
    files = 0
    for d in _runs():
        seen = set()
        for f in list(d.rglob("seed_dataset.json")) + list(d.rglob("seed_data.json")):
            t = f.read_text(errors="ignore")
            if t in seen:
                continue
            seen.add(t)
            files += 1
            try:
                data = json.loads(t)
            except Exception:
                continue
            if not isinstance(data, dict):
                continue
            for rows in data.values():
                if isinstance(rows, list):
                    hits = _word_boundary_markers([r for r in rows if isinstance(r, dict)])
                    assert not hits, (f, hits)
    assert files >= 400, f"non-vacuity: only {files} seed files scanned"


def test_874s_number_is_the_one_that_did_not_reproduce():
    """★ Kept as a case, not just a note. `design["assets"]` is what the reverted helper read; the
    avatar imagery lives in a component `crop` that is never staged. If an avatar ever IS staged,
    this fails and #874 becomes revivable — which is the only condition under which it should be."""
    staged = 0
    for d in _runs():
        for p in d.rglob("design_system*.json"):
            try:
                ds = json.loads(p.read_text())
            except Exception:
                break
            hay = " ".join(f"{a.get('id','')} {a.get('file','')}"
                           for a in (ds.get("assets") or []) if isinstance(a, dict)).lower()
            if re.search(r"avatar|profile", hay):
                staged += 1
            break
    assert staged == 0, f"{staged} runs stage an avatar now — #874 may be revivable"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
