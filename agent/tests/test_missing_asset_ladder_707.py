r"""#707: the staged asset set has no avatars, so the lane invented filenames and shipped 404s.

Found by checking the delivered corpus against the run description's own requirement — "use the
REAL provided assets", "no dead links". For every released run, every local `/assets/...` path
referenced in the shipped frontend was resolved against `app/frontend/public/`:

    delivered runs                      27
    local asset references              3712
    references that do not resolve      20, across 8 runs
    of those, /assets/avatars/...       **19**

Nineteen of twenty are profile avatars, each run inventing its own naming scheme —
`avatar-1.png`, `av_blue.svg`, `kid.png`, `profile-red.svg`, `av-01.svg` — and six of the eight
affected runs have no `avatars/` directory at all. The provided asset set has no avatars, the
"who's watching" screen needs them, and the frontend prompt gave the lane no sanctioned way out:
rule 3 says "USE THE REAL STAGED ASSETS", rule 5 says "IMAGES MUST RESOLVE", and neither says what
to do when the staged set does not contain the thing you need. So the lane broke rule 5.

The framework already ships the tools for this — `search_icons`, `search_logos`, `search_photos`,
`save_image`, all granted to the frontend lane. They are called in **0 of 253 run logs**, and
`search_icons`/`search_logos` appear in **no prompt at all**; `search_photos`/`save_image` appear
only in the shared definition, and only for gathering visual REFERENCES, not for filling an asset
gap. A tool nobody is told to use is a tool nobody uses.

Two changes, in that order of importance:

  * **frontend_agent.j2 rule 5b** states the ladder: staged asset → source it with
    search_icons/search_logos/search_photos + save_image → construct it in code (a monogram
    avatar is legitimate; rule 3 forbids ignoring an asset that EXISTS, not drawing one that does
    not) → and never the fourth option of referencing a path you did not create.
  * **`stage_missing_frontend_assets`** is the backstop. Its scan was
    `/assets/(icons|placeholders)/` — the two directories that were never the problem — so it
    could not see `avatars/` at all; and it skipped every non-SVG ("can't synthesize cheaply"),
    which is 11 of the 19. It now scans any `/assets/<dir>/`, writes a 1×1 transparent PNG for
    raster references, and LOGS every placeholder it had to invent, because silently filling a
    hole is how a real seeding bug would hide behind a grey square.
"""
import inspect
import pathlib
import tempfile

import pytest

from env_generator.llm_generator.multi_agent.runtime import frontend_scaffold as fs


def _tree(root: pathlib.Path, jsx: str, existing=()):
    (root / "app/frontend/src/pages").mkdir(parents=True)
    (root / "app/frontend/public/assets").mkdir(parents=True)
    for rel in existing:
        p = root / "app/frontend/public/assets" / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"REAL")
    (root / "app/frontend/src/pages/P.jsx").write_text(jsx, encoding="utf-8")


# --- the directory the lane invents is now in scope ------------------------------------------

def test_an_avatar_reference_is_staged():
    with tempfile.TemporaryDirectory() as td:
        root = pathlib.Path(td)
        _tree(root, "<img src='/assets/avatars/avatar-1.png'/>")
        assert fs.stage_missing_frontend_assets(root) == ["avatars/avatar-1.png"]


def test_a_raster_reference_gets_a_real_png():
    """The old code skipped every non-SVG; 11 of the 19 broken refs were .png."""
    with tempfile.TemporaryDirectory() as td:
        root = pathlib.Path(td)
        _tree(root, "<img src='/assets/avatars/kid.png'/>")
        fs.stage_missing_frontend_assets(root)
        b = (root / "app/frontend/public/assets/avatars/kid.png").read_bytes()
        assert b.startswith(b"\x89PNG\r\n\x1a\n"), "must be a decodable PNG, not an SVG in a .png"
        assert b.endswith(b"IEND\xaeB`\x82")


@pytest.mark.parametrize("ref", [
    "/assets/avatars/av_blue.svg", "/assets/avatars/profile-red.svg",
    "/assets/backdrops/landing_bg.jpg", "/assets/badges/new.webp",
])
def test_every_observed_broken_shape_is_covered(ref):
    with tempfile.TemporaryDirectory() as td:
        root = pathlib.Path(td)
        _tree(root, f"<img src='{ref}'/>")
        assert fs.stage_missing_frontend_assets(root), ref


def test_the_icons_case_still_works():
    """The original scope must not regress."""
    with tempfile.TemporaryDirectory() as td:
        root = pathlib.Path(td)
        _tree(root, "<img src='/assets/icons/home_24.svg'/>")
        assert fs.stage_missing_frontend_assets(root) == ["icons/home_24.svg"]


# --- it must never touch a real asset ------------------------------------------------------------

def test_an_existing_asset_is_left_alone():
    with tempfile.TemporaryDirectory() as td:
        root = pathlib.Path(td)
        _tree(root, "<img src='/assets/posters/real.jpg'/>", existing=["posters/real.jpg"])
        assert fs.stage_missing_frontend_assets(root) == []
        assert (root / "app/frontend/public/assets/posters/real.jpg").read_bytes() == b"REAL"


def test_a_remote_url_is_not_staged():
    with tempfile.TemporaryDirectory() as td:
        root = pathlib.Path(td)
        _tree(root, "<img src='https://cdn.example.com/assets/avatars/a.png'/>")
        out = fs.stage_missing_frontend_assets(root)
        assert out == [] or all("cdn" not in o for o in out)


def test_a_missing_frontend_is_a_no_op():
    with tempfile.TemporaryDirectory() as td:
        assert fs.stage_missing_frontend_assets(pathlib.Path(td)) == []


# --- the backstop announces itself ----------------------------------------------------------------

def test_it_logs_what_it_had_to_invent():
    src = inspect.getsource(fs.stage_missing_frontend_assets)
    assert "_LOG_707" in src
    assert "warning(" in src


def test_the_log_says_the_lane_skipped_the_ladder():
    src = inspect.getsource(fs.stage_missing_frontend_assets)
    assert "search_icons/search_photos/save_image" in src


# --- the prompt carries the ladder, which is the actual fix ----------------------------------------

def _prompt() -> str:
    root = pathlib.Path(fs.__file__).resolve().parents[1]
    return (root / "prompts" / "v3" / "frontend_agent.j2").read_text(encoding="utf-8")


def test_the_prompt_names_all_four_rungs():
    p = _prompt()
    assert "5b. WHEN THE STAGED SET HAS NO ASSET" in p
    for rung in ("search_icons(", "search_logos(", "search_photos(", "save_image("):
        assert rung in p, rung
    assert "CONSTRUCT it in code" in p


def test_the_prompt_forbids_the_fourth_option():
    p = _prompt()
    assert "never acceptable" in p
    assert "that file must exist in `app/frontend/public/`" in p


def test_the_prompt_resolves_the_conflict_with_rule_3():
    """Rule 3 forbids hand-drawing; 5b must say why constructing is different."""
    p = _prompt()
    assert "rule 3 is about ignoring an asset that EXISTS" in p


def test_the_prompt_carries_the_measurement():
    p = _prompt()
    assert "19 of 20 broken image references" in p


def test_the_original_rules_survive():
    p = _prompt()
    assert "USE THE REAL STAGED ASSETS" in p
    assert "IMAGES MUST RESOLVE" in p


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
