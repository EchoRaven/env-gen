# PIPELINE FIX PROPOSAL #41 — scaffold a baseline src/services/api.js when ABSENT (frontend build blocker)

Run #38 (full #1/#2/G1/G2/#40 stack) ABORTED without delivery — `💥 STUCK: framework
validation wedged on docker_up for 7 post-cap cycles`. Root (from the build log + the bug
tasks): the frontend **vite build fails** —
`Could not resolve "../services/api" from "src/pages/LoginPage.jsx"`. The lane wrote pages
that `import ... from '../services/api'` but **never created `src/services/api.js`** → rollup
can't resolve it → docker build fails → docker_up FAILS → no delivery. (This is NOT G1: the
regenerated App.jsx imports resolve to existing page files; the unresolved import is the
pages → api.js edge.)

## Why the existing repair doesn't catch it
`frontend_scaffold.repair_frontend_api_exports` (FIX #37, runs every validation tick via
framework_validation.py:119-120) heals export-DRIFT (api.js exists but a page imports a name
it doesn't export → aliases the missing export). But it **BAILS when api.js is ABSENT**
(frontend_scaffold.py:87-91: `if not api_js.exists(): … return {"repaired": False, "reason":
"no api.js"}`). So a totally-missing api.js — pages importing a file that was never written —
is unhandled → permanent build failure → "framework regenerates the same artifact, agents
can't self-heal" abort.

The framework already scaffolds the frontend INFRA baseline (Dockerfile/nginx/start.sh/
package.json/vite — frontend_scaffold.py:449+) precisely so a silent frontend lane can't
block delivery. But `src/services/api.js` is treated as lane-owned (FIX #37 header) and has
NO baseline — so when the lane references it but doesn't write it, the build dies.

## Proposed fix (frontend analogue of the backend skeleton; consistency-by-construction)
In `repair_frontend_api_exports`, when api.js is ABSENT **and** some src file imports
`../services/api` (the scan at :97 already finds these imports), **CREATE a minimal baseline
api.js** instead of bailing, then run the EXISTING export-reconciliation so every imported
name resolves. The baseline is domain-agnostic — it encodes only the FIXED platform contract
(already known framework-wide):
  - a `request(path, {method, body, auth})` fetch wrapper that attaches
    `Authorization: Bearer <localStorage token>` and parses JSON;
  - the fixed-envelope helpers (`apiGet`/`apiPost`/`apiPut`/`apiDelete` returning
    `data.item` / `data.items` per the projector envelope);
  - then the existing reconciliation (lines 112-134) aliases every name the pages import
    (e.g. `registerAccount`, `getNotes`) to a thin wrapper, so the build RESOLVES.
This guarantees the frontend always BUILDS (the import resolves); G2 + remediation still drive
the lane to fill real page content. Only CREATE when absent — never clobber a lane-written
api.js (the existing drift-heal path keeps handling that).

## Open questions for the reviewer
1. Confirm the abort root is the missing api.js (build log: "Could not resolve
   ../services/api"), and that `repair_frontend_api_exports` bails on absent api.js
   (frontend_scaffold.py:87-91) so nothing creates it.
2. Is `repair_frontend_api_exports` the right place (it runs every tick on the integration
   tree + already scans imports), or should the baseline live in `scaffold_frontend_baseline`
   / `_BASELINE_FILES`? (The latter writes unconditionally; the former is import-aware and
   only acts when pages reference api.js — preferable to avoid shipping an unused api.js.)
3. The baseline api.js content: is a generic fetch+Bearer+envelope wrapper + aliased exports
   enough to BUILD (the immediate goal), accepting the functions may be approximate until the
   lane fills them? Or must it project per-endpoint functions from RegistryHub (more correct
   but couples the scaffold to the contract — does repair_frontend_api_exports have the
   endpoints)? Recommend: minimal-to-build now (unblock delivery), per-endpoint projection as
   a follow-up.
4. Related (NOT this fix): run #38 also showed the frontend required-files gate blocking
   finish on missing app/frontend/{Dockerfile,package.json,…} in the LANE WORKTREE
   (worktree-absence) + the verifier registered ZERO chains (so #40's auto-prepend never
   fired; business_chain blocked on "no chains"). Flag whether these are separate proposals.

## Rank
api.js-baseline (this) unblocks the frontend BUILD = the run #38 abort cause. The
worktree-absence (frontend infra files) + verifier-no-chains are the next two, both upstream
of a clean delivery.
