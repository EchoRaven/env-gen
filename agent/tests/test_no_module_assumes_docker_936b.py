r"""#936b: the same literal, everywhere else — and an explicit line under what was left.

`subprocess.run(["docker", ...])` raises `FileNotFoundError` on this host; verified by execution,
not inference. Ten argv lists across five modules began with that literal, and every one of them
sits inside a `try`, so each failed silently.

The read-only ones are now resolved through `container_runtime.runtime_bin()`. What that restores,
proven live against r154's containers:

    _find_db_container   docker ps        -> ['docker_database_1', 'docker_backend_1', ...]
    the psql candidate   docker exec …    -> rc=0, `select count(*) from titles` = 60

The agent's own database tool had no working path to the database on this host: `_find_db_container`
returned None because `docker ps` raised, and every `docker exec`/`docker compose exec` candidate
raised too, leaving only a direct `psql` that needs the binary on the host. Same for
`log_tools`' `compose logs` — a lane could not read its own container's logs.

★ UPDATE 2026-08-18 (#961): the lifecycle literals ARE now converted, and the allowlist below is
empty. The original note deferred them because "switching the binary under them could produce a
second project alongside the running one … needs a generation to validate". That risk turned out
to be bounded by construction, which is why it no longer needs a generation:

    runtime_bin() prefers docker whenever the binary resolves. Under run_netflix.sh the podman
    shim is on PATH, so it returns "docker" and the argv is byte-identical to pre-#961. The
    binary changes ONLY where `docker` does not resolve at all — and there the old call raised
    FileNotFoundError. **A call that was crashing cannot have been starting a second stack.**

Also corrected: this docstring said "ten argv lists across five modules". Measured by AST it was
SEVEN across FOUR — the count had swept in `memory_bank.py:997`, a keyword list, which is the very
false positive the structural locator below exists to reject.
"""
import ast
import pathlib

import pytest


#: ★ A LEXICAL discriminator was not enough. The first version accepted any list whose second
#: element was a docker subcommand, and `memory_bank.get_digest` holds
#: ``["docker", "compose", "port", "url", "vite", …]`` — a keyword list for a substring match,
#: not a command line. It fired on prose. The rule below is STRUCTURAL instead: a list is a
#: command line when it sits where a command line goes.
_RUNNERS = frozenset({"run", "Popen", "check_output", "call", "check_call"})
_CMD_NAMES = ("cmd", "arg", "argv", "command")

#: Functions allowed to keep the literal, with the reason. Keyed by function NAME rather than
#: line number so the guard survives edits — and so adding one is a decision someone writes down.
#: EMPTY since #961 — every lifecycle site now resolves the runtime. Kept (rather than deleted)
#: because the guard below is "nothing outside this set", and an empty set states the rule at its
#: strongest: no module may hardcode the binary. Re-adding a name is a decision someone writes down.
_LIFECYCLE_ALLOWED: dict = {}

_ROOT = pathlib.Path(__file__).resolve().parents[1] / "env_generator"


def _argv_sites():
    """(module, line, enclosing function, subcommand) for every list literal that IS a docker
    command line — judged by position, not vocabulary.

    A list counts when it is the first positional argument of a subprocess runner, or when it is
    assigned/appended into a name that reads like a command (`cmd`, `args`, `candidate_cmds`).
    Everything else beginning with the string "docker" is prose: a tag list, a keyword filter.
    """
    out = []
    for p in sorted(_ROOT.rglob("*.py")):
        if "test" in p.name:
            continue
        try:
            tree = ast.parse(p.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            continue
        funcs = [n for n in ast.walk(tree)
                 if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
        cmdish = set()          # id() of List nodes sitting in a command position
        for n in ast.walk(tree):
            if isinstance(n, ast.Call):
                fn = getattr(n.func, "attr", None) or getattr(n.func, "id", None)
                if fn in _RUNNERS and n.args and isinstance(n.args[0], ast.List):
                    cmdish.add(id(n.args[0]))
                if fn == "append" and n.args and isinstance(n.args[0], ast.List):
                    owner = getattr(n.func, "value", None)
                    nm = getattr(owner, "id", "") or getattr(owner, "attr", "")
                    if any(k in nm.lower() for k in _CMD_NAMES):
                        cmdish.add(id(n.args[0]))
            if isinstance(n, ast.Assign) and isinstance(n.value, ast.List):
                for t in n.targets:
                    nm = getattr(t, "id", "") or getattr(t, "attr", "")
                    if any(k in nm.lower() for k in _CMD_NAMES):
                        cmdish.add(id(n.value))
            if isinstance(n, ast.Return) and isinstance(n.value, ast.List):
                cmdish.add(id(n.value))
            if isinstance(n, ast.BinOp) and isinstance(n.left, ast.List):
                cmdish.add(id(n.left))          # ["docker", ...] + args
            # ★ `for cmd in (["docker", …], ["docker-compose", …]):` — database_tools' retry
            # ladder. The first locator missed it and the allowlist looked stale as a result;
            # a name that is present but unreachable is the same lie as a dead entry.
            if isinstance(n, ast.For) and isinstance(n.iter, (ast.Tuple, ast.List)):
                nm = getattr(n.target, "id", "") or getattr(n.target, "attr", "")
                if any(k in nm.lower() for k in _CMD_NAMES):
                    for e in n.iter.elts:
                        if isinstance(e, ast.List):
                            cmdish.add(id(e))
        for n in ast.walk(tree):
            if not (isinstance(n, ast.List) and n.elts and id(n) in cmdish):
                continue
            head = n.elts[0]
            if not (isinstance(head, ast.Constant) and head.value == "docker"):
                continue
            second = n.elts[1] if len(n.elts) > 1 else None
            owner = max((f for f in funcs if f.lineno <= n.lineno <= (f.end_lineno or 0)),
                        key=lambda f: f.lineno, default=None)
            out.append((str(p.relative_to(_ROOT)), n.lineno,
                        owner.name if owner else "<module>",
                        second.value if isinstance(second, ast.Constant) else "?"))
    return out


def test_the_locator_is_not_vacuous(tmp_path):
    """★ Non-vacuity, proven SYNTHETICALLY — this test used to demand the defect survive.

    It asserted `{"_compose", "_run_compose"} <= live_sites`, i.e. that two real functions still
    hardcoded the binary. #961 fixed them and this test went red *because the bug was fixed* —
    the exact shape of [[a-green-suite-can-pin-the-defect]], where three tests pinning a field's
    spelling kept #782 alive for 122 runs.

    Non-vacuity is a property of the LOCATOR, so prove it against a fixture the locator is not
    allowed to lose, never against the tree it polices.
    """
    global _ROOT
    sample = tmp_path / "sample.py"
    sample.write_text(
        "import subprocess\n"
        "def _compose(f):\n"
        "    return subprocess.run(['docker', 'compose', '-f', str(f), 'up'])\n"
        "def _base_args():\n"
        "    args = ['docker', 'compose']\n"
        "    return args\n"
    )
    _orig, _ROOT = _ROOT, tmp_path
    try:
        sites = _argv_sites()
    finally:
        _ROOT = _orig
    assert {s[2] for s in sites} >= {"_compose", "_base_args"}, (
        f"the locator no longer detects the pre-#961 shape it exists to forbid: {sites}")


def test_no_read_only_path_still_assumes_docker():
    """★ THE guard. Anything outside the lifecycle allowlist must go through the resolver."""
    stray = [s for s in _argv_sites() if s[2] not in _LIFECYCLE_ALLOWED]
    assert not stray, (
        "these assume a docker binary that does not exist on a podman host: "
        + "; ".join(f"{m}:{ln} in {fn}() (docker {sub} …)" for m, ln, fn, sub in stray))


def test_the_allowlist_has_no_dead_entries():
    """A name that no longer holds the literal is a comment pretending to be a decision."""
    live = {s[2] for s in _argv_sites()}
    assert not (set(_LIFECYCLE_ALLOWED) - live), sorted(set(_LIFECYCLE_ALLOWED) - live)


def test_prose_is_not_mistaken_for_a_command():
    """★ The bug in the FIRST version of this guard, kept as a test.

    `memory_bank.get_digest` holds ``["docker", "compose", "port", "url", "vite", …]`` — keywords
    for a substring match — and `seed_data` holds tag lists like ``["docker", "bcrypt", "alpine"]``.
    A lexical rule ("second element is a docker subcommand") flagged the first of those as a
    command line. Position is the honest test, and these two modules are the fixture."""
    found = {m for m, _, _, _ in _argv_sites()}
    assert not any("memory_bank" in m or "seed_data" in m for m in found), sorted(found)


def test_the_shared_resolver_exists_and_prefers_docker(monkeypatch):
    from env_generator.llm_generator.multi_agent.runtime import container_runtime as cr
    import shutil
    monkeypatch.setattr(shutil, "which", lambda b: "/usr/bin/docker" if b == "docker" else None)
    assert cr.runtime_bin() == "docker"
    monkeypatch.setattr(shutil, "which", lambda b: "/usr/bin/podman" if b == "podman" else None)
    assert cr.runtime_bin() == "podman"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))


# --------------------------------------------------------------------------- the shim gap

def test_the_fallback_announces_itself_once(caplog, monkeypatch):
    """★ The corrected mechanism. `tools/podman_shim/docker` rescues `docker ps` and `docker exec`
    but CANNOT rescue `docker compose ps -q <service>`: podman-compose exits 2 with empty stdout,
    which is not an exception. That single shape is what #715/#738 key on, which is why
    served_build.json exists in 0 runs — not, as this ticket first claimed, a missing binary.

    Measured under the shim: `docker ps --format` rc=0 with all three containers, and
    `docker compose -f … ps -q frontend` rc=2 with empty stdout."""
    import logging
    import subprocess as sp
    from env_generator.llm_generator.multi_agent.runtime import container_runtime as cr

    cr._SAID.clear()

    def fake(cmd, **kw):
        if "compose" in cmd:                      # podman-compose: exit 2, EMPTY stdout
            return sp.CompletedProcess(cmd, 2, "", "unrecognized arguments: frontend")
        return sp.CompletedProcess(cmd, 0, "206cda4e42cb\n", "")

    monkeypatch.setattr(cr.subprocess, "run", fake)
    with caplog.at_level(logging.INFO,
                         logger="env_generator.llm_generator.multi_agent.runtime.container_runtime"):
        assert cr.container_id("/c.yml", "frontend") == "206cda4e42cb"
        assert cr.container_id("/c.yml", "frontend") == "206cda4e42cb"
    said = [r for r in caplog.records if "#936" in r.getMessage()]
    assert len(said) == 1, f"once, not per call (#845) — got {len(said)}"
    assert "no service positional" in said[0].getMessage()


def test_a_working_compose_lookup_says_nothing(caplog):
    """On a real docker host the first path answers, and silence is correct."""
    import logging
    import subprocess as sp
    from env_generator.llm_generator.multi_agent.runtime import container_runtime as cr
    cr._SAID.clear()
    orig = cr.subprocess.run
    cr.subprocess.run = lambda cmd, **kw: sp.CompletedProcess(cmd, 0, "abc\n", "")
    try:
        with caplog.at_level(logging.INFO):
            assert cr.container_id("/c.yml", "frontend") == "abc"
    finally:
        cr.subprocess.run = orig
    assert not [r for r in caplog.records if "#936" in r.getMessage()]


# --------------------------------------------------------------------------- the preflight

def _provider(monkeypatch, out):
    import subprocess as sp
    from env_generator.llm_generator.multi_agent.runtime import container_runtime as cr
    monkeypatch.setattr(cr.subprocess, "run",
                        lambda cmd, **kw: sp.CompletedProcess(cmd, 0, out, ""))
    return cr.compose_provider()


def test_podman_compose_is_reported_as_lacking_the_service_positional(monkeypatch):
    """★ Measured on this host: `docker compose version` under the shim answers
    'podman-compose version 1.5.0', and `podman-compose ps --help` prints
    `usage: podman-compose ps [-h] [-q] [-f FORMAT]` — no service positional."""
    p = _provider(monkeypatch, "podman-compose version 1.5.0\npodman version 5.8.3\n")
    assert p["service_ps"] is False
    assert "podman-compose" in p["provider"]
    assert "no service positional" in p["message"].lower()


def test_compose_v2_is_reported_as_capable(monkeypatch):
    p = _provider(monkeypatch, "Docker Compose version v2.27.0\n")
    assert p["service_ps"] is True and "2.27" in p["provider"]


def test_a_failed_probe_assumes_capable_rather_than_crying_wolf(monkeypatch):
    """★ An unreachable probe is not evidence of a broken provider — the opposite default would
    print the warning on every docker host with a slow daemon (#845)."""
    from env_generator.llm_generator.multi_agent.runtime import container_runtime as cr

    def boom(cmd, **kw):
        raise OSError("nope")
    monkeypatch.setattr(cr.subprocess, "run", boom)
    p = cr.compose_provider()
    assert p["service_ps"] is True and p["provider"] == "unknown"


def test_the_preflight_reports_the_provider_and_uses_the_right_logger():
    """★ The seam: orchestrator has NO module-level `logger` and 117 uses of `self._logger`.
    #910 shipped that exact NameError on a line that only runs when the defect fires."""
    import ast
    import inspect
    from env_generator.llm_generator.multi_agent import orchestrator as orc
    fn = [n for n in ast.walk(ast.parse(inspect.getsource(orc)))
          if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
          and n.name == "_preflight_check"]
    assert fn, "_preflight_check not found"
    src = ast.get_source_segment(inspect.getsource(orc), fn[0]) or ""
    assert "compose_provider" in src, "the preflight must probe the compose provider"
    bare = [n for n in ast.walk(fn[0]) if isinstance(n, ast.Attribute)
            and isinstance(n.value, ast.Name) and n.value.id == "logger"]
    assert not bare, "orchestrator has no module-level `logger`; use self._logger"
