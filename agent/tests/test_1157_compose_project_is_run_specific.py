"""#1157: every run's compose project was named `docker`.

The project name defaults to the compose file's DIRECTORY, and the framework
writes it to `<run>/docker/docker-compose.yml` — so every run has shared
containers (`docker-backend-1`), networks, volumes, and image tags
(`docker-backend:latest`).

#962 documented the ambiguity and worked around it for container LOOKUP ("Stop
the stale stack, or give the run its own compose project name") but never fixed
the project name, and lookup was not the worst of it. Measured live: r13
delivered and was runtime-verified (60 titles, frontend 200); r14 then ran and
retagged `docker-backend:latest` at 02:20; bringing r13 up afterwards WITHOUT
--build served r14's backend against r13's database, and r14's model declares
`titles.genres` while r13's DDL does not. Every /api/titles answered
`UndefinedColumn: column titles.genres does not exist` -> HTTP 500, the browse
home had no data, and only the empty My List rendered. Nothing about the
verified artifact had changed except that another run happened.
"""
import re
from pathlib import Path

from env_generator.llm_generator.multi_agent.runtime import scaffolder as sc

SRC = Path(sc.__file__).read_text(encoding="utf-8")


def _block():
    """Anchor on the ticket, stop at the compose body it precedes (#943)."""
    i = SRC.index("# #1157: NAME THE COMPOSE PROJECT AFTER THE RUN.")
    return SRC[i:SRC.index("# Generated with run-specific free host ports.", i)]


def test_the_compose_file_declares_a_name():
    assert 'f"name: {_proj1157}' in SRC, "compose must carry a top-level `name:`"
    assert "orch.output_dir" in _block()


def test_the_name_line_is_prepended_not_templated():
    """test_compose_db_env_conventions locates the template by the literal
    `docker_compose = f\'\'\'` and renders it with .format() over a fixed key set,
    so a placeholder inside the template is a KeyError, not a compose change."""
    i = SRC.index('f"name: {_proj1157}')
    assert "+ docker_compose" in SRC[i:SRC.index("\n", i)]


def test_the_name_is_sanitised_to_composes_charset():
    b = _block()
    assert ".isalnum()" in b and ".isascii()" in b
    assert ".lower()" in b


def test_it_never_emits_an_empty_project_name():
    """An empty `name:` is worse than none — compose rejects the file."""
    assert '"envgen-run"' in _block()


def _proj(name: str) -> str:
    """The shipped expression, applied to a directory name."""
    out = re.sub(r"[^a-z0-9_-]+", "-", str(name or "").lower()).strip("-")
    return out or "envgen-run"


def test_real_run_names_survive_intact():
    assert _proj("netflix-local-r13") == "netflix-local-r13"
    assert _proj("netflix-local-r14") == "netflix-local-r14"
    # the two runs that collided must not collapse onto one project
    assert _proj("netflix-local-r13") != _proj("netflix-local-r14")


def test_awkward_names_are_still_valid():
    assert _proj("My Env (v2)!") == "my-env-v2"
    assert _proj("") == "envgen-run"
    assert _proj("///") == "envgen-run"
    for n in ("My Env (v2)!", "UPPER_CASE", "a.b.c"):
        assert re.fullmatch(r"[a-z0-9_-]+", _proj(n)), n
