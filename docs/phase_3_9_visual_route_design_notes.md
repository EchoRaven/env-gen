# Phase 3.9 visual:\<route\> namespace — Design Notes (SHIPPED Path B)

**Status:** ✅ SHIPPED at `f2eb4569` via **Path B simplified**
(2026-06-01). The submitter-authorship concern in the original DEFER
was already covered by the previously-shipped Phase 4.3
(`submit_visual_review` locked to `{visual_reviewer}` at `e40ae472`)
— Path B ships the resolver namespace + `gate_registry.list_visual_reviews`
helper WITHOUT widening Phase 4.5 to admit `visual_similarity_runtime`.
The phantom stays parked until a real SSIM runtime caller exists.
Anchor Q at `story_hub.py` (inverted guard `if _phase < 3.9:`).

**Original DEFER rationale (preserved for context):** Phase 3.9
enables the `visual:<route>` resolver in story_hub, **co-shipping
with Phase 4.3** per the roadmap (line 96): 3.9 alone lights up the
namespace but leaves visual-submitter authorship ungated, allowing
any agent to spoof `submit_visual_review` verdicts. Phase 4.3 is
itself listed as P1 unshipped per the roadmap table.

## What ships in Phase 3.9

Per `docs/phase_4_plus_roadmap.md` lines 96-101:

1. **`visual:<route>` resolver in story_hub**:

   ```python
   def _resolve_visual(reg, target_key):
       route = target_key[len("visual:"):].strip()
       # Phase 3.9 design: index by metadata['route'] NOT page_key —
       # that was the C1 concern fix. Walks gate_registry pages with
       # kind=='visual_review'.
       try:
           pages = reg.gate_registry.list_pages(kind="visual_review")
       except Exception:
           pages = []
       for page in pages or []:
           md = page.get("metadata") or {}
           if md.get("route") != route:
               continue
           status = page.get("status")
           if status != "approved":
               return "fail" if status == "rejected" else "evidence_pending"
           # When SSIM was computed, check threshold; otherwise pass.
           ssim_score = md.get("ssim_score")
           threshold = md.get("ssim_threshold") or 0.0
           if ssim_score is None:
               # Phase 3.9 invariant: compute_ssim returns None on
               # import/file/zero-variance failure per its contract.
               # SSIM-None is evidence_pending, NOT failed.
               return "evidence_pending"
           if ssim_score < threshold:
               return "fail"
           return "pass"
       return "evidence_pending"
   ```

2. **`_DEFAULT_RESOLVERS` registration**: add `"visual:"` →
   `_resolve_visual` to `runtime/story_hub.py`.

3. **Tests** — `TestVisualResolver(PhaseResolverFixtureContracts,
   unittest.TestCase)` subclass that:
   - Seeds visual review evidence via canonical
     `gate_registry.register_visual_review_task` +
     `gate_registry.submit_visual_review`.
   - `declared_record_fields = {"status", "metadata"}` — locks the
     schema-misread defense at test time (the C1 design error was
     reading `page_key` instead of `metadata.route`).
   - Asserts SSIM-None case returns `evidence_pending` (NOT `fail`).
   - Asserts approved + score ≥ threshold → pass.

4. **Status-helper count bump**: 17→19 mechanisms when both 3.9 + 4.3
   ship together.

## Why this hasn't shipped autonomously

Two design blockers:

### Blocker A — Phase 4.3 must co-ship

The roadmap (line 96 — "they do together") says Phase 3.9 alone
recreates the BLOCKER B1 failure class one layer up. Phase 4.3's
`submit_visual_review` authorship lock allowed_set:
- `{orchestrator, visual_reviewer, verifier, visual_similarity_runtime}`

`visual_similarity_runtime` is a **phantom identity** today — needs to
be a real runtime principal before the gate widens to admit it. Same
class as the `contract_test_runtime` issue in Phase 3.5.

### Blocker B — page_key vs metadata.route invariant

The C1 design error was the original resolver design reading `page_key`
(which is opaque) instead of `metadata.route` (which is the
human-meaningful identity). The fix is clear (use `metadata.route`),
but the runtime invariant — every shipped `register_visual_review_task`
call must set `metadata.route` — needs an audit pass to confirm no
production callsite writes the page without setting `route`.

## Unblocking conditions

1. **Visual_similarity_runtime principal** — define what identity
   string the programmatic visual_review writes its rows under
   (mirrors `runhub` for `record_probe`).
2. **Audit register_visual_review_task callsites** — confirm every
   site sets `metadata['route']`.
3. **TestVisualResolver subclass** ready to use O2 seeds (via
   `seed_visual_review` helper that already exists at
   `tests/fixtures/phase_resolver_contracts.py`, currently NOT in the
   v1 ship per the design notes Blocker 3 fix).

## Workflow stats

(No workflow run yet for Phase 3.9; this doc establishes the briefing
so the next workflow can pre-bake the visual_similarity_runtime
principal + page_key→metadata.route invariant as Candidate A.)

## What's NOT in scope here

- Phase 4.3 visual-submitter authorship gate — needs separate
  workflow once `visual_similarity_runtime` principal is pinned.
- Phase 3.5 endpoint_contract namespace (separate doc).
- The O2 `seed_visual_review` helper — already shipped at commit
  `0e25cd5c` but currently NOT exported in v1 (deferred per design
  notes Blocker 3 fix). Re-export when Phase 3.9 lands.
