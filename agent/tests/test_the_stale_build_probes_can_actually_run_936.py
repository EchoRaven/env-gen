r"""#936: both stale-build probes shell out to `docker`, and this host has no docker binary.

`visual_fidelity` invokes a literal ``"docker"`` in four places — the compose ``up``, the
container-id lookup, and the two ``exec``s that #715 and #738 depend on. On a podman-backed gen
host `subprocess.run` raises `FileNotFoundError`, every one of those calls sits inside a `try`, and
the probes therefore never execute. The evidence is absolute rather than statistical:

    served_build.json — #738's state file — exists in 0 of the corpus's runs.

#738 exists because r148 released v1.0.0 with the SPA crashing on every route; its one job is to
notice "the served bundle did not change while app/frontend did". #715 is the other half. Neither
has ever run here.

★ r154 is the case that wanted them. 50 commits touched 12 frontend source files after 18:00, and
across all 12 capture rounds the screens produced almost no distinct renderings:

    login 1 distinct image of 12 captures · landing 2 · games 2 · browse_home 3 · movies 3

That is the shape #738 was written to explain, and nothing could say whether the bundle was stale,
because the probe could not run. (Deliberately NOT claiming it was: the fix restores the ability to
answer, and over-reading an artifact is what made #934 necessary.)

Live proof on r154's still-running containers after the fix: runtime resolves to `podman`, the
frontend container id comes back as `206cda4e42cb`, and the exec lists
`index-CPCKce0W.js` — the Vite content-hashed name that IS #738's fingerprint.
"""
import ast
import inspect
import subprocess

import pytest

from env_generator.llm_generator.multi_agent.runtime import visual_fidelity as vf


# --------------------------------------------------------------------------- the resolver

def test_docker_is_preferred_when_present(monkeypatch):
    """A docker host must be byte-identical to before."""
    import shutil
    monkeypatch.setattr(shutil, "which", lambda b: f"/usr/bin/{b}" if b == "docker" else None)
    assert vf._runtime_bin_936() == "docker"


def test_podman_is_used_when_docker_is_absent(monkeypatch):
    import shutil
    monkeypatch.setattr(shutil, "which", lambda b: "/usr/bin/podman" if b == "podman" else None)
    assert vf._runtime_bin_936() == "podman"


def test_neither_present_falls_back_without_raising(monkeypatch):
    import shutil
    monkeypatch.setattr(shutil, "which", lambda _b: None)
    assert vf._runtime_bin_936() == "docker"


def test_it_is_resolved_per_call_not_cached(monkeypatch):
    """A cached value would survive a host change inside one process and is not worth the risk;
    `shutil.which` is a PATH walk, called a handful of times per round."""
    import shutil
    monkeypatch.setattr(shutil, "which", lambda b: "/x" if b == "docker" else None)
    assert vf._runtime_bin_936() == "docker"
    monkeypatch.setattr(shutil, "which", lambda b: "/x" if b == "podman" else None)
    assert vf._runtime_bin_936() == "podman"


# --------------------------------------------------------------------------- the id lookup

def test_the_compose_path_is_used_when_it_answers(monkeypatch):
    seen = []

    def fake(cmd, **kw):
        seen.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, "abc123\n", "")
    monkeypatch.setattr(vf.subprocess, "run", fake)
    assert vf._container_id_936("/c.yml", "frontend") == "abc123"
    assert len(seen) == 1 and "compose" in seen[0]


def test_the_name_filter_rescues_podman_compose(monkeypatch):
    """★ podman-compose's `ps` has NO service positional — argparse exits 2 with EMPTY stdout,
    which is not an exception. Already learned in validation_runner; the fallback is the fix."""
    def fake(cmd, **kw):
        if "compose" in cmd:
            return subprocess.CompletedProcess(cmd, 2, "", "unrecognized arguments: frontend")
        return subprocess.CompletedProcess(cmd, 0, "cid-from-filter\n", "")
    monkeypatch.setattr(vf.subprocess, "run", fake)
    assert vf._container_id_936("/c.yml", "frontend") == "cid-from-filter"


def test_a_missing_binary_does_not_raise(monkeypatch):
    def boom(cmd, **kw):
        raise FileNotFoundError("docker")
    monkeypatch.setattr(vf.subprocess, "run", boom)
    assert vf._container_id_936("/c.yml", "frontend") == ""


def test_multiple_ids_take_the_first(monkeypatch):
    monkeypatch.setattr(vf.subprocess, "run",
                        lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, "one\ntwo\n", ""))
    assert vf._container_id_936("/c.yml", "frontend") == "one"


# --------------------------------------------------------------------------- no literals left

def test_no_call_site_still_hardcodes_docker():
    """★ The whole defect was a literal in an argv list. Walked as AST so the ticket comments —
    which necessarily contain the word — cannot satisfy or break it."""
    tree = ast.parse(inspect.getsource(vf))
    bad = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        f = node.func
        name = getattr(f, "attr", None) or getattr(f, "id", None)
        if name != "run" or not node.args:
            continue
        argv = node.args[0]
        if isinstance(argv, ast.List) and argv.elts:
            head = argv.elts[0]
            if isinstance(head, ast.Constant) and head.value == "docker":
                bad.append(node.lineno)
    assert not bad, f"argv lists still starting with a literal 'docker' at lines {bad}"


def test_the_probes_reach_the_runtime_through_the_resolver():
    """Non-vacuity for the test above: the resolver must actually be called in argv position."""
    tree = ast.parse(inspect.getsource(vf))
    uses = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Name) and n.func.id == "_runtime_bin_936"]
    assert len(uses) >= 3, f"expected the resolver at the exec/compose sites, found {len(uses)}"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
