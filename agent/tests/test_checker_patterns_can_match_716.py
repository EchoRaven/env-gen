r"""#716: a checker pattern that cannot match is indistinguishable from a defect that did not occur.

`tools/check_pending_experiments.sh` is how every fix in this session gets read off a run. Each
line greps the run log for one signature and prints LIVE or NOT SEEN. A pattern that no longer
matches its production string therefore prints NOT SEEN forever, and NOT SEEN is exactly what a
working fix looks like when its condition never arose — so the failure is silent and reads as
good news.

That is not hypothetical. #713's line looked for "captured BYTE-IDENTICAL images", which was the
wording of MY implementation; when two independent implementations of that detector collided I
deleted mine and kept the other, which says "#713 %d screens captured the SAME image (md5 %s)".
The session's most fundamental finding — a quarter of all screen scores measured on a shared page
— would have read NOT SEEN on the very run launched to validate it. Caught by hand while r148 was
still running; this test is that hand-check made permanent.

The rule: every pattern must be findable in the framework source, either as a literal or, when
the message is assembled at runtime, as its parts. Three kinds of false alarm are accounted for,
because each one bit during the manual pass:

  * `.*` in a pattern — split on it and require every remaining part;
  * BRE escaping (`\[projected\]`) — unescape before comparing to source;
  * f-string wrapping — `"...foo "` + `"bar..."` never contains "foo bar", so fold the joins.

Genuinely runtime-constructed signatures cannot be found in source at all and are listed by name,
with the construction site, rather than silently skipped.
"""
import re
from pathlib import Path

import pytest


CHECKER = Path(__file__).resolve().parents[2] / "tools" / "check_pending_experiments.sh"
SRC_ROOT = Path(__file__).resolve().parents[1] / "env_generator" / "llm_generator"

# Signatures assembled at runtime, so no literal can exist in source. Each entry names WHERE it
# is built, so an entry that goes stale is traceable rather than a permanent excuse.
RUNTIME_BUILT = {
    "] business_chain:": "chain_executor.py — f\"[{r['name']}] {b}\"",
    # #727's adoption probe. The literal `reach=` is never written anywhere: #725's dispatch
    # logger formats every argument as f"{_k}={...}", so the pair only exists at runtime. Its
    # first spelling was `"reach"` WITH quotes, which does appear in hub_tools.py as a dict key
    # — that satisfied the source check above while matching nothing a run ever emits.
    "reach=": "tooling.py — f\"{_k}={truncate(_sh, 120)}\" over kickoff_declare_ui_page's arg",
}


def _patterns(kind="grep_log"):
    """Patterns of ONE kind. The two kinds have opposite expectations and must not be mixed.

    `grep_log` searches for a signature the framework EMITS — it must be findable in source, or
    it reports NOT SEEN forever. `gone_log` searches for the OLD defect text that a fix was
    meant to eliminate; several of those strings were never ours to begin with (#687's
    `net::ERR_CONNECTION_REFUSED` is Chromium's) or are runtime-specific (#685 names a concrete
    path), so "absent from source" is the expected state and proves nothing either way.
    """
    out = {}
    for line in CHECKER.read_text(encoding="utf-8").split("\n"):
        m = re.match(r'\s*' + kind + r'\s+"([^"]+)"\s+"([^"]+)"', line)
        if m:
            out[m.group(1)] = m.group(2)
    return out


def _haystack():
    src = "".join(p.read_text(errors="ignore") for p in SRC_ROOT.rglob("*.py"))
    # Fold adjacent string literals: "...foo " "bar..." never contains "foo bar".
    return src + "\n" + re.sub(r'"\s*\n\s*f?"', "", src)


def _parts(pattern: str):
    """The literal fragments a grep pattern requires, with BRE escaping undone."""
    pat = pattern.rstrip("$")
    pat = pat.replace(r"\[", "[").replace(r"\]", "]").replace(r"\.", ".")
    return [p for p in pat.split(".*") if p.strip()]


# --- the checker is parseable at all ---------------------------------------------------------

def test_the_checker_exists_and_has_patterns():
    assert CHECKER.is_file()
    assert len(_patterns()) >= 20
    assert _patterns("gone_log"), "the disappearing-defect block must still exist"


def test_the_two_kinds_are_disjoint():
    assert not (set(_patterns()) & set(_patterns("gone_log")))


def test_no_pattern_is_empty():
    assert all(p.strip() for p in _patterns().values())


# --- every pattern can match something that exists ---------------------------------------------

def test_a_pattern_that_only_matches_a_dict_KEY_is_caught():
    """#716's ceiling, found by #727 slipping through it.

    This test asks whether a pattern exists in SOURCE. That is not the same question as whether
    it matches a LOGGED line, and #727's first version proved the gap: its pattern was `"reach"`
    with quotes, which appears in hub_tools.py as a dict key and satisfied this check — while the
    log, after #725 renders a list argument as its shape, reads `reach=[1]` with no quotes. The
    pattern could never have matched a run.

    A general fix is not available from here: this file cannot know a tool's log FORMAT. What it
    can do is refuse the specific shape that caused it — a pattern that is nothing but a
    double-quoted identifier, which is a source-literal spelling rather than a log spelling."""
    import re as _re
    suspicious = [f"{label} -> {pat}" for label, pat in _patterns().items()
                  if _re.fullmatch(r'\\?"[a-z_]+\\?"', pat.strip())]
    assert not suspicious, (
        "these patterns are bare quoted identifiers, which match a source dict key rather than "
        "anything a log writes — spell them as they appear in the LINE: " + ", ".join(suspicious))


def test_every_EMITTED_pattern_is_findable_in_the_source():
    hay = _haystack()
    missing = []
    for label, pat in sorted(_patterns().items()):
        if pat in RUNTIME_BUILT:
            continue
        if not all(part in hay for part in _parts(pat)):
            missing.append(f"{label}  ->  {pat}")
    assert not missing, (
        "these patterns match no production string, so they will report NOT SEEN forever:\n  "
        + "\n  ".join(missing))


@pytest.mark.parametrize("pat,site", sorted(RUNTIME_BUILT.items()))
def test_a_runtime_built_signature_names_its_construction_site(pat, site):
    """An exemption has to say where the string comes from, or it is just a silenced failure."""
    assert site and ".py" in site
    assert pat in _patterns().values(), f"exemption for a pattern no longer in the checker: {pat}"


# --- every pattern verified against a REAL output line, not against source -----------------------
# The lesson of three consecutive mistakes: a pattern can exist in source and still never match a
# run. Source presence and log matching are different questions, and only the second one matters.
# Each entry is a line as a run actually writes it — copied from a log where one exists, or
# constructed from the exact f-string that produces it.
SAMPLE_LINES = {
    "#727 reach declared":
        "🔧 kickoff_declare_ui_page: id=card_hover route=/browse reach=[1]",
    "#713 identical captures":
        "#713 5 screens captured the SAME image (md5 02a3e3): landing, player",
    "#713b shared-route sharing":
        "#713b 4 screens share ONE route (/browse) and therefore one capture: account_menu",
    "#711 gate left the app behind":
        "#711 the gating average has left the app behind: blocking_average 0.6190 vs "
        "blocking_average_live 0.4250 (gap 0.1940)",
    "#691 absent delivery subtree":
        "delivery subtree 'mcp_server' is not in the working tree at commit time — nothing "
        "from it will ship",
    "#691b subtree recovered":
        "recovered delivery subtree 'mcp_server' from 5f9973483 — it was committed on a branch",
    "#706 promotion refused":
        "framework delivery: integration -> main promotion did not happen (promotion merge "
        "conflict: 2 file(s): app/backend/main.py)",
    "#722 served build verified":
        "#715 served build matches the source: all 13 declared route(s) are present",
    "#723 captures all distinct":
        "#713 all 12 screen captures are distinct — no shared-page scoring this pass.",
    "#700 identical-content routes":
        "#615 6 routes render identical content: /browse, /games — all fetch only /api/titles",
}


@pytest.mark.parametrize("label,line", sorted(SAMPLE_LINES.items()))
def test_the_pattern_matches_a_line_a_run_actually_writes(label, line):
    pats = _patterns()
    assert label in pats, f"{label} is no longer in the checker; drop the sample or fix the label"
    for part in _parts(pats[label]):
        assert part in line, (
            f"{label}'s pattern fragment {part!r} does not appear in the line a run writes. "
            f"This is the #727 shape: the pattern was spelled for the SOURCE, not the LOG.")


def test_the_samples_cover_this_sessions_probes():
    """A sample table nobody extends is worse than none — it looks like coverage."""
    recent = {l for l in _patterns() if any(f"#{n}" in l for n in range(691, 730))}
    covered = recent & set(SAMPLE_LINES)
    assert len(covered) >= 8, f"only {len(covered)} of {len(recent)} recent probes have a sample"


# --- the regression that motivated this ----------------------------------------------------------

def test_713s_pattern_matches_a_real_message():
    real = "#713 5 screens captured the SAME image (md5 02a3e3): landing, player"
    # EXACT label, not a prefix: adding a "#713b shared-route sharing" line made
    # startswith("#713") ambiguous and this test selected the wrong pattern. The guard was
    # right; the selector was not.
    pat = next(p for l, p in _patterns().items() if l.startswith("#713 "))
    assert all(part in real for part in _parts(pat)), (pat, real)


def test_the_wording_that_used_to_be_searched_for_is_gone():
    """The deleted implementation's phrasing must not creep back into the checker."""
    assert not any("BYTE-IDENTICAL" in p for p in _patterns().values())


# --- the three false-alarm shapes are handled ------------------------------------------------------

def test_a_star_pattern_is_split_not_matched_whole():
    assert _parts("staged .* placeholder asset(s)") == ["staged ", " placeholder asset(s)"]


def test_bre_escaping_is_undone_before_comparing():
    assert _parts(r"\[projected\] data load failed:") == ["[projected] data load failed:"]


def test_folded_literals_are_searchable():
    hay = _haystack()
    assert 'the gating average has left the app behind' in hay


def test_a_trailing_anchor_does_not_break_the_lookup():
    assert _parts("net::ERR_CONNECTION_REFUSED$") == ["net::ERR_CONNECTION_REFUSED"]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
