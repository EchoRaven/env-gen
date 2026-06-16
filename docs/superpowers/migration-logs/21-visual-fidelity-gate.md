# Cutover 20: UI Visual Fidelity Gate

**Branch:** `haibotong-cutover-20-visual-fidelity`
**Date:** 2026-05-25

## What

Visual reviewer agent (13th profile) + structural gate that blocks
`deliver_project()` if any UI route marked `critical=true` lacks an approved
Visual Review. Approve requires similarity_score >= 0.75 (critical routes),
>=3 substantive deviations (aspect/expected/actual/severity), and >=20-char summary.

Same pattern as Cutover 14 architect-review (>=3 challenges) but for visual
instead of structural design.

## Commits

- `e662badd` Cutover 20: record pre-flight baseline (regressions 7 OK, discover 737 OK)
- `4236c5d9` WorkHub: add visual_review lifecycle (>=3 deviations + similarity_score for approve)
- `0b277be8` Add visual_review_gate: assert_critical_visuals_approved raises if any critical route not approved
- `e79b5788` Add visual_review_tools: register/submit/list_pending/get_status + bundle wiring
- `7d91a94e` Add visual_reviewer agent profile (13th) + wire visual_review_tools to frontend/orchestrator
- `f7c632b5` Add visual_reviewer_agent.j2 prompt (>=3 deviations + 0.75 critical floor + compare_with_screenshot)
- `4f4789b7` DeliverProjectTool: visual review gate (block if any critical route not approved)
- `a5890394` Orchestrator + frontend prompts: VISUAL FIDELITY DISCIPLINE + register_visual_review_task workflow

## Test deltas
- Regressions: 7 OK -> 7 OK
- Discover: 737 OK -> 788 OK (+51 new)

## New surfaces
- runtime/visual_review_gate.py — assert_critical_visuals_approved + list_unapproved_critical
- tools/visual_review_tools.py — 4 tools (register/submit/list/get_status)
- prompts/v2/visual_reviewer_agent.j2 — new agent prompt
- WorkHub: register_visual_review_task / submit_visual_review / list_pending_visual_reviews / list_critical_visual_reviews / is_visual_approved / get_visual_review
- 13th agent profile: visual_reviewer

## Reused surfaces
- WorkHub pages with kind="visual_review" (Cutover 14 pattern)
- CompareWithScreenshotTool from vision_tools.py (Cutover 18 inventory)
- mark_intentionally_dead allowlist (Cutover 19 escape hatch)
- force_deliver orchestrator-only audit bypass (Cutover 19 pattern)

## Known limits (future cutovers)
- Frontend / orchestrator must manually capture screenshots + register tasks
  (RunHub does not yet auto-screenshot post-run; future cutover)
- Vision comparison uses CompareWithScreenshotTool which is itself LLM-based;
  the similarity_score is what the visual_reviewer judges, not an automated metric
- No per-component diff yet — only full-route comparison
