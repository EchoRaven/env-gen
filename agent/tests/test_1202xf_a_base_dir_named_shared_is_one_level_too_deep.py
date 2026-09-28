"""#1202xf: the doubled hub store guard only covered the case that was never dangerous.

`HubRegistry(base)` resolves its store with `_resolve_hub_dir`, which appends `shared/hubs`.
So `HubRegistry("<run>/shared")` -- one level too deep -- resolves to `<run>/shared/shared/hubs`:
a store nothing else writes to, which every gate then reads as "nothing registered, nothing
wrong". #1202wf warned about exactly that and #1202wq redirected... but only when
`<base>/hubs` already existed AND `<base>/shared/hubs` did not.

That is the one case where the data was there to find. The two it missed both end in the
silent empty registry the warning describes:

    fresh run   nothing exists yet          -> created `<run>/shared/shared/hubs`
    both exist  a run already contaminated  -> kept writing to the doubled copy

`base_dir.name == "shared"` settles both without probing anything: the argument is meant to be
the RUN directory, whose child is `shared`, so a base_dir literally named `shared` is the
caller having gone one level too deep.

MEASURED on the corpus: 176 of 178 run directories carry a `shared/shared`. 88 hold files from
runs between 2026-08-24 and 2026-09-07; the other 88 are from this session's own tooling,
7,220 files, every one a duplicate of a file already in that run's real `shared/hubs` (checked
file by file -- zero had no counterpart). Nothing after 2026-09-07 produced one from a run,
which is why this reads as a latent hazard rather than an active loss.
"""
import logging
import shutil
import sys
import os

import pytest

_AGENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_AGENT, "env_generator", "llm_generator"))

from multi_agent.runtime.hub_registry import HubRegistry  # noqa: E402


def _run_dir(tmp_path, prep):
    run = tmp_path / "run"
    (run / "shared" / "hubs").mkdir(parents=True)
    if prep == "both":
        (run / "shared" / "shared" / "hubs").mkdir(parents=True)
    if prep == "fresh":
        shutil.rmtree(run / "shared" / "hubs")
        (run / "shared").mkdir(parents=True, exist_ok=True)
    return run


@pytest.mark.parametrize("prep", ["real", "both", "fresh"])
def test_a_shared_base_dir_resolves_to_the_real_store(tmp_path, prep):
    """★ All three, not just the one the data was already in."""
    run = _run_dir(tmp_path, prep)
    reg = HubRegistry(str(run / "shared"))
    assert reg._store_dir == run / "shared" / "hubs", (
        "%s: store resolved to %s" % (prep, reg._store_dir))


def test_the_fresh_run_no_longer_creates_the_doubled_directory(tmp_path):
    """The dangerous one: nothing exists, so nothing can be probed, and the empty store it
    would have made is the one every gate misreads as clean."""
    run = _run_dir(tmp_path, "fresh")
    HubRegistry(str(run / "shared"))
    assert not (run / "shared" / "shared" / "hubs").exists(), (
        "the doubled store was created on a fresh run")


def test_the_correct_call_is_untouched(tmp_path):
    """★ The guard must not move the store for callers that were already right."""
    run = tmp_path / "run"
    run.mkdir()
    reg = HubRegistry(str(run))
    assert reg._store_dir == run / "shared" / "hubs", reg._store_dir
    assert not (run / "shared" / "shared").exists()


def test_a_run_directory_that_happens_to_end_in_shared_is_still_redirected(tmp_path):
    """Deliberate: the name is the whole signal, so a run dir named `shared` is redirected
    too. That is the safe direction -- it reads the store a correct caller would have used,
    and the alternative is a silent empty registry."""
    run = tmp_path / "shared"
    run.mkdir()
    reg = HubRegistry(str(run))
    assert reg._store_dir == run / "hubs", reg._store_dir


def test_it_says_so(tmp_path, caplog):
    """#575/#1202qb convention: never a silent redirect."""
    run = _run_dir(tmp_path, "fresh")
    with caplog.at_level(logging.WARNING):
        HubRegistry(str(run / "shared"))
    assert any("1202xf" in r.message or "1202xf" in str(r.msg) for r in caplog.records), (
        "the redirect happened without saying so: %r" % [r.message for r in caplog.records])


def test_a_probe_failure_cannot_stop_a_run_from_starting(tmp_path):
    """The original guard wrapped its probe in try/except for this reason; keep it true."""
    run = tmp_path / "run"
    run.mkdir()
    reg = HubRegistry(str(run))
    assert reg._store_dir.is_dir()
