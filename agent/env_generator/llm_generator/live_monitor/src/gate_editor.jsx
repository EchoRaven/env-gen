// Shared delivery-gate editor — the single source of truth used by BOTH the
// new-project page and the in-project Delivery Gates page, so they stay unified.
// Exposes window.EnvGenGates. Uses window.HubUI.UiSelect (available at render).
const { useState } = React;

const GATE_TYPES = [
  { value: "file_exists", label: "File exists" },
  { value: "endpoint_exists", label: "API endpoint exists" },
  { value: "mcp_tool_exists", label: "MCP tool exists" },
  { value: "visual_similarity", label: "Visual similarity" },
  { value: "code_check", label: "Code check (run command)" },
];
const HTTP_METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE"].map((m) => ({ value: m, label: m }));

// Mirror of multi_agent/runtime/user_gates.validate_gate so the UI rejects bad
// gates before they reach the server. Returns an error string, or null if valid.
function validateGate(name, type, params) {
  if (!(name || "").trim()) return "Gate name is required.";
  if (type === "file_exists" && !(params.path || "").trim()) return "Path is required.";
  if (type === "endpoint_exists") {
    if (!(params.method || "").trim()) return "HTTP method is required.";
    if (!(params.path || "").trim()) return "Path is required.";
  }
  if (type === "mcp_tool_exists" && !(params.name || "").trim()) return "Tool name is required.";
  if (type === "visual_similarity") {
    if (!(params.page_id || "").trim()) return "page_id is required.";
    const ms = parseFloat(params.min_similarity);
    if (isNaN(ms)) return "min_similarity is required.";
    if (ms < 0 || ms > 1) return "min_similarity must be between 0 and 1.";
  }
  if (type === "code_check" && !(params.command || "").trim()) return "Command is required.";
  return null;
}

function gateAutoName(type, p) {
  if (type === "file_exists") return `file: ${p.path || "?"}`;
  if (type === "endpoint_exists") return `${p.method || "GET"} ${p.path || "?"}`;
  if (type === "mcp_tool_exists") return `mcp: ${p.name || "?"}`;
  if (type === "visual_similarity") return `visual: ${p.page_id || "?"} ≥ ${p.min_similarity ?? "?"}`;
  if (type === "code_check") {
    const cmd = (p.command || "?").trim();
    const short = cmd.length > 40 ? cmd.slice(0, 40) + "…" : cmd;
    return `code: ${short}`;
  }
  return "gate";
}

function normalizeGateParams(type, params) {
  const p = { ...(params || {}) };
  if (type === "visual_similarity" && p.min_similarity !== undefined && p.min_similarity !== "") {
    p.min_similarity = parseFloat(p.min_similarity);
  }
  if (type === "code_check") {
    if (p.expect_exit !== undefined && p.expect_exit !== "") p.expect_exit = parseInt(p.expect_exit, 10);
    else delete p.expect_exit;
    if (p.timeout !== undefined && p.timeout !== "") p.timeout = parseInt(p.timeout, 10);
    else delete p.timeout;
    if (!(p.expect_contains || "").trim()) delete p.expect_contains;
  }
  return p;
}

// One gate per line; type auto-detected. Blank lines / # comments ignored.
function parseGateLines(text) {
  const rows = [];
  for (const raw of String(text || "").split("\n")) {
    const line = raw.trim();
    if (!line || line.startsWith("#")) continue;
    let m;
    if ((m = line.match(/^(GET|POST|PUT|PATCH|DELETE)\s+(\S+)/i))) {
      rows.push({ type: "endpoint_exists", params: { method: m[1].toUpperCase(), path: m[2] } });
    } else if ((m = line.match(/^file:\s*(.+)$/i))) {
      rows.push({ type: "file_exists", params: { path: m[1].trim() } });
    } else if ((m = line.match(/^mcp:\s*(.+)$/i))) {
      rows.push({ type: "mcp_tool_exists", params: { name: m[1].trim() } });
    } else if ((m = line.match(/^visual:\s*(\S+)\s*(?:>=|≥|>)?\s*([0-9]*\.?[0-9]+)?/i))) {
      rows.push({ type: "visual_similarity", params: { page_id: m[1], min_similarity: m[2] ? parseFloat(m[2]) : 0.9 } });
    } else if ((m = line.match(/^(?:code|run):\s*(.+)$/i))) {
      rows.push({ type: "code_check", params: { command: m[1].trim() } });
    } else if (line.startsWith("/")) {
      rows.push({ type: "endpoint_exists", params: { method: "GET", path: line } });
    } else if (line.includes("/") || line.includes(".")) {
      rows.push({ type: "file_exists", params: { path: line } });
    }
  }
  return rows;
}

// Valid, normalized, auto-named gates from editor rows (incomplete rows skipped).
function collectGates(rows) {
  const out = [];
  for (const row of rows || []) {
    const params = normalizeGateParams(row.type, row.params);
    const auto = gateAutoName(row.type, params);
    if (validateGate(auto, row.type, params)) continue;
    out.push({ name: auto, type: row.type, params });
  }
  return out;
}

// Per-type parameter fields. set(patch) merges into the row's params.
function GateRowParams({ type, params, set }) {
  const UiSelect = window.HubUI?.UiSelect;
  if (type === "file_exists") {
    return <input className="input-px w-full font-mono" placeholder="path (e.g. app/backend/src/server.js)"
                  value={params.path || ""} onChange={(e) => set({ path: e.target.value })} />;
  }
  if (type === "endpoint_exists") {
    return (
      <div className="flex gap-2">
        {UiSelect
          ? <UiSelect value={params.method || "GET"} onChange={(v) => set({ method: v })} options={HTTP_METHODS} minWidth={104} inputStyle />
          : <input className="input-px w-24" value={params.method || "GET"} onChange={(e) => set({ method: e.target.value })} />}
        <input className="input-px flex-1 font-mono" placeholder="/api/path"
               value={params.path || ""} onChange={(e) => set({ path: e.target.value })} />
      </div>
    );
  }
  if (type === "mcp_tool_exists") {
    return <input className="input-px w-full font-mono" placeholder="mcp tool_name"
                  value={params.name || ""} onChange={(e) => set({ name: e.target.value })} />;
  }
  if (type === "visual_similarity") {
    return (
      <div className="flex gap-2">
        <input className="input-px flex-1" placeholder="page_id (e.g. home)"
               value={params.page_id || ""} onChange={(e) => set({ page_id: e.target.value })} />
        <input className="input-px w-24" inputMode="decimal" placeholder="≥ 0.90"
               value={params.min_similarity ?? ""} onChange={(e) => set({ min_similarity: e.target.value })} />
      </div>
    );
  }
  if (type === "code_check") {
    return (
      <div className="space-y-2">
        <input className="input-px w-full font-mono" placeholder="command (runs in workspace, e.g. npm --prefix app/backend test)"
               value={params.command || ""} onChange={(e) => set({ command: e.target.value })} />
        <div className="flex gap-2">
          <input className="input-px flex-1 font-mono" placeholder="expect output contains… (optional)"
                 value={params.expect_contains || ""} onChange={(e) => set({ expect_contains: e.target.value })} />
          <input className="input-px w-20" inputMode="numeric" placeholder="exit 0"
                 value={params.expect_exit ?? ""} onChange={(e) => set({ expect_exit: e.target.value })} />
          <input className="input-px w-24" inputMode="numeric" placeholder="120s"
                 value={params.timeout ?? ""} onChange={(e) => set({ timeout: e.target.value })} />
        </div>
      </div>
    );
  }
  return null;
}

// The full repeatable-rows editor: pick a type, fill it, + for more, or paste a
// list. `rows` / `setRows` are owned by the caller (so it can collectGates()).
function GateRowsEditor({ rows, setRows, note }) {
  const Icons = window.Icons || {};
  const UiSelect = window.HubUI?.UiSelect;
  const [bulkOpen, setBulkOpen] = useState(false);
  const [bulkText, setBulkText] = useState("");
  const [localNote, setLocalNote] = useState("");

  const addRow = (type = "file_exists") => setRows((rs) => [...(rs || []), { type, params: {} }]);
  const removeRow = (idx) => setRows((rs) => rs.filter((_, i) => i !== idx));
  const setRowType = (idx, type) => setRows((rs) => rs.map((r, i) => (i === idx ? { type, params: {} } : r)));
  const setRowParams = (idx, patch) => setRows((rs) => rs.map((r, i) => (i === idx ? { ...r, params: { ...r.params, ...patch } } : r)));
  function parseBulk() {
    const parsed = parseGateLines(bulkText);
    if (!parsed.length) { setLocalNote("No gates recognized — check the format examples below."); return; }
    setRows((rs) => [...(rs || []), ...parsed]);
    setBulkText(""); setLocalNote("");
  }

  return (
    <div>
      {(note || localNote) && <div className="mb-2 text-xs text-fg-muted">{note || localNote}</div>}
      {(rows || []).length > 0 && (
        <div className="space-y-2 mb-3">
          {rows.map((row, i) => (
            <div key={i} className="flex items-start gap-2">
              {UiSelect
                ? <UiSelect value={row.type} onChange={(v) => setRowType(i, v)} options={GATE_TYPES} minWidth={172} inputStyle />
                : <select value={row.type} onChange={(e) => setRowType(i, e.target.value)} className="input-px" style={{ width: 172 }}>{GATE_TYPES.map(t => <option key={t.value} value={t.value}>{t.label}</option>)}</select>}
              <div className="flex-1 min-w-0">
                <GateRowParams type={row.type} params={row.params} set={(patch) => setRowParams(i, patch)} />
              </div>
              <button onClick={() => removeRow(i)} title="Remove"
                      className="text-fg-muted hover:text-danger text-xl leading-none px-1 mt-1 shrink-0">×</button>
            </div>
          ))}
        </div>
      )}
      <div className="flex items-center gap-2">
        <button onClick={() => addRow()} className="btn-px btn-px-ghost btn-px-sm">
          {Icons.plus ? <Icons.plus size={12} /> : "+"} Add gate
        </button>
        <button onClick={() => { setBulkOpen((o) => !o); setLocalNote(""); }} className="btn-px btn-px-ghost btn-px-sm">
          {bulkOpen ? "Close paste" : "Paste list…"}
        </button>
      </div>
      {bulkOpen && (
        <div className="mt-3 p-3 rounded-md border border-border bg-bg-secondary space-y-2">
          <textarea value={bulkText} onChange={(e) => setBulkText(e.target.value)} rows={6}
                    className="input-px textarea-px w-full font-mono"
                    placeholder={"One gate per line — type is auto-detected:\n\nGET /api/users\nPOST /api/posts\nfile: app/backend/src/server.js\nmcp: search_posts\nvisual: home >= 0.9\ncode: npm --prefix app/backend test"} />
          <div className="flex items-center justify-between gap-3">
            <span className="text-2xs text-fg-muted leading-snug">
              Formats: <code className="font-mono">METHOD /path</code> · <code className="font-mono">file: path</code> · <code className="font-mono">mcp: name</code> · <code className="font-mono">visual: page ≥ score</code> · <code className="font-mono">code: command</code>
            </span>
            <button onClick={parseBulk} className="btn-px btn-px-primary btn-px-sm shrink-0">Parse</button>
          </div>
        </div>
      )}
    </div>
  );
}

window.EnvGenGates = {
  GATE_TYPES, HTTP_METHODS,
  validateGate, gateAutoName, normalizeGateParams, parseGateLines, collectGates,
  GateRowParams, GateRowsEditor,
};
