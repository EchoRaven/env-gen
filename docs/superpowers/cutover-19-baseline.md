# Cutover 19 Baseline (Dead-Code Gate)

## Test counts
- regressions: 7 OK
- discover: 698 OK

## Gap this cutover closes
Schema gates (Cutover 7) verify declared APIs/tables are implemented.
NO REVERSE CHECK: implemented endpoints/components/files can be dead
(zero consumers) and still ship. Dead artifacts pass all current gates.

## Approach
- runtime/coverage_audit.py: pure scanner over APIHub provider+consumer
  graphs and app-root source-file import graph
- WorkHub page kind="coverage_allowlist" for orchestrator-blessed
  intentionally-dead files (audited)
- DeliverProjectTool: refuses if coverage_dead - allowlist non-empty
- force_deliver kwarg = orchestrator-only audit bypass (matches Cutover 7
  force_merge pattern)

## Inventory

### Generated app root convention
The Orchestrator's `output_dir` is the workspace root; the generated
app lives under `<output_dir>/app/` with `frontend/` and `backend/`
subdirectories. Examples observed in `demos/`:
- `demos/foodhub-web/app/{frontend,backend}/`
- `demos/github-web/app/{frontend,backend}/`
- `demos/jira-web/app/{frontend,backend}/`
- `demos/moviehub-web/moviehub/app/{frontend,backend}/` (nested sub-name variant)
- `demos/airbnb/homestay/app/{frontend,backend}/` (nested sub-name variant)

Task 2 file scanner should accept an `app_root` parameter and walk it
recursively (skipping `node_modules`, `.venv`, `dist`, `build`,
`__pycache__`). The deliver gate (Task 5) computes `app_root` as
`agent.workspace_path / "app"` if present, falling back to
`agent.workspace_path`.

### Entry-point file names observed in real generated apps
- Frontend: `App.jsx`, `App.tsx`, `main.tsx`, `main.jsx`, `index.tsx`,
  `index.ts` (under `frontend/src/`)
- Backend: `server.js`, `server.ts`, `server.py`, `app.py`, `main.py`,
  `__init__.py`, `__main__.py`, `manage.py`, `wsgi.py`, `asgi.py`
- Config (also treated as entry-point so they aren't flagged dead):
  `vite.config.{ts,js}`, `next.config.js`, `tailwind.config.js`,
  `package.json`, `tsconfig.json`, `docker-compose.yml`, `Dockerfile`

### APIHub helpers confirmed (agent/env_generator/llm_generator/multi_agent/runtime/apihub.py)
- `register_consumer(endpoint_id, file_path, agent, metadata=None)` -> dict   (line 138)
- `get_consumers(endpoint_id)` -> List[dict]                                   (line 190)
- `register_table(name, schema=None, provider="", ...)`                        (line 439)
- `list_tables(provider=None)` -> Dict[str, dict]                              (line 464)
- `register_table_consumer(table_name, file_path, agent, ...)`                 (line 500)
- `get_endpoints()` -> Dict[str, dict]                                         (line 559)

Signatures match Cutover 18 expectations; no plan adjustments needed.

### DeliverProjectTool retro gate (Cutover 16 anchor)
File: `agent/env_generator/llm_generator/tools/agent_interaction_tools.py`

- `execute(self, confirmation, delivery_summary, checklist=None)` declared at line 641
- Cutover 16 retro gate body spans lines 642-656 (the `try:` block ending
  in the bare `pass` on line 656)
- Task 5 will insert the coverage pre-flight block immediately after line
  656 (before the "Verify confirmation" block at line 658)
- The `execute` signature needs an added `force_deliver: bool = False`
  kwarg per Task 5 Step 3
