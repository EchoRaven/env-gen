# Cutover 20 Baseline (UI Visual Fidelity Gate)

## Test counts
- regressions: 7 OK
- discover: 737 OK

## Gap this cutover closes
Cutover 14 (Architect Reviewer) catches design *assumptions*, not visual
*fidelity*. A generated UI that compiles + has no dead components can still
look nothing like the reference. No mechanical enforcement of "符合 reference
材料" today.

## Approach
- WorkHub kind="visual_review" pages (mirror Cutover 14 design_review)
- New visual_reviewer agent (13th profile) - never writes code
- submit_visual_review requires similarity_score in [0,1] + >=3 deviations + summary
- DeliverProjectTool refuses if any critical visual_review not approved
- force_deliver bypass (Cutover 19 pattern) for legitimate divergence

## Existing surfaces reused
- WorkHub pages with kind+status+metadata (Cutover 14)
- CompareWithScreenshotTool / AnalyzeImageTool (vision_tools.py)
- CaptureWebpageTool / Playwright (image_search_tools.py - for future
  auto-screenshot wiring, NOT this cutover)
- mark_intentionally_dead allowlist (Cutover 19)
