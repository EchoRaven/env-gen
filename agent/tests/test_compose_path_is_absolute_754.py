r"""#754: the compose path was checked in one directory and used in another.

`_resolve_compose_file` searched under `generated_dir`, confirmed the file with `exists()`, and
returned the path **as given**. `start_run` then handed that string to a subprocess whose cwd is
`generated_dir` itself. When `generated_dir` arrives relative — and some call paths pass it that
way — the check succeeds against the PARENT's cwd (`repo/agent`) and the identical string is
unresolvable in the child.

The error reads like a missing file and is not one:

    compose up FAILED (rc=1) — Cause: CRITICAL:podman_compose:missing files:
    ['generated/netflix-web-r149/docker/docker-compose.yml']

while `agent/generated/netflix-web-r149/docker/docker-compose.yml` is right there, 3464 bytes.

r149 hit it five times. The corpus holds **216 recorded boot failures and not one of them said
why**, because `compose_stderr` had one writer and zero readers until #748 — this is the first
defect that finding paid for, and it was found by reading r149's log rather than by guessing.

Both halves are fixed: the returned compose path is resolved, and so is the cwd handed to
`ComposeLifecycle` — leaving the cwd relative works only while the parent happens to sit where it
was built, which is the same coupling one argument over.
"""
import inspect
import pathlib

import pytest

from env_generator.llm_generator.multi_agent.runtime.hubs.runhub import service as svc


def _tree(tmp_path, name="docker-compose.yml", where="docker"):
    root = tmp_path / "generated" / "envX"
    d = root / where if where else root
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_text("services: {}\n", encoding="utf-8")
    return root


# --- the r149 case ------------------------------------------------------------------------------

def test_a_relative_input_yields_an_absolute_path(tmp_path, monkeypatch):
    root = _tree(tmp_path)
    monkeypatch.chdir(tmp_path)
    got = svc._resolve_compose_file("generated/envX")
    assert got is not None
    assert pathlib.Path(got).is_absolute(), got


def test_the_returned_path_resolves_from_the_childs_cwd(tmp_path, monkeypatch):
    """The actual failure: the child runs with cwd=generated_dir. Before #754 the returned
    relative path did not exist from there, which is precisely what podman_compose reported."""
    root = _tree(tmp_path)
    monkeypatch.chdir(tmp_path)
    got = svc._resolve_compose_file("generated/envX")
    monkeypatch.chdir(root)                       # become the subprocess
    assert pathlib.Path(got).exists(), got


def test_the_old_behaviour_is_reproducible(tmp_path, monkeypatch):
    """Non-vacuity: without resolving, the same string really is unresolvable in the child."""
    root = _tree(tmp_path)
    monkeypatch.chdir(tmp_path)
    naive = "generated/envX/docker/docker-compose.yml"
    assert pathlib.Path(naive).exists(), "it exists from the parent's cwd"
    monkeypatch.chdir(root)
    assert not pathlib.Path(naive).exists(), "and not from the child's — that is the bug"


# --- the rest of #293's contract is untouched ------------------------------------------------------

def test_an_absolute_input_still_works(tmp_path):
    root = _tree(tmp_path)
    got = svc._resolve_compose_file(str(root))
    assert got == str((root / "docker" / "docker-compose.yml").resolve())


@pytest.mark.parametrize("name,where", [
    ("docker-compose.yml", "docker"),
    ("docker-compose.dev.yml", "docker"),
    ("docker-compose.yml", ""),
    ("docker-compose.yaml", ""),
])
def test_every_candidate_location_is_still_searched(tmp_path, name, where):
    root = _tree(tmp_path, name=name, where=where)
    got = svc._resolve_compose_file(str(root))
    assert got and got.endswith(name), got


def test_docker_dir_still_wins_over_the_root(tmp_path):
    root = _tree(tmp_path, "docker-compose.yml", "docker")
    (root / "docker-compose.yml").write_text("services: {}\n", encoding="utf-8")
    got = svc._resolve_compose_file(str(root))
    assert "docker/docker-compose.yml" in got.replace("\\", "/")


def test_no_compose_file_is_still_none(tmp_path):
    (tmp_path / "empty").mkdir()
    assert svc._resolve_compose_file(str(tmp_path / "empty")) is None


def test_a_missing_root_is_still_none(tmp_path):
    assert svc._resolve_compose_file(str(tmp_path / "nope")) is None


# --- the cwd half ------------------------------------------------------------------------------------

def _start_run_src() -> str:
    return inspect.getsource(svc.RunHub.start_run)


def test_the_cwd_is_resolved_too():
    s = _start_run_src()
    assert "_gd754 = str(Path(generated_dir).resolve())" in s
    assert "cwd=_gd754" in s


def test_the_compose_file_is_resolved_from_the_same_value():
    """Both must come from ONE resolved value; deriving them separately is how they drifted."""
    s = _start_run_src()
    assert "compose_file=_resolve_compose_file(_gd754)" in s


def test_an_unresolvable_path_does_not_crash_the_run():
    s = _start_run_src()
    i = s.index("_gd754 = str(Path(generated_dir).resolve())")
    assert "except Exception:" in s[i:s.index("compose = compose or", i)]


def test_an_injected_compose_still_wins():
    """`compose or ...` — callers that pass their own lifecycle must be unaffected."""
    assert "compose = compose or ComposeLifecycle(" in _start_run_src()


# --- provenance ---------------------------------------------------------------------------------------

def test_the_diagnosis_is_recorded_not_just_the_fix():
    d = " ".join(inspect.getsource(svc._resolve_compose_file).replace("#", " ").split())
    assert "a path checked in one directory and used in another" in d
    assert "it reads as the former" in d


def test_the_r149_evidence_is_quoted():
    d = " ".join(inspect.getsource(svc._resolve_compose_file).replace("#", " ").split())
    assert "missing files:" in d and "netflix-web-r149" in d
    assert "3464 bytes" in d


def test_the_debt_to_748_is_recorded():
    d = " ".join(inspect.getsource(svc._resolve_compose_file).replace("#", " ").split())
    assert "216 recorded boot" in d
    assert "the first defect that finding paid for" in d


def test_293s_original_reason_survives():
    """#293 fixed 'no configuration file provided' (r76: 16/16 aborted). #754 must not erase it."""
    d = " ".join((svc._resolve_compose_file.__doc__ or "").split())
    assert "no configuration file provided" in d
    assert "16/16 aborted" in d


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
