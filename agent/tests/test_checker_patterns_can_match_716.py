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


# --- the regression that motivated this ----------------------------------------------------------

def test_713s_pattern_matches_a_real_message():
    real = "#713 5 screens captured the SAME image (md5 02a3e3): landing, player"
    pat = next(p for l, p in _patterns().items() if l.startswith("#713"))
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
