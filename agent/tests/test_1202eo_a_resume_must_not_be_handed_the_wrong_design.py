r"""#1202eo: a resume without DESIGN was silently handed netflix's references.

`run_validation.sh` carried `DESIGN="${DESIGN:-$REPO/design_inputs/netflix}"`. Resuming any
other env without passing DESIGN therefore fed it NETFLIX's design input. googlemaps-r16's
three resumes did exactly that: the reference spec was recompiled from netflix's 20 images
and overwrote google_maps' own —

    main run   30 files / 29 images -> 13 screens, 18 endpoints, 20 entities, 8 mcp tools
    resume 1   21 files / 20 images -> 17 screens, 17 endpoints,  9 entities, 0 mcp tools

— and every gate afterwards judged a google_maps app against netflix's contract. About
$340 of resume time was spent on a mismatched spec, and the failures it produced read as
real defects until the image counts gave it away.

Two halves. The launcher no longer has an env-specific default (the project's standing
rule is that nothing in the pipeline hardcodes one env). And the compile says so out loud
when it is about to replace a spec that different inputs produced — #1202ca's reuse check
is correct but cannot know that different inputs on a resume mean a wrong launch.
"""
from pathlib import Path

import pytest

THIS_DIR = Path(__file__).resolve().parent
ROOT = THIS_DIR.parents[1]
SH = (ROOT / "run_validation.sh").read_text(encoding="utf-8")
RM = (ROOT / "agent" / "env_generator" / "llm_generator" / "multi_agent" / "runtime"
      / "reference_materials.py").read_text(encoding="utf-8")


def test_the_launcher_has_no_env_specific_design_default():
    """The standing rule: no env-specific hardcoding anywhere in the pipeline."""
    assert 'DESIGN="${DESIGN:-$REPO/design_inputs/netflix}"' not in SH
    assert "design_inputs/netflix\"" not in SH.replace("# ", "")


def test_a_resume_prefers_the_input_the_run_was_built_with():
    assert ".design_input_1202eo" in SH
    i = SH.index('if [ -z "${DESIGN:-}" ]; then')
    seg = SH[i:SH.index("if [ ! -d", i)]
    assert "_recorded" in seg and "cat " in seg


def test_it_refuses_rather_than_guessing():
    i = SH.index('if [ -z "${DESIGN:-}" ]; then')
    seg = SH[i:SH.index("if [ ! -d", i)]
    assert "REFUSING" in seg and "exit 2" in seg


def test_a_nonexistent_design_is_refused():
    assert 'if [ ! -d "$DESIGN" ]' in SH


def test_the_launcher_records_what_it_used():
    """So the next resume can recover it instead of defaulting."""
    # the WRITE site, not the read site the resume branch uses. Bounded by the landmark
    # that follows it, never by a byte count (#943 — my fourth offence today).
    i = SH.rindex(".design_input_1202eo")
    seg = SH[SH.rindex("mkdir -p", 0, i):SH.index("DESC=", i)]
    assert "printf" in seg, seg


def test_the_recompile_announces_what_it_replaces():
    i = RM.index("#1202eo RECOMPILING OVER AN EXISTING REFERENCE SPEC")
    seg = RM[i:RM.index("except Exception as _pe_1202eo", i)]
    for field in ("screens", "endpoints", "entities", "mcp_tools"):
        assert field in seg, f"the notice must name {field} — the counts are the tell"


def test_the_notice_cannot_break_the_compile():
    i = RM.index("#1202eo: SAY SO WHEN A RECOMPILE")
    seg = RM[i:RM.index("spec, _ = await", i)]
    assert "except Exception" in seg
    assert "warn_once_1201" in seg
