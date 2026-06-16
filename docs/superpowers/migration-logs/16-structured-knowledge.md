# Cutover 15: Structured Knowledge Outputs (ADR / Runbook / Postmortem)

**Branch:** `haibotong-cutover-15-structured-knowledge`
**Date:** 2026-05-24

## What

Forced the Knowledge agent (and any other writer) to produce structured
engineering documents - Architecture Decision Records (ADR), Runbooks,
and Postmortems - instead of dumping free-form notes. Each structured
document type has required fields validated at write time.

- 3 new `KnowledgeCategory` values: `ADR`, `RUNBOOK`, `POSTMORTEM`.
- `Knowledge` dataclass gains `structured_fields: Dict[str, Any]` (default
  `{}`), serialised through `to_dict` / `from_dict`. Free-form writes via
  `store_knowledge` are unaffected.
- 6 new LLM tools in `tools/structured_knowledge_tools.py`:
  - `submit_adr(title, decision, context, alternatives, consequences, status)`
  - `submit_runbook(title, trigger, steps, verification, rollback)`
  - `submit_postmortem(title, incident_date, impact, timeline, root_cause, action_items)`
  - `list_adrs(status=None, limit=20)` / `list_runbooks(limit=20)` /
    `list_postmortems(limit=20)`
- Validation lives in the submit tools (alternatives >= 1, runbook steps
  >= 3, postmortem timeline >= 3, action_items >= 1, ISO date for
  `incident_date`, ADR status enum) so ad-hoc `store_knowledge` writes are
  not regressed.
- New `structured_knowledge_tools` bundle registered in
  `multi_agent/tool_bundles.py` and wired to the `knowledge` profile in
  `agents/agents_config.yaml`.
- `knowledge_agent.j2` prompt teaches when to reach for `submit_adr` vs
  `submit_runbook` vs `submit_postmortem` and when free-form
  `store_knowledge` is still appropriate.

## Sentinel-encoded persistence workaround

The existing `KnowledgeStore` sqlite schema has no `structured_fields`
column. Rather than ship a destructive schema migration mid-cutover, the
submit tools serialise the structured payload as JSON inside the
existing `content` column under a sentinel prefix
(`__structured_fields__:{...}`). The list helpers detect the sentinel
and decode it back into a real `dict` for callers, preferring the
in-memory `structured_fields` attribute when populated (fresh objects)
and falling back to the sentinel JSON for entries that round-trip
through the store. Net effect: callers see a structured `dict`; the
store keeps its current schema. A future cutover can promote
`structured_fields` to a first-class column and migrate the sentinel
rows.

## Commits

- `4b12018e` Cutover 15: record pre-flight baseline (regressions 7 OK, discover 584 OK)
- `dfeb1426` Knowledge: add ADR/RUNBOOK/POSTMORTEM categories + structured_fields dict
- `439b1b71` Add structured_knowledge_tools: submit_adr/runbook/postmortem + list_adrs/runbooks/postmortems
- `bcfae2c0` Register structured_knowledge_tools bundle + wire to knowledge profile
- `f754e3d3` Knowledge agent prompt: teach submit_adr / submit_runbook / submit_postmortem
- `b2cac154` Add end-to-end test: structured doc submit -> list lifecycle (validation + persistence)

## Test deltas

- Regressions: 7 OK -> 7 OK
- Discover: 584 OK -> 611 OK (+27 new)

## New surfaces

- `multi_agent/knowledge/types.py` - `KnowledgeCategory.{ADR,RUNBOOK,POSTMORTEM}`
  enum values; `Knowledge.structured_fields: Dict[str, Any]` field with
  `to_dict` / `from_dict` round-trip support.
- `tools/structured_knowledge_tools.py` - 6 tools
  (`SubmitADRTool`, `SubmitRunbookTool`, `SubmitPostmortemTool`,
  `ListADRsTool`, `ListRunbooksTool`, `ListPostmortemsTool`) plus
  sentinel encode/decode helpers and a `create_structured_knowledge_tools`
  factory.
- `multi_agent/tool_bundles.py` - `structured_knowledge_tools` bundle
  entry in `TOOL_BUNDLE_REGISTRY` + `TOOL_BUNDLE_REQUIREMENTS`.

## Updated prompts

- `multi_agent/prompts/v2/knowledge_agent.j2` - new "STRUCTURED
  ENGINEERING DOCUMENTS" block teaching the submit_* / list_* surface and
  when to prefer each type over free-form `store_knowledge`.

## Updated config

- `multi_agent/agents/agents_config.yaml` - `knowledge` profile picks up
  the `structured_knowledge_tools` bundle alongside its existing
  knowledge bundles.

## Known gaps (future cutovers)

- Sentinel-prefixed JSON inside `content` is a transitional encoding.
  A future cutover should promote `structured_fields` to a first-class
  column with a backfill that strips the sentinel and rehydrates the
  dict.
- Postmortem `action_items` are free-form strings; they are not yet
  linked to WorkHub tasks. Auto-creating WorkHub tasks for each action
  item is the natural next step.
- ADR `status` transitions (proposed -> accepted -> deprecated /
  superseded) are not enforced - any status can be submitted at any
  time, and there is no "supersedes" link between ADRs.
- The list tools filter Python-side after pulling the category bucket;
  this is fine at current volume but should move to a real DB filter if
  the knowledge corpus grows large.
