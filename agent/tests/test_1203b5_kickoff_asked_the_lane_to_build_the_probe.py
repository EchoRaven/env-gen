r"""#1203b5: kickoff must not ask a lane to IMPLEMENT the framework's own probe.

`registryhub._infra_kind_for_probe` tags a `__`-prefixed registration `kind="infra"` so that
"the exemption they already implement start[s] working, and any gate added later inherits it".
This generator is a later consumer and did not inherit it: it walked `contract["endpoints"]`
and emitted `impl.endpoint.<m>.<p>` plus `validate.api_smoke.<m>.<p>` for every (method, path),
probes included.

r144 is the loop in its own task ledger:

    orchestrator → backend   impl.endpoint.get.__noop_orchestrator_probe        [completed]
    orchestrator → verifier  validate.api_smoke.get.__noop_orchestrator_probe  [completed]

the lane built it, `deliverability_parked_probe_route` blocked delivery, and the orchestrator
then filed EIGHT more P0s to have it deleted — "P0 follow-up: noop probe still detected by
deliverability gate" — one still in_progress at 80 minutes. That blocker's prose guesses "if a
CHECK pushed you to add it"; it was a task carrying the framework's own name.

IT IS KICKOFF, CONFIRMED BY TIMESTAMP: all FIFTEEN of r144's `impl.endpoint.*` tasks were
created inside a 2-second window (1790976954), one shot, with the probe's among them — and that
is 96 minutes BEFORE the lane last touched the probe's registry entry (1790982746). The registry
record reads `_updated_by: backend`, which is the LAST writer, not the first; the probe was in
the contract kickoff synthesised from. `_munge_path('/__noop_orchestrator_probe__')` yields
exactly the observed id, `impl.endpoint.get.__noop_orchestrator_probe` — checked, because the
double underscore looked at first like it could not have come from a `.replace("__", "_")`.

MEASURED: 11 of 183 runs carry such tasks (39 in total: r144, r122 4, r123 5, r125 6, r126 4,
googlemaps-r16 4). The predicate selects 100 of the corpus's 5119 registered endpoints (1.95%)
across 65 runs, 34 distinct paths, every one a probe.

★ THE FIRST DRAFT ALSO SKIPPED `kind in (infra, control)` and would have skipped 1085 of 5119
(21%) — `/api/v1/tenants` (328), `/api/v1/admin/init-tenant` (165), `/health` (164),
`/api/v1/reset` (164) — the CONTROL PLANE, which lanes must implement, and which r144 is
separately blocked on (`init-tenant returns 404`). Those tests are below, because that
regression is the one this ticket could most easily have caused.
"""
import os
import sys

_AGENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_AGENT, "env_generator", "llm_generator"))

import multi_agent.runtime.kickoff.schema_tolerance as ST  # noqa: E402


def _gen(endpoints):
    """The kickoff task ids for this contract.

    Named directly rather than discovered by introspection: `synthesize_task_tree` is the one
    writer of `impl.endpoint.*`, and a test that went looking for "some function taking a
    contract" would silently start testing a different one.

    NOTE: the generator emits TWO tasks per surviving endpoint -- `impl.endpoint.<m>.<p>` for
    the owning lane and `validate.api_smoke.<m>.<p>` for the verifier -- so these tests assert
    on WHICH endpoints are represented, never on a row count. (My first draft counted rows and
    went red at 2-vs-1 on a patch that was working.)
    """
    out = ST.synthesize_task_tree({"endpoints": endpoints, "tables": []})
    tasks = out.get("tasks") if isinstance(out, dict) else out
    return [str(t.get("id") or t.get("title") or "")
            for t in (tasks or []) if isinstance(t, dict)]


def _impl(endpoints):
    """Just the implementation tasks, one per surviving endpoint."""
    return [i for i in _gen(endpoints) if i.startswith("impl.endpoint.")]


def _ep(path, method="GET", **kw):
    d = {"method": method, "path": path, "status": "defined"}
    d.update(kw)
    return d


def test_the_probe_gets_no_task():
    """★ The exact endpoint r144 was told to build."""
    ids = _gen([_ep("/__noop_orchestrator_probe__"), _ep("/api/videos")])
    assert not [i for i in ids if "noop" in i], ids
    assert [i for i in ids if "videos" in i], ids
    assert len(ids) == 2, "the surviving endpoint should get impl + validate: %s" % ids


def test_every_probe_spelling_in_the_corpus_is_covered():
    """34 distinct paths, all `__`-leading; a few of the real ones."""
    paths = ["/__noop__", "/__list__", "/__orchestrator_probe__",
             "/__probe_read_only_orchestrator_state__",
             "/__noop_orchestrator_state_check__"]
    ids = _impl([_ep(p) for p in paths] + [_ep("/api/feed")])
    assert ids == ["impl.endpoint.get._api_feed"], "a probe still produced a task: %s" % ids


def test_the_control_plane_still_gets_its_tasks():
    """★ THE REGRESSION THIS NEARLY CAUSED. `kind="control"` is exempted by the gates that ask
    "is this business surface?" — never by "should this be built?". r144 is blocked on
    `POST /api/v1/admin/init-tenant returns 404`, so a lane that is never told to build it
    cannot ever unblock the run."""
    eps = [_ep("/api/v1/tenants", "POST", kind="control"),
           _ep("/api/v1/admin/init-tenant", "POST", kind="control"),
           _ep("/api/v1/reset", "POST", kind="control"),
           _ep("/api/v1/tenants/{tenant_id}", "GET", kind="control")]
    ids = _impl(eps)
    assert len(ids) == 4, "%d of 4 control-plane endpoints survived: %s" % (len(ids), ids)
    for frag in ("tenants", "init", "reset"):
        assert any(frag in i for i in ids), "%r lost its impl task: %s" % (frag, ids)


def test_health_still_gets_its_task():
    """`/health` carries `kind="infra"` in 164 corpus records and is a real endpoint."""
    ids = _impl([_ep("/health", kind="infra")])
    assert len(ids) == 1 and "health" in ids[0], ids


def test_app_surface_under_a_dunder_is_left_alone():
    """The framework's own carve-out, quoted in registryhub's tagger: the convention is a
    LEADING `__` segment, so `/api/__x` is app surface."""
    ids = _impl([_ep("/api/__internal/stats")])
    assert len(ids) == 1, "an app path with a non-leading `__` was skipped: %s" % ids


def test_the_predicate_is_only_the_leading_segment():
    """Stated directly on the predicate so a later edit cannot quietly widen it back to
    `kind`, which is what the 21% draft did."""
    f = ST._is_framework_probe_1203b5
    assert f("/__noop__") is True
    assert f("/api/__x") is False
    assert f("/api/v1/admin/init-tenant") is False
    assert f("/health") is False


def test_a_malformed_path_is_not_a_probe():
    f = ST._is_framework_probe_1203b5
    for bad in (None, "", 123, [], {}):
        assert f(bad) is False, bad


def test_the_skip_happens_before_dedup_and_linking():
    """★ Position matters, not just presence: the loop it guards also builds `seen_keys` and
    the endpoint->table links, so skipping later would leave a probe in the DAG while removing
    only its task. Pinned with AST rather than a line number (#943)."""
    import ast
    import inspect

    src = inspect.getsource(ST)
    tree = ast.parse(src)
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
             and getattr(n.func, "id", "") == "_is_framework_probe_1203b5"]
    # one in the generator (the definition's own body does not call itself)
    assert len(calls) == 1, "called %d time(s)" % len(calls)
    # it is inside a `for ... in endpoints_raw` loop, and a `continue` follows it
    loops = [n for n in ast.walk(tree) if isinstance(n, ast.For)
             and any(c is calls[0] for c in ast.walk(n))
             and getattr(n.iter, "id", "") == "endpoints_raw"]
    assert loops, "the skip is not inside the endpoints_raw loop"
    guard = [n for n in ast.walk(loops[0]) if isinstance(n, ast.If)
             and any(c is calls[0] for c in ast.walk(n.test))]
    assert guard and any(isinstance(b, ast.Continue) for b in guard[0].body), \
        "the probe is detected and then not skipped"
    # and `seen_keys[key] = ...` comes AFTER it in the same loop
    assigns = [n for n in ast.walk(loops[0]) if isinstance(n, ast.Subscript)
               and getattr(n.value, "id", "") == "seen_keys"]
    assert assigns, "seen_keys is no longer built in this loop"
    assert min(a.lineno for a in assigns) > guard[0].lineno, \
        "the endpoint enters seen_keys before the probe check"
