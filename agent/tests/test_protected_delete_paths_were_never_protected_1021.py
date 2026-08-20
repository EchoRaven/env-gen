r"""#1021b: `_is_protected_delete_path` never protected a single path it names.

Found by #1021's protected-path test, which deleted `.git/HEAD` through `apply_patch` and
PASSED. The guard is shared with the `delete_file` tool, so this was live for both.

    rel = _workspace_rel(...).replace("\\", "/").lstrip("./")
    protected_prefixes = (".git/", ".cursor/", ".openenv_trash/")
    return rel == ".git" or rel.startswith(protected_prefixes)

`str.lstrip` takes a SET OF CHARACTERS, not a prefix. Every protected entry begins with `.`,
so the strip removed the exact character the test then required:

    ".git/HEAD".lstrip("./")          -> "git/HEAD"          startswith(".git/")          False
    ".cursor/rules".lstrip("./")      -> "cursor/rules"      startswith(".cursor/")       False
    ".openenv_trash/x".lstrip("./")   -> "openenv_trash/x"   startswith(".openenv_trash/") False
    ".git".lstrip("./")               -> "git"               == ".git"                     False

So the function returned False for **every** input it exists to refuse — a guard that is
present, called, and inert. It is the class in `an-unwatched-check-reports-did-not-run`: the
check ran on every delete and reported "not protected" every time, and nothing compared its
answer to its intent.

The `./`-prefix case it was presumably written for still works: `"./app/x.py"` -> `"app/x.py"`.
"""
import pytest

from env_generator.llm_generator.tools.file_tools import _is_protected_delete_path
from workspace import Workspace


def _ws(tmp_path):
    return Workspace(str(tmp_path))


@pytest.mark.parametrize("rel", [
    ".git",
    ".git/HEAD",
    ".git/config",
    ".git/refs/heads/main",
    ".cursor",
    ".cursor/rules",
    ".openenv_trash",
    ".openenv_trash/api.jsx.123.deleted",
])
def test_a_protected_path_is_refused(tmp_path, rel):
    assert _is_protected_delete_path(_ws(tmp_path), tmp_path / rel) is True, rel


@pytest.mark.parametrize("rel", [
    "app/frontend/src/services/api.jsx",
    "app/backend/custom_routes.py",
    "README.md",
    ".gitignore",          # a dotfile, but not inside .git/ — deletable
    ".github/workflows/ci.yml",
    "src/.gitkeep",
])
def test_an_ordinary_path_is_still_deletable(tmp_path, rel):
    assert _is_protected_delete_path(_ws(tmp_path), tmp_path / rel) is False, rel


def test_the_dot_slash_prefix_case_still_works(tmp_path):
    """What the original `lstrip("./")` was reaching for — a leading `./` must not defeat
    the match."""
    assert _is_protected_delete_path(_ws(tmp_path), tmp_path / "./.git/HEAD") is True


def test_the_control_is_the_pre_fix_expression():
    """Planted control: the exact pre-fix line, shown returning False for all four cases it
    was supposed to catch. If this ever goes green the bug was not what this file claims."""
    def pre_fix(rel: str) -> bool:
        rel = rel.replace("\\", "/").lstrip("./")
        return rel == ".git" or rel.startswith((".git/", ".cursor/", ".openenv_trash/"))

    assert [pre_fix(r) for r in
            (".git", ".git/HEAD", ".cursor/rules", ".openenv_trash/x")] == [False] * 4
    assert pre_fix("./app/x.py") is False   # the case it did handle, unchanged by the fix


def test_delete_file_the_tool_also_refuses_now(tmp_path):
    """The guard's other caller — the fix is not apply_patch-specific."""
    from env_generator.llm_generator.tools.canonical_file_tools import DeleteFileTool
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
    res = DeleteFileTool(workspace=_ws(tmp_path)).execute(".git/HEAD")
    assert not res.success and "protected" in (res.error_message or "")
    assert (tmp_path / ".git" / "HEAD").exists()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
