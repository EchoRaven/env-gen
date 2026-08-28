"""#1144: the write guard told the truth one turn too late.

Writing a framework-owned file is refused with a message that is already correct — it names
`custom_routes.py` / `src/pages/*.jsx` as the place to author. The cost is WHEN it arrives:
the caller has already read the file, composed a patch, and spent a turn before hearing it.

Measured over the eight netflix runs: **70 of 360** edit/apply_patch/write failures are this
denial, and `docker-compose.yml` alone is 23 of them — the same lane churn that then went
hunting for host ports by hand (34 probes to :49160, 32 to :58081 in r9, see #1134b).

Ownership is knowable the moment the file is read. This asks the ONE map the write guard and
the conflict resolver already share (`is_framework_owned`), so a second copy cannot drift
from it (#665).
"""
from __future__ import annotations

import pathlib
import tempfile

from env_generator.llm_generator.tools.canonical_file_tools.read import ReadTool
from env_generator.llm_generator.workspace import Workspace


class _FWWorkspace(Workspace):
    """A workspace whose ownership map claims main.py."""

    def is_framework_owned(self, p):
        return str(p).endswith("main.py")


class _RaisingWorkspace(Workspace):
    def is_framework_owned(self, p):
        raise RuntimeError("ownership map unavailable")


def _tmp():
    d = pathlib.Path(tempfile.mkdtemp())
    (d / "main.py").write_text("# projected\n", encoding="utf-8")
    (d / "custom_routes.py").write_text("# yours\n", encoding="utf-8")
    return d


class TestOwnershipArrivesWithTheContent:

    def test_a_framework_owned_file_is_flagged(self):
        d = _tmp()
        res = ReadTool(workspace=_FWWorkspace(str(d))).execute(file_path="main.py")
        assert res.success
        assert (res.data or {}).get("framework_owned") is True
        assert res.notices and "FRAMEWORK-OWNED" in res.notices[0]

    def test_the_notice_says_where_to_author_instead(self):
        d = _tmp()
        res = ReadTool(workspace=_FWWorkspace(str(d))).execute(file_path="main.py")
        note = res.notices[0]
        assert "custom_routes.py" in note
        assert "src/pages" in note

    def test_a_lane_owned_file_in_the_same_workspace_is_not_flagged(self):
        d = _tmp()
        res = ReadTool(workspace=_FWWorkspace(str(d))).execute(file_path="custom_routes.py")
        assert res.success
        assert (res.data or {}).get("framework_owned") is False
        assert not res.notices


class TestItNeverBlocksOrBreaks:
    """Reading a framework-owned file is legitimate and frequent — nothing may be refused."""

    def test_reading_is_still_allowed_and_returns_the_content(self):
        d = _tmp()
        res = ReadTool(workspace=_FWWorkspace(str(d))).execute(file_path="main.py")
        assert res.success
        assert "projected" in (res.data or {}).get("content", "")

    def test_a_workspace_without_the_map_is_silent(self):
        d = _tmp()
        res = ReadTool(workspace=Workspace(str(d))).execute(file_path="main.py")
        assert res.success
        assert not res.notices
        assert (res.data or {}).get("framework_owned") is False

    def test_an_ownership_map_that_raises_does_not_fail_the_read(self):
        d = _tmp()
        res = ReadTool(workspace=_RaisingWorkspace(str(d))).execute(file_path="main.py")
        assert res.success, res.error_message
        assert not res.notices


class TestItReusesTheSingleMap:

    def test_it_calls_is_framework_owned_rather_than_re_deriving(self):
        src = pathlib.Path(
            "env_generator/llm_generator/tools/canonical_file_tools/read.py"
        ).read_text(encoding="utf-8")
        assert "is_framework_owned" in src
        # no second ownership table in the read tool
        assert "FRAMEWORK_OWNED_PATHS" not in src
        assert src.count("def is_framework_owned") == 0
