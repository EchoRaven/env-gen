# Workspace / Root model redesign

> Status: PROPOSAL — written for external review.
> Author trail: hand-edits on each new symptom led to fragmented logic;
> this doc steps back and re-derives the model. No code change until
> reviewer signs off.

## 1. What this is about

After several rounds of patching, the meaning of "workspace" and
"root" inside the env-gen runtime has fragmented. Each newly observed
bug got a narrow local fix and the model is now contradictory in
parts. Two recently observed symptoms (which prompted this doc):

* The Design Agent could not see reference screenshots because
  `list_reference_images()` resolved against the per-agent worktree
  (`<project>/worktrees/design/screenshots`) which is empty, instead
  of the project root (`<project>/screenshots`).
* The verifier was running probes against assets that don't exist yet
  in its worktree because path lookups also assume the wrong root.

Both are downstream of the same unanswered question: **for any given
file path an agent asks about, which physical directory backs it?**

## 2. What the runtime currently has

Concrete layout for a project named `<P>`:

```
<P>/
  app/                                  # code (per-agent worktree owns this)
  design/                               # specs (shared)
  screenshots/                          # reference images (shared, read-only)
  references/                           # UI-uploaded refs (shared, read-only)
  .memory/                              # not currently used at root
  shared/hubs/*.json                    # JsonStore-backed hub state
  worktrees/
    orchestrator/   (the bare repo lives here as default branch)
    design/         (branch=agent/design)
    backend/        (branch=agent/backend)
    frontend/       (branch=agent/frontend)
    database/       (branch=agent/database)
    verifier/       (branch=agent/verifier)
    knowledge/      (branch=agent/knowledge)
```

Each agent has its `workspace.root` set to a different place depending
on its phase / construction path:

* Orchestrator's `workspace.root` = `<P>` (no worktree)
* Phase-0-per-agent worktree pattern: `workspace.root` = `<P>/worktrees/<id>`
* `PathRoutedWorkspace` (introduced earlier): routes `app/*` to the
  worktree but other paths to base — but this is only wired for some
  call sites.

The result: a file tool can be called by the same agent in the same
step and resolve the same string differently depending on which entry
point built its `workspace`.

## 3. Three asset categories the agents touch

It is useful to name them because the right backing root differs.

| Category | Examples | Read/Write | Owner | Lives at |
|----|----|----|----|----|
| **A. Per-agent code** | `app/backend/server.js`, `app/frontend/src/App.jsx` | RW (by owning agent) | Whichever agent's branch | per-agent worktree |
| **B. Shared spec / design** | `design/spec.api.json`, `design/README.md` | W by design, R by all | design | project root |
| **C. Shared read-only assets** | `screenshots/login.png`, `references/*` | R by all, W by orchestrator init only | orchestrator (at init) | project root |
| **D. Hub state** | `shared/hubs/*.json` | R/W via `HubRegistry` — never via file tools | hubs themselves | project root |
| **E. Per-agent memory / scratch** | `.memory/`, scratch dirs | RW by owning agent | each agent | per-agent worktree |

`D` already correctly goes through `HubRegistry` and never touches
file tools. The rest is where the confusion lives.

## 4. What "workspace.root" should mean

Today the field is overloaded: callers treat it as both "the directory
this agent writes its own code into" and "the directory file tools
should resolve every relative path against". Those are not the same
thing once we have per-agent worktrees and shared assets.

Three plausible models:

### Model A — `workspace.root` = worktree, tools fall back to project root

The model the most recent (now-reverted) patch was heading toward. Each
file tool grows a "if not in worktree, try project root" branch.

Pros:
* Minimal new surface area.
* Tools that need the worktree (e.g. `write` to `app/...`) keep working.

Cons:
* Every tool that touches paths needs the fallback to be added
  individually — the bug recurs each time a new tool ships.
* The model is implicit: callers cannot tell from the API which paths
  resolve where.
* Tests easily miss the fallback path.

### Model B — `workspace` becomes a `PathRoutedWorkspace` everywhere

Generalize the existing `PathRoutedWorkspace` so it owns ALL routing
decisions, and remove the ability for tools to read `workspace.root`
directly. Tools call `workspace.resolve("design/spec.api.json")` and
the workspace returns the right absolute path.

Routing table (proposal):

| Path prefix | Resolves to | Rationale |
|----|----|----|
| `app/` | worktree | code |
| `design/` | project root | shared specs |
| `screenshots/` | project root | shared refs |
| `references/` | project root | shared refs |
| `mockups/`, `images/`, `assets/` | project root | shared refs |
| `shared/` | project root | (hub state is read via registry; this is just for inspect tools) |
| `.memory/`, `memory/` | worktree | per-agent scratch |
| everything else | worktree (default) | safe default — local |

Pros:
* Routing decision lives ONCE.
* Tools stay simple.
* Same idea already exists in the codebase — just incompletely wired.
* New routes are an additive table change with a test.

Cons:
* Need to audit every direct `workspace.root` use and convert it.
* Some uses are legitimately "I want the worktree" — those need a
  named accessor (`workspace.worktree_root` / `workspace.project_root`).

### Model C — sync shared assets into each worktree

At worktree creation, copy or symlink `screenshots/`, `references/`,
`design/` from project root into the new worktree. Tools then resolve
against the worktree as before.

Pros:
* Zero tool changes.
* Single physical root per agent.

Cons:
* Spec files (`design/spec.api.json`) are written BY one agent and
  read BY others — synced copies diverge. Either you symlink them
  (now you have shared write), or you accept staleness.
* Worktree creation cost grows.
* For screenshots (read-only) a symlink would be fine; for design
  specs it isn't.
* Mixed approach (symlink some, copy others, leave others) re-creates
  the very fragmentation we are trying to fix.

## 5. Recommendation

**Model B** — generalize `PathRoutedWorkspace` to cover all five asset
categories, remove direct `workspace.root` reads from file tools, and
expose two named accessors:

```python
workspace.resolve(relpath: str) -> Path     # the only path-resolution call
workspace.worktree_root -> Path              # explicit, for tools that need it
workspace.project_root -> Path               # explicit, for tools that need it
```

Why B over A and C:
* A is the pattern that produced the bugs in the first place. Choosing
  it locks in "each new tool is a new chance to forget the fallback".
* C handles read-only assets fine but breaks down on shared writes
  (design specs). Half-applied C is worse than no C.
* B centralizes the decision. A reviewer can read one table and know
  where every path lives.

## 6. Migration plan (only relevant if Model B is approved)

External reviewer's framing absorbed and made concrete here. Their
diagnosis ("the right abstraction was chosen, the migration just
didn't finish — half state is worse than either pure model") is
correct, and verifications below were re-counted against the
current tree on 2026-05-28:

* `workspace.root /` concat sites in tools (every one of these is a
  potential mis-route): **44**
* `workspace.resolve(...)` call sites in tools (the right pattern):
  **26**
* Direct `Workspace(output_dir)` instantiations bypassing the routed
  wrapper across `tools/` + `multi_agent/`: **87**
  — concentrated in `tools/docker_tools.py` (5 distinct constructors,
  each falling back to `Path.cwd()` on miss) and `tools/__init__.py`'s
  tool factory.
* `WorkspaceManager._can_write` permission machinery
  (`workspace_manager.py:251`, plus `AGENT_WRITE_DIRS` at L32 and
  callers at L205, L291, L326): still present, still wired, but the
  real write path is now routed through `PathRoutedWorkspace` /
  worktrees and never consults `_can_write`. Dead model running in
  parallel.

### The five-step migration

These are ordered so each step is shippable on its own and reduces
risk for the next one.

1. **Kill the bypass `Workspace(output_dir)` constructors** — the
   biggest single source of the half-migration. `tools/__init__.py`
   and `docker_tools.py` (5 sites each + `Path.cwd()` fallbacks)
   currently `new Workspace(output_dir)` instead of taking the
   routed workspace by injection. Convert to constructor injection:
   tools receive the routed workspace from the same pool the agent
   uses. Acceptance: `grep "= Workspace(" tools/ multi_agent/` returns
   0 hits in production paths.

2. **Ban `.root /` concatenation in tools** — convert all 44 sites to
   `workspace.resolve(...)`. Add named accessors only where the
   intent really is "give me the worktree directory" (e.g. for the
   tools that `cd` into the worktree for shell commands):
   `workspace.code_root` (worktree) and `workspace.base_root`
   (project root). Deprecate `.root` with a runtime warning, then
   delete it after one cycle.

3. **Data-driven routing table.** Today `app/` is the only "per-agent"
   prefix, hardcoded in `path_routed_workspace.py`. Make the table
   an explicit declaration shipped with the workspace:

   ```python
   ROUTING_TABLE = [
       # (prefix,        target,        notes)
       ("app/",           "code_root",   "per-agent code"),
       ("design/",        "base_root",   "shared specs"),
       ("screenshots/",   "base_root",   "shared refs (read-only)"),
       ("references/",    "base_root",   "UI uploads (read-only)"),
       ("mockups/",       "base_root",   "shared refs"),
       ("images/",        "base_root",   "shared assets"),
       ("docker/",        "base_root",   "compose/runtime files"),
       ("shared/",        "base_root",   "hub state (inspect only)"),
       (".memory/",       "code_root",   "per-agent scratch"),
       ("tasks/",         "base_root",   "task definitions"),
       # default fall-through: code_root (safe local default for writes)
   ]
   ```

   The table is what a reviewer reads to know where a path lives;
   adding a new prefix is a one-line table change with a test.

4. **Pick one permission model and retire the other.** Two clean
   options:
   * **Fold write-scope into the routed workspace.** Each route entry
     gains an `allowed_writers: Optional[Set[str]]`. The routed
     workspace's resolve-for-write rejects writes from non-allowed
     agents. Then `WorkspaceManager._can_write` + `AGENT_WRITE_DIRS`
     get deleted.
   * **Formally retire `_can_write`.** Worktree isolation + the
     auto-merge gate already act as the write boundary at the git
     layer. `_can_write` becomes a no-op deprecation shim, then
     deleted after one cycle. The routed workspace just routes; git
     guards the rest.

   Reviewer suggests "二选一"; this doc recommends the second (let
   git be the boundary) because it removes machinery rather than
   adding to it. Open for discussion.

5. **Delete the "guess N locations" fallbacks.** Once routing is
   authoritative, `view_image`'s 5-prefix loop +
   `verification_tools.py`'s `app/backend/routes` /
   `backend/src/routes` / `backend/routes` triple-try (and the
   matching frontend variants) collapse to a single `resolve()`.
   Each removed fallback is one less place a future bug can hide.

6. **Permanent guard.** A test that fails the build if any module
   outside `workspace/` references `workspace.root` directly or
   constructs `Workspace(...)` directly. Same shape as the
   `test_no_ghost_tool_references.py` guard added last round. This
   is what prevents the half-migration from recurring.

## 7. What still needs a decision from you

After the external review, the model question is settled (Model B,
data-driven routing table) and the migration sequence is clear.
Three things still need your call before code touches:

1. **Permission model — fold or retire?** (Step 4.) The reviewer says
   "二选一". This doc recommends RETIRE (`_can_write` deletion,
   worktrees + merge gate are the boundary). The alternative is
   FOLD (per-route `allowed_writers`, then delete `_can_write`).
   FOLD gives stricter mid-step protection; RETIRE is simpler.
   **Default if you don't answer: RETIRE.**

2. **Sequencing — big-bang or phased?** Steps 1-2-3-5 together touch
   ~130 files. Three options:
   * **Phased** (recommended): land step 1 (kill bypass constructors)
     alone in one PR, step 2 (`.root` → `.resolve()`) in a second,
     step 3 + step 5 + step 6 in a third. Three reviewable PRs,
     pipeline keeps running between them because each lands a
     non-breaking superset.
   * **Big-bang**: all at once. One PR, one merge, faster to a clean
     state, harder to review.
   **Default if you don't answer: PHASED.**

3. **Do we lock the routing table now**, or treat the §6 step 3 table
   as a draft that can be edited during step 3? Locking now means
   the reviewer can sign off on the exact table; leaving it open
   means we can adjust if step 3 surfaces a route nobody anticipated.
   **Default if you don't answer: LOCK NOW** (table in §6 step 3 is
   the source of truth; future additions require a one-line PR with
   a test).

### Resolved by reviewer / verification (no longer open)

* "Project root vs worktree as the shared root" — project root. The
  base layout `<P>/` is the canonical shared root; worktrees are
  views over `<P>/app/`.
* "shared/hubs visibility from file tools" — route to base, read-only.
  Inspect-debug only; canonical writes still go through `HubRegistry`.
* ".memory/ scope" — per-worktree is correct. It's per-step scratch.
  Cross-step memory already lives in `HubRegistry.workhub` /
  generator_memory's persisted state, not the filesystem.
* "Write protection for screenshots/references/" — covered by the
  permission model decision (Step 4). With RETIRE, worktree-as-
  sandbox catches it because routed reads can't accidentally hit
  base. With FOLD, the route entry's `allowed_writers={}` makes it
  explicit.
* "Backward compat" — monitor's log resolution does NOT go through
  the routed workspace; that path stays untouched.

## 8. What this doc does NOT cover

* The verifier wake-up timing issue (separate concern — was being
  discussed before this design pulled focus).
* Hub-registration sticky tools (already landed).
* Symlink-vs-copy tradeoffs for the bundled screenshot library
  (`tools/screenshot/`) — orthogonal.

---

Hand back to reviewer. No code will change until a model is picked.
