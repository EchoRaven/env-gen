# Cutover 24 Baseline (Deliverable Verification Stage)

## Test counts
- regressions: 7 OK
- discover: 891 OK

## Gap this cutover closes
DeliverProjectTool checks an LLM-judged checklist (`no_bugs/requirements_met/...`)
that's pure self-assertion. Cutovers 16/19/20/21 added evidence-based gates,
but NOTHING enforces that RunHub actually ran. Orchestrator can deliver having
never spun up the app.

## Approach
- runtime/deliverability.py aggregates RunHub/APIHub/Coverage/Seed/Visual into
  a unified DeliverabilityReport
- DeliverProjectTool adds gate: refuses if no successful RunHub run since
  agent._session_start_ts
- 2 LLM tools: deliverability_check (full report) + deliverability_summary (verdict)
- Orchestrator prompt teaches the new workflow
- force_deliver=True bypasses (publishes deliverability_bypass EventHub event)
