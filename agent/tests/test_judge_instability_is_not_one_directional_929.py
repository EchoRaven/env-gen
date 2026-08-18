r"""#929: #893 could only see the judge getting KINDER, never the judge collapsing a screen.

#893 records "the same code_state got a different verdict" — judge noise, so a reader can weigh
`missing` accordingly. It walked `merged`, the post-#500 list, and compared each entry to the
prior verdict. When the live capture scored LOWER, the merge has already put the prior record back
in `merged`, so `_s` IS `_pn`: the delta is 0 and the missing-sets are equal, by construction.

Executed control before the fix, same tree both ways, one screen:

    0.60 -> 0.00    judge_unstable_893: null        silent
    0.00 -> 0.60    judge_unstable_893: delta 0.6   reported

The blind direction is the one that matters. r154 is the live case: `title_detail` scored 0.60 and
then 0.00 twice, on a capture that is byte-identical between those two rounds and shows a
complete, working detail page — hero art, Play / + / like, 2026 · TV-14 · HD, synopsis, genre tag,
and an Episodes section with a season selector and an episode row. #711 reported the aggregate
divergence; nothing named the screen or said the tree had not changed under it.

Fix: compare THIS capture against the prior — `screens`, not `merged`. Recorded, not acted on,
exactly as #893 was.
"""
import json
import subprocess
from pathlib import Path

import pytest

from env_generator.llm_generator.multi_agent.runtime import visual_fidelity as vf


@pytest.fixture
def repo(tmp_path):
    """#893 only looks when the tree is unchanged, so the fixture needs a real HEAD."""
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    for k, v in (("user.email", "t@t"), ("user.name", "t")):
        subprocess.run(["git", "-C", str(tmp_path), "config", k, v], check=True)
    (tmp_path / "f").write_text("x")
    subprocess.run(["git", "-C", str(tmp_path), "add", "f"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "commit", "-qm", "c"], check=True)
    return tmp_path


def _res(name, sim, missing=()):
    return {"name": name, "route": "/x", "similarity": sim, "passed": sim >= 0.65,
            "dimensions": {"layout": {"score": sim, "missing": list(missing)}},
            "deviations": [], "fixes": [], "summary": ""}


def _persist(repo, results):
    vf._persist_verdict(repo, passed=False, min_similarity=0.65, summary="s",
                        coverage={}, results=results)
    return json.loads((Path(repo) / "design" / "visual_gate" / "verdict.json")
                      .read_text(encoding="utf-8"))


def _unstable(v):
    return {u["screen"]: u for u in (v.get("judge_unstable_893") or [])}


# --------------------------------------------------------------------------- both directions

def test_a_collapse_on_an_unchanged_tree_is_reported(repo):
    """★ The blind direction — r154's title_detail, 0.60 then 0.00 on the same code_state."""
    _persist(repo, [_res("title_detail", 0.60, ["hero"])])
    v = _persist(repo, [_res("title_detail", 0.00, ["hero", "nav", "rows"])])
    u = _unstable(v)
    assert "title_detail" in u, v.get("judge_unstable_893")
    assert u["title_detail"]["score_delta"] == pytest.approx(0.60)
    assert u["title_detail"]["appeared"] == ["nav", "rows"]


def test_an_improvement_is_still_reported(repo):
    """The direction that already worked must keep working."""
    _persist(repo, [_res("t", 0.00, ["hero", "nav", "rows"])])
    v = _persist(repo, [_res("t", 0.60, ["hero"])])
    u = _unstable(v)
    assert "t" in u and u["t"]["vanished"] == ["nav", "rows"]


def test_a_stable_screen_is_not_reported(repo):
    _persist(repo, [_res("t", 0.60, ["hero"])])
    v = _persist(repo, [_res("t", 0.60, ["hero"])])
    assert not v.get("judge_unstable_893")


def test_a_small_score_move_with_the_same_missing_set_is_not_reported(repo):
    """#893's own threshold: under 0.10 with an identical missing set is not instability."""
    _persist(repo, [_res("t", 0.60, ["hero"])])
    v = _persist(repo, [_res("t", 0.55, ["hero"])])
    assert not v.get("judge_unstable_893")


def test_a_changed_tree_is_never_instability(repo):
    """The premise of the ticket: a different code_state explains a different verdict."""
    _persist(repo, [_res("t", 0.60, ["hero"])])
    (Path(repo) / "f").write_text("y")
    subprocess.run(["git", "-C", str(repo), "commit", "-qam", "c2"], check=True)
    v = _persist(repo, [_res("t", 0.00, ["hero", "nav"])])
    assert not v.get("judge_unstable_893")


def test_the_collapse_still_keeps_the_high_water_score(repo):
    """#929 changes what is REPORTED, not what is recorded — #500's merge is untouched."""
    _persist(repo, [_res("t", 0.60, ["hero"])])
    v = _persist(repo, [_res("t", 0.00, ["hero", "nav"])])
    s = v["screens"][0]
    assert s["similarity"] == 0.60 and s["similarity_live"] == 0.00


def test_a_screen_absent_from_this_capture_is_not_instability(repo):
    """Not photographed is not a different verdict (#928's carry-over, one detector over)."""
    _persist(repo, [_res("a", 0.60, ["hero"]), _res("b", 0.60, ["hero"])])
    v = _persist(repo, [_res("a", 0.60, ["hero"])])
    assert "b" not in _unstable(v)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
