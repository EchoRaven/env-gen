r"""#1203ha: `ToolResult.fail(msg, data=...)` swallowed the payload into metadata.

```python
    @classmethod
    def fail(cls, error_message: str, **metadata) -> "ToolResult":
        return cls(success=False, error_message=error_message, metadata=metadata)
```

`data=` landed in `**metadata`, so `self.data` stayed None and the payload sat in
`self.metadata["data"]` -- which `__str__` never reads, and which nothing in the tree
reads either: zero consumers of `metadata["data"]` exist.

#674 exists precisely to stop a failed result dropping `data` on the floor ("on FAILURE
this returned the error line ALONE and dropped `data` on the floor -- and `data` is where
tools put what actually went wrong"). This construction walked straight past it.

MEASURED over the corpus, on the four call sites that pass `data=`:
    353  `Docker compose validation failed: Found N issue(s) in docker-compose.yml`
         across 93 logs. `data["issues"]` names every issue; the agent saw the COUNT.
         261 of the 353 say "Found 1 issue(s)" -- one issue, never named, 93 runs.
    181  `Query failed: ...` across 58 logs. `data` carried `error_type` and a COMPUTED
         `suggestion` from `_parse_db_error`; the agent saw neither.
The other two sites (no working DB transport, connectivity test) have never fired in the
corpus, so no claim is made for them -- they are the same construction and fixed with it.

★ WHY A CHOKEPOINT AND NOT FOUR EDITS. "Fixing one reader is worse than none": four call
sites today, and the next one to write `fail(msg, data=...)` would read as correct and
silently drop its diagnosis again. The fix is in `fail`, and
`test_fail_cannot_swallow_data_again` pins it there.
"""
import ast
import asyncio
import inspect
import os
import pathlib
import sys

_AGENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _AGENT)
sys.path.insert(0, os.path.join(_AGENT, "env_generator", "llm_generator"))

from utils.tool import ToolResult  # noqa: E402


# ------------------------------------------------------------- the constructor
def test_data_reaches_the_payload_not_the_metadata():
    """★ The defect in one assertion."""
    res = ToolResult.fail("Query failed", data={"suggestion": "create the table first"})
    assert res.data == {"suggestion": "create the table first"}
    assert "data" not in res.metadata, res.metadata


def test_the_agent_facing_text_carries_the_payload():
    """What #674 built the rendering for. The error line alone is the defect."""
    res = ToolResult.fail("Query failed: relation \"users\" does not exist",
                          data={"error_type": "undefined_table",
                                "suggestion": "Create the table first."})
    text = str(res)
    assert "does not exist" in text, text
    assert "Create the table first." in text, text


def test_other_metadata_still_goes_to_metadata():
    """★ The non-regression: `data` is the only key that moves."""
    res = ToolResult.fail("boom", exit_code=3, attempts=2)
    assert res.metadata == {"exit_code": 3, "attempts": 2}
    assert res.data is None


def test_a_failure_with_no_payload_is_unchanged():
    res = ToolResult.fail("just a message")
    assert res.data is None and res.metadata == {} and res.success is False
    assert "just a message" in str(res)


def test_a_falsy_payload_is_still_moved():
    """`metadata.pop("data", None)` must not be confused with a truthiness test: an empty
    issue list is a different statement from no payload at all."""
    res = ToolResult.fail("nothing found", data=[])
    assert res.data == [], res.data
    assert "data" not in res.metadata


# ---------------------------------------------------------- the real call sites
def _fake_workspace(root):
    class _W:
        base_root = root
    return _W()


def test_docker_validate_names_the_issue_it_found():
    """★ THE CALLER, not the helper. 261 corpus records say "Found 1 issue(s)" and never
    which -- this drives the real tool over a real compose file whose build context does
    not exist, and requires the issue text in what the agent reads."""
    import tempfile

    from tools.docker_tools import DockerValidateTool
    with tempfile.TemporaryDirectory() as d:
        root = pathlib.Path(d)
        (root / "docker").mkdir()
        (root / "docker" / "docker-compose.yml").write_text(
            "services:\n"
            "  backend:\n"
            "    build:\n"
            "      context: ../does-not-exist-anywhere\n"
            "      dockerfile: Dockerfile\n"
        )
        tool = DockerValidateTool(workspace=_fake_workspace(root))
        res = asyncio.run(tool.execute())
        assert res.success is False, res
        text = str(res)
        assert "issue" in text.lower(), text
        # the issue list itself, not just its length
        assert res.data is not None, "the payload is gone again"
        assert res.data.get("issues"), res.data
        assert str(res.data["issues"][0])[:20] in text, (res.data["issues"][0], text)


def test_the_four_payload_call_sites_are_still_wired():
    """★ Structural. If a site stops passing `data=`, its diagnosis is gone again and no
    behavioural test here would notice."""
    found = []
    for rel in ("env_generator/llm_generator/tools/docker_tools.py",
                "env_generator/llm_generator/tools/database_tools.py"):
        tree = ast.parse(pathlib.Path(os.path.join(_AGENT, rel)).read_text(encoding="utf-8"))
        for n in ast.walk(tree):
            if (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                    and n.func.attr == "fail"
                    and isinstance(n.func.value, ast.Name)
                    and n.func.value.id == "ToolResult"
                    and any(k.arg == "data" for k in n.keywords)):
                found.append((rel, n.lineno))
    assert len(found) >= 4, found


def test_fail_cannot_swallow_data_again():
    """★ The chokepoint pinned. `**metadata` is still the signature -- what matters is that
    `data` is lifted out of it before the result is built."""
    src = inspect.getsource(ToolResult.fail)
    assert 'metadata.pop("data"' in src, src
    assert "data=data" in src, src
