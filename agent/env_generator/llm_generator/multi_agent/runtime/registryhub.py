"""The CONTRACT REGISTRY hub ("registryhub"; historical name: RegistryHub).

Registers and lifecycles every contract surface of a generated app: API
endpoints, database tables, consumers (incl. pending intents), contract
tests, examples, breaking changes — and the MCP registry rides alongside.
Renamed from APIHub on 2026-06-11 (user decision, full sweep — tool names,
store filenames, events all use the ``registryhub`` prefix; no back-compat).
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from .eventhub import EventHub
from .json_store import JsonStore


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


class RegistryHub:
    """Apifox-like API registry, schema, consumer, mock, test, and review hub."""

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
                    bare root ``/`` which stays as-is).
        """
        m = str(method or "").upper().strip()
        p = str(path or "").strip()
        if p:
            if not p.startswith("/"):
                p = "/" + p
            if len(p) > 1 and p.endswith("/"):
                p = p.rstrip("/") or "/"
        return f"{m} {p}"

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
        endpoint_id = self.endpoint_id(method, path)
        actor = agent or provider or "registryhub"
        now = time.time()
        old = self._endpoints.get(endpoint_id)
        endpoint = {
            **(old or {}),
            "id": endpoint_id,
            "method": str(method or "").upper(),
            "path": path,
            "status": status or (old or {}).get("status") or "defined",
            "provider": provider or (old or {}).get("provider"),
            "schema": schema or (old or {}).get("schema") or {},
            "metadata": {**((old or {}).get("metadata") or {}), **(metadata or {})},
            "_updated_by": agent,
            "_updated_at": now,
        }
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
        test_id = f"test:{endpoint_id}:{now}"
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
        self._contract_tests.update(
            lambda m: m.set(test_id, test, agent),
            change_info={"agent": agent},
        )
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
        table = {
            **(existing or {}),
            "id": table_id,
            "name": name,
            "status": status or (existing or {}).get("status") or "defined",
            "provider": provider or (existing or {}).get("provider"),
            "schema": (
                schema if schema is not None
                else (existing or {}).get("schema") or {}
            ),
            "metadata": {
                **((existing or {}).get("metadata") or {}),
                **(metadata or {}),
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
            # PermissionError, so EVERY agent holding the workhub_register_ui_page
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
        name = self._ui_snake(name)
        # LIFECYCLE AUTHORITY (mechanism #54): only the framework audit
        # (orchestrator) may flip a page to implemented; an agent self-claiming
        # it is downgraded to defined.
        if str(status or "").lower() == "implemented" and agent != "orchestrator":
            status = "defined"
        actor = agent or "registryhub"
        now = time.time()
        existing = self._ui_pages.value().get(name) or {}
        rec = {
            **existing,
            "id": f"page:ui:{name}", "name": name, "kind": "ui_page",
            "route": route or existing.get("route", ""),
            "component": component or existing.get("component", ""),
            "apis_used": (apis_used if apis_used is not None
                          else existing.get("apis_used", [])),
            "components": (components if components is not None
                           else existing.get("components", [])),
            "path": path or existing.get("path", ""),
            "status": status or existing.get("status") or "defined",
            "metadata": {**(existing.get("metadata") or {}), **(metadata or {})},
            "_updated_by": agent, "_updated_at": now,
        }
        if not existing:
            rec["created_by"] = agent
            rec["created_at"] = now
        self._ui_pages.update(lambda m: m.set(name, rec, actor),
                              change_info={"agent": actor})
        self._emit("ui_page_registered", rec, recipients=[])
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
            mismatch = _schema_subset_check(
                metadata["expected_columns"], table.get("schema", {}),
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

    def detect_table_breaking_change(
        self, old_schema: dict, new_schema: dict,
    ) -> dict:
        old_schema = old_schema or {}
        new_schema = new_schema or {}
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
        from .chain_executor import normalize_steps
        norm, errors = normalize_steps(steps)
        if errors or not norm:
            return {"error": (
                "chain rejected: " + ("; ".join(errors) or "no valid steps") +
                ". Each step needs method+path (or endpoint='METHOD /path'), "
                "optional body/expect/save/auth — see the chain spec.")}
        now = time.time()
        actor = agent or "registryhub"
        rec = {"id": str(name), "name": str(name),
               "description": str(description or ""),
               "steps": norm, "status": "registered",
               "last_result": None, "last_run_at": None,
               "registered_by": actor, "_updated_at": now}
        self._verification_chains.update(
            lambda m: m.set(str(name), rec, actor), change_info={"agent": actor})
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
