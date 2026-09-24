r"""#1202dg: #1202aw silenced one of the two refusal sites.

#1202aw removed r32's 71 warnings about `.openenv_trash/` — the framework's own trash can,
created by `file_tools`' delete path and already in the generated project's .gitignore. It
added `FRAMEWORK_SCRATCH_DOTDIRS_1202AW` and consulted it in `auto_commit._should_stage_path`.

netflix-r42 then logged 81 of these:

    codehub.commit refused dotfile paths for agent backend: ['.openenv_trash/']
    codehub.commit refused dotfile paths for agent frontend: ['.openenv_trash/']

`codehub.service.commit` refuses the same paths through the same filter and logs its own
warning, and it never consulted the suppression list — `FRAMEWORK_SCRATCH_DOTDIRS_1202AW`
had exactly ONE consumer in the whole repo, the module that defines it. The mechanism was
built and only half wired, which is this codebase's most expensive recurring mistake.

The distinction #1202aw drew is the one that matters and is preserved here: the trash is
still REFUSED, just not announced, while a dotfile an AGENT authored (`.gates/`, `.secrets/`)
is a real finding and keeps its warning. Silence must not become permission.
"""
import re
import sys
from pathlib import Path

import pytest

THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS_DIR.parent / "env_generator" / "llm_generator"))

from multi_agent.runtime.hubs.codehub import service as svc  # noqa: E402
from multi_agent.agents.runtime.auto_commit import (  # noqa: E402
    _filter_paths_for_staging,
)


def test_framework_scratch_is_not_worth_announcing():
    assert svc._noteworthy_dropped_1202dg([".openenv_trash/"]) == []
    assert svc._noteworthy_dropped_1202dg([".openenv_trash/old.jsx"]) == []
    assert svc._noteworthy_dropped_1202dg(["app/.openenv_trash/x/y.py"]) == []


def test_an_agent_authored_dotfile_is_still_reported():
    """The finding the guard exists for survives."""
    assert svc._noteworthy_dropped_1202dg([".gates/secret.json"]) == [".gates/secret.json"]


def test_a_mixed_batch_reports_only_the_actionable_half():
    got = svc._noteworthy_dropped_1202dg([".openenv_trash/old.jsx", ".secrets/k.pem"])
    assert got == [".secrets/k.pem"]


def test_silence_did_not_become_permission():
    """The trash must still be refused staging — this is the #1202aw invariant."""
    assert _filter_paths_for_staging([".openenv_trash/old.jsx"], agent_id="frontend") == []
    assert _filter_paths_for_staging(["app/main.py"], agent_id="backend") == ["app/main.py"]


def test_both_commit_refusal_sites_consult_it():
    """Two log sites shared the bug; fixing one and not the other is how it got here.

    Landmark-anchored, not a byte window: the check must keep covering these sites as the
    file moves.
    """
    import inspect

    src = inspect.getsource(svc)
    warn_sites = [m.start() for m in re.finditer(
        r'"codehub\.commit refused dotfile paths for agent', src)]
    assert len(warn_sites) == 2, (
        "expected the two known commit refusal sites, found %d" % len(warn_sites))

    for pos in warn_sites:
        # anchor on the `dropped = ` assignment that feeds this site, not a byte count
        window_start = src.rfind("dropped = ", 0, pos)
        assert window_start != -1
        preceding = src[window_start:pos]
        assert "_noteworthy_dropped_1202dg" in preceding, (
            "a commit refusal site still announces the framework's own trash")


# --- #1202dy: the other half of auto_commit's silent-refusal set --------------------------
#
# `_should_stage_path` refuses TWO kinds without a word: the framework's scratch dirs, and
# Python's build artifacts — "``__pycache__/*.pyc`` files cause 'Cannot merge binary files'
# conflicts ... These are build artifacts, never source — refuse them unconditionally."
#
# #1202dg mirrored only the first half into codehub, so netflix-r45 logged four of:
#
#     codehub.commit refused dotfile paths for agent backend: ['app/backend/__pycache__/']
#
# calling a compiler artifact a "dotfile path" and reporting it as if a reader could act.
# Nobody authored it and nobody can remove it; it is regenerated on the next import.

def test_pycache_is_not_worth_announcing():
    assert svc._noteworthy_dropped_1202dg(["app/backend/__pycache__/"]) == []
    assert svc._noteworthy_dropped_1202dg(["app/backend/__pycache__/main.cpython-311.pyc"]) == []


@pytest.mark.parametrize("p", ["app/x.pyc", "app/x.pyo", "app/x.pyd"])
def test_compiled_artifacts_are_not_worth_announcing(p):
    assert svc._noteworthy_dropped_1202dg([p]) == []


def test_an_agent_dotfile_still_survives_the_wider_filter():
    got = svc._noteworthy_dropped_1202dg(
        ["app/backend/__pycache__/x.pyc", ".openenv_trash/y.jsx", ".secrets/k.pem"])
    assert got == [".secrets/k.pem"]


def test_ordinary_python_source_is_untouched():
    assert svc._noteworthy_dropped_1202dg(["app/backend/main.py"]) == ["app/backend/main.py"]
