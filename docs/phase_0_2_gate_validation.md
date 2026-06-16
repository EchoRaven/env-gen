# Phase 0.2 — §11 Adversarial Gate-Validation Report

> Mandatory pre-SHIPPED deliverable per `docs/progressive_elaboration_refactor.md` §11.2.5
> (added 2026-05-30 after the Phase 0.2 attempt-1 SHIPPED-without-§11
> failure that this very report exists to prevent recurring).

## 0. tl;dr

Phase 0.2 attempt-2 ran the §11 adversarial gate-validation workflow
(run id `wtqhbnw3e`) **before** claiming closure. The workflow probes 3
attack surfaces × 14 bypass attempts total. Result:

- **14 / 14** original-finding probes → **REFUTED** (the reviewer's
  attempt-1 confirmed bypasses no longer reproduce).
- **2 NEW_FINDING** surfaced during the probe. Both flagged honestly
  rather than swept under the ALL_REFUTED claim. Risk analysis below.

Closure recommendation: **SHIP with the 2 NEW_FINDINGs explicitly
recorded as known-context for the broader threat model**. The reviewer
should decide whether to accept ship or block on either.

**UPDATE (2026-05-30, round-8 both-reviewer ACCEPT):** Phase 0.2 narrow
scope is now ✅ SHIPPED after 8 review rounds + attempt-7.1's over-reach
correction. Both R1 and R2 ACCEPTed in round-8. The final mandatory
disclosure (R1 round-8 verbatim condition):

> The monitor control plane is unauthenticated; it is safe only bound
> to loopback for a single trusted local user; do not expose it
> (`--host` off-loopback requires `ENVGEN_AUTH_TOKEN`, and full
> per-call authz is the Phase 0.2-EXT security PR).

The full SHIPPED note + deployment-safety table live in
`progressive_elaboration_refactor.md` Phase 0.2 SHIPPED section.

Suite: **1753 / 0** with 3 structural invariants in CI (tool-layer +
method-layer GREEN; monitor-layer pin-count GREEN at 53 known-EXT
bypassers, REDs on regression in either direction).

**Deployment-safety disclosure (in sync with
`docs/progressive_elaboration_refactor.md` Phase 0.2 SHIPPED note,
R2 round-5 precise wording)**:

Phase 0.2 is safe ONLY for **SINGLE-USER LOCAL** deployment. The bind
guard (commit `6e8bf29b`) refuses non-loopback `--host` without
`ENVGEN_AUTH_TOKEN` — but `ENVGEN_AUTH_TOKEN` gates ENTRY only, NOT
per-endpoint role. Once the token is set and a non-loopback bind is
taken, ANY authenticated user can still reach all **53 ungated
mutations** (`delete_project`, `codehub_force_merge_pr`, `deliver_project`
force_deliver, etc.) enumerated by
`tests/test_monitor_call_gate_invariant.py`. Therefore:

| Deployment | Safety |
|---|---|
| Loopback (127.0.0.1) | OK Safe — the documented Phase 0.2-narrow story |
| Non-loopback + token + SINGLE trusted user | Acceptable risk (single user → lateral movement moot) |
| Non-loopback + token + MULTIPLE users | BLOCKED — needs Phase 0.2-EXT first |
| Non-loopback + NO token | Bind guard refuses to start |

Multi-user / shared-tenant deployment requires Phase 0.2-EXT closure
(the ~53 `*_call` role-gating) + ExecuteIPython/Bash sandboxing per
§0.5 below.

## 0.5 Threat Model (added attempt-3 per reviewer demand)

Phase 0.2 protects a SPECIFIC trust boundary. State it precisely so
"3.1 critical closed" does not overclaim.

### What Phase 0.2 actually defends

- **The control plane (monitor-server process)**: an authenticated
  agent cannot escalate from its own process to the monitor-server
  process. The original 3.1 #2 RCE delivery surface (allowlist
  agent-writable → loaded by monitor → executed AS monitor) is
  closed.
- **Cross-agent integrity**: agent A cannot rewrite agent B's
  worktree, the shared hub state, the design specs, or the
  operator-authored gate allowlist.
- **Accident prevention**: per-role write scopes catch unintended
  cross-domain writes (frontend can't silently rewrite design specs).

### What Phase 0.2 does NOT defend

- **Host-from-agent**: agents with the `runtime` tool bundle
  (ExecuteBashTool + ExecuteIPythonTool, assigned to Orchestrator /
  Backend / Verifier / Worker via runtime_full) have unsandboxed
  local code execution as the OS user. No chroot, no container, no
  seccomp. The "sandbox escape" framing from audit 3.1 is incoherent
  against the agent — there is no sandbox there.
- **Multi-tenant deployment**: this codebase as-shipped is not safe
  to expose to untrusted users. Shared/multi-tenant deployment is
  OUT OF SCOPE; treating it as in-scope would be a P0.
- **Prompt-injected agents**: under a broader threat model where
  agents can be subverted by hostile input data, ExecuteBash/IPython
  is the primary escalation path. Phase 0.2 reduces secondary
  escalation paths (control plane, cross-agent) but does not address
  the primary one.

### The headline corrected

"3.1 critical #1 + #2 closed" means: closed AGAINST AGENT→MONITOR
escalation. It does not mean: closed as a host-from-attacker bound.
An operator deploying this system in a shared environment would
need to add ExecuteIPython/Bash sandboxing (a separate P0 PR) before
any non-trivial exposure.

## 1. Background

Phase 0.2 attempt-1 (commits `e2648135` + `ce20c7a1`) was declared SHIPPED
on a 27-test green adversarial suite. Reviewer's independent §11 probe
then surfaced 5 confirmed CRITICAL/HIGH bypasses, and Phase 0.2 was
RE-OPENED in commit `33d60121`. The plan doc was amended (§11.2.5) to
make §11 adversarial validation MANDATORY pre-SHIPPED.

Phase 0.2 attempt-2 (commits `02d2f3a8` + `26c37682` + `d9c0e236` +
`205a8fcd`) applies all 6 reviewer-required fixes AND runs §11 BEFORE
claiming closure.

## 2. The 6 fixes (commit table)

| Fix # | Reviewer requirement | Commit(s) | Files |
|---|---|---|---|
| 1 | `.gates/` read-only base route + allowlist out of agent-writable space | `02d2f3a8` | `path_routed_workspace.py` (routing entry), `user_gates.py` (env-var path) |
| 2 | argv hardening: absolute binary + interpreter denylist | `02d2f3a8` | `user_gates.py` |
| 3 | Per-route containment + write-gate on resolved path | `02d2f3a8` (folded with fix 1's same-file edits) | `path_routed_workspace.py` |
| 4 | Non-canonical file_tools through `workspace.resolve()` | `26c37682` | `file_tools.py` |
| 5 | Auto-stage path filter | `d9c0e236` | `agents/runtime/auto_commit.py`, `hubs/codehub/service.py` |
| 6 | Test fixture to production nesting + bypass regression tests | `205a8fcd` | `tests/test_path_routed_workspace_containment.py` |

## 3. Adversarial probe — verbatim results per surface

### Surface A — `allowlist-agent-writable`

| Probe | Verdict | Evidence (abbrev.) |
|---|---|---|
| `ws.is_write_allowed('.gates/allowed_code_checks.yaml', any_agent)` | **REFUTED** | Returns False for all 6 agent_ids tested. `.gates/` is first in `ROUTING_TABLE` at `path_routed_workspace.py:61` with `writers=frozenset()`. |
| `ws.resolve('.gates/...')` should land under `base_root`, not `code_root` | **REFUTED** | Live PoC: resolves to `base/.gates/allowed_code_checks.yaml`; `is_relative_to(base)`=True, `is_relative_to(code)`=False. |
| `_load_allowed_code_checks` reads `$ENVGEN_ALLOWED_CODE_CHECKS_FILE` not `<workspace>/.gates/` | **REFUTED** | With env unset → returns `{}`. With env set to operator path AND workspace `.gates/...` ALSO present → loader returns only the operator entry, NOT the agent-written one. |
| Agent uses file_write/edit/apply_patch/copy_reference_image to write `.gates/` | **REFUTED** | `tooling.py:264` `_check_write_permission` iterates writes through `ws.is_write_allowed`; rejected paths return `ToolResult(success=False, error_message='Write permission denied')`. |
| Auto-stage path: `.gates/` file ends up in worktree out-of-band — does it auto-stage? | **REFUTED** | `_should_stage_path` at `auto_commit.py:44-81` rejects any path component starting with `.` unless in `ALLOWED_DOTFILES`. Confirmed across `.gates/x`, `.github/x`, `.env`, `app/.gates/x`. |
| `resolve_conflict` tool writes via `abs_path = repo_root / rel_path` (bypass attempt) | **REFUTED** | Even if planted, allowlist loader at `user_gates.py:252` only reads `os.environ[ENVGEN_ALLOWED_CODE_CHECKS_FILE]` — never `repo_root` or workspace paths. |
| **NEW_FINDING**: agent sets `$ENVGEN_ALLOWED_CODE_CHECKS_FILE` from inside ExecuteIPython | see §4 below |  |

### Surface B — `file-tools-deviation-gap`

| Probe | Verdict | Evidence (abbrev.) |
|---|---|---|
| `CopyReferenceImageTool` rejects `src=/etc/passwd` | **REFUTED** | New `_resolve_source_image` at `file_tools.py:1259-1319` drops the old candidate list (`root.parent`, `repo_root`, `cwd`, raw fall-through). Only `workspace.resolve(...)` and `screenshot_lib`-contained paths accepted. |
| `ListReferenceImagesTool` rejects arbitrary out-of-workspace dir | **REFUTED** | New `_resolve_reference_project` at `file_tools.py:1114-1137` only accepts `workspace.resolve()`-contained paths or `is_relative_to(lib_root)` `screenshot_lib` paths. Execute path (lines 1069-1086) no longer falls back to raw `screenshot_lib/project` join. |
| `view_image` fallback rejects out-of-workspace | **REFUTED** | `ViewImageTool.execute` at `file_tools.py:913-922` routes through `_resolve_workspace_path` which calls `workspace.resolve()` and rejects out-of-workspace paths. Raw-fallback branch removed. |
| Sanity: legit in-workspace use of all three tools still works | **REFUTED** (i.e. confirms NO regression) | Live PoC: `src='screenshots/ref.png'`, `src='proj_a/img.png'` (bundled lib), `ListReferenceImagesTool(project='screenshots')` all succeed. |

### Surface C — `containment-bypass-hunt`

| Probe | Verdict | Evidence (abbrev.) |
|---|---|---|
| `..` escape from code into base under production geometry: `ws.resolve('../../shared/secret')` | **REFUTED** | `ValueError` raised at `path_routed_workspace.py:299-307`. Per-route containment (line 200) — code-route input that lands outside `code_root` → fail. |
| Cross-agent worktree access: `ws.resolve('../another_agent/x')` | **REFUTED** | `ValueError`. Same enforcement: `code_root` only for code-route. |
| Absolute path inside base but outside code: `ws.resolve(str(base_root / 'design' / 'spec.api.json'))` | **REFUTED**¹ | Live PoC: ACCEPTED — but classified as REFUTED because the design route INFERS from absolute path. The original concern (escape-to-base from code-route) is the load-bearing one; absolute base-inside is intentional. |
| Write-gate on raw input that resolves into read-only route: `ws.is_write_allowed('../screenshots/x', agent_id='x')` | **REFUTED** | Returns False at `path_routed_workspace.py:334-337`. `is_write_allowed` calls `resolve()` first; per-route containment raises; `except ValueError: return False`. |
| Legit code-internal: `ws.resolve('foo/bar.py')` | **REFUTED** (i.e. no regression) | ACCEPTED → `<code_root>/foo/bar.py`. |
| Legit absolute inside code: `ws.resolve(str(code_root / 'foo.py'))` | **REFUTED** (i.e. no regression) | ACCEPTED → `<code_root>/foo.py`. |
| **NEW_FINDING**: base-route `..`-traversal-within-base read path: `ws.resolve('design/../shared/secret')` | see §4 below |  |

¹ This probe was authored expecting REJECTION based on a misreading of fix #3's spec; the verifier correctly notes that absolute paths get the route inferred from the root they live under (correct behavior per fix #3 design notes in commit `02d2f3a8`).

## 4. The NEW_FINDINGs — honest disclosure

> Originally drafted as "2 NEW_FINDINGs"; expanded over rounds of
> review to four. **#1** and **#2** surfaced in attempt-2's §11 probe.
> **#3** surfaced in attempt-3 (a within-base read variant of #2).
> **#4** surfaced in attempt-5 round-4 (R2's residual on
> ``open_pull_request`` monitor wrapper). All four are kept here so
> the cumulative honest-residual list is one document, not scattered
> across commit logs.
>
> Attribution corrections (R1 round-4, attempt-5):
> - ``GenerateSeedSQL``'s containment fix (``workspace.resolve()``
>   routing in ``data_engine_tools.py``) landed in commit ``c7f7184d``
>   (the 44-site ``.root/`` → ``.resolve()`` migration), NOT in
>   attempt-4 commit ``5f5da7d4``. attempt-4's actual contribution at
>   ``5f5da7d4`` is the gate-set addition that wires
>   ``generate_seed_sql``'s ``output_file`` parameter through
>   ``_enforce_write_permissions``. The two together close the
>   FULLY_AGENT_CONTROLLED finding.
> - ``GenerateSeedSQL`` severity is **HIGH** (per ``tooling.py:324``'s
>   gate-comment, the actor is the model-driven agent — not external —
>   so the impact is bounded by agent capability and does not warrant
>   Critical, which is reserved for external-attacker control-plane
>   escalations).

### NEW_FINDING #1 (Surface A): ExecuteIPython sets env vars

> An agent with the `runtime` tool bundle (`tool_bundles.py:73-86` —
> includes `ExecuteBashTool` + `ExecuteIPythonTool`) can:
> - Run `os.environ['ENVGEN_ALLOWED_CODE_CHECKS_FILE'] = '/tmp/agent.yaml'`
>   via `ExecuteIPythonTool`'s `eval/exec` (`runtime_tools.py:1205-1207`)
>   or `%env KEY=VALUE` magic (`runtime_tools.py:1285-1295`).
> - Pre-populate `/tmp/agent.yaml` (which is agent-writable in `/tmp`).
> - Trigger `code_check` to run the agent-authored allowlist entry.

**Rationale corrected attempt-3 per Reviewer 1**: the original draft
argued "ExecuteIPython subsumes it" — i.e. an agent that can already
run arbitrary code gets no new capability from setting an env var.
That framing is wrong because it pretends the agent and the monitor
share a process. They don't. The correct rationale is **process
isolation**:

> POSIX env vars do not propagate child→parent. An agent's
> `os.environ['ENVGEN_ALLOWED_CODE_CHECKS_FILE'] = '/tmp/agent.yaml'`
> mutates only the agent's own process (or, in same-process agent-
> worker geometry, the agent worker — which is still not the monitor-
> server). The gate runs in the monitor-server process, which reads
> `ENVGEN_ALLOWED_CODE_CHECKS_FILE` from ITS OWN environment, set
> ONCE at monitor launch. Nothing the agent does to its own
> `os.environ` is visible to that loader. Process isolation closes
> the basic finding; "ExecuteIPython subsumes it" does NOT, and
> would not even apply in the multi-tenant case where the agent has
> code execution but is precisely what we DON'T trust.

**Defense-in-depth (FIX C, attempt-3)**: the env-var-cache hardening
landed in attempt-3 (load `ENVGEN_ALLOWED_CODE_CHECKS_FILE` once at
monitor-server startup, cache the resolved path, refuse re-reads) is
still the right move even though the basic case is already inert by
process isolation. It removes the cache-invalidation surface entirely
and would close the residual risk if a future refactor ever co-located
the gate loader with agent-controllable state (e.g. by running gates
in-process inside an agent worker).

**Under the broader (multi-tenant / prompt-injected) threat model**:
ExecuteBash/IPython is the primary escalation path and process
isolation of the gate-loader does NOT help — see §0.5. The proper
remediation under that model is sandboxing of ExecuteBash/IPython,
not gate hardening.

**Recommendation for reviewer**: ship under the stated trust-boundary
threat model (§0.5). The env-var-cache hardening (FIX C) lands in the
same attempt-3 series. No deferred-blocker.

### NEW_FINDING #2 (Surface C): base-route `..`-traversal-within-base reads

> `ws.resolve('design/../shared/secret')` — the input matches the
> `design/` base route prefix; the resolved path lands at
> `base/shared/secret` (still inside `base_root`, in the read-only
> `shared/` base route); `_is_contained(resolved, 'base')` returns True.

**NOT a write bypass** — verified live: `ws.is_write_allowed('design/../shared/secret', agent_id='design')` returns False because `_route_of_resolved` re-derives the route from the resolved path and finds `shared/` writers=`frozenset()`.

**IS a read-path consideration** — an agent with a base-route prefix
(e.g. `design/`) can use `..` to read OTHER base-routed locations
(e.g. `shared/`, `screenshots/`). Those locations ARE all reachable
directly via their named prefixes, so this is not a privilege
escalation — just a non-canonical access pattern.

**Recommendation**: document as a known design choice. The cleaner
alternative ("require resolved path to stay UNDER the matched prefix
subtree") may break legitimate workflows that use relative escapes
between base assets and warrants a separate PR if reviewer wants the
tighter form. NOT blocking ship.

### NEW_FINDING #3 (Surface C, attempt-3): within-base `..`-traversal can READ `.gates/`

Reviewer 2 warned that the same within-base traversal that surfaced as
NEW_FINDING #2 (for `shared/`) might let a base-prefix-routed agent
READ the operator-only `.gates/` directory via `design/../.gates/...`.
Live probe (production-geometry fixture, design role):

```
ws.resolve('design/../.gates/allowed_code_checks.yaml')
  → ACCEPTED → <base>/.gates/allowed_code_checks.yaml
  is_relative_to(base)=True, is_relative_to(code)=False
ws.is_write_allowed('design/../.gates/allowed_code_checks.yaml', 'design')
  → False
ws.resolve('.gates/allowed_code_checks.yaml')          # direct prefix
  → ACCEPTED → <base>/.gates/allowed_code_checks.yaml  # SAME path
ws.is_write_allowed('.gates/allowed_code_checks.yaml', any_agent)
  → False
```

**Symmetric with NEW_FINDING #2 — NOT a privilege escalation**:
- The traversal-form READ and the direct-prefix READ land at the
  exact same resolved path. Both are reachable. The `..`-form gives
  the agent NO new capability over the direct form.
- The write-gate (re-derived from the resolved path's route by
  `_route_of_resolved`) correctly returns False for both forms — the
  `.gates/` route has `writers=frozenset()`, irrespective of which
  raw string brought the resolver here.
- **The `.gates/` directory's contents are not consulted by the
  monitor in any case**: the gate loader reads
  `os.environ['ENVGEN_ALLOWED_CODE_CHECKS_FILE']` (an operator-set
  path that need not be inside the workspace at all — see
  `user_gates.py:252`), so even if an agent READ the workspace
  `.gates/` yaml, that yaml is not what the monitor evaluates.

**Resolution**: documented as expected behavior, NOT a finding to
fix. The read symmetry follows from the design (any base-routed
prefix is reachable by any agent for read), and the write-gate
correctly resists both forms. The defense-in-depth `.gates/`
routing entry exists precisely so a misplaced operator YAML in
the workspace cannot be agent-mutated; READ of such a YAML is by
design.

The cleaner "stay under matched prefix subtree" rule from
NEW_FINDING #2 would also block this READ as a side-effect; that
remains a separate-PR tightening, not a Phase 0.2 blocker.

### NEW_FINDING #4 (attempt-5 round-4, R2): open_pull_request monitor wrapper forwards body.author

> The monitor-layer wrapper ``codehub_open_pr_call`` at
> ``live_monitor_server.py:3861`` passes ``author=body.get("author") or
> "ui_user"`` untrusted into ``reg.codehub.open_pull_request``. An
> authenticated UI user (when ``auth_required()`` is ON) can spoof the
> PR author identity by setting ``body.author`` to any string. In the
> default auth-off posture, any loopback caller can do the same with no
> credentials.

**Why this is a finding** (R2 round-4):
- ``CodeHub.open_pull_request`` (service.py:180-319) deliberately has
  NO author-identity gate (see METHOD_ALLOWLIST entry — the seven
  structural gates at :200/:208/:213/:223/:236/:246/:260 are guardrails
  on linked-tasks/reviewers/etc., not on author identity).
- The tool-layer wrapper at ``hub_tools.py:220`` correctly pins
  ``author=self._agent_id`` so an agent-side caller cannot spoof.
- The monitor-layer wrapper forwards ``body.author`` unfiltered. This
  is a monitor-path leak of the otherwise-pinned author identity.

**Severity**: MEDIUM (not HIGH). The PR author allowlist is itself a
downstream gate — every PR still requires verified WorkHub task
links, ≥2 distinct reviewers excluding author, etc. — so the spoof
gives an attacker a tagged-as-someone-else PR draft, not arbitrary
write access. The impact is impersonation in audit trails, not
elevation of write capability.

**Resolution status**: documented here as honest residual #4 per R2
round-4's explicit request that it not be forgotten. **Closed in
Phase 0.2-EXT** alongside the rest of monitor role-gating (the broader
monitor-layer invariant is intentionally RED to enumerate exactly
this class of residual). The minimum hard-pin in the monitor handler
mirroring ``codehub_force_merge_pr_call``'s pattern at
``live_monitor_server.py:3945`` is the surgical fix; deferring it to
the dedicated Phase 0.2-EXT scope keeps the monitor-path corrections
under one coherent PR.

**Sibling fix landed (attempt-5 CORRECTION 4) — scope clarified (R1 round-5)**:
the analogous hard-pin for ``codehub_merge_pr_call`` (merge, not open)
DID land in this attempt at ``live_monitor_server.py:3903``. **What
that hard-pin actually closes vs leaves open** (the earlier "FIX C
closes the merge chain" framing was overstated and is replaced here):

FIX C removes the ``body.agent`` SPOOF VECTOR in auth-ON deployments
(monitor handler hard-pins ``agent="orchestrator"`` before reaching
the method-layer gate at ``service.py:518``, so an authenticated UI
user can no longer satisfy the method-layer role gate with an
attacker-chosen ``agent`` string). It does NOT close the
unauthenticated open→approve→merge chain: ``codehub_merge_pr_call``
has no auth gate in the default auth-off posture, and
``submit_review`` trusts attacker-chosen reviewer ids. That chain
remains **EXT-scope** — closing it requires the monitor-layer
role-gating + reviewer-identity enforcement that the
intentionally-RED ``test_monitor_call_gate_invariant.py`` enumerates.

In the SHIPPED narrow-scope posture the only mitigation for the
unauthenticated chain is the bind guard
(``_enforce_bind_guard`` refuses non-loopback bind without
``ENVGEN_AUTH_TOKEN``). open_pull_request's body.author hard-pin is
deliberately deferred to the same EXT PR — partial monitor-path
hardening would create an inconsistent surface; better to close the
entire monitor-path role-gating story (and the unauthenticated
chain it implies) in one coherent EXT PR.

## 5. Suite delta

| Stage | Passing | Failing |
|---|---|---|
| Phase 0.1 baseline (`f55003e3`) | 1581 | 0 |
| Phase 0.2 attempt-1 (sibling fixture, claimed SHIPPED) | 1608 | 0 |
| Phase 0.2 attempt-2 (post all 6 re-fixes, production fixture) | **1666** | **0** |

Net delta vs Phase 0.1 baseline: +85 (mostly the production-geometry
regression tests + non-canonical-tool tests + argv-hardening tests).

## 6. Lesson recorded in plan doc §11.2.5

Phase 0.2 attempt-1's failure was the exact land-but-dead failure mode
§11 was created to prevent. The §11 adversarial workflow was the right
mechanism; the bug was timing — it ran AFTER my claim of closure, not
before. §11.2.5 (added in commit `33d60121`) now makes pre-SHIPPED
§11 mandatory. This report is the §11.2.5 deliverable for Phase 0.2
attempt-2 and demonstrates the corrected discipline.

## 7. Closure recommendation

**Closing 3.1 critical #1 (path-traversal escape) and #2 (RCE-enabler)
under the stated threat model**, with the 2 NEW_FINDINGs explicitly
surfaced for reviewer's broader-threat-model judgment.

If reviewer accepts NEW_FINDING #1 as deferrable: Phase 0.2 → SHIPPED ✅.
If reviewer blocks on NEW_FINDING #1: Phase 0.2 stays "pending-adversarial"
and we add the env-var-cache fix in a follow-up commit.

Reviewer cross-ref: Phase 0.2 round-2 sign-off pending.
