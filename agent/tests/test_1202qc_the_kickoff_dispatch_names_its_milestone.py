"""#1202qc: the post-kickoff task_ready names the current milestone, not a hardcoded M1."""
from pathlib import Path
from types import SimpleNamespace

from env_generator.llm_generator.multi_agent.runtime import kickoff_driver as KD


def test_the_label_follows_the_current_milestone():
    assert KD._milestone_label_1202qc(SimpleNamespace(_current_milestone={"id": "M3"})) == "M3"
    assert KD._milestone_label_1202qc(
        SimpleNamespace(_current_milestone={}, _current_milestone_version="1.2.0")) == "v1.2.0"
    assert KD._milestone_label_1202qc(object()) == "milestone"


def test_the_dispatch_message_no_longer_hardcodes_m1():
    src = Path(KD.__file__).read_text(encoding="utf-8")
    assert "\"Kickoff finalized — the M1 contract" not in src
    assert "_milestone_label_1202qc(self._orch)" in src
