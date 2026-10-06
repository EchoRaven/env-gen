"""#1203fy — the IMPLEMENTATION PROGRESS nudge's framework-endpoint exemption never fired.

`_build_endpoint_impl_directive` skips endpoints whose kind is on the fixed surface:

    if (ep.get("kind") or "").lower() in ("infra", "auth", "spine", "control", "system"):

`registryhub._tag_parked_probe_1202dw` writes that tag to `metadata["kind"]`, and its own
docstring says so: "Every one of those gates ALREADY exempts `metadata.kind` in
FIXED_ENDPOINT_KINDS". Counted over every run directory: of 5747 registered endpoints, a
TOP-LEVEL `kind` appears ZERO times, while 2696 carry `metadata.kind` (oauth 1104, infra 892,
auth 368, control 293, business 39). The skip was structurally dead.

The nudge is not advisory -- "you CANNOT finish until they do", "ACTION THIS STEP: ... WRITE
its FastAPI route handler with real DB logic" -- so the lane writes the framework's own probe
and `deliverability_parked_probe_route` then blocks delivery on it. #1203b5 named that loop and
closed the task-generator half; this emitter kept it open. r164's backend notebook, verbatim:
"Implementation progress prompt suggested adding __noop handlers, but current delivery-blocking
WorkHub task explicitly requires deleting/deregistering them".

Replayed over the 203 runs with a backend on disk: 106 endpoints listed before, 30 after
(-76 across 26 runs); 10 of the 106 were parked `__` probes across nine runs including r163 and
r164, and after the fix, zero.
"""
import inspect
from pathlib import Path

import pytest

from env_generator.llm_generator.multi_agent.agents.runtime.step_pipeline.action import (
    AgentActionStageMixin)
from env_generator.llm_generator.multi_agent.runtime import deliverability as dlv
from env_generator.llm_generator.multi_agent.runtime.kickoff.contract import (
    FIXED_ENDPOINT_KINDS)
from env_generator.llm_generator.multi_agent.runtime.lifecycle import endpoint_kind


class _Registry:
    def __init__(self, eps):
        self._eps = eps

    def get_endpoints(self):
        return self._eps


class _Hubs:
    def __init__(self, eps):
        self.registryhub = _Registry(eps)


class _Logger:
    def __init__(self):
        self.warnings = []

    def warning(self, *a, **k):
        self.warnings.append(a)


class _Agent(AgentActionStageMixin):
    """Only the agent's surroundings are stood in for; the real method runs."""

    def __init__(self, eps, worktree):
        self._hubs = _Hubs(eps)
        self._config_key = "backend"
        self._worktree_dir = str(worktree)
        self._logger = _Logger()
        self._impl_dir_diag_logged = True   # skip the FIX#24 one-shot diagnostic


def _ep(path, *, method="GET", kind=None, top_kind=None, provider="backend", status="defined"):
    rec = {"method": method, "path": path, "provider": provider, "status": status}
    if kind is not None:
        rec["metadata"] = {"kind": kind}
    if top_kind is not None:
        rec["kind"] = top_kind
    return rec


@pytest.fixture
def worktree(tmp_path):
    """A lane source tree that serves exactly one business route."""
    be = tmp_path / "app" / "backend"
    be.mkdir(parents=True)
    (be / "custom_routes.py").write_text(
        'from fastapi import APIRouter\n'
        'router = APIRouter()\n'
        '@router.get("/api/videos")\n'
        'def videos():\n'
        '    return []\n', encoding="utf-8")
    return tmp_path


# ------------------------------------------------- the defect, through the real caller

def test_a_parked_probe_is_no_longer_listed_as_work(worktree):
    """r164's shape: the probe is registered, tagged infra under metadata, and has no code."""
    agent = _Agent({"GET /__noop__": _ep("/__noop__", kind="infra"),
                    "GET /api/videos": _ep("/api/videos")}, worktree)
    out = agent._build_endpoint_impl_directive()
    assert out is None, out


def test_the_probe_was_listed_before_the_fix(worktree):
    """The counter-control: with the tag where the OLD code looked for it, the exemption
    fired -- which is why the defect was invisible in reproduction but live in every run."""
    old_shape = _ep("/__noop__", top_kind="infra")
    assert (old_shape.get("kind") or "").lower() == "infra"      # old predicate: skipped
    new_shape = _ep("/__noop__", kind="infra")
    assert (new_shape.get("kind") or "").lower() == ""           # old predicate: NOT skipped
    assert endpoint_kind(new_shape) == "infra"                   # new predicate: skipped
    agent = _Agent({"GET /__noop__": new_shape}, worktree)
    assert agent._build_endpoint_impl_directive() is None


@pytest.mark.parametrize("kind", sorted(FIXED_ENDPOINT_KINDS))
def test_every_fixed_kind_under_metadata_is_exempt(kind, worktree):
    agent = _Agent({"X": _ep("/framework/thing/%s" % kind, kind=kind)}, worktree)
    assert agent._build_endpoint_impl_directive() is None, kind


def test_a_real_business_endpoint_is_still_demanded(worktree):
    """The fix must not silence the nudge: this is the gaming loophole it exists to close."""
    agent = _Agent({"GET /api/comments": _ep("/api/comments"),
                    "GET /api/videos": _ep("/api/videos")}, worktree)
    out = agent._build_endpoint_impl_directive()
    assert out is not None
    assert "/api/comments" in out
    assert "1/2 of your business endpoints" in out


def test_a_business_tagged_probe_is_still_caught_by_the_path_guard(worktree):
    """`_tag_parked_probe_1202dw`: "A caller that states its own kind keeps it" -- so a probe
    registered as `kind="business"` carries no exemption, and only the path net stops it.
    0 such registrations exist today; this is the defence in depth."""
    agent = _Agent({"GET /__noop__": _ep("/__noop__", kind="business")}, worktree)
    assert agent._build_endpoint_impl_directive() is None


def test_api_prefixed_double_underscore_is_app_surface_not_machinery(worktree):
    """The framework's own convention, quoted from the tagger: a LEADING `__` segment is
    machinery, `/api/__x` is app surface and is left alone. The guard must not over-reach."""
    agent = _Agent({"GET /api/__x": _ep("/api/__x")}, worktree)
    out = agent._build_endpoint_impl_directive()
    assert out is not None and "/api/__x" in out


def test_the_framework_auth_signup_is_not_the_lanes_work(worktree):
    """Two of the 106 were `POST /auth/signup`, which #1203fw made the framework serve."""
    agent = _Agent({"POST /auth/signup": _ep("/auth/signup", method="POST")}, worktree)
    assert agent._build_endpoint_impl_directive() is None


def test_another_lanes_endpoint_is_untouched(worktree):
    agent = _Agent({"GET /api/pages": _ep("/api/pages", provider="frontend")}, worktree)
    assert agent._build_endpoint_impl_directive() is None


# ----------------------------------------------------------------- structure, not substring

def test_the_nudge_consults_the_one_predicate_not_a_fourth_copy():
    """`lifecycle` says why: "Six modules re-listed this surface and all six omitted the same
    three. Imported, not re-listed." Anchored on the method's source, over the AST."""
    import ast
    src = inspect.getsource(AgentActionStageMixin._build_endpoint_impl_directive)
    tree = ast.parse(src.lstrip())
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    assert "_isb1203fy" in names, "the method must call lifecycle.is_business"
    imported = {a.asname or a.name
                for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) for a in n.names}
    assert "_isb1203fy" in imported and "_ek1203fy" in imported
    # and it must NOT carry its own copy of the fixed-surface list any more
    strs = {n.value for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str)}
    assert not {"infra", "auth", "spine", "control"} <= strs, (
        "the hand-written kind list is back")


def test_the_second_reader_was_fixed_too():
    """#1203fy's other half: `deliverability` read the same wrong key with a third copy of the
    list. Fixing one reader of a fact and not the other is worse than fixing neither."""
    src = inspect.getsource(dlv)
    i = src.index("def _no_page_declares_an_api_1202rm")
    body = src[i:src.index("\ndef ", i + 1)]
    assert '_e.get("kind")' not in body, "the top-level-only read is back"
    assert "_endpoint_kind_1203fy(_e) in _FIXED_ENDPOINT_KINDS_1203FY" in body


def test_the_second_readers_kind_set_is_the_canonical_one():
    assert dlv._FIXED_ENDPOINT_KINDS_1203FY == FIXED_ENDPOINT_KINDS
    assert "oauth" in dlv._FIXED_ENDPOINT_KINDS_1203FY, (
        "the hand-written copy omitted nothing here, but the canonical set is the point")


@pytest.mark.parametrize("rec,expected", [
    ({"metadata": {"kind": "infra"}}, "infra"),
    ({"kind": "OAuth"}, "oauth"),
    ({"kind": "auth", "metadata": {"kind": "infra"}}, "auth"),
    ({}, ""), (None, ""), ("not a dict", ""),
    ({"metadata": None}, ""), ({"metadata": "junk"}, ""),
])
def test_the_second_readers_kind_helper_reads_either_shape(rec, expected):
    assert dlv._endpoint_kind_1203fy(rec) == expected


def test_the_comments_name_a_function_that_exists():
    """#1203b5 (and this ticket, copying it) named a `registryhub` tagger that has ZERO
    definitions in the tree. The real one is `_tag_parked_probe_1202dw`. A comment that sends
    the next reader to a name that does not exist is the same trap as grepping the literal
    instead of the constant, so the name is pinned rather than trusted.

    The needle is assembled from fragments on purpose: spelled out, THIS FILE would be its own
    first hit, which is the self-pollution that makes a sweep read as a finding."""
    from pathlib import Path as _P
    from env_generator.llm_generator.multi_agent.runtime import registryhub as rh
    assert callable(getattr(rh, "_tag_parked_probe_1202dw", None))
    needle = "_infra" + "_kind_for" + "_probe"
    root = _P(rh.__file__).parents[4]
    offenders = []
    for py in root.rglob("*.py"):
        if "__pycache__" in str(py):
            continue
        try:
            if needle in py.read_text(encoding="utf-8", errors="ignore"):
                offenders.append(str(py.relative_to(root)))
        except OSError:
            continue
    assert offenders == [], "these name a tagger that does not exist: %s" % offenders


def test_the_corpus_shape_is_the_one_the_fix_reads():
    """The whole defect in one assertion: a registration that went through
    `_tag_parked_probe_1202dw` has NO top-level kind, which is the shape on disk."""
    from env_generator.llm_generator.multi_agent.runtime.registryhub import (
        _tag_parked_probe_1202dw)
    md = _tag_parked_probe_1202dw("/__noop__", None)
    assert md == {"kind": "infra"}
    rec = {"method": "GET", "path": "/__noop__", "metadata": md}
    assert rec.get("kind") is None, "the tagger does not write a top-level kind"
    assert endpoint_kind(rec) == "infra"
