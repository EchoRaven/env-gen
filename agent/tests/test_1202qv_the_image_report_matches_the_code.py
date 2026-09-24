r"""#1202qv: the image-localization report describes the branch the code actually takes.

#1202qo removed the generated placeholder glyph: an image URL that matches no staged asset is
now left exactly as it is, so offline it renders as the browser's broken-image mark -- the
truth, instead of a substitute that looks like a working picture.

The report never followed. tiktok-r128 said, twice:

    IMAGE LOCALIZATION: 0 ref(s) matched a STAGED asset by filename token, 27 fell back to a
    generated PLACEHOLDER glyph (100%); 145 real asset(s) are staged.

No glyph was generated for any of those 27. Whoever read that line was told the app had 27
placeholder pictures in it; what it has is 27 <img> pointing at hosts that do not resolve. The
two call for different work, and the second is also the one worth the alarm.

`_placeholder_ref` survives with no callers -- this pins that it stays that way.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "env_generator" / "llm_generator")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

RT = ROOT / "env_generator" / "llm_generator" / "multi_agent" / "runtime"


def _heal_report() -> str:
    """The IMAGE LOCALIZATION format string, by landmark, not by offset."""
    src = (RT / "heal_pipeline.py").read_text(encoding="utf-8")
    i = src.index('"IMAGE LOCALIZATION: ')
    return src[i:src.index("_st, _ph,", i)]


def test_the_report_does_not_claim_a_placeholder_was_generated():
    assert "PLACEHOLDER glyph" not in _heal_report()


def test_the_report_says_the_unmatched_url_was_left_alone():
    r = _heal_report().lower()
    assert "external url" in r and "broken-image" in r


def test_the_report_still_names_the_staged_population():
    """The count that separates 'nothing was staged' from 'nothing matched'."""
    assert "staged" in _heal_report().lower()


def test_nothing_calls_the_placeholder_generator():
    """It builds the substitute the user ruled out; a caller would put it back."""
    src = (RT / "frontend_scaffold.py").read_text(encoding="utf-8")
    uses = [m.start() for m in re.finditer(r"_placeholder_ref\s*\(", src)]
    assert uses, "the name vanished - rewrite this test against whatever replaced it"
    # every mention must be its own definition; anything else is a call site
    callers = [u for u in uses if not re.search(r"def\s+$", src[max(0, u - 8):u])]
    assert callers == [], "a call site reintroduces the generated placeholder glyph"


def test_an_unmatched_image_url_is_left_untouched(tmp_path):
    """The behaviour the report now describes."""
    from multi_agent.runtime.frontend_scaffold import _local_ref_for
    pub = tmp_path / "public"
    (pub / "assets").mkdir(parents=True)
    tally = {}
    url = "https://images.example.com/photo-abc123"
    assert _local_ref_for(url, "avatar_url", pub, [], tally) == url
    assert tally.get("unmatched") == 1
    assert not (pub / "assets" / "placeholders").exists()
