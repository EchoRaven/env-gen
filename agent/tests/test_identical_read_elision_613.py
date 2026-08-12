r"""#613: the THIRD identical delivery of a file nobody changed.

Measured over the arc's logs — 12469 `read` calls:

    28%  first read, or a read after something wrote to the file
    28%  SECOND delivery of unchanged content
    45%  (5561) the THIRD or later

r134's backend read `custom_routes.py` **135 times** with nothing changing in between, at ~8.2k
tokens each.

#609 fixed only the provably-safe subset (duplicates inside ONE tool batch) and deliberately left
this alone: a cross-turn cache cannot know whether the agent still HOLDS the earlier content
after a context trim, and answering "unchanged" to an agent that lost it would wedge the lane.

Two things make the third-and-later delivery safe where the second was not — the agent has by
then received the identical bytes TWICE, and the marker carries its own escape hatch, so the
worst case is one extra round-trip rather than a starved lane.

State lives on the INSTANCE. Tool objects are built per agent (`agent._tool_instances`), so one
lane's reads can never suppress another's — the failure mode that made a path-keyed global
(`_file_read_state`) unusable here.
"""
import pytest

from env_generator.llm_generator.tools.canonical_file_tools.read import (
    _IDENTICAL_READ_ELIDE_AT as N,
    ReadTool,
)
from env_generator.llm_generator.workspace import Workspace


@pytest.fixture()
def tool(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "f.py").write_text("\n".join(f"line {i}" for i in range(40)),
                                           encoding="utf-8")
    return ReadTool(workspace=Workspace(str(tmp_path))), tmp_path


def _content(res):
    assert res.success, res
    return res.data["content"]


# --- the elision -----------------------------------------------------------------------------

def test_the_first_two_deliveries_are_whole(tool):
    t, _ = tool
    for _ in range(N - 1):
        assert "line 0" in _content(t.execute(file_path="app/f.py"))


def test_the_third_identical_delivery_is_a_marker(tool):
    t, _ = tool
    for _ in range(N - 1):
        t.execute(file_path="app/f.py")
    c = _content(t.execute(file_path="app/f.py"))
    assert "line 0" not in c
    assert "unchanged since your last read" in c


def test_the_marker_states_the_size_and_the_escape(tool):
    t, _ = tool
    for _ in range(N):
        res = t.execute(file_path="app/f.py")
    c = _content(res)
    assert "chars" in c and "lines" in c
    assert "force=true" in c


def test_force_re_delivers_the_whole_text(tool):
    t, _ = tool
    for _ in range(N):
        t.execute(file_path="app/f.py")
    assert "line 0" in _content(t.execute(file_path="app/f.py", force=True))


def test_a_write_resets_the_counter(tool):
    t, p = tool
    for _ in range(N):
        t.execute(file_path="app/f.py")
    (p / "app" / "f.py").write_text("changed\n", encoding="utf-8")
    assert "changed" in _content(t.execute(file_path="app/f.py"))          # 1st after change
    assert "changed" in _content(t.execute(file_path="app/f.py"))          # 2nd
    assert "unchanged since" in _content(t.execute(file_path="app/f.py"))  # 3rd


# --- what must never be suppressed -----------------------------------------------------------

def test_another_agents_tool_instance_is_unaffected(tool, tmp_path):
    """The reason a path-keyed global could not be used: agents share a process."""
    t, p = tool
    for _ in range(N + 2):
        t.execute(file_path="app/f.py")
    other = ReadTool(workspace=Workspace(str(p)))
    assert "line 0" in _content(other.execute(file_path="app/f.py"))


def test_a_ranged_read_is_always_delivered(tool):
    t, _ = tool
    for _ in range(N + 2):
        res = t.execute(file_path="app/f.py", offset=1, limit=5)
    assert "line 0" in _content(res)


def test_a_ranged_read_does_not_poison_the_whole_file_counter(tool):
    t, _ = tool
    for _ in range(5):
        t.execute(file_path="app/f.py", offset=1, limit=5)
    assert "line 0" in _content(t.execute(file_path="app/f.py"))


def test_a_different_file_has_its_own_counter(tool):
    t, p = tool
    (p / "app" / "g.py").write_text("other\n", encoding="utf-8")
    for _ in range(N + 1):
        t.execute(file_path="app/f.py")
    assert "other" in _content(t.execute(file_path="app/g.py"))


def test_the_threshold_is_at_least_three(tool):
    """Two full deliveries before any elision — that is the whole safety argument."""
    assert N >= 3


def test_the_evidence_is_recorded_next_to_the_code():
    import inspect
    src = " ".join(inspect.getsource(ReadTool.execute).replace("#", " ").split())
    assert "45% (5561) are the THIRD or later" in src and "135 times" in src


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
