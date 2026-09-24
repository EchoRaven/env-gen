r"""#1202ao: a corrupt .user_gates.json used to delete every user-authored gate, silently.

Same shape as #1202an, on a file that matters more. `merge_user_gates` reads the store, sets
`existing = []` on ANY exception, computes `kept` from it, and writes `kept + added` — so a
read failure persists only this compile's gates and every user-authored one is gone.

`.user_gates.json` is what `deliver_project_call` evaluates. Losing it does not fail the run:
it makes the run EASIER, because the bar it has to clear quietly drops to whatever the compile
just generated. That is the worst direction for a silent loss.

The sweep that found it followed #1202an's pattern — read, set empty on failure, write back —
across llm_generator/. Seven functions matched; this is the one where the empty write destroys
something the user authored. `pin_frontend_build_tooling` writes fixed content and never merges,
the counters (#939/#946) lose only counts, and #1197's projection memo loses only provenance.
"""

import json
import logging
import sys
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS_DIR.parent / "env_generator" / "llm_generator"))

from multi_agent.runtime.reference_materials import merge_user_gates  # noqa: E402


_USER_GATE = {"name": "user_must_have_search", "source": "user", "check": "x"}
_COMPILED = {"name": "spec_gate_1", "source": "reference_spec", "check": "y"}


def test_a_healthy_file_keeps_the_user_gates(tmp_path):
    p = tmp_path / ".user_gates.json"
    p.write_text(json.dumps([_USER_GATE]), encoding="utf-8")
    merge_user_gates(tmp_path, [_COMPILED])
    names = {g["name"] for g in json.loads(p.read_text(encoding="utf-8"))}
    assert "user_must_have_search" in names and "spec_gate_1" in names


def test_a_corrupt_file_is_preserved_before_the_overwrite(tmp_path):
    p = tmp_path / ".user_gates.json"
    p.write_text('[{"name": "user_must_have_sea', encoding="utf-8")
    merge_user_gates(tmp_path, [_COMPILED])
    saved = [x for x in tmp_path.iterdir() if "corrupt" in x.name]
    assert len(saved) == 1
    assert saved[0].read_text(encoding="utf-8") == '[{"name": "user_must_have_sea'


def test_the_loss_says_that_the_bar_drops(caplog, tmp_path):
    """The consequence is the actionable part: fewer gates means an easier delivery."""
    p = tmp_path / ".user_gates.json"
    p.write_text("not json at all", encoding="utf-8")
    with caplog.at_level(logging.ERROR):
        merge_user_gates(tmp_path, [_COMPILED])
    assert "#1202ao" in caplog.text
    assert "LOWERS the bar" in caplog.text


def test_an_absent_file_is_quiet(caplog, tmp_path):
    """No file is legitimately empty — the first compile of every run hits this."""
    with caplog.at_level(logging.ERROR):
        merge_user_gates(tmp_path, [_COMPILED])
    assert "#1202ao" not in caplog.text
    assert not [x for x in tmp_path.iterdir() if "corrupt" in x.name]


def test_a_non_list_file_is_not_treated_as_damage(caplog, tmp_path):
    """`{}` parses fine and is simply the wrong shape — no bytes are at risk."""
    p = tmp_path / ".user_gates.json"
    p.write_text("{}", encoding="utf-8")
    with caplog.at_level(logging.ERROR):
        merge_user_gates(tmp_path, [_COMPILED])
    assert "#1202ao" not in caplog.text


def test_the_compile_still_lands_its_gates(tmp_path):
    """Refusing the write would drop this compile's gates instead and leave the file
    unreadable forever — #1202an's reasoning, applied here too."""
    p = tmp_path / ".user_gates.json"
    p.write_text("[broken", encoding="utf-8")
    merge_user_gates(tmp_path, [_COMPILED])
    assert json.loads(p.read_text(encoding="utf-8"))[0]["name"] == "spec_gate_1"
