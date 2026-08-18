r"""#934: when the harness fails to photograph a screen, last round's picture stays on disk.

The record is honest — #768 sets `screenshot: None`, `capture_missing: True`, and a deviation that
says in words *"This is not a verdict on the page"*. The DIRECTORY is not: `visual_gate/<name>.png`
still holds whatever the last successful round wrote, and it looks perfectly healthy.

★ This one caught me. r154 ran SEVEN rounds with `title_detail` at 0.00 while
`visual_gate/title_detail.png` held a complete, correct detail page — hero art, Play / + / like,
meta row, synopsis, Episodes with a season selector. I opened it, reasoned from it, and wrote the
r154 illustration of two tickets around "the judge scored a working page 0.00". Then I listed the
mtimes:

    title_detail.png   17:19:57   ← round 1, never rewritten
    every other screen 19:01:xx   ← this round

The capture had failed every round since. The 0.00 was correct and the picture was stale. Nothing
about the judge was wrong; #500's merge had also discarded the honest live record and kept round
1's 0.6, so `verdict.json` showed 0.6 beside a healthy image for a screen that had not been
photographed in ninety minutes.

A lane reads the same directory. So does #713, for which a stale file is a real image that can
duplicate-match another screen and produce a finding about a page nobody shot.

Renamed, never deleted — #930 has already archived the picture under the code_state that earned
its score, and the pixels stay available under a name that cannot be read as current.
"""
import pytest

from env_generator.llm_generator.multi_agent.runtime import visual_fidelity as vf


def test_a_stale_capture_is_moved_aside(tmp_path):
    (tmp_path / "title_detail.png").write_bytes(b"round-one")
    assert vf._retire_stale_capture_934(tmp_path, "title_detail") is True
    assert not (tmp_path / "title_detail.png").exists()
    assert (tmp_path / "title_detail.NOT-CAPTURED.png").read_bytes() == b"round-one"


def test_the_pixels_are_never_deleted(tmp_path):
    """★ The evidence stays. Deleting it would repeat the erasure this whole line of tickets is
    about — #767's raw reply, #768's 'could not be captured' in 0 of 116 verdicts, #932's
    findings."""
    (tmp_path / "player.png").write_bytes(b"important-evidence")
    vf._retire_stale_capture_934(tmp_path, "player")
    assert b"important-evidence" in (tmp_path / "player.NOT-CAPTURED.png").read_bytes()


def test_nothing_to_retire_is_not_an_error(tmp_path):
    assert vf._retire_stale_capture_934(tmp_path, "never_shot") is False


def test_a_second_failure_overwrites_the_previous_stale_file(tmp_path):
    """Two failed rounds in a row must not accumulate; the newest stale image is the useful one."""
    (tmp_path / "a.png").write_bytes(b"one")
    vf._retire_stale_capture_934(tmp_path, "a")
    (tmp_path / "a.png").write_bytes(b"two")
    vf._retire_stale_capture_934(tmp_path, "a")
    assert (tmp_path / "a.NOT-CAPTURED.png").read_bytes() == b"two"


def test_a_dotted_screen_name_keeps_its_name(tmp_path):
    """★ `with_suffix` would eat everything after the first dot — `a.b.png` becomes `a.NOT-...`.
    Written because the first version of this used `with_suffix`."""
    (tmp_path / "browse.v2.png").write_bytes(b"x")
    vf._retire_stale_capture_934(tmp_path, "browse.v2")
    assert (tmp_path / "browse.v2.NOT-CAPTURED.png").is_file()
    assert not (tmp_path / "browse.NOT-CAPTURED.png").exists()


def test_a_directory_that_does_not_exist_is_survivable(tmp_path):
    assert vf._retire_stale_capture_934(tmp_path / "nope", "x") is False


def test_it_never_raises_on_a_weird_name(tmp_path):
    for bad in ("", "..", "/etc/passwd"):
        assert vf._retire_stale_capture_934(tmp_path, bad) in (True, False)


def test_the_no_capture_branch_calls_it():
    """★ Behavioural anchoring is not available here without driving the whole async capture
    pipeline, so this asserts the CALL exists — and asserts it against the AST, not the text, so a
    mention in a docstring cannot satisfy it (three source-scanning instruments went wrong on
    exactly that this session)."""
    import ast
    import inspect
    fn = [n for n in ast.walk(ast.parse(inspect.getsource(vf)))
          if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
          and n.name == "run_visual_fidelity"]
    # ★ `ast.FunctionDef` alone found nothing — the capture pipeline is async, and a locator that
    # silently matches zero nodes passes any "not in" assertion. Non-vacuity asserted first.
    assert fn, "run_visual_fidelity not found"
    calls = [n for n in ast.walk(fn[0]) if isinstance(n, ast.Call)
             and isinstance(n.func, ast.Name) and n.func.id == "_retire_stale_capture_934"]
    assert len(calls) == 1, f"expected exactly one call, found {len(calls)}"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
