"""#1202gf — the gate's other required artifact never reached the release.

delivery_gate's `required_files` is ["docker/docker-compose.yml", "design/README.md"], but
the framework-delivery commit stages `_subs_1148 = ["app", "mcp_server", "docker"]`. Only
the first required file lives under one of those, so the second was checked in the WORKING
TREE and never committed to `integration` — which is where the release branch is cut from.

Measured across the 136 kept repos on this machine: 113 carry design/README.md in the
working tree, and 2 have it committed. So in 111 of 113 the gate passed on a file the
release does not contain. It is consumer-facing — the app's name, its full API surface and
the `docker compose up` line — exactly what someone receiving the environment needs.

Staged as a single FILE. `design/` also holds the reference images and screenshots, 170–265
MB of them, and #1202cs exists precisely to keep those out of the run's git history.
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(
    0, str(Path(__file__).resolve().parents[1] / "env_generator" / "llm_generator"))

MA = Path(__file__).resolve().parents[1] / "env_generator" / "llm_generator" / "multi_agent"
HEAL = (MA / "runtime" / "heal_pipeline.py").read_text(encoding="utf-8")
GATE = (MA / "runtime" / "delivery_gate.py").read_text(encoding="utf-8")


def _required_files() -> list:
    """Read the gate's own list rather than restating it."""
    i = GATE.index("required_files = [")
    block = GATE[i:GATE.index("]", i)]
    return re.findall(r'"([^"]+)"', block)


def test_the_gate_still_requires_the_readme():
    """If this list changes, the staging below has to change with it."""
    req = _required_files()
    assert "design/README.md" in req, req
    assert "docker/docker-compose.yml" in req, req


def test_every_required_file_is_staged_by_the_delivery_commit():
    """The property: nothing the gate requires may be absent from what ships."""
    i = HEAL.index("_subs_1148 = [")
    subs = re.findall(r'"([^"]+)"', HEAL[i:HEAL.index("]", i)])
    # Anchor on the git call itself: the same message appears in #1150's comment above,
    # and index() would find that one first (the #943 trap, in this test).
    commit_i = HEAL.index('["commit", "-m",')
    staged_block = HEAL[i:commit_i]
    for rel in _required_files():
        covered = any(rel == s or rel.startswith(s.rstrip("/") + "/") for s in subs)
        if covered:
            continue
        assert f'"{rel}"' in staged_block, (
            f"{rel} is required by the gate but is under no staged subdirectory "
            f"({subs}) and is not staged by name — it cannot reach the release")


def test_the_readme_is_staged_as_a_file_not_the_directory():
    """design/ carries 170-265 MB of reference images; #1202cs keeps them out of git."""
    import re as _re
    # The property: every path handed to `git add` is a file or an app-tree subdirectory —
    # never `design` itself. (A quoted "design" also appears legitimately in the
    # `repo / "design" / "README.md"` path construction, so match the git call, not the word.)
    staged_args = _re.findall(r'\["add", "-A", "--", ([^\]]+)\]', HEAL)
    assert staged_args, "no git add call found"
    for args in staged_args:
        assert '"design"' not in args, f"the whole design/ directory is staged: {args}"
    assert any('"design/README.md"' in a for a in staged_args), staged_args


def test_it_is_guarded_by_the_file_existing():
    # Landmark-anchored, never a byte window (#943): the guard is the `try:` that opens
    # this block, so read from there to the git call.
    i = HEAL.index('["add", "-A", "--", "design/README.md"]')
    guard = HEAL.rindex("try:", 0, i)
    assert "is_file()" in HEAL[guard:i], (
        "stages unconditionally; a missing README would error")


def test_the_failure_is_reported_not_swallowed_silently():
    i = HEAL.index("#1202gf README stage skipped")
    line_start = HEAL.rindex("\n", 0, i)
    line_end = HEAL.index("\n", i)
    assert "_logger" in HEAL[line_start:line_end]
