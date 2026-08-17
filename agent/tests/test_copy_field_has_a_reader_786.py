r"""#786: `copy` had a writer and zero readers — the exact defect #779 was fixing, committed on
the same day, by me, while fixing it.

#779's finding: `design_system.shadow_scale` and `design_system.material` are MEASURED from the
reference, written to `design_system.json`, and **named nowhere in the frontend prompt**. A field
with a writer and no reader cannot move a score, and `style` was the lowest-mean dimension (0.615,
`flat` in 79% of 504 notes). The fix was to name them in the lane's build spec.

#778, added hours later, put `copy` on the design-prep component schema, wrote a prompt clause
demanding verbatim transcription, and carried the field through both fixed-key projections. Every
part of the WRITE path. Then:

    grep 'get("copy")' / '["copy"]'  over runtime/   -> nothing
    grep for a component `copy` field over the prompts -> nothing
                                                          (only the English word, and `&copy;`)

So the transcribed reference text was being measured, validated and persisted, and no consumer
ever asked for it. `ui_copy` would have kept scoring as a floor dimension with the fix "shipped".

★ The lesson is not "check for readers" — #779 IS that lesson, written down, and it did not
transfer to the next change made by the same author on the same day. **A new field is not done
when it is produced and tested; it is done when something CONSUMES it.** The write path is the
easy half and it is the half that has tests, which is precisely why it feels finished.

These tests assert the reader exists in both prompt versions (v3 is default, v4 opt-in per #269 —
a clause added to only one silently applies to some runs and not others, which is how a prompt
change becomes unreproducible).
"""
import pathlib

import pytest


_PROMPTS = pathlib.Path(__file__).resolve().parents[1] / (
    "env_generator/llm_generator/multi_agent/prompts")


def _frontend(v: str) -> str:
    return (_PROMPTS / v / "frontend_agent.j2").read_text(encoding="utf-8")


@pytest.mark.parametrize("v", ["v3", "v4"])
def test_the_copy_field_is_named_to_the_lane(v):
    s = _frontend(v)
    assert "`copy`" in s, "the field the lane must read is not named"
    assert "VERBATIM text transcribed" in s


@pytest.mark.parametrize("v", ["v3", "v4"])
def test_the_instruction_is_actionable_not_just_a_mention(v):
    """#779's failure mode was silence; a bare mention would be the same failure with extra words.
    The clause has to say what to DO with the field."""
    s = _frontend(v)
    assert "character for character" in s
    assert "do not paraphrase" in s
    assert "invent none" in s, "the empty case must be stated or the lane fills it with guesses"


@pytest.mark.parametrize("v", ["v3", "v4"])
def test_the_measurement_travels_with_the_instruction(v):
    """#779's clause carries its own evidence (79% / 0.615) so a later reader can tell whether the
    instruction is load-bearing. This one carries 9152 / 84%."""
    s = _frontend(v)
    assert "9152" in s and "84%" in s


@pytest.mark.parametrize("v", ["v3", "v4"])
def test_779s_own_fields_are_still_named(v):
    """Non-regression: the fix this one was modelled on must not have been edited away."""
    s = _frontend(v)
    assert "shadow_scale" in s and "material" in s


# --- #787: the same sweep found a second orphan, and it is per-screen layout ground truth -----

@pytest.mark.parametrize("v", ["v3", "v4"])
def test_layout_metrics_is_named_to_the_lane(v):
    """`screens[].layout_metrics` is written by design_prep.py and read by NOBODY — not another
    framework module, not either prompt. r151 carries it on 20 of 20 screens with 15 DISTINCT
    boxes, so it is real per-screen ground truth: `left_px: 0, width_px: 1918` (full-bleed) vs
    `left_px: 66, width_px: 1786` (~66px gutters). The prompt meanwhile asks the lane to match
    'content max-width' by eye."""
    s = _frontend(v)
    assert "layout_metrics" in s
    assert "FULL-BLEED" in s, "the zero-gutter case is the one an eyeballed container gets wrong"
    assert "PER SCREEN" in s and "15 distinct boxes" in s


def test_both_prompt_versions_got_the_same_clause():
    """v3 is default and v4 is opt-in per file (#269). The first attempt at this clause patched v3
    and threw on v4 because the anchor text differs between them — a half-applied prompt change
    makes runs silently non-comparable, which is the failure this asserts against."""
    a, b = _frontend("v3"), _frontend("v4")
    for marker in ("LAYOUT IS MEASURED FOR YOU TOO", "VERBATIM text transcribed"):
        assert marker in a and marker in b, marker


# --- #788: a prompt claim of enforcement that no code backs ----------------------------------

@pytest.mark.parametrize("v", ["v3", "v4"])
def test_the_binding_spec_claim_is_true(v):
    """The prompt told the lane its `screens + must_have lists are enforced by user gates at
    delivery`. Exhausting every reader:

        reference_materials.py:208  the LLM prompt that WRITES must_have
        hub_tools.py:2488/2536/2544 the kickoff tool that ACCEPTS and stores it
        frontend_audit.py:952/959   reads it ONLY to decide whether a page is a MAP

    Nothing compares it to the built UI. `.user_gates.json` is a real mechanism
    (live_monitor_server.py) but does not read it. The `screens` half IS enforced, just not by a
    'user gate' — the visual gate captures and scores every spec screen, so an unbuilt one is a
    blocking zero. Half-true, and the false half is the half that reads as a checklist."""
    s = _frontend(v)
    assert "enforced by user gates at delivery" not in s, "the false claim survived"
    assert "is NOT machine-checked anywhere" in s
    assert "blocking zero" in s, "the half that IS true must still motivate the lane"


@pytest.mark.parametrize("v", ["v3", "v4"])
def test_the_correction_defers_to_781(v):
    """must_have is extracted from materials that may be DOCUMENTS, while #781 binds the judge to
    the reference IMAGE. Naming a precedence stops the two instructions fighting."""
    s = _frontend(v)
    assert "the image wins (#781)" in s


def test_must_have_is_still_only_read_for_map_detection():
    """Non-vacuity: if someone later wires real enforcement, this test should fail and be
    replaced by one that checks it — rather than the prompt quietly becoming true again."""
    import inspect
    from env_generator.llm_generator.multi_agent.runtime import frontend_audit
    src = inspect.getsource(frontend_audit)
    i = src.index("must_have")
    assert "_is_map_page" in src[max(0, i - 900):i + 200]


def test_the_write_path_still_produces_the_field():
    """Non-vacuity for the whole item: a reader is only worth having if the writer still runs.
    #778 put `copy` on the schema and through BOTH fixed-key projections."""
    from env_generator.llm_generator.multi_agent.runtime import design_prep as dp
    import inspect
    src = inspect.getsource(dp)
    assert '"copy": {"type": "string"}' in src, "the schema field"
    assert src.count('"copy"') >= 3, "schema + both projections (the #500/#771 fixed-key class)"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
