"""N-P0-3 (Netflix): string business-key capture + placeholder resolution.

The #245 LIVE recovery path already substitutes a real value for a wrong-typed
literal on a 404/500. This covers the OTHER half: a verifier-authored chain that
references a ``${title_slug}``/``${username}`` placeholder no prior step saved.
Before this fix, ``_harvest_resource_ids`` captured only ``id`` (so a slug leaked
through as the literal ``${title_slug}`` -> 404) and ``_resolve_unresolved_dollar_vars``
only resolved ``${x_id}``. Netflix detail routes are keyed by ``{slug}``/``{titleSlug}``.

Loaded in isolation (the full engine import graph needs a Rust toolchain that is
egress-blocked here); chain_executor's only sibling import is stubbed.
"""
import sys
import types
import pathlib

_RUNTIME = pathlib.Path(__file__).resolve().parents[1] / (
    "env_generator/llm_generator/multi_agent/runtime")


def _load_chain_executor():
    pkg = types.ModuleType("ce_pkg")
    pkg.__path__ = []
    sys.modules["ce_pkg"] = pkg
    import env_generator.llm_generator.multi_agent.runtime.message_format as _mf1034
    sys.modules["ce_pkg.message_format"] = _mf1034  # #1034: leaf helper, no deps
    vr = types.ModuleType("ce_pkg.validation_runner")
    vr._http = lambda *a, **k: {"status": 0}
    vr._form_retry_warranted = lambda *a, **k: False
    # #1052: chain_executor imports the REAL predicate from validation_runner (one definition,
    # shared with #1051). This harness hand-stubs every module the source reaches, so a new
    # import must be added here too — same seam the #1034 helper hit.
    from env_generator.llm_generator.multi_agent.runtime.validation_runner import (
        _route_ran_despite_404_1051 as _rr1051)
    vr._route_ran_despite_404_1051 = _rr1051
    sys.modules["ce_pkg.validation_runner"] = vr
    src = (_RUNTIME / "chain_executor.py").read_text(encoding="utf-8")
    mod = types.ModuleType("ce_pkg.chain_executor")
    mod.__package__ = "ce_pkg"
    exec(compile(src, str(_RUNTIME / "chain_executor.py"), "exec"), mod.__dict__)
    return mod


ce = _load_chain_executor()


# --- harvest captures string business keys, not just id -----------------------

def test_harvest_captures_slug_alongside_id():
    into = {}
    ce._harvest_resource_ids({"titles": [{"id": 7, "slug": "stranger-things"}]}, into)
    assert into.get("title") == 7          # existing #83 behaviour preserved
    assert into.get("title_slug") == "stranger-things"


def test_harvest_captures_username_and_handle():
    into = {}
    ce._harvest_resource_ids(
        {"users": [{"id": 3, "username": "neo", "handle": "the_one"}]}, into)
    assert into.get("user") == 3
    assert into.get("user_username") == "neo"
    assert into.get("user_handle") == "the_one"


def test_harvest_string_key_is_setdefault_not_clobber():
    into = {"title_slug": "authored-value"}
    ce._harvest_resource_ids({"titles": [{"id": 1, "slug": "from-feed"}]}, into)
    assert into["title_slug"] == "authored-value"  # never overwrite a captured value


def test_harvest_ignores_empty_string_keys():
    into = {}
    ce._harvest_resource_ids({"titles": [{"id": 1, "slug": "   "}]}, into)
    assert "title_slug" not in into
    assert into.get("title") == 1


# --- placeholder resolution now handles string keys ---------------------------

def test_resolve_string_placeholder_from_by_resource():
    by = {"title": 7, "title_slug": "stranger-things"}
    assert ce._resolve_unresolved_dollar_vars("${title_slug}", 99, by) == "stranger-things"


def test_resolve_username_placeholder_from_by_resource():
    by = {"user_username": "neo"}
    assert ce._resolve_unresolved_dollar_vars("${user_username}", 99, by) == "neo"


def test_resolve_id_placeholder_unchanged():
    # #245/#136 numeric path must keep resolving via the res=var[:-3] rule.
    by = {"video": 42}
    assert ce._resolve_unresolved_dollar_vars("${video_id}", 99, by) == 42


def test_resolve_unknown_string_key_falls_back_to_last_id():
    # A ${x_slug} with nothing captured still degrades to last_id (prior behaviour),
    # never leaves the raw literal.
    assert ce._resolve_unresolved_dollar_vars("${missing_slug}", 5, {}) == 5


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
