"""#1202jq: localizing an image chooses between a real asset and a glyph — say which.

`_local_ref_for` picks a STAGED asset when a filename token matches, else writes a generated
placeholder SVG. Those two produce very different apps, and both callers reported only WHICH
FILES were touched — so a run whose content imagery localized entirely to placeholders looked
identical, in every report, to one that matched real media every time.

tiktok-r109 is the instance: every `videos.thumbnail` became `/assets/placeholders/ph-img-0
.svg`, its explore grid rendered a wall of landscape glyphs, and the visual gate scored the
wound — nine of nine screens below the bar, mean 0.30, $339 spent. The adjacent r110 matched
real media and averaged 0.69 on the same env. Nothing said "the pictures are not here".

HONEST LIMIT, pinned in the docstring under test: across 49 runs the correlation is weak
(content imagery >=50% placeholder gives mean 0.35 over n=3, against 0.43 for the rest, and
one of the three scored 0.61). This reports a condition; it does not diagnose one, and it
changes no verdict.
"""
import sys
import pathlib
import json

_AGENT = pathlib.Path(__file__).resolve().parents[1]
if str(_AGENT) not in sys.path:
    sys.path.insert(0, str(_AGENT))

import inspect                                                          # noqa: E402

from env_generator.llm_generator.multi_agent.runtime import frontend_scaffold as FS  # noqa: E402


def _fe(tmp, src):
    fe = tmp / "frontend"
    (fe / "src").mkdir(parents=True)
    (fe / "public" / "assets").mkdir(parents=True)
    (fe / "src" / "Page.jsx").write_text(src, encoding="utf-8")
    return fe


def test_a_glyph_fallback_is_counted(tmp_path):
    fe = _fe(tmp_path, '<img src="https://images.unsplash.com/photo-1.jpg" />\n')
    r = FS.localize_frontend_external_images(fe)
    assert r["placeholder"] == 1 and r["staged"] == 0, r
    assert r["localized"], "non-vacuity: the rewrite must actually have happened"


def test_a_real_match_is_counted_as_staged(tmp_path):
    fe = _fe(tmp_path, '<img src="https://cdn.example.com/hero_shot.jpg" />\n')
    (fe / "public" / "assets" / "hero_shot.jpg").write_bytes(b"\xff\xd8\xff")
    r = FS.localize_frontend_external_images(fe)
    assert r["staged"] == 1 and r["placeholder"] == 0, r


def test_the_seed_localizer_reports_the_same_split(tmp_path):
    be = tmp_path / "backend"; be.mkdir()
    fe = _fe(tmp_path, "// no urls\n")
    (be / "seed_data.json").write_text(json.dumps(
        {"videos": [{"thumbnail": "https://images.unsplash.com/a.jpg"},
                    {"thumbnail": "https://cdn.example.com/real_clip.jpg"}]}))
    (fe / "public" / "assets" / "real_clip.jpg").write_bytes(b"\xff\xd8\xff")
    r = FS.localize_seed_external_images(be, fe)
    assert r["localized"] == 2, r
    assert r["staged"] == 1 and r["placeholder"] == 1, r


def test_the_counts_are_present_even_with_nothing_to_do(tmp_path):
    """Absent would read as zero anyway — but a caller dividing by staged+placeholder needs
    the keys to exist on every path, including the early return."""
    fe = _fe(tmp_path, "const a = 1;\n")
    r = FS.localize_frontend_external_images(fe)
    assert r["staged"] == 0 and r["placeholder"] == 0, r
    be = tmp_path / "empty"; be.mkdir()
    r2 = FS.localize_seed_external_images(be, fe)     # no seed_data.json at all
    assert "staged" in r2 and "placeholder" in r2, r2


def test_it_still_never_raises(tmp_path):
    """The `finally` that reports the split must not have displaced the `except`."""
    src = inspect.getsource(FS.localize_frontend_external_images)
    assert "except Exception as exc" in src and "finally:" in src, (
        "both are required: the counts report on every path, and the function still swallows")
    r = FS.localize_frontend_external_images(tmp_path / "does_not_exist")
    assert r["placeholder"] == 0


def test_the_honest_limit_is_recorded_at_the_site():
    """A count invites a causal reading. The weak corpus correlation belongs beside it."""
    doc = inspect.getdoc(FS._local_ref_for) or ""
    assert "HONEST LIMIT" in doc
    assert "n=3" in doc and "0.61" in doc, (
        "the counter-example — a high-placeholder run that scored well — is the half that "
        "stops the next reader treating this as a diagnosis")
