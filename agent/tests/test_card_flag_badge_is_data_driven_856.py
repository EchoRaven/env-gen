r"""#856: the corpus's largest deviation class had no emitter, and the data for it was already there.

Found by opening the long tail item 180 left standing — **89% of deviation lines matched none of
the 13 hand-written clusters**, so I stopped hand-writing clusters and let phrase frequency name
them. The top phrases by RUN count were all one thing:

    recently added 105 runs | profile avatar 97 | kids badge 97 | new season 94
    new episode 88 | top badge 85 | live now 80 | today's top 75 | pagination dots 77

Summed as one class, **card badges/ribbons are 1505 entries across 115 of 119 runs — 19.4% of
every deviation line in the corpus**, an order of magnitude above `hover preview card` (160/94)
which the keyword pass had ranked #1. One class, dozens of wordings; exactly the trap that once
hid a pagination indicator under five names.

**#435 already emits a rank numeral, but it is gated on the ROW HEADING** ("Top 10"), so it can
only mark a ranked rail. Nothing rendered a PER-CARD status — and the data was present all along:
`is_kids` on catalog rows in **134 of 144 runs (2515 rows)**, plus a long tail of `is_trending`
(10 runs), `is_featured`, `recently_added`, `is_top10`, `added_at`.

★ **Product-agnostic by construction: the label is derived from the COLUMN NAME.** `is_kids` →
"Kids", `recently_added` → "Recently Added" — so a shop's `is_on_sale` renders "On Sale" and a job
board's `is_remote` renders "Remote". That is the #782 multi-key-fallback shape, not a schema
assumption, and it is why this is a framework capability rather than a Netflix hack.

Executed under node, like #782 — a source assertion here is what pinned #782 for 122 rounds.
"""
import json
import shutil
import subprocess

import pytest

from env_generator.llm_generator.multi_agent.runtime import frontend_scaffold as fs


_NODE = shutil.which("node") or shutil.which("nodejs")
pytestmark = pytest.mark.skipif(_NODE is None, reason="needs a node runtime to execute the JS")


def _js(exprs):
    src = fs._REF_HELPERS_JS.replace("\\`", "`")
    body = ";".join(f'out[{json.dumps(n)}] = {e}' for n, e in exprs)
    prog = f"const out = {{}};\n{src}\n{body};\nconsole.log(JSON.stringify(out));"
    r = subprocess.run([_NODE, "-e", prog], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr[-1500:]
    return json.loads(r.stdout)


def test_the_helpers_still_parse():
    """Non-vacuity: if the block fails to evaluate, every case below fails loudly rather than
    passing on an empty object."""
    assert _js([("k", "_BADGE_KEYS.length")])["k"] >= 10


def test_the_field_that_actually_exists_renders():
    """`is_kids` — 134 of 144 corpus runs, 2515 rows, and the judge reported it missing on 97."""
    assert _js([("v", '_badgesOf({"title":"X","is_kids":true})')])["v"] == ["Kids"]


@pytest.mark.parametrize("rec,want", [
    ({"is_new": True}, "New"),
    ({"is_trending": True}, "Trending"),
    ({"recently_added": True}, "Recently Added"),
    ({"coming_soon": True}, "Coming Soon"),
    ({"is_top10": True}, "Top10"),
])
def test_the_label_comes_from_the_column_name(rec, want):
    assert _js([("v", f"_badgesOf({json.dumps(rec)})")])["v"] == [want]


@pytest.mark.parametrize("rec,want", [
    ({"is_on_sale": True}, "On Sale"),
    ({"is_remote": True}, "Remote"),
    ({"is_free": True}, "Free"),
])
def test_a_non_media_app_gets_a_sensible_badge(rec, want):
    """★ The generality claim, tested rather than asserted: a shop and a job board get correct
    labels from the same code, with no product literal anywhere in it."""
    assert _js([("v", f"_badgesOf({json.dumps(rec)})")])["v"] == [want]


@pytest.mark.parametrize("v", [False, 0, "", None, "false", "False", "no", "0"])
def test_a_falsy_flag_renders_nothing(v):
    """`is_kids: false` is on more rows than `true` — a badge on every card would be worse than
    none."""
    assert _js([("v", f'_badgesOf({{"is_kids": {json.dumps(v)}}})')])["v"] == []


@pytest.mark.parametrize("rec", [{"status": "active"}, {"label": "Drama"}, {"tag": "sci-fi"},
                                 {"is_kids": "maybe"}, {"featured": "sometimes"}])
def test_an_arbitrary_string_is_never_a_badge(rec):
    """★ Only strict booleans count. A `status: "active"` column would otherwise stamp every card
    in the catalog — the #782 lesson in reverse: a plausible NAME whose VALUE is not what the
    badge means."""
    assert _js([("v", f"_badgesOf({json.dumps(rec)})")])["v"] == []


def test_a_row_with_no_flags_is_byte_identical():
    """The corpus is 10 of 144 runs without any such column; those apps must be unchanged."""
    assert _js([("v", '_badgesOf({"id":1,"title":"X","year":2019})')])["v"] == []
    assert _js([("v", "_badgesOf(null)")])["v"] == []


def test_multiple_flags_are_ordered_not_dropped():
    """The card shows the first, but the helper must not silently lose the rest — a caller may
    want them, and an accessor that truncates is the bound-with-no-check class."""
    v = _js([("v", '_badgesOf({"is_new":true,"is_kids":true,"is_trending":true})')])["v"]
    assert v == ["New", "Kids", "Trending"]


def test_no_helper_contains_a_control_character():
    """★ #856b, a guard for the whole block rather than for my mistake.

    `_REF_HELPERS_JS` is a NON-raw triple-quoted Python string, so a single-backslash escape in
    the JS is consumed at import time: `/\\b\\w/g` written as `/\b\w/g` reaches node as a
    literal BACKSPACE and a literal 0x17, and the regex silently stops matching. That is exactly
    what happened here — `_badgeLabel` returned `"kids"` instead of `"Kids"` — and the existing
    helpers only survive because they were written with doubled backslashes.

    The fix in `_badgeLabel` was to drop the regex for `split('_').map(...)`, so the code cannot
    have the bug. This test generalises it: nothing in the block may contain a control character,
    whatever a future author writes."""
    src = fs._REF_HELPERS_JS
    bad = [(i, repr(c)) for i, c in enumerate(src)
           if ord(c) < 32 and c not in "\n\t"]
    assert not bad, f"control characters from a swallowed escape: {bad[:5]}"
    assert len(src) > 2000, "non-vacuity: the block must be the real one"


# --- the emitter ---------------------------------------------------------------------------------

def test_the_badge_is_rest_visible_and_positioned_off_the_rank():
    """#435's rank numeral owns top-left and the two co-occur on ranked rails. It must also be
    REST-visible: the gate scores static screenshots, so a hover-only affordance scores nothing."""
    out = fs._card_flag_badge_856("#e50914")
    assert "absolute right-1 top-1" in out
    assert "hover" not in out
    assert "#e50914" in out


def test_the_card_site_calls_it_and_stays_positioned():
    """The container must carry `relative` unconditionally now — it used to be added only when the
    rank badge was present, and an absolutely-positioned badge in a static parent escapes the
    card."""
    import inspect
    src = inspect.getsource(fs)
    i = src.index("_card_flag_badge_856(accent) +")
    window = src[i - 700:i]
    assert 'relative\\" "' in window, window[-300:]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
