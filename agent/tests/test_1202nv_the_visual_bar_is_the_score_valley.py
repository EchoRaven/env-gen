"""#1202nv: the per-screen visual bar is 0.55, defined once.

Measured on 3,681 per-screen judgments: bimodal with the valley at 0.50-0.55. The captures behind
the bands: ~0.1-0.2 wrong page; 0.40-0.54 right layout with placeholder/missing primary media;
0.55-0.65 the right page with real content and polish gaps (r125 explore_grid 0.58,
messages_dm_empty 0.60, r126 fyp_feed_comments_panel 0.64) — 525 judgments (14%) that failed at
0.65. Judge noise between consecutive rounds: p75 0.06, p90 0.12.

0.65 was written in three places (the gate, the browser test-user's mismatch list, the snapshot
quality summary); they read one definition now.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime import visual_fidelity as VF  # noqa: E402

RUNTIME = LLM / "multi_agent" / "runtime"


def test_the_default_bar_is_the_valley(monkeypatch):
    monkeypatch.delenv("ENVGEN_VISUAL_MIN", raising=False)
    assert VF.VISUAL_MIN_DEFAULT_1202NV == 0.55
    assert VF.visual_min_similarity_1202nv() == 0.55


def test_the_env_override_still_wins(monkeypatch):
    monkeypatch.setenv("ENVGEN_VISUAL_MIN", "0.7")
    assert VF.visual_min_similarity_1202nv() == 0.7
    monkeypatch.setenv("ENVGEN_VISUAL_MIN", "junk")
    assert VF.visual_min_similarity_1202nv() == 0.55


def test_no_site_keeps_its_own_copy_of_the_bar():
    for name in ("visual_fidelity.py", "test_user_runner.py"):
        src = (RUNTIME / name).read_text(encoding="utf-8")
        assert 'os.environ.get("ENVGEN_VISUAL_MIN", "0.65")' not in src, name
    snap = (RUNTIME / "run_snapshot.py").read_text(encoding="utf-8")
    assert "visual_min_similarity_1202nv" in snap
