r"""#767: a 0.00 discarded the only thing that could explain it.

r150 released with eight screens at 0.00 whose captures are 1.4-1.6 MB of correctly rendered
page. I opened the PNGs: `browse_home` is a complete Netflix clone — wordmark, full nav, hero
with a seeded title and synopsis, three poster rails of real artwork. So the zeros are a
MEASUREMENT failure, and the question that would settle it —

    did the judge actually SAY 0.0, or did it return an empty JSON that #766 now flags?

— could not be answered, because `_parse_verdict` reads the reply and throws the text away.

A zero is the one score worth keeping evidence for: it is the only value a NON-answer can
produce, it is rare enough that the cost is nothing, and #500's high-water merge erases it from
the persisted record within a round or two.

**#767b is the half that nearly made this useless.** The screen record is built by an
`results.append({...})` that projects a FIXED key set, so the crumb was being dropped one line
after it was created. Checked rather than assumed — the same class of miss as #741's field
location and #752's blast radius, both of which I got wrong this session by not looking.
"""
import inspect

import pytest

from env_generator.llm_generator.multi_agent.runtime import visual_fidelity as vf


# --- every way to reach 0.00 keeps its reply ------------------------------------------------------

@pytest.mark.parametrize("payload,why", [
    ('{"deviations": ["x"]}', "empty verdict (#766)"),
    ('{"similarity": 0.0, "summary": "nothing matches"}', "an explicit zero"),
    ('{"dimensions": {"layout": {"score": 0.0}}}', "dimensions averaging to zero"),
    ("no json here at all", "no JSON"),
    ('{"similarity": 0.0, ', "unparseable"),
])
def test_a_zero_keeps_the_raw_reply(payload, why):
    v = vf._parse_verdict(payload)
    assert v["similarity"] == 0.0, why
    assert v.get("raw_judge_reply"), why


@pytest.mark.parametrize("payload", [
    '{"similarity": 0.72}',
    '{"similarity": 1.0}',
    '{"dimensions": {"layout": {"score": 0.5}}}',
])
def test_a_non_zero_carries_nothing_extra(payload):
    """No bloat: this is a diagnostic crumb for the one value that can be manufactured."""
    assert vf._parse_verdict(payload).get("raw_judge_reply") is None


def test_the_reply_is_truncated():
    v = vf._parse_verdict('{"similarity": 0.0, "summary": "' + "x" * 5000 + '"}')
    assert len(v["raw_judge_reply"]) <= 400


def test_the_explicit_zero_is_still_not_a_judge_error():
    """#766 must not have been widened by #767 — an honest zero stays honest."""
    v = vf._parse_verdict('{"similarity": 0.0}')
    assert "judge_error" not in v
    assert v.get("raw_judge_reply")


# --- #767b: it survives the projection ---------------------------------------------------------------

def test_the_screen_record_carries_it():
    src = inspect.getsource(vf.run_visual_fidelity)
    assert '"raw_judge_reply": verdict["raw_judge_reply"]' in src


def test_it_is_absent_when_there_is_nothing_to_carry():
    src = inspect.getsource(vf.run_visual_fidelity)
    assert 'if verdict.get("raw_judge_reply") else {}' in src


def test_the_projection_is_still_a_fixed_key_set():
    """The bug this half fixes is that the append PROJECTS. If someone later replaces it with
    `**verdict`, this test should fail loudly rather than silently changing what is persisted."""
    src = inspect.getsource(vf.run_visual_fidelity)
    i = src.index('results.append({"name": screen["name"]')
    blk = src[i:src.index('"summary": verdict.get("summary", "")})', i)]
    assert "**verdict" not in blk


# --- provenance ------------------------------------------------------------------------------------

def _prov() -> str:
    src = inspect.getsource(vf._parse_verdict)
    i = src.index("#767: KEEP THE RAW REPLY FOR A ZERO")
    return " ".join(l.strip().lstrip("#").strip()
                    for l in src[i:src.index("def _stamp767", i)].split("\n"))


def test_it_records_that_the_pngs_settled_it():
    p = _prov()
    assert "I opened the PNGs" in p
    assert "complete Netflix clone" in p


def test_it_records_why_only_a_zero():
    p = _prov()
    assert "the only value that can be" in p and "produced by a NON-answer" in p


def test_767b_records_that_it_nearly_shipped_useless():
    src = " ".join(inspect.getsource(vf.run_visual_fidelity).replace("#", " ").split())
    assert "the fix would have shipped and recorded nothing" in src


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))


def test_767b_was_not_enough_the_verdict_projection_drops_it_too():
    """#768b. The append into `results` was only the FIRST projection. `_persist_verdict`
    projects AGAIN on its way to verdict.json, so #767's crumb still reached nothing until that
    one carried it as well. Two fixed-key projections on one path, and the second was found only
    because a #768 test asserted the gating average and it disagreed with the live one."""
    import json
    src = inspect.getsource(vf._persist_verdict)
    assert '"raw_judge_reply": r["raw_judge_reply"]' in src
    assert '"capture_missing": r.get("capture_missing")' in src


def test_the_crumb_actually_reaches_disk(tmp_path):
    """End to end, because two projections in a row is exactly how it silently did not."""
    import json
    vf._persist_verdict(tmp_path, passed=False, min_similarity=0.65, summary="t", coverage=None,
                        results=[{"name": "a", "route": "/a", "similarity": 0.0, "passed": False,
                                  "advisory": False, "blank": False, "capture_missing": False,
                                  "raw_judge_reply": "{}", "deviations": [], "dimensions": {}}])
    v = json.loads((tmp_path / "design" / "visual_gate" / "verdict.json").read_text())
    assert v["screens"][0]["raw_judge_reply"] == "{}"
