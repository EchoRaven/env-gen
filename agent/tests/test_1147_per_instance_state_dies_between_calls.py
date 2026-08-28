"""#1147: per-instance tool state is empty on arrival, so #1145 and #613 never fired.

netflix-local-r10 proved it from the live logs, not from reasoning:

    get_skill called 177 times; the orchestrator fetched `release-readiness` 76 times and
    every one of those 76 responses had the SAME length — a byte-identical payload, so the
    fingerprint matched every time and the elision should have fired from call 3 onward.
    It fired ZERO times. So did read's #613 elision, in r9 AND r10.

The same code fires correctly when one instance is reused, which is how it was tested and why
it looked finished. Tool instances do not survive between calls in this framework, so any
optimisation built on `self.<state>` is dead on arrival — and #613 has been dead since it was
written.

`file_tools._file_read_state` is module-level and DOES work (its "File changed since last
read" guard fired 30 times in r9). That is the shape that survives, so the fingerprints move
there, keyed by the workspace's code_root so two lanes in different worktrees cannot elide
each other's FIRST delivery.
"""
from __future__ import annotations

import asyncio
import pathlib
import tempfile

from env_generator.llm_generator.tools.knowledge_tools import GetSkillTool, _SKILL_FP_1147
from env_generator.llm_generator.workspace import Workspace


def _skill_dir(name="demo", body="body " * 40):
    d = pathlib.Path(tempfile.mkdtemp())
    p = d / ".agents" / "skills" / name
    p.mkdir(parents=True)
    (p / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: d\n---\n\n{body}", encoding="utf-8")
    return d


def _fetch(ws, name="demo"):
    """A FRESH TOOL each call on the SAME workspace — exactly what the live run does.

    The workspace object is what an agent holds for its lifetime; the tool pool is rebuilt
    around it. Passing the same object is the production shape, and a different object is
    another lane (which #613's own test models).
    """
    tool = GetSkillTool(workspace=ws)
    return str(((asyncio.run(tool.execute(name=name)).data or {})
                .get("skill") or {}).get("instructions") or "")


def _elided(text):
    return "already delivered" in text


class TestItSurvivesFreshInstances:
    """The live shape: a new tool object per call."""

    def test_the_third_fetch_is_elided_even_with_new_instances(self):
        ws = Workspace(str(_skill_dir()))
        assert not _elided(_fetch(ws))
        assert not _elided(_fetch(ws))
        assert _elided(_fetch(ws)), "per-instance state would be empty here — the r10 bug"
        assert _elided(_fetch(ws))

    def test_the_full_text_is_delivered_the_first_two_times(self):
        ws = Workspace(str(_skill_dir()))
        first = _fetch(ws)
        assert "body" in first and len(first) > 100


class TestLanesDoNotElideEachOther:
    """#1145's class attribute would have let one lane silence another lane's first read."""

    def test_a_second_workspace_still_gets_the_full_text(self):
        wa, wb = Workspace(str(_skill_dir())), Workspace(str(_skill_dir()))
        for _ in range(3):
            _fetch(wa)
        assert _elided(_fetch(wa))
        assert not _elided(_fetch(wb)), "a different worktree must start from zero"


class TestTheCondenseResetStillWorks:
    """#1145b: after a condense the caller may no longer hold it."""

    def test_forgetting_restores_full_delivery_for_that_workspace_only(self):
        wa, wb = Workspace(str(_skill_dir())), Workspace(str(_skill_dir()))
        for _ in range(3):
            _fetch(wa)
            _fetch(wb)
        assert _elided(_fetch(wa)) and _elided(_fetch(wb))

        GetSkillTool(workspace=wa).forget_deliveries_1145()

        assert not _elided(_fetch(wa)), "the condensed lane must get its content back"
        assert _elided(_fetch(wb)), "an untouched lane keeps its counter"


class TestTheStateIsWhereItSurvives:

    def test_the_map_is_module_level(self):
        assert isinstance(_SKILL_FP_1147, dict)

    def test_no_instance_attribute_holds_the_fingerprints(self):
        import inspect
        src = inspect.getsource(GetSkillTool)
        assert "self._skill_fingerprints_1145" not in src, \
            "instance state is empty on arrival in this framework"
