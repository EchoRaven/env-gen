"""#1202ka: the kickoff synthesizer read the meeting and the lanes wrote the registry.

`try_synthesize`'s own first line says it: "synthesize the contract from the meeting's
decisions". The lanes register endpoints, tables and pages into RegistryHub — the durable
record every later phase reads. When a lane does the work and never transcribes the decision,
the synthesis is empty, validation fails on "MUST be a non-empty list", and the run dies with
its contract sitting one file over.

Two runs died on it within an hour, both salvageable:

  * r113 aborted with `contract.endpoints`, `contract.data_model.tables` and `task_tree` all
    "MUST be a non-empty list" — while its RegistryHub held 15 endpoints, 4 tables, 9 ui_pages.
  * r112 aborted with `Missing=['backend']` while that lane was, in the same second, calling
    `registryhub_register_table` for live_streams / dm_conversations / direct_messages /
    notifications.

Three more runs in the corpus hit the same validation (googlemaps-r15, netflix-r43,
tiktok-r104); netflix-r43 survived it and delivered, which says the contract was fine and only
its transcription was missing.

Verified against r113's real ledger before shipping: the backfill produces 15/4/9 and, after
`_normalize_backend_endpoints_for_reconcile`, every endpoint satisfies the validator's shape
(non-empty `response_key`, bool `auth_required`).
"""
import sys
import pathlib

_AGENT = pathlib.Path(__file__).resolve().parents[1]
if str(_AGENT) not in sys.path:
    sys.path.insert(0, str(_AGENT))

import inspect                                                        # noqa: E402

from env_generator.llm_generator.multi_agent.runtime.kickoff import run_kickoff as RK  # noqa: E402

_F = RK._backfill_drafts_from_registry_1202ka


class _RH:
    def __init__(self, eps=None, tables=None, pages=None):
        self._e, self._t, self._p = eps or {}, tables or {}, pages or {}

    def get_endpoints(self):
        return self._e

    def list_tables(self):
        return self._t

    def list_ui_pages(self):
        return self._p


class _H:
    def __init__(self, rh):
        self.registryhub = rh


_EPS = {"e1": {"method": "get", "path": "/api/videos"},
        "e2": {"method": "POST", "path": "/api/videos/{id}/like",
               "schema": {"auth_required": True, "response_key": "like"}}}
_TABLES = {"t1": {"name": "videos", "schema": {"columns": [{"name": "id", "type": "text"}]}}}
_PAGES = {"p1": {"id": "feed", "name": "feed_page", "route": "/",
                 "apis_used": ["GET /api/videos"]}}


def test_an_empty_draft_takes_the_registry():
    """★ r113's shape: nothing in the meeting, everything in the hub."""
    out, notes = _F(_H(_RH(_EPS, _TABLES, _PAGES)), {"backend": {}, "frontend": {}})
    assert notes == ["endpoints<-registry:2", "tables<-registry:1", "ui_pages<-registry:1"]
    eps = out["backend"]["endpoints"]
    assert {e["path"] for e in eps} == {"/api/videos", "/api/videos/{id}/like"}
    assert eps[0]["method"] == "GET", "method is upper-cased for the validator"
    assert out["backend"]["data_model"]["tables"][0]["name"] == "videos"
    assert out["frontend"]["ui_pages"][0]["route"] == "/"


def test_a_stated_flag_travels_but_nothing_is_invented():
    """Minimal shapes on purpose — `_normalize_backend_endpoints_for_reconcile` fills the
    rest with the defaults it documents. Deriving them here would be a fourth reading."""
    out, _ = _F(_H(_RH(_EPS)), {"backend": {}, "frontend": {}})
    by_path = {e["path"]: e for e in out["backend"]["endpoints"]}
    assert by_path["/api/videos/{id}/like"]["auth_required"] is True
    assert by_path["/api/videos/{id}/like"]["response_key"] == "like"
    assert "auth_required" not in by_path["/api/videos"], (
        "an unstated flag must stay unstated here, so the normalizer's documented default "
        "applies rather than one invented in this function")


def test_a_written_draft_is_never_overridden():
    """★ It changes WHERE the synthesizer looks, not whose decision it honours."""
    drafts = {"backend": {"endpoints": [{"method": "GET", "path": "/api/mine"}]},
              "frontend": {"ui_pages": [{"id": "x", "name": "x"}]}}
    out, notes = _F(_H(_RH(_EPS, _TABLES, _PAGES)), drafts)
    assert out["backend"]["endpoints"] == [{"method": "GET", "path": "/api/mine"}]
    assert out["frontend"]["ui_pages"] == [{"id": "x", "name": "x"}]
    assert notes == ["tables<-registry:1"], "only the section that was empty"


def test_an_empty_registry_changes_nothing():
    drafts = {"backend": {}, "frontend": {}}
    out, notes = _F(_H(_RH()), drafts)
    assert notes == [] and out == drafts


def test_a_record_without_method_or_path_is_skipped():
    """A half-written registration must not become a contract row the validator rejects."""
    out, _ = _F(_H(_RH({"a": {"method": "GET"}, "b": {"path": "/api/x"},
                        "c": {"method": "GET", "path": "/api/ok"}})),
                {"backend": {}, "frontend": {}})
    assert [e["path"] for e in out["backend"]["endpoints"]] == ["/api/ok"]


def test_a_broken_registry_never_breaks_kickoff():
    class _Boom:
        def get_endpoints(self):
            raise RuntimeError("hub down")

    drafts = {"backend": {}}
    out, notes = _F(_H(_Boom()), drafts)
    assert out == drafts and notes == []


def test_it_runs_before_the_normalizer_on_the_reconcile_path():
    """★ Reachability: after the normalizer, the registry's rows would miss the shape
    defaults and fail the very validation this exists to clear."""
    src = inspect.getsource(RK.try_synthesize)
    # ORDERING: the LAST backfill call (the one inside the drafts pipeline) must still precede
    # the shape normalizer. #1202kp added an EARLIER call — the quorum-check probe — so anchor
    # on the last, not the first.
    i = src.rindex("_backfill_drafts_from_registry_1202ka(")
    j = src.index("_normalize_backend_endpoints_for_reconcile(")
    assert i < j, "the backfill must precede the shape normalizer"

    # RECONCILE-ONLY, checked per call site rather than by looking for the literal
    # `if reconcile:` before the first one — #1202kp's probe is guarded by
    # `if missing and reconcile:`, which is equally reconcile-only and broke the old
    # substring form. Every call site must sit under a guard that reads `reconcile`.
    import ast as _ast
    import textwrap as _tw
    tree = _ast.parse(_tw.dedent(src))
    sites = [n for n in _ast.walk(tree)
             if isinstance(n, _ast.Call) and isinstance(n.func, _ast.Name)
             and n.func.id == "_backfill_drafts_from_registry_1202ka"]
    assert sites, "the backfill is no longer called at all"
    guarded = 0
    for node in _ast.walk(tree):
        if not isinstance(node, _ast.If):
            continue
        body = _ast.dump(_ast.Module(body=node.body, type_ignores=[]))
        if "_backfill_drafts_from_registry_1202ka" not in body:
            continue
        if "reconcile" in {n.id for n in _ast.walk(node.test) if isinstance(n, _ast.Name)}:
            guarded += 1
    assert guarded >= len(sites), (
        f"{len(sites)} call site(s) but only {guarded} guarded by `reconcile` — the happy "
        "path must still require the meeting")
