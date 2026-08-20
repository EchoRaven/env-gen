r"""#1021: apply_patch implemented two thirds of the format the models are trained on.

`_parse_patch` handled `*** Add File:` and `*** Update File:` and nothing else, so every
`*** Delete File:` raised. It failed in TWO distinct ways, which is why the log carries two
error strings for one cause:

    *** Delete File: x            at top level      -> "unknown patch section: ..."
    *** Update File: a            after an update   -> "invalid patch line: *** Delete File: ..."
    ...
    *** Delete File: b                               (the update loop did not treat it
                                                       as a section boundary, so the line
                                                       fell through to the body validator)

Measured over the run logs r160-r171: **37 rejections across 11 of the 12 runs** (2-6 each;
only r161 had none). This is not a rare malformed-patch case, it is the lane's normal way of
removing a file.

r171 is the worked example, and it is the api-collision blocker the handoff traces:

    11:31:15  framework scaffolds baseline services/api.js   (2123 B template, no NetflixAPI;
                                                               no .jsx sibling yet, so #638's
                                                               shim correctly returns None)
    11:36:23  LANE writes services/api.js    (2822 chars)
    11:41:44  LANE writes services/api.jsx   (2806 chars)     <- collision, 10m29s later
    11:54:03  lane tries to DELETE api.jsx  -> refused
    12:01:56  again  -> refused
    12:04:21  again  -> refused
    12:12:30  again  -> refused
    12:22:38  again  -> refused
    12:23:20  again  -> refused
    12:13-12:18  lane gives up and hand-builds a workaround shim
    12:39:44  the "window.NetflixAPI is undefined" errors finally stop  (~46 minutes)

The lane had the right fix at 11:54 and the tool would not let it happen. A `delete_file`
tool is registered for every lane, but r171 invoked it **zero** times — the model reaches for
the patch format. So this accepts the format rather than trying to teach it away.

**It grants no new authority.** The applier copies `delete_file`'s policy verbatim (protected
paths refused, trash rather than unlink), and the two places that already treat a patch as a
mutation are updated with it: the write-permission gate (or a patch could delete a
framework-owned file the same lane may not write) and the auto-stage hook (or the deletion is
left out of the commit and the file returns).
"""
import inspect
from pathlib import Path

import pytest

from env_generator.llm_generator.tools.canonical_file_tools.shared import (
    _parse_patch,
)


def _patch(*body):
    return "\n".join(("*** Begin Patch",) + body + ("*** End Patch",))


# --- the parser -------------------------------------------------------------------------------

def test_a_delete_section_parses():
    ops = _parse_patch(_patch("*** Delete File: app/frontend/src/services/api.jsx"))
    assert [(o.op_type, o.path) for o in ops] == [
        ("delete", "app/frontend/src/services/api.jsx")]


def test_the_top_level_variant_no_longer_raises():
    """The 'unknown patch section' half of the failure."""
    ops = _parse_patch(_patch("*** Delete File: a.js"))
    assert ops and ops[0].op_type == "delete"


def test_a_delete_after_an_update_no_longer_raises():
    """The 'invalid patch line' half — the update loop must treat it as a boundary.

    This is the exact shape r171 sent at 11:54:03 and 12:04:21.
    """
    ops = _parse_patch(_patch(
        "*** Update File: src/App.jsx",
        "@@",
        " import React from 'react';",
        "-import api from './services/api.jsx';",
        "+import api from './services/api.js';",
        "*** Delete File: src/services/api.jsx",
    ))
    assert [(o.op_type, o.path) for o in ops] == [
        ("update", "src/App.jsx"), ("delete", "src/services/api.jsx")]


def test_several_deletes_in_one_patch():
    ops = _parse_patch(_patch(
        "*** Delete File: a.js", "*** Delete File: b.js", "*** Delete File: c.js"))
    assert [o.path for o in ops] == ["a.js", "b.js", "c.js"]


def test_a_delete_mixed_with_an_add():
    ops = _parse_patch(_patch(
        "*** Delete File: old.js",
        "*** Add File: new.js",
        "+export const x = 1;",
    ))
    assert [(o.op_type, o.path) for o in ops] == [("delete", "old.js"), ("add", "new.js")]


def test_a_delete_carrying_the_removed_lines_is_tolerated():
    """Models sometimes append the file's content to a delete. The intent is unambiguous."""
    ops = _parse_patch(_patch(
        "*** Delete File: a.js",
        "-export function gone() {}",
        "-",
    ))
    assert [(o.op_type, o.path) for o in ops] == [("delete", "a.js")]


def test_a_delete_carrying_GARBAGE_still_raises():
    """Tolerating a body must not become 'swallow anything' — that hides real malformation."""
    with pytest.raises(ValueError):
        _parse_patch(_patch("*** Delete File: a.js", "this is not a patch line"))


def test_the_delete_op_carries_no_body():
    op = _parse_patch(_patch("*** Delete File: a.js"))[0]
    assert op.hunks == [] and op.add_lines == []


def test_an_unknown_section_STILL_raises():
    """Control: the fix must not have turned the parser permissive in general."""
    with pytest.raises(ValueError, match="unknown patch section"):
        _parse_patch(_patch("*** Rename File: a.js"))


# --- the planted control: these inputs must FAIL on the pre-fix parser ------------------------

_PRE_FIX_REJECTS = (
    _patch("*** Delete File: a.js"),
    _patch("*** Update File: b.js", "@@", "-x", "+y", "*** Delete File: a.js"),
)


def test_the_control_reproduces_the_original_failure():
    """Re-runs both inputs against a parser with the #1021 branch removed, and demands the
    two original errors. Without this the tests above would also pass on a parser that
    silently ignored the section (item 456's rule: after repairing a blind check, plant the
    defect and demand the finding)."""
    src = inspect.getsource(_parse_patch)
    assert "#1021" in src, "the fix's marker is gone — this control is measuring nothing"
    # strip the Delete-File branch and the boundary clause, restoring the pre-fix parser
    i = src.index("        # #1021:")
    j = src.index("        raise ValueError(f\"unknown patch section: {line}\")")
    pre_fix = (src[:i] + src[j:]).replace(
        '\n                        or current_line.startswith("*** Delete File: ")', "")
    assert '"*** Delete File: "' not in pre_fix, (
        "the pre-fix reconstruction still mentions the section — the control would be "
        "measuring the FIXED parser and could never go red")
    from env_generator.llm_generator.tools.canonical_file_tools import shared as _sh
    ns = dict(vars(_sh))
    exec(compile(pre_fix, "<pre_fix_parse_patch>", "exec"), ns)
    old = ns["_parse_patch"]

    errors = []
    for text in _PRE_FIX_REJECTS:
        with pytest.raises(ValueError) as exc:
            old(text)
        errors.append(str(exc.value))
    assert any("unknown patch section" in e for e in errors), errors
    assert any("invalid patch line" in e for e in errors), errors
    # and the fixed parser accepts both
    for text in _PRE_FIX_REJECTS:
        assert any(o.op_type == "delete" for o in _parse_patch(text))


# --- the applier ------------------------------------------------------------------------------

def _tool(tmp_path):
    from env_generator.llm_generator.tools.canonical_file_tools.patch import ApplyPatchTool
    from workspace import Workspace
    return ApplyPatchTool(workspace=Workspace(str(tmp_path)))


def test_the_file_is_actually_gone(tmp_path):
    (tmp_path / "api.jsx").write_text("export const dup = 1;\n", encoding="utf-8")
    res = _tool(tmp_path).execute(_patch("*** Delete File: api.jsx"))
    assert res.success, res.error_message
    assert not (tmp_path / "api.jsx").exists()


def test_the_delete_is_recoverable_from_trash(tmp_path):
    """Trash, not unlink — a wrong delete by an agent must not be unrecoverable."""
    (tmp_path / "api.jsx").write_text("export const dup = 1;\n", encoding="utf-8")
    _tool(tmp_path).execute(_patch("*** Delete File: api.jsx"))
    trashed = list((tmp_path / ".openenv_trash").glob("api.jsx*.deleted"))
    assert trashed and trashed[0].read_text(encoding="utf-8") == "export const dup = 1;\n"


def test_a_protected_path_is_refused(tmp_path):
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
    res = _tool(tmp_path).execute(_patch("*** Delete File: .git/HEAD"))
    assert not res.success and "protected" in (res.error_message or "")
    assert (tmp_path / ".git" / "HEAD").exists()


def test_a_missing_file_is_an_error_not_a_silent_success(tmp_path):
    res = _tool(tmp_path).execute(_patch("*** Delete File: nope.js"))
    assert not res.success


def test_a_directory_is_refused(tmp_path):
    (tmp_path / "services").mkdir()
    res = _tool(tmp_path).execute(_patch("*** Delete File: services"))
    assert not res.success and (tmp_path / "services").is_dir()


def test_the_r171_patch_now_works_end_to_end(tmp_path):
    """The whole point: App.jsx repointed and the duplicate module removed, in one patch.

    The update half needs a prior `read` (the stale-write guard), exactly as it does for an
    agent; the delete half deliberately does NOT, matching `delete_file`.
    """
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "App.jsx").write_text(
        "import api from './services/api.jsx';\n", encoding="utf-8")
    (tmp_path / "src" / "services").mkdir()
    (tmp_path / "src" / "services" / "api.js").write_text(
        "export const NetflixAPI = {};\nwindow.NetflixAPI = NetflixAPI;\n", encoding="utf-8")
    (tmp_path / "src" / "services" / "api.jsx").write_text(
        "export function getTitles() {}\n", encoding="utf-8")

    from env_generator.llm_generator.tools.canonical_file_tools.read import ReadTool
    from workspace import Workspace
    ws = Workspace(str(tmp_path))
    ReadTool(workspace=ws).execute("src/App.jsx")

    res = _tool(tmp_path).execute(_patch(
        "*** Update File: src/App.jsx",
        "@@",
        "-import api from './services/api.jsx';",
        "+import api from './services/api.js';",
        "*** Delete File: src/services/api.jsx",
    ))
    assert res.success, res.error_message
    assert not (tmp_path / "src" / "services" / "api.jsx").exists()
    assert "api.js'" in (tmp_path / "src" / "App.jsx").read_text(encoding="utf-8")
    assert (tmp_path / "src" / "services" / "api.js").exists(), "the real module must survive"


def test_a_failed_delete_stops_the_patch(tmp_path):
    """Operations are applied in order and the first failure returns — a later delete must not
    run after an earlier hunk failed to match."""
    (tmp_path / "a.js").write_text("real content\n", encoding="utf-8")
    (tmp_path / "b.js").write_text("x\n", encoding="utf-8")
    res = _tool(tmp_path).execute(_patch(
        "*** Update File: b.js", "@@", "-nonexistent line", "+y",
        "*** Delete File: a.js",
    ))
    assert not res.success
    assert (tmp_path / "a.js").exists(), "a delete ran after an earlier operation failed"


# --- the two gates that already treat a patch as a mutation -----------------------------------

def test_the_write_guard_sees_a_patch_delete():
    """Scoped to the function that enforces ownership: if `*** Delete File:` is not collected
    as a write target, a lane can delete a framework-owned file it may not write."""
    from env_generator.llm_generator.multi_agent.agents.runtime.tooling import AgentTooling
    src = inspect.getsource(AgentTooling._enforce_write_permissions)
    assert "*** Delete File: " in src, (
        "the write-permission gate does not collect patch deletes as write targets")


def test_the_auto_stage_hook_stages_a_patch_delete_AS_a_deletion():
    """`action="delete"` matters: stage_deletion uses `git add -A`, which records a removal.
    Staged as "add" the deletion is dropped from the commit and the file comes back."""
    from env_generator.llm_generator.multi_agent.agents.runtime.step_pipeline.tooling import (
        AgentStepToolingMixin as _M)
    src = inspect.getsource(_M._process_tool_calls)
    i = src.index('elif tool_name == "apply_patch":')
    j = src.index('elif tool_name == "delete_file":', i)
    block = src[i:j]
    assert '*** Delete File: ' in block, "patch deletes are never staged"
    assert 'patch_deleted' in block and 'action="delete"' in block, (
        "a patch delete must stage as a deletion, not as an add")


def test_the_premise_still_holds():
    """If delete_file ever stops being registered for lanes, the 'grants no new authority'
    argument in the docstring stops being true and this fix needs re-justifying."""
    from env_generator.llm_generator.tools.canonical_file_tools import DeleteFileTool
    assert DeleteFileTool.NAME == "delete_file"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
