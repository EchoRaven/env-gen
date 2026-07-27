# PIPELINE FIX PROPOSAL #35 — the codehub_open_pr / "no open PR" integrity-nag CLASS

## Symptom (run #34, live, 21:22-21:25)
The orchestrator's thinking log, immediately after committing its memory-bank update:
> "the `codehub_open_pr` tool isn't in my current repertoire… The instructions mentioned 'consider `codehub_open_pr`'… Is this a hallucination in the prompt? … the integrity check is suggesting a PR, however. That's unusual. … I jumped the gun and prematurely used `codehub_commit` instead of first opening a pull request… And then, I prematurely called `finish()`. That's not right."

The orchestrator burned several coordination rounds confused, even considering it had erred by committing — because something told it to open a PR with a tool it does not have.

## Root cause — the CLASS (not one prompt line)
The pipeline moved to **commit-only / framework-auto-integrates** (backend_agent.j2 already says so after #BUG-1; `runtime/hubs/codehub/service.py:1133` "files were already auto-committed/merged"; orchestrator_agent.j2:164 "PRs exist for VISIBILITY only … do not open"). **PR-mode is dead** — nothing anywhere sets `pr_mode`/PR-mode in `task_data` (verified by grep). Yet multiple surfaces still treat "open a PR" as a required step:

1. **`agents/runtime/commit_gate.py:22 + 110-111` — the INTEGRITY CHECK (primary driver).**
   - Line 22: `"unpushed_commits": details.get("ahead",0) > 0 and not details.get("has_open_pr")` — flags *commits-ahead-with-no-PR* as a "loose end."
   - Lines 110-111: renders `**Branch has {ahead} commits but NO open PR** -> consider: codehub_open_pr(...)`.
   - In commit-only mode this state is **normal and complete** — the framework auto-integrates the commit. The check flags correct behavior as a defect and nags every agent that commits (orchestrator confirmed; the lanes hit it next, risking premature finish/un-finish loops).

2. **`agents/runtime/hub_pulse.py:610-612`** — `if commits_ahead_of_main>0 and not my_open_prs: -> consider codehub_commit(...) then codehub_open_pr(...)`. Same wrong advice, repeated every pulse.

3. **`prompts/v3/frontend_agent.j2:71`** — still says `Standard git ops via codehub_commit + codehub_open_pr` and lists `codehub_open_pr` as a tool. This is the IDENTICAL bug #BUG-1 fixed in backend_agent.j2 but missed for frontend. Frontend will hit the same confusion.

4. **`prompts/v3/worker_agent.j2:40,50,61,161`** — four conditional "if PR-mode" references to `codehub_open_pr`. PR-mode is dead, so these are vestigial; they should collapse to commit-only so a spawned worker is never told to open a PR.

5. **`prompts/v3/orchestrator_agent.j2:164`** — already says "PRs exist for VISIBILITY only … do not open," which is correct, but the `codehub_open_pr` mention is what the orchestrator latched onto when the integrity check nagged it. Lower priority; clarify only if cheap.

## ⬛ v2 SCOPE EXPANSION (user directive): fix PROMPT **and** STRUCTURE together
User: "既然 open pr 不需要，那要不就不要给 frontend 这个 tool …需要在 prompt 和 structure 上一同修复."
Prompt-only is half a fix — if a tool is dead, the model should not be OFFERED it at all
(else it stays tempted/confused). So the v2 fix ALSO removes the dead PR tools from the
agent tool surface (structure). Two tools are PR-coupled and dead in commit-only mode:
- **codehub_open_pr** — open a PR (run #34: orchestrator chased a phantom PR).
- **codehub_resolve_conflict(pr_id=...)** (`runtime/hubs/codehub/service.py:876`) — PR-based
  conflict resolution → run #34 "PR not found: 1". The BRANCH-based
  `codehub_resolve_merge_conflict` (`agents/runtime/auto_commit.py:558`) is the live one.

⚠️ DISAMBIGUATION (do NOT touch): `runtime/kickoff/arbitration_table.py:resolve_conflict()`
is a KICKOFF contract-arbitration function, UNRELATED to PRs — KEEP it. Only the codehub
*tool* `codehub_resolve_conflict` (pr_id-based) is being retired.

### Structural removal surfaces (verify each):
- `tool_bundles.py:347` `_bundle_codehub_tools` `include_names` — drop `codehub_open_pr`
  (+ `codehub_resolve_conflict`?). This is the BUILD lever — not built ⇒ never offered.
- `hub_tool_surface.py:39-44` codehub `writes` set — drop the same names (categorization).
- `agents/base.py:277-278` — `codehub_resolve_conflict` in some always/allow set — assess.
- `agents/agents_config.yaml:267` — `codehub_open_pr: api_contract_guard_consulted`
  precondition becomes dead config — remove.
- Underlying methods (`service.py:233 open_pull_request`, `:876 resolve_conflict`) — LEAVE
  the Python methods (no framework caller, harmless) OR remove; reviewer to advise.

### ⚠️ Test blast radius (7 files reference codehub_open_pr) — MUST update, not ignore:
`test_codehub_open_pr_description.py`, `test_prompt_tool_policy_grant_guard.py`,
`test_skill_consult_precondition.py`, `test_monitor_call_gate_invariant.py`,
`test_prelaunch_audit_fixes.py`, `test_live_monitor_endpoints.py`, `test_commit_gate.py`.
Each must be re-pointed or deleted; full suite must stay green.

## Proposed fix — PROMPT half (already drafted, generalizable to all environments)
The principle: **commit IS the complete action; committed work auto-integrates; never advise opening a PR.** No env-specific logic.

- **commit_gate.py:** drop `unpushed_commits` from the loose-end set (commits-ahead-no-PR is not a loose end in commit-only mode). Remove the lines 110-111 block. (Keep `dirty_worktree` → `codehub_commit` advice — that IS a real loose end.)
- **hub_pulse.py:610-612:** replace the "consider … codehub_open_pr" branch with either nothing, or a one-liner "committed work auto-integrates to the integration branch; no PR needed." Keep the genuine PR-review reminders (`prs_needing_my_review`) — those only fire if a PR actually exists, which won't happen in commit-only mode, so they're inert, not harmful.
- **frontend_agent.j2:71:** mirror the backend #BUG-1 fix verbatim — `write_when: "Commit your work with codehub_commit — the framework integrates committed work to the integration branch automatically; you do NOT open a PR."`, `tools: "codehub_list_inline_comments, codehub_commit"`.
- **worker_agent.j2:** collapse the four PR-mode conditionals to commit-only (drop `codehub_open_pr` from tools + the "if PR-mode" steps).
- **orchestrator_agent.j2:164 (optional):** keep "do not open," drop the parenthetical tool name to remove the lure.

## Open questions for the reviewer (verify — do not assume)
1. Is `unpushed_commits` consumed anywhere besides the integrity-check text (e.g. a gate that blocks finish on it)? If a finish/commit gate keys on it, removing it from the *display* is fine but confirm no gate logic regresses. `commit_gate.py:22` builds a dict — trace every consumer.
2. backend retains `codehub_open_pr` gated on `api_contract_guard_consulted` (agents_config.yaml:267) — should we also remove that gate/tool, or leave the tool available-but-unadvertised (prompt already steers away)? Recommendation: leave the tool, fix only the advice/prompts (minimal blast radius); but confirm the integration flow never *requires* a PR for any path.
3. Does any reviewer/verifier flow read PRs (`codehub_list_inline_comments` expects a `pr_id`)? If inline-comment review presupposes a PR, then fully retiring PRs could break the verifier→lane feedback channel. Confirm how inline comments are addressed in commit-only mode before we tell agents PRs never exist.

## Test plan (LOCAL-only, gitignored)
- commit_gate: a state with `ahead>0, has_open_pr=False, dirty=False` now yields NO integrity-check block (was: a "NO open PR" nag).
- commit_gate: a `dirty_worktree` state STILL yields the `codehub_commit` advice (no regression).
- hub_pulse: `commits_ahead>0, no PRs` yields no "open_pr" advice.
- frontend_agent.j2 / worker_agent.j2: assert `codehub_open_pr` absent.
- Existing suite stays green.
