"""#1173: Docker owned app/database, so the re-author could never write.

The wipe #482 exists for removes `app/database/init/` ENTIRELY -- the directory,
not just the file. The compose stack then mounts `../app/database/init`, and
Docker CREATES a missing bind-mount source as ROOT. The framework runs as an
ordinary user, so every later re-author fails EACCES and the run can never
clear `database_sql_missing`.

This is what actually killed netflix-local-r11: 119 `Permission denied:
.../app/database/init/` lines with `app/database` owned root:root, against 0
such lines in r13 and r14, which both delivered. I had diagnosed r11 as the
branch-topology mechanism (#1148) -- the file really was only on `main` -- but
the reason the framework could not restore it was these 119 failures, which I
never read at the time.

It recurred on r16 mid-session: 26 failures, the gate stuck on
database_sql_missing, and clearing the directory by hand took the same run to a
single remaining check within one tick.

`app/` belongs to the run, so the directory can be moved aside and rebuilt
WITHOUT root -- rename is a parent-directory operation.
"""
import asyncio
import os
import stat
import types
from pathlib import Path

import pytest

from env_generator.llm_generator.multi_agent.runtime.framework_validation import (
    _os_access_w, reauthor_missing_database_sql as heal)


def _orch(root, on_generate=None):
    calls = []

    class _O:
        output_dir = root
        _logger = types.SimpleNamespace(warning=lambda *a, **k: calls.append(a[0]))

        async def _generate_database(self):
            d = Path(self.output_dir) / "app" / "database" / "init"
            d.mkdir(parents=True, exist_ok=True)
            (d / "01_init.sql").write_text("-- schema", encoding="utf-8")
            if on_generate:
                on_generate()

    o = _O()
    o.calls = calls
    return o


def test_writability_probe(tmp_path):
    d = tmp_path / "d"
    d.mkdir()
    assert _os_access_w(d) is True
    os.chmod(d, stat.S_IRUSR | stat.S_IXUSR)
    try:
        assert _os_access_w(d) is False
    finally:
        os.chmod(d, 0o755)


def test_an_unknown_path_is_assumed_writable():
    """Never invent a blocker: an unanswerable probe must not trigger the move."""
    assert _os_access_w(None) is True


def test_a_root_owned_directory_is_moved_aside_and_rebuilt(tmp_path):
    (tmp_path / "app" / "database" / "init").mkdir(parents=True)
    os.chmod(tmp_path / "app" / "database", stat.S_IRUSR | stat.S_IXUSR)
    o = _orch(tmp_path)
    try:
        assert asyncio.run(heal(o)) is True
    finally:
        for p in (tmp_path / "app").iterdir():
            if p.is_dir():
                os.chmod(p, 0o755)
    assert (tmp_path / "app" / "database" / "init" / "01_init.sql").exists()
    assert any(p.name.startswith(".database-root-orphan")
               for p in (tmp_path / "app").iterdir())
    assert any("#1173" in c for c in o.calls)


def test_a_writable_directory_is_left_alone(tmp_path):
    """The move is a repair, not a routine -- a healthy run must not see it."""
    (tmp_path / "app" / "database" / "init").mkdir(parents=True)
    o = _orch(tmp_path)
    assert asyncio.run(heal(o)) is True
    assert not any(p.name.startswith(".database-root-orphan")
                   for p in (tmp_path / "app").iterdir())
    assert not any("#1173" in c for c in o.calls)


def test_an_existing_sql_short_circuits_before_any_of_this(tmp_path):
    d = tmp_path / "app" / "database" / "init"
    d.mkdir(parents=True)
    (d / "01_init.sql").write_text("-- already here", encoding="utf-8")
    o = _orch(tmp_path)
    assert asyncio.run(heal(o)) is False
    assert o.calls == []


def test_it_never_raises_into_the_tick_loop(tmp_path):
    class _Bad:
        output_dir = tmp_path / "nope"
        _logger = types.SimpleNamespace(warning=lambda *a, **k: None)

        async def _generate_database(self):
            raise RuntimeError("boom")

    assert asyncio.run(heal(_Bad())) is False
