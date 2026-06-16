# Cutover 14: Design Review Stage

**Branch:** `haibotong-cutover-14-design-review`
**Date:** 2026-05-24

## What

Added a mandatory architect-review hop between Design and downstream implementation.

- Design docs ride on WorkHub pages with `kind="design"`. New lifecycle: `draft -> under_review -> approved | needs_revision`.
- New `architect_reviewer` agent profile (12th profile). Subscribes only to design pages; never writes code.
- `submit_design_review(state="approve")` requires >=3 substantive `challenges` (each with non-empty `claim`/`concern`/`recommendation`). Mirrors Cutover-13's substantive-review pattern.
- New `runtime/design_gate.py` exposes `assert_design_approved(workhub, page_id)` raising `DesignNotApprovedError` if status != "approved".
- Downstream agents (backend/database/frontend) get the `design_tools` bundle; prompts teach them to call `design_get_status` before starting work and refuse if not approved.

## Commits

- `f8d7bcc0` Cutover 14: record pre-flight baseline (regressions 7 OK, discover 534 OK)
- `753005f2` WorkHub: add design-review lifecycle (>=3 substantive challenges for approve)
- `efd54501` Add design_gate: assert_design_approved raises DesignNotApprovedError if status != approved
- `2f900f39` Add design_tools LLM surface (submit_for_review / submit_review / list_pending / get_status)
- `c64faf4c` Add architect_reviewer agent profile + wire design_tools into design/backend/database/frontend
- `ad47eb71` Add architect_reviewer_agent.j2 prompt (>=3 substantive challenges, never writes code)
- `f0d61bfb` Design + backend/database/frontend prompts: teach kind=design lifecycle + design_get_status gate
- `a42f0341` Add end-to-end design-review test: rubber-stamp blocked, substantive unblocks downstream

## Test deltas
- Regressions: 7 OK -> 7 OK
- Discover: 534 OK -> 584 OK (+50 new)

## New surfaces
- `design_gate.py` — DesignNotApprovedError + assert_design_approved + is_design_approved
- `design_tools.py` — 4 tools (submit_for_review, submit_review, list_pending_review, get_status)
- `architect_reviewer_agent.j2` — new agent prompt
- WorkHub: 5 new methods (submit_design_for_review, submit_design_review, is_design_approved, list_pending_design_reviews, get_design_page)
- agents_config.yaml: 12 profiles (was 11)

## Updated prompts
- design_agent.j2: must use kind="design", call submit_for_review, await approval
- backend_agent.j2 / database_agent.j2 / frontend_agent.j2: must call design_get_status; refuse if not approved

## Known gaps (future cutovers)
- Architect reviewer's challenges aren't semantically validated — only shape (3 entries, all 3 fields non-empty). A reviewer could submit garbage triples. Future work: knowledge-base check that challenges actually engage with the design content.
- No "designate the design page" mechanism on tasks today — orchestrator must include `design_page_id` in task metadata for downstream agents to know which page to check.
