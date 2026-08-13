r"""#669: every agent's memory bank said the backend was Node.js/Express. It is FastAPI.

`memory-bank/<agent>/` was the last unmined artifact. Hashing it is what exposed this:

    tech_context.md      1715 files, ONE distinct md5 — byte-identical everywhere
    system_patterns.md   1715 files, ONE distinct md5
    project_brief.md     1715 files, 144 distinct — i.e. per-RUN, as intended
    active_context.md    1715 files, 457 distinct

Two of the six files are global constants, and one of those constants is factually wrong:

    - Backend: Node.js                                     <- {backend_tech}, defaulted
    - Backend: Express, JWT auth, PostgreSQL client        <- hardcoded, not a placeholder
    - Otherwise run backend + frontend locally with node   <- hardcoded

against a corpus where **144 of 144** generated backends are Python/FastAPI and **0** have a
`package.json`. `project_info` never supplies a "backend" key, so the "Node.js" default was used
in all 1715. Every lane, in every run, was told the wrong stack — uniformly, which is why no
single run ever looked anomalous.

Every replacement claim was checked against the corpus before being written, after the first
draft invented `app/backend/requirements.txt` — which exists in 0 of 144. The real manifest is
`app/backend/pyproject.toml` (136 of 144; the other 8 have none), and all 136 declare fastapi,
uvicorn, sqlalchemy, psycopg and pyjwt.
"""
import re

import pytest

from env_generator.llm_generator.memory import memory_bank as mb


def _tech_template():
    return mb.MemoryBank.CORE_FILES["tech_context"]["template"]


def _source():
    import inspect
    return inspect.getsource(mb)


# --- the wrong facts are gone -------------------------------------------------------------------

def test_the_backend_default_is_no_longer_Node():
    src = _source()
    assert 'project_info.get("backend", "Node.js")' not in src


def test_the_backend_default_is_what_the_scaffolder_emits():
    src = _source()
    assert 'project_info.get("backend", "FastAPI (Python)")' in src


def test_the_template_no_longer_claims_Express():
    assert "Express" not in _tech_template()


def test_the_template_no_longer_tells_the_lane_to_run_the_backend_with_node():
    body = _tech_template().lower()
    assert "backend + frontend locally with node" not in body


# --- the right facts are stated ------------------------------------------------------------------

@pytest.mark.parametrize("dep", ["FastAPI", "Uvicorn", "SQLAlchemy", "psycopg", "PyJWT"])
def test_the_real_backend_dependencies_are_named(dep):
    """All five are declared by 136 of 136 generated backends that have a manifest."""
    assert dep in _tech_template()


def test_it_names_the_real_manifest_path():
    """The first draft invented app/backend/requirements.txt — 0 of 144 have one."""
    t = _tech_template()
    assert "app/backend/pyproject.toml" in t
    assert "requirements.txt" not in t


def test_it_says_plainly_that_the_backend_has_no_package_json():
    """0 of 144 backends have one; a lane looking for it will not find it."""
    assert "NO package.json" in _tech_template()


def test_the_frontend_manifest_is_still_pointed_at_correctly():
    assert "app/frontend/package.json" in _tech_template()


def test_uvicorn_is_named_as_the_way_to_run_it():
    assert "uvicorn" in _tech_template().lower()


# --- the substitutable parts still substitute ------------------------------------------------------

def test_the_stack_lines_are_still_placeholders_not_literals():
    """A caller that DOES know the stack must still be able to override all three."""
    t = _tech_template()
    for ph in ("{frontend_tech}", "{backend_tech}", "{database_tech}"):
        assert ph in t


def test_the_frontend_and_database_defaults_are_unchanged():
    """Both were already correct — React and PostgreSQL — and must not move."""
    src = _source()
    assert 'project_info.get("frontend", "React")' in src
    assert 'project_info.get("database", "PostgreSQL")' in src


def test_the_template_still_renders_with_the_three_keys():
    rendered = _tech_template().format(frontend_tech="React", backend_tech="FastAPI (Python)",
                                       database_tech="PostgreSQL")
    assert "- Backend: FastAPI (Python)" in rendered
    assert "{" not in rendered.replace("{}", "")


def test_no_other_placeholder_was_introduced():
    """A stray brace would raise KeyError at render time for every agent."""
    names = set(re.findall(r"\{(\w+)\}", _tech_template()))
    assert names == {"frontend_tech", "backend_tech", "database_tech"}


# --- provenance -------------------------------------------------------------------------------

def test_the_measurement_is_recorded():
    flat = " ".join(_source().replace("#", " ").split())
    assert "BYTE-IDENTICAL across all 1715 agent memory banks" in flat
    assert "144 of 144 generated backends are Python/FastAPI" in flat


def test_why_it_went_unnoticed_is_recorded():
    flat = " ".join(_source().split())
    assert "nothing ever supplies a" in flat


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
