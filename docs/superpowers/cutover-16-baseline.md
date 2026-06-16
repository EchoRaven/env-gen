# Cutover 16 Baseline (Retro Stage)

## Test counts
- regressions: 7 OK
- discover: 611 OK

## Gap this cutover closes
Orchestrator can call deliver_project() the moment smoke passes — no
mandatory reflection on the generation. Cutover 15 added structured
postmortems for incidents; this cutover adds the broader "retro" doc
type tied to deliver_project as a hard gate.

## Approach
- retros are WorkHub pages with kind="retro" (parallel to design pages)
- submit_retro requires plan_vs_reality, lessons, proposed_prompt_changes
- runtime/retro_aggregator.py pure function computes bug/run/review stats
- DeliverProjectTool refuses if no retro for this session's generation_id
