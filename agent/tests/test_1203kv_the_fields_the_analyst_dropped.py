"""#1203kv/#1203kw: the analyst rewrites design_system.json and every MEASURED field is gone.

`design_prep`'s own merge is careful about them — `# assets: add description/use by id (never
touch id/file/type/dims/staged_path)` — but the document that reaches the orchestrator is
usually not the merge's output. The spawned design_analyst REWRITES the whole file, and its
shape is `{id, file, staged_path, description, use}`. `load_valid_design_system` accepts it,
because all it asks is that the document parse and carry `design_system` or `screens`.

MEASURED over the 39 modern runs carrying a design_system.json — 882 asset entries, `type`
absent on 882 of them — by driving the real consumers over the real documents:

    _nav_utility_icons  (#421, the top-nav search/bell/kids/profile cluster)   0/39 non-empty
    _ref_image_pool     (#415, the projector's hero bg + rail/grid posters)    0/39 non-empty

and with the fields restored, 39/39 and 36/39. #421 then resolves `icons/search_20e71c0a.svg`
and `icons/profile_9410ceda.svg` — icons that were staged, served, and unreachable because a
word was missing. (`_brand_logo_url` filters on `type` too and stays empty either way; its
cause is elsewhere and this does not claim it.)

#1203kw is the other half, and it is why the fields are RE-MEASURED rather than guessed from
the filename. Of the icons the restored #421 resolves, 39 of 39 runs emit exactly one through
the `<img>` channel, always `Account`, and 39 of 39 of those files are `fill="currentColor"`
with no colour of their own — the invisible-on-a-themed-nav class that #551 already named, for
two labels it listed by name. Reviving #421 without generalising that rule would have put an
invisible image on every nav, beside #443's avatar chip that already renders the account.
"""
import ast
import inspect
import json
import logging
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime import design_prep as DP  # noqa: E402
from multi_agent.runtime import frontend_scaffold as FS  # noqa: E402

# A monochrome icon, the shape tiktok's `icons/profile_9410ceda.svg` really has.
MONO_SVG = ('<svg fill="currentColor" viewBox="0 0 48 48" width="1em" height="1em">'
            '<path d="M24 3a10 10 0 1 1 0 20Z"></path></svg>')
# One that carries its own colour, the shape `explore-card-user-verified_6717018b.svg` has.
COLOURED_SVG = ('<svg viewBox="0 0 24 24" width="24" height="24">'
                '<circle cx="12" cy="12" r="11" fill="#20d5ec"/></svg>')
ANALYST_KEYS = ("id", "file", "staged_path", "description", "use")


def _entry(aid, rel, desc="An icon."):
    """Exactly the five keys the analyst's rewrite carries — no more."""
    return {"id": aid, "file": rel, "staged_path": "public/assets/" + rel,
            "description": desc, "use": ["left navigation"]}


def _stage(tmp_path, files):
    d = tmp_path / "design" / "assets"
    for rel, body in files.items():
        p = d / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(body, bytes):
            p.write_bytes(body)
        else:
            p.write_text(body, encoding="utf-8")
    return tmp_path


def _doc(assets):
    return {"design_system": {"palette": {"bg": "#000"}}, "screens": [],
            "assets": [dict(a) for a in assets]}


def test_the_measured_fields_come_back_from_the_staged_file(tmp_path):
    _stage(tmp_path, {"icons/profile_94.svg": MONO_SVG,
                      "icons/verified.svg": COLOURED_SVG})
    out = DP.complete_design_system(
        _doc([_entry("profile-94", "icons/profile_94.svg"),
              _entry("verified", "icons/verified.svg")]), {}, tmp_path)
    by = {a["id"]: a for a in out["assets"]}
    assert by["profile-94"]["type"] == "svg", by["profile-94"]
    assert by["verified"]["type"] == "svg", by["verified"]
    # dominant_colors is the field #1203kw needs, and it CANNOT be derived from a filename
    assert by["profile-94"]["dominant_colors"] == [], by["profile-94"]
    assert by["verified"]["dominant_colors"] == ["#20d5ec"], by["verified"]
    assert by["verified"]["dims"] == [24, 24], by["verified"]
    # the analyst's own words survive untouched
    assert by["profile-94"]["description"] == "An icon."
    assert by["profile-94"]["use"] == ["left navigation"]


def test_a_value_the_analyst_authored_is_never_overwritten(tmp_path):
    _stage(tmp_path, {"icons/x.svg": COLOURED_SVG})
    a = _entry("x", "icons/x.svg")
    a["type"] = "sprite"
    a["dominant_colors"] = ["#000000"]
    out = DP.complete_design_system(_doc([a]), {}, tmp_path)
    assert out["assets"][0]["type"] == "sprite", out["assets"]
    assert out["assets"][0]["dominant_colors"] == ["#000000"], out["assets"]


def test_a_file_that_is_gone_gets_its_type_and_no_invented_measurements(tmp_path):
    """An absent field must stay absent rather than become a measurement nobody made."""
    out = DP.complete_design_system(
        _doc([_entry("ghost", "icons/not-on-disk.svg")]), {}, tmp_path)
    a = out["assets"][0]
    assert a["type"] == "svg", a
    for k in ("dims", "transparent", "dominant_colors"):
        assert k not in a, (k, a)


def test_the_consumer_comes_alive(tmp_path):
    """The half that matters: a restored field nobody reads changes nothing, so this drives
    the real #421 resolver rather than asserting on the field."""
    _stage(tmp_path, {"icons/search_20.svg": MONO_SVG,
                      "icons/Notifications_e2.svg": MONO_SVG,
                      "icons/profile_94.svg": MONO_SVG})
    assets = [_entry("search-20", "icons/search_20.svg"),
              _entry("notifications-e2", "icons/Notifications_e2.svg"),
              _entry("profile-94", "icons/profile_94.svg")]
    before = _doc(assets)
    assert FS._nav_utility_icons(before) == [], (
        "NON-VACUITY: without the measured fields the resolver is the empty list this "
        "ticket measured in 39 of 39 runs")
    after = DP.complete_design_system(_doc(assets), {}, tmp_path)
    got = dict(FS._nav_utility_icons(after))
    assert got.get("Search") == "/assets/icons/search_20.svg", got
    assert got.get("Notifications") == "/assets/icons/Notifications_e2.svg", got
    assert got.get("Account") == "/assets/icons/profile_94.svg", got


def test_a_monochrome_icon_does_not_reach_the_nav_as_an_image_1203kw(tmp_path):
    _stage(tmp_path, {"icons/profile_94.svg": MONO_SVG})
    ds = DP.complete_design_system(
        _doc([_entry("profile-94", "icons/profile_94.svg")]), {}, tmp_path)
    assert dict(FS._nav_utility_icons(ds)).get("Account"), "the resolver must still find it"
    jsx = FS._ref_nav_jsx([("Home", "/")], "#e50914", vertical=False, design=ds)
    assert "profile_94.svg" not in jsx, (
        "#1203kw: an SVG with no colour of its own paints its own default inside an <img>, "
        "where the nav's CSS cannot reach it — #551's rule, asked of the asset instead of a "
        "label list.\n" + jsx)

    # NON-VACUITY: the <img> channel is alive — a coloured asset on the same label is emitted
    _stage(tmp_path / "col", {"icons/profile_col.svg": COLOURED_SVG})
    ds2 = DP.complete_design_system(
        _doc([_entry("profile-col", "icons/profile_col.svg")]), {}, tmp_path / "col")
    jsx2 = FS._ref_nav_jsx([("Home", "/")], "#e50914", vertical=False, design=ds2)
    assert "profile_col.svg" in jsx2, jsx2
    assert 'alt="Account"' in jsx2, jsx2


def test_551s_two_labels_are_still_routed_inline_even_when_coloured(tmp_path):
    """#1203kw replaced #551's label list as the test for INVISIBILITY, not as the reason
    those two labels skip the <img> channel. They skip it because `_nav_chrome_454` already
    renders them inline, so emitting an <img> as well would duplicate the icon.

    Found by mutation: deleting the label list changed nothing in the tests above, because
    every search/bell fixture there is monochrome and the colour test excludes it anyway.
    A COLOURED search asset is the case where the list is load-bearing.
    """
    _stage(tmp_path, {"icons/search_col.svg": COLOURED_SVG})
    ds = DP.complete_design_system(
        _doc([_entry("search-col", "icons/search_col.svg", "Search.")]), {}, tmp_path)
    # NON-VACUITY: it IS resolved, and it DOES carry its own colour
    assert dict(FS._nav_utility_icons(ds)).get("Search"), FS._nav_utility_icons(ds)
    assert ds["assets"][0]["dominant_colors"] == ["#20d5ec"], ds["assets"]

    jsx = FS._ref_nav_jsx([("Home", "/")], "#e50914", vertical=False, design=ds)
    assert 'aria-label="Search"' in jsx, ("the inline chrome must render the search", jsx)
    assert "search_col.svg" not in jsx, (
        "#551: an <img> here would be a SECOND search icon beside the inline one.\n" + jsx)


def test_an_unmeasured_colour_field_is_not_read_as_no_colour(tmp_path):
    """`dominant_colors` ABSENT means not measured; only a measured EMPTY list excludes. The
    difference matters for an entry whose staged file is gone."""
    # The id has to carry a token #421 matches ("profile"), or the resolver never offers it
    # and the test would pass for the wrong reason. Nothing is staged for it, so the fields
    # stay unmeasured.
    a = _entry("profile-gone", "icons/profile_gone.svg")
    ds = DP.complete_design_system(_doc([a]), {}, tmp_path)
    assert "dominant_colors" not in ds["assets"][0], ds["assets"]
    assert dict(FS._nav_utility_icons(ds)).get("Account"), (
        "NON-VACUITY: the resolver must offer it, or nothing is being excluded or kept")
    jsx = FS._ref_nav_jsx([("Home", "/")], "#e50914", vertical=False, design=ds)
    assert "profile_gone.svg" in jsx, ("an unmeasured asset keeps the status quo", jsx)


def test_the_file_question_is_not_restated_here():
    """#1032: `material_prep` owns "what is this file", and it is the same `_ingest_one` that
    built the original manifest — so the restored values agree with it by construction rather
    than by my having copied its tables correctly."""
    src = inspect.getsource(DP.complete_design_system)
    tree = ast.parse(src)
    imported = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.ImportFrom) and (n.module or "").endswith("material_prep"):
            imported |= {a.name for a in n.names}
    assert "_ingest_one" in imported, imported
    lits = [n for n in ast.walk(tree) if isinstance(n, ast.Dict)
            and any(isinstance(k, ast.Constant) and isinstance(k.value, str)
                    and k.value.startswith(".") for k in n.keys)]
    assert lits == [], "a second suffix table would drift from material_prep's"


def test_the_count_is_reported(tmp_path, caplog):
    """A counter the pass keeps and nobody prints is a measurement nobody receives — the
    defect class this ticket is an instance of. `screens_routed` (#352) was in that position
    too; the line names both now."""
    _stage(tmp_path, {"icons/x.svg": COLOURED_SVG})
    with caplog.at_level(logging.INFO, logger="Orchestrator"):
        DP.complete_design_system(_doc([_entry("x", "icons/x.svg")]), {}, tmp_path)
    said = " ".join(r.getMessage() for r in caplog.records)
    assert "1 asset(s) re-measured" in said, said
    assert "screens routed" in said, said


def test_every_modern_corpus_run_resolves_the_cluster_after_the_pass(tmp_path):
    """The measurement in the docstring, re-run against the real documents and the real
    staged files. Skipped when the corpus is not on this disk."""
    import pytest
    # The measured baseline "0 of 39" is a MODERN-ERA number. The corpus holds 137 runs and
    # the older design documents DO carry `type`, so a universe of every run reads 115
    # non-empty before the pass and says nothing about this defect. Restoring the era is
    # part of restoring the measurement.
    docs = []
    for p in sorted((ROOT.parent / "generated").glob("*/design/design_system.json")):
        _m = re.search(r"r(\d+)$", p.parent.parent.name)
        if not _m or int(_m.group(1)) < 150:
            continue
        try:
            d = json.loads(p.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            continue
        if isinstance(d, dict) and (d.get("assets") or []) and (
                p.parent / "assets").is_dir():
            docs.append((p.parent.parent, d))
    if len(docs) < 10:
        pytest.skip("too few corpus design docs on this disk (%d)" % len(docs))
    before = sum(1 for _r, d in docs if FS._nav_utility_icons(d))
    # #1203mk: captured HERE, not after the loop below -- `complete_design_system` mutates
    # the doc it is handed, so the same comprehension run afterwards sees every doc already
    # completed and names the whole corpus. (My first version of this fix did exactly that
    # and the test caught it.)
    _FIRST_POST_FIX_RUN_1203MK = 189
    _early_1203mk = [run.name for run, d in docs if FS._nav_utility_icons(d)
                     and int(re.search(r"r(\d+)$", run.name).group(1))
                     < _FIRST_POST_FIX_RUN_1203MK]
    after = 0
    for i, (run, d) in enumerate(docs):
        # The pass ENDS by rewriting design_system.json, so it must never be pointed at a
        # corpus run. Give it a scratch output dir whose design/assets SYMLINKS the real
        # staged files: the measurement reads exactly those bytes, every write lands in tmp.
        work = tmp_path / ("run%d" % i) / "design"
        work.mkdir(parents=True)
        (work / "assets").symlink_to(run / "design" / "assets")
        after += 1 if FS._nav_utility_icons(
            DP.complete_design_system(d, {}, work.parent)) else 0
    # #1203mk: this was a bare `assert before == 0`, and it went RED the first time the fix
    # it guards reached a real run. r189 is the first run launched after #1203kv restored the
    # field the design_analyst was dropping, so r189's own `design_system.json` resolves nav
    # utility icons BEFORE the completion pass -- which is the fix WORKING, reported as a
    # test failure. Exactly the direction #1203kz's note warns about: an assertion that the
    # corpus still shows the defect turns red on the day the defect is fixed.
    #
    # The historical measurement is kept as what it is -- a measurement, with its date -- and
    # the live claim is narrowed to the runs it can still be true of: a run that PREDATES the
    # fix must still show the empty baseline, because nothing has changed for it.
    #
    #   measured 2026-10-14, before the fix: 39 of 39 modern runs returned empty.
    assert not _early_1203mk, (
        "a run that predates #1203kv resolves nav utility icons before the completion pass, "
        "so the baseline this ticket measured no longer holds for it", _early_1203mk)
    assert after >= len(docs) * 0.9, (after, len(docs))
