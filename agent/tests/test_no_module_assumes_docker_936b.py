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

★ What is deliberately NOT changed, and why: every remaining literal is in a LIFECYCLE path — it
creates, starts, stops or prunes containers. Those are not dead in the same sense (something does
bring the stack up in every run, and I have not traced what), so switching the binary under them
could produce a second project alongside the running one. That needs a generation to validate, not
a unit test, and it is recorded rather than guessed at.
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
_LIFECYCLE_ALLOWED = {
    "_compose": "validation_runner: compose up/build/down for the generated stack",
    "_base_args": "runhub ComposeLifecycle: up/down",
    "_run_compose": "docker_tools: the agent's compose build/up path",
    "_try_start_db_service": "database_tools: compose up -d <db service>",
    "execute": "docker_tools tool bodies: compose down, container prune",
}

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


def test_the_locator_finds_the_known_lifecycle_sites():
    """★ Non-vacuity. A locator that matches nothing would make the next test pass forever."""
    sites = _argv_sites()
    assert sites, "found no docker argv lists at all — the locator is broken, not the tree"
    assert {"_compose", "_run_compose"} <= {s[2] for s in sites}


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
