r"""#822: a screen the SPEC declares but no reference image covers is dropped silently.

The skeleton is built from the reference IMAGES, so `reference_spec.json` can require a screen the
pipeline will never see. Measured over r140+:

    `profiles`  declared in 11 of 11 runs
                reference image in 0 of them
                -> absent from every design_system.json, every visual_gate capture, every verdict

Never photographed, never scored, never blocking. For a streaming clone that is the who's-watching
picker — the first screen after login.

★ It also corrects #788, which recorded the spec's `screens` list as ENFORCED on the grounds that
*"the visual gate captures and scores every screen in it, so an unbuilt one is photographed blank
and takes a blocking zero."* True only for screens **with** a reference image; silent for the rest.
I wrote that sentence; this is the measurement that qualifies it.

Nothing is invented here — a screen cannot be scored against an image that does not exist. What
changes is that the gap is **stated** instead of inferred from an absence.
"""
import logging
import pathlib
import shutil
import tempfile

import pytest

from env_generator.llm_generator.multi_agent.runtime import design_prep as dp


_R151 = (pathlib.Path(__file__).resolve().parents[1]
         / "generated" / "netflix-web-r151" / "design")


def _build(refs, tmp):
    out = pathlib.Path(tmp)
    (out / "design").mkdir(parents=True, exist_ok=True)
    shutil.copy(_R151 / "reference_spec.json", out / "design" / "reference_spec.json")
    return dp.build_skeleton_design_system({"references": refs}, out)


def test_the_real_gap_is_named_and_only_it(caplog):
    """★ Non-vacuity in the direction that matters: with every real reference present, exactly one
    screen is reported — the one that genuinely has no image."""
    if not (_R151 / "reference_spec.json").is_file():
        pytest.skip("r151 not present")
    refs = sorted(str(p) for p in (_R151 / "references").glob("*.jpg"))
    assert len(refs) > 15, "non-vacuity: the fixture really does carry the references"
    with tempfile.TemporaryDirectory() as d, caplog.at_level(logging.WARNING):
        ds = _build(refs, d)
    assert len(ds.get("screens") or []) == 20
    msgs = [r.getMessage() for r in caplog.records if "no reference image" in r.getMessage()]
    assert len(msgs) == 1
    assert "['profiles']" in msgs[0]


def test_profiles_really_is_absent_from_the_skeleton():
    if not (_R151 / "reference_spec.json").is_file():
        pytest.skip("r151 not present")
    refs = sorted(str(p) for p in (_R151 / "references").glob("*.jpg"))
    with tempfile.TemporaryDirectory() as d:
        ds = _build(refs, d)
    assert "profiles" not in {s.get("name") for s in ds.get("screens") or []}


def test_the_message_says_what_it_costs():
    """'A screen is missing' understates it: the consequence is that the gate cannot block on it,
    which is the part a reader needs."""
    # Asserted on fragments that do not span a string-literal line wrap. The first version used
    # the whole sentence and failed against working code because the message is assembled from
    # two adjacent literals — the fifth time this session that a wrap broke an assertion.
    import inspect
    src = inspect.getsource(dp.build_skeleton_design_system)
    assert "capture, score or block on them" in src
    assert "enforced only" in src


def test_a_spec_with_every_image_is_silent(caplog):
    """Non-vacuity the other way: no warning when nothing is missing, or it becomes noise."""
    if not (_R151 / "reference_spec.json").is_file():
        pytest.skip("r151 not present")
    import json
    with tempfile.TemporaryDirectory() as d:
        out = pathlib.Path(d)
        (out / "design").mkdir(parents=True)
        (out / "design" / "reference_spec.json").write_text(
            json.dumps({"screens": []}), encoding="utf-8")
        with caplog.at_level(logging.WARNING):
            dp.build_skeleton_design_system({"references": []}, out)
    assert not [r for r in caplog.records if "no reference image" in r.getMessage()]


def test_a_missing_spec_file_is_not_an_error():
    """design-prep runs before every lane; this check must never be the thing that breaks it."""
    with tempfile.TemporaryDirectory() as d:
        dp.build_skeleton_design_system({"references": []}, pathlib.Path(d))


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
