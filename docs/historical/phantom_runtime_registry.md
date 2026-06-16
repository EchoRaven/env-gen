# Phantom Runtime Principal Registry

A **phantom runtime principal** is an actor name that appears in
runtime code (either as a default actor string OR as a candidate for
inclusion in a Phase X.Y gate's allowed_set) but is **not** an agent
profile in `agents_config.yaml`. Phantom principals are the most
common reason a gate ships broken: the gate admits a name nothing
ever claims as its identity, so empty-actor fallthrough or
PermissionError fires for 100% of real callers.

This doc is the canonical registry of all currently-known phantoms.
Each entry tells the next implementer:
- where the phantom name appears
- which gate / phase it would unblock
- the principal-pin recipe
- the order of operations to lift it from phantom to real

Maintainers: update whenever a new gate workflow flags a phantom
during its phantom-identity adversarial lens (e.g. workflow
`wvimglo1v` for Phase 4.6 expansion).

## Phantom inventory

### 1. `contract_test_runtime` (Phase 3.5 — Path B simplified SHIPPED; phantom DEFERRED)

- **Status (per user 2026-05-31 decision):** Phase 3.5 SHIPPED via
  Path B simplified — the endpoint_contract namespace + verdict-field
  amendment ship WITHOUT widening the Phase 4.4 allowed_set to
  include `contract_test_runtime`. Phase 4.4 stays `{verifier}`-only;
  the `contract_test_runtime` principal stays parked until a real
  runtime caller is introduced. Commit pending.
- **Why parked:** widening the allowed_set with a principal nobody
  authors as creates a permanent unused entry — exactly the
  phantom shape this registry exists to prevent. Path B keeps the
  authorship surface honest.
- **When to revisit:** ONLY when a real contract-test runtime
  component lands (scheduled contract-test runner that authors
  `record_api_test` rows on behalf of the verifier lane). At that
  point: define `CONTRACT_TEST_RUNTIME_PRINCIPAL` in
  `runtime/_role_gate.py`, widen `{verifier}` →
  `{verifier, contract_test_runtime}`, thread the principal as
  `agent=` at the new runtime callsite, and update this row.
- **Where it appears today:** design notes
  (`docs/phase_3_5_endpoint_contract_design_notes.md`) +
  roadmap (`docs/phase_4_plus_roadmap.md:84-90`). Zero references
  in runtime code. Phase 4.4 production gate at apihub.py:467 is
  the `{verifier}`-only authorship lock.

### 2. `visual_similarity_runtime` (Phase 3.9 — Path B simplified SHIPPED; phantom DEFERRED)

- **Status (per user 2026-05-31 decision):** Phase 3.9 SHIPPED via
  Path B simplified — the `visual:<route>` namespace + resolver ship
  WITHOUT widening the Phase 4.5 `submit_visual_review` allowed_set
  to include `visual_similarity_runtime`. Phase 4.5 stays
  `{visual_reviewer}`-only; the `visual_similarity_runtime`
  principal stays parked until a real SSIM-based programmatic
  reviewer component is introduced. Commit pending.
- **Why parked:** mirrors the Phase 3.5 contract_test_runtime
  rationale — widening an allowed_set with a principal nobody
  authors as creates a permanent unused entry. Path B keeps the
  authorship surface honest while still shipping the resolver +
  story-gate plumbing.
- **When to revisit:** ONLY when a real programmatic SSIM-based
  visual reviewer lands (a runtime component that computes SSIM
  and authors visual_review approvals on its own). At that point:
  define `VISUAL_SIMILARITY_RUNTIME_PRINCIPAL` in
  `runtime/_role_gate.py`, widen `{visual_reviewer}` →
  `{visual_reviewer, visual_similarity_runtime}`, thread the
  principal as `reviewer=` at the new runtime callsite, and
  update this row.
- **Where it appears today:** design notes
  (`docs/phase_3_9_visual_route_design_notes.md`) + roadmap
  (`docs/phase_4_plus_roadmap.md:96-101`). Zero references in
  runtime code. Phase 4.5 production gate at gate_registry.py:323
  is the `{visual_reviewer}`-only authorship lock.

### 3. `runhub` (Phase 4.6 expansion / Phase 2.5 already-shipped)

- **Status:** PARTIALLY-PHANTOM. `runhub` is a real hub-internal
  actor string used in `hubs/runhub/service.py:89, 105, 221, 224,
  247, 344` as the actor passed into JsonStore writes. It is NOT a
  configured agent profile in `agents_config.yaml`.
- **Phase 2.5 record_probe gate** already admits this principal
  (runtime-only idiom — `require_runtime_actor` admits exactly
  `{"runhub"}`). This works because RunHub itself authors probe
  records as a runtime component, not via an agent profile.
- **Where the phantom risk lives:** any FUTURE gate (e.g. Phase 4.6
  expansion's proposed `record_check` allowed_set) that adds `runhub`
  to a regular allowlist gate's allowed_set without using the
  runtime-only `require_runtime_actor` helper would be confused —
  agents would never claim `agent="runhub"`, so the gate would never
  fire.
- **Pin recipe:** use `require_runtime_actor` (singleton `{"runhub"}`
  semantic) NOT `require_allowed_actor` for any future gate whose
  trust source is RunHub. Don't bundle `runhub` into a multi-actor
  allowlist.

### 4. `ui_user` / `unknown` (Phase 4.6 expansion callsite cleanup)

- **Status:** REAL phantom — these are placeholder default strings
  used in HTTP shims (`live_monitor_server.py`) and some retry paths
  (`hub_registry.py:413-419`'s record_check retry uses
  `agent=publisher` which can be any string).
- **Phase 4.6 ship note in `runtime/elaboration_phase.py:411-412`
  explicitly fences expansion:** "open_pull_request /
  request_review / record_check stay open pending callsite cleanup
  (ui_user/unknown defaults)".
- **Pin recipe:**
  1. Audit every HTTP shim default — replace `agent="ui_user"` with
     `agent=""` (empty-actor fallthrough — matches Phase 4.5 + 4.6
     shim flip pattern).
  2. Audit retry paths in hub_registry — replace `agent=publisher`
     with a properly-bound caller identity threaded via the O14
     caller-kwarg pattern (commit `b39305ac` + `dc3d972d`).
  3. Audit tool wrappers in `tools/hub_tools.py` for the codehub
     tools — confirm each passes `agent=self._agent_id` (most
     already do; EventHub tools were threaded in `dc3d972d`).
- **Order of ops:** this cleanup is the prerequisite for Phase 4.6.1
  (record_check gate) + 4.6.2 (open_pull_request gate). Land it as
  Step A before any further codehub gate expansion.

### 5. `human` / `human_user` (Phase 4.7-slim Path A + Path C SHIPPED)

- **Status:** Phase 4.7-slim Path A SHIPPED (commit pending,
  follows 3a768740). Anchor O at `eventhub.py:428+`. The legacy
  `"human_user"` placeholder is rejected at phase>=4.7 — the
  project must configure its actual 甲方 identity via
  `ENVGEN_HUMAN_USER_ID` env var, `HubRegistry(human_user_id=...)`
  kwarg, or explicit per-call `from_user=...`. Tests:
  `tests/test_phase_4_7_human_console_identity.py` (14 cases).
- **What changed from "phantom" status:**
  - HumanConsole now captures a real `default_user_id` at init
    (no longer hardcodes `"human_user"`).
  - `EventHub.publish_human_message` at phase>=4.7 enforces
    non-phantom `from_user`.
  - User's directive 2026-05-31: "项目必须知道自己的甲方，也就是
    human user是谁，要不然发消息可能agent不知道对方的身份" —
    the gate makes "甲方 unset" surface loudly instead of
    silently emitting un-addressable messages.
- **Still phantom-shaped (Path C work):** the existing legacy
  callers in tests/CLI that pass `from_user="human_user"`
  literal continue to work at phase<4.7 (this gate is purely
  additive). Path C (long-term) replaces the env-var bridge
  with session-derived identity from live_monitor cookie/auth
  at request time — multi-user pipelines need per-request
  identity, not process-wide.
- **Order of ops:** Path A SHIPPED at 960dc566. Path C SHIPPED
  (commit-pending after this doc update) — the live_monitor
  session-auth track was already in place (Cutover 35
  `_apply_request_user`), so Path C is a 5-LOC extension that
  stamps `body["from_user"] = session_username` alongside the
  existing `body["agent"] = session_username`. The HTTP shims
  dropped their literal `"human_user"` defaults so the precedence
  chain (Path C > body > Path A env var > rejected) works
  cleanly. Phantom fully retired.

### 6. WorkHub producer-side principals (Phase 4.5a/b/c P1)

- **Status:** No specific principal name — the entire Phase 4.5a/b/c
  bundle was DEFERed per `docs/phase_4_5_workhub_design_notes.md` on
  architectural grounds (WorkHub's whole surface is producer-side per
  PR 3 of the hub-responsibility-split plan; there's nothing
  verdict-authoring to gate). Three unblock paths exist:
  - (a) Re-scope as Phase 4.5d targeting remaining gate_registry
    VERDICT-AUTHORING methods (recommended)
  - (b) Introduce a new "ownership-equals" gate idiom for
    producer-side WorkHub methods (was dropped from O1 as premature
    abstraction)
  - (c) Drop the rows outright
- **No principals to pin** unless path (b) is chosen, in which case
  every WorkHub method's owner field would become a real
  ownership-equals comparison target. The current `agent=` string
  bookkeeping field at WorkHub mutations is NOT a trust principal;
  promoting it to one requires the new gate idiom design.

## Cross-reference matrix

| Phantom | Phase blocked | Pin path | Effort | Priority |
|---|---|---|---|---|
| `contract_test_runtime` | 3.5 — Path B SHIPPED; phantom parked | Wait for real runtime caller, then pin | Med — needs new runtime component | DEFERRED (Phase 3.5 shipped WITHOUT widening) |
| `visual_similarity_runtime` | 3.9 — Path B SHIPPED; phantom parked | Pin alongside real SSIM runtime | Med — needs SSIM runtime | DEFERRED (Phase 3.9 shipped WITHOUT widening) |
| `runhub` partial | 2.5 already SHIPPED; future gates | Use require_runtime_actor not allowlist | Doc-only | Doc |
| `ui_user` / `unknown` | 4.6 expansion | Audit HTTP shims + hub_registry retry paths | Low — mechanical | P0 (4.6.1/4.6.2 blocked) |
| `human` / `human_user` | 4.7-slim Path A SHIPPED; Path C waits on session-auth | Env-var bridge today; live_monitor cookie→user_id long-term | Path A: shipped. Path C: High — UI track coordination | Path A done; Path C P2 |
| WorkHub producer principals | 4.5a/b/c P1 | Drop or re-design with ownership-equals idiom | Arch decision needed | P1 (architectural) |

## Recommended next-session order

1. **`ui_user`/`unknown` cleanup** (Step A of Phase 4.6 expansion). 1-2
   small commits. Unblocks Phase 4.6.1 + 4.6.2 follow-ups.
2. **`contract_test_runtime` pin**: Path B simplified SHIPPED at
   Phase 3.5 — phantom DEFERRED indefinitely. Pin ONLY if/when a
   real runtime contract-test caller is introduced.
3. **`visual_similarity_runtime` pin**: Path B simplified SHIPPED at
   Phase 3.9 — phantom DEFERRED indefinitely. Pin ONLY when a real
   SSIM-based programmatic reviewer component lands.
4. **Phase 4.5a/b/c retire/re-scope workflow**: pick (a) / (b) / (c)
   above. Architectural decision.
5. **`human` / `human_user`**: Path A SHIPPED (env-var bridge);
   Path C (session-derived identity) waits on the live_monitor
   session-auth track.

## Maintenance discipline

Whenever a workflow's phantom-identity lens flags a NEW phantom:

1. Add an entry to this doc with the standard fields (where it
   appears, what it blocks, pin recipe, order of ops).
2. Cross-reference back from any affected design notes file.
3. Use this doc as the canonical answer when an audit prejudges a
   row as "no-phantom-blockers" — verify against this registry
   before trusting the prejudgment.
