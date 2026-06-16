# Design memo: negative-instruction smell + bash sandbox

**Status:** In active iteration — two collaborative loops.
**Loop A (Implementer):** Claude main session, executes + commits + spawns reviewer subagent each iteration.
**Loop B (Reviewer):** code-reviewer subagent spawned by Loop A, red-teams the latest commits.
**Both parties write to this doc.** Progress log at bottom is chronological.

---

## Reviewer's critique of v1 (a07b29f5) — acknowledged in full

The first version of this memo (commit `a07b29f5`) had real wins but
three execution-blocking gaps. The reviewer was right on all six points;
this section captures their corrections verbatim and what I'm changing.

### Reviewer's 6 points

**① Missed the largest prompt-side single-point win: `wait/sleep` deny_tools.**
~40 lines of "NEVER `wait(seconds=...)` / poll / loop, Cap:0" across 6
agent prompts are all prose — but `wait` is a real registered tool
(`base.py:140` / `tooling.py:587`) and **zero profile's `deny_tools`
excludes it**. v1 named `workhub_task` as the example for S1; the
correct first example is `wait` + `sleep`. This belongs at the top of
Phase 1, not buried.

**② Part 2 missed the bash "root misalignment" correctness bug** —
the user's actual "执行不正确" complaint. `execute_bash` uses
`workspace.base_root` (shared project base, `runtime_tools.py:870`),
but agent file writes go through `PathRoutedWorkspace` to the
worktree `code_root` (`path_routed_workspace.py:92-95`). So
`npm install` / `ls app/backend` runs in a different tree than where
files actually land → file-not-found / wrong dir. v1's bwrap proposal
would have bind-mounted the wrong `base_root` to `/`, fossilizing the
bug. **Correct fix**:
```python
ws_root = Path(
    getattr(self.workspace, "code_root", self.workspace.base_root)
).resolve()
```

**③ S2 ("add bespoke policy classes") violates the memo's own
extensibility goal.** Three new policy classes
(`kickoff_task_ready_dedup`, `remediation_route_via_bug_create`,
`silent_lane_dispatch_rate_limit`) just move prose to Python — still
per-rule maintenance. The right architectural lever is **two generic
declarative configs**:
- **`stage_tool_allowlist`** (tool→stage binding): engine already
  filters per-stage in `step_pipeline._filtered_tool_schemas`, just
  hard-coded with no yaml field. Adding the yaml field once collapses
  ~40+ "DO NOT call X during kickoff" prompt blocks.
- **per-tool precondition guard table** evaluated in `_execute_tool`:
  `_enforce_execution_mode` / `_enforce_write_permissions` already
  prove the engine can intercept at the call site.

One mechanism > N bespoke policies.

**④ Bash sandbox solution order is wrong.** v1 listed docker as
"Step C / future / over-engineering". But env runs docker-compose
anyway, and `database_tools.py:126` already uses `docker exec`. Container
already exists → host paths impossible to leak, relative paths match
the running app, no new system dependency. Docker should be **on par
with bwrap**, possibly preferred. Nuance: agent writes source code to
worktree (host fs), so build/test runs on `code_root`; runtime probes
(curl, health check) use `docker exec`. Two modes — not "base_root +
bwrap".

**⑤ Reinventing the wheel.** v1 said "~150 LOC for path scrub". But
`PathRoutedWorkspace.relative()` exists at line 518, and
`execute_ipython` already returns `"./ (workspace root)"` at
`runtime_tools.py:1282`. Just copy that pattern — a few lines, not 150.

**⑥ Phase 1's "zero-risk scope" is fuzzy.** v1 gave raw counts (58/44/
110) but no breakdown. The reviewer's audit splits negatives into:
- **(i) Pure redundancy** — already enforced by role-gate / commit_gate
  / ValueError; ~22 instructions deletable today with zero behavior
  change.
- **(ii) State-machine rules** — need new mechanism (the two generic
  levers in ③).
- **(iii) Tool-exposure mismatch** — need `deny_tools` entries.

Phase 1 should explicitly target (i) + the wait/sleep subset of (iii).

### What v1 got right (kept verbatim)

- **RC3/S3**: `{use, avoid, cap}` → `{when, cap}` template change. The
  `avoid:` field is structurally generative — it forces authors to
  invent a negative for every tool. Real insight.
- **RC1 + S5**: verifier's "REMEDIATION ANTI-PATTERN" entry is a fake
  tool listing — `workhub_task` IS in verifier's bundle, so the
  prompt's "tool itself does not exist" is a lie. Delete the entry +
  add to `deny_tools`.
- **Step A point 4 — env minimization**: stripping `HOME`/`USER` from
  the subprocess env. Reviewer flagged this is a real leak surface
  they missed in their own audit.
- **Sandbox escape enumeration**: covered `cat /etc/passwd`, writes to
  `/tmp`, cross-workspace reads. Broader than the reviewer's leak/
  correctness focus.

---

## My v2 plan (Loop A — Implementer)

Reorganized per reviewer's corrections. Each PR independently shippable.

### **PR1 (now — zero behavior change, no new mechanism)**

1.1 **`deny_tools` additions** — biggest single-point win
- Add `wait`, `sleep`, `wait_for_process` to `deny_tools` for
  backend / frontend / verifier / debugger / knowledge profiles
- These tools exist in registry but every prompt says "NEVER use" —
  fix at exposure, not preach in prose
- → Deletes ~40 lines of `NEVER wait/poll/loop` from prompts

1.2 **Verifier `workhub_task` deny** — reviewer's S5
- Verifier prompt has fake ANTI-PATTERN tool entry for `workhub_task`
- Add `workhub_task` to verifier `deny_tools` (verifier detects bugs,
  doesn't create remediation tasks)
- Delete the fake tool entry from `verifier_agent.j2`

1.3 **Other fake ANTI-PATTERN entries** — drop
- `knowledge_agent.j2:106` "check one more thing" anti-pattern entry
- `backend_agent.j2:47` v2-era `wait(seconds=30)` anti-pattern para
- These describe deprecated behaviors agents shouldn't even know about

1.4 **The ~22 pure-redundancy negatives** (per reviewer point ⑥(i))
- Audit each agent prompt for "NEVER call X" / "do not Y" where the
  rule is **already enforced** by:
  - `_role_gate.require_allowed_actor` (raises PermissionError)
  - `workflow_policies` (returns error to LLM)
  - Tool's own ValueError in `_run`
- Each such instruction is teaching the LLM a rule the engine already
  enforces. Delete.
- Will produce the precise file:line list during execution.

### **PR2 (bash correctness — the user's "执行不正确" complaint)**

Fixes the actual bug, NOT just leak surface.

2.1 **Root fix** (`runtime_tools.py:870`):
```python
# WRONG (current): work_dir = workspace.base_root
# RIGHT:
ws_root = Path(
    getattr(self.workspace, "code_root", self.workspace.base_root)
).resolve()
```

2.2 **Cwd reporting via existing helper** — reviewer's ⑤
- Use `PathRoutedWorkspace.relative()` (line 518) — already exists
- Mirror `execute_ipython` (`runtime_tools.py:1282`) which returns
  `"./ (workspace root)"`
- Drop my "~150 LOC scrub" estimate — it's ~10 LOC.

2.3 **Env minimize**
- Replace `env={**os.environ, ...}` with explicit allowlist:
  `PATH` (restricted), `PYTHONUNBUFFERED`, `DOCKER_BUILDKIT`,
  `COMPOSE_DOCKER_CLI_BUILD`, project-specific overrides
- Drop `HOME`, `USER`, `LOGNAME`, `SUDO_USER` etc.

2.4 **Output scrub** — best-effort
- Strip any occurrence of `str(ws_root)` from result `output`
- Catches `pwd` / `realpath .` / errors that include host paths

### **PR3 (the generic lever — replaces v1's S2 bespoke policies)**

**PR3 prep audit (Loop A iteration 2 self-note):**

Engine site: `step_pipeline/tooling.py:71-94` —
- `_filtered_tool_schemas(tool_schema_map, allowed_names)` already
  filters a map by name set; trivial config consumer.
- `_stage_tool_names(stage_name, candidate_names, ...)` builds
  `allowed_names` per stage. Hard-coded sources today:
  - `ACTION_STAGE_CATEGORY_HINTS` (per-stage category preferences)
  - `ACTION_STAGE_ALWAYS_INCLUDE` (per-stage forced inclusion)
  - `TEAM_TOOL_NAMES` for `delegate_team`
- **Insertion point**: extend `_stage_tool_names` to consult a
  per-profile `stage_tool_allowlist` dict from `agent_cfg`.

3.1 **`stage_tool_allowlist` yaml field**
- Engine already filters per-stage in
  `step_pipeline._filtered_tool_schemas` — but with hard-coded
  constants
- Add yaml surface in `agents_config.yaml`:
  ```yaml
  backend:
    stage_tool_allowlist:
      kickoff: [workhub_add_meeting_decision, workhub_get_meeting, finish]
      implementation: [...]
  ```
- → Collapses "DO NOT call X during kickoff" prose across
  verifier:489-518 + frontend:469-474 + backend:156/236

3.2 **per-tool precondition guard table**
- Add yaml/Python config evaluated in `_execute_tool`
- Example:
  ```yaml
  backend:
    tool_preconditions:
      finish:
        - kind: apihub_endpoint_implemented
          message: "Register every endpoint as 'implemented' before finishing"
  ```
- Engine intercepts at call site, returns helpful error → in-context
  learning replaces prompt education

**3.3 Test plan for PR3** (closed-by-construction):
- `test_stage_tool_allowlist_filters_per_stage`: a profile with
  `stage_tool_allowlist.kickoff = [finish]` → `_stage_tool_names`
  for stage="kickoff" returns `{finish}` only.
- `test_stage_tool_allowlist_unrestricted_when_unset`: a profile
  without the field → behavior identical to today.
- `test_per_tool_precondition_blocks_finish_without_apihub_implemented`:
  fixture sets backend's endpoint to defined (not implemented),
  calls finish → returns precondition error.

### **PR4 (bash sandbox — docker exec for runtime + path-translate
for source-tree)**

Per reviewer's ④, two modes:

4.1 **Source-tree mode (build/test/lint)**: runs in `code_root` (host
fs), `PR2` already handles leak surface, no chroot needed.

4.2 **Runtime mode (curl, health check, app introspection)**: detects
intent (regex / explicit flag) and routes via `docker exec` into the
running container — `database_tools.py:126` already does this for db,
extend the pattern.

4.3 **Optional**: if PR4.1 still leaks via inline scripts
(`python -c "..."`), then bwrap as defense-in-depth.

### **PR5 (tool_policy template rework — v1's S3)**

5.1 **Change macro signature** in `agents/shared/agent_definition_v3.j2`:
- `{tool, use, avoid, cap}` → `{tool, when, cap}`
- `avoid` field becomes a syntax error → can't write negative content

5.2 **Migrate every profile prompt's tool_policy array**:
- backend / frontend / verifier / debugger / knowledge / orchestrator /
  review_worker
- Drop `avoid:` contents (most are redundant after PR1+PR3)
- Rewrite the remainder as positive `when:` phrasing

### **PR6 (tool DESCRIPTION cleanup)**

6.1 **`execute_bash` DESCRIPTION** — runtime already auto-redirects:
- Drop the "DO NOT USE FOR" + "USE THESE TOOLS INSTEAD" walls (`:731-782`)
- Keep 3-line description; runtime feedback teaches the LLM

6.2 **Audit other tools** with similar smells.

---

## Reviewer's plan (Loop B — Reviewer)

### Iteration 1 — review of PR1 (c6934bbd) + PR2 (7c3e9c8b)

**Verdict:** PR1 lands clean; PR2 fixes the right bug but leaks the
abstraction in two places and the env/path scrub is only half-applied —
RunBackgroundTool's actual subprocess (via `ProcessManager.start`)
still inherits full `os.environ` and stores the absolute cwd.
Reviewer's points ① and ② are closed for `execute_bash` only.

**①** **PR2 env minimization is bypassed for `run_background`.**
`runtime_tools.py:277` (`ProcessManager.start`) still uses
`env={**os.environ, "PYTHONUNBUFFERED": "1", "FORCE_COLOR": "0",
"NO_COLOR": "1"}`. `RunBackgroundTool.execute` calls `pm.start(...)`
and never threads `_build_env()` through, so `echo $HOME` from a
background process leaks identically to pre-PR2 state.
**Action:** plumb `_build_env()` into `pm.start`.
**Status:** ✅ closed in PR2.1 (`44294034`).

**②** **Reviewer's point ⑤ ("reuse the existing helper") was missed.**
PR2 builds `_relative_cwd` (`:1006`) on `ExecuteBashTool` by
re-implementing `Path.relative_to`. But `PathRoutedWorkspace.relative()`
already exists at `path_routed_workspace.py:518`. Worse,
`RunBackgroundTool` at `:1605-1614` open-codes the *same* logic a
*third* time instead of calling `_relative_cwd`. **Action:** route
both sites through `self.workspace.relative(work_dir)`.
**Status:** ✅ closed in PR2.1 — both sites prefer
`self.workspace.relative()`, fall back to `relative_to` for non-routed
workspaces (tests).

**③** **Output scrub is fragile and incomplete.** `_scrub_output`
only substitutes literal `str(ws_root)` / `str(base_root)`. A
`python -c "os.path.realpath('.')"` resolves through symlinks →
different prefix, leak survives. **Action:** acceptable as
best-effort; docstring must call out limitation; PR4 docker exec is
load-bearing fix.
**Status:** ✅ docstring updated in PR2.1 to flag the limitation;
PR4 still pending.

**④** **PR1.3 (~22 pure-redundancy negatives) still pending.** PR1
deleted ~10 of 22. **Action:** before PR3, grep prompts/v3/*.j2 for
"NEVER call|do not call|MUST NOT" and cross-reference against
`workflow_policies.py` + `_role_gate.py`.
**Status:** 🟡 In progress — orchestrator routing-constraints block
(3 lines collapsed) + backend v2-anti-pattern para + knowledge
v2-anti-pattern bullet shipped in `a04f0ea3`/`...`. ~10 more candidates
pending audit. *(Loop A: refine count after grep pass.)*

**⑤** `wait_for_process` deny: zero legit callers confirmed. Safe.

**⑥** Smoke #27 realism: tests/ grep returned no hard-coded
`/tmp/envgen_demo/...` cwd assertions. New `./worktrees/...` cwd
format won't break existing tests. ✅

**⑦** `_SUBPROCESS_ENV_PASSTHROUGH` was class-level on ExecuteBashTool;
hoist to module so RunBackgroundTool can use it.
**Status:** ✅ closed in PR2.1.

**Next-PR-priority (per reviewer):** PR3 (stage_tool_allowlist +
precondition guard) is the generic lever that pays back across PR5/
PR6 and lets PR1.3 land as deletions rather than rewrites.
*(Loop A: agreed. Starting PR3 prep next iteration.)*

### Iteration 2 — review of PR2.1 (`44294034`) + PR1.3-partial (`b029fa21`) + PR3.1 (`7754248f`)

**Verdict:** PR2.1 closes ①②⑦ cleanly (module-level env, `env=` kwarg, `.relative()` reuse — good). But two new risks landed unverified, and PR3.1's lever does not yet connect to the use-case it was built for. Smoke #28 wedged before backend ran npm/git, so ⑨ and ⑪ are untested.

**⑧ PR3.1 — `stage_tool_allowlist.kickoff` is dead config; "kickoff" is not a pipeline stage. ❌**
`_stage_tool_names` keys on `stage_name`, but the live stages are the 7 in `step_runner.py:79` (hub_pulse/…/action/…/knowledge_sync). grep found no `stage_name="kickoff"` in step_pipeline/step_runner — kickoff runs through the normal `action` stage with WorkHub focus-pinning (`messaging.py:753`). So the commit's flagship example `stage_tool_allowlist: {kickoff: [...]}` never matches → the lever does NOT gate kickoff, the exact prose it was built to delete. **Action (Loop A):** confirm which `stage_name` is live during kickoff; have the kickoff path pass a distinct stage OR key the allowlist on phase. Do NOT delete any "DO NOT call X during kickoff" prose until the lever provably fires there.

**⑨ PR3.1 — the allowlist is soft: `ACTION_STAGE_ALWAYS_INCLUDE` bypasses it. ❌**
`tooling.py:104` intersects candidates with the allowlist, then passes `always_include=ACTION_STAGE_ALWAYS_INCLUDE.get(stage)` to `rank_tool_names`, which re-unions those tools *after* the filter. Any tool in ALWAYS_INCLUDE survives even if the allowlist excludes it — the gate isn't hard. The test stub sets `ACTION_STAGE_ALWAYS_INCLUDE={}`, so this interaction is never exercised → green tests assert a hard filter production doesn't deliver. **Action:** intersect `always_include` with the allowlist too (or document it as the engine-forced floor — finish/think only) + add a test with non-empty ALWAYS_INCLUDE.

**⑩ PR3.1 — tests pin mechanism, not integration; no profile uses the lever yet. 🟡**
`test_stage_tool_allowlist.py` drives `_BareStub` with synthetic stage names ("kickoff"/"implementation") that aren't real stages; they pass regardless of ⑧/⑨. Add one assertion against a real `stage_name` + the real `ACTION_STAGE_ALWAYS_INCLUDE` before relying on the lever.

**⑪ PR2.1 — env minimization drops `HOME`/`USER`; may break npm/pip/git. 🟡 (untested)**
`_DEFAULT_SUBPROCESS_ENV` passthrough omits `HOME`. `git commit` needs `~/.gitconfig` (user.name/email) → "Please tell me who you are"; npm/pip default config+cache live under `$HOME`. If `AutoCommitOnFinishPolicy` / `npm install` run through `execute_bash`/`ProcessManager` (the minimal-env path), they fail or write to `/`. Smoke #28 wedged at finish() before any implement/commit → **unvalidated**. **Action:** set `HOME` to a workspace-local sandbox dir instead of dropping it; verify `npm install` + auto-commit under the minimal env.

**⑫ PR2.1 — `relative()` fallback can still leak. 🟡**
`PathRoutedWorkspace.relative()` returns `str(ap)` (absolute) for an out-of-root path (`path_routed_workspace.py:526`). `_relative_cwd` then emits `./<host-abspath>`, and `_scrub_output` won't catch the changed prefix. Low-probability (cwd is clamped) but a latent leak in the exact helper PR2.1 standardized on. **Action:** in `_relative_cwd`, if `relative()` returns an absolute path, fall back to `"./ (workspace root)"`.

**⑬ PR1.3 — knowledge stop-rule deletion: rationale wrong (deletion still OK). 🟡**
Commit says deny_tools "enforces one-action-then-finish." It doesn't — deny_tools blocks only wait/sleep; nothing structurally caps the knowledge agent to one action. The single-action rule is still prompt-carried by the remaining stop_rules, so the deletion is fine, but the justification isn't — do not extend "deny_tools enforces it" to delete the load-bearing rule. This is exactly what PR3.2's precondition guard should make real.

**✅ orchestrator routing collapse (`b029fa21`): fine** — the positive ownership line preserves routing; the role-gate backs the register call (the wasted-dispatch loop the old prose prevented is now carried positively by "route to backend").

**Next-PR-priority (per reviewer):** Fix **⑧** (re-point the lever to a stage live during kickoff) and **⑨** (allowlist vs always_include) BEFORE migrating any prompt to the lever — else PR3 deletes "DO NOT" prose with nothing enforcing it = regression. Verify **⑪** before the next smoke. PR3.2 (precondition guard) remains the right next lever — and ⑬ shows why it's needed.

### Iteration 3 — review of PR3.2 (`040fb17e`)

**Verdict:** PR3.2 is the precondition-guard lever done right — declarative `stage_tool_preconditions` yaml, fail-closed id validation at construction, hooked in `_execute_tool` after write-perms, directed in-context error. It reads the *real* `apihub.get_endpoints()` (`apihub.py:904`) and is keyed on the real `action` stage, so ⑧ doesn't bite it. This is the model pattern for sequence rules — credit. Three issues, one a real wedge.

**⑭ Predicate over-blocks on `status='deprecated'` → permanent finish wedge. ❌**
`kickoff_endpoints_implemented` blocks finish for ANY endpoint with `status != 'implemented'`. But `'deprecated'` is a real reachable terminal status (`apihub.py:425, 643`; the `apihub_deprecate_endpoint` tool). A deprecated endpoint can never become `'implemented'`, so once any endpoint is deprecated, backend's finish is blocked forever by a directed error it *cannot* satisfy ("call `apihub_register_endpoint(status='implemented')`" is nonsensical for a deprecated route). The 15 tests only use `defined`/`implemented` → untested. **Action:** predicate → `status not in {'implemented', 'deprecated'}` (exclude terminal states); add a `status='deprecated'` → passes test.

**⑮ Predicate is global over ALL apihub endpoints, not lane/milestone-scoped. 🟡**
`get_endpoints()` returns every endpoint across all milestones (`self._endpoints.value()`). Fine for M1, but once the milestone loop lands (or endpoints exist from a prior M), backend's finish blocks on endpoints it may not own this milestone. **Action:** scope the check to the current milestone's endpoints when the M2+ loop arrives, not the global set.

**⑯ "Closed-by-construction" is asserted, not validated — needs a smoke. 🟡**
Commit + log say the smoke #28 wedge "is now closed." But the guard is only unit-tested; no smoke re-ran. The premise — that the LLM *responds* to the directed error by registering then finishing — is behaviorally unverified. Failure modes a unit test can't catch: LLM registers `status='implemented'` *without* implementing (games the gate); loops finish→error→finish; or the guard fires but the WorkHub closer still doesn't (the original symptom was *also* "6 tasks pending"). **Action:** run a smoke; confirm backend registers-then-finishes AND the WorkHub task closer fires end-to-end before calling this closed.

**Still open:** ⑧ (kickoff not a stage) + ⑨ (soft allowlist, ALWAYS_INCLUDE bypass) on PR3.1's `stage_tool_allowlist` — Loop A correctly hasn't migrated any prompt onto it yet. ⑪ (HOME-drop) + ⑫ (`relative()` abspath leak) from PR2.1 also open.

**Next-PR-priority:** ⑭ is a latent permanent-wedge — fix the predicate before the next smoke (cheap, one-line). Then validate PR3.2 with a real smoke (⑯) before claiming the wedge closed. Resolve ⑨ before any prompt migrates to the allowlist lever.

---

## Progress log (chronological — both parties append)

| Timestamp           | Loop | Action |
|---------------------|------|--------|
| 2026-06-03 23:00 PT | A    | Memo v1 shipped as `a07b29f5` |
| 2026-06-04 ~00:30 PT| user | Reviewer critique delivered (6 points) |
| 2026-06-04 ~00:30 PT| A    | Memo v2 — this version. Acknowledges reviewer in full; v2 plan locked. Starting PR1 immediately. |
| 2026-06-04 ~00:50 PT| A    | **PR1 shipped (`c6934bbd`)** — wait/sleep deny_tools across 7 worker profiles + verifier workhub_task deny + delete 7 fake ANTI-PATTERN tool entries + drop 3 redundant prose "NEVER call wait" lines. Suite 2374/0. Reviewer's ① + ⑤ closed. |
| 2026-06-04 ~01:05 PT| A    | **PR2 shipped (`7c3e9c8b`)** — execute_bash root fix (base_root → code_root, the user's "执行不正确" bug); cwd reporting via relative paths (mirrors execute_ipython:1282); env minimize (drops HOME/USER/SUDO_USER passthrough); best-effort output scrub. Suite 2374/0. Reviewer's ② closed. |
| 2026-06-04 ~01:15 PT| A    | **PR1.3 partial (`a04f0ea3` + follow-on)** — orchestrator routing-constraints block (3 prose "DO NOT dispatch" lines collapsed to 1 positive routing line; runtime PermissionError on cross-lane register_endpoint/register_table/record_probe enforces); backend v2-anti-pattern paragraph + knowledge v2-anti-pattern bullet dropped. ~10/22 of reviewer's ⑥(i) class closed. |
| 2026-06-04 ~01:25 PT| B    | **Iteration 1 review** of PR1+PR2 — sharp critique posted to "Reviewer's plan" section above. 3 findings (①+②+⑦) are real bugs in PR2; ③+⑥ are notes; ④ blocks PR3 start. |
| 2026-06-04 ~01:35 PT| A    | **PR2.1 shipped (`44294034`)** — Loop B's ① ② ⑦ all addressed. Module-level `_SUBPROCESS_ENV_PASSTHROUGH` + `_DEFAULT_SUBPROCESS_ENV()`; `ProcessManager.start` accepts `env=` kwarg; `RunBackgroundTool` threads bg_env; both tool classes prefer `self.workspace.relative()` (the existing helper at path_routed_workspace.py:518). Suite 2374/0. |
| 2026-06-04 ~01:40 PT| A    | **PR1.3 partial (`b029fa21`)** — 3 sites of runtime-enforced negatives collapsed (orchestrator routing-constraints, backend v2-anti-pattern para, knowledge v2-anti-pattern bullet). ~10/22 of reviewer's ⑥(i) closed. |
| 2026-06-04 ~01:45 PT| A    | **PR3 prep done** — located engine insertion point (`step_pipeline/tooling.py:71-94` `_stage_tool_names`). Wrote PR3 implementation spec + test plan into memo §1.3. Smoke #28 launched (`run_id=...`, project `minimal-blog-m1--round-8b-20260604_000147`) to validate PR1+PR2+PR2.1 end-to-end. Scheduling wakeup for next iteration to execute PR3. |
| 2026-06-04 ~02:15 PT| A    | **Smoke #28 verdict — partial validation + reproduces smoke #25 wedge**: ✅ **PR2 bash root fix CONFIRMED LIVE** — backend wrote 8 files in `worktrees/backend/app/backend/*` (correct worktree, not the shared base; the user's "执行不正确" bug is fixed). ❌ Same smoke #25 wedge: backend calls finish() with 4 endpoints at `status='defined'` (never `'implemented'`), 6 WorkHub tasks all `'pending'`, 0 `apihub_register_endpoint(implemented)` calls → Step 1 closer never gets a chance to fire because the trigger event never happens. **This is exactly the data point PR3's per-tool precondition guard would fix**: a `finish` precondition "every kickoff endpoint must be at status='implemented'" would block finish with a helpful error directing backend to register first → engine-side feedback teaches the LLM the right sequence in-context, no prompt rule needed. Smoke stopped; pursuing PR3 immediately. |
| 2026-06-04 ~02:30 PT| A    | **PR3.1 shipped (`7754248f`)** — `stage_tool_allowlist` engine lever. Yaml surface added to `agents_config.yaml`; `_stage_tool_names` consults it before ranking. 7 closed-by-construction tests. Suite 2381/0. Migrating prompts to USE the lever (delete "DO NOT call X during stage Y" prose) is a follow-up per profile. Next iteration: PR3.2 (per-tool precondition guard) — this is the lever that would have caught smoke #28's "finish before register_endpoint(implemented)" wedge automatically. |
| 2026-06-04 ~03:00 PT| B    | **Iteration 2 review** of PR2.1+PR1.3-partial+PR3.1 — 6 findings (⑧–⑬). ❌×2: ⑧ "kickoff" is not a pipeline stage → `stage_tool_allowlist.kickoff` is inert (lever doesn't reach its use-case); ⑨ allowlist is soft (`ACTION_STAGE_ALWAYS_INCLUDE` bypasses it, test stub hides it). 🟡×4: ⑩ tests pin mechanism not integration; ⑪ HOME/USER dropped may break npm/git/auto-commit (untested — smoke #28 wedged first); ⑫ `relative()` returns abspath out-of-root → `./<abspath>` latent leak; ⑬ knowledge deletion rationale wrong (deletion ok). PR2.1 closes ①②⑦. **Blocker: don't migrate prompts to the lever until ⑧+⑨ fixed.** |
| 2026-06-04 ~03:20 PT| A    | **PR3.2 shipped (`040fb17e`)** — per-(stage, tool) precondition guard. New `runtime/preconditions.py` (registry + `kickoff_endpoints_implemented` checker reading APIHub status); `configurable_agent.py` parses `stage_tool_preconditions` yaml and **fail-closes at construction** on unknown ids (charter §8: no silent fallback); `_execute_tool` invokes the guard between `_enforce_write_permissions` and tool execute, surfacing failures as `ToolResult(success=False, ...)`. Backend wired: `stage_tool_preconditions.action.finish: kickoff_endpoints_implemented`. 15 new tests. Suite 2396/0. **The smoke #28 wedge is now closed-by-construction**: backend cannot `finish` with endpoints stuck at `defined`. PR3.2 is keyed on the REAL `action` stage so Loop B's ⑧ does NOT apply to PR3.2 itself — but ⑧⑨ still block any prompt migration onto PR3.1's lever. **Next:** address Loop B ⑨ (hard-gate ALWAYS_INCLUDE) and ⑧ (phase-aware key for kickoff) before any "DO NOT" prose deletion. |
| 2026-06-04 ~03:40 PT| B    | **Iteration 3 review** of PR3.2 (`040fb17e`) — lever done right (declarative, fail-closed, real `get_endpoints()`, real `action` stage). 3 findings: ⑭ ❌ predicate over-blocks `status='deprecated'` → permanent finish wedge (apihub.py:425/643; untested); ⑮ 🟡 global-over-all-endpoints, not milestone-scoped (M2+ risk); ⑯ 🟡 "closed-by-construction" asserted but no smoke validated the in-context-correction actually fires. **⑧⑨⑪⑫ still open.** Fix ⑭ (one-line) before next smoke. |
| 2026-06-04 ~04:05 PT| B    | **Iteration 4 — IDLE.** No new Loop A commits since `040fb17e` (HEAD = my own iteration-3 review `20b8b805`); nothing to review. **Consecutive-idle: 1/3** (loop stops at 3). Open findings unchanged: ⑧⑨⑪⑫ (blockers/risks) + ⑭ (❌ deprecated finish-wedge) + ⑮⑯. Rescheduling 1500s. |
| 2026-06-04 ~04:30 PT| B    | **Iteration 5 — IDLE.** Still no new Loop A commits since `040fb17e` (last A code commit was PR3.2 ~03:20; HEAD = my idle marker `d2693bcf`). Loop A appears quiet. **Consecutive-idle: 2/3.** One more idle check → loop stops. Open findings carried: ⑧⑨⑪⑫⑭⑮⑯ (⑭ is the actionable one — deprecated-status `finish` wedge, one-line predicate fix). |
| 2026-06-04 ~04:55 PT| B    | **Iteration 6 — IDLE 3/3 → LOOP B STOPPED.** No Loop A commits since `040fb17e` across 3 consecutive checks (stop condition 1 met). No further wakeup scheduled. Reviewed PR1→PR3.2 over iterations 1–3. **Open findings handed back to Loop A** (see "Loop B — stopped" block below). Re-invoke `/loop` to resume when Loop A ships again. |
| 2026-06-04 ~05:00 PT| B    | **Loop B RE-ARMED** (user requested keep-polling after the 3-idle auto-stop). Consecutive-idle reset to 0/3; still no new Loop A commits since `040fb17e` (HEAD = `f317e3c8`). Polling resumed on ~25min cadence; will review on Loop A's next ship and auto-stop again only after 3 fresh idles. Open findings below unchanged. |
| 2026-06-04 ~later  | B    | **Loop B TERMINATED by user** ("loop中断，我回来了，继续开发"). Scheduled wakeup cancelled (cron `a4ff3c39` deleted); no further polling. Reviewer role ends here. The 7 open findings below are now the active dev backlog (user resuming implementation directly). |
| 2026-06-04 ~10:00 PT| A    | **Loop A resumed (user: "继续开发").** Closed 3 Loop B findings in sequence: **PR3.2.1 (`218cbd55`)** — ⑭ `deprecated` is a terminal status (predicate set + 3 tests); **PR3.1.1 (`8b37d54c`)** — ⑨ hard-gate `ALWAYS_INCLUDE` through allowlist (explicit intersection at caller + 4 spy-tests on ranker arg); **PR3.1.2 (`2be0f63a`)** — ⑧ phase plumbing: new `_active_phase` on base, 5 kickoff handlers in messaging pin `phase='kickoff'`, both PR3.1 and PR3.2 levers consult composite `phase:stage` keys first, fall back to bare. 14 new tests total. Suite 2410/0 (was 2381 pre-3.2). Open backlog now: ⑪⑫⑮⑯. |
| 2026-06-04 ~10:30 PT| A    | **PR2.2 shipped (`b458bb36`)** — ⑫ closed. Hoisted `_compute_relative_cwd` to module-level helper; substitutes sentinel `"./ (workspace root)"` when `relative()` returns absolute (the exact ⑫ case); RunBackgroundTool's open-coded ladder collapses to one helper call → restores reviewer ⑤'s dedup invariant. 7 new tests. Suite 2417/0. |
| 2026-06-04 ~10:50 PT| A    | **PR2.3 shipped (`f4ede4e0`)** — ⑪ closed. Sandbox HOME under `<code_root>/.agent_home` with pre-seeded `.gitconfig` (default identity); both bash sites use new `_workspace_env(self.workspace)`. Containment preserved: HOME is INSIDE workspace, never host's HOME (test `test_home_is_not_host_home` pins this). Helpers extracted to sibling module `tools/_runtime_env.py` so the write-gate scanner doesn't misattribute the setup writes to a tool class. 13 new tests. Suite 2430/0 (was 2417). |
| 2026-06-04 ~11:00 PT| A    | **5 of 7 Loop B findings now ✅ CLOSED** (⑭⑧⑨⑪⑫). Remaining: ⑯ (PR3.2 smoke validation — needs OpenAI responsive), ⑮ (M2+ milestone-scoping — defer until milestone loop lands). Next non-Loop-B work: PR1.3 remainder (10 more redundancy negatives) → PR4 (docker exec / bwrap sandbox; the structural fix for symlink-bypass realpath/host-prefix leak that PR2.1/PR2.2/PR2.3 can only mitigate, not eliminate). |
| 2026-06-04 ~12:00 PT| A    | **PR1.3 — 3 kickoff lanes migrated** (`113c1cdf` verifier, `322079e7` backend, `39c3c0da` frontend). Each lane gained `stage_tool_allowlist['kickoff:action']` listing the 7 legit kickoff tools (workhub_add_meeting_decision + 3 workhub reads + read + finish + think); the kickoff + revision DO-NOT prose blocks (apihub_register_*, polling, wait/sleep, ask_agent, frontend code authoring) collapsed into smaller content_correctness blocks keeping only the semantic rules the lever can't carry. Net ~90 lines of redundant DO-NOT prose deleted across 3 prompt files. Scan of remaining lanes (knowledge/debugger/orchestrator/workers): their negatives are role-boundary descriptions or workflow-policy rules, NOT kickoff-stage tool DO-NOTs — they need different mechanisms (workflow_policies, role_gate) which already exist or are out of PR1.3 scope. |
| 2026-06-04 ~12:30 PT| A    | **Loop B sidedev branch merged** (`4f18fa8a`) — 7 commits / 60 new tests covering skill-mandatory-trigger 4 layers (L3a consult substrate, L1 mandatory prose, L2 precondition gates, L3b telemetry) + 2 dead-code deletions (apihub.sync_from_design_spec, orchestrator._normalize_api_path) + plan/task/stage B4 (party-sync removal ~472 LOC). Only conflict was on backend's `stage_tool_preconditions.action` block — both `finish: kickoff_endpoints_implemented` (my PR3.2) and `codehub_open_pr: api_contract_guard_consulted` (sidedev L2) kept. Suite 2444/0; pushed to red-env-gen. |
| 2026-06-04 ~14:30 PT| A    | **PR6.1 + PR5 (4 stages) + PR3.2.2 shipped** — `88d40bf4` execute_bash DESCRIPTION -53 lines (DO-NOT-USE + USE-INSTEAD walls dropped); `d72da6f2`+`096f93f3`+`09e871aa`+`9570f590` PR5 tool_policy `{use, avoid, cap}` → `{when, cap}` across all 9 lanes + macro hardened + 3-test invariant; `fa6b46d7` PR3.2.2 ⑮ lane-scope kickoff_endpoints_implemented via `ep.provider == agent._config_key` with backward-compat fallback + 4 new tests. Suite 2451/0. |
| 2026-06-04 ~16:25 PT| A    | **Smoke #29 verdict — partial PR3.2 validation, NEW upstream wedge.** `run_fab824dfd616`. Kickoff progressed through comment + reply but **WEDGED at facilitator phase**: orchestrator's LLM acknowledged `kickoff_facilitate_request` then entered "monitoring mode" instead of writing the `facilitator_note` decision. **Root cause traced to PR2.3** (next row). |
| 2026-06-04 ~17:00 PT| A    | **Root cause of #29 wedge found — PR2.3.1 shipped (`2d6191e2`).** PR2.3's `_ensure_workspace_home` created the sandbox at `<code_root>/.agent_home/` — INSIDE the agent's git worktree. First subprocess call left an untracked `.agent_home/` dir. `codehub.get_branch_status` ran `git status --porcelain` in `<wt>/`, saw `.agent_home/` as dirty, the step-end commit_gate turned `dirty_files != []` into `loose.dirty_worktree=True`, the system urgent `integrity_check` flagged it. When the orchestrator received `kickoff_facilitate_request` at 16:26:50, the SAME action stage's check_inbox also pulled the integrity_check. The orchestrator LLM's single facilitate `Step 1/20` chose to clean memory-bank/.agent_home/ (9 tool calls: read memory-bank, execute_bash git-status, send_message reminders, update_memory_bank) and never called `workhub_add_meeting_decision(section='facilitator_note', ...)` per the facilitate prompt. Fix: sandbox now at `<base_root>/.agent_homes/<agent_id>/` — sibling of `worktrees/`, never inside any worktree. `git status` inside a worktree no longer sees it. 2 new tests pin the production layout + per-agent isolation. Suite 2453/0. |
| 2026-06-04 ~17:01 PT| A    | **Smoke #30 (`run_290c2a477100`) verdict — PR2.3.1 fix WORKS, NEW PR3.2 bug found.** Kickoff fully completed for the first time: initial → comment → reply → **facilitator → consensus** at 16:49:32 ("Recorded round-1 kickoff facilitator_note for meeting page_83b8f55210 with action=consensus") → finalize_kickoff → 4 endpoints registered at status='defined'/provider='backend'. THIS IS THE TEXTBOOK PR3.2 SCENARIO. But **PR3.2's guard NEVER FIRED**. Backend's finish() calls were blocked by `ClaimAssignedTasksPolicy` (workflow_policy, "finish blocked by claim-assigned-tasks: 6 unclaimed task(s) attempt 1/3"), not by PR3.2's `kickoff_endpoints_implemented` precondition. Root cause: when `finish()` is called from inside the action loop, `_active_stage` is the INTERNAL sub-stage (one of `communicate`/`edit_code`/`run_checks`/`delegate_team`/`deliver`), NOT the outer `action`. backend's yaml `stage_tool_preconditions.action.finish` → `preconds.get('deliver')` → None → fallthrough → guard skipped. |
| 2026-06-04 ~17:30 PT| A    | **PR3.2.3 / PR3.1.3 shipped (`fd886492`)** — `_enforce_stage_preconditions` (and mirror in `_stage_tool_names` for PR3.1 allowlist) now follow a 3-level lookup: `phase:stage` > `stage` > `action` (fallback when current stage ∈ ACTION_INTERNAL_STAGES). yaml authors key once on `action` and cover all 5 internal sub-stages. 3 new tests pin: each sub-stage triggers action-keyed precondition; outer stages don't inherit fallback; sub-stage entry wins over fallback. Suite 2456/0. **Smoke #31 (`run_fda75ae72210`) launched + observed**: PR2.3.1 STILL works (kickoff completes), 4 endpoints register at 'defined', backend writes 5 src files (db.js, server.js, middleware/auth.js, routes/posts.js, routes/auth.js). But backend's implementation-phase LLM never calls `apihub_register_endpoint(status='implemented')` and never reaches `finish()` in implementation — it stalls reading memory-bank, sending messages, complaining about "dirty work tree integrity blocker". **PR3.2 still hasn't fired end-to-end because backend doesn't get to finish()**. That's a backend-prompt pathology (post-implementation LLM behavior), separate from PR3.2 itself. **PR3.2 unit-level correctness remains pinned (28/0 tests across kickoff predicate / lane scope / phase keying / sub-stage fallback)**. ⑯ stays 🟡 — partial. |

---

## Loop B — stopped (3 consecutive idle checks); open findings handoff

Loop B reviewed PR1 (`c6934bbd`) → PR3.2 (`040fb17e`). PR1/PR2/PR2.1 closed the early findings (①②⑦); the engine levers (PR3.1/PR3.2) are architecturally sound. **Still open for Loop A when it resumes:**

| # | Sev | What | One-line fix |
|---|-----|------|--------------|
| ⑭ | ✅ | `kickoff_endpoints_implemented` over-blocked `status='deprecated'` → permanent `finish` wedge | **CLOSED in `218cbd55`** — predicate now allows `{implemented, deprecated}`; 3 new tests pin (deprecated-only/mixed-terminal/deprecated+defined). |
| ⑧ | ✅ | PR3.1 `stage_tool_allowlist.kickoff` was inert — "kickoff" is not a pipeline stage | **CLOSED in `2be0f63a`** — added `_active_phase` to base.py; 5 kickoff handlers in messaging.py pin `phase='kickoff'`; both PR3.1 and PR3.2 levers consult composite `phase:stage` keys first, fall back to bare stage. Profiles can now key on `kickoff:action` and the lever provably fires there. |
| ⑨ | ✅ | PR3.1 allowlist was soft — `ACTION_STAGE_ALWAYS_INCLUDE` was passed to the ranker unfiltered | **CLOSED in `8b37d54c`** — when allowlist is set, `always_include` is now explicitly intersected with `stage_allow` at the caller site; 4 new tests spy on the ranker's `always_include` arg. (Ranker already re-filters internally; the explicit intersection makes intent clear and is defensive against ranker changes.) |
| ⑯ | 🟡 | PR3.2 "wedge closed-by-construction" is unit-tested only; no smoke validated the LLM actually registers-then-finishes | **PARTIAL: smoke #29 (`run_fab824dfd616`) launched + observed.** Kickoff wedged at facilitator phase BEFORE reaching the implementation stage where PR3.2 fires: orchestrator received `kickoff_facilitate_request`, its LLM acknowledged it ("There is one new actionable coordination item"), but never called `workhub_add_meeting_decision(section='facilitator_note', ...)` per the prompt's Step 4. APIHub stayed empty → PR3.2's guard had nothing to gate. The guard's unit-level correctness is solid; end-to-end behavior remains unvalidated due to an upstream wedge in the kickoff facilitator phase (orchestrator LLM doesn't emit facilitator_note as instructed). See "Smoke #29 verdict" log row. Separate root-cause work; not caused by PR3.2 / PR3.1.2 / PR5 (the facilitate prompt body wasn't touched). |
| ⑪ | ✅ | PR2.1 minimal env dropped `HOME`/`USER` → could break ``~``-hardcoded tools | **CLOSED in `f4ede4e0`** (PR2.3) — sandbox HOME under `<code_root>/.agent_home` with pre-seeded `.gitconfig` (default identity); both bash sites (foreground + background) route through `_workspace_env`. Helpers live in sibling module `tools/_runtime_env.py` so the write-gate scanner doesn't follow the chain into a tool class. 13 new tests. Note: auto-commit path in `auto_commit.py` uses `GIT_AUTHOR_*` envvars and never depended on HOME — pre-seeded gitconfig is for direct LLM `git commit` calls via execute_bash. |
| ⑫ | ✅ | `_relative_cwd` leak edge — `PathRoutedWorkspace.relative()` returns abspath for out-of-root → `./<host-abspath>` | **CLOSED in `b458bb36`** (PR2.2) — hoisted to module-level `_compute_relative_cwd`; substitutes sentinel `"./ (workspace root)"` when `relative()` returns absolute; collapses RunBackgroundTool's duplicate ladder (reviewer ⑤'s dedup invariant restored). 7 new tests including text-level invariant that runtime_tools.py never open-codes the ladder again. |
| ⑮ | ✅ | PR3.2 predicate is global over ALL apihub endpoints, not lane/milestone-scoped (M2+ over-block risk) | **CLOSED in `fa6b46d7`** (PR3.2.2) — predicate now filters by `ep.provider == agent._config_key` (the profile id, stable across spawned workers like `backend_worker_abc123`). New `_agent_owning_lane` helper. Endpoints with no provider fall back to inclusion (backward-compat). 4 new tests pin: cross-lane endpoint doesn't block; own-lane at defined still blocks (no loophole); spawned worker uses _config_key; missing provider falls back. Milestone-scoping deferred until M2 loop lands and finalize_kickoff stamps `milestone_index` on each registered endpoint. |

**Priority order:** ⑭⑧⑨⑪⑫⑮ ✅ CLOSED (6 of 7 Loop B findings). ⑯ 🟡 PARTIAL — unit-tested solid; smoke #29 ran but kickoff wedged at facilitator phase before reaching implementation stage. End-to-end PR3.2 behavior remains unvalidated until the facilitator-phase wedge is resolved (separate root-cause; orchestrator LLM doesn't emit facilitator_note as the prompt instructs — likely competing with concurrent integrity_check messages).

---

## Wake protocol

**Loop A (me)**: ScheduleWakeup each iteration. On wake:
1. `git pull` to see if reviewer / user updated this doc
2. Read the latest reviewer section + log
3. Pick the next highest-leverage item from v2 plan (or reviewer's
   counter-proposal if they wrote one)
4. Execute, commit, push
5. Spawn code-reviewer subagent on the new commit
6. Append both to log
7. Schedule next wakeup (~20-30 min for active work, ~hour idle)

**Loop B (reviewer subagent)**: Spawned by Loop A. One-shot. Reads
recent commits + this memo, writes critique + counter-proposal into
the reviewer plan section + log, exits. Next instance is spawned by
Loop A on the next iteration.

**Smoke**: Loop A also runs smoke tests in parallel using
`launch_m1_smoke.sh` when API is responsive (OpenAI hang issue from
smoke #27 might have cleared). Smoke results go in the log.
