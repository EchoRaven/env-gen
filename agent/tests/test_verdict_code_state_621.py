r"""#621: record which code state a score belongs to.

#618 showed the persisted `blocking_average` can beat the live one in **24 of 39** runs (up to
+0.44), and that delivery almost never comes from a PASS — only **1 of 40** verdicts ever passed;
the rest release through the bounded escape at whatever the last round happened to leave behind.
Shipping the run's own BEST state instead is the obvious repair, and it was blocked by one
missing thing: a join key.

Both halves already exist. The commits are recorded (codehub has 36 in r142, with sha, branch and
author) and the scores are recorded — nothing linked a capture to the tree it scored.

Stamping HEAD costs a `rev-parse` and makes that selection possible later. It is the #611 move:
record what a future question will need. It changes no decision taken here, and a project that is
not a git repo simply gets `None`.
"""
import json
import os
import subprocess

import pytest

from env_generator.llm_generator.multi_agent.runtime import visual_fidelity as vf

_ENV = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}


def _persist(root, sim=0.5):
    (root / "design" / "visual_gate").mkdir(parents=True, exist_ok=True)
    vf._persist_verdict(str(root), passed=False, min_similarity=0.65, summary="s",
                        coverage={}, results=[{"name": "login", "route": "/login",
                                               "similarity": sim}])
    return json.loads((root / "design" / "visual_gate" / "verdict.json")
                      .read_text(encoding="utf-8"))


def _repo(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "commit", "-q", "--allow-empty", "-m", "x"],
                   env=_ENV, check=True)
    return tmp_path


def test_the_head_sha_is_recorded(tmp_path):
    v = _persist(_repo(tmp_path))
    head = subprocess.run(["git", "-C", str(tmp_path), "rev-parse", "HEAD"],
                          capture_output=True, text=True).stdout.strip()
    assert v["code_state"] == head and len(head) == 40


def test_it_pairs_with_the_live_score_not_the_merged_one(tmp_path):
    """The sha describes THIS capture, which is what `blocking_average_live` measures."""
    v = _persist(_repo(tmp_path), sim=0.42)
    assert v["blocking_average_live"] == pytest.approx(0.42)
    assert v["code_state"]


def test_a_new_commit_gives_a_new_code_state(tmp_path):
    root = _repo(tmp_path)
    first = _persist(root)["code_state"]
    subprocess.run(["git", "-C", str(root), "commit", "-q", "--allow-empty", "-m", "y"],
                   env=_ENV, check=True)
    assert _persist(root)["code_state"] != first


# --- it must never break the gate ------------------------------------------------------------

def test_a_non_repo_yields_None_rather_than_raising(tmp_path):
    assert _persist(tmp_path)["code_state"] is None


def test_the_verdict_is_still_written_when_git_is_unavailable(tmp_path):
    v = _persist(tmp_path)
    assert v["blocking_average_live"] is not None and "screens" in v


def _block():
    """The code #621 adds: the `_head_sha = None` guard, the `rev-parse`, and the `except` that
    restores None.

    Anchored on the rev-parse itself. It used to run from the first "#621" mention to
    `_verdict = {`, which assumed #621's code was the last thing before the verdict dict — #930
    hoisted the lookup above the merge (the archive is named after the sha) and the old span then
    covered the whole merge, so `test_it_changes_no_decision` failed on `_merged_passed`, code
    #621 does not touch. Anchoring on the call keeps the assertions pointed at #621's own lines
    wherever they sit."""
    import inspect
    src = inspect.getsource(vf._persist_verdict)
    i = src.index('"rev-parse"')
    start = src.rindex("_head_sha = None", 0, i)
    end = src.index("_head_sha = None", i) + len("_head_sha = None")
    return src[start:end]


def test_the_block_locator_finds_the_lookup_and_nothing_else():
    """★ The locator is the test's instrument; a wrong span passed a false verdict once already."""
    b = _block()
    assert '"rev-parse"' in b and b.count("_head_sha = None") == 2
    assert "merged" not in b and "similarity" not in b, b


def test_the_lookup_is_bounded(tmp_path):
    """A hung git must not stall the gate."""
    assert "timeout=10" in _block()


def test_it_changes_no_decision(tmp_path):
    b = _block()
    assert "_merged_passed" not in b and "passed =" not in b


def test_the_reason_it_exists_is_recorded():
    import inspect
    flat = " ".join(inspect.getsource(vf._persist_verdict).replace("#", " ").split())
    assert "24 of 39 runs" in flat and "1 of 40 verdicts ever passed" in flat
    assert "join key" in flat


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
