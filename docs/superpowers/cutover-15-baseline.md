# Cutover 15 Baseline (Structured Knowledge Outputs)

## Test counts
- regressions: 7 OK
- discover: 584 OK

## Gap this cutover closes
Knowledge agent produces free-form notes; no structured ADR / runbook /
postmortem categories. Settled architecture decisions, operational procedures,
and incident retrospectives get lost in unstructured dumps.

## Existing surfaces we extend
- `KnowledgeCategory` enum in `multi_agent/knowledge/types.py` — has 30+
  free-form categories; adding 3 structured ones (ADR/RUNBOOK/POSTMORTEM)
- `Knowledge` dataclass — adding `structured_fields: Dict[str, Any]`
- `tools/knowledge_tools.py` — uses BaseTool (not HubTool); adding sibling
  `structured_knowledge_tools.py` with same convention

## Tool surface added (6 tools)
- submit_adr / submit_runbook / submit_postmortem (validated writes)
- list_adrs / list_runbooks / list_postmortems (filtered queries)

## Recon notes for Task 3 (knowledge_tools.py convention)
- Base class: `BaseTool` (imported from `utils.tool`, NOT `HubTool`).
  Example: `class QueryKnowledgeTool(BaseTool):` / `class StoreKnowledgeTool(BaseTool):`
- `__init__`: `super().__init__(name=self.NAME, category=ToolCategory.KNOWLEDGE)`
- Method: `async def execute(self, ...) -> ToolResult` (no `_run`).
- `ToolResult` shape (dataclass at `agent/utils/tool.py:43`):
  `success: bool`, `data: Any`, `error_message: Optional[str]`,
  `execution_time: float`, `metadata: dict`. Convenience constructors:
  `ToolResult.ok(data=...)` and `ToolResult.fail(error_message=...)`.
- Store access: module-level `_get_store()` (knowledge_tools.py:25) lazy-loads
  `KnowledgeStore(db_url=KnowledgeStore.default_sqlite_url())` into
  `_knowledge_store` global. Tests override by assigning `_kt._knowledge_store`.
- Factory: `create_knowledge_tools(workspace: Optional[Workspace] = None) -> List[BaseTool]`
  at knowledge_tools.py:614.

## Recon notes for Task 4 (tool_bundles.py registration)
- Existing knowledge bundles (3): `knowledge_read_tools`, `knowledge_write_tools`,
  `knowledge_skill_tools` (tool_bundles.py:456-458).
- Pattern (tool_bundles.py:190+):
  ```python
  def _bundle_knowledge_read(builder: ToolPoolBuilder, context: ToolAssemblyContext) -> None:
      tools = [tool for tool in create_knowledge_tools(workspace=context.workspace)
               if getattr(tool, "NAME", "") in {"query_knowledge", "get_relevant_knowledge"}]
      builder.add(tools, "knowledge_read")
  ```
  Note: `builder.add(tools, "knowledge_read")` — second arg is a **string**, not a tuple.
- Registry maps name -> bundle fn in `TOOL_BUNDLE_REGISTRY` (line 456).
- Requirements maps name -> `{category}` set in `TOOL_BUNDLE_REQUIREMENTS` (line 503).

## HEAD
- Branch: `haibotong-cutover-15-structured-knowledge`
- Parent commit: b8e51076 (Cutover 15 plan)
