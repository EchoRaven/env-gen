r"""#709: a write was denied as FRAMEWORK-OWNED for a path the framework has never written.

Found by mining r147's own log by tool-failure class — `write` is the second-largest after chain
registration — and reading the denial reasons rather than the counts:

    Write denied: ['app/frontend/src/services/package.json'] are FRAMEWORK-OWNED files.
    The framework generates + overwrites them deterministically...

The framework generates `app/frontend/package.json`. It has never generated one under
`src/services/`. Across the 253 kept logs there are 1576 framework-owned write denials, and
**134 of them name a non-canonical path**:

    app/frontend/src/services/package.json   x98
    app/frontend/src/package.json            x32
    package.json                             x4

Ninety-eight retries on one path is what "here is a reason you cannot act on" looks like.

**The refusal is right; only the reason was wrong.** A Vite app has one manifest, and a nested
`package.json` would shadow it — denying that is correct. And the basename match behind it is
DELIBERATE: `path_routed_workspace._framework_owned_routes` mirrors the conflict resolver's
ownership map precisely so the write guard and the resolver cannot diverge. So the semantics are
untouched. What changes is that a shadowing-name denial now says it is a shadowing-name denial,
and says what to do instead. Same class as #682 and #690: the detection was fine, the text was
the cost.

Canonicality is inferred from the data that already exists — directly under the lane prefix
(`app/frontend/package.json`) versus nested deeper — rather than from a new accessor. My first
draft called a `framework_owned_paths()` that does not exist, which would have made the whole
branch dead: the exact defect class this session has spent its time finding.
"""
import inspect
import re

import pytest

from env_generator.llm_generator.multi_agent.runtime.path_routed_workspace import (
    _framework_owned_routes,
)
from env_generator.llm_generator.multi_agent.agents.runtime import tooling as tl


def _classify(rel: str) -> str:
    """Mirror of the production rule, exercised on the paths the corpus actually produced."""
    for prefix, bases in (_framework_owned_routes() or []):
        if not rel.startswith(prefix):
            continue
        tail = rel[len(prefix):]
        if tail in bases:
            return "canonical"
        if tail.rsplit("/", 1)[-1] in bases:
            return "shadowing"
        return "unowned"
    return "unowned"


# --- the rule, on the shapes the corpus produced -----------------------------------------------

@pytest.mark.parametrize("rel", [
    "app/frontend/src/services/package.json",   # x98 in the corpus
    "app/frontend/src/package.json",            # x32
])
def test_a_nested_manifest_is_a_shadowing_name(rel):
    assert _classify(rel) == "shadowing"


@pytest.mark.parametrize("rel", ["app/frontend/package.json", "app/backend/main.py"])
def test_the_canonical_path_keeps_the_original_verdict(rel):
    assert _classify(rel) == "canonical"


def test_a_lane_file_is_not_owned_at_all():
    assert _classify("app/frontend/src/pages/MyPage.jsx") == "unowned"


def test_the_ownership_map_is_non_empty():
    """If the map ever loads empty the rule is vacuous, so assert the premise."""
    assert _framework_owned_routes()


# --- the production branch says the right things --------------------------------------------------

def _block() -> str:
    src = inspect.getsource(tl)
    i = src.index("#709: SAY WHICH KIND OF DENIAL THIS IS")
    return src[i:src.index("Write denied: {fw_owned} are FRAMEWORK-OWNED", i)]


def _message() -> str:
    """The branch's message as ONE string.

    Asserting against the SOURCE splits every sentence at the f-string joins, so a phrase that
    spans two literals never matches — which is why two assertions here failed on a message that
    reads correctly. Same trap #694's first draft hit; fold the concatenation away first.
    """
    return re.sub(r'"\s*\n\s*f"', "", _block())


def test_it_denies_rather_than_allows():
    """The nested manifest is still refused — only the wording changes."""
    b = _block()
    assert "success=False" in b


def test_it_says_the_framework_does_not_generate_that_path():
    b = _message()
    assert "NOT because the framework generates that path" in b


def test_it_names_the_one_real_manifest():
    b = _message()
    assert "app/frontend/package.json" in b
    assert "ONE package.json" in b


def test_it_gives_an_action():
    b = _message()
    assert "add dependencies by registering the contract" in b
    assert "needs no manifest" in b


def test_it_marks_the_metadata_distinctly():
    b = _block()
    assert '"shadowing_name": True' in b
    assert '"framework_owned": False' in b


def test_the_canonical_message_is_still_reachable():
    src = inspect.getsource(tl)
    assert "are FRAMEWORK-OWNED files. The framework " in src


def test_the_branch_cannot_raise():
    b = _block()
    assert "except Exception:" in b
    assert "_canon_709 = []" in b


# --- provenance -------------------------------------------------------------------------------------

def test_the_measurement_is_recorded():
    b = " ".join(_block().replace("#", " ").split())
    assert "1576 framework-owned write denials" in b
    assert "134 name a path that is not the canonical one" in b
    assert "x98" in b


def test_the_deliberate_basename_match_is_recorded():
    b = " ".join(_block().replace("#", " ").split())
    assert "basename match is DELIBERATE" in b
    assert "mirrors the conflict resolver" in b


def test_my_dead_branch_near_miss_is_recorded():
    b = " ".join(_block().replace("#", " ").split())
    assert "does not exist, which" in b and "dead" in b


# --- ported from a duplicate file I wrote before noticing this one existed -------------------

def test_the_routes_helper_is_shaped_as_the_branch_assumes():
    """The branch's own comment records a first draft that called a function which did not
    exist; if the shape ever changes, the whole branch silently becomes dead code."""
    from env_generator.llm_generator.multi_agent.runtime.path_routed_workspace import (
        _framework_owned_routes,
    )
    routes = _framework_owned_routes()
    assert routes, "no routes: the #709 branch would never fire"
    for prefix, bases in routes:
        assert prefix.endswith("/")
        assert bases and all("/" not in b for b in bases), "bases must be BASENAMES"
    assert {"app/frontend/", "app/backend/"} <= {p for p, _ in routes}


@pytest.mark.parametrize("rel", [
    "app/frontend/src/package.json",            # r147, x2
    "app/frontend/src/services/package.json",   # r147, x2
])
def test_the_exact_paths_r147_denied_are_classified_as_shadowing(rel):
    assert _classify(rel) == "shadowing"


def test_the_shadowed_directory_really_is_lane_owned():
    """src/services/ is granted to the lane — which is precisely why the old denial was wrong."""
    from env_generator.llm_generator.multi_agent.agents.runtime.auto_commit import (
        _FRONTEND_LANE_OWNED_DIRS,
    )
    assert "src/services/" in _FRONTEND_LANE_OWNED_DIRS


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
