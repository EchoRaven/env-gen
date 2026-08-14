"""The CONTRACT REGISTRY hub ("registryhub"; historical name: RegistryHub).

Registers and lifecycles every contract surface of a generated app: API
endpoints, database tables, consumers (incl. pending intents), contract
tests, examples, breaking changes — and the MCP registry rides alongside.
Renamed from APIHub on 2026-06-11 (user decision, full sweep — tool names,
store filenames, events all use the ``registryhub`` prefix; no back-compat).
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from .eventhub import EventHub
from .json_store import JsonStore

if TYPE_CHECKING:                       # annotation-only: no runtime import, no cycle
    # `RegistryHub.__init__` annotates `workhub: "WorkHub | None"`, but the name was never
    # brought into this module — `EventHub` beside it resolves only because it is imported for
    # real above. The annotation was unresolvable to any reader and to the type checker.
    #
    # Scope, honestly: this does NOT make `typing.get_type_hints(RegistryHub.__init__)` work.
    # The module carries `from __future__ import annotations`, so hints are strings evaluated
    # against runtime globals, where a TYPE_CHECKING name does not exist. That call still
    # raises NameError — and nothing reaches it: nothing in this repo calls get_type_hints, and
    # RegistryHub is neither a pydantic model nor a FastAPI dependency. A real import would fix
    # that too (verified: no cycle — workhub never references registryhub), but paying
    # import-time coupling for a path nobody walks is the wrong trade.
    from .workhub import WorkHub


def _schema_subset_check(expected: dict, actual: dict, path: str = "") -> "dict | None":
    """Return None if `expected` is a structural+type subset of `actual`.
    Otherwise return {"missing": [dotted_paths], "type_mismatches": [dotted_paths]}.

    Pure dict comparison. No jsonschema dependency. Allows `actual` to have
    additional keys (additive endpoints OK).
    """
    if not isinstance(expected, dict) or not isinstance(actual, dict):
        return None  # non-dict — skip; only dict shapes are validated
    missing: list = []
    type_mismatches: list = []
    for key, expected_val in expected.items():
        dotted = f"{path}.{key}" if path else key
        if key not in actual:
            missing.append(dotted)
            continue
        actual_val = actual[key]
        if isinstance(expected_val, dict) and isinstance(actual_val, dict):
            sub = _schema_subset_check(expected_val, actual_val, path=dotted)
            if sub is not None:
                missing.extend(sub["missing"])
                type_mismatches.extend(sub["type_mismatches"])
        elif expected_val != actual_val:
            type_mismatches.append(dotted)
    if missing or type_mismatches:
        return {"missing": missing, "type_mismatches": type_mismatches}
    return None


_NOT_FOUND_OR_DENIED = frozenset({401, 403, 404, 410})


def is_negative_probe_step(step) -> bool:
    """True when a chain step exists ONLY to be refused (#363).

    `business_chain_isolation`'s own remediation text demands exactly this
    test -- "a SECOND user (or an unauthenticated request) reading another
    user's resource MUST be refused (expect 401/403)" -- and every rejected step
    of this shape in r91/r92/r93 carried expect=[404] on a deliberately invalid
    id. The registry then refused the chain for using an id that does not
    exist, which is the entire point of the probe.

    Requires the expectation to be PURELY negative: `/api/videos/xyz/save` with
    expect [200,201,401,404] also wants success and keeps the strict treatment.
    """
    try:
        exp = step.get("expect")
    except Exception:
        return False
    if not isinstance(exp, (list, tuple, set)) or not exp:
        return False
    try:
        codes = {int(c) for c in exp}
    except Exception:
        return False
    return bool(codes) and codes <= _NOT_FOUND_OR_DENIED


def collapse_last_literal_segment(path: str) -> str:
    """Rewrite the final path segment to a param placeholder (#363).

    Minimal on purpose: one segment, and the result must still match a
    REGISTERED template for the step to be accepted, so a genuinely wrong path
    stays rejected.
    """
    raw = str(path or "")
    if not raw.startswith("/"):
        return raw
    segs = [s for s in raw.split("/") if s != ""]
    if len(segs) < 2:
        return raw
    return "/" + "/".join(segs[:-1] + ["{x}"])


class RegistryHub:
    """Apifox-like API registry, schema, consumer, mock, test, and review hub.

    #693: that sentence over-advertises, and the gap is measurable rather than a matter of
    taste. `_meta.version` in a JsonStore counts writes exactly — `JsonStore.update` always
    `_save_raw`s and always `_bump_meta`s, with no conditional skip — so a store still sitting
    at version 1 across every kept run was created and never written by anybody. Over 146 runs:

        live            endpoints v96, verification_chains v1574, consumers v41,
                        breaking_changes v37 ...
        drained         pending_consumers — v29/v33 in r145/r146 and empty at rest, because
                        entries are promoted then deleted; see EXPERIMENTS_PENDING item 16
        never written   examples, mocks, reviews, seed_registrations, table_consumers,
                        table_breaking_changes  — a writer exists, it has never fired
        no writer       projects, providers, SCHEMAS — construction and `.value()` reads only,
                        no mutation anywhere in the tree, so every branch keyed on them is dead

    So of the five surfaces this line promises, `schema` and `mock` have never held a record,
    and `review` has a writer that has never run. Kept in one place rather than deleted piecemeal
    because the readers still exist and an empty store is a legitimate state — what was wrong was
    the docstring implying they carry data.
    """

    def __init__(self, hub_dir: Path, eventhub: "EventHub | None" = None,
                 workhub: "WorkHub | None" = None):
        self.hub_dir = Path(hub_dir)
        self.eventhub = eventhub
        self._workhub = workhub
        # Optional callable injected by orchestrator. Returns the set of
        # agent ids that are currently spawned and not terminated. Used
        # by request_api_review to reject reviewer lists that include
        # agents who haven't been spawned yet — design can't invite
        # backend/frontend for review before they exist. None => no
        # liveness check (tests, early bootstrap).
        self._live_agents_provider: Optional[Any] = None
        self._projects = JsonStore(self.hub_dir / "registryhub_projects.json")
        self._endpoints = JsonStore(self.hub_dir / "registryhub_endpoints.json")
        self._schemas = JsonStore(self.hub_dir / "registryhub_schemas.json")
        self._examples = JsonStore(self.hub_dir / "registryhub_examples.json")
        self._mocks = JsonStore(self.hub_dir / "registryhub_mocks.json")
        self._contract_tests = JsonStore(self.hub_dir / "registryhub_contract_tests.json")
        self._verification_chains = JsonStore(self.hub_dir / "registryhub_verification_chains.json")
        self._providers = JsonStore(self.hub_dir / "registryhub_providers.json")
        # #664: #71's per-endpoint chain-reject counter, PERSISTED. It was an in-memory
        # attribute on this object while every other fact the hub holds lives on disk, so it
        # only accumulated while one RegistryHub instance happened to handle both rejects.
        # Measured over 249 run logs: 4928 chain rejections, 4 escalations (0.08%).
        self._chain_rejects = JsonStore(self.hub_dir / "registryhub_chain_reject_counts.json")
        self._consumers = JsonStore(self.hub_dir / "registryhub_consumers.json")
        self._api_reviews = JsonStore(self.hub_dir / "registryhub_reviews.json")
        self._breaking_changes = JsonStore(self.hub_dir / "registryhub_breaking_changes.json")
        self._tables = JsonStore(self.hub_dir / "registryhub_tables.json")
        self._table_consumers = JsonStore(self.hub_dir / "registryhub_table_consumers.json")
        self._seed_registrations = JsonStore(self.hub_dir / "registryhub_seed_registrations.json")
        self._table_breaking_changes = JsonStore(self.hub_dir / "registryhub_table_breaking_changes.json")
        self._mcp_registry = JsonStore(self.hub_dir / "registryhub_mcp_registry.json")
        # ui_page contract layer (A1→A3, 2026-06-12): the frontend's analog of
        # the endpoint/table contract. A ui_page declares route + component +
        # apis_used + components; it lives HERE (registryhub = contracts), not in
        # workhub (collaboration nodes: kickoff/retro/project). As of A3 the
        # RegistryHub is the SOLE OWNER: workhub.update_ui_page/get_ui_pages are
        # thin delegates to these methods; workhub no longer stores ui_pages.
        # Components are the API-owning layer pages roll up.
        self._ui_pages = JsonStore(self.hub_dir / "registryhub_ui_pages.json")
        self._ui_components = JsonStore(self.hub_dir / "registryhub_ui_components.json")
        # Pending consumer queue (Bug-3+6): agents declare consumer intent on
        # an endpoint that may not be registered yet. When the endpoint is
        # later registered, the pending entry is auto-promoted to a real
        # ``_consumers`` row and the requesting agent receives an
        # ``endpoint_implemented`` urgent event so it can resume work.
        self._pending_consumers = JsonStore(self.hub_dir / "registryhub_pending_consumers.json")
        # PR 4 + PR 5 (hub-responsibility-split plan, ranks 4–5):
        # the MCP server/tool/consumer methods moved to
        # ``MCPRegistry`` and the table/seed/table-consumer methods
        # moved to ``SchemaHub``. RegistryHub still owns the on-disk
        # stores (``registryhub_mcp_registry.json``,
        # ``registryhub_tables.json``,
        # ``registryhub_table_consumers.json``,
        # ``registryhub_seed_registrations.json``,
        # ``registryhub_table_breaking_changes.json``) — paths unchanged
        # for snapshot compatibility — but no longer carries the
        # method surfaces. Those modules read/write the stores via
        # the handles HubRegistry passes them at init.
        self.ensure_documents()

    def attach_workhub(self, workhub) -> None:
        self._workhub = workhub

    def attach_live_agents_provider(self, provider) -> None:
        """Inject a zero-arg callable returning the iterable of currently
        active agent ids. ``request_api_review`` uses it to reject
        reviewers that aren't running yet (e.g. design inviting
        backend/frontend before they're spawned)."""
        self._live_agents_provider = provider

    def ensure_documents(self) -> None:
        for store in [
            self._projects, self._endpoints, self._schemas, self._examples, self._mocks,
            self._contract_tests, self._providers, self._consumers, self._api_reviews,
            self._breaking_changes, self._tables, self._table_consumers,
            self._seed_registrations, self._table_breaking_changes,
            self._pending_consumers,
            self._mcp_registry,
            self._ui_pages, self._ui_components,
        ]:
            store.update(lambda m: m, change_info={"system": "ensure_registryhub_document"})

    def _emit(self, event_type: str, payload: dict, recipients: Optional[List[str]] = None, priority: str = "normal") -> None:
        if self.eventhub:
            # Phase 4.1c: caller="registryhub" → owner-equals admit.
            self.eventhub.publish_event(
                "registryhub", event_type, payload,
                recipients=recipients or [], priority=priority,
                caller="registryhub",
            )

    @staticmethod
    def endpoint_id(method: str, path: str) -> str:
        """Canonicalize ``(method, path)`` to one endpoint id.

        Normalizes ``METHOD /api/posts/`` and ``method /api/posts`` and
        ``GET api/posts`` to the same id so backend's registration and
        frontend's consumer-registration don't silently miss each other
        because of a stray trailing slash or case difference.

        Rules:
          * method → upper-case, trimmed.
          * path  → trimmed; ensure exactly one leading ``/`` if path
                    is non-empty; strip trailing ``/`` (except for the
                    bare root ``/`` which stays as-is); Express ``:param``
                    → FastAPI ``{param}`` (PROPOSAL #29).

        PROPOSAL #29: the ``:param`` → ``{param}`` step makes the SAME route
        registered in either idiom — frontend/router ``/api/notes/:id`` vs backend
        FastAPI ``/api/notes/{id}`` — resolve to ONE endpoint id, instead of two
        distinct endpoints (the second a phantom the backend can never implement →
        permanent finish-block). Slash-anchored so a literal ``:`` MID-segment (a
        custom-method path) is untouched. This matches the ``_express_to_fastapi``
        normalization route_projector/backend_audit/frontend_audit already apply for
        verification matching, so endpoint IDENTITY now agrees with the matcher.
        PROPOSAL #39 (#1): the id is also param-NAME-agnostic — every ``{param}`` collapses
        to ``{}`` so the SAME route declared as ``/notes/{id}`` and implemented as
        ``/notes/{note_id}`` resolves to ONE endpoint id (the param name is arbitrary),
        instead of forking a phantom ``defined`` endpoint that blocks
        all_business_endpoints_implemented forever (run #36: validation never opened because
        the declared ``{id}`` variant stayed ``defined`` while the backend implemented
        ``{note_id}``). The STORED ``path`` keeps the real param name (codegen + the route
        handler need it); only the IDENTITY is param-agnostic — same idea as
        ``route_projector._norm_path``. MUST stay byte-identical with
        ``kickoff/contract.py:endpoint_id``.
        """
        import re as _re
        m = str(method or "").upper().strip()
        # Strip any QUERY STRING before identity: a loose chain/consumer path like
        # ``/api/notes?tag=updated`` exercises the registered ``GET /api/notes`` (the
        # query is a filter ON that endpoint, NOT a distinct endpoint). Without this a
        # verifier chain that tests a list filter is rejected as a "phantom endpoint"
        # → business_chain never registers → delivery blocked (smoke-notes exp6).
        _path = str(path or "").split("?", 1)[0]
        ident = _re.sub(r"\{[^}]+\}", "{}", RegistryHub._canonical_path(_path))
        return f"{m} {ident}"

    @staticmethod
    def _canonical_path(path: str) -> str:
        """The canonical FastAPI path form used by both ``endpoint_id`` and the stored
        endpoint ``path`` field (PROPOSAL #38 A2): trim, ensure one leading ``/``, strip
        trailing ``/`` (except bare root), and rewrite Express ``:param`` → FastAPI
        ``{param}`` (slash-anchored, PROPOSAL #29). Storing this — not the raw input —
        means a registration of ``/api/notes/:id`` PERSISTS as ``/api/notes/{id}``, so the
        route projector stamps a real path param (not a literal ``:id`` static route) and
        the verifier tests ``/api/notes/1`` against a matching route instead of getting a
        405. Byte-identical normalization to the prior inline ``endpoint_id`` logic."""
        p = str(path or "").strip()
        if p:
            if not p.startswith("/"):
                p = "/" + p
            if len(p) > 1 and p.endswith("/"):
                p = p.rstrip("/") or "/"
            import re as _re
            p = _re.sub(r"(?<=/):([A-Za-z_][A-Za-z0-9_]*)", r"{\1}", p)
        return p

    @staticmethod
    def _canonical_response_key(method: str, path: str) -> str:
        """PROPOSAL #50: the canonical response envelope key the route_projector emits —
        ``item`` (non-GET / ``/me`` / param-tail) else ``items`` (collection GET). Mirrors
        kickoff ``_canonical_response_key`` (#46); kept here too so the REGISTRY layer
        (which every registration flows through, incl. backend impl-time) enforces it."""
        import re as _re
        m = str(method or "GET").upper().strip()
        last = next((p for p in reversed(str(path or "").strip("/").split("/")) if p), "")
        is_param = (last.startswith("{") and last.endswith("}")) or last.startswith(":")
        single = m != "GET" or last == "me" or is_param
        return "item" if single else "items"

    def register_endpoint(self, method: str, path: str, schema: dict = None, provider: str = "", agent: str = "", status: str = "defined", **metadata: Any) -> dict:
        # Ownership: backend owns endpoint registration; the kickoff
        # coordinator (actor='orchestrator') also registers the
        # canonical contract during finalize_kickoff. Frontend signals
        # data-shape needs via `api_requirement` events on EventHub;
        # backend designs the endpoint and publishes the contract.
        from ._role_gate import require_allowed_actor
        require_allowed_actor(
            method_name="register_endpoint",
            agent=agent,
            provider=provider,
            allowed_set={"backend", "orchestrator"},
            target_label="registryhub.register_endpoint",
            error_extra=(
                "backend lane owns endpoint registration; the kickoff "
                "coordinator (actor='orchestrator') registers contracts "
                "during finalize_kickoff. Frontend sends api_requirement "
                "events via EventHub. Design / verifier must NOT register "
                "endpoints — produce sections, "
                "not registrations."
            ),
        )
        # PATH-PARAM VALIDATION (#57, outlook run-43 live): a brace param must be a
        # named identifier. The verifier registered ``DELETE /api/messages/{}`` —
        # projected verbatim that emits ``def h(: str, ...)`` → SyntaxError → the
        # backend CRASH-LOOPS and every validation cycle dies on backend_port.
        # Reject at the source with the fix in the message (the projector also
        # sanitizes defensively for garbage already stored).
        import re as _re
        for _seg in str(path or "").split("/"):
            if _seg.startswith("{") and _seg.endswith("}"):
                if not _re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", _seg[1:-1]):
                    raise ValueError(
                        f"invalid path parameter '{_seg}' in '{path}': every "
                        "{...} must be a NAMED identifier — e.g. "
                        "/api/messages/{messageId}, not /api/messages/{}. "
                        "Re-register with a named param.")
        endpoint_id = self.endpoint_id(method, path)
        actor = agent or provider or "registryhub"
        now = time.time()
        old = self._endpoints.get(endpoint_id)
        # RESERVED-SURFACE GUARD (env-gated ENVGEN_RESERVED_PATH_GUARD, default-off):
        # the fixed framework surface (/health, /auth/*, /oauth/*, /.well-known/*, the
        # tenant control plane) is registered by the orchestrator and SERVED by the
        # runtime AS/control-plane — not by lane code. register_endpoint is otherwise a
        # silent last-write-wins upsert, so a lane re-registering one of these
        # (method, path) silently CLOBBERS the framework's entry (wrong kind / owner /
        # response_key) and desyncs system↔agent. When the flag is set, reject any
        # concrete NON-orchestrator actor that touches the reserved surface — a lane
        # registers ONLY its own /api business endpoints; the framework owns the rest.
        import os as _os
        _guard_actor = (agent or provider or "").strip().lower()
        if (_os.environ.get("ENVGEN_RESERVED_PATH_GUARD")
                and _guard_actor and _guard_actor != "orchestrator"):
            _p = self._canonical_path(path)
            _old_kind = str(((old or {}).get("metadata") or {}).get("kind") or "").strip().lower()
            _reserved_kind = _old_kind in {
                "auth", "oauth", "infra", "spine", "control_plane", "control", "health"}
            _reserved_path = (
                _p in ("/", "/health", "/auth", "/oauth")
                or _p.startswith(("/auth/", "/oauth/", "/.well-known"))
                or _p.startswith("/api/v1/tenants")
                or _p.startswith("/api/v1/admin")
                or _p in ("/api/v1/init-tenant", "/api/v1/reset")
            )
            if _reserved_kind or _reserved_path:
                raise PermissionError(
                    f"register_endpoint refused: {str(method or '').upper()} {_p} is part "
                    f"of the FRAMEWORK-OWNED fixed surface (health / auth / oauth / "
                    f".well-known / tenant control-plane). The orchestrator registers these "
                    f"and the runtime SERVES them — a lane must NOT re-register them (it "
                    f"would clobber the framework's entry). Register ONLY your own /api "
                    f"business endpoints."
                )
        endpoint = {
            **(old or {}),
            "id": endpoint_id,
            "method": str(method or "").upper(),
            # #38 A2: store the CANONICAL FastAPI path (`:id`→`{id}`), not the raw input,
            # so the projector + verifier never see a literal Express `:id` (→ 405).
            "path": self._canonical_path(path),
            "status": status or (old or {}).get("status") or "defined",
            "provider": provider or (old or {}).get("provider"),
            "schema": schema or (old or {}).get("schema") or {},
            "metadata": {**((old or {}).get("metadata") or {}), **(metadata or {})},
            "_updated_by": agent,
            "_updated_at": now,
        }
        # PROPOSAL #50: enforce the canonical response envelope key (item/items — what the
        # projector emits + the delivery gate requires) for BUSINESS endpoints on EVERY
        # registration. #46 canonicalizes at KICKOFF, but the backend registers endpoints
        # at IMPL time (e.g. an invented /api/dummy_trigger with response_key='triggered')
        # which bypasses kickoff → the gate's business_response_key_noncanonical
        # hard-blocks delivery (smoke-notes 2026-06-19: the FINAL remaining check before the
        # first create_release was a backend-registered non-canonical key). Scope mirrors
        # #46 + the gate's exemption: business /api/ + non-exempt kind only (control-plane
        # keeps its declared key — clobbering it would cause false contract-drift). Only a
        # PRESENT non-canonical key is rewritten; an absent key stays absent (gate-exempt).
        _md = endpoint["metadata"]
        # Canonicalize the EFFECTIVE response_key the gate reads — metadata OR
        # schema (the gate's `noncanonical_business_response_keys` falls back to
        # schema.response_key). A lane that put a non-canonical key ONLY in schema
        # (youtube run #18: GET /api/v1/health → schema.response_key='status', no
        # metadata key) bypassed the metadata-only rewrite → the gate hard-blocked
        # delivery on it. Set metadata.response_key (read first by the gate) to the
        # canonical envelope the projector actually emits.
        _rk = _md.get("response_key") or (endpoint.get("schema") or {}).get("response_key")
        if (isinstance(_rk, str) and _rk and _rk not in ("item", "items")
                and str(endpoint["path"]).startswith("/api/")
                and str(_md.get("kind") or "").strip().lower() not in {
                    "auth", "oauth", "infra", "spine", "control_plane", "custom"}
                and not (_md.get("custom") or _md.get("custom_route"))):
            _canon = self._canonical_response_key(
                endpoint["method"], endpoint["path"])
            _md["response_key"] = _canon
            # keep schema consistent so no other reader sees the stale non-canonical key
            if isinstance(endpoint.get("schema"), dict) and endpoint["schema"].get("response_key"):
                endpoint["schema"]["response_key"] = _canon
        old_full = {
            **((old or {}).get("schema") or {}),
            "method": (old or {}).get("method"),
            "path": (old or {}).get("path"),
            "response_key": ((old or {}).get("metadata") or {}).get("response_key"),
            "auth_required": ((old or {}).get("metadata") or {}).get("auth_required"),
        }
        new_full = {
            **endpoint["schema"],
            "method": endpoint.get("method"),
            "path": endpoint.get("path"),
            "response_key": (endpoint.get("metadata") or {}).get("response_key"),
            "auth_required": (endpoint.get("metadata") or {}).get("auth_required"),
        }
        breaking = self.detect_breaking_change(old_full, new_full)
        if breaking["is_breaking"]:
            self._record_breaking_change(endpoint_id, breaking, agent=agent)
            endpoint["breaking_change"] = breaking
        self._endpoints.update(
            lambda m: m.set(endpoint_id, endpoint, actor),
            change_info={"agent": actor},
        )

        # Flush pending consumers (Bug-3+6): agents that declared intent
        # to consume this endpoint while it didn't yet exist get promoted
        # to real consumers AND notified via an urgent ``endpoint_implemented``
        # event so they can wake up and start integrating.
        promoted_agents: List[str] = []
        try:
            pending_now = self._pending_consumers.value() or {}
            matching_keys = [
                k for k, v in pending_now.items()
                if isinstance(v, dict) and v.get("endpoint_id") == endpoint_id
            ]
            for pkey in matching_keys:
                pe = pending_now[pkey]
                now_promote = time.time()
                consumer = {
                    "id": pkey,
                    "endpoint_id": endpoint_id,
                    "file_path": pe.get("file_path"),
                    "agent": pe.get("agent"),
                    "metadata": pe.get("metadata") or {},
                    "created_at": now_promote,
                    "_updated_by": pe.get("agent"),
                    "_updated_at": now_promote,
                }
                self._consumers.update(
                    lambda m, c=consumer, k=pkey, a=pe.get("agent"): m.set(k, c, a),
                    change_info={"agent": pe.get("agent")},
                )
                self._pending_consumers.update(
                    lambda m, k=pkey: m.delete(k, "registryhub"),
                    change_info={"agent": "registryhub"},
                )
                ag = pe.get("agent")
                if ag and ag not in promoted_agents:
                    promoted_agents.append(ag)
        except Exception:
            # Defensive: flushing pending must never block endpoint registration.
            pass

        # Determine the right event type. ``endpoint_implemented`` fires
        # when status transitions to (or is set to) ``implemented`` — this
        # is the signal consumers actually care about. ``endpoint_defined``
        # for the initial declaration. ``endpoint_registered`` is kept as
        # a legacy umbrella event for back-compat with existing
        # subscribers (UI, etc.).
        new_status = (endpoint.get("status") or "").lower()
        old_status = ((old or {}).get("status") or "").lower()
        transition_event = None
        if new_status == "implemented" and old_status != "implemented":
            transition_event = "endpoint_implemented"
        elif new_status == "defined" and old_status not in {"defined", "implemented"}:
            transition_event = "endpoint_defined"

        # Build recipients for the transition event: existing real
        # consumers + agents we just promoted out of pending.
        if transition_event:
            try:
                existing_consumers = [
                    c.get("agent") for c in self._consumers.value().values()
                    if isinstance(c, dict) and c.get("endpoint_id") == endpoint_id
                ]
            except Exception:
                existing_consumers = []
            recipient_set: List[str] = []
            for a in (existing_consumers + promoted_agents):
                if a and a not in recipient_set:
                    recipient_set.append(a)
            self._emit(
                transition_event,
                {**endpoint, "promoted_pending_agents": promoted_agents},
                recipients=recipient_set,
                priority="urgent" if transition_event == "endpoint_implemented" else "normal",
            )

        # §6/§7 C1 (2026-06-06): HUB-QUERY validation trigger. When this flip to
        # ``implemented`` makes EVERY business endpoint implemented, the backend
        # contract is fully realized → emit ``validation_ready`` to the verifier.
        # A STRUCTURAL trigger (lifecycle.all_business_endpoints_implemented), NOT
        # a fragile collection of lane finish-notifies — smoke #6 showed that
        # heuristic stalls forever when a lane doesn't cleanly finish (the
        # frontend was stuck in a codehub_commit retry loop, so "both lanes done"
        # never fired and the verifier sat blocked). The verifier's docker
        # readiness gate handles "frontend not merged yet" (defer + retry), so
        # triggering on the backend contract being complete is safe.
        if transition_event == "endpoint_implemented":
            try:
                from .lifecycle import all_business_endpoints_implemented
                if all_business_endpoints_implemented(self.get_endpoints()):
                    self._emit(
                        "validation_ready",
                        {"signal": "validation_ready",
                         "reason": "all_business_endpoints_implemented",
                         "trigger_endpoint": endpoint_id},
                        recipients=["verifier"],
                        priority="urgent",
                    )
            except Exception:
                pass

        # Drive the matching WorkHub ``implement_endpoint`` task to
        # ``completed`` on every status=implemented call (not just the
        # transition flip — retry-after-deps-resolved must succeed).
        # The sync helper is idempotent on terminal states.
        if new_status == "implemented" and self._workhub is not None:
            try:
                self._workhub.sync_impl_endpoint_completed(
                    method, path, agent=actor,
                )
            except Exception:
                pass

        # Detect schema-change-on-already-implemented: design or another
        # agent re-registered an endpoint whose status was already
        # ``implemented``. The transition_event branches above don't fire
        # in this case (old==new==implemented), but the provider AND
        # existing consumers need to know their assumed contract just
        # moved under their feet — otherwise backend's implementation
        # silently drifts from the spec until verifier catches it.
        schema_actually_changed = (old or {}).get("schema") != endpoint.get("schema")
        if old and schema_actually_changed and old_status == "implemented" and new_status == "implemented":
            provider_id = endpoint.get("provider")
            try:
                consumer_ids = [
                    c.get("agent") for c in self._consumers.value().values()
                    if isinstance(c, dict) and c.get("endpoint_id") == endpoint_id
                ]
            except Exception:
                consumer_ids = []
            recipients = []
            for a in ([provider_id] + consumer_ids):
                if a and a not in recipients:
                    recipients.append(a)
            self._emit(
                "endpoint_schema_changed",
                {
                    **endpoint,
                    "is_breaking": bool(breaking.get("is_breaking")),
                    "changed_by": agent,
                },
                recipients=recipients,
                priority="urgent" if breaking.get("is_breaking") else "high",
            )

        self._emit("endpoint_registered", endpoint, recipients=[], priority="normal")
        return endpoint

    def update_schema(self, endpoint_id: str, request: dict = None, response: dict = None, agent: str = "") -> dict:
        endpoint = self._endpoints.get(endpoint_id)
        if not endpoint:
            return {"error": f"Endpoint not found: {endpoint_id}"}
        schema = dict(endpoint.get("schema") or {})
        if request is not None:
            schema["request"] = request
        if response is not None:
            schema["response"] = response
        method, path = endpoint_id.split(" ", 1)
        return self.register_endpoint(method, path, schema=schema, provider=endpoint.get("provider"), agent=agent, status=endpoint.get("status", "defined"))

    def register_consumer(
        self,
        endpoint_id: str,
        file_path: str,
        agent: str,
        metadata: dict = None,
        pending: bool = False,
    ) -> dict:
        """Register a consumer relationship.

        Phase 0+ behaviour:
          * Default (``pending=False``): hard L1 write-time gate — the
            endpoint must already exist, not be deprecated, and the
            consumer's expected_schema must subset-match. This is what
            backend/frontend call when they have already written code
            against a declared endpoint.
          * ``pending=True``: the endpoint may not exist yet (typical
            during early-pipeline scheduling — e.g. backend declares
            intent to consume ``GET /api/users`` before design has
            published it). The entry is queued in ``_pending_consumers``
            and is automatically promoted + the requesting agent is
            sent an ``endpoint_implemented`` urgent event when the
            endpoint is later registered.
        """
        # Normalize caller-supplied endpoint_id so trailing-slash or
        # case-different ids still resolve to the canonical entry
        # (matches what register_endpoint stores).
        if isinstance(endpoint_id, str) and " " in endpoint_id:
            try:
                _m, _p = endpoint_id.split(" ", 1)
                endpoint_id = self.endpoint_id(_m, _p)
            except Exception:
                pass

        # L1 write-time gate
        endpoint = self._endpoints.value().get(endpoint_id)
        if not endpoint:
            if pending:
                now = time.time()
                key = f"{endpoint_id}:{file_path}:{agent}"
                pending_entry = {
                    "id": key,
                    "endpoint_id": endpoint_id,
                    "file_path": file_path,
                    "agent": agent,
                    "metadata": metadata or {},
                    "queued_at": now,
                }
                self._pending_consumers.update(
                    lambda m: m.set(key, pending_entry, agent),
                    change_info={"agent": agent},
                )
                self._emit(
                    "consumer_pending",
                    pending_entry,
                    recipients=[],  # info-only; promotion event has recipients
                    priority="normal",
                )
                return {
                    "status": "pending",
                    "endpoint_id": endpoint_id,
                    "queued_for": agent,
                    "hint": (
                        "Endpoint not registered yet. Queued as pending — you "
                        "will receive an ``endpoint_implemented`` urgent event "
                        "once the producer registers it."
                    ),
                }
            return {"error": "endpoint_not_registered",
                    "endpoint_id": endpoint_id,
                    "hint": "Call registryhub_register_endpoint first (backend agent), "
                            "or call this tool with pending=True to queue intent."}
        if endpoint.get("status") == "deprecated":
            return {"error": "endpoint_deprecated",
                    "endpoint_id": endpoint_id,
                    "replacement_id": endpoint.get("replacement_id"),
                    "hint": "Use the replacement endpoint instead."}
        if metadata and "expected_schema" in metadata:
            mismatch = _schema_subset_check(
                metadata["expected_schema"], endpoint.get("schema", {}))
            if mismatch:
                return {"error": "schema_mismatch",
                        "endpoint_id": endpoint_id,
                        "missing_fields": mismatch.get("missing"),
                        "type_mismatches": mismatch.get("type_mismatches"),
                        "hint": "Fix consumer code to match endpoint schema, "
                                "or registryhub_request_review to negotiate a change."}
        now = time.time()
        key = f"{endpoint_id}:{file_path}:{agent}"
        consumer = {
            "id": key,
            "endpoint_id": endpoint_id,
            "file_path": file_path,
            "agent": agent,
            "metadata": metadata or {},
            "created_at": now,
            "_updated_by": agent,
            "_updated_at": now,
        }
        self._consumers.update(
            lambda m: m.set(key, consumer, agent),
            change_info={"agent": agent},
        )
        self._emit("consumer_registered", consumer, recipients=[])
        return consumer

    def record_api_test(self, endpoint_id: str, result: dict, evidence: dict = None, agent: str = "verifier") -> dict:
        # Authorship lock: contract-test records are the artifact verifier
        # reads to decide pass/fail on the API contract. Only the verifier
        # lane may author. Path A bundle trim in tool_bundles.py +
        # verifier-only grant in agents_config.yaml prevent agents from
        # reaching this method via the tool path; this hub-method gate
        # catches hub-direct callers.
        from ._role_gate import require_allowed_actor
        require_allowed_actor(
            method_name="record_api_test",
            agent=agent,
            provider=None,
            allowed_set={"verifier"},
            target_label="registryhub.record_api_test",
            error_extra=(
                "contract-test records are authored by the verifier "
                "lane only."
            ),
        )
        now = time.time()
        # Event-store efficiency (#4): upsert by a STABLE per-endpoint key
        # (drop the timestamp) so re-recording the same endpoint overwrites
        # the prior row instead of appending a new one every validation run.
        # The endpoint's latest contract-test result is the only row callers
        # need; history is not consumed. Readers filter by ``endpoint_id``
        # (get_contract_test_results / list_contract_test_results_sorted) and
        # still see exactly one current row per endpoint.
        test_id = f"test:{endpoint_id}"
        result_dict = result or {}
        # Derive explicit top-level ``verdict`` ("pass"/"fail") from the
        # writer's result dict so the endpoint_contract resolver can do
        # an unambiguous lookup. Original ``result`` dict is preserved
        # unchanged (existing readers that inspect status_code/passed
        # still work).
        # Derivation precedence:
        #   1. result["passed"]      (boolean from pytest/jest etc.)
        #   2. result["result"]      ("pass"/"fail" string verdict)
        #   3. result["status_code"] (HTTP 2xx/3xx = pass, else fail)
        # If none of the three is present, verdict is "unknown" — the
        # resolver treats this as "evidence_pending" so the story
        # gate doesn't approve on ambiguous evidence.
        verdict = "unknown"
        if "passed" in result_dict:
            verdict = "pass" if result_dict["passed"] else "fail"
        elif "result" in result_dict:
            val = str(result_dict["result"]).strip().lower()
            if val == "pass":
                verdict = "pass"
            elif val == "fail":
                verdict = "fail"
        elif "status_code" in result_dict:
            try:
                sc = int(result_dict["status_code"])
                verdict = "pass" if 200 <= sc < 400 else "fail"
            except (TypeError, ValueError):
                verdict = "unknown"
        test = {
            "id": test_id, "endpoint_id": endpoint_id,
            "result": result_dict, "evidence": evidence or {},
            "agent": agent, "created_at": now,
            "verdict": verdict,
        }
        # Event-store efficiency (#4): only emit ``api_test_recorded`` when
        # the verdict ACTUALLY CHANGED versus the last recorded result for
        # this endpoint. An identical re-record (same verdict + same HTTP
        # status_code) is a no-op for every consumer of the event stream, so
        # we skip the emit (the youtube run re-recorded 35 endpoints 42×
        # identically → 63% of all events). The store row is still upserted
        # so the latest result/evidence/timestamp stay current.
        prior = self._contract_tests.get(test_id)
        prior_status = (prior or {}).get("result", {}).get("status_code") if prior else None
        new_status = result_dict.get("status_code")
        verdict_changed = (
            prior is None
            or prior.get("verdict") != verdict
            or prior_status != new_status
        )
        self._contract_tests.update(
            lambda m: m.set(test_id, test, agent),
            change_info={"agent": agent},
        )
        if verdict_changed:
            self._emit("api_test_recorded", test, recipients=[])
        return test

    def get_consumers(self, endpoint_id: str) -> List[dict]:
        return [
            c for c in self._consumers.value().values()
            if c.get("endpoint_id") == endpoint_id
        ]

    def list_pending_consumers(self, agent: Optional[str] = None) -> List[dict]:
        """Return queued ``pending=True`` consumer entries. Optionally
        filtered to a single agent. Each item carries ``queued_at`` so
        callers can compute age.
        """
        items = list((self._pending_consumers.value() or {}).values())
        if agent is not None:
            items = [c for c in items if c.get("agent") == agent]
        return items

    def list_stale_pending_consumers(
        self,
        ttl_seconds: float = 1800.0,
        now_ts: Optional[float] = None,
    ) -> List[dict]:
        """Return pending consumers older than ``ttl_seconds``.

        A long-pending consumer is a stuck dependency: the producer
        either forgot to register, or the spec changed in a way that
        renamed the endpoint id. Either way the orchestrator should
        nudge the producer or have the consumer requeue. Each result
        carries ``age_seconds``.
        """
        now = float(now_ts) if now_ts is not None else time.time()
        out = []
        for c in self.list_pending_consumers():
            queued = float(c.get("queued_at") or 0.0)
            if queued <= 0:
                continue  # malformed entry — don't surface as stale
            age = now - queued
            # Negative age = clock skew or future-dated entry; not stale.
            if age < ttl_seconds:
                continue
            out.append({**c, "age_seconds": int(age)})
        return out

    def get_dependencies_for_file(self, file_path: str) -> List[dict]:
        return [
            c for c in self._consumers.value().values()
            if c.get("file_path") == file_path
        ]

    def get_breaking_changes(self, since_ts: float = None) -> List[dict]:
        items = list(self._breaking_changes.value().values())
        if since_ts is not None:
            items = [b for b in items if b.get("created_at", 0) >= since_ts]
        items.sort(key=lambda b: b.get("created_at", 0), reverse=True)
        return items

    def get_contract_test_results(self, endpoint_id: str) -> List[dict]:
        return [
            t for t in self._contract_tests.value().values()
            if t.get("endpoint_id") == endpoint_id
        ]

    def list_contract_test_results_sorted(
        self, endpoint_id: str, *,
        by: str = "created_at", desc: bool = True,
    ) -> List[dict]:
        results = [
            t for t in self._contract_tests.value().values()
            if t.get("endpoint_id") == endpoint_id
        ]
        results.sort(key=lambda t: t.get(by, 0), reverse=desc)
        return results

    def add_mock(self, endpoint_id: str, mock_response: dict, agent: str = "") -> dict:
        if endpoint_id not in self._endpoints.value():
            return {"error": f"Endpoint not found: {endpoint_id}"}
        actor = agent or "registryhub"
        now = time.time()
        mock_id = f"mock:{endpoint_id}:{now}:0"
        mock = {
            "id": mock_id,
            "endpoint_id": endpoint_id,
            "response": mock_response or {},
            "created_by": agent,
            "created_at": now,
        }
        self._mocks.update(
            lambda m: m.set(mock_id, mock, actor),
            change_info={"agent": actor},
        )
        self._emit("mock_added", mock, recipients=[])
        return mock

    def add_example(self, endpoint_id: str, request_example: dict = None,
                    response_example: dict = None, agent: str = "") -> dict:
        if endpoint_id not in self._endpoints.value():
            return {"error": f"Endpoint not found: {endpoint_id}"}
        actor = agent or "registryhub"
        now = time.time()
        example_id = f"example:{endpoint_id}:{now}:0"
        example = {
            "id": example_id,
            "endpoint_id": endpoint_id,
            "request": request_example or {},
            "response": response_example or {},
            "created_by": agent,
            "created_at": now,
        }
        self._examples.update(
            lambda m: m.set(example_id, example, actor),
            change_info={"agent": actor},
        )
        self._emit("example_added", example, recipients=[])
        return example

    def deprecate_endpoint(self, endpoint_id: str, replacement_id: str = None,
                           agent: str = "") -> dict:
        endpoint = self._endpoints.get(endpoint_id)
        if not endpoint:
            return {"error": f"Endpoint not found: {endpoint_id}"}
        actor = agent or "registryhub"
        now = time.time()
        updated = dict(endpoint)
        updated["status"] = "deprecated"
        if replacement_id:
            updated["replacement_id"] = replacement_id
        updated["_updated_by"] = agent
        updated["_updated_at"] = now
        self._endpoints.update(
            lambda m: m.set(endpoint_id, updated, actor),
            change_info={"agent": actor},
        )
        # #231 (r21 split-brain): consolidation must CASCADE, or stale
        # declarations steer lanes back onto the dead path (the frontend
        # 'corrected' its call to the deprecated /api/feed 29s after the
        # backend dropped it → authed 404 in the delivered app).
        if replacement_id:
            try:
                rep = self._endpoints.value().get(replacement_id)
                if isinstance(rep, dict):
                    # carry behavioral metadata the replacement lacks
                    # (auth_required: false on the old public feed was lost →
                    # the projected replacement got the default token wall)
                    _old_meta = dict(endpoint.get("metadata") or {})
                    _rep2 = dict(rep)
                    _rep_meta = dict(_rep2.get("metadata") or {})
                    _changed = False
                    for _mk in ("auth_required", "response_key"):
                        _ov = endpoint.get(_mk, _old_meta.get(_mk))
                        if _ov is not None and _mk not in _rep_meta \
                                and _rep2.get(_mk) is None:
                            _rep_meta[_mk] = _ov
                            _changed = True
                    if _changed:
                        _rep2["metadata"] = _rep_meta
                        _rep2["_updated_by"] = actor
                        _rep2["_updated_at"] = now
                        self._endpoints.update(
                            lambda m: m.set(replacement_id, _rep2, actor),
                            change_info={"agent": actor})
                    # rewrite ui_pages.apis_used off the dead path
                    _old_call = (f"{str(endpoint.get('method') or 'GET').upper()} "
                                 f"{endpoint.get('path') or ''}").strip()
                    _new_call = (f"{str(rep.get('method') or 'GET').upper()} "
                                 f"{rep.get('path') or ''}").strip()
                    if _old_call and _new_call and _old_call != _new_call:
                        for _pn, _pg in (self._ui_pages.value() or {}).items():
                            if not isinstance(_pg, dict):
                                continue
                            _apis = list(_pg.get("apis_used") or [])
                            _new_apis = [
                                _new_call if str(a).strip() in
                                (_old_call, endpoint.get("path")) else a
                                for a in _apis]
                            if _new_apis != _apis:
                                _pg2 = dict(_pg)
                                _pg2["apis_used"] = _new_apis
                                _pg2["_updated_by"] = actor
                                _pg2["_updated_at"] = now
                                self._ui_pages.update(
                                    lambda m, _n=_pn, _r=_pg2: m.set(_n, _r, actor),
                                    change_info={"agent": actor})
            except Exception:
                pass  # cascade is best-effort; the deprecation itself landed
        consumers = [c.get("agent") for c in self._consumers.value().values()
                     if c.get("endpoint_id") == endpoint_id]
        self._emit(
            "endpoint_deprecated",
            {"endpoint_id": endpoint_id, "replacement_id": replacement_id, "deprecated_by": agent},
            recipients=sorted(set(consumers)),
            priority="high",
        )
        return updated

    def detect_breaking_change(self, old_schema: dict, new_schema: dict) -> dict:
        old_schema = old_schema or {}
        new_schema = new_schema or {}
        old_response = old_schema.get("response") or {}
        new_response = new_schema.get("response") or {}
        old_request = old_schema.get("request") or {}
        new_request = new_schema.get("request") or {}

        removed_response_fields: list = []
        type_changed_fields: list = []
        if isinstance(old_response, dict) and isinstance(new_response, dict):
            removed_response_fields = sorted(set(old_response.keys()) - set(new_response.keys()))
            for key in old_response.keys() & new_response.keys():
                if old_response[key] != new_response[key]:
                    type_changed_fields.append(key)

        required_added_in_request: list = []
        if isinstance(old_request, dict) and isinstance(new_request, dict):
            for key in set(new_request.keys()) - set(old_request.keys()):
                value = new_request[key]
                if isinstance(value, str) and "required" in value.lower():
                    required_added_in_request.append(key)

        method_changed = bool(
            old_schema.get("method") and new_schema.get("method")
            and old_schema["method"] != new_schema["method"]
        )
        path_changed = bool(
            old_schema.get("path") and new_schema.get("path")
            and old_schema["path"] != new_schema["path"]
        )
        response_key_changed = bool(
            old_schema.get("response_key") != new_schema.get("response_key")
            and (old_schema.get("response_key") is not None or new_schema.get("response_key") is not None)
        )
        auth_added = bool(new_schema.get("auth_required") and not old_schema.get("auth_required"))

        is_breaking = any([
            removed_response_fields, type_changed_fields,
            required_added_in_request, method_changed, path_changed,
            response_key_changed, auth_added,
        ])

        return {
            "is_breaking": is_breaking,
            "removed_response_fields": removed_response_fields,
            "type_changed_fields": sorted(type_changed_fields),
            "required_added_in_request": sorted(required_added_in_request),
            "method_changed": method_changed,
            "path_changed": path_changed,
            "response_key_changed": response_key_changed,
            "auth_added": auth_added,
        }

    def _record_breaking_change(self, endpoint_id: str, breaking: dict, agent: str = "") -> dict:
        actor = agent or "registryhub"
        now = time.time()
        key = f"breaking:{endpoint_id}:{now}"
        payload = {"id": key, "endpoint_id": endpoint_id, "breaking": breaking,
                   "created_at": now, "_updated_by": agent}
        self._breaking_changes.update(
            lambda m: m.set(key, payload, actor),
            change_info={"agent": actor},
        )
        consumers = [c for c in self._consumers.value().values()
                     if c.get("endpoint_id") == endpoint_id]
        recipient_agents = sorted(set(c.get("agent") for c in consumers if c.get("agent")))

        self._emit("breaking_change_detected", payload,
                   recipients=recipient_agents, priority="urgent")

        # Auto-create a fix task in WorkHub per affected consumer agent
        workhub = getattr(self, "_workhub", None)
        if workhub is not None:
            for consumer_agent in recipient_agents:
                consumer_files = [
                    c.get("file_path") for c in consumers
                    if c.get("agent") == consumer_agent
                ]
                try:
                    workhub.create_task(
                        title=f"Fix breaking change in {endpoint_id}",
                        description=(
                            f"RegistryHub detected a breaking change in {endpoint_id}: "
                            f"{breaking}. Consumer files: {consumer_files}"
                        ),
                        assignee=consumer_agent,
                        agent=agent or "registryhub",
                        source="registryhub_breaking_change",
                        linked_apis=[endpoint_id],
                        affected_files=consumer_files,
                        priority="P0",
                    )
                except Exception:
                    # Hub linkage missing in test setup is non-fatal; the event still went out.
                    pass
        return payload

    def request_api_review(self, endpoint_id: str, reviewers: List[str], agent: str = "", reason: str = "") -> dict:
        # Reject reviews against endpoints that don't exist. Without
        # this gate, an agent that doesn't know the right tool calls
        # ``registryhub_request_review`` with placeholder ids ("placeholder",
        # "placeholder2", …) and each call writes a fresh row keyed by
        # ``api_review:<id>:<now>`` — fast path to a poisoned hub state
        # full of pending reviews assigned to backend/frontend who can't
        # action them. (Observed in the Facebook smoke run.)
        if not isinstance(endpoint_id, str) or not endpoint_id.strip():
            return {"error": "registryhub_request_review: endpoint_id must be non-empty"}
        if endpoint_id not in (self._endpoints.value() or {}):
            return {
                "error": f"registryhub_request_review: unknown endpoint_id {endpoint_id!r}. "
                          "Register the endpoint first via registryhub_register_endpoint. "
                          "(registryhub_request_review is per-endpoint approval — "
                          "design-phase approval is decided in the "
                          "orchestrator-hosted kickoff meeting, not via this tool.)",
            }
        if not reviewers:
            return {"error": "registryhub_request_review: reviewers must include at least one agent"}
        # Reject reviewers that aren't currently active. There is a hard
        # lifecycle rule that implementation agents (backend, frontend,
        # database, verifier) only start AFTER design completes — so if
        # design tries to invite them at design time, the review
        # request lands in a dead inbox and nobody will action it.
        # Surfacing a clear error here pushes the agent to invite an
        # actually-running reviewer (orchestrator / orchestrator
        # / knowledge), which is the correct lifecycle for that phase.
        provider = self._live_agents_provider
        if provider is not None:
            try:
                live = set(provider() or [])
            except Exception:
                live = None
            if live is not None and live:
                missing = [r for r in reviewers if r not in live]
                if missing:
                    return {
                        "error": (
                            f"registryhub_request_review: reviewer(s) not currently "
                            f"running: {missing}. Currently active agents: "
                            f"{sorted(live)}. If you need design-phase review, "
                            f"invite orchestrator / orchestrator instead — "
                            f"implementation agents (backend/frontend/database/"
                            f"verifier) only start after design is approved."
                        ),
                    }
        actor = agent or "registryhub"
        now = time.time()
        review_id = f"api_review:{endpoint_id}:{now}"
        review = {"id": review_id, "endpoint_id": endpoint_id, "reviewers": reviewers or [], "status": "pending", "reason": reason, "created_by": agent, "created_at": now}
        self._api_reviews.update(
            lambda m: m.set(review_id, review, actor),
            change_info={"agent": actor},
        )
        self._emit("api_review_requested", review, recipients=reviewers or [], priority="high")
        return review

    def submit_api_review(self, review_id: str, reviewer: str,
                          decision: str, comments: Optional[List[Any]] = None) -> dict:
        review = self._api_reviews.get(review_id)
        if not review:
            return {"error": f"Review not found: {review_id}"}
        if decision not in {"approve", "request_changes", "comment"}:
            return {"error": f"Invalid decision: {decision}"}
        now = time.time()
        updated = dict(review)
        updated["status"] = decision
        updated["comments"] = list(comments or [])
        reviewed_by = list(updated.get("reviewed_by") or [])
        if reviewer not in reviewed_by:
            reviewed_by.append(reviewer)
        updated["reviewed_by"] = reviewed_by
        updated["_updated_by"] = reviewer
        updated["_updated_at"] = now
        self._api_reviews.update(
            lambda m: m.set(review_id, updated, reviewer),
            change_info={"agent": reviewer},
        )
        endpoint_id = review.get("endpoint_id")
        self._emit(
            "api_review_submitted",
            {"review_id": review_id, "endpoint_id": endpoint_id, "reviewer": reviewer,
             "decision": decision, "comments": list(comments or [])},
            recipients=[review.get("created_by")] if review.get("created_by") else [],
            priority="high" if decision == "request_changes" else "normal",
        )
        return updated

    # ------------------------------------------------------------------
    # Table registry (DB schema). v3 single-owner: backend owns the
    # API + the DB schema, so endpoints and tables live on the same
    # hub. (The intermediate SchemaHub façade was a v2-era split that
    # didn't survive the single-owner reality.) MCP registry methods
    # still live separately on ``hubs.mcp_registry`` (PR 4 split).
    # ------------------------------------------------------------------

    def register_table(
        self,
        name: str,
        schema: dict = None,
        provider: str = "",
        agent: str = "",
        status: str = "defined",
        **metadata: Any,
    ) -> dict:
        from ._role_gate import require_allowed_actor
        require_allowed_actor(
            method_name="register_table",
            agent=agent,
            provider=provider,
            allowed_set={"backend", "database_worker", "orchestrator"},
            target_label="registryhub.register_table",
            error_extra=(
                "backend lane owns table registration; the kickoff "
                "coordinator (actor='orchestrator') registers tables "
                "during finalize_kickoff. Route cross-team needs via "
                "EventHub api_requirement or send_message(to='orchestrator', ...)."
            ),
        )
        actor = agent or provider or "registryhub"
        now = time.time()
        table_id = name
        existing = self._tables.value().get(table_id)
        # NORMALIZE AT THE WRITE BOUNDARY: the contract tools advertise a
        # FLAT-MAP schema (``{column: "type string"}``) while kickoff emits
        # ``{"columns":[{name,type,…}]}``. Storing either verbatim meant the
        # flat map never projected (``_columns_of`` returned [] → id-only ORM/
        # DDL, every other column silently dropped on re-registered tables).
        # Collapse to ONE canonical shape here so the store holds a single
        # representation every downstream reader already understands.
        _wiped_by: str = ""
        if schema is not None:
            from .database_scaffold import normalize_table_schema
            stored_schema: Any = normalize_table_schema(schema)
            # (FIX #90 note: an empty-columns registration is LEGAL here — kickoff and
            # seed flows register name-first shapes routinely. The junk-table fatality
            # is fixed render-side: database_scaffold synthesises an `id` PK instead of
            # raising, mirroring what render_models always did.)
            #
            # #590 — EMPTY IS "UNSPECIFIED", NEVER "THE TABLE HAS NO COLUMNS". FIX #90 made an
            # empty-columns registration legal for a table nobody has described yet; it must
            # not also mean a re-registration can DESTROY a schema that is already known.
            # A table with zero columns cannot exist — database_scaffold synthesises an `id`
            # PK rather than raising, which is the system already saying "empty carries no
            # information". So the merge-upsert has to treat it exactly like ``schema=None``.
            #
            # r133 ground truth (event stream, `table_registered` for `my_list`):
            #     03:17:05 cols=4  by=orchestrator      … registered at kickoff
            #     04:37:21 cols=3  by=orchestrator
            #     04:57:03 cols=0  by=BACKEND           <- the lane re-registered, no columns
            #     04:57:29 cols=0  by=orchestrator      <- the status flip propagated it
            # 26s later the skeleton regenerated and baked in `class MyList(Base): id`, the
            # PK-only model behind #568's live cross-user leak. Its sibling `ratings` was never
            # touched after 04:38 and kept all 4 columns — the difference is only WHO wrote last.
            # Scanned across 56 runs: 2 wipes (r133 `my_list`, r119 `profiles` 5→0, both by the
            # backend lane). r119 survived purely by luck — a later registration restored the
            # columns 63s on; the wipe is fatal exactly when it is the LAST write before
            # scaffolding. Column REDUCTIONS (45 seen) are left alone: those are real schema
            # revisions, and the 23 spine `users` 6→4 shrinks provably never reach the model
            # (the framework re-synthesises spine tables — verified in r103/r113/r115).
            if not (stored_schema.get("columns") or []):
                _known = ((existing or {}).get("schema") or {}).get("columns") or []
                if _known:
                    stored_schema = (existing or {}).get("schema")
                    _wiped_by = actor
        else:
            stored_schema = (existing or {}).get("schema") or {}
        table = {
            **(existing or {}),
            "id": table_id,
            "name": name,
            "status": status or (existing or {}).get("status") or "defined",
            "provider": provider or (existing or {}).get("provider"),
            "schema": stored_schema,
            "metadata": {
                **((existing or {}).get("metadata") or {}),
                **(metadata or {}),
                # #590: leave a breadcrumb in the artifact so the attempt is diagnosable
                # offline — the event stream alone would show only the preserved columns.
                **({"schema_wipe_prevented_by": _wiped_by} if _wiped_by else {}),
            },
            "_updated_by": agent,
            "_updated_at": now,
        }
        new_status = (table.get("status") or "").lower()
        self._tables.update(
            lambda m: m.set(table_id, table, actor),
            change_info={"agent": actor},
        )
        self._emit("table_registered", table, recipients=[])
        if new_status == "implemented":
            # Symmetric to endpoint_implemented (backend subscribes to BOTH;
            # the table event was never emitted → a dead subscription, found in
            # the 2026-06-12 event-flow audit). Emit so the subscription is
            # live, then cascade the impl.table.* task completion (#43).
            self._emit("table_implemented", table, recipients=[], priority="normal")
            if getattr(self, "_workhub", None) is not None:
                try:
                    self._workhub.sync_impl_table_completed(name, agent=actor)
                except Exception:
                    pass
        return table

    def list_tables(self, provider: str = None) -> Dict[str, dict]:
        tables = self._tables.value()
        if provider is None:
            return tables
        return {k: v for k, v in tables.items() if v.get("provider") == provider}

    def get_table(self, name: str) -> Optional[dict]:
        return self._tables.value().get(name)

    # ------------------------------------------------------------------
    # ui_page contract surface (A1→A3, 2026-06-12) — mirrors register_table.
    # Shape follows TABLE (name-keyed, defined→implemented, no breaking-change
    # machinery) not ENDPOINT (ui_page consumes endpoints; it isn't consumed).
    # As of A3 the impl.page.<name> / impl.component.<name> task cascade lives
    # HERE (register_ui_page/register_ui_component → sync_impl_page_completed /
    # sync_impl_component_completed) — workhub is now a thin delegate that no
    # longer stores ui_pages.
    # ------------------------------------------------------------------

    @staticmethod
    def _ui_snake(name: str) -> str:
        """PascalCase component name → snake page id (round 38 case-dup fix)."""
        import re as _re
        if _re.search(r"[A-Z]", str(name or "")):
            snake = _re.sub(r"(?<!^)(?=[A-Z])", "_", str(name)).lower()
            snake = _re.sub(r"_+", "_", snake).strip("_")
            if snake:
                return snake
        return str(name or "")

    def _autoregister_ui_consumers_627(self, rec: dict, actor: str) -> None:
        """#627/#629 — A PAGE OR COMPONENT THAT DECLARES `apis_used` IS A CONSUMER OF THEM.

        `_record_breaking_change` is a complete mechanism: it finds the endpoint's registered
        consumers, sends each an urgent event, and auto-creates a fix task per consumer agent.
        It is dead in most runs because nothing registers consumers — `register_consumer` is an
        LLM TOOL, so it fires only when a lane thinks to call it.

        Measured at EMIT TIME, from each event's own `recipients` field — the only reading that
        answers "was anyone actually told": of **1129** breaking changes across 42 runs, **33
        (2.9%)** reached anybody. Replaying the corpus in timestamp order and registering
        consumers from records that existed BEFORE each event:

            pages only (#627)        +324  ->  357 (31.6%)
            + components (#629)      +320  ->  677 (60.0%)

        The two halves are near-equal because components carry the endpoints pages do not:
        `GET /api/search` was 40 of the unrouted, `GET /api/titles/trending` 29. `response_key_changed` alone accounts for 583 of the total, which is exactly
        the shape of the crashes the verifier then files as unowned P0s ("Landing page renders
        blank", "default-imported listTitles is an object, not a function").

        That figure took three attempts and both wrong ones are recorded on purpose:
          * "25% → 58%" read the FINAL consumer store, which accumulates all run long and so
            credits consumers that did not exist when the event fired. A final-state store is
            not a timeline — the same mistake the squash-merge reading made in #622.
          * "2.9% → 25.0%" fixed the timeline but compared endpoint ids with a hand-rolled
            string match, missing that `endpoint_id()` already collapses `{param}` → `{}`
            (PROPOSAL #39). Do not reimplement the code's normalization in a measurement —
            call it. (A "fix" for that non-problem was written and reverted.)

        The link already exists in the framework's own records: 435 of 738 registered pages
        carry a non-empty `apis_used`, and all 754 entries are already in the canonical
        ``METHOD /path`` form that matches `endpoint_id` — no new source of truth, no LLM
        discretion. The residual 75% are endpoints no page declares; widening that source is a
        separate question and is NOT attempted here.

        The owner is the FRONTEND lane, from the page's own path, falling back to the lane a UI
        page belongs to by definition — never `created_by`, which is the orchestrator for 417 of
        those 754 entries and would repeat #626's "assigned to someone who cannot fix it".

        ``pending=True`` so a page declaring an endpoint before it is published is queued and
        auto-promoted rather than rejected by the L1 gate. Best-effort throughout: a page
        registration must never fail because of a consumer row.
        """
        try:
            apis = rec.get("apis_used") or []
            if not apis:
                return
            path = str(rec.get("path") or "")
            owner = None
            try:
                from .bug_triage import find_owning_agent_for_file
                owner = find_owning_agent_for_file(path)
            except Exception:
                owner = None
            # A ui_page IS frontend territory; `created_by` is the registrar, not the fixer.
            owner = owner if owner in ("frontend", "backend") else "frontend"
            for endpoint_id in apis:
                if not isinstance(endpoint_id, str) or " " not in endpoint_id:
                    continue
                try:
                    self.register_consumer(
                        endpoint_id=endpoint_id,
                        file_path=path or f"{rec.get('kind') or 'ui'}:{rec.get('name')}",
                        agent=owner,
                        pending=True,
                        metadata={"auto_registered_by": "register_ui_page#627",
                                  "ui_page": rec.get("name")},
                    )
                except Exception:
                    continue
        except Exception:
            return

    def register_ui_page(self, name: str, route: str = "", component: str = "",
                         apis_used: list = None, components: list = None,
                         path: str = "", status: str = "defined",
                         agent: str = "", **metadata: Any) -> dict:
        from ._role_gate import require_allowed_actor
        require_allowed_actor(
            method_name="register_ui_page",
            agent=agent,
            provider=None,
            # A3 (2026-06-12): widened from {frontend, orchestrator} when
            # workhub.update_ui_page became a thin delegate to this method.
            # The old workhub path was UNGATED and its shadow-write swallowed
            # PermissionError, so EVERY agent holding the registryhub_register_ui_page
            # tool (orchestrator/backend/frontend/verifier/debugger — see
            # tool_bundles._bundle_workhub_tools grants) could write a ui_page.
            # backend/verifier/debugger are added here to preserve that
            # previously-succeeding behavior; the implemented→defined downgrade
            # below still keeps lifecycle authority with the orchestrator audit.
            allowed_set={"frontend", "orchestrator", "backend", "verifier",
                         "debugger"},
            target_label="registryhub.register_ui_page",
            error_extra=(
                "frontend lane owns ui_page registration; the kickoff "
                "coordinator (actor='orchestrator') declares pages during "
                "finalize_kickoff. Route cross-team needs via send_message("
                "to='orchestrator', ...)."
            ),
        )
        # STRUCTURAL GUARD: App.jsx is the FRAMEWORK-OWNED router/entry point. A
        # ui_page whose component (or name) is a reserved frontend identifier — "App"
        # above all — collides with App.jsx's own `export default function App()` and
        # its react-router imports, so the projected router fails to build ("symbol
        # App has already been declared", smoke-notes 2026-06-19 → frontend build
        # broken every cycle → run wedged). Reject at the SOURCE so the frontend entry
        # point stays consistent (the projector also aliases as a backstop). The agent
        # must pick a descriptive page name.
        _RESERVED_FRONTEND_IDENTS = {"App", "BrowserRouter", "Routes", "Route", "React"}
        _cand = {str(component or "").strip(), str(name or "").strip()}
        _clash = _cand & _RESERVED_FRONTEND_IDENTS
        # Reject for AGENT actors (they must rename). The orchestrator's kickoff
        # FINALIZE path is left to pass — raising there would break finalization;
        # the projector's reserved-name aliasing is the build-safety net for it.
        if _clash and str(agent or "") != "orchestrator":
            raise ValueError(
                f"register_ui_page rejected: {sorted(_clash)} is a RESERVED framework "
                f"identifier — App.jsx is the framework-owned router/entry point, NOT a "
                f"page. Rename the page component to something descriptive (e.g. "
                f"'NotesAppPage', 'HomePage') and re-register; pages never share App.jsx's name."
            )
        name = self._ui_snake(name)
        # LIFECYCLE AUTHORITY (mechanism #54): only the framework audit
        # (orchestrator) may flip a page to implemented; an agent self-claiming
        # it is downgraded to defined.
        if str(status or "").lower() == "implemented" and agent != "orchestrator":
            status = "defined"
        actor = agent or "registryhub"
        now = time.time()
        _pages_now = self._ui_pages.value() or {}
        # #593 — A PAGE IS ITS ROUTE. The store is keyed by NAME, so the two seeding paths
        # (`<name>_page` from the #225 design-screen seed, `<name>` from the contract) each
        # created their OWN record for one route. Measured over 45 runs: 28 duplicate routes in
        # 6 runs — and ALL 28 disagree on `apis_used` and/or `components`. r142 (a
        # *** MULTI-MILESTONE VALIDATED *** run) carries 9, r133 carries 8. r142 `/games`:
        #     page:ui:games_page  apis ['GET /api/profiles']  comps [TopNav, PosterRail]
        #     page:ui:games       apis ['GET /api/titles']    comps [top_nav, category_header,
        #                                                            hero_billboard, poster_rail]
        # both `implemented`, 6 minutes apart, both from the orchestrator. The router dispatches
        # on the ROUTE, so one page has two contracts and every consumer that iterates the store
        # (frontend_audit, remediation_dispatcher, the delivery gate's ui_page_unwired) acts on
        # whichever it reaches first — dict-insertion order.
        #
        # Honest scope: this is contract hygiene, NOT a fidelity fix. Duplicate-route screens
        # score 0.641 against 0.624 for single-record screens, and the within-run paired deltas
        # swing +0.183 to -0.252 — no effect. What it removes is the NON-DETERMINISM.
        #
        # Merging is strictly not-worse than the status quo: both records are already live and
        # already audited, so the union of their apis_used is exactly the set the audit demands
        # today — it just stops depending on which record a reader happens to hit first.
        # #596 — A PAGE'S `path` MUST BE ABLE TO BE ITS COMPONENT'S FILE. frontend_audit states
        # the canonical layout ("a page's root component lives in src/pages/, name == filename")
        # but nothing enforced it at the write boundary, so a record could name two different
        # files at once. Measured over 623 records carrying BOTH fields, 16 disagree (2.6%, 4
        # runs), in two distinct shapes:
        #     r54  every page      component=<X>Page      path stem=App      <- the ROUTER file
        #     r27  browse_home_page component=BrowseHomePage path stem=browse <- a ROUTE, not a file
        #          genre_category_page                       path stem=:slug
        #     r115 login           component=Login        path stem=LoginPage
        #     r139 title_detail    component=BrowseHomePage path stem=TitleDetailPage
        # The first two shapes are unambiguously junk — a route or the framework's own entry
        # point is never a page component file — so the path is dropped and the audit's
        # canonical `src/pages/<Component>.jsx` lookup takes over.
        #
        # The last two are NOT arbitrated here, deliberately: both stems are plausible page
        # components and the corrupted field differs between them (r115's `component` looks
        # right, r139's looks wrong — its title_detail page claims BrowseHomePage). Guessing
        # would have made r139 worse. They get a `path_component_mismatch` breadcrumb and are
        # left exactly as written. r115 is what this costs: its lane-authored 162-line
        # `Login.jsx` stays orphaned behind the framework's 72-line `LoginPage.jsx` until an
        # arbiter exists.
        if path and component:
            _stem = str(path).replace("\\", "/").rsplit("/", 1)[-1].rsplit(".", 1)[0]
            if _stem != str(component).strip():
                if (not re.fullmatch(r"[A-Z][A-Za-z0-9]*", _stem or "")
                        or _stem in _RESERVED_FRONTEND_IDENTS):
                    metadata = {**(metadata or {}), "path_rejected_596": str(path)}
                    path = ""
                else:
                    metadata = {**(metadata or {}),
                                "path_component_mismatch": f"{component} vs {_stem}"}

        _alias = ""
        if route and name not in _pages_now:
            _r = str(route).strip()
            for _k, _v in _pages_now.items():
                if isinstance(_v, dict) and str(_v.get("route") or "").strip() == _r:
                    _alias, name = name, _k       # keep the FIRST-registered key stable
                    break
        existing = _pages_now.get(name) or {}

        def _union(old: Any, new: Any) -> list:
            """Order-preserving union — the fuller contract, no duplicates."""
            out: List[Any] = []
            for _src in (old or [], new or []):
                for _x in _src:
                    if _x not in out:
                        out.append(_x)
            return out

        rec = {
            **existing,
            "id": f"page:ui:{name}", "name": name, "kind": "ui_page",
            "route": route or existing.get("route", ""),
            "component": component or existing.get("component", ""),
            "apis_used": (_union(existing.get("apis_used"), apis_used) if _alias
                          else (apis_used if apis_used is not None
                                else existing.get("apis_used", []))),
            "components": (_union(existing.get("components"), components) if _alias
                           else (components if components is not None
                                 else existing.get("components", []))),
            "path": path or existing.get("path", ""),
            "status": status or existing.get("status") or "defined",
            "metadata": {
                **(existing.get("metadata") or {}),
                **(metadata or {}),
                # #593: the alias stays on the record — a reader looking for the name the
                # other seeding path used must still be able to find this page.
                **({"merged_route_aliases": _union(
                    (existing.get("metadata") or {}).get("merged_route_aliases"),
                    [_alias])} if _alias else {}),
            },
            "_updated_by": agent, "_updated_at": now,
        }
        # PROPOSAL #47 (v2): a thin/placeholder ui_page (no route/component yet) is a
        # SUPPORTED design-phase registration (scan_pages_without_files +
        # test_page_without_path_field_is_silently_ignored treat it as a placeholder), so
        # registration stays PERMISSIVE here. The malformed-entry handling that keeps a
        # route-less placeholder from permanently blocking delivery now lives in the
        # delivery gate's ui_page_unwired computation (it skips entries with no real
        # '/'-route) — not at registration.
        if not existing:
            rec["created_by"] = agent
            rec["created_at"] = now
        self._ui_pages.update(lambda m: m.set(name, rec, actor),
                              change_info={"agent": actor})
        self._emit("ui_page_registered", rec, recipients=[])
        self._autoregister_ui_consumers_627(rec, actor)
        if str(rec.get("status") or "").lower() == "implemented":
            self._emit("ui_page_implemented", rec, recipients=[], priority="normal")
            # A3 (2026-06-12): RegistryHub now OWNS the impl.page.<name> task
            # cascade (moved out of workhub when workhub became a thin
            # delegate) — symmetric to register_table → sync_impl_table_completed.
            if getattr(self, "_workhub", None) is not None:
                try:
                    self._workhub.sync_impl_page_completed(name, agent=actor)
                except Exception:
                    pass
        return rec

    def list_ui_pages(self) -> Dict[str, dict]:
        return self._ui_pages.value() or {}

    def get_ui_page(self, name: str) -> Optional[dict]:
        return self._ui_pages.value().get(self._ui_snake(name))

    def register_ui_component(self, name: str, component: str = "",
                              apis_used: list = None, status: str = "defined",
                              agent: str = "", **metadata: Any) -> dict:
        actor = agent or "registryhub"
        now = time.time()
        existing = self._ui_components.value().get(name) or {}
        rec = {
            **existing,
            "id": f"component:ui:{name}", "name": name, "kind": "ui_component",
            "component": component or existing.get("component", ""),
            "apis_used": (apis_used if apis_used is not None
                          else existing.get("apis_used", [])),
            "status": status or existing.get("status") or "defined",
            "metadata": {**(existing.get("metadata") or {}), **(metadata or {})},
            "_updated_by": agent, "_updated_at": now,
        }
        if not existing:
            rec["created_by"] = agent
            rec["created_at"] = now
        self._ui_components.update(lambda m: m.set(name, rec, actor),
                                   change_info={"agent": actor})
        self._emit("ui_component_registered", rec, recipients=[])
        # #629: a COMPONENT that declares `apis_used` is a consumer too — same argument as #627
        # and the same field. 192 of 901 registered components carry one, and they cover exactly
        # what the page-only version could not: `GET /api/search` (40 of the unrouted),
        # `GET /api/titles/trending` (29), `GET /api/profiles`. Measured on the same
        # timestamp-ordered replay, pages alone take routing 2.9% -> 31.6%; adding components
        # takes it to **60.0%**. A component record has no `path`, so the owner falls back to
        # the lane a UI component belongs to by definition.
        self._autoregister_ui_consumers_627(rec, actor)
        # A3 (2026-06-12): RegistryHub now OWNS the impl.component.<name> task
        # cascade (moved out of workhub when workhub became a thin delegate).
        if str(rec.get("status") or "").lower() == "implemented" and getattr(self, "_workhub", None) is not None:
            try:
                self._workhub.sync_impl_component_completed(name, agent=actor)
            except Exception:
                pass
        return rec

    def list_ui_components(self) -> Dict[str, dict]:
        return self._ui_components.value() or {}

    def get_ui_component(self, name: str) -> Optional[dict]:
        return self._ui_components.value().get(name)

    def backfill_ui_pages_from_workhub(self) -> int:
        """One-time migration: import legacy ui_page/ui_component records that
        live in a pre-A1 workhub_pages.json but not yet here — the
        resume-of-a-pre-A1-run case. Post-A3 the RegistryHub is the sole owner
        for fresh runs, so this is a no-op there; it survives only to recover
        ui_pages from old on-disk snapshots on RESUME.

        Idempotent: only names ABSENT here are imported, so a re-run never
        reverts a status the live writes already advanced. Bypasses the role
        gate (system migration, not an agent call)."""
        wh = getattr(self, "_workhub", None)
        if wh is None:
            return 0
        migrated = 0
        try:
            present = self._ui_pages.value()
            add = {n: p for n, p in (wh.get_ui_pages() or {}).items()
                   if n not in present}
            if add:
                def _mut(m):
                    for n, p in add.items():
                        m = m.set(n, {**p, "name": n}, "system")
                    return m
                self._ui_pages.update(
                    _mut, change_info={"system": "backfill_ui_pages"})
                migrated += len(add)
            present_c = self._ui_components.value()
            add_c = {n: c for n, c in ((wh.get_ui_components() or {})
                     if hasattr(wh, "get_ui_components") else {}).items()
                     if n not in present_c}
            if add_c:
                def _mutc(m):
                    for n, c in add_c.items():
                        m = m.set(n, {**c, "name": n}, "system")
                    return m
                self._ui_components.update(
                    _mutc, change_info={"system": "backfill_ui_components"})
                migrated += len(add_c)
        except Exception:
            pass
        return migrated

    def update_table_schema(
        self, name: str, schema: dict, agent: str = "",
    ) -> dict:
        from ._role_gate import require_allowed_actor
        require_allowed_actor(
            method_name="update_table_schema",
            agent=agent,
            provider=None,
            allowed_set={"backend", "database_worker"},
            target_label="registryhub.update_table_schema",
            error_extra=(
                "backend lane owns table schema mutations. Route "
                "cross-team needs via EventHub api_requirement or "
                "send_message(to='orchestrator', ...)."
            ),
        )
        table = self.get_table(name)
        if not table:
            return {"error": f"Table not found: {name}"}
        old_schema = table.get("schema") or {}
        new_schema = schema or {}
        breaking = self.detect_table_breaking_change(old_schema, new_schema)
        if breaking["is_breaking"]:
            actor = agent or "registryhub"
            now = time.time()
            key = f"breaking_table:{name}:{now}"
            payload = {
                "id": key, "table_name": name, "breaking": breaking,
                "created_at": now, "_updated_by": agent,
            }
            self._table_breaking_changes.update(
                lambda m: m.set(key, payload, actor),
                change_info={"agent": actor},
            )
            self._emit(
                "table_breaking_change_detected", payload,
                recipients=[], priority="urgent",
            )
        return self.register_table(
            name, schema=new_schema, provider=table.get("provider"),
            agent=agent, status=table.get("status", "defined"),
        )

    def register_table_consumer(
        self,
        table_name: str,
        file_path: str,
        agent: str,
        metadata: dict = None,
    ) -> dict:
        # Deliberately ungated on actor identity — `agent` is the
        # CONSUMER, not the owner. The L1 write-time gate
        # (schema_mismatch) below is the only enforcement.
        table = self.get_table(table_name)
        if not table:
            return {
                "error": "table_not_registered",
                "table_name": table_name,
                "hint": "Call registryhub_register_table first.",
            }
        if metadata and "expected_columns" in metadata:
            # ``expected_columns`` is a flat ``{column: type}`` map (the
            # consumer states the columns it reads). The stored schema is now
            # the canonical ``{"columns":[…]}`` shape, so flatten it to the
            # same ``{column: type}`` form before subset-checking — otherwise
            # the check would look for the consumer's columns under the single
            # ``"columns"`` key and always report them missing.
            mismatch = _schema_subset_check(
                metadata["expected_columns"],
                self._schema_as_col_map(table.get("schema", {})),
            )
            if mismatch:
                return {
                    "error": "schema_mismatch",
                    "table_name": table_name,
                    "missing_fields": mismatch.get("missing"),
                    "type_mismatches": mismatch.get("type_mismatches"),
                    "hint": (
                        "Fix consumer code to match table schema, "
                        "or coordinate with backend."
                    ),
                }
        now = time.time()
        key = f"{table_name}|{file_path}|{agent}"
        consumer = {
            "id": key,
            "table_name": table_name,
            "file_path": file_path,
            "agent": agent,
            "metadata": metadata or {},
            "created_at": now,
            "_updated_by": agent,
            "_updated_at": now,
        }
        self._table_consumers.update(
            lambda m: m.set(key, consumer, agent),
            change_info={"agent": agent},
        )
        self._emit("table_consumer_registered", consumer, recipients=[])
        return consumer

    def get_table_consumers(self, table_name: str) -> List[dict]:
        """Signature parity with ``get_consumers(endpoint_id)``."""
        return [
            c for c in (self._table_consumers.value() or {}).values()
            if c.get("table_name") == table_name
        ]

    def register_seed_data(
        self,
        table_name: str,
        row_count: int,
        sample_excerpt: Optional[List[dict]] = None,
        agent: str = "",
    ) -> dict:
        from ._role_gate import require_allowed_actor
        require_allowed_actor(
            method_name="register_seed_data",
            agent=agent,
            provider=None,
            allowed_set={"backend", "database_worker"},
            target_label="registryhub.register_seed_data",
            error_extra=(
                "seed data registration is the backend lane's "
                "responsibility (database_worker admitted for spawn parity)."
            ),
        )
        if not isinstance(row_count, int) or row_count < 0:
            return {"error": "row_count must be a non-negative integer"}
        existing_table = self._tables.value().get(table_name)
        if existing_table is None:
            return {"error": (
                f"table not registered: {table_name!r} "
                f"(call register_table first)"
            )}
        sample = list(sample_excerpt or [])[:3]
        now = time.time()
        record = {
            "table_name": table_name,
            "row_count": row_count,
            "sample_excerpt": sample,
            "registered_by": agent or "database",
            "registered_at": now,
        }
        self._seed_registrations.update(
            lambda m: m.set(table_name, record, agent or "database"),
            change_info={"agent": agent or "database"},
        )
        self._emit("seed_registered", record, recipients=[])
        return record

    def get_seed_data(self, table_name: str) -> Optional[dict]:
        return self._seed_registrations.value().get(table_name)

    def list_seed_registrations(self) -> Dict[str, dict]:
        return dict(self._seed_registrations.value() or {})

    @staticmethod
    def _schema_as_col_map(schema: Any) -> Dict[str, str]:
        """Flatten ANY accepted table-schema shape (flat map, ``{"columns":
        [...]}``, or bare list) to a ``{column_name: type}`` map so the
        breaking-change diff is shape-agnostic — it compares column NAMES and
        TYPES, not the container shape. (Without this, a canonical stored
        old-schema diffed against a flat-map new-schema would compare the
        single key ``"columns"`` against the real column names.)"""
        from .database_scaffold import normalize_columns
        cols = normalize_columns(schema)
        out: Dict[str, str] = {}
        for c in cols:
            if isinstance(c, dict):
                cn = str(c.get("name") or "").strip()
                if cn:
                    out[cn] = str(c.get("type") or "")
        return out

    def detect_table_breaking_change(
        self, old_schema: dict, new_schema: dict,
    ) -> dict:
        old_schema = self._schema_as_col_map(old_schema or {})
        new_schema = self._schema_as_col_map(new_schema or {})
        removed_columns: list = sorted(
            set(old_schema.keys()) - set(new_schema.keys())
        )
        type_changed_columns: list = sorted(
            k for k in old_schema.keys() & new_schema.keys()
            if old_schema[k] != new_schema[k]
        )
        is_breaking = bool(removed_columns or type_changed_columns)
        return {
            "is_breaking": is_breaking,
            "removed_columns": removed_columns,
            "type_changed_columns": type_changed_columns,
        }

    def get_table_breaking_changes(self, since_ts: float = None) -> list:
        items = list(self._table_breaking_changes.value().values())
        if since_ts is not None:
            items = [b for b in items if b.get("created_at", 0) >= since_ts]
        items.sort(key=lambda b: b.get("created_at", 0), reverse=True)
        return items

    # ------------------------------------------------------------------
    # PR 4 (hub-responsibility-split plan, rank 4) retired the MCP
    # registry methods to ``multi_agent/runtime/mcp_registry.py``.
    # Retired methods:
    #   * register_mcp_server, get_mcp_servers
    #   * register_mcp_tool, get_mcp_tools
    #   * register_mcp_consumer, get_mcp_consumers
    # ------------------------------------------------------------------

    def get_endpoints(self) -> Dict[str, dict]:
        return self._endpoints.value()

    def get_versions(self) -> Dict[str, int]:
        return {
            "registryhub_endpoints": self._endpoints.get_version(),
            "registryhub_schemas": self._schemas.get_version(),
            "registryhub_consumers": self._consumers.get_version(),
            "registryhub_contract_tests": self._contract_tests.get_version(),
            "registryhub_reviews": self._api_reviews.get_version(),
            "registryhub_breaking_changes": self._breaking_changes.get_version(),
            "registryhub_tables": self._tables.get_version(),
            "registryhub_ui_pages": self._ui_pages.get_version(),
            "registryhub_ui_components": self._ui_components.get_version(),
        }

    def register_verification_chain(self, name: str, steps: list,
                                    description: str = "", agent: str = "") -> dict:
        """Register a verifier-designed API chain (user design 2026-06-12):
        chains are CONTRACT SURFACE — registered like endpoints/tables, with
        BOUNDARY validation (round 35: file-written chains drifted schema and
        were silently dropped). Steps are normalized here; malformed input is
        rejected WITH teaching. Execution results are recorded back via
        ``record_chain_result`` so the registry shows pass/fail history."""
        # FREEZE-ON-GREEN (2026-07-01): once business_chain has passed, RE-AUTHORING an
        # EXISTING chain is a NO-OP while the contract is unchanged — a verifier that keeps
        # re-writing a passing chain into a broken one caused a regression↔restore OSCILLATION
        # that wedged delivery for 75min (run-25). The already-passing chain is kept. A NEW
        # chain name (add coverage) and a CHANGED contract (next milestone → different eps set;
        # frozen-eps set by framework_validation.snapshot_passing_chains) are unaffected. The
        # framework's own coverage-completion + the regression-guard restore write the store
        # directly (not via this method), so neither is blocked.
        _frozen_eps = getattr(self, "_chains_frozen_eps", None)
        if _frozen_eps is not None and str(name) in (self._verification_chains.value() or {}):
            try:
                _cur_eps = set((self._endpoints.value() or {}).keys())
            except Exception:
                _cur_eps = None
            if _cur_eps is not None and _cur_eps == _frozen_eps:
                return {
                    "frozen": True, "name": str(name),
                    "detail": ("business_chain is GREEN and the contract is unchanged, so this "
                               "chain is FROZEN — re-authoring a passing chain is a no-op (the "
                               "existing passing chain is kept). This prevents regressing a "
                               "clean gate. To ADD coverage use a NEW chain name; the freeze "
                               "lifts automatically at the next milestone (new endpoints)."),
                }
        from .chain_executor import (
            normalize_steps,
            undecidable_access_expectations,
            unsatisfiable_expectation_pairs,
        )
        norm, errors = normalize_steps(steps)
        if errors or not norm:
            return {"error": (
                "chain rejected: " + ("; ".join(errors) or "no valid steps") +
                ". Each step needs method+path (or endpoint='METHOD /path'), "
                "optional body/expect/save/auth — see the chain spec.")}
        # #586: reject a chain that asks ONE request to answer two ways. Measured across the
        # arc: of the 23 broken-step instances in the runs that DIED on business_chain_failing,
        # 11 were this shape — a step demanding a non-2xx on a request an earlier/later step in
        # the SAME chain demands succeed (the app cannot do both, so the chain can never pass).
        # It also actively MISTEACHES the lane: chasing the impossible 400 in r132, the backend
        # made the endpoint require a header the harness cannot send, taking the failing-chain
        # count from 1 to 5. Telling the verifier HERE lets it fix the chain; #570/#580 remain
        # as the runtime net for chains registered by an older framework (#59c).
        _bad = unsatisfiable_expectation_pairs(norm)
        if _bad:
            _d = "; ".join(f"step[{i}] expects success and step[{j}] expects only a non-2xx "
                           f"for the SAME request ({p})" for i, j, p in _bad[:3])
            return {"error": (
                "chain rejected: unsatisfiable expectations — " + _d +
                ". One request cannot return two different statuses. If you meant to test a "
                "REJECTION, make it a genuinely different request: a different actor (auth), "
                "a foreign id in the path/query, or a different body. A step CAN set `headers` "
                "(#686), but not Authorization — actor identity comes from `auth`, so "
                "'the same call as a different user' must use a different token.")}
        # #591: the MIRROR of #586 — an expectation nothing can FALSIFY. A business step that
        # accepts both a 2xx and 401/403 passes whether the app served the data or refused the
        # caller, so it proves nothing about access control while still counting toward the
        # green chain total. Arc-wide: 56 such steps in 16 runs, sitting on exactly the
        # resources every owner-scoping leak lived on (/api/my-list x26, rating x8,
        # /api/continue-watching x6) — r133 (the #568 live leak) has 12, r142 has 13.
        _blind = undecidable_access_expectations(norm)
        if _blind:
            _d = "; ".join(f"step[{i}] {p} expects {c}" for i, p, c in _blind[:3])
            return {"error": (
                "chain rejected: undecidable access expectation — " + _d +
                ". Accepting a 2xx AND 401/403 for the same step means it passes whether the "
                "request was SERVED or REFUSED, so it cannot detect a cross-user leak or a "
                "wrongly-denied owner. Decide what this actor should get: keep the 2xx for the "
                "OWNER, and put the denial in a SEPARATE step that uses a different actor "
                "(auth) or a foreign id. Control-plane paths (/auth, /oauth, /api/v1/*, "
                "/health, /.well-known) are exempt; 409 and 404 are not denial codes.")}
        # PROPOSAL #42 (user): every chain step MUST exercise a REGISTERED endpoint. A
        # chain that references an endpoint which doesn't exist tests a phantom (404/422)
        # and fails business_chain forever (the verifier authors loose paths). All
        # framework endpoints (/auth/*, /oauth/*, /api/v1/*, /health, /.well-known) AND the
        # business endpoints are in the registry, so "must be registered" needs NO
        # whitelist. Match via endpoint_id (param-NAME-agnostic + :id↔{id}, PROPOSAL #1/#29),
        # so /api/notes/{id} in a chain matches a backend /api/notes/{note_id}. #40's
        # auto-prepended /auth/register is registered too, so it passes.
        registered_ids = set((self._endpoints.value() or {}).keys())
        if registered_ids:  # only enforce once a contract exists (kickoff registered it)
            import re as _re

            def _chain_eid(step):
                # chain paths carry ${var} substitution segments (e.g. /api/notes/${note_id})
                # — collapse those to a path param FIRST so endpoint_id's {param}/:param
                # normalization yields /api/notes/{} (matching the registered endpoint).
                p = _re.sub(r"\$\{[^}]+\}", "{x}", str(step.get("path") or ""))
                # FIX #137 (instagram run-61, live; also seen run-52): a LITERAL numeric
                # segment (GET /api/posts/1 — the verifier binding a REAL seed id into a
                # by-id step) must ALSO match the registered {id} template. It didn't, so
                # the verifier's rewrite-with-real-ids was REJECTED ("endpoints NOT
                # registered: GET /api/posts/1") — locking it out of its own remediation
                # path and leaving the stale failing chain to 404 forever.
                p = _re.sub(r"/\d+(?=/|$)", "/{x}", p)
                return self.endpoint_id(step.get("method") or "GET", p)

            def _chain_eid_ok(s) -> bool:
                if _chain_eid(s) in registered_ids:
                    return True
                # #363: a PURELY negative probe uses an id that must not exist —
                # bind it to the registered TEMPLATE instead of refusing the
                # chain for the property that makes it a probe. It still has to
                # match a real registered route.
                if is_negative_probe_step(s):
                    alt = dict(s)
                    alt["path"] = collapse_last_literal_segment(s.get("path") or "")
                    return _chain_eid(alt) in registered_ids
                return False

            unregistered = sorted({
                _chain_eid(s) for s in norm if s.get("path")
                if not _chain_eid_ok(s)
            })
            if unregistered:
                # Fix #71 (netflix r75, 2026-08-05): a verifier that authors a chain step for
                # an endpoint the contract never defined (r75: PUT /api/profiles/{id} — a
                # hallucinated update-profile route ABSENT from reference_spec.json) gets this
                # reject and RE-SUBMITS the IDENTICAL chain — 38× in r75 — burning deliver-tail
                # cycles (防止浪费token) while business_chain churns. Dedup the identical repeat
                # (same chain name + same unregistered-endpoint set) and ESCALATE the guidance so
                # the verifier DROPS the step instead of looping. Keyed on (name, unregistered)
                # so it SELF-INVALIDATES the moment the missing endpoint IS registered
                # (unregistered shrinks → new key → normal reject). Best-effort: any bookkeeping
                # fault falls through to the plain reject. Additive: FIRST reject is unchanged,
                # the happy path and chain content are untouched. Generalizes to every app/env.
                _escalate = ""
                try:
                    # Count rejects PER unregistered ENDPOINT (not per chain-name/step-set).
                    # r76 (2026-08-05) proved the (name, unregistered)-keyed counter never
                    # escalated: the verifier re-submits the SAME missing endpoint under a
                    # VARYING chain name (and/or a different companion endpoint) each time
                    # (PUT /api/profiles/{} rejected 6×, 0 escalations). Per-endpoint counting
                    # is robust to both — escalate when ANY endpoint in THIS reject has now been
                    # rejected >=2 times across ALL chains. Self-invalidates: once an endpoint is
                    # registered it drops out of `unregistered`, so its count stops advancing.
                    # #664 — #71 COUNTED IN MEMORY, SO IT ALMOST NEVER ESCALATED.
                    # The counter above lived on `self`, while every other fact this hub holds
                    # is a JsonStore on disk. It therefore only advanced while ONE RegistryHub
                    # instance handled both rejects; across a process boundary (or a re-spawned
                    # lane) it reset to zero. Proven directly: same instance escalates on the
                    # 2nd reject, a fresh instance per reject never escalates at all.
                    #
                    # Measured over the 249 run logs: 4928 chain rejections and 4 escalations —
                    # 0.08%. The verifier re-submits the same nonexistent endpoint a median of
                    # 28 times per run (max 126, r98: PUT /api/profiles/{}), and #71's guidance,
                    # which exists precisely to break that loop, was reaching it 4 times total.
                    # Post-#71 runs are not better than pre-#71 ones (median 30 vs 26), which is
                    # what an inert fix looks like.
                    #
                    # Persisting it keeps #71's semantics exactly: per-endpoint, across chain
                    # names, self-invalidating once the endpoint is registered. The in-memory
                    # dict stays as the fallback so a store fault still degrades to a plain
                    # reject, as the contract above promises.
                    _mem = getattr(self, "_chain_reject_endpoint_counts", None)
                    if _mem is None:
                        _mem = {}
                        self._chain_reject_endpoint_counts = _mem
                    try:
                        _counts = dict(self._chain_rejects.value() or {})
                    except Exception:
                        _counts = _mem
                    _repeat = []
                    for _ep in unregistered:
                        _n = int(_counts.get(_ep) or 0) + 1
                        _counts[_ep] = _n
                        _mem[_ep] = _n
                        if _n >= 2:
                            _repeat.append(_ep)
                    try:
                        for _ep in unregistered:
                            self._chain_rejects.set(str(_ep), _counts[_ep], agent="registryhub")
                    except Exception:
                        pass
                    if _repeat:
                        _worst = max(_counts[_ep] for _ep in _repeat)
                        _escalate = (
                            " ⚠ Endpoint(s) [%s] have now been rejected %d times across your "
                            "chains — they are NOT in the registered contract and cannot be "
                            "tested. Re-submitting ANY chain that references them (under any name) "
                            "will keep failing: DROP those steps (or the chain). If delivery "
                            "genuinely needs this coverage, ask the backend lane to implement + "
                            "register the endpoint FIRST." % (", ".join(_repeat), _worst))
                except Exception:
                    _escalate = ""
                # #636 — LEAD WITH THE INSTRUCTION, NOT THE CONTRACT DUMP.
                # The escalation above is correct and it fires; it was simply LAST, behind a
                # dump of every registered endpoint — median 669 chars, max 825 across 45 runs.
                # Measured over the 56 run logs, this rejection is the single largest error
                # class in the corpus: 514 occurrences in 50 of 50 runs, median 18 per run for
                # a median of just 2 distinct causes (r129: 81 rejections, 5 causes). The
                # verifier re-submits the same unsatisfiable chain ~9x per cause.
                #
                # (What the logs CANNOT show: whether the agent read the warning. They truncate
                # at 300 chars, so the escalation appears 0 times in 55 files — an artifact of
                # the log, not evidence about the agent. What is provable is the ORDERING, and
                # #619/#620 already settled that: put what to DO first, the data after.)
                #
                # The dump is also narrowed to the resource actually referenced. "Every endpoint
                # in the contract" is not an answer to "this one is missing"; the sibling
                # endpoints on the same path prefix are.
                _pref = {e.split(" ", 1)[1].rsplit("/", 1)[0] for e in unregistered
                         if " " in e} - {""}
                _kin = sorted(e for e in registered_ids
                              if any(e.split(" ", 1)[-1].startswith(p) for p in _pref))
                _rest = len(registered_ids) - len(_kin)
                _catalog = (", ".join(_kin) if _kin else "(none on that path)")
                if _rest > 0:
                    _catalog += f" — plus {_rest} endpoint(s) on other paths"
                return {"error": (
                    (_escalate.strip() + " " if _escalate else "")
                    + "chain rejected: these steps reference endpoints NOT registered in "
                    "RegistryHub: " + ", ".join(unregistered) + ". A verification chain may "
                    "only exercise endpoints that exist. The BACKEND lane registers endpoints "
                    "(registryhub_register_endpoint) — as the verifier, fix the chain to use "
                    "one that exists. Registered on the same path: " + _catalog + ".")}
        now = time.time()
        actor = agent or "registryhub"
        # #478: IDEMPOTENT re-registration (r52 convergence churn — never delivered). The
        # old code reset EVERY re-register to status='registered' (unrun) + last_result=None,
        # so the verifier's repeated re-registration (r52: 12× per run) kept flipping
        # already-PASSING chains back to unrun → business_chain_failing → delivery-gate
        # churn → 0 release. FIX: when the STEPS are UNCHANGED, PRESERVE the chain's proven
        # status + last_result; only a genuinely NEW or step-CHANGED chain resets to
        # 'registered' (must be re-run). run_chains re-executes all chains each validation,
        # so a preserved status is re-validated — an app regression on unchanged steps is
        # caught on the next run (never masks a real failure). Generalizable to every env.
        _existing = (self._verification_chains.value() or {}).get(str(name))
        if (isinstance(_existing, dict) and _existing.get("steps") == norm
                and _existing.get("status") in ("passing", "framework_blocked")):
            rec = {**_existing,
                   "description": str(description or _existing.get("description", "")),
                   "registered_by": actor, "_updated_at": now}
        else:
            rec = {"id": str(name), "name": str(name),
                   "description": str(description or ""),
                   "steps": norm, "status": "registered",
                   "last_result": None, "last_run_at": None,
                   "registered_by": actor, "_updated_at": now}
        self._verification_chains.update(
            lambda m: m.set(str(name), rec, actor), change_info={"agent": actor})
        # VERIFIER-DRIVEN READ ISOLATION (2026-06-30, user: "must work for ALL envs"): a chain
        # step asserting a by-id read/write must be DENIED (403/404) to a NON-owner is the
        # verifier's domain judgment that the resource is per-user-PRIVATE. Mark that table
        # owner_scoped_reads so the backend regen (render_skeleton_main honours table metadata)
        # projects its reads owner-scoped BY CONSTRUCTION — closing the cross-user data leak the
        # backend agent UNRELIABLY declares (outlook run-9/10: it scoped `messages`, forgot
        # `events` → GET /api/events/{id} returned any user's row). ENV-AGNOSTIC, no global
        # default flip: a PUBLIC resource (social feed) gets NO isolation probe → never scoped.
        try:
            from .chain_executor import _is_cross_user_denial
            _tbl_names = set((self._tables.value() or {}).keys())
            _to_scope = set()
            for _st in norm:
                if not _is_cross_user_denial(_st):
                    continue
                _segs = [s for s in str(_st.get("path") or "").split("?", 1)[0].split("/")
                         if s and s.lower() != "api"]
                if _segs and _segs[0] in _tbl_names:
                    _to_scope.add(_segs[0])
            for _tn in _to_scope:
                _t = self._tables.value().get(_tn)
                if isinstance(_t, dict) and not (_t.get("metadata") or {}).get("owner_scoped_reads"):
                    _t2 = {**_t, "metadata": {**(_t.get("metadata") or {}),
                                              "owner_scoped_reads": True}}
                    self._tables.update(
                        lambda m, _k=_tn, _v=_t2: m.set(_k, _v, actor),
                        change_info={"agent": actor})
        except Exception:
            pass
        self._emit("verification_chain_registered", rec, recipients=[])
        return rec

    def get_verification_chains(self) -> Dict[str, dict]:
        return self._verification_chains.value() or {}

    def record_chain_result(self, name: str, result: dict, agent: str = "") -> dict:
        actor = agent or "registryhub"
        rec = self._verification_chains.value().get(str(name))
        if not isinstance(rec, dict):
            return {"error": f"chain not found: {name}"}
        rec = {**rec,
               "status": "passing" if not result.get("broken") else "failing",
               "last_result": {"broken": result.get("broken") or [],
                               "steps": result.get("steps") or []},
               "last_run_at": time.time()}
        self._verification_chains.update(
            lambda m: m.set(str(name), rec, actor), change_info={"agent": actor})
        return rec

    def snapshot(self) -> Dict[str, Any]:
        return {
            "projects": self._projects.value(),
            "verification_chains": self._verification_chains.value(),
            "endpoints": self._endpoints.value(),
            "schemas": self._schemas.value(),
            "examples": self._examples.value(),
            "mocks": self._mocks.value(),
            "contract_tests": self._contract_tests.value(),
            "providers": self._providers.value(),
            "consumers": self._consumers.value(),
            "api_reviews": self._api_reviews.value(),
            "breaking_changes": self._breaking_changes.value(),
            "tables": self._tables.value(),
            # Cutover 43.20: expose MCP registry + table consumers to the UI so
            # the RegistryHub page can render MCP servers/tools and table dependents.
            "mcp_registry": self._mcp_registry.value(),
            "table_consumers": self._table_consumers.value(),
            # Cutover 43.22: seed-data audit + table schema breaking changes.
            "seed_registrations": self._seed_registrations.value(),
            "table_breaking_changes": self._table_breaking_changes.value(),
            # A1 (2026-06-12): ui_page contract layer — the monitor RegistryHub
            # view renders these alongside endpoints/tables/mcp (it already
            # filters kind==ui_page out of workhub; A2 repoints it here).
            "ui_pages": self._ui_pages.value(),
            "ui_components": self._ui_components.value(),
        }
