# Cutover 40: Reference Materials Upload

**Branch:** `haibotong-cutover-40-references`
**Date:** 2026-05-26

## What

Users upload arbitrary reference materials into a project via the UI.
Files land in `<workspace>/references/<filename>` and are auto-indexed
in `<workspace>/references/INDEX.md` so agents can discover them.

Six categories detected by file extension:
- `image` (png/jpg/jpeg/webp/gif/svg)
- `python` (.py — typically MCP server source)
- `spec` (yaml/yml/json — OpenAPI etc.)
- `doc` (md/txt/rst)
- `data` (csv/tsv/jsonl/ndjson)
- `other` (anything else)

10MB per-file cap. Path-traversal rejected (no `/`, `\`, `..`, leading
`.`, or absolute paths). Same-name uploads overwrite.

## Commits

- 13a03d22 Cutover 40: record pre-flight baseline
- 8f02636d Cutover 40: references upload/list/delete + auto INDEX.md generation
- bb323978 Cutover 40: ReferencesSection frontend (upload/list/preview/delete)
- (this) Cutover 40: migration log

## Test deltas
- Regressions: 7 OK → 7 OK
- Pytest collect: 1150 → 1163 (+13 new tests)
- `agent/tests/test_references.py` — 13 PASS
- `agent/tests/test_user_gates.py` + `test_user_gates_endpoints.py` + `test_live_monitor_endpoints.py` — 103 PASS (unchanged)

## New surfaces

### Backend
- `_references_dir(workspace)`, `_categorize_file(name)`, `_safe_reference_path`, `_file_preview`, `_regenerate_references_index`
- `list_references_call(workspaces_root, project_id)` → `{files: [...]}` with category/size/uploaded_at/preview
- `upload_reference_call(workspaces_root, project_id, body)` body `{filename, content_base64}`
- `delete_reference_call(workspaces_root, project_id, filename)`
- `GET /api/projects/<id>/references` — list
- `POST /api/projects/<id>/references` — upload (base64 in body)
- `DELETE /api/projects/<id>/references/<filename>` — remove (registered BEFORE the bare delete-project DELETE so the more specific route wins)
- `INDEX.md` auto-generated on every upload + delete

### Frontend
- `<ReferencesSection projectId />` in `WorkHubPanel`, mounted right after `<UserGatesSection />`
- Upload via hidden `<input type="file">` + `FileReader.readAsDataURL` → strip `data:...;base64,` prefix → POST as base64
- Per-file: category badge, size, expandable text preview, delete button (with confirm)

## Agent integration

Agents can read `<workspace>/references/INDEX.md` to discover all uploaded
files and their categories. The orchestrator's existing
`--reference-images` mechanism (Cutover 34) already scans the workspace
for screenshots; this cutover does NOT auto-wire references into that
flow, but the INDEX.md is the single discovery point for agents that
choose to consult them.

## Known limits

- Base64 upload doubles transferred bytes (intentional — stdlib HTTP
  server doesn't parse multipart). Fine for typical reference sizes
  (≤10MB).
- No directory uploads. To upload a multi-file MCP server, zip it or
  upload one file at a time.
- Categories are extension-based only. A `.txt` file containing JSON
  is categorized as `doc`. Future cutover could sniff content.
- INDEX.md format is fixed (markdown table). Future may extend with
  content fingerprints / hash for caching.
- No content scanning / validation per category (e.g., we don't check
  that a `.yaml` is valid YAML).
- The previous `--reference-images` CLI flag is unchanged; uploading
  via the new endpoint does NOT auto-add to that list. For Cutover
  34 generations, the orchestrator must opt-in to reading the
  references directory (planned for a future cutover).
- Binary files (detected by null bytes in first 2KB) have `preview: null`
  in the list response — the UI hides the "preview" disclosure for them.
