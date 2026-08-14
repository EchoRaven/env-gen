# Netflix generality bring-up — session 2026-07-30/31 (fixes #384–#387)

Branch: `feat/netflix-generality-366-367` · Model: `claude-opus-4-7` (anthropic-native via the
Vertex cert-mTLS proxy, prompt caching on) · Runtime: podman + podman-compose + fwdproxy relay.

## TL;DR

Four deterministic framework fixes took the **Netflix** generation from "wedges before delivery"
to **api_smoke ALL-GREEN + business_chain 79-step green + visual 13/13 pages judged + every prior
delivery gate cleared**. All four are committed, unit-tested (isolation harness), and **validated
live** across runs #10–#13. No full delivery yet: the runs now die on a *new, multi-front* tail
(backend seed-data propagation, frontend route-authoring quality, business_chain non-determinism)
rather than any fixed issue. Recommendation: **merge #384–#387**, then treat the remaining tail as a
separate, scoped piece of work (details + options below).

## The four fixes (all committed on the branch, tests gitignored under `agent/tests/`)

| # | commit | file | problem → fix | validated |
|---|--------|------|---------------|-----------|
| **#384** | `087cbf5` | `runtime/frontend_scaffold.py` (`backfill_page_apis`) + `runtime/scaffolder.py` | A ui_page with **empty `apis_used`** (kickoff's `profiles`, `search`) projected a bare flagged stub → `deliverability_frontend_fallback_page` hard-blocked. Backfill a GET endpoint by token overlap so the page projects a real measured floor. Additive; never invents. | r10–r13: `frontend_fallback_pages: 0/13` |
| **#385** | `74e46e7` | `runtime/visual_fidelity.py` (`_select_judged_screens`) | `max_screens=8` cap silently dropped owned page screens, but the verdict **fails any owned screen left unjudged** → any app with >8 pages (Netflix has 13) was mathematically unpassable. Judge every blocking page; cap only trims advisory overflow. | r12/r13: `VISUAL COVERAGE judged 13/20`, never-judged empty (was stuck 8/20) |
| **#386** | `53a757f` | `runtime/chain_executor.py` (`_is_control_plane_public` + waiver) | A verifier-authored **denial-probe** (expect 401/403) against a control-plane PUBLIC infra endpoint (`GET /api/v1/tenants`, `auth_required:False`, fetched pre-auth by the login TenantPicker) is mis-authored: 200 is correct, and the verifier can't "fix" it without breaking login → NO-CONVERGENCE abort. Waive denial-probes on the 6 fixed control-plane paths; real business endpoints still fail on a genuine leak. | r12/r13: tenants-probe failures = 0 |
| **#387** | `32bc61a` | `runtime/frontend_scaffold.py` (`scaffold_pages_from_contract` route derivation) | A ui_page registered with **empty `route`** (`profiles_page`) had its App.jsx route derived from the name *including* the `_page` suffix → `/profiles-page`, while the ui_flow gate + design expect the canonical `/profiles` → `/profiles` blank → `deliverability_ui_flow_failed` hard-block (lane wires `/profiles-page`, reports "M1 complete", never reconciles). Drop a trailing `page` token → `/profiles`. Declared routes untouched. | r13: `ui_flow_failed=0`, no `/profiles blank` |

Tests (gitignored, isolation harness — stub sibling imports + `exec` the source):
`test_frontend_backfill_apis.py` (7), `test_visual_fidelity_coverage.py` (4),
`test_chain_control_plane_probe.py` (5), `test_frontend_page_route_canon.py` (4). All green.

## Run-by-run progression (each run reached a later stage)

- **r9** (before this arc's frontend fixes): business_chain converged, died on `deliverability_frontend_fallback_page` (profiles/search bare stubs). → #384.
- **r10**: with #384, reached the **visual gate** (never hit before) — died on the `max_screens=8` cap (7 owned screens "never judged"). → #385.
- **r11**: with #384+#385, wedged early on business_chain — the `/api/v1/tenants` denial-probe (NO-CONVERGENCE). → #386.
- **r12**: with #384+#385+#386 — **api_smoke ALL-GREEN (16/16, 79-step business_chain), visual 13/20 judged, DELIVER_PROJECT called** — died at the *last* gate: `deliverability_ui_flow_failed` (`/profiles` blank via `/profiles-page` mis-route). → #387.
- **r13**: with all four — deepest yet; **every fixed gate stayed clear**. Died on a NEW multi-front tail (below).

## Remaining tail (NOT yet fixed — the strategy decision)

r13 STUCK-aborted: `framework validation wedged on [business_chain] for 7 post-cap cycles`. Root
causes, in priority order:

1. **Backend: `seed_data.json missing on integration`** (PRIMARY killer). Empty DB →
   `POST /api/titles/1/rating → 404 "referenced resource not found"` (9×) + `POST /api/my-list → 404`
   → business_chain can't converge → abort. In r12 the seed data WAS present and business_chain went
   79-step green; in r13 the backend lane's seed task stayed "blocked on same single item" and never
   wrote `seed_data.json` to integration. **Likely a real, fixable framework seed-propagation gap OR
   backend-lane non-determinism — worth diagnosing first (candidate #388).**

2. **Frontend route-authoring quality** (secondary blocker, `deliverability_frontend_fallback_page`
   via the #223 code-truth sweep): the lane wired `/browse → CardHoverPreviewPage` (wrong), left
   `BrowseHomePage` a **stub at `/browse-home`**, and created a `/title-detail` vs `/title/:id`
   duplicate. Same *class* as #387 but fuzzier — screen names (`browse_home`, `title_detail`) don't
   map cleanly to canonical routes (`/browse`, `/title/:id`) the way `profiles_page → /profiles` did.
   Needs scaffold↔lane route canonicalization/**dedup** (don't create a parallel stub route when the
   lane covers a screen) or design-route-aware mapping — not a clean 1-liner. May be better addressed
   by tuning the frontend-lane prompt than by more framework heuristics.

3. **business_chain non-determinism**: green in r12, wedged in r13 — largely a symptom of (1) (seed
   data present vs absent), but worth confirming once (1) is fixed.

## Recommendation

- **Merge #384–#387** — they are clean, tested, and each validated live; they are independent of the
  remaining tail and strictly advance generality.
- Treat the tail as a **separate scoped effort**, starting with **(1) seed_data propagation** (the
  actual r13 killer; most likely a genuine framework bug). Only after that, decide whether (2) is a
  framework route-dedup fix or a frontend-lane prompt change.

## Ops / infra notes (reusable, this host)

- Launch: `./run_netflix_opus.sh` (gitignored). Vertex anthropic proxy on `:8790`, fwdproxy container
  relay on `:19080` — **both left running** and reusable for the next attempt.
- podman: docker.io→VMVM mirror + local `uv` stand-in + `firewall_driver="none"` + host-network
  builds (all in `tools/podman_setup.sh`). Engine venv: `/opt/miniconda3` py3.10, binary-only deps.
- A fresh run self-cleans (`--fresh` → `reset_output_dir`); tear down leftover podman stacks with
  `podman-compose down -v` in `agent/generated/<name>/docker` before relaunch.
- GitHub egress is blocked for the agent — **user pushes/merges** this branch.

Session fix tally on this branch: **#366–#387 (23 framework fixes)**.
