# GOAL — Next Session (starting at run **r131**)

**Read this first, then `HANDOFF_2026-08-11_netflix_ownerscoping.md` for full context.**
**Commands live in a separate file: `COMMANDS_next_session.md` (copy-paste ready).**

Repo: `/home/haibotong/forgingground-gen`
Branch: `feat/netflix-generality-366-367` (upstream `origin/feat/netflix-generality-366-367`, **ahead 10**)
Next run number: **r131** (r130 was the last; `agent/generated/netflix-web-r130` exists)

---

## 0. NORTH STAR (the standing directive)

> 持续优化整个 pipeline，直到能完美没有 bug 地构建我们目标的环境。

Translated into a measurable target:

> **The generator must produce the multi-milestone Netflix-clone app end-to-end, with rc=0 and
> ≥2 progressive release tags in `codehub_releases.json`, on a SLOW/UNFAVORABLE LLM draw —
> not just on a lucky one.**

The word that matters is **reliably**. We already know the pipeline *can* do this: r115, r118,
r121, r125 delivered clean multi-milestone. The failure mode is **variance**, not incapacity.
So the goal of this session is NOT "get one green run" — a green run on a favorable draw proves
nothing new. The goal is **to remove a source of variance from the framework** and then prove it
with a run.

**The single verdict line you are chasing** (written by the monitor into
`netflix-web-r131_monitor.TERMINAL`):

```
VERDICT:          *** MULTI-MILESTONE VALIDATED *** (>=2 tags + rc=0)
```

---

## 1. WHERE WE LEFT OFF (state you inherit)

### 1.1 Code state
- **11 commits unpushed** (`#566m` → `#566w`). Agent github egress is **403** — *the user pushes*.
  See `COMMANDS_next_session.md` §1.
- Working tree **clean** (framework code). Nothing running. 0 containers.
- Full test suite: **1272 passed** + **73 pre-existing `oauth_contract/test_zoom.py` network
  failures** (no network in the sandbox — UNRELATED, ignore them). Any *new* failure is yours.
  (Baseline was 1266 before #566w added 6 tests — both numbers verified by running the suite.)
- `agent/tests/` is **gitignored** — the per-fix unit tests exist on disk but are NOT in the commits.
  Do not be surprised; do not "fix" the gitignore.

### 1.2 The last four fixes and their validation status

| # | commit | what it fixes | e2e-validated? |
|---|--------|---------------|----------------|
| #566s | `09c8911` | cross-user IDOR in projected CREATE (`_fw_owns` → 403) | ✅ **r129** (IDOR fails = 0) |
| #566t | `2d6054b` | projected CREATE fills DB column DEFAULT for dropped NOT-NULL col | ✅ **r129** (rating-value-null = 0, rating-400 = 0, my-list-GET-400 = 0) |
| #566u | `8b393b2` | projected CREATE upserts owner-scoped state-writes on (owner,subject) conflict → kills rating-409 | ❌ **unit + render only — NEEDS r131** |
| #566v | `0b6f935` | chain read-isolation re-verify tolerates SECURE-override reads (empty list ≠ leak) | ❌ **unit only — NEEDS r131** |
| #566w | `4ab3000` | **kebab-case resources rejoin the projected-read-wins guard** — `/api/my-list` was lane-served because the set holds `my_list` | ❌ **unit + render + r130 counterfactual — NEEDS r131** |

**#566u, #566v and #566w have never run e2e.** That is the first thing r131 buys you.
**#566w is the most important of the three** — see §2.3.

### 1.3 What r130 told us (the important part)

r130 **FAILED rc=1 with 0 tags** — and it wedged on **M1**, which had delivered fine in r127/r128/r129.
Nothing in the framework regressed. What changed was the **LLM draw**.

The lane's own custom handler `_resolve_profile` (in the generated app's `custom_routes.py`)
**oscillated across remediation cycles**:

```
missing-header → 400   (should be 401/403)
cross-user     → 200   (LEAK — should be 403)
own-profile    → 403   (FALSE DENIAL — should be 200)
```

Each remediation cycle the LLM "fixed" one of these and broke another. The gate never cleared.
The dominant chain evidence was on **`/api/my-list`**: `→ 403 (expected [200]` **23x** (false denial
on the caller's own row) alongside `→ 200 (expected [403, 404]` **3x** (cross-user leak) — the same
endpoint failing in *both* directions.

**But "the LLM draw" is only half the story.** The follow-up question — *why was the lane serving
`/api/my-list` at all, when the framework has a guard that makes projected reads win?* — is what
uncovered the actual bug. See §2.3: the guard was silently disabled for kebab-case resources.
A bad draw was the trigger; the missing guard is what let the trigger wedge the run.

---

## 2. ★ THE SYSTEMIC ROOT (this is the thesis of the session)

### 2.1 Two handler layers — internalize this or nothing else makes sense

Generated apps have **two** sources of route handlers:

| layer | authored by | file | registration |
|-------|-------------|------|--------------|
| **PROJECTED** | the framework (`route_projector.py`) | emitted into `main.py` | second |
| **CUSTOM** | the LLM backend lane | `custom_routes.py` | **FIRST** |

FastAPI matches the **first** registered route → a custom handler **SHADOWS** the projected one…
**unless the framework drops it first.** At include time every lane route is filtered through
`_custom_route_overrides_projected(method, path)`; routes it rejects are removed from the router,
so the projected handler serves. That filter is the real control point — §2.3.

Owner-scoping fixes #566s/t/u all live in the **projected** layer, so they are invisible on any
path where the lane's route survives the filter. That is why those fixes were real and correct and
*still* did not save r130 — `/api/my-list` was slipping through the filter.

### 2.2 The variance source, stated precisely

> **LANE OWNER-SCOPING VARIANCE.** The LLM backend writes (and re-writes, per remediation cycle)
> custom handlers that implement owner-scoping ad-hoc. Owner-scoping is *exactly* the class of
> logic an LLM gets subtly wrong — it is a 3-way discrimination (no-auth / not-yours / yours)
> where fixing one branch commonly breaks another. Favorable draws get it right in 1–2 cycles;
> slow draws oscillate until the wall clock or the 7-cycle STUCK-ABORT ends the run.

**This is the highest-leverage remaining bug class in the pipeline** — but the right way to attack
it is **not** to make the LLM better at owner-scoping. It is to make sure the framework's existing
"projected read wins" guard actually **covers every resource it claims to cover**, so the LLM's
owner-scoping is never on the critical path for a CRUD read. #566w is precisely that: it did not
teach the lane anything, it restored coverage the guard had silently lost.

**The generalizable lesson to carry forward:** when a lane-authored handler is misbehaving, first
ask *"should the lane have been serving this route at all?"* before trying to make the lane's code
correct. Check `_custom_route_overrides_projected` for that method+path. A coverage gap in the
guard is cheaper to fix and strictly more reliable than improving LLM output.

### 2.3 The lever — ★ PARTIALLY ALREADY BUILT, AND IT WAS BROKEN BY A ONE-LINE BUG

**Read this carefully — it overturns the "we must build a big new mechanism" framing.**

The framework **already implements** "projected reads win over lane reads" for CRUD shapes
(`#77` for owner-scoped resources, `#528` extended to all registered resources). The gate is
`_custom_route_overrides_projected(method, path)` in the emitted `main.py`: it returns `False`
for a standard-CRUD read on a registered resource, which **drops the lane's custom route** so the
schema-safe, owner-scoped projected handler serves it.

**The bug (#566w, found and fixed this session):** that function compared a **URL path segment**
against `_NESTED_CHILD_RESOURCES` / `_OWNER_SCOPED_RESOURCES`, but those sets are built from
**table names**. Table names are `snake_case` (`my_list`, `continue_watching`); the REST paths for
the same resources are `kebab-case` (`/api/my-list`, `/api/continue-watching`). So
`'my-list' not in {'my_list', ...}` → the guard silently **did not fire** → the lane's custom GET
won → oscillation.

Verified counterfactual against r130's own emitted sets:

```
/api/my-list             before=True  after=False   <== lane-served -> PROJECTED-served
/api/my-list/{id}        before=True  after=False   <== lane-served -> PROJECTED-served
/api/continue-watching   before=True  after=False   <== lane-served -> PROJECTED-served
/api/titles              before=False after=False   (already protected)
/api/profiles            before=False after=False   (already protected)
/api/search              before=True  after=True    (correctly still lane-owned)
```

`/api/my-list` is **exactly** the endpoint that oscillated 403-own / 200-cross-user and wedged
r130. Single-word resources (`profiles`, `titles`) were always protected — which is precisely why
this bug hid for so long: it only bites **multi-word** resources.

**Consequence for planning:** the expensive standardization work below is now a **contingency, not
the primary plan.** Validate #566w first; it may well be the whole fix.

- **(A) SEED + CANONICALIZE — contingency if #566w is insufficient.**
  Add a canonical `_fw_resolve_owner_scope(...)` to `_MAIN_HEADER` and pre-seed a correct
  implementation into the lane scaffold, so the LLM starts from working code instead of inventing
  owner-scoping. Only needed for paths where the lane legitimately still wins (actions, search,
  novel shapes) — a much smaller surface than before.

- **(B) PROJECT + PROTECT — already implemented; #566w repairs it.**
  Nothing new to build. If gaps remain, they are more normalization/coverage bugs in the same
  policy function — look there **first** before writing new mechanism.

---

## 3. OBJECTIVES, IN PRIORITY ORDER

### OBJECTIVE 1 — Push, then establish the r131 baseline *(do this first, always)*

**Why:** #566u and #566v are unvalidated. Launching r131 with the code exactly as it stands
gives you (a) e2e proof or refutation of two fixes, and (b) a fresh, current wedge trace to aim
Objective 2 at. Do not start editing the framework before you have this.

**Do:**
1. Ask the user to push (`COMMANDS_next_session.md` §1). Attempting the push yourself gets 403.
2. Pre-flight (providers up, base images cached, nothing running) — §2.
3. Launch r131 with the multi-milestone env — §3.
4. Start keeper + monitor — §4.
5. While it runs, **do the Objective-2 diagnosis reading** (§5 greps + code reading). Do not sit idle.

**Success criteria (read from the log, §6 greps):**
- `#566u` — rating `→ 409` count = **0**
- `#566v` — `my-list ... expected [403` / "DENIAL-PROBE got success" = **0 or tolerated**
- `#566s` — projected-create IDOR leaks (`POST ... → 2xx (expected [40`) = **0**
- `#566t` — rating-value-null = **0**, rating `→ 400` = **0**
- Ideal terminal: `*** MULTI-MILESTONE VALIDATED ***`

**Interpretation rules (do not skip these — I got burned by both):**
- **Timestamp-check every error you find in the log.** In r129 I diagnosed a wedge from an
  `UndefinedColumn` line that turned out to be from **17:08** when generation ended at **20:48** —
  a stale line from an earlier cycle. Always confirm the error is *after* the last successful
  chain pass. Grep for the later `business_chain: **PASS**` before concluding anything.
- **A green r131 does NOT close the session.** A favorable draw proves nothing about variance.
  If r131 is green, you still owe Objective 2 — and you should be *pleased*, not done.

### OBJECTIVE 2 — Validate #566w, then standardize only if it is insufficient

**#566w (kebab-case resource guard, §2.3) is already implemented, unit-tested and committed this
session.** It is the single highest-probability fix for the r130 wedge class, and it is tiny.

**Do, in order:**

1. **Confirm #566w took effect in r131's emitted app** (do this ~20 min in, as soon as
   `main.py` exists — `COMMANDS_next_session.md` §7):
   - `def _fw_resource_seg(` present in `agent/generated/netflix-web-r131/app/backend/main.py`
   - `_custom_route_overrides_projected("GET", "/api/my-list")` → **False**
   - the lane's custom `my-list` GET is **dropped** at include time (projected serves it)
2. **Watch the r130 oscillation signature specifically** (§6 per-step grep). Success = **zero**
   `my-list ... → 403 (expected [200]` AND zero `my-list ... → 200 (expected [403, 404]`.
   Those two lines appearing together is the oscillation; either alone is a different bug.
3. **Only if the oscillation persists** on a path the lane still legitimately owns (an action verb,
   search, or a novel shape — check with the policy function before assuming), escalate to §2.3
   option (A): canonical `_fw_resolve_owner_scope(...)` in `_MAIN_HEADER` + lane scaffold seed.
   Reuse the existing FK-introspection toolbox (handoff §4); **do not hand-roll introspection.**
4. **If a NEW multi-word resource still slips the guard**, suspect another normalization/coverage
   gap in the same policy function *before* building anything new. Candidate follow-ups already
   visible in the source: the set builder uses `_n.rstrip("s")` (strips **all** trailing `s`, so
   `address` → `addre`) and adds a doubled-plural (`profiless`) — both are sloppy but currently
   harmless; they become real if a resource ends in multiple `s`.

**Success criteria:**
- #566w confirmed live in the generated app (step 1) — this is a *cheap, early* check, do not skip it.
- The r130 oscillation signature does not reappear.
- Any additional change is generalizable, unit-tested with render+compile, no product literals.

### OBJECTIVE 3 — Chain / checklist staleness + gate flapping *(if it blocks; else backlog)*

`run_chains()` only re-runs the **current milestone's** chains. Earlier-milestone chain results go
**stale** and the delivery gate reads `last_result`/`status` (`delivery_gate.py:744-750`) — so the
gate can flap between `business_chain_failing` and clear without any code changing. Same story for
`verification_checklist_not_ready`, which is derived from the four `build:*` CodeHub checks.

Only take this on if r131 (or the Objective-2 validating run) demonstrably wedges **on staleness
rather than on a real failure**. Distinguishing those two is the whole job here — a stale PASS is as
dangerous as a stale FAIL.

### BACKLOG (documented, not this session unless they block)
- rating → **422** "value is required" — fails in **request validation**, i.e. *before* the handler,
  so `_fw_fill_required_defaults` cannot see it. Needs a schema-level fix.
- my-list → **404** on `title_id` FK.
- Same-user readback advisory (diagnostic only — #566p).

---

## 4. GUARDRAILS (hard rules — these exist because violating them cost real hours)

**G1 — Diagnose ground-truth-FIRST, then STOP and REPORT before each 2–3h run.**
A run is a 2–3 hour commitment. Never blind-relaunch after a wedge. Pin the exact failing step from
the log *and* the app code under `agent/generated/netflix-web-rNNN/`, report it, then relaunch.

**G2 — One generalizable, tested framework change per iteration.**
No product literals in framework code. If a fix only works for the Netflix app, it is not a fix —
it is a hardcode, and it will silently break the next target environment.

**G3 — Every `route_projector.py` / `backend_skeleton.py` change gets a unit test that renders a
sample `main.py` via `render_skeleton_main(endpoints, tables)` and `py_compile`s it.**
`_MAIN_HEADER` is a triple-quoted string. A typo in it is not a syntax error in *our* repo — it is
a syntax error in **every generated app**, discovered 2 hours into a run. The render+compile
assertion is the only thing standing between you and that. It is non-negotiable.

**G4 — Never mask an isolation failure without a re-verify.**
#566v tolerates an empty-list read *only* after a fresh-intruder re-verify confirms no rows leak
(`_response_has_rows`). Any future "tolerate this failure" change must carry the same structure:
tolerate *only* on positive evidence of safety, never on absence of evidence. Fail-OPEN is allowed
only on introspection **fault**, never on a policy decision.

**G5 — `pkill` FOOTGUN.** NEVER `pkill -f <pattern>` — the pattern matches your own command line and
you will kill your own shell. Kill by **PID / pgid only**.

**G6 — Do not "fix" BuildKit.** `DOCKER_BUILDKIT=0` is pinned deliberately; the classic layer cache
is the offline build mechanism. Turning BuildKit on breaks offline builds.

**G7 — Timestamp-check every log error before believing it** (see Objective 1 interpretation rules).

**G8 — The run reads the LOCAL tree.** Pushing does not affect a running or future run; the code on
disk is what executes. Conversely, editing files mid-run can affect a run in progress — don't.

---

## 5. DEFINITION OF DONE (for this session)

Ordered from minimum-acceptable to true-done:

1. ✅ 11 commits pushed by the user.
2. ✅ r131 completes and #566u / #566v / **#566w** are **either validated or refuted with a concrete
   log trace**. (Refuted-with-evidence is a perfectly good outcome — it is what the run is *for*.)
3. ✅ If #566w proves insufficient, owner-scoping standardization (§2.3 A) is **implemented,
   unit-tested with render+compile, and committed** as a generalizable change with no product
   literals. If #566w IS sufficient, this item is satisfied by *not* building it — say so explicitly.
4. ★ **A run on a SLOW draw delivers clean multi-milestone** —
   `*** MULTI-MILESTONE VALIDATED ***`, ≥2 tags, rc=0 — with the lane's owner-scoped read correct
   on the first cycle instead of oscillating.

Item 4 is the north star. Items 1–3 are the session's committed scope; item 4 is what you are
building toward and may take another session to land. **Say plainly which of these you achieved —
do not report a favorable-draw green run as if it proved variance was fixed.**

---

## 6. FIRST FIVE MINUTES (literal opening sequence)

1. Read `HANDOFF_2026-08-11_netflix_ownerscoping.md` §1 (two handler layers) and §5 (systemic root).
2. Open `COMMANDS_next_session.md`.
3. Run §2 pre-flight. Confirm: providers up, 5 base images, nothing running, tree clean.
4. Ask the user to run the §1 push.
5. Launch r131 (§3) + keeper/monitor (§4).
6. **While it runs**, confirm #566w took effect in the generated app as soon as `main.py` exists
   (`COMMANDS_next_session.md` §7) — do not idle-wait on the monitor.
