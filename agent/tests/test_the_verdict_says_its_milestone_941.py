r"""#941: verdict.json spans every milestone of a run and never said which one.

`_persist_verdict` merges best-of-captures across the whole run (#500) and nothing resets it at a
milestone boundary — no unlink, no rmtree, no reset anywhere on that path. On a compound app the
recorded fidelity for a page can therefore have been earned by a version a later milestone
replaced, and the document could not say so: the string "milestone" appears **zero times** in
r154's verdict, which spans M1 and M2.

`rounds.jsonl` is the worse half: it is the run's only append-only record, it spans every
milestone, and r154's twelve rounds carry no way to tell M1's from M2's.

The label is built from what the plan actually carries — `index`, `name`, `id`, verified against
r154's `milestones.json` (`{'id': 'ms_d3d6595a', 'index': '2', 'name':
'M2-category-pages-search-player', 'status': 'active'}`) rather than guessed.
"""
import json
from pathlib import Path

import pytest

from env_generator.llm_generator.multi_agent.runtime import visual_fidelity as vf


def _persist(tmp, results, label=None):
    vf._persist_verdict(tmp, passed=False, min_similarity=0.65, summary="s",
                        coverage={}, results=results, milestone_label=label)
    v = json.loads((Path(tmp) / "design" / "visual_gate" / "verdict.json").read_text())
    rows = [json.loads(l) for l in
            (Path(tmp) / "design" / "visual_gate" / "rounds.jsonl").read_text().splitlines()
            if l.strip()]
    return v, rows


def _res(name, sim):
    return {"name": name, "route": "/x", "similarity": sim, "dimensions": {},
            "deviations": [], "fixes": [], "summary": ""}


def test_the_verdict_carries_the_label(tmp_path):
    v, _ = _persist(tmp_path, [_res("a", 0.5)], "2 M2-category-pages-search-player ms_d3d6595a")
    assert v["milestone"] == "2 M2-category-pages-search-player ms_d3d6595a"


def test_every_round_carries_it(tmp_path):
    """★ The half that matters more — the append-only file is what survives."""
    _persist(tmp_path, [_res("a", 0.5)], "1 M1-auth ms_363a057b")
    _, rows = _persist(tmp_path, [_res("a", 0.6)], "2 M2-search ms_d3d6595a")
    assert [r["milestone"] for r in rows] == ["1 M1-auth ms_363a057b", "2 M2-search ms_d3d6595a"]


def test_a_single_milestone_run_is_unchanged(tmp_path):
    """No label → no key. A single-milestone run's artifacts stay byte-identical."""
    v, rows = _persist(tmp_path, [_res("a", 0.5)])
    assert "milestone" not in v and "milestone" not in rows[-1]


def test_the_label_does_not_disturb_the_merge(tmp_path):
    _persist(tmp_path, [_res("a", 0.8)], "1 M1 x")
    v, _ = _persist(tmp_path, [_res("a", 0.2)], "2 M2 y")
    assert v["screens"][0]["similarity"] == 0.8         # #500 still latches
    assert v["screens"][0]["similarity_live"] == 0.2    # #928 still annotates
    assert v["milestone"] == "2 M2 y"


def test_the_call_site_builds_it_from_real_plan_keys():
    """★ Fields verified against r154's milestones.json, not invented: id / index / name."""
    import inspect
    src = inspect.getsource(vf)
    i = src.index("_mlabel941")
    block = src[i:src.index("milestone_label=_mlabel941", i)]
    for k in ('"index"', '"name"', '"id"'):
        assert k in block, k
    assert "_current_milestone" in block


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
