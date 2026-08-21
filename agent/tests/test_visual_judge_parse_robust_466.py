"""#466 (r45 shows=0.00 = 'judge JSON unparseable' — a 1.5MB rendered screen that
scored a FALSE 0.0 and dragged the mean). ROOT: the VLM judge's 7-dimension rubric
JSON (layout/components/style/color/typography/iconography/copy, each score+notes+fix,
plus deviations/fixes/summary) can exceed the old max_tokens=3000 → the response is
TRUNCATED → _parse_verdict's json.loads fails → it returned a real similarity=0.0
that was COUNTED in the mean AND (unlike 'judge call failed') NOT flagged judge_error,
so it was even cached as truth. A judge glitch must not corrupt the optimization
signal. FIX: (1) max_tokens 3000→8000 (headroom so the JSON never truncates — the root
cause); (2) flag unparseable/no-JSON as judge_error so a parse failure is never cached
as real 0.0 and is re-judged next milestone. Generalizable (every judge call/app) —
measurement integrity. Validate the parse contract directly (deterministic)."""
import sys
import types
from pathlib import Path

_SRC = (Path(__file__).resolve().parents[1] / "env_generator" / "llm_generator"
        / "multi_agent" / "runtime" / "visual_fidelity.py")


def _load():
    pkg = types.ModuleType("vf_pkg")
    pkg.__path__ = []
    vr = types.ModuleType("vf_pkg.validation_runner")
    vr._service_host_port = lambda *a, **k: None
    sys.modules["vf_pkg"] = pkg
    import env_generator.llm_generator.multi_agent.runtime.message_format as _mf1034
    sys.modules["vf_pkg.message_format"] = _mf1034  # #1034: leaf helper, no deps
    sys.modules["vf_pkg.validation_runner"] = vr
    # #898: `visual_fidelity` derives its ceilings via `stage_contract.llm_ceiling_898`, imported
    # inside the accessor. This harness hand-stubs each module the source reaches, so a new one
    # must be added here too — the same contract `validation_runner` above is satisfying.
    import env_generator.llm_generator.multi_agent.runtime.stage_contract as _sc
    sys.modules["vf_pkg.stage_contract"] = _sc
    mod = types.ModuleType("vf_pkg.visual_fidelity")
    mod.__package__ = "vf_pkg"
    exec(compile(_SRC.read_text(encoding="utf-8"), str(_SRC), "exec"), mod.__dict__)
    return mod


VF = _load()


def test_valid_json_parses_without_judge_error():
    text = ('```json\n{"similarity": 0.72, "dimensions": {"layout": {"score": 0.8, '
            '"notes": "good"}}, "deviations": ["x"], "fixes": [], "summary": "ok"}\n```')
    v = VF._parse_verdict(text)
    assert abs(v["similarity"] - 0.72) < 1e-6
    assert v["dimensions"]["layout"]["score"] == 0.8
    assert not v.get("judge_error"), "a cleanly-parsed verdict must NOT be judge_error"


def test_truncated_json_is_judge_error_not_real_zero():
    # a response cut off mid-JSON (the max_tokens truncation that caused shows=0.00)
    # cut off mid-JSON but with an inner '}' so the {.*} extractor matches an
    # UNBALANCED span → json.loads fails (the 'unparseable' path, distinct from no-JSON)
    truncated = ('{"similarity": 0.55, "dimensions": {"layout": {"score": 0.6, '
                 '"notes": "hero billboard is und"}')
    v = VF._parse_verdict(truncated)
    assert v["similarity"] == 0.0
    assert v.get("judge_error") is True, \
        "unparseable/truncated JSON must be judge_error (transient), not cached as real 0.0"
    assert "unparseable" in " ".join(v["deviations"])


def test_no_json_at_all_is_judge_error():
    v = VF._parse_verdict("I could not compare these images.")
    assert v["similarity"] == 0.0
    assert v.get("judge_error") is True
    assert "no JSON" in " ".join(v["deviations"])


def test_max_tokens_budget_raised():
    # guard the root-cause fix: the judge call must request ample tokens so the
    # rubric JSON never truncates again (the value lives in judge_screen_pair's source)
    src = _SRC.read_text(encoding="utf-8")
    assert "max_tokens=8000" in src, "judge max_tokens must be raised (was 3000 → truncation)"
    assert "max_tokens=3000" not in src, "the old truncating 3000 budget must be gone"


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
