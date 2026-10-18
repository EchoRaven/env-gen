r"""#1202x: probe the database service this compose declares, not three guesses.

`_db_container_1039` swept ("database", "db", "postgres") unconditionally. On a project whose
only database service is `database` — every netflix run — two of those three name a service that
does not exist, and each miss costs a `docker ps` plus an ERROR line reporting that it found
OTHER runs' containers instead:

    r30   132x  `docker ps --filter name=db` found 3 running container(s) ... NONE belongs to
                this run

An error about a service that was never supposed to exist. The narrowing is safe by
construction: an unreadable or unparsable compose yields an empty set, which means "do not
narrow" and restores the old sweep exactly.

Deliberately not a YAML parse — this runs inside a gate and pyyaml is not guaranteed here.
"""

import sys
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS_DIR.parent / "env_generator" / "llm_generator"))

from multi_agent.runtime.seed_audit import _compose_services_1202x  # noqa: E402


_COMPOSE = """version: '3'

services:
  database:
    image: postgres:15
    environment:
      POSTGRES_DB: app
  backend:
    build: ../app/backend
  frontend:
    build: ../app/frontend

volumes:
  app_auth_keys:
"""


def _write(tmp_path, text):
    f = tmp_path / "docker-compose.yml"
    f.write_text(text, encoding="utf-8")
    return f


def test_it_reads_the_declared_services(tmp_path):
    assert _compose_services_1202x(_write(tmp_path, _COMPOSE)) == {
        "database", "backend", "frontend"}


def test_it_stops_at_the_end_of_the_services_block(tmp_path):
    """`volumes:` and its children are not services."""
    got = _compose_services_1202x(_write(tmp_path, _COMPOSE))
    assert "volumes" not in got and "app_auth_keys" not in got


def test_nested_keys_are_not_services(tmp_path):
    got = _compose_services_1202x(_write(tmp_path, _COMPOSE))
    assert "image" not in got and "environment" not in got and "POSTGRES_DB" not in got


def test_an_unreadable_file_does_not_narrow(tmp_path):
    """Empty means 'probe everything', which is the safe direction."""
    assert _compose_services_1202x(tmp_path / "nope.yml") == set()
    assert _compose_services_1202x(_write(tmp_path, "no services key here\n")) == set()


def test_the_resolver_falls_back_when_nothing_is_declared(tmp_path, monkeypatch):
    """A compose it cannot read must still try all three names, as before.

    #1203nr changed the CRITERION, not the property. This read a SOURCE SLICE from
    `def _db_container_1039` to the next `\ndef `, and #1203nr moved that function's body
    into `_db_container_why_1203nr` so the reason could travel with the id -- the slice then
    held only the delegating wrapper and the assertion failed on a refactor that preserves
    exactly what it was written to protect. Asserted as BEHAVIOUR now (#943): probe the
    resolver and see which service names it actually asks for.
    """
    from env_generator.llm_generator.multi_agent.runtime import container_runtime as CR
    from env_generator.llm_generator.multi_agent.runtime import seed_audit as SA

    asked = []

    def spy(compose, svc, timeout=None):
        asked.append(svc)
        return ""

    monkeypatch.setattr(CR, "container_id", spy)

    # unreadable / no services key -> must not narrow
    SA._db_container_1039(_write(tmp_path, "no services key here\n"), 5)
    assert asked == ["database", "db", "postgres"], asked

    # declares only `database` -> must narrow to it (that is #1202x's whole point)
    asked.clear()
    SA._db_container_1039(_write(tmp_path, _COMPOSE), 5)
    assert asked == ["database"], asked
