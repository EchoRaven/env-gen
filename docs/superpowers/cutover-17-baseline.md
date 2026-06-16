# Cutover 17 Baseline (Observability Dashboard)

## Test counts
- regressions: 7 OK
- discover: 636 OK

## Gap this cutover closes
.agent_logs/ accumulates ~hundreds of events per agent per generation but
nobody reads them. No "which agent retried most" / "top tools used" / "events
per hour" is answerable today.

## After Cutover 17
- runtime/observability/log_parser.py: pure aggregator -> LogStats
- runtime/observability/dashboard.py: LogStats -> self-contained HTML
- CLI: python -m multi_agent.runtime.observability
- LLM tool: observability_dashboard (callable by orchestrator)
- Final cutover in the 17-cutover roadmap.
