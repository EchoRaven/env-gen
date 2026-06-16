# Pipeline Process Design (living doc)

> Co-designed 2026-06-05+. One section per flow. Each flow = a relatively-fixed
> **SOP** (standard procedure) that agents follow, operating over a **stateful hub
> kernel**. We design these one-by-one.

## §0 — Design model (the lens for every flow)

The pipeline is **fixed SOPs over a stateful hub kernel**. Three ingredients:

1. **Artifact state machine** — every contract noun (milestone, endpoint, table,
   page, predicate) has an explicit **lifecycle** of states + legal transitions +
   who may trigger each + what each transition **emits**.
2. **Dependency graph** — typed edges between artifacts, declared by the consumer:
   `page → endpoints it calls`, `predicate → endpoints/flows it covers`,
   `endpoint → tables it touches`, `mcp_tool → endpoint` (1:1). The hub owns the
   graph (`register_consumer` already records it).
3. **Reactive propagation** — a status transition on a producer is computed
   through the graph and **notifies the affected consumers**, who run their own
   re-evaluate SOP. This is what keeps N agents aligned without a babysitter.

**Where each constraint lives (the tier rule):**
- **Construct** — if it's deterministic + identical every env, the runtime makes it
  (spine DDL, AS, MCP, fixed-surface registration). No LLM, no gate.
- **State machine / hub-enforced** — lifecycle transitions, dependency edges,
  change-propagation. Structural, universal, domain-agnostic.
- **Prompt SOP** — the *steps* an agent takes and the *content* it authors. Freedom
  lives here; the SOP just sequences the hub operations around the work.
- **Gate (last resort)** — only a structural-universal invariant that can't be
  constructed (e.g. "build context has a Dockerfile"). **Litmus:** "true for EVERY
  valid env regardless of what it does?" If no → it's a prompt SOP, not a gate.
  A gate must NEVER encode a domain assumption (no hardcoded path lists, etc.).

## §0.5 — Agent execution model: three step types (foundational)

Every SOP is a sequence of steps, and a step is exactly one of three kinds. The
engine dispatches by kind — this is how tool-calling stays useful *and* the
procedure stays fixed.

| Step kind | Executed by | Tool-calling? | Examples |
|---|---|---|---|
| **Procedural / bookkeeping** | the **framework**, deterministically | none — no LLM | register page `defined`, add consumer edge, flip status → `implemented`, notify consumers |
| **Structured-output** (bounded creativity) | LLM returns **typed data**; framework executes the consequence | no tools — `StructuredOutput` | kickoff section, `RoadmapReview`, "which endpoints does this page consume", a status decision |
| **Agentic sub-loop** (open creativity) | LLM **free tool-calling** over a **scoped** menu | full tools, scoped per step | write business code, design the UI, debug |

**The core shift:** contract bookkeeping moves from *"a tool the LLM chooses to
call"* to *"a consequence the framework executes from the LLM's structured
output."* The agent never "calls `register_endpoint`" — it *returns* the endpoint +
the tables/consumers, and the framework registers it. The whole "agent forgot to
register / set the wrong status" drift class disappears **by construction**.

**Tool-calling concentrates in the agentic sub-loops** (the genuinely open work),
where it shines; structured-output handles bounded creativity; procedural steps
have no LLM at all. So tools fit *better*, not worse, than the flat-menu model.

**Escape hatch (not a railroad):** inside an agentic sub-loop an agent may *intend*
a contract change (e.g. "I need another table") → that intent **enters** the
relevant modify-SOP (§5). Macro control-flow is a fixed state machine; micro
creativity is free; agents enter SOPs by intent, not by being dragged through a
script.

**Implementation path:** this is an evolution of the existing engine, not a
rewrite — `execution_pipeline.stages` is already a staged loop,
`stage_tool_allowlist` already scopes tools per stage, and workflow
`StructuredOutput` already returns typed data. We converge these into one explicit
SOP definition per `role × trigger`, each step tagged with its kind, dispatched by
the engine.

## §1 — Artifact lifecycles (DRAFT — open for re-division)

| Artifact | States | Owner / who transitions | Transition emits |
|---|---|---|---|
| **Milestone** | `drafted → in_review → revised → finalized → in_development → delivered` | orchestrator drafts; all agents review | review requests; kickoff trigger on `finalized` |
| **Endpoint** | `defined → implementing → implemented → revising → implemented` (+ `deprecated`) | backend; orchestrator for the fixed surface | on `revising`/breaking change → notify consumers (pages, predicates) |
| **Table** | `defined → implemented → revising → implemented` | backend / runtime (spine = construct) | on change → notify backend refs |
| **Page** | `defined → implementing → implemented → revising` | frontend | declares endpoint consumers on `defined` |
| **Predicate/Test** | `defined → covered → passing \| failing → revising` | verifier | on producer change → re-validate |
| **MCP tool** | `implemented` (constructed 1:1 from endpoints) | runtime | — |

`kind` (business \| auth \| oauth \| infra \| spine) is a **structural attribute** of an
endpoint, set at registration — used to route SOPs/gates by structure, never by path.

**An endpoint carries TWO orthogonal dimensions** (D5.1):
- **lifecycle** (producer side, single value): `defined → implementing → implemented → revising`.
- **claims** (consumer side, a set of in-edges): *claimed by* `[page, …]` + *covered by*
  `[predicate, …]`. A claim is a consumer's declared dependency, surfaced on the
  endpoint ("endpoint X: implemented, claimed by home-page + detail-page, covered by
  test-3"). The claims set is the live dependency graph (§8) and is what makes
  "who breaks if I change?" a hub query, not tribal knowledge. Same shape applies to
  tables (claimed by endpoints).

## §2 — Project skeleton (phase order)

```
STARTUP: milestone planning  (project-level, all agents review)   →  §3
  └ for each finalized milestone:
       KICKOFF: contract negotiation for this milestone's slice    →  §4
       DEVELOP: lanes run their add/modify SOPs over the hub        →  §5
       VERIFY:  verifier validation (docker + smoke from contract)  →  §6
       DELIVER: gate + advance to next milestone                    →  §7
```

## §3 — FLOW: Project startup / milestone planning  (SETTLED 2026-06-05)

**Goal:** turn the raw project description into a finalized, all-hands-reviewed
milestone roadmap, BEFORE any per-milestone kickoff. **Distinct phase from
kickoff** (D3.1 ✓): planning decides *what the slices are*; kickoff (§4) negotiates
*one slice's contract*. Reuses the existing meeting infra (WorkHub meeting page +
meeting decisions + facilitator), as a `planning` meeting (milestone_index=0).

**Milestone definition (D-gran ✓):** M1 = thinnest end-to-end vertical slice (auth
+ 1 entity + 1 flow — the walking skeleton). Each later Mᵢ builds ON the previous
ones, adding features per user feedback + the final requirements. Milestones are
cumulative, never throwaway.

**SOP:**
1. **Convene** — orchestrator selects ALL agents (backend, frontend, verifier,
   debugger) as participants and **broadcasts the project intro** (mandatory first
   action).
2. **Draft milestones** — orchestrator drafts the breakdown + a real doc per
   milestone at `docs/milestones/M<i>.md` (D3.4 ✓ — real files; reviewers read
   them, kickoff consumes them as scope input), registers each `Milestone` as
   `drafted`, assigns each participant to review.
3. **Per-role structured review** (D-struct ✓) — each participant returns a
   `RoadmapReview` (schema below), not freeform prose; milestone → `in_review`.
   Each reviews from its lens:
   - **backend** — API/data feasibility; is each slice's backend scope coherent + sized right?
   - **frontend** — UI/flow clarity; reference assets available; UI scope sized right?
   - **verifier** — testability; is each milestone's acceptance expressible as concrete predicates?
   - **debugger** — **generation/bring-up reliability** (NOT security; we only care
     about generating the env): will this slice come up + run cleanly?
     dependency/sequencing/bring-up-order risk, seed-data feasibility,
     observability/debuggability. The "what'll be painful to generate or run" voice.
4. **Revise + re-review** — orchestrator addresses blocking concerns, revises the
   docs (→ `revised`), re-assigns. **Bounded to 2 rounds** (D3.3 ✓). On
   non-convergence the orchestrator **finalizes anyway** and records the remaining
   blocking concerns as **risks** on the milestone (planning never blocks the
   whole project on perfection).
5. **Finalize** — milestones → `finalized`; emits the kickoff trigger for M1 (→ §4).

**`RoadmapReview` (the structured return):**
```python
{
  "role": "backend" | "frontend" | "verifier" | "debugger",
  "decision": "approve" | "request_changes",
  "concerns": [
    {
      "milestone_id": "M2",
      "topic": str,                 # short label, e.g. "slice too big", "bring-up order"
      "detail": str,                # the concern in 1-2 sentences
      "severity": "blocking" | "minor",
      "proposed_change": str,       # concrete fix the orchestrator can apply
    }, ...
  ],
}
```
Aggregation rule (orchestrator): any `blocking` concern across the 4 reviews →
another revise round (up to 2). All `approve` / only `minor` → finalize.
`concerns` may span milestones (lets debugger flag cross-milestone sequencing).

## §4 — FLOW: Per-milestone kickoff  (DESIGNING NOW)

**Goal:** negotiate ONE milestone's **business** contract; finalize ⇒ register it +
emit the task graph. The fixed surface is GIVEN, not negotiated.

**Empirical driver (smoke-notes, 2026-06-05):** two runs both died at kickoff —
(a) backend declared `GET /health` → "endpoint has no UI consumer"; (b) after a
prompt fix, frontend's login screen referenced `POST /auth/login` → "UI call to
undefined endpoint" (backend business-only didn't define it). BOTH are the same
root cause: **the fixed surface isn't in the contract the cross-check sees.** Prose
conventions can't fix it (the frontend rightly references `/auth/login`). →

**D4.1 (settled by evidence):** register the fixed surface (spine tables `kind=spine`,
AS/`/auth` `kind=auth`, `/oauth` `kind=oauth`, control plane `kind=infra`) in
APIHub/SchemaHub **before** the kickoff meeting opens. Lanes then SEE it via
`apihub_list_endpoints`. (Move `orchestrator._register_contract_surface` to
pre-kickoff. The milestone's *business* tables/endpoints still register at finalize.)

**D4.2 (settled by evidence):** cross-checks resolve references against the
**registered contract** (fixed + whatever business the meeting has declared) and key
off the structural `kind` — "needs a UI consumer" applies to `kind=business` only;
fixed surface is exempt by attribute, never by path. The frontend MAY reference
`/auth/login` (resolves to `kind=auth`); no lane may add/modify the fixed surface.

**D4.3 (REFRAMED by smoke #3, 2026-06-05 — the real gap):** finalize is
**consensus ⟹ tasks created AND DISPATCHED**, atomically. Smoke #3 reached
`finalized` with `tasks=11 predicates=9 failures=0` — so tasks ARE created. The gap
is **dispatch**: the lanes only enter implementation when they receive a
`task_ready` *from the orchestrator* (`KickoffBootstrapGate`, allowed_starters=
['orchestrator']), but the orchestrator relies on the `kickoff_complete`
subscription + a later "nudge" — which (a) isn't a `task_ready` so doesn't pass the
gate, and (b) arrives AFTER the lanes have burned their idle budget on empty
kickoff-reply finishes and been `LaneIdleCircuitBreaker`-halted (frontend → tier-3
`lane_halted_human`). Result: 11 tasks unclaimed, no app code, orchestrator drifts
to delivery empty.

**Fix direction (the §5-entry framework step):** finalize → register contract +
create+assign tasks + **immediately dispatch a `task_ready` from the orchestrator to
each assignee** (a `[P]` step, not a subscription/nudge race) AND reset the lanes'
idle counter at the kickoff→implement phase boundary (kickoff replies must not
pre-halt the implementation phase). This is the deterministic version of "consensus
⟹ work starts."

**SOP:** fixed surface pre-registered → lanes author BUSINESS sections (may
reference fixed surface) → synthesize + kind-aware cross-check → bounded revision
→ finalize = register business contract (`defined`) + emit task graph atomically →
lanes get `task_ready` (→ §5).

**OPEN:**
- **D4.4** Attendees: backend + frontend + verifier (debugger lives in §3 + §6)?
- **D4.5** Round bound (today 3) + on non-convergence: abort vs finalize-with-risks
  (planning §3 finalizes-with-risks; should kickoff too, or is a broken contract a
  hard stop?).

## §5 — FLOW: Development SOPs  (DESIGNING NOW)

Every artifact moves `defined → implementing → implemented`. The `defined` state is
**born** either at kickoff (framework, from the lanes' structured sections) or
mid-development (a lane, by intent — §5.2). Implementation is then the same SOP
regardless of who created `defined`. Steps tagged `[P]`rocedural / `[S]`tructured /
`[A]`gentic per §0.5.

### §5.1 — Implement a `defined` artifact (the main loop; endpoint↔backend, page↔frontend)
Trigger: `task_ready` for an artifact in `defined`.
1. `[P]` framework → status `implementing`; hands the lane the artifact's contract
   (from hub) + its declared dependencies.
2. `[A]` lane does the open work — backend writes the route/handler; frontend
   downloads design assets, builds the page. Scoped tools (write/edit/bash/lint;
   frontend also view_image/capture).
3. `[S]` lane returns the realized links: frontend → the endpoints the page actually
   calls; backend → the tables the endpoint touches.
4. `[P]` framework → record consumer/table edges, run the minimal build-presence
   check, status → `implemented`, emit `implemented` event.

### §5.2 — Add a NEW artifact mid-development (intent-driven; the escape hatch)
Trigger: inside §5.1's `[A]` loop a lane forms intent "I need endpoint/page X not in
the contract."
1. `[S]` lane returns the new artifact's contract (endpoint: method/path/response_key
   /tables; page: route + consumed endpoints).
2. `[P]` framework registers it `defined`; runs the kind-aware cross-check against
   the registered contract (§4 D4.2); if it touches others, notifies them.
3. → falls into §5.1 to implement it.

### §5.3 — Modify an existing artifact (your "backend 改 API"; reactive producer side)
Trigger: a lane forms intent "endpoint X's shape must change."
1. `[S]` lane returns the proposed change (new shape).
2. `[P]` framework → status `revising`; **computes the impact set from the dependency
   graph** (pages consuming it + predicates covering it) and **notifies exactly those
   consumers** with the specific affected page/test (the hub generates this — see §8).
3. `[A]` lane implements the change.
4. `[P]` framework → status `implemented`; this transition **triggers §5.4 in each
   notified consumer**.

### §5.4 — Re-evaluate on dependency change (consumer side; the alignment engine)
Trigger: a producer this lane depends on went `revising`→`implemented`.
1. `[P]` framework wakes the consumer with the changed artifact + the specific
   dependent items it owns (this page / this test).
2. `[S]` consumer returns `{needs_change: bool, what}`.
3. `[A]` if needed, consumer updates its page / test.
4. `[P]` consumer re-tests; framework records the re-validation; statuses settle.

> §5.3 + §5.4 are the whole point: a producer change pulls *exactly* the right
> consumers into a bounded re-evaluate loop, with **no orchestrator babysitting** —
> the dependency graph (§8) routes it. Backend never has to "remember" who uses its
> API; the hub knows.

**SETTLED (2026-06-05):**
- **D5.1** Lifecycle stays `defined/implementing/implemented/revising`; `claimed` is
  NOT a lifecycle phase — it's the **consumer relationship** on the endpoint
  ("claimed by page X", "covered by test Y"), i.e. the §8 dependency in-edges (see §1).
- **D5.2** Done = lane self-declares via `[S]` "done" **AND** the framework verifies
  the structural minimum (build-critical files present + lint clean) before the `[P]`
  flip to `implemented`. Both — lane declares intent, framework verifies the floor.
- **D5.3** Unified — `predicate` is a §5.1-style artifact: `defined` at kickoff →
  `covered` when the test is written → `passing | failing` on run.

## §8 — Dependency graph & reactive propagation (the alignment engine)  (DESIGNING NOW)

The hub owns a **typed dependency graph**; consumers declare the edges. This is the
machine under §5.3/§5.4 — the thing that lets a producer change pull *exactly* the
right consumers in, with no orchestrator babysitting.

**Edges (declared by the consumer side):**
- `page --claims--> endpoint` — surfaced as "endpoint claimed by page". (`register_consumer` today.)
- `predicate --covers--> endpoint | flow` — the verifier's test coverage edge.
- `endpoint --reads--> table` — response references tables.
- `mcp_tool --projects--> endpoint` — 1:1, constructed (§3c), not declared.

**The propagation rule (reactive, hub-executed):** when an artifact transitions in a
way that can break consumers (shape change / `revising` / `deprecated`):
1. `[P]` hub queries the **in-edges** ("who claims/covers me?")
2. `[P]` hub computes the **impact set** — the specific pages + predicates (NOT "the
   frontend lane" — the *exact artifacts*)
3. `[P]` hub emits a **targeted notification** to each owner, naming the dependent item
4. each owner enters **§5.4** (re-evaluate). Backend never addresses anyone by name —
   it just transitions state; the graph routes the consequence.

**The cross-checks become live graph queries, not a one-shot kickoff gate:**
- *dead endpoint* = an endpoint with zero claims (and `kind=business`).
- *UI call to undefined* = a page claim whose target endpoint doesn't exist.
- *table drift* = an endpoint `reads` a table not in the schema.
These now hold **continuously** (every add/modify re-checks the local neighbourhood),
not just at kickoff. The §4 kickoff cross-check is the *first* evaluation of the same
queries — same engine, run early.

**Breaking-change handling** (APIHub already has `get_breaking_changes` + breaking-change
task creation) is the canonical §5.3 trigger: a shape change to a *claimed* endpoint is
a breaking change → notify claimants → §5.4. We're formalizing what's half-built.

**SETTLED (2026-06-05):**
- **D8.1** Claims are **field-level**: a page claims `endpoint + the response fields it
  reads`. The impact query on a change only wakes claimants whose claimed *fields*
  changed → fewer false "you're affected" wakeups, tighter alignment.
- **D8.2** When a producer goes `revising`, claimants **do NOT block** — they proceed
  against the last `implemented` shape and **reconcile when it returns** (§5.4). Keeps
  lanes parallel; the cost is occasional rework, which the reconcile loop absorbs.

## §6 — FLOW: Verification  (DESIGNING NOW)

The verifier owns **predicates** — structured acceptance checks derived from the
contract. Lifecycle `defined → covered → passing | failing`; a predicate carries
`covers` edges (§8) to the endpoints/flows it asserts.

### §6.1 — Author predicates (kickoff; §5.1-style)
`[S]` verifier returns predicates, one+ per critical `user_flow`:
`{flow, kind: api_smoke | ui_flow, target, assert}` → `[P]` framework registers each
`defined` + records the `covers` edges.

### §6.2 — Cover a predicate (write the test)
`[A]` verifier writes the docker-driven smoke test → `[S]` returns which predicate it
covers → `[P]` predicate → `covered`.

### §6.3 — Run validation
**Trigger (structural — the real ⚠2):** the hub emits `validation_ready` when **every
business artifact in the milestone is `implemented`** — a hub query over lifecycle
states, NOT a lane finish-notify heuristic. Also re-triggered per §5.4 when a
`covered` endpoint changes.
1. `[A]` verifier brings up `docker compose` + runs the covered tests.
2. `[P]` framework → each predicate `passing | failing`.
3. `[P]` on `failing`: hub routes via the `covers` edge to the owning producer
   (api_smoke fail → the endpoint's backend; ui_flow fail → the page's frontend) +
   the debugger triage SOP. Owner re-enters §5.1/§5.3 → re-validate.

> The trigger is "all business artifacts `implemented`?" (state query) — it can't fire
> early on a half-built tree and can't stall on a missing notify. This is the
> structural form of the ⚠2 fix.

**OPEN: D6.1** predicates only at kickoff, or verifier may add mid-dev (escape hatch
like §5.2)? (lean yes — uniform.)

## §7 — FLOW: Delivery  (DESIGNING NOW)

A milestone is `delivered` when acceptance holds. The gate is **mostly a hub query**
(construct/state-machine tier), not LLM judgment.

**Blockers — the minimal structural-universal set (pass the §0 litmus):**
- `docker compose up` succeeds (the env actually runs).
- every `kind=business` endpoint is `implemented` AND claimed (no dead endpoint);
  every page `implemented`; no dangling claim.
- every CRITICAL predicate is `passing`.

**Advisory (recorded, never block):** visual-review diffs, non-critical predicate
fails, nice-to-haves → carried forward as risks / next-milestone input.

**SOP:**
1. `[P]` orchestrator composes the delivery gate as the hub query above.
2. blockers remaining → route each to its owner (an unsatisfied artifact/predicate
   with a known owner) → §5/§6 fix loop. **Not** a full abort.
3. `[P]` all blockers clear → milestone → `delivered`.
4. `[P]` `delivered` emits the next milestone's kickoff (§4); M(i+1) builds ON M(i)'s
   delivered state (cumulative).

**OPEN: D7.1** at the FINAL milestone, `delivered` → triggers the env
relocation/registration (`envs/<env>/` + `env.yaml`/`mcp.yaml`/`pool.yaml`) so the
agentsuite-red pool can consume it. (lean: yes — last-milestone delivery = "pool-ready".)
