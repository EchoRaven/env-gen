"""#1186 — MATERIAL-PREP re-decomposed every reference screen on every resume.

It is one vision call per screen. netflix r17 (three resumes) and r21 each re-ran it in
full — ~3 minutes and ~$2.50 a time — over reference images that had not changed. Measured
on the live r21 resume: started 15:51:07, `MATERIAL-PREP: 20/20 reference screen(s)
decomposed` at 15:52:20, all 21 component_specs rewritten by 15:55.

The checkpoint cannot prevent this. Its `phases` entry stays `status=planning, iteration=0,
planned=0, generated=0` and its `files` map is empty, because `start_file`, `complete_file`
and `fail_phase` are never called anywhere in the framework. So the guard belongs at the
artifact, where it needs no resume flag at all: a spec that is newer than the image it came
from is already the answer.

Freshness is mtime against the SOURCE image, not mere existence — a replaced reference must
still be decomposed, and a corrupt spec must heal rather than stick.
"""
import asyncio
import json
import time

import pytest

from env_generator.llm_generator.multi_agent.runtime import reference_materials as rm


class _Logger:
    def __init__(self):
        self.lines = []

    def _rec(self, msg, *a):
        try:
            self.lines.append(str(msg) % a if a else str(msg))
        except Exception:
            self.lines.append(str(msg))

    info = warning = debug = error = _rec


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("ENVGEN_COMPONENT_SPECS", "1")
    imgs = []
    for n in ("home", "login", "player"):
        p = tmp_path / f"{n}.jpg"
        p.write_bytes(b"jpeg")
        imgs.append(str(p))
    calls = []

    async def _fake_decompose(img, llm):
        calls.append(img)
        return {"count": 2, "components": [{"name": "hero"}, {"name": "rail"}]}

    from env_generator.llm_generator.multi_agent.runtime import material_prep
    monkeypatch.setattr(material_prep, "decompose_reference", _fake_decompose)
    return tmp_path, imgs, calls


def _run(tmp_path, imgs, logger=None):
    return asyncio.run(rm.precompute_component_specs(
        images=imgs, output_dir=tmp_path, llm=object(), logger=logger or _Logger()))


def test_a_first_run_decomposes_everything(env):
    tmp_path, imgs, calls = env
    out = _run(tmp_path, imgs)
    assert len(calls) == 3 and len(out) == 3


def test_a_resume_decomposes_nothing_and_still_reports_the_specs(env):
    """★ The r17/r21 case: same images, specs already on disk."""
    tmp_path, imgs, calls = env
    first = _run(tmp_path, imgs)
    calls.clear()
    log = _Logger()
    second = _run(tmp_path, imgs, log)
    assert calls == [], "a resume must not re-run a single vision call"
    assert sorted(second) == sorted(first), "the staged specs are still the answer"
    assert any("reusing 3/3" in l for l in log.lines), log.lines


def test_a_changed_reference_is_decomposed_again(env):
    tmp_path, imgs, calls = env
    _run(tmp_path, imgs)
    calls.clear()
    time.sleep(0.01)
    from pathlib import Path
    Path(imgs[1]).write_bytes(b"jpeg-v2")          # the reference changed
    Path(imgs[1]).touch()
    _run(tmp_path, imgs)
    assert calls == [imgs[1]], "only the screen whose image is newer than its spec"


def test_a_corrupt_or_empty_spec_heals(env):
    tmp_path, imgs, calls = env
    _run(tmp_path, imgs)
    specs = tmp_path / "design" / "component_specs"
    (specs / "home.json").write_text("{ not json")
    (specs / "login.json").write_text(json.dumps({"components": []}))
    calls.clear()
    _run(tmp_path, imgs)
    assert sorted(calls) == sorted([imgs[0], imgs[1]]), (
        "an unreadable spec and one with no components must both be redone")


def test_nothing_is_written_when_disabled(env, monkeypatch):
    tmp_path, imgs, calls = env
    monkeypatch.setenv("ENVGEN_COMPONENT_SPECS", "0")
    assert _run(tmp_path, imgs) == [] and calls == []
