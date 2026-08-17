r"""#789: the write guard could switch itself off, permanently and silently.

Found by the sweep item 114 called for — check that every prompt claim asserting a CONSEQUENCE has
a live enforcer. Ten claims were checked and nine were clean (the first two probes came back empty
only because the patterns were too narrow; `_framework_owned_routes` and the audit's
page-imports-page regex both exist and are load-bearing). This is what the tenth turned up — not a
missing enforcer, but a live one that can vanish:

    except Exception:
        _FW_OWNED_MAP_CACHE = []        # silent AND sticky

Two properties, each defensible alone, harmful together:

  * **silent** — no log. The prompt tells the backend lane "the write is denied + discarded" for
    main.py / models.py / Dockerfile / pyproject. If the guard is off, that sentence is false and
    nothing says so.
  * **sticky** — the failure is CACHED. And the failure mode is not hypothetical: this function is
    lazy *precisely because it can be reached during module load* ("Lazy + cached to avoid a
    module-load cycle"). A call at that moment raises, caches `[]`, and leaves every
    framework-owned file writable for the rest of the process — after the cycle has resolved.

The fail-open itself is deliberate and is KEPT ("never wedge writes"). Only its visibility and its
permanence change: success is cached, failure is not, and the degradation is announced once.

Same family as #769 (a bare `except: continue` lost 9 of 12 captures and the gate reported a
HARNESS number as an app score), #770 (a failed repair said nothing) and #788 (a claim with no
enforcer). The recurring shape is not "the code is wrong" — it is **"the code stopped working and
nothing said so."**
"""
import importlib
import logging

import pytest

from env_generator.llm_generator.multi_agent.runtime import path_routed_workspace as prw


@pytest.fixture(autouse=True)
def _reset_guard_state():
    prw._FW_OWNED_MAP_CACHE = None
    prw._FW_OWNED_WARNED = False
    yield
    prw._FW_OWNED_MAP_CACHE = None
    prw._FW_OWNED_WARNED = False


def _break_the_import(monkeypatch):
    real = importlib.import_module
    def boom(name, *a, **k):
        if name.endswith("auto_commit"):
            raise ImportError("simulated module-load cycle")
        return real(name, *a, **k)
    monkeypatch.setattr(importlib, "import_module", boom)
    # `from ..agents.runtime.auto_commit import _OWNERSHIP` goes through __import__, not
    # import_module — patch the builtin the statement actually uses.
    import builtins
    real_imp = builtins.__import__
    def boom2(name, *a, **k):
        if "auto_commit" in name:
            raise ImportError("simulated module-load cycle")
        return real_imp(name, *a, **k)
    monkeypatch.setattr(builtins, "__import__", boom2)


def test_the_guard_works_normally():
    """Non-vacuity: the map really does load, so the failure tests below mean something."""
    routes = prw._framework_owned_routes()
    assert routes, "the ownership map is empty even without a simulated failure"


def test_a_load_failure_is_announced(monkeypatch, caplog):
    _break_the_import(monkeypatch)
    with caplog.at_level(logging.WARNING):
        assert prw._framework_owned_routes() == []
    assert any("WRITE GUARD DEGRADED" in r.message for r in caplog.records), \
        "the guard turned off without saying so"


def test_the_warning_names_the_consequence(monkeypatch, caplog):
    """A log line that says only 'degraded' does not tell the reader the prompt is now lying."""
    _break_the_import(monkeypatch)
    with caplog.at_level(logging.WARNING):
        prw._framework_owned_routes()
    msg = " ".join(r.getMessage() for r in caplog.records)
    assert "NOT being denied" in msg
    assert "is false" in msg, "the prompt's claim being falsified is the point"


def test_the_warning_fires_once_not_per_write(monkeypatch, caplog):
    _break_the_import(monkeypatch)
    with caplog.at_level(logging.WARNING):
        for _ in range(5):
            prw._framework_owned_routes()
    assert sum("WRITE GUARD DEGRADED" in r.message for r in caplog.records) == 1


def test_the_failure_is_not_cached(monkeypatch):
    """The sticky half. A load-time miss must not disable the guard for the whole process."""
    _break_the_import(monkeypatch)
    assert prw._framework_owned_routes() == []
    assert prw._FW_OWNED_MAP_CACHE is None, "the failure was cached — the guard is off for good"
    monkeypatch.undo()
    assert prw._framework_owned_routes(), "it did not self-heal once the import worked again"


def test_success_is_still_cached(monkeypatch):
    """The cache exists to avoid a module-load cycle; #789 must not have removed that."""
    first = prw._framework_owned_routes()
    assert prw._FW_OWNED_MAP_CACHE is not None
    _break_the_import(monkeypatch)
    assert prw._framework_owned_routes() == first, "a cached success must not re-import"


def test_it_still_fails_OPEN(monkeypatch):
    """The trade is unchanged on purpose: a broken guard must never wedge every write."""
    _break_the_import(monkeypatch)
    assert prw._framework_owned_routes() == []          # empty, not an exception


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
