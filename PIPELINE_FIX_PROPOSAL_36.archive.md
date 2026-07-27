# PIPELINE FIX PROPOSAL #36 — run #34 validation-wedge cluster (CLASS C primary)

Run #34 reached VALIDATION (furthest ever) then WEDGED. Diagnosed cluster below; **CLASS C
is the immediate unblocker** (it's why the conflict from CLASS B never resolved). Asking the
reviewer to verify+prescribe CLASS C, and to weigh the CLASS B defense-in-depth.

## CLASS C (PRIMARY / unblocker) — worktree-collision in the strategic merge pre-step
Run #34 log (orchestrator resolving its own branch's conflict):
```
codehub_resolve_merge_conflict FAILED: strategic merge blocked: uncommitted changes in
repo_root on integration could not be moved onto agent/orchestrator before integrating
(fatal: 'agent/orchestrator' is already checked out at .../worktrees/orchestrator)
```
Source: `agents/runtime/auto_commit.py:626-646` in `resolve_merge_conflict_via_strategy`.
When repo_root has tracked-dirty WIP, the code does `git checkout agent_branch` **in
repo_root** (line 636) to move the WIP onto the agent branch before integrating. But
`repo_root` is the BARE project root (it has `integration`/`main` checked out), while every
lane AND the orchestrator hold `agent/<id>` checked out in its OWN worktree
(`worktrees/<id>`). Git forbids checking out a branch that's already checked out elsewhere →
`git checkout agent/orchestrator` fatals → "strategic merge blocked" → the **#22/#23
ownership resolver never runs** (it would have resolved the Dockerfile framework-side — the
`_OWNERSHIP` map DOES cover `Dockerfile`, auto_commit.py:249/261). So the conflict is
unresolvable and validation wedges.

### Diagnosis to VERIFY + open questions for the reviewer:
1. Is `git checkout agent_branch` in repo_root the wrong mechanism whenever `agent_branch`
   is checked out in a worktree (i.e. ALWAYS for orch + lanes)? Confirm the worktree
   topology (repo_root bare on integration; `worktrees/<id>` per agent).
2. WHY is there tracked-dirty WIP in repo_root *on the integration branch* at resolve time
   (the dirt the code tries to move onto agent_branch)? Whose edits are these, and is moving
   them onto `agent_branch` even the right intent — or should repo_root dirt on integration
   be handled differently (committed to the agent's worktree via `git -C worktrees/<id>`,
   or stashed)? The fix must not drop an agent's real work (the existing comment's concern).
3. Prescribe the fix: operate on the branch IN ITS WORKTREE (`git -C worktrees/<lane>
   add/commit`) instead of `git checkout agent_branch` in repo_root? Or detect the
   worktree and skip the checkout? Is this orchestrator-specific or all-lanes?
4. Does `merge_agent_branch_to_main` (the other integration path, auto_commit.py:343) have
   the SAME `git checkout` collision latent? (It says "checkout agent in repo_root" at
   :366.) If so this is a shared class — fix both.

## CLASS B (defense-in-depth) — lanes can write framework-owned files
`path_routed_workspace.py:92` routes ALL of `app/backend/` as writable by the backend lane
(directory-level — "agent owns its worktree", no per-file protection). So the backend lane
overwrote the framework-owned `app/backend/Dockerfile` (added a failing `apt-get install
libpq-dev gcc` — unnecessary; framework `_DOCKERFILE` uses `psycopg[binary]`, clean,
backend_skeleton.py:437). That edit is what CREATED the conflict + (because it built before
integration/overwrite) the apt exit-100 build failure. The `_OWNERSHIP` map already lists
these files framework-side, AND the scaffold overwrites them every tick — so the lane's edit
is *supposed* to be a harmless no-op. But it isn't: it triggers a conflict (→ CLASS C) and a
broken pre-overwrite build. **Question for reviewer:** is a framework-owned-file WRITE GUARD
worth it (reject lane writes to the scaffold's owned files within app/backend & app/frontend,
deny-set DERIVED from the scaffold's written files, not hardcoded), or does fixing CLASS C
(+ existing ownership resolver + scaffold overwrite) make CLASS B redundant? Recommendation:
add the guard — it stops wasted lane rounds + the pre-overwrite broken build at the source,
and the deny-set is deterministically the scaffold's outputs. Enforce where? (write/edit/
apply_patch tool layer, or path_routed_workspace per-file deny within the app routes.)

## CLASS A (secondary) — run_validation output truncation hides the failure
Agents (orchestrator+verifier) repeatedly: "the run_validation output got truncated… I need
the full stack trace" → re-ran run_validation blindly 3×. The business_chain failure detail
(the build error) was not visible to them. Find where run_validation's result is truncated
before reaching the agent context; surface the actionable failure detail (or make it
retrievable, e.g. via inbox/an explicit read) so a lane can self-fix instead of re-running.

## CLASS E (secondary) — contradictory phase messaging
Lanes saw BOTH "14/19 endpoints implemented — you MUST finish them all" AND "VALIDATION
phase — every endpoint is implemented, no new feature work" in the same step. The phase
display/pulse said VALIDATION while the endpoint counter said 14/19 unimplemented. Likely the
phase display (current_run_phase / hub_pulse) diverged from actual endpoint state, or
validation_ready/the verifier trigger fired with endpoints still unimplemented-with-code.
Reconcile the phase signal with all_business_endpoints_implemented (status AND route code).

## Scope ask
Reviewer: focus on CLASS C (verify root + prescribe the worktree-safe fix + check
merge_agent_branch_to_main for the same latent collision). Give a yes/no + rationale on the
CLASS B write-guard. A/E can be lighter (confirm the diagnosis + point at the code to change).
