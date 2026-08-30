"""#1169: the reset tool brought the stack up under a name only it knew.

`project_name = f"gen_{uuid4().hex[:8]}"` was chosen "to avoid stale
references", and it does -- by orphaning the stack from everything else. Every
other component resolves a container through the COMPOSE FILE:
`container_id(compose_file, service)` -> `compose ps -q`, plus #962's
config_files label check. A stack under a name only this tool knows is
invisible to the validation runner, the seed audit's live row counts,
#1039/#1168's queries and the port probes.

The `down --remove-orphans` two lines above is what actually clears stale
state; the random name only guaranteed the new state was unreachable.

#1157 gives every generated compose a `name:` derived from the run, so passing
no `-p` lets compose use it and every resolver agrees. The tool has never been
called in any run in the corpus (0 across r11/r12/r13/r14), so this changes no
observed behaviour -- it removes a trap before something walks into it.
"""
import re
from pathlib import Path

from env_generator.llm_generator.tools import docker_tools as dt
from env_generator.llm_generator.tools.docker_tools import (
    _compose_project_name_1169 as project_name)

SRC = Path(dt.__file__).read_text(encoding="utf-8")


def test_an_explicit_name_wins(tmp_path):
    """#1157's shape."""
    f = tmp_path / "docker-compose.yml"
    f.write_text("name: netflix-local-r16\nversion: '3.8'\nservices: {}\n",
                 encoding="utf-8")
    assert project_name(f) == "netflix-local-r16"


def test_without_a_name_it_is_the_directory(tmp_path):
    """Exactly what compose itself would do, so the two cannot disagree."""
    d = tmp_path / "docker"
    d.mkdir()
    f = d / "docker-compose.yml"
    f.write_text("version: '3.8'\nservices: {}\n", encoding="utf-8")
    assert project_name(f) == "docker"


def test_a_quoted_name_is_unquoted(tmp_path):
    f = tmp_path / "docker-compose.yml"
    f.write_text('name: "my-run"\nservices: {}\n', encoding="utf-8")
    assert project_name(f) == "my-run"


def test_an_unreadable_file_falls_back_safely():
    assert project_name("/nope/docker-compose.yml") == "docker"
    assert project_name(None) == "docker"


def test_a_name_inside_a_service_is_not_mistaken_for_the_project(tmp_path):
    """`name:` nested under a service is indented; only a top-level key counts."""
    f = tmp_path / "docker-compose.yml"
    f.write_text("services:\n  db:\n    container_name: pg\n    name: notaproject\n",
                 encoding="utf-8")
    assert project_name(f) == tmp_path.name


def test_the_tool_no_longer_passes_a_project_flag():
    """`-p <random>` is what made the stack unreachable."""
    # #943: anchor on the assignment, cut at the method's own end marker — never a
    # fixed byte window.
    i = SRC.index("_compose_project_name_1169(compose_file)")
    tail = SRC[i:SRC.index("return ToolResult", i)]
    assert '"-p", project_name' not in tail
    assert "#1169" in SRC


def test_it_still_removes_orphans_which_is_the_real_cleanup():
    assert '"down", "--remove-orphans"' in SRC
