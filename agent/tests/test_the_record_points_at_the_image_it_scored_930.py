r"""#930: a merged record's `screenshot` pointed at the LATEST image, not the one it scored.

#771 put the capture's path into the record so "look at the image" becomes a lookup instead of an
inference — its docstring says that omission cost a session its single most decisive step. The
path is stable (`visual_gate/<name>.png`) and every round overwrites the file, so the moment
#500's merge keeps an older record the lookup returns a different picture than the one scored.

r154, live: the `title_detail` record reads `similarity: 0.6` and its `screenshot` is the file
that scored 0.00 — twice, byte-identical between those two rounds. Opening it showed a complete
working detail page, which is the right read for the 0.00 capture and the wrong pairing for the
0.6 record.

Fix: copy the image aside when a record WINS the merge and point that record at the copy. Only
winners are archived, so the directory grows once per genuine improvement rather than once per
round; `screenshot_live` keeps the moving path.
"""
import json
import subprocess
from pathlib import Path

import pytest

from env_generator.llm_generator.multi_agent.runtime import visual_fidelity as vf


@pytest.fixture
def repo(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    for k, v in (("user.email", "t@t"), ("user.name", "t")):
        subprocess.run(["git", "-C", str(tmp_path), "config", k, v], check=True)
    (tmp_path / "f").write_text("x")
    subprocess.run(["git", "-C", str(tmp_path), "add", "f"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "commit", "-qm", "c"], check=True)
    (tmp_path / "design" / "visual_gate").mkdir(parents=True)
    return tmp_path


def _shot(repo, name, content):
    p = repo / "design" / "visual_gate" / f"{name}.png"
    p.write_bytes(content)
    return p


def _res(name, sim, shot):
    return {"name": name, "route": "/x", "similarity": sim, "passed": False,
            "screenshot": str(shot), "reference": "/ref.jpg",
            "dimensions": {}, "deviations": [], "fixes": [], "summary": ""}


def _persist(repo, results):
    vf._persist_verdict(repo, passed=False, min_similarity=0.65, summary="s",
                        coverage={}, results=results)
    return json.loads((repo / "design" / "visual_gate" / "verdict.json")
                      .read_text(encoding="utf-8"))


def _one(v, name="title_detail"):
    return {s["name"]: s for s in v["screens"]}[name]


# --------------------------------------------------------------------------- the point

def test_a_merged_record_still_shows_the_image_it_scored(repo):
    """★ THE ticket. Round 1 scores 0.6 on image A; round 2 overwrites the file with image B and
    scores 0.00. The kept 0.6 record must still resolve to A."""
    shot = _shot(repo, "title_detail", b"AAAA-round-one")
    _persist(repo, [_res("title_detail", 0.60, shot)])
    shot.write_bytes(b"BBBB-round-two")
    v = _persist(repo, [_res("title_detail", 0.00, shot)])
    s = _one(v)
    assert s["similarity"] == 0.60
    assert Path(s["screenshot"]).read_bytes() == b"AAAA-round-one", (
        "the record's own image must be the one that earned its score")


def test_the_moving_path_is_still_available(repo):
    shot = _shot(repo, "title_detail", b"AAAA")
    v = _persist(repo, [_res("title_detail", 0.60, shot)])
    s = _one(v)
    assert Path(s["screenshot"]).name.startswith("title_detail@")
    assert s["screenshot_live"] == str(shot)


def test_a_winner_is_archived_under_its_code_state(repo):
    shot = _shot(repo, "title_detail", b"AAAA")
    v = _persist(repo, [_res("title_detail", 0.60, shot)])
    head = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"],
                          capture_output=True, text=True).stdout.strip()
    assert Path(v["screens"][0]["screenshot"]).name == f"title_detail@{head[:8]}.png"


def test_a_new_high_water_re_archives(repo):
    """A later capture that WINS must archive its own image, not keep the old pointer.

    ★ The third round is what gives this test teeth: without it the assertion passes with the fix
    reverted too, because the moving path happens to hold the right bytes at that moment. Found by
    reverting and noticing this test stayed green."""
    shot = _shot(repo, "title_detail", b"AAAA")
    _persist(repo, [_res("title_detail", 0.30, shot)])
    shot.write_bytes(b"BBBB-better")
    v = _persist(repo, [_res("title_detail", 0.80, shot)])
    shot.write_bytes(b"CCCC-a-later-round-overwrites-the-file")
    assert Path(_one(v)["screenshot"]).read_bytes() == b"BBBB-better"


def test_the_archive_grows_once_per_improvement_not_per_round(repo):
    """Three rounds, one improvement: the losing rounds must not leave copies behind."""
    shot = _shot(repo, "title_detail", b"AAAA")
    _persist(repo, [_res("title_detail", 0.60, shot)])
    for payload, sim in ((b"BBBB", 0.10), (b"CCCC", 0.20), (b"DDDD", 0.05)):
        shot.write_bytes(payload)
        _persist(repo, [_res("title_detail", sim, shot)])
    assert len(list((repo / "design" / "visual_gate" / "captures").glob("*.png"))) == 1


def test_re_archiving_the_same_bytes_is_a_no_op(repo):
    shot = _shot(repo, "title_detail", b"AAAA")
    _persist(repo, [_res("title_detail", 0.60, shot)])
    arch = next((repo / "design" / "visual_gate" / "captures").glob("*.png"))
    before = arch.stat().st_mtime_ns
    _persist(repo, [_res("title_detail", 0.70, shot)])
    assert arch.stat().st_mtime_ns == before


# --------------------------------------------------------------------------- it never breaks

def test_a_record_without_a_screenshot_is_untouched(repo):
    r = _res("title_detail", 0.60, "")
    r.pop("screenshot")
    v = _persist(repo, [r])
    assert "screenshot" not in _one(v) or _one(v)["screenshot"] in (None, "")


def test_a_missing_file_is_untouched(repo):
    v = _persist(repo, [_res("title_detail", 0.60, repo / "nope.png")])
    assert _one(v)["screenshot"] == str(repo / "nope.png")
    assert "screenshot_live" not in _one(v)


def test_no_git_still_persists(tmp_path):
    """`_head_sha` is None outside a repo — #930 must name the archive anyway, not crash."""
    (tmp_path / "design" / "visual_gate").mkdir(parents=True)
    shot = _shot(tmp_path, "title_detail", b"AAAA")
    v = _persist(tmp_path, [_res("title_detail", 0.60, shot)])
    assert Path(_one(v)["screenshot"]).name == "title_detail@nocommit.png"


def test_the_hoisted_head_sha_still_reaches_the_verdict(repo):
    """★ The seam: #621's `rev-parse` moved above the merge. `code_state` must be unchanged."""
    shot = _shot(repo, "title_detail", b"AAAA")
    v = _persist(repo, [_res("title_detail", 0.60, shot)])
    head = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"],
                          capture_output=True, text=True).stdout.strip()
    assert v["code_state"] == head


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
