"""
Workflow policy registry for configurable agents.

Policies move role-specific runtime gates and finish behavior out of the generic
EnvGenAgent / ConfigurableAgent core.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, FrozenSet, List, Optional, Tuple

from utils.llm import Message


class BaseWorkflowPolicy:
    """Base workflow policy interface.

    ``always_runs()`` — bookkeeping vs gate (PR 2.5-fix-2, 2026-05-29).
    The original first-match-wins ``_apply_finish_policies`` loop was
    structurally fragile: ANY policy that returned a non-None outcome
    starved every later policy in the list, including the
    ``LaneIdleCircuitBreakerPolicy`` whose only job is to bump the
    idle counter. Adversarial review found this bug recurring across
    multiple policy classes (HubConsistencyPolicy, ClaimAssignedTasksPolicy,
    FinishContinuePolicy) — fixing the YAML order once was a one-shot
    patch; the next added policy or YAML re-order would silently
    re-open the deadlock.

    Two-pass dispatch fixes it structurally. A policy whose
    ``always_runs()`` returns ``True`` is invoked in PASS 1
    (bookkeeping) regardless of YAML order or peer outcomes; its
    return value is expected to be ``None``. If a bookkeeping policy
    ever returns a non-None outcome, the dispatcher logs an ERROR
    and discards the outcome — preserving the
    gate-bookkeeping-separation invariant without crashing a running
    finish. PASS 2 then runs the first-match-wins gate loop, skipping
    already-fired bookkeeping policies. The breaker sets
    ``always_runs() -> True``; every gate keeps the default ``False``.
    No YAML edit, no future policy, no order-shuffle can starve the
    breaker again.
    """

    def always_runs(self) -> bool:
        """Bookkeeping marker. See class docstring."""
        return False

    def allow_task_ready(self, agent: Any, message: Any) -> Optional[Tuple[bool, str]]:
        return None

    def allow_resident_wakeup(
        self, agent: Any, message: Any, inbox_msg: Dict[str, Any],
    ) -> Optional[Tuple[bool, str]]:
        """Re-audit (2026-05-29) HIGH #4: resident lanes are woken by
        non-task_ready inbox messages via
        ``_maybe_schedule_resident_message_wakeup``. That path was
        bypassing the policy gates the task_ready path consults, so
        ``DependsOnPolicy`` ("waiting on upstream X") and
        ``VerifierValidationTriggerPolicy`` ("verifier only acts on
        explicit validation triggers") could be silently bypassed —
        any inbox message would wake the lane regardless of its
        readiness contract.

        Default: no opinion (None) — most policies don't care about
        wakeup paths. Subclasses whose ``allow_task_ready`` rejection
        semantics ALSO apply to arbitrary inbox messages should
        override to delegate to ``allow_task_ready`` (see
        ``DependsOnPolicy`` / ``VerifierValidationTriggerPolicy``).

        ``KickoffBootstrapGate`` (round 8h Stage 1; replaces the
        retired ``ImplementationBootstrapPolicy``) deliberately does
        NOT override this — its ``allow_task_ready`` has a side effect
        (flipping ``_kickoff_bootstrapped``) and the
        bootstrap-vs-wakeup interaction is already gated inline in
        ``messaging.py``.
        """
        return None

    async def handle_finish(
        self,
        agent: Any,
        *,
        tool_name: str,
        tool_args: Dict[str, Any],
        tool_call: Any,
        tool_call_id: str,
        messages: List[Any],
        files_created: List[str],
        files_modified: List[str],
    ) -> Optional[Dict[str, Any]]:
        return None


def _is_validation_ready_signal(message: Any) -> bool:
    """True if ``message`` is the hub-emitted ``validation_ready`` signal (§6 C1).

    RegistryHub emits it when EVERY business endpoint is ``implemented``
    (lifecycle.all_business_endpoints_implemented). It is the AUTHORITATIVE
    "backend contract complete" trigger and must bypass the lane-completion gates
    (``DependsOnPolicy``, ``VerifierValidationTriggerPolicy``) — those rely on
    lanes cleanly finishing, which stalls when a lane drifts into a post-impl
    bookkeeping loop (smoke #6/#7). Belt-and-suspenders across delivery paths."""
    try:
        metadata = getattr(message, "metadata", None) or {}
        tags = {str(t).lower() for t in (metadata.get("tags") or [])}
        signal = " ".join([
            str(metadata.get("event_type") or ""),
            str(metadata.get("msg_type") or ""),
            str(metadata.get("type") or ""),
            str(getattr(message, "message_type", "") or ""),
            str(getattr(message, "payload", "") or ""),
            " ".join(tags),
        ]).lower()
        return "validation_ready" in signal or "all_business_endpoints_implemented" in signal
    except Exception:
        return False


class DependsOnPolicy(BaseWorkflowPolicy):
    def __init__(self, depends_on: List[str]):
        self.depends_on = [str(dep).strip() for dep in (depends_on or []) if str(dep).strip()]

    def allow_task_ready(self, agent: Any, message: Any) -> Optional[Tuple[bool, str]]:
        if not self.depends_on:
            return None
        # §6 C1: the hub's validation_ready signal is authoritative readiness —
        # the hub already confirmed the contract is complete, so don't re-gate on
        # whether the upstream LANES cleanly finished (they may be mid bookkeeping).
        if _is_validation_ready_signal(message):
            return None
        missing = [dep for dep in self.depends_on if dep not in getattr(agent, "_upstream_ready_agents", set())]
        if missing:
            return False, f"waiting on depends_on={missing}"
        return None

    def allow_resident_wakeup(
        self, agent: Any, message: Any, inbox_msg: Dict[str, Any],
    ) -> Optional[Tuple[bool, str]]:
        """If upstream hasn't reached ``task_ready`` yet, this lane
        cannot do useful work on ANY inbox message — not just on a
        literal task_ready. Reuse the dependency-readiness check."""
        return self.allow_task_ready(agent, message)


class KickoffBootstrapGate(BaseWorkflowPolicy):
    """Round 8h Stage 1 + smoke #22 fix — replaces the retired
    ``ImplementationBootstrapPolicy``.

    Old gate (pre Stage 1): filesystem check for
    ``design/spec.{api,database,ui}.json`` — designed for the
    (now-retired) design agent that wrote those files. Post
    round-8e.1 there was no writer; the gate deadlocked every smoke
    (Backend/Frontend rejected every ``task_ready`` with
    ``design gate not ready``, smoke #18 / #19 / #20 all wedged).

    Stage 1 v1 (commit 08872912): hub-driven via
    ``workhub.list_tasks(assignee=agent.agent_id)``. Smoke #22
    surfaced this v1 was TOO STRICT: ``finalize_kickoff`` only
    creates ``implement_endpoint`` + ``implement_table`` tasks (all
    owner=backend post round-8e.1 design+database merge). Frontend
    never gets WorkHub tasks at kickoff finalize → gate rejected
    every Patch B v2 nudge forever ("no tasks assigned to frontend").
    Backend was unblocked (it owns the kickoff-created tasks) but
    Frontend stayed wedged.

    Stage 1 v2 (this commit) — **global kickoff-finalized signal**:
    a lane is bootstrapped when ``RegistryHub`` has any registered
    endpoint OR WorkHub has any task. Either signal proves
    ``finalize_kickoff`` ran (it's the only writer of both). Per-lane
    semantics retired: every lane that subscribes to kickoff_request
    is allowed to start once kickoff finalized — finer routing is the
    orchestrator's job + the lane's own prompt, not this gate.

    Sticky: once bootstrapped, the flag stays. Re-checking the hubs
    on every ``task_ready`` would be redundant — kickoff cannot
    become "un-finalized". For Mn>1 kickoffs the new tasks +
    endpoints are appended to the same hub stores, so the flag stays
    correctly true through the project's entire lifecycle.

    Constructor:
      - ``allowed_starters``: still gates which agent may dispatch
        the first task_ready (in practice always ``['orchestrator']``).
      - ``required_files`` (legacy) is GONE.
    """

    def __init__(self, allowed_starters: List[str]):
        self.allowed_starters = [
            str(v).strip() for v in (allowed_starters or []) if str(v).strip()
        ]

    def allow_task_ready(self, agent: Any, message: Any) -> Optional[Tuple[bool, str]]:
        if getattr(agent, "_kickoff_bootstrapped", False):
            return None

        from_agent = message.header.source_agent_id
        if self.allowed_starters and from_agent not in self.allowed_starters:
            return (
                False,
                f"kickoff bootstrap gate: implementation agent requires "
                f"initial task_ready from {self.allowed_starters} "
                f"(got {from_agent})",
            )

        hubs = getattr(agent, "_hubs", None)
        if hubs is None:
            # Runtime setup race — agent not yet wired to the hubs.
            # Deny with informative reason; the next call (after wiring
            # catches up) will pass cleanly.
            return False, (
                "kickoff bootstrap gate: hubs not yet attached to "
                f"{agent.agent_id} (wiring race)"
            )

        # Global kickoff-finalized signal — accept iff EITHER store
        # shows finalize_kickoff has produced output. Per-lane "has
        # tasks?" gating retired in smoke #22 follow-up; frontend never
        # gets kickoff-created tasks (backend owns endpoints+tables
        # post round-8e.1), so a per-lane check rejects frontend
        # forever even though kickoff has clearly finalized.
        kickoff_finalized = False
        check_results: List[str] = []

        # Signal A: RegistryHub has any registered endpoint. finalize_kickoff
        # is the only writer at kickoff time (actor='orchestrator').
        try:
            registryhub = getattr(hubs, "registryhub", None)
            if registryhub is not None and hasattr(registryhub, "_endpoints"):
                # Hub store private attr is the cleanest way to count
                # WITHOUT churning RegistryHub's public surface for this one
                # gate. value() returns a dict of {endpoint_id: ...}.
                endpoints = registryhub._endpoints.value()
                if endpoints:
                    kickoff_finalized = True
                    check_results.append(
                        f"registryhub_endpoints={len(endpoints)}"
                    )
                else:
                    check_results.append("registryhub_endpoints=0")
        except Exception as exc:
            check_results.append(
                f"registryhub_endpoints_err={exc.__class__.__name__}"
            )

        # Signal B: WorkHub has any task (regardless of assignee). Kept
        # as a parallel signal — finalize_kickoff also writes tasks.
        if not kickoff_finalized:
            try:
                workhub = getattr(hubs, "workhub", None)
                if workhub is not None:
                    tasks = workhub.list_tasks()
                    if tasks:
                        kickoff_finalized = True
                        check_results.append(f"workhub_tasks={len(tasks)}")
                    else:
                        check_results.append("workhub_tasks=0")
            except Exception as exc:
                check_results.append(
                    f"workhub_tasks_err={exc.__class__.__name__}"
                )

        if not kickoff_finalized:
            return False, (
                "kickoff bootstrap gate: no kickoff-finalized signal "
                f"({', '.join(check_results)}). finalize_kickoff has "
                "not produced RegistryHub endpoints OR WorkHub tasks yet. "
                "The lane accepts the next task_ready once kickoff "
                "completes."
            )

        agent._kickoff_bootstrapped = True
        return None


class VerifierValidationTriggerPolicy(BaseWorkflowPolicy):
    def __init__(
        self,
        *,
        allowed_sender: str,
        accepted_tags: List[str],
        accepted_phases: List[str],
        payload_keywords: List[str],
        impl_completion_senders: Optional[List[str]] = None,
    ):
        self.allowed_sender = str(allowed_sender).strip()
        self.accepted_tags = {str(v).strip().lower() for v in (accepted_tags or []) if str(v).strip()}
        self.accepted_phases = {str(v).strip().lower() for v in (accepted_phases or []) if str(v).strip()}
        self.payload_keywords = [str(v).strip().lower() for v in (payload_keywords or []) if str(v).strip()]
        # ⚠2 fix (Theme C robustness, 2026-06-05): the verifier used to wake
        # ONLY on an explicit orchestrator-authored validation trigger. When the
        # orchestrator's coord loop failed to author it, the run STALLED with a
        # finished backend+frontend and an idle verifier (the orchestrator then
        # idle-nudged the knowledge lane — pure noise). So ALSO accept impl-lane
        # completion: when EVERY impl lane (backend+frontend) has sent its
        # finish-notify (``finish(notify=['verifier'])`` → task_ready tagged
        # ``from_<lane>``), self-trigger validation. Gating on ALL impl lanes —
        # not the first — means the verifier never runs docker on a half-built
        # tree; with the required_files gate, "impl lane finished" now implies
        # its build-critical files exist, so this is a sound readiness signal.
        self.impl_completion_senders = {
            str(v).strip().lower()
            for v in (impl_completion_senders if impl_completion_senders is not None
                      else ["backend", "frontend"])
            if str(v).strip()
        }
        self._completed_impl: set = set()

    def allow_task_ready(self, agent: Any, message: Any) -> Optional[Tuple[bool, str]]:
        from_agent = message.header.source_agent_id
        metadata = message.metadata or {}
        tags = {str(t).lower() for t in (metadata.get("tags") or [])}
        phase = str(metadata.get("phase", "")).lower()
        validation_phase = bool(metadata.get("validation_phase", False))
        payload_text = str(message.payload or "").lower()

        # §6 C1 (2026-06-06): the HUB-QUERY trigger — RegistryHub emits ``validation_ready``
        # (recipients=['verifier']) the moment every business endpoint is
        # ``implemented``. The canonical structural trigger; supersedes the fragile
        # lane-finish heuristic below (which stalled when a lane didn't cleanly
        # finish — smoke #6/#7). Admit regardless of sender.
        if _is_validation_ready_signal(message):
            return None

        explicit_trigger = (
            from_agent == self.allowed_sender
            and (
                validation_phase
                or phase in self.accepted_phases
                or bool(tags.intersection(self.accepted_tags))
                or any(keyword in payload_text for keyword in self.payload_keywords)
            )
        )
        if explicit_trigger:
            return None

        # Impl-lane completion fallback: record this lane's finish, and admit the
        # wake only once ALL impl lanes have finished (so validation runs against
        # the complete tree, exactly once, without an orchestrator trigger).
        sender = str(from_agent or "").strip().lower()
        if sender in self.impl_completion_senders:
            self._completed_impl.add(sender)
            if self.impl_completion_senders.issubset(self._completed_impl):
                return None  # all impl lanes done → self-trigger validation
            still_waiting = sorted(self.impl_completion_senders - self._completed_impl)
            return False, (
                f"{agent.agent_id} recorded completion from {sender}; "
                f"awaiting {still_waiting} before self-triggering validation"
            )

        return False, f"{agent.agent_id} requires explicit validation-phase trigger from {self.allowed_sender}"

    def allow_resident_wakeup(
        self, agent: Any, message: Any, inbox_msg: Dict[str, Any],
    ) -> Optional[Tuple[bool, str]]:
        """Verifier must not auto-wake on arbitrary inbox messages —
        the whole point of this policy is "only act on an explicit
        validation-phase trigger". Apply the same gate to
        resident-wakeup messages, with one exemption:
        ``task_created`` events whose new task is assigned to the
        verifier itself ARE legitimate validation-phase triggers
        (kickoff's task_tree synthesis creates ``validate_*`` tasks
        owned by verifier; suppressing those would leave the lane
        idle with its own queue full)."""
        # task_created-for-self exemption now applies at the
        # messaging layer (see _maybe_schedule_resident_message_wakeup
        # in agents/runtime/messaging.py) so it covers ALL policies
        # uniformly — DependsOnPolicy was the second gate to fire
        # after VerifierValidationTriggerPolicy.
        decision = self.allow_task_ready(agent, message)
        if decision is None:
            return None
        return decision


class FinishContinuePolicy(BaseWorkflowPolicy):
    def __init__(self, *, tool_name: str = "finish", followup_message: str = ""):
        self.tool_name = tool_name
        self.followup_message = followup_message

    async def handle_finish(
        self,
        agent: Any,
        *,
        tool_name: str,
        tool_args: Dict[str, Any],
        tool_call: Any,
        tool_call_id: str,
        messages: List[Any],
        files_created: List[str],
        files_modified: List[str],
    ) -> Optional[Dict[str, Any]]:
        if tool_name != self.tool_name:
            return None

        result = await agent._execute_tool(tool_name, tool_args)
        messages.append(Message.assistant(tool_calls=[tool_call]))
        result_str = result.data if result.success else f"Error: {result.error_message}"
        if isinstance(result_str, dict):
            result_str = json.dumps(result_str, indent=2)
        messages.append(Message.tool(str(result_str)[:10000], tool_call_id))
        if self.followup_message:
            messages.append(Message.user(self.followup_message))
        return {"action": "continue"}


class HubConsistencyPolicy(BaseWorkflowPolicy):
    """Block ``finish()`` when the agent has written code without
    registering the corresponding entries in the relevant hubs.

    Hard rule, not a prompt suggestion. The gate intercepts ``finish``,
    counts what the agent has materially changed this session against
    what is registered in the relevant hubs (registryhub_endpoints,
    registryhub_tables, workhub_pages, codehub_commits), and — if a gap
    exists — injects a structured rejection message into the agent's
    own conversation and returns ``{"action": "continue"}`` so the
    agent runs again and fixes the gap before exiting.

    Parameters
    ----------
    expect_hub_kinds:
        Which hub stores the agent is expected to populate. Each entry
        is one of ``registryhub_endpoints``, ``registryhub_tables``,
        ``workhub_pages``, ``codehub_commits``.
    file_patterns:
        Substrings that, if present in a created/modified file path,
        count as "evidence the agent wrote code in the relevant area".
        Empty list means "any file counts" — used by codehub_commits
        which doesn't care which file as long as something changed.
    min_modifications_for_codehub:
        Threshold for the ``codehub_commits`` check — don't punish a
        tiny edit-and-finish. Default 5.
    """

    def __init__(
        self,
        *,
        expect_hub_kinds: List[str],
        file_patterns: List[str],
        min_modifications_for_codehub: int = 5,
        file_patterns_exclude: Optional[List[str]] = None,
    ):
        self.expect_hub_kinds = [str(k).strip() for k in (expect_hub_kinds or []) if str(k).strip()]
        self.file_patterns = [str(p).strip() for p in (file_patterns or []) if str(p).strip()]
        # Default exclusions: tests, configs, lockfiles, docs — these are
        # written by agents but don't materially produce APIs/tables/pages,
        # so they shouldn't trigger the "you didn't register" gate.
        default_excludes = [
            "test_", ".test.", ".spec.",
            "/tests/", "/test/", "__tests__",
            "package.json", "package-lock.json", "yarn.lock",
            "tsconfig", "jest.config", "vite.config", "webpack.config",
            "Dockerfile", "docker-compose", ".env",
            "requirements.txt", "Pipfile", "pyproject.toml",
            "README", ".md", ".gitignore", ".eslintrc",
        ]
        provided_excludes = [str(p).strip() for p in (file_patterns_exclude or []) if str(p).strip()]
        # Union, dedup, preserve order
        seen = set()
        self.file_patterns_exclude: List[str] = []
        for pat in provided_excludes + default_excludes:
            if pat not in seen:
                self.file_patterns_exclude.append(pat)
                seen.add(pat)
        self.min_modifications_for_codehub = int(min_modifications_for_codehub)

    async def handle_finish(
        self,
        agent: Any,
        *,
        tool_name: str,
        tool_args: Dict[str, Any],
        tool_call: Any,
        tool_call_id: str,
        messages: List[Any],
        files_created: List[str],
        files_modified: List[str],
    ) -> Optional[Dict[str, Any]]:
        if tool_name != "finish":
            return None

        touched = list(files_created or []) + list(files_modified or [])
        # Fallback to the agent's session-level file tracking
        # (``GeneratorMemory._files_created/_files_modified``) — multiple
        # call sites (chat mini-loop, autonomous step pipeline) write to
        # memory but only the step pipeline passes ``files_created`` /
        # ``files_modified`` in to ``_apply_finish_policies``. Without
        # this fallback the gate sees an empty list during chat-mode
        # finishes and silently no-ops even when the agent wrote files.
        if not touched:
            mem = getattr(agent, "memory", None)
            if mem is not None:
                try:
                    touched = list(getattr(mem, "_files_created", []) or []) + \
                              list(getattr(mem, "_files_modified", []) or [])
                except Exception:
                    touched = []
        # No evidence at all → don't block (e.g. observer agent finishing a tick).
        if not touched:
            return None
        # File-pattern gate is per-policy: if it's set and nothing matches,
        # this gate has no business firing for this finish. (codehub_commits
        # passes an empty list, meaning any file counts.)
        relevant = [p for p in touched if self._path_matches(p)]
        if self.file_patterns and not relevant:
            return None

        # For the codehub_commits threshold the right unit is "in-scope"
        # work, not total churn. When ``file_patterns`` is set we count
        # only files that matched (otherwise an agent that wrote 1
        # route + 10 README edits would trip a routes-scoped gate with
        # "you changed 11 files" — confusing and inaccurate). With no
        # patterns configured (the "any file" mode) we keep the full
        # count.
        modifications = len(relevant) if self.file_patterns else len(touched)
        gaps: List[str] = []
        for kind in self.expect_hub_kinds:
            gap_msg = self._check_hub_kind(
                agent=agent,
                kind=kind,
                relevant=relevant,
                modifications=modifications,
                touched=touched,
            )
            if gap_msg:
                gaps.append(gap_msg)

        if not gaps:
            return None

        bullet = "\n".join(f"- {g}" for g in gaps[:12])
        block_text = (
            "🚫 finish() blocked by hub-consistency gate.\n\n"
            "Before you can finish, the following must be reconciled:\n"
            f"{bullet}\n\n"
            "Take the listed actions, then call finish() again."
        )
        messages.append(Message.assistant(tool_calls=[tool_call]))
        messages.append(Message.tool(block_text, tool_call_id))
        messages.append(Message.user(
            "Hub-consistency gate fired. Address every item above. "
            "Do not summarize — execute the missing register/commit calls."
        ))
        try:
            agent._logger.warning(
                f"[{agent.agent_id}] finish blocked by hub-consistency: {len(gaps)} gap(s)"
            )
        except Exception:
            pass
        return {"action": "continue"}

    def _path_matches(self, path: str) -> bool:
        p = str(path or "")
        # Apply exclusions first — tests / configs / docs never count
        # as "API-surface code that needs hub registration".
        if any(ex in p for ex in self.file_patterns_exclude):
            return False
        # No include-patterns set → every non-excluded path counts.
        if not self.file_patterns:
            return True
        return any(pat in p for pat in self.file_patterns)

    def _check_hub_kind(
        self,
        *,
        agent: Any,
        kind: str,
        relevant: List[str],
        modifications: int,
        touched: Optional[List[str]] = None,
    ) -> Optional[str]:
        """Return a gap message when the kind is empty + evidence exists,
        ``None`` when consistent or unknown kind."""
        hubs = getattr(agent, "_hubs", None)
        if hubs is None:
            return None

        if kind == "registryhub_endpoints":
            # Step A: count endpoints owned BY THIS AGENT, not total.
            # Previously the gate passed if ANY agent had registered
            # an endpoint — design could register one endpoint and
            # backend could ship a route file without registering, gate
            # passes. Per-agent check makes "you wrote it / you
            # register it" enforceable.
            owned = self._count_owned_endpoints(hubs, agent.agent_id)
            if relevant and owned == 0:
                sample = ", ".join(relevant[:3])
                more = f" (+{len(relevant) - 3} more)" if len(relevant) > 3 else ""
                return (
                    f"You wrote {len(relevant)} route/controller file(s) "
                    f"[{sample}{more}] but registered 0 endpoints in "
                    f"RegistryHub as their provider. Call "
                    f"`registryhub_register_endpoint(method=..., path=..., schema=..., "
                    f"provider='{agent.agent_id}', status='implemented')` for "
                    f"each route before finish."
                )
            return None

        if kind == "registryhub_tables":
            owned = self._count_owned_tables(hubs, agent.agent_id)
            if relevant and owned == 0:
                sample = ", ".join(relevant[:3])
                more = f" (+{len(relevant) - 3} more)" if len(relevant) > 3 else ""
                return (
                    f"You wrote {len(relevant)} schema/migration file(s) "
                    f"[{sample}{more}] but registered 0 tables in RegistryHub as "
                    f"their provider. Call `registryhub_register_table(name=..., "
                    f"columns=..., provider='{agent.agent_id}')` for each table."
                )
            return None

        if kind == "workhub_pages":
            owned = self._count_owned_pages(hubs, agent.agent_id)
            if relevant and owned == 0:
                sample = ", ".join(relevant[:3])
                more = f" (+{len(relevant) - 3} more)" if len(relevant) > 3 else ""
                return (
                    f"You wrote {len(relevant)} page file(s) [{sample}{more}] "
                    f"but registered 0 ui_pages as RegistryHub ui_pages. Call "
                    f"`workhub_register_ui_page(name=..., path=..., "
                    f"status='implemented', components=[...])` for each."
                )
            return None

        if kind == "codehub_commits":
            # CodeHub stores live under ``codehub.stores.commits``.
            stores = getattr(getattr(hubs, "codehub", None), "stores", None)
            count = self._store_count(getattr(stores, "commits", None) if stores else None)
            if modifications >= self.min_modifications_for_codehub and count == 0:
                return (
                    f"CodeHub shows 0 commits, but you've changed "
                    f"{modifications} file(s) this session. Call "
                    f"`codehub_commit(message=..., files=[...])` to record "
                    f"your work so other agents (and the verifier) can see it."
                )
            return None

        # Unknown kind — silently ignore so misconfig doesn't crash finish.
        return None

    @staticmethod
    def _count_owned_endpoints(hubs: Any, agent_id: str) -> int:
        """Count RegistryHub endpoints whose ``provider`` is this agent."""
        try:
            store = getattr(hubs.registryhub, "_endpoints", None)
            value = store.value() if store and hasattr(store, "value") else {}
            return sum(
                1 for ep in value.values()
                if isinstance(ep, dict) and ep.get("provider") == agent_id
            )
        except Exception:
            return 0

    @staticmethod
    def _count_owned_tables(hubs: Any, agent_id: str) -> int:
        """Count RegistryHub tables whose ``provider`` is this agent."""
        try:
            store = getattr(hubs.registryhub, "_tables", None)
            value = store.value() if store and hasattr(store, "value") else {}
            return sum(
                1 for tbl in value.values()
                if isinstance(tbl, dict) and tbl.get("provider") == agent_id
            )
        except Exception:
            return 0

    @staticmethod
    def _count_owned_pages(hubs: Any, agent_id: str) -> int:
        """Count RegistryHub ui_pages owned by this agent (created or last
        updated). Accepts both ``_updated_by`` and ``created_by`` since
        the page can be touched by multiple agents."""
        try:
            store = getattr(hubs.registryhub, "_ui_pages", None)
            value = store.value() if store and hasattr(store, "value") else {}
            return sum(
                1 for p in value.values()
                if isinstance(p, dict)
                and (p.get("_updated_by") == agent_id or p.get("created_by") == agent_id)
            )
        except Exception:
            return 0

    @staticmethod
    def _store_count(store: Any) -> int:
        """Count entries in a JsonStore-backed dict.

        ``JsonStore.value()`` already strips the reserved ``_meta``
        bookkeeping key, so a plain ``len(...)`` is the right answer.
        Bare-dict fallback (some test stubs pass dicts directly) is
        accepted but expected to be already meta-free.
        """
        if store is None:
            return 0
        try:
            value = store.value() if hasattr(store, "value") else store
        except Exception:
            return 0
        if not isinstance(value, dict):
            return 0
        return len(value)


class ClaimAssignedTasksPolicy(BaseWorkflowPolicy):
    """Block ``finish()`` when this agent has pending tasks that
    name it as the assignee but haven't been claimed.

    Reviewer Q5 of the hub-responsibility-split plan
    (``docs/hub_responsibility_split_plan.md``): tier-3 of the
    lane-idle circuit breaker now cancels unclaimed assigned tasks
    deterministically, but that's a reactive escalation. The
    underlying root cause is that agents ROUTINELY finish a round
    while leaving tasks unclaimed in their queue — verifier sees
    "agent finished, no progress", waits ~3 idle rounds, then
    cancels. The dead time is the cost. This gate makes the cost
    visible at the SOURCE: the agent literally cannot end the round
    while it has assigned-but-unclaimed work; it must either claim
    (and then act on) or cancel (and explain) each task.

    Conservative shape — only fires when:
        * the task's ``assignee == agent.agent_id``,
        * the task's ``status == "pending"`` (not in_progress /
          completed / cancelled),
        * the task's ``claimed_by`` is empty.

    Returns ``{"action": "continue"}`` and injects a structured
    rejection message listing the offending tasks, same shape as
    ``HubConsistencyPolicy.handle_finish``.

    PR 2.5-fix (2026-05-28, reviewer feedback): dep-blocked tasks
    are marked separately in the message because ``claim_task``
    hard-rejects them (``service.py:494-500``) — telling an agent
    to "claim" a dep-blocked task is a guaranteed-fail loop. The
    rejection text tells them which option is actually available.

    PR 2.5-fix (2026-05-28, reviewer feedback): a retry cap auto-
    cancels the offending tasks after
    ``_MAX_CONSECUTIVE_BLOCKS`` rounds with the SAME blocking set
    and no progress. Reason: faster recovery — the breaker fires at
    ~10 idle steps, this fires at ~3 same-set blocks. Once tasks
    are auto-cancelled, the next finish proceeds. Auto-cancel
    reason is recorded on each task so post-mortem reviews can see
    why.

    (Previously this docstring also framed the retry cap as
    "defence in depth in case the breaker ordering ever gets
    inverted again". PR 2.5-fix-2 made the dispatcher two-pass,
    which means the breaker is now structurally guaranteed to fire
    in pass 1 regardless of YAML order or peer outcomes — so the
    cap is purely a recovery-speed concern, not a backup against
    ordering bugs.)
    """

    # Cap the list to keep the rejection message readable when an
    # agent has dozens of assigned tasks — the agent only needs to
    # see a few examples + the count.
    _MAX_LISTED = 8
    # Same blocking set, this many consecutive rounds → escalate
    # by auto-cancelling. Tuned for fast recovery: the breaker's
    # tier-3 fires at ~10 idle steps, this fires at ~3 same-set
    # blocks, so an agent that just keeps re-finishing without
    # acting on the rejection text is unstuck in <1/3 the wall
    # time. High enough that genuine work has multiple shots to
    # make progress.
    _MAX_CONSECUTIVE_BLOCKS = 3

    def __init__(self):
        # Per-instance retry tracker. Each agent profile gets its
        # own policy instance via ``create_workflow_policies`` so a
        # single counter (not keyed by agent_id) is correct here,
        # but we key by agent_id defensively in case the policy is
        # ever shared between agents in future refactors.
        self._consecutive_blocks: Dict[str, int] = {}
        self._last_blocking_set: Dict[str, frozenset] = {}

    async def handle_finish(
        self,
        agent: Any,
        *,
        tool_name: str,
        tool_args: Dict[str, Any],
        tool_call: Any,
        tool_call_id: str,
        messages: List[Any],
        files_created: List[str],
        files_modified: List[str],
    ) -> Optional[Dict[str, Any]]:
        if tool_name != "finish":
            return None
        hubs = getattr(agent, "_hubs", None)
        workhub = getattr(hubs, "workhub", None) if hubs is not None else None
        if workhub is None:
            return None

        unclaimed = self._collect_unclaimed_assigned(workhub, agent.agent_id)
        if not unclaimed:
            # No blocking set this round — reset the retry counter so
            # a future blocking set starts from 0, not from wherever
            # it left off after auto-cancel.
            self._consecutive_blocks.pop(agent.agent_id, None)
            self._last_blocking_set.pop(agent.agent_id, None)
            return None

        # Retry-cap bookkeeping: only count "same blocking set" as
        # a repeat. If even one task entered or left the set, the
        # agent is making progress (claimed one, cancelled one,
        # got a new assignment) — reset the counter.
        current_set = frozenset(t.get("id") for t in unclaimed if t.get("id"))
        last_set = self._last_blocking_set.get(agent.agent_id)
        if last_set == current_set:
            self._consecutive_blocks[agent.agent_id] = (
                self._consecutive_blocks.get(agent.agent_id, 0) + 1
            )
        else:
            self._consecutive_blocks[agent.agent_id] = 1
            self._last_blocking_set[agent.agent_id] = current_set

        # Retry cap — STOP ENFORCING and let finish proceed, but KEEP the
        # tasks pending. They used to be auto-cancelled here, which raced the
        # by-construction pipeline (live instagram, 2026-06-10): the skeleton
        # implements the contract and the RegistryHub→WorkHub sync completes the
        # impl.* tasks the moment endpoints flip 'implemented' — but only if
        # the tasks are still non-terminal. Auto-cancelling them first made
        # every run end with "31 cancelled" ghosts and broke the sync's
        # completion record. A pending task is harmless: sync completes it
        # later, the idle breaker handles true stalls, and dispatch ignores
        # terminal-free pending rows.
        if self._consecutive_blocks[agent.agent_id] > self._MAX_CONSECUTIVE_BLOCKS:
            try:
                agent._logger.warning(
                    f"[{agent.agent_id}] claim-gate retry cap exceeded after "
                    f"{self._MAX_CONSECUTIVE_BLOCKS} consecutive blocks — "
                    f"finish allowed; {len(unclaimed)} task(s) left PENDING "
                    "for the contract-sync to complete (no auto-cancel)."
                )
            except Exception:
                pass
            self._consecutive_blocks.pop(agent.agent_id, None)
            self._last_blocking_set.pop(agent.agent_id, None)
            return None

        # Split into claimable vs dep-blocked. claim_task() rejects
        # tasks with incomplete deps (service.py:494-500), so
        # telling the agent to "claim" a dep-blocked task is a
        # guaranteed-fail loop. Mark them separately.
        actionable, dep_blocked = self._split_dep_blocked(workhub, unclaimed)

        listed = unclaimed[: self._MAX_LISTED]
        remainder = len(unclaimed) - len(listed)
        dep_blocked_ids = {t.get("id") for t in dep_blocked}
        lines = []
        for t in listed:
            tid = t.get("id") or "<no id>"
            title = (t.get("title") or "").strip() or "<no title>"
            meta = t.get("metadata") or {}
            sev = meta.get("severity") or meta.get("priority") or "-"
            # PR 2.5-fix-2 (2026-05-29, reviewer follow-up):
            # emit a POSITIVE ``[claimable]`` tag alongside the
            # ``[dep-blocked: only cancel works]`` tag. The previous
            # cut only tagged dep-blocked tasks, leaving claimable
            # ones bare; the rejection text then referenced "for
            # [claimable] tasks" but the marker was never rendered,
            # so an agent grepping for the literal token found
            # nothing.
            tag = (
                " [dep-blocked: only cancel works]"
                if tid in dep_blocked_ids
                else " [claimable]"
            )
            lines.append(f"- {tid} [{sev}] {title}{tag}")
        bullet = "\n".join(lines)
        more = f"\n  (+{remainder} more not shown)" if remainder > 0 else ""
        # Retry-cap warning fires exactly on the LAST blocking
        # round — the next call with the same set will auto-cancel.
        # PR 2.5-fix-2 (2026-05-29): the previous gate fired one
        # round too early (``attempt_n >= cap - 1`` made the warning
        # appear on round cap-1 even though the actual escalation
        # was on round cap+1, not cap). Now fires only on round cap
        # itself; on round cap+1 we never reach this branch (the
        # auto-cancel above returned).
        attempt_n = self._consecutive_blocks[agent.agent_id]
        warn = ""
        if attempt_n >= self._MAX_CONSECUTIVE_BLOCKS:
            warn = (
                f"\n\n⚠️ This is the LAST block attempt "
                f"({attempt_n}/{self._MAX_CONSECUTIVE_BLOCKS}). On "
                "the next call with the same task set, these tasks "
                "will be AUTO-CANCELLED and finish will be allowed "
                "through."
            )
        # PR 2.5-fix-2 (2026-05-29): branch the rejection text when
        # ALL unclaimed are dep-blocked. The previous text always
        # described both option (a) and option (b); when actionable
        # was empty option (a) was a dead instruction the agent
        # could still try (and get a guaranteed-fail loop until the
        # retry cap kicked in). Now we emit cancel-only guidance.
        if actionable:
            action_text = (
                "Before calling finish() you must, for EACH listed task:\n"
                "  (a) for tasks tagged ``[claimable]``: call "
                "``workhub_task(action='claim', task_id=...)`` and do "
                "the work, OR\n"
                "  (b) for tasks tagged ``[dep-blocked: only cancel "
                "works]`` (and for any claimable task you genuinely "
                "want to drop): call ``workhub_cancel_task("
                "task_id=..., reason='<why>')``."
            )
        else:
            action_text = (
                "Every listed task is dep-blocked — their dependencies "
                "are not yet completed and ``workhub_task(action="
                "'claim', ...)`` will hard-reject them. Before calling "
                "finish() you must call "
                "``workhub_cancel_task(task_id=..., reason='<why>')`` "
                "for EACH listed task. There is no claim option this "
                "round."
            )
        block_text = (
            "🚫 finish() blocked by claim-assigned-tasks gate.\n\n"
            f"You have {len(unclaimed)} task(s) assigned to you that are "
            f"still pending and unclaimed "
            f"({len(dep_blocked)} dep-blocked, "
            f"{len(actionable)} claimable):\n"
            f"{bullet}{more}\n\n"
            f"{action_text}\n\n"
            "Silently leaving these in your queue causes the lane to "
            "show 'idle' to the rest of the team — that's the deadlock "
            "the tier-3 circuit breaker cancels reactively. Resolve "
            "them at the source."
            f"{warn}"
        )
        messages.append(Message.assistant(tool_calls=[tool_call]))
        messages.append(Message.tool(block_text, tool_call_id))
        messages.append(Message.user(
            "Claim-assigned-tasks gate fired. Address every listed task "
            "(claim or cancel). Do not finish until your assigned queue "
            "is empty of unclaimed pending work."
        ))
        try:
            agent._logger.warning(
                f"[{agent.agent_id}] finish blocked by claim-assigned-tasks: "
                f"{len(unclaimed)} unclaimed task(s) "
                f"(attempt {attempt_n}/{self._MAX_CONSECUTIVE_BLOCKS})"
            )
        except Exception:
            pass
        return {"action": "continue"}

    @staticmethod
    def _split_dep_blocked(
        workhub: Any, tasks: List[Dict[str, Any]]
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """Partition ``tasks`` into (actionable, dep_blocked).
        A task is dep-blocked if any of its ``depends_on`` tasks
        has status != 'completed' — matching the rejection logic
        in ``claim_task`` exactly (service.py:494-500)."""
        try:
            store = workhub.stores.tasks
            value = store.value() if hasattr(store, "value") else store
        except Exception:
            value = {}
        if not isinstance(value, dict):
            value = {}
        actionable: List[Dict[str, Any]] = []
        dep_blocked: List[Dict[str, Any]] = []
        for t in tasks:
            deps = t.get("depends_on") or []
            blocked = False
            for dep_id in deps:
                dep = value.get(dep_id)
                if dep is None or (isinstance(dep, dict)
                                    and dep.get("status") != "completed"):
                    blocked = True
                    break
            (dep_blocked if blocked else actionable).append(t)
        return actionable, dep_blocked

    @staticmethod
    def _collect_unclaimed_assigned(workhub: Any, agent_id: str) -> List[Dict[str, Any]]:
        """Return tasks where assignee==agent_id, status=='pending',
        claimed_by is empty. Tolerates store-shape variations and
        returns ``[]`` on any iteration error so a misconfigured hub
        can't itself block finish."""
        try:
            stores = getattr(workhub, "stores", None)
            store = getattr(stores, "tasks", None) if stores else None
            if store is None:
                return []
            value = store.value() if hasattr(store, "value") else store
        except Exception:
            return []
        if not isinstance(value, dict):
            return []
        out: List[Dict[str, Any]] = []
        for task in value.values():
            if not isinstance(task, dict):
                continue
            if task.get("assignee") != agent_id:
                continue
            if task.get("status") != "pending":
                continue
            # ``claimed_by`` is the live-claim marker. Treat empty
            # string / None / missing as "unclaimed".
            if task.get("claimed_by"):
                continue
            out.append(task)
        # Stable order: priority-rank then created_at — matches the
        # ordering ``list_ready_tasks`` uses so the agent sees the
        # same picture as their schedulers.
        order = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
        def _key(t: Dict[str, Any]):
            meta = t.get("metadata") or {}
            prio = meta.get("priority") or meta.get("severity") or "P2"
            return (order.get(prio, 99), t.get("created_at", 0.0))
        out.sort(key=_key)
        return out


class RequiredFilesPolicy(BaseWorkflowPolicy):
    """Block ``finish()`` until every configured path exists in the
    agent's worktree (B2, 2026-06-05).

    The LLM lanes follow their recipe only partially — across smokes
    #38-49 the backend lane sometimes shipped only ``src/`` (no
    Dockerfile / package.json) and the frontend likewise. Compose's
    per-service ``build:`` then fails on the missing Dockerfile and no
    env ever reached a working ``docker compose up``. This gate makes
    file completeness a HARD precondition for finish, not a prompt
    suggestion. Pair with ``lane_idle_circuit_breaker`` (which caps
    retries) so a lane that genuinely can't produce a file fails forward
    rather than looping forever.

    Paths are relative to the agent's worktree root (``_worktree_dir``).
    Charter §8 (no silent fallback): if the worktree is unknown the gate
    cannot verify, so it ABSTAINS (returns None) and the finish proceeds
    through the remaining gates — it never blocks blindly nor pretends
    success. NOTE: ``app/database/`` is intentionally NOT listed for any
    lane — the runtime is its sole owner (see
    ``orchestrator._generate_database``), so gating an LLM lane on it
    would deadlock a finish on a file the lane never writes.
    """

    def __init__(self, paths: List[str], any_of: Optional[List[List[str]]] = None):
        self.paths = [str(p).strip() for p in (paths or []) if str(p).strip()]
        # ``any_of`` is a list of alternative-groups: each group is satisfied if
        # AT LEAST ONE member exists. Lets a gate require "a src entry" without
        # pinning the extension (``src/main.jsx`` vs ``src/main.tsx``) — the
        # frontend completeness fix (⚠1) needs this so a real entry/App/api.js +
        # LoginPage/TenantPicker is mandatory without false-blocking on jsx≠tsx.
        self.any_of: List[List[str]] = []
        for group in (any_of or []):
            members = [str(p).strip() for p in (group or []) if str(p).strip()]
            if members:
                self.any_of.append(members)

    async def handle_finish(
        self,
        agent: Any,
        *,
        tool_name: str,
        tool_args: Dict[str, Any],
        tool_call: Any,
        tool_call_id: str,
        messages: List[Any],
        files_created: List[str],
        files_modified: List[str],
    ) -> Optional[Dict[str, Any]]:
        if tool_name != "finish" or not (self.paths or self.any_of):
            return None
        # Phase guard (smoke deadlock fix, 2026-06-05): required_files
        # applies ONLY to implementation-phase finishes. During the
        # kickoff-reply phase the lane has no filesystem tools and no
        # app/<domain> files can exist yet, so enforcing impl-file presence
        # there deadlocks the reply finish (chicken-and-egg — the exact
        # failure the retired implementation_bootstrap gate caused).
        # ``_kickoff_bootstrapped`` flips True only when the lane is admitted
        # its first post-finalize impl task_ready (KickoffBootstrapGate);
        # kickoff-reply wakes via EventHub subscription, not that gate, so
        # the flag stays False through kickoff. Default False → abstain (the
        # safe direction: a slipped-through finish is caught by the other
        # gates; a kickoff deadlock is catastrophic).
        if not getattr(agent, "_kickoff_bootstrapped", False):
            return None
        wt = getattr(agent, "_worktree_dir", None)
        if wt is None:
            # Can't verify without a worktree — abstain (don't false-block).
            return None
        root = Path(wt)
        missing = [p for p in self.paths if not (root / p).exists()]
        # An any_of group is "missing" only when NONE of its alternatives exist.
        missing_groups = [
            grp for grp in self.any_of
            if not any((root / p).exists() for p in grp)
        ]
        if not missing and not missing_groups:
            return None

        bullets = [f"- {p}" for p in missing]
        bullets += [f"- one of: {', '.join(grp)}" for grp in missing_groups]
        bullet = "\n".join(bullets)
        block_text = (
            "🚫 finish() blocked by required-files gate.\n\n"
            "These files MUST exist in your worktree before you can finish:\n"
            f"{bullet}\n\n"
            "Write every missing file (full content, not a stub), then call "
            "finish() again."
        )
        messages.append(Message.assistant(tool_calls=[tool_call]))
        messages.append(Message.tool(block_text, tool_call_id))
        messages.append(Message.user(
            "Required-files gate fired. Create each missing file listed above "
            "with real content. Do not summarize — write the files, then finish()."
        ))
        try:
            agent._logger.warning(
                f"[{agent.agent_id}] finish blocked by required-files: "
                f"missing={missing} missing_any_of={missing_groups}"
            )
        except Exception:
            pass
        return {"action": "continue"}


class AutoCommitOnFinishPolicy(BaseWorkflowPolicy):
    """On a successful finish(), commit any staged changes in the
    agent's worktree to ``agent/<id>`` with author=agent_id.

    Side-effecting bookkeeping, never blocks: returns ``None`` so the
    finish proceeds normally. A commit failure is logged at WARNING.
    """

    async def handle_finish(
        self,
        agent: Any,
        *,
        tool_name: str,
        tool_args: Dict[str, Any],
        tool_call: Any,
        tool_call_id: str,
        messages: List[Any],
        files_created: List[str],
        files_modified: List[str],
    ) -> Optional[Dict[str, Any]]:
        if tool_name != "finish":
            return None
        wt = getattr(agent, "_worktree_dir", None)
        if wt is None:
            return None
        from multi_agent.agents.runtime.auto_commit import (
            commit_worktree, merge_agent_branch_to_main, restage_written_files,
        )
        # Backstop (2026-06-05): per-write _auto_stage can silently skip
        # (workspace.resolve→None), leaving the agent's files UNTRACKED so
        # commit_worktree (pre-staged only) commits nothing and the whole
        # deliverable never reaches the branch (smoke #2: backend app/*
        # untracked → agent/backend empty → docker_up impossible). Re-stage
        # every file the agent wrote this session before committing. Uses
        # files_created/modified with the GeneratorMemory fallback (the chat
        # mini-loop doesn't pass the lists), mirroring HubConsistencyPolicy.
        touched = list(files_created or []) + list(files_modified or [])
        if not touched:
            mem = getattr(agent, "memory", None)
            if mem is not None:
                try:
                    touched = list(getattr(mem, "_files_created", []) or []) + \
                              list(getattr(mem, "_files_modified", []) or [])
                except Exception:
                    touched = []
        if touched:
            try:
                restage_written_files(wt, touched, agent_id=str(agent.agent_id))
            except Exception:
                pass
        msg = (tool_args.get("message") or "").strip()[:120] or "auto-commit"
        commit_msg = f"[{agent.agent_id}] finish: {msg}"
        ok, info = commit_worktree(
            worktree_dir=wt,
            branch=f"agent/{agent.agent_id}",
            author=str(agent.agent_id),
            message=commit_msg,
        )
        if not ok:
            try:
                agent._logger.warning(
                    f"[{agent.agent_id}] auto-commit on finish failed: {info}"
                )
            except Exception:
                pass
            return None

        # After a successful commit, integrate the agent's branch into the
        # shared ``integration`` branch so every OTHER agent's worktree
        # pull will surface this work. The shared branch is the
        # canonical "what would the CI build" reference. Without this
        # step, agent worktrees stay isolated forever — verifier's
        # docker-compose / test runs against an empty worktree.
        hubs = getattr(agent, "_hubs", None)
        repo_root = None
        if hubs is not None and hasattr(hubs, "codehub"):
            repo_root = getattr(hubs.codehub, "repo_root", None)
        if repo_root is None and hasattr(agent, "workspace"):
            # Fallback — assume the agent's workspace.base_dir IS the repo.
            repo_root = getattr(agent.workspace, "base_dir", None)
        if repo_root is None:
            return None

        merge_ok, merge_info = merge_agent_branch_to_main(
            repo_root=repo_root,
            agent_branch=f"agent/{agent.agent_id}",
            main_branch="integration",
            agent_id=str(agent.agent_id),
        )
        if not merge_ok:
            # Conflict (or git error). Emit a structured event so the
            # orchestrator / humans can route resolution. Never block
            # the finish on this — the agent's own work is committed to
            # ``agent/<id>``; integration just lags until conflict is
            # resolved.
            try:
                agent._logger.warning(
                    f"[{agent.agent_id}] auto-merge to integration failed: {merge_info}"
                )
            except Exception:
                pass
            if hubs is not None and hasattr(hubs, "eventhub"):
                try:
                    hubs.eventhub.publish_event(
                        source_hub=str(agent.agent_id),
                        event_type="merge_conflict",
                        payload={
                            "agent": str(agent.agent_id),
                            "source_branch": f"agent/{agent.agent_id}",
                            "target_branch": "integration",
                            "detail": merge_info,
                        },
                        recipients=["orchestrator"],
                        priority="urgent",
                    )
                except Exception as _emit_err:
                    try:
                        agent._logger.warning(
                            f"[{agent.agent_id}] merge_conflict event emit failed: {_emit_err}"
                        )
                    except Exception:
                        pass
        return None


class LaneIdleCircuitBreakerPolicy(BaseWorkflowPolicy):
    """Step B: detect when an agent is stuck producing zero output across
    multiple finish() cycles, and emit escalating signals so the
    orchestrator can route the lane out of deadlock.

    Tiered escalation (each fires once when the threshold is crossed,
    until the counter resets):

      Level 1 (warn_after_idle_steps):
          Emit ``lane_idle_warning`` to orchestrator. Soft nudge.
      Level 2 (failforward_after_idle_steps):
          Emit ``lane_stuck_failforward``. Orchestrator's prompt says
          consider failing the lane's task and unblocking downstream.
      Level 3 (halt_after_idle_steps):
          Emit ``lane_halted_human`` AND take the deterministic action
          configured by ``halt_action``:
            * ``"signal_only"`` — old behaviour: just the event. Use when
              you want a strictly-passive breaker and trust the
              orchestrator LLM to act on the event.
            * ``"fail_task"`` (default) — auto-fail the lane's currently
              claimed in-progress task with ``workhub.fail_task(reason=
              "lane_idle_circuit_breaker tier-3: N consecutive idle
              steps")``. Downstream agents with depends_on on that
              task can then proceed; the orchestrator can re-create
              the task if it wants to retry. This was the reviewer's
              critique of the first cut: "tier-3 should DO something
              deterministic, not just signal — otherwise the LLM may
              ignore the urgent event and the run hangs to budget."

    "Productive" step (resets the counter):
      * the agent wrote / modified any file this step, OR
      * the agent's owned hub-item count went up (new endpoint
        registered as provider, new table, new ui_page, new commit).

    Idempotency: the deterministic tier-3 action runs at most once
    per tier crossing — subsequent idle steps that don't bump the
    tier won't re-fail the same task.
    """

    _VALID_HALT_ACTIONS = frozenset({"signal_only", "fail_task"})

    def always_runs(self) -> bool:
        """Bookkeeping marker — the breaker MUST be invoked on every
        finish call regardless of how peer policies order themselves
        or what they return. See ``BaseWorkflowPolicy.always_runs``."""
        return True

    def __init__(
        self,
        *,
        warn_after_idle_steps: int = 2,
        failforward_after_idle_steps: int = 4,
        halt_after_idle_steps: int = 6,
        halt_action: str = "fail_task",
    ):
        self.warn_after_idle_steps = max(1, int(warn_after_idle_steps))
        self.failforward_after_idle_steps = max(
            self.warn_after_idle_steps + 1, int(failforward_after_idle_steps)
        )
        self.halt_after_idle_steps = max(
            self.failforward_after_idle_steps + 1, int(halt_after_idle_steps)
        )
        action = str(halt_action).strip().lower()
        if action not in self._VALID_HALT_ACTIONS:
            raise ValueError(
                f"halt_action must be one of {sorted(self._VALID_HALT_ACTIONS)}, "
                f"got {halt_action!r}"
            )
        self.halt_action = action

    async def handle_finish(
        self,
        agent: Any,
        *,
        tool_name: str,
        tool_args: Dict[str, Any],
        tool_call: Any,
        tool_call_id: str,
        messages: List[Any],
        files_created: List[str],
        files_modified: List[str],
    ) -> Optional[Dict[str, Any]]:
        if tool_name != "finish":
            return None

        # Kickoff-phase suppression (smoke #4, 2026-06-05): during kickoff a lane
        # does bounded reply work (authoring its section / posting meeting
        # decisions) and legitimately finishes WITHOUT writing files or growing an
        # OWNED hub — the breaker must NOT count that as idle, or the lane
        # fails-forward MID-KICKOFF, can't complete its revision, and the meeting
        # stalls into conflict→abort. The breaker is an IMPLEMENTATION-phase safety
        # net; kickoff has its own bounded driver (rounds + timeout). Gate on
        # ``_kickoff_bootstrapped`` (flips True only when the lane is dispatched its
        # first implementation task_ready — orchestrator._dispatch_implementation_phase).
        if not getattr(agent, "_kickoff_bootstrapped", False):
            return None

        # 1. Compute productive signal.
        wrote_files = bool((files_created or []) + (files_modified or []))
        cur_owned = self._count_total_owned(agent)
        prev_owned = getattr(agent, "_lane_idle_prev_owned", None)
        if prev_owned is None:
            # First observation — seed the counter without firing.
            agent._lane_idle_prev_owned = cur_owned
            agent._consecutive_idle_steps = 0
            agent._last_idle_tier = 0
            return None
        hub_grew = cur_owned > prev_owned
        agent._lane_idle_prev_owned = cur_owned
        productive = wrote_files or hub_grew

        # 2. Reset on productive step. ``_lane_idle_tier3_failed`` also
        # resets — a lane that recovered and then re-stuck should be
        # eligible for another deterministic action on a new tier-3.
        if productive:
            agent._consecutive_idle_steps = 0
            agent._last_idle_tier = 0
            agent._lane_idle_tier3_failed = False
            return None

        # 3. Idle step — bump counter and maybe escalate.
        n = getattr(agent, "_consecutive_idle_steps", 0) + 1
        agent._consecutive_idle_steps = n
        last_tier = getattr(agent, "_last_idle_tier", 0)
        new_tier = last_tier
        if n >= self.halt_after_idle_steps and last_tier < 3:
            new_tier = 3
        elif n >= self.failforward_after_idle_steps and last_tier < 2:
            new_tier = 2
        elif n >= self.warn_after_idle_steps and last_tier < 1:
            new_tier = 1
        if new_tier > last_tier:
            agent._last_idle_tier = new_tier
            self._emit_escalation(agent, n, new_tier)
        return None

    def _emit_escalation(self, agent: Any, idle_steps: int, tier: int) -> None:
        """Emit a structured event so the orchestrator gets a clear,
        actionable signal in its inbox."""
        hubs = getattr(agent, "_hubs", None)
        eventhub = getattr(hubs, "eventhub", None) if hubs is not None else None
        if eventhub is None or not hasattr(eventhub, "publish_event"):
            return
        tier_meta = {
            1: ("lane_idle_warning", "normal",
                "Lane has produced no measurable output for "
                f"{idle_steps} consecutive step(s). Soft nudge — "
                "check what's blocking and consider sending a "
                "directive to the agent."),
            2: ("lane_stuck_failforward", "high",
                f"Lane has been idle for {idle_steps} steps. "
                "Consider failing the lane's task (workhub_fail_task) "
                "and re-evaluating downstream dependencies, or "
                "spawning a worker to unblock."),
            3: ("lane_halted_human", "urgent",
                f"Lane has been idle for {idle_steps} steps after "
                "two prior escalations. Escalate to human triage; "
                "the agent is unable to self-recover."),
        }
        event_type, priority, suggestion = tier_meta.get(
            tier, ("lane_idle_warning", "normal", "")
        )
        try:
            eventhub.publish_event(
                source_hub=str(getattr(agent, "agent_id", "agent")),
                event_type=event_type,
                payload={
                    "lane": getattr(agent, "agent_id", ""),
                    "idle_steps": idle_steps,
                    "tier": tier,
                    "suggestion": suggestion,
                },
                recipients=["orchestrator"],
                priority=priority,
            )
        except Exception:
            # Best-effort — never let the breaker itself crash finish.
            pass
        try:
            agent._logger.warning(
                f"[{agent.agent_id}] LaneIdleCircuitBreaker "
                f"tier={tier} idle_steps={idle_steps} "
                f"event={event_type}"
            )
        except Exception:
            pass
        # Deterministic action at tier 3 (reviewer's hardening note):
        # an event alone is unreliable — the orchestrator LLM might
        # ignore it. Take a concrete action that unblocks the rest of
        # the run independent of LLM behaviour.
        if tier >= 3 and self.halt_action == "fail_task":
            self._auto_fail_lane_task(agent, idle_steps)

    def _auto_fail_lane_task(self, agent: Any, idle_steps: int) -> None:
        """Find every task the lane is responsible for AND in a
        non-terminal state, then either fail it (if claimed) or cancel
        it (if assigned but never claimed).

        Reviewer's follow-up: the first cut only acted on
        ``status=in_progress AND claimed_by==lane`` tasks, but in
        observed deadlocks the agents responded to ``task_ready``
        messages WITHOUT ever calling ``claim_task``. Tasks stayed
        ``status=pending, claimed_by=None`` forever, so the
        deterministic action was a no-op exactly when it was needed.

        Widened behaviour (see reviewer suggestion #1):
          * ``claimed_by == lane && status == "in_progress"`` →
            ``workhub.fail_task`` (the lane owned the task and
            admits it can't complete it).
          * ``assignee == lane && claimed_by == None && status == "pending"`` →
            ``workhub.cancel_task`` (the lane never picked it up;
            downstream re-evaluates depends_on).

        Idempotent via ``_lane_idle_tier3_failed`` sentinel.
        """
        if getattr(agent, "_lane_idle_tier3_failed", False):
            return  # already acted in this tier-3 crossing
        hubs = getattr(agent, "_hubs", None)
        workhub = getattr(hubs, "workhub", None) if hubs is not None else None
        if workhub is None or not hasattr(workhub, "list_tasks"):
            return
        agent_id = getattr(agent, "agent_id", "")
        if not agent_id:
            return

        # Gather every assigned-to-this-lane task in a non-terminal
        # state. ``list_tasks`` filters by status one value at a time;
        # call twice and merge.
        def _list(status: str) -> List[Dict[str, Any]]:
            try:
                return list(workhub.list_tasks(assignee=agent_id, status=status) or [])
            except Exception:
                return []
        in_progress = _list("in_progress")
        pending = _list("pending")

        reason = (
            f"lane_idle_circuit_breaker tier-3: {idle_steps} consecutive "
            f"idle steps with no file writes and no new hub registrations. "
            f"Lane has been auto-cleared so downstream depends_on can "
            f"proceed; orchestrator can re-create the task if a retry "
            f"makes sense."
        )

        failed_ids: List[str] = []
        cancelled_ids: List[str] = []

        # Branch 1 — fail tasks the lane claimed (in_progress + claimed_by).
        for task in in_progress:
            if not isinstance(task, dict):
                continue
            if task.get("claimed_by") != agent_id:
                continue  # claimed by someone else (rare) — don't touch
            tid = task.get("id")
            if not tid:
                continue
            try:
                result = workhub.fail_task(task_id=tid, agent=agent_id, reason=reason,
                                           force=True)  # framework remediation
                if isinstance(result, dict) and not result.get("error"):
                    failed_ids.append(tid)
            except Exception:
                continue

        # Branch 2 — cancel tasks the lane was assigned but never claimed.
        # This is the observed-deadlock case: agents kicked off by
        # ``task_ready`` messages without ever calling claim_task,
        # so the task sits pending forever.
        for task in pending:
            if not isinstance(task, dict):
                continue
            if task.get("claimed_by"):
                continue  # claimed by some other workflow — leave alone
            tid = task.get("id")
            if not tid:
                continue
            try:
                result = workhub.cancel_task(
                    task_id=tid, agent=agent_id, reason=reason,
                    force=True,  # framework remediation, not an LLM decision
                )
                if isinstance(result, dict) and not result.get("error"):
                    cancelled_ids.append(tid)
            except Exception:
                continue

        # Mark so we never re-fire in the same tier-3 crossing, even if
        # both lists came back empty.
        agent._lane_idle_tier3_failed = True
        if not failed_ids and not cancelled_ids:
            return

        # Emit a structured event so orchestrator sees both outcomes,
        # not just the warning.
        eventhub = getattr(hubs, "eventhub", None) if hubs is not None else None
        if eventhub is not None and hasattr(eventhub, "publish_event"):
            try:
                eventhub.publish_event(
                    source_hub=agent_id,
                    event_type="lane_task_auto_failed",
                    payload={
                        "lane": agent_id,
                        "idle_steps": idle_steps,
                        "failed_task_ids": failed_ids,
                        "cancelled_task_ids": cancelled_ids,
                        "reason": reason,
                    },
                    recipients=["orchestrator"],
                    priority="urgent",
                )
            except Exception:
                pass
        try:
            agent._logger.warning(
                f"[{agent_id}] tier-3 deterministic action: "
                f"failed {len(failed_ids)} claimed task(s), "
                f"cancelled {len(cancelled_ids)} assigned-but-unclaimed task(s)"
            )
        except Exception:
            pass

    @staticmethod
    def _count_total_owned(agent: Any) -> int:
        """Sum of owned items across all hubs — the productivity proxy."""
        hubs = getattr(agent, "_hubs", None)
        if hubs is None:
            return 0
        agent_id = getattr(agent, "agent_id", "")
        try:
            ep = HubConsistencyPolicy._count_owned_endpoints(hubs, agent_id)
            tb = HubConsistencyPolicy._count_owned_tables(hubs, agent_id)
            pg = HubConsistencyPolicy._count_owned_pages(hubs, agent_id)
        except Exception:
            return 0
        # Also count codehub commits authored by the agent if available.
        commits = 0
        try:
            stores = getattr(getattr(hubs, "codehub", None), "stores", None)
            cm_store = getattr(stores, "commits", None) if stores else None
            value = cm_store.value() if cm_store and hasattr(cm_store, "value") else {}
            commits = sum(
                1 for c in value.values()
                if isinstance(c, dict) and c.get("author") == agent_id
            )
        except Exception:
            commits = 0
        return ep + tb + pg + commits


class RetroBeforeDeliverPolicy(BaseWorkflowPolicy):
    """Reviewer's memory-redesign recommendation #2: "给关键节点加 gate
    (比如交付前必须 submit_retro), 否则它们永远 0 调用".

    Without a hard gate, ``submit_retro`` sees 0 calls — the agent
    finishes the run before bothering to record what happened. This
    policy intercepts ``deliver_project`` / ``report_completion`` and
    blocks them until at least one retro has been filed FOR THE
    CURRENT GENERATION.

    The first cut of this policy used ``workhub.list_retros()`` which
    returns retros from ALL prior runs in the same workspace. In
    ``--no-fresh`` mode (the usual iteration mode) a prior run's
    retro would silently satisfy the gate for every subsequent run,
    defeating the whole point. The reviewer caught this; the fix is
    to read ``hubs.generation_id`` (pinned by the orchestrator at
    run start) and call ``workhub.get_latest_retro_for_generation``.

    If ``generation_id`` isn't set on the hub registry (test bootstrap
    or unwired orchestrator), the gate falls back to the legacy
    "any retro counts" behaviour so it never crashes mid-finish, and
    logs a warning so the operator sees the degraded check.

    Block message includes the schema template so the agent doesn't
    waste a round figuring out submit_retro's shape.
    """

    _TRIGGER_TOOLS = frozenset({"deliver_project", "report_completion"})

    async def handle_finish(
        self,
        agent: Any,
        *,
        tool_name: str,
        tool_args: Dict[str, Any],
        tool_call: Any,
        tool_call_id: str,
        messages: List[Any],
        files_created: List[str],
        files_modified: List[str],
    ) -> Optional[Dict[str, Any]]:
        if tool_name not in self._TRIGGER_TOOLS:
            return None
        hubs = getattr(agent, "_hubs", None)
        if hubs is None or not hasattr(hubs, "workhub"):
            return None

        # Generation-scoped check: only retros recorded during THIS
        # run count. Without this, --no-fresh runs are silently
        # gate-bypassed by prior workspace state.
        gen_id = getattr(hubs, "generation_id", None)
        gate = getattr(hubs, "gate_registry", None)
        try:
            if gate is None:
                # GateRegistry not attached (test bootstrap before
                # HubRegistry's PR-3 wiring path); fall back to None.
                has_retro = False
            elif gen_id is not None and hasattr(
                gate, "get_latest_retro_for_generation"
            ):
                this_run_retro = gate.get_latest_retro_for_generation(gen_id)
                has_retro = this_run_retro is not None
            else:
                # Defensive fallback: gen_id missing (unwired
                # registry) → revert to the legacy "any retro counts"
                # check so the gate never crashes. Log so the
                # degraded check is visible.
                if gen_id is None:
                    try:
                        agent._logger.warning(
                            f"[{getattr(agent, 'agent_id', '?')}] retro gate "
                            "running without generation_id — falling back to "
                            "any-retro check; orchestrator should call "
                            "hubs.attach_generation_id at startup."
                        )
                    except Exception:
                        pass
                has_retro = bool(gate.list_retros() or [])
        except Exception:
            has_retro = False
        if has_retro:
            return None
        gen_label = f" (generation={gen_id})" if gen_id else ""
        block_text = (
            f"🚫 deliver gate: no retro recorded for this run{gen_label}.\n\n"
            "Memory-redesign gate: before "
            f"`{tool_name}` can run, you must call `submit_retro(...)` so "
            "the lessons from this run are captured. Prior runs' retros "
            "do NOT satisfy this gate — the scope is the current "
            "generation only.\n\nTemplate:\n\n"
            "```\n"
            "submit_retro(\n"
            "  title='<one-line summary>',\n"
            "  plan_vs_reality=[\n"
            "    {'planned': '...', 'actual': '...', 'delta': '...'},\n"
            "    ...  # >=2 entries\n"
            "  ],\n"
            "  root_causes=['...', '...'],\n"
            "  decisions=[{'decision': '...', 'rationale': '...'}],\n"
            "  follow_ups=[{'item': '...', 'owner': '...'}],\n"
            ")\n"
            "```\n\n"
            "After the retro lands, call "
            f"`{tool_name}` again — the gate auto-passes once a retro "
            "exists for this generation."
        )
        messages.append(Message.assistant(tool_calls=[tool_call]))
        messages.append(Message.tool(block_text, tool_call_id))
        messages.append(Message.user(
            f"Deliver gate fired. Call `submit_retro(...)` now, then "
            f"`{tool_name}` again. Do not summarize — file the retro."
        ))
        try:
            agent._logger.warning(
                f"[{agent.agent_id}] {tool_name} blocked by retro gate"
            )
        except Exception:
            pass
        return {"action": "continue"}


# Belt-and-suspenders registry of policy ``kind:`` values whose
# ``handle_finish`` can return a non-None gate outcome ("starvers").
# The structural fix is the two-pass dispatch in
# ``runtime/tooling._apply_finish_policies`` — bookkeeping policies
# fire in pass 1 regardless of YAML order, so a starver listed before
# the breaker can no longer starve it. This registry is the second
# layer of defence: ``_check_starver_breaker_ordering`` emits a
# WARNING when a profile orders a starver before the breaker in YAML
# (a likely sign of a misconception about the policy contract). If a
# future policy is added without updating this set, the structural
# guarantee still holds (that's pass 1's job) — but the operator
# loses the loud log line at boot. Keep this in sync.
STARVER_POLICY_KINDS: FrozenSet[str] = frozenset({
    "finish_continue",
    "hub_consistency_gate",
    "claim_assigned_tasks",
    "retro_before_deliver",
    "required_files",
    # NOTE (PR 2.5-fix-2 re-verify x2, 2026-05-29): intentionally
    # NOT listing ``verifier_validation_trigger`` or
    # ``implementation_bootstrap`` here. Both policies only
    # override ``allow_task_ready`` — they inherit
    # ``BaseWorkflowPolicy``'s base ``handle_finish`` (returns
    # None unconditionally) and therefore cannot starve a finish
    # dispatch. Listing either spuriously WARNs every boot.
    # New starver kinds added here MUST have an actual
    # ``handle_finish`` override that can return non-None.
})

# Policies whose handle_finish is bookkeeping-only (returns None
# unconditionally; ``always_runs() -> True``). Kept here so the
# starver-vs-bookkeeping invariant is visible in a single place.
BOOKKEEPING_POLICY_KINDS: FrozenSet[str] = frozenset({
    "lane_idle_circuit_breaker",
})


def _check_starver_breaker_ordering(agent_cfg: Dict[str, Any]) -> None:
    """Emit a WARNING log if a profile lists a starver policy BEFORE
    a bookkeeping policy in YAML. The structural two-pass dispatch
    still guarantees bookkeeping policies fire (pass 1), so this is
    a hygiene check, not a correctness gate — but it surfaces YAML
    that's been authored under the old "first-match-wins" mental model
    and might confuse a future maintainer.

    PR 2.5-fix-2 re-verify x2: the warning message now names the
    matched bookkeeping kind dynamically (``kinds[breaker_idx]``)
    rather than hardcoding ``lane_idle_circuit_breaker``. If a
    future commit adds a second kind to ``BOOKKEEPING_POLICY_KINDS``
    (e.g. a telemetry observer), the warning will name the actual
    matched policy."""
    raw_entries = agent_cfg.get("workflow_policies", []) or []
    kinds = [str((e or {}).get("kind", "")).strip().lower() for e in raw_entries]
    breaker_idx = next(
        (i for i, k in enumerate(kinds) if k in BOOKKEEPING_POLICY_KINDS), -1
    )
    if breaker_idx < 0:
        return
    bookkeeping_kind = kinds[breaker_idx]
    starvers_before = [
        (i, k) for i, k in enumerate(kinds[:breaker_idx])
        if k in STARVER_POLICY_KINDS
    ]
    if not starvers_before:
        return
    try:
        import logging
        logging.getLogger(__name__).warning(
            "workflow_policies: profile lists starver kind(s) %s BEFORE "
            "bookkeeping policy %r. Structural pass-1 dispatch still "
            "guarantees the bookkeeping policy fires, but the YAML "
            "ordering carries the old first-match-wins mental model "
            "and may be misleading. Suggested order: bookkeeping "
            "policies first, then gates.",
            [k for _, k in starvers_before],
            bookkeeping_kind,
        )
    except Exception:
        pass


def create_workflow_policies(agent_cfg: Dict[str, Any]) -> List[BaseWorkflowPolicy]:
    """Resolve workflow policies from config."""
    policies: List[BaseWorkflowPolicy] = []
    flags = agent_cfg.get("flags", {}) or {}

    for raw in agent_cfg.get("workflow_policies", []) or []:
        kind = str((raw or {}).get("kind", "")).strip().lower()
        if kind == "kickoff_bootstrap_gate":
            # Round 8h Stage 1: replaces the retired
            # ``implementation_bootstrap`` kind. The legacy kind
            # required ``required_files`` (filesystem
            # design/spec.*.json check); the new kind is hub-driven,
            # so only ``allowed_starters`` carries forward. A yaml
            # block still using the old ``implementation_bootstrap``
            # kind raises loudly on config load (see
            # ``test_implementation_bootstrap_retired.py``).
            policies.append(
                KickoffBootstrapGate(
                    allowed_starters=list(raw.get("allowed_starters") or []),
                )
            )
        elif kind == "implementation_bootstrap":
            # Round 8h Stage 1: legacy kind retired (charter §6.C
            # "delete-don't-skip" — no back-compat shim). A yaml block
            # still using the old kind is a stale config that must be
            # updated to ``kickoff_bootstrap_gate``.
            raise ValueError(
                "workflow_policies kind='implementation_bootstrap' is "
                "RETIRED (round 8h Stage 1; replaced by "
                "'kickoff_bootstrap_gate'). The old filesystem "
                "spec.{api,database,ui}.json gate was a chicken-and-egg "
                "deadlock after the design agent was retired in "
                "round-8e.1. Update agents_config.yaml: replace "
                "`kind: implementation_bootstrap` with "
                "`kind: kickoff_bootstrap_gate` and drop the "
                "`required_files` entry — the new gate uses WorkHub "
                "task assignments as the bootstrap signal."
            )
        elif kind == "verifier_validation_trigger":
            policies.append(
                VerifierValidationTriggerPolicy(
                    allowed_sender=str(raw.get("allowed_sender") or "orchestrator"),
                    accepted_tags=list(raw.get("accepted_tags") or []),
                    accepted_phases=list(raw.get("accepted_phases") or []),
                    payload_keywords=list(raw.get("payload_keywords") or []),
                    impl_completion_senders=(
                        list(raw["impl_completion_senders"])
                        if raw.get("impl_completion_senders") is not None else None
                    ),
                )
            )
        elif kind == "finish_continue":
            policies.append(
                FinishContinuePolicy(
                    tool_name=str(raw.get("tool_name") or "finish"),
                    followup_message=str(raw.get("followup_message") or "").strip(),
                )
            )
        elif kind == "hub_consistency_gate":
            policies.append(
                HubConsistencyPolicy(
                    expect_hub_kinds=list(raw.get("expect_hub_kinds") or []),
                    file_patterns=list(raw.get("file_patterns") or []),
                    file_patterns_exclude=list(raw.get("file_patterns_exclude") or []) or None,
                    min_modifications_for_codehub=int(
                        raw.get("min_modifications_for_codehub", 5)
                    ),
                )
            )
        elif kind == "auto_commit_on_finish":
            policies.append(AutoCommitOnFinishPolicy())
        elif kind == "lane_idle_circuit_breaker":
            policies.append(
                LaneIdleCircuitBreakerPolicy(
                    warn_after_idle_steps=int(raw.get("warn_after_idle_steps", 2)),
                    failforward_after_idle_steps=int(raw.get("failforward_after_idle_steps", 4)),
                    halt_after_idle_steps=int(raw.get("halt_after_idle_steps", 6)),
                    halt_action=str(raw.get("halt_action", "fail_task")),
                )
            )
        elif kind == "retro_before_deliver":
            policies.append(RetroBeforeDeliverPolicy())
        elif kind == "claim_assigned_tasks":
            policies.append(ClaimAssignedTasksPolicy())
        elif kind == "required_files":
            policies.append(
                RequiredFilesPolicy(
                    paths=list(raw.get("paths") or []),
                    any_of=list(raw.get("any_of") or []),
                )
            )
        elif kind:
            raise ValueError(f"Unknown workflow policy kind: {kind}")

    depends_on = flags.get("depends_on") or []
    if depends_on:
        policies.append(DependsOnPolicy(depends_on=list(depends_on)))

    _check_starver_breaker_ordering(agent_cfg)
    return policies
