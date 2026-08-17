"""Audit rank-1 (whack-a-mole eradication): the generated backend's best-effort fallbacks
(``_fw_owner_val``, the seed loader) are correct by construction but SILENT — each swallowed
exception hid one real bug that then surfaced only one-per-50-min-run (the rating saga
#392->#393->#394->#395 was four bugs stacked under one ``except``). This locks in the
``_fw_dbg`` / ``_seed_dbg`` instrumentation: the swallow sites that hid those bugs now log
the exception to stderr (-> ``docker logs backend``) when FW_DEBUG is set, so ONE validation
run surfaces ALL layered failures. The helpers MUST be no-ops when FW_DEBUG is unset (zero
behaviour change on a normal delivery run).
"""
import contextlib
import io
import re

from env_generator.llm_generator.multi_agent.runtime.backend_skeleton import (
    render_skeleton_main, render_seed_data)

_TABLES = {
    "users": {"columns": [
        {"name": "id", "type": "integer", "primary_key": True},
        {"name": "email", "type": "text not null"},
        {"name": "name", "type": "text not null"}]},
    "profiles": {"columns": [
        {"name": "id", "type": "integer", "primary_key": True},
        {"name": "user_id", "type": "integer", "fk": "users.id"},
        {"name": "name", "type": "text not null"},
        {"name": "created_at", "type": "timestamp not null"}]},
    "titles": {"columns": [
        {"name": "id", "type": "integer", "primary_key": True},
        {"name": "name", "type": "text"}]},
    "ratings": {"columns": [
        {"name": "id", "type": "integer", "primary_key": True},
        {"name": "profile_id", "type": "integer", "fk": "profiles.id"},
        {"name": "title_id", "type": "integer", "fk": "titles.id"},
        {"name": "value", "type": "integer not null"}]},
}
_EPS = [{"method": "POST", "path": "/api/titles/{id}/rating", "auth_required": True},
        {"method": "POST", "path": "/api/ratings", "auth_required": True}]

_MAIN = render_skeleton_main(_EPS, _TABLES)
_SEED = render_seed_data(_TABLES)


def test_generated_sources_still_compile():
    compile(_MAIN, "main.py", "exec")
    compile(_SEED, "seed_data.py", "exec")


def test_helpers_defined_and_default_off():
    assert "def _fw_dbg(where" in _MAIN
    assert "def _seed_dbg(where" in _SEED
    # both read FW_DEBUG from the env and short-circuit when it's falsey
    assert '_FW_DEBUG = os.environ.get("FW_DEBUG"' in _MAIN or \
           "_FW_DEBUG = os.environ.get('FW_DEBUG'" in _MAIN
    assert "if not _FW_DEBUG:" in _MAIN
    assert "if not _FW_DEBUG:" in _SEED


def test_rating_saga_swallow_sites_are_instrumented():
    # the exact sites that hid #392-#395 must now name themselves when FW_DEBUG is on
    for tag in ("fw_owner_val.resolve",              # the 4-layer outer swallow (#392-#395)
                "fw_owner_val.autocreate_sub_entity",  # the auto-create INSERT (#393/#394)
                "fw_owner_val.python_type"):
        assert tag in _MAIN, tag


def test_seed_drop_sites_are_instrumented():
    for tag in ("seed_row_drop", "seed_commit_rollback", "seed_if_empty"):
        assert tag in _MAIN or tag in _SEED, tag


def _extract(src, name):
    """Pull a top-level ``def NAME(...)...`` block out of a rendered source string and exec
    it in isolation so we can exercise its runtime behaviour."""
    m = re.search(r"\ndef " + re.escape(name) + r"\(where[^\n]*\):\n(?:(?: {4}| {8})[^\n]*\n|\n)+", src)
    assert m, "could not extract %s" % name
    return m.group(0)


def _run_helper(src, name, fw_debug):
    block = _extract(src, name)
    ns = {"_FW_DEBUG": fw_debug}
    exec(block, ns)
    buf = io.StringIO()
    with contextlib.redirect_stderr(buf):
        try:
            ns[name]("some.where", ValueError("boom-xyz"))
        except Exception as exc:  # the helper must NEVER raise into the fallback path
            raise AssertionError("%s raised: %r" % (name, exc))
    return buf.getvalue()


def test_fw_dbg_is_noop_when_disabled():
    assert _run_helper(_MAIN, "_fw_dbg", False) == ""


def test_fw_dbg_prints_when_enabled():
    out = _run_helper(_MAIN, "_fw_dbg", True)
    assert "some.where" in out and "boom-xyz" in out and "FW_DEBUG" in out


def test_seed_dbg_is_noop_when_disabled():
    assert _run_helper(_SEED, "_seed_dbg", False) == ""


def test_seed_dbg_prints_when_enabled():
    out = _run_helper(_SEED, "_seed_dbg", True)
    assert "some.where" in out and "boom-xyz" in out


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
