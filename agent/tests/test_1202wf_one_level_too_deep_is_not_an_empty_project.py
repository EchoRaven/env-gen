"""#1202wf: a HubRegistry pointed one level too deep must say so.

`_resolve_hub_dir` appends `shared/hubs` to whatever it is given, and the constructor then
creates that directory and lets every hub write its empty default into it. So a caller who
hands over the RUN's `shared/` directory -- one level too deep -- gets `shared/shared/hubs`:
a complete, valid-looking, entirely EMPTY registry. `list_ui_pages()` returns {} and every
gate reading it concludes that nothing is registered and therefore nothing is wrong. That is
#883's failure mode at the largest scale this system has, and it is silent.

It is not hypothetical: the corpus carries 83 `shared/shared` directories dated before this
ticket. I made the same mistake while probing, which is how it was found -- and it silently
invalidated an offline reading of `ui_page_unwired` before I noticed the registry was empty
rather than the pages clean.

The tell is exact, not heuristic: `<base>/hubs` existing means the caller passed the `shared`
directory itself. A run root never has a `hubs` child, so a correct call cannot trip it, and a
brand-new run, where neither path exists, cannot either.
"""
import logging
import os
import sys

_AGENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_AGENT, "env_generator", "llm_generator"))

from multi_agent.runtime.hub_registry import HubRegistry  # noqa: E402


def _warnings(caplog):
    return [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]


def test_the_shared_directory_itself_is_announced(tmp_path, caplog):
    run = tmp_path / "some-run"
    (run / "shared" / "hubs").mkdir(parents=True)
    with caplog.at_level(logging.WARNING):
        HubRegistry(run / "shared")
    hits = [m for m in _warnings(caplog) if "#1202wf" in m]
    assert hits, (
        "pointing at `shared` creates shared/shared/hubs and every gate then reads an empty "
        "registry as a clean one; that must not be silent. warnings=%r" % _warnings(caplog))
    assert "one level too deep" in hits[0]


def test_the_run_directory_is_silent(tmp_path, caplog):
    run = tmp_path / "some-run"
    (run / "shared" / "hubs").mkdir(parents=True)
    with caplog.at_level(logging.WARNING):
        HubRegistry(run)
    assert not [m for m in _warnings(caplog) if "#1202wf" in m], (
        "the correct call must not warn: %r" % _warnings(caplog))


def test_a_brand_new_run_is_silent(tmp_path, caplog):
    """Neither path exists yet, which is the ordinary first construction."""
    run = tmp_path / "fresh-run"
    run.mkdir()
    with caplog.at_level(logging.WARNING):
        HubRegistry(run)
    assert not [m for m in _warnings(caplog) if "#1202wf" in m], _warnings(caplog)


def test_it_does_not_fire_when_both_paths_exist(tmp_path, caplog):
    """A `hubs` child AND a `shared/hubs` child: ambiguous, so say nothing rather than guess."""
    run = tmp_path / "odd-run"
    (run / "hubs").mkdir(parents=True)
    (run / "shared" / "hubs").mkdir(parents=True)
    with caplog.at_level(logging.WARNING):
        HubRegistry(run)
    assert not [m for m in _warnings(caplog) if "#1202wf" in m], _warnings(caplog)


def test_the_registry_still_works_after_warning(tmp_path, caplog):
    """The probe reports; it must never be the reason a run cannot start."""
    run = tmp_path / "some-run"
    (run / "shared" / "hubs").mkdir(parents=True)
    with caplog.at_level(logging.WARNING):
        reg = HubRegistry(run / "shared")
    assert reg.registryhub is not None
