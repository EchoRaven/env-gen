const { useState, useEffect } = window.React;

// ---- Shared helpers ----
function fmtTime(ts) {
  if (!ts) return "—";
  try {
    const ms = ts > 1e12 ? ts : ts * 1000;
    return new Date(ms).toLocaleString();
  } catch (e) {
    return String(ts);
  }
}

function fmtDuration(start, end) {
  if (!start) return "—";
  if (!end) return "running";
  const ms = (end - start) * 1000;
  if (ms < 1000) return `${Math.round(ms)}ms`;
  if (ms < 60 * 1000) return `${(ms / 1000).toFixed(1)}s`;
  return `${(ms / 60000).toFixed(1)}m`;
}

function shortId(s, n) {
  n = n || 12;
  return s && s.length > n ? s.slice(0, n) + "…" : s;
}

async function postJson(url, body) {
  try {
    const r = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "include",
      body: JSON.stringify(body || {}),
    });
    return await r.json();
  } catch (e) {
    return { error: String(e) };
  }
}

async function deleteJson(url, body) {
  try {
    const r = await fetch(url, {
      method: "DELETE",
      headers: { "Content-Type": "application/json" },
      credentials: "include",
      body: JSON.stringify(body || {}),
    });
    return await r.json();
  } catch (e) {
    return { error: String(e) };
  }
}

function HubCard({ title, count, subtitle, children, accent }) {
  return (
    <div className="hub-card" style={{ borderLeftColor: accent }}>
      <div className="hub-card-header">
        <h3>{title}</h3>
        {count !== undefined && <span className="hub-card-count">{count}</span>}
      </div>
      {subtitle && <p className="hub-card-subtitle">{subtitle}</p>}
      <div className="hub-card-body">{children}</div>
    </div>
  );
}

function PriorityChip({ priority }) {
  const p = priority || "P2";
  return <span className={`priority-chip prio-${p}`}>{p}</span>;
}

function StatusPill({ value, kind }) {
  const v = value || "unknown";
  return <span className={`hub-pill pill-${kind || "default"} status-${v}`}>{v}</span>;
}

// ---- Generic inline form scaffold ----
function HubForm({ title, children, error, onSubmit, onCancel, submitLabel, destructive }) {
  return (
    <div className={`hub-form ${destructive ? "hub-form-destructive" : ""}`}>
      <h4>{title}</h4>
      <div className="hub-form-body">{children}</div>
      {error && <div className="hub-form-error">{error}</div>}
      <div className="hub-form-actions">
        <button type="button" className="hub-op-btn" onClick={onSubmit}>{submitLabel || "Submit"}</button>
        <button type="button" className="hub-op-btn ghost" onClick={onCancel}>Cancel</button>
      </div>
    </div>
  );
}

// ---- CodeHubPanel ----
// snapshot shape: { repos, branches, commits, pull_requests, review_threads, code_reviews, checks, releases }
function CodeHubPanel({ snapshot, projectId, onChange }) {
  const s = snapshot || {};
  const prs = Object.values(s.pull_requests || {});
  const branches = Object.values(s.branches || {});
  const commits = Object.values(s.commits || {});
  const checks = Object.values(s.checks || {});
  const [showOpen, setShowOpen] = useState(false);
  const [reviewFor, setReviewFor] = useState(null);
  const [checkFor, setCheckFor] = useState(null);

  const openPrs = prs.filter((pr) => (pr.merge_state || pr.status) !== "merged");
  const mergedPrs = prs.filter((pr) => (pr.merge_state || pr.status) === "merged");

  const sortedCommits = [...commits].sort(
    (a, b) => (b.created_at || b._updated_at || 0) - (a.created_at || a._updated_at || 0)
  );

  async function mergePr(prId) {
    if (!projectId) return;
    const data = await postJson(`/api/projects/${projectId}/codehub/pull_requests/${prId}/merge`, { strategy: "squash", agent: "ui_user" });
    if (data && data.error) alert(`Merge failed: ${data.error}`);
    onChange && onChange();
  }

  async function forceMerge(prId) {
    if (!projectId) return;
    const reason = window.prompt("Force-merge reason (>= 20 chars). This BYPASSES the verifier gate:");
    if (!reason || reason.length < 20) { alert("Force-merge cancelled (reason too short)."); return; }
    if (!window.confirm(`Force-merge ${prId}?\nThis BYPASSES the pre-merge verifier gate.\nReason: "${reason}"`)) return;
    const data = await postJson(`/api/projects/${projectId}/codehub/pull_requests/${prId}/force_merge`, { reason });
    if (data && data.error) alert(`Force-merge failed: ${data.error}`);
    onChange && onChange();
  }

  return (
    <HubCard
      title="CodeHub"
      count={prs.length}
      subtitle={`${openPrs.length} open · ${mergedPrs.length} merged · ${branches.length} branches · ${commits.length} commits · ${checks.length} checks`}
      accent="#6cb6ff"
    >
      <div className="hub-actions">
        <button type="button" className="hub-op-btn" onClick={() => setShowOpen(true)} disabled={!projectId}>+ Open PR</button>
      </div>

      <h4 className="hub-subtitle">Open pull requests ({openPrs.length})</h4>
      {openPrs.length === 0 ? (
        <div className="hub-empty">No open PRs.</div>
      ) : (
        <table className="hub-table">
          <thead>
            <tr>
              <th>PR</th>
              <th>Title</th>
              <th>State</th>
              <th>Author</th>
              <th>Reviewers</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {openPrs.map((pr) => (
              <tr key={pr.id} className="pr-row">
                <td><code>{pr.id}</code></td>
                <td>{pr.title || <em>(no title)</em>} <small>{pr.source_branch} → {pr.target_branch}</small></td>
                <td><StatusPill value={pr.merge_state || pr.status} kind="pr" /></td>
                <td>{pr.author || "—"}</td>
                <td><small>{(pr.reviewers || []).join(", ") || "—"}</small></td>
                <td className="hub-row-actions">
                  <button type="button" className="hub-op-btn small" onClick={() => mergePr(pr.id)}>Merge</button>
                  <button type="button" className="hub-op-btn small" onClick={() => setReviewFor(pr.id)}>Review</button>
                  <button type="button" className="hub-op-btn small" onClick={() => setCheckFor(pr.id)}>Check</button>
                  <button type="button" className="hub-op-btn small destructive" onClick={() => forceMerge(pr.id)}>Force-merge</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {mergedPrs.length > 0 && (
        <>
          <h4 className="hub-subtitle">Recently merged ({mergedPrs.length})</h4>
          <ul className="hub-list">
            {mergedPrs.slice(-5).reverse().map((pr) => (
              <li key={pr.id}>
                <code>{pr.id}</code> {pr.title || pr.source_branch} <small>by {pr.author}</small>
              </li>
            ))}
          </ul>
        </>
      )}

      <h4 className="hub-subtitle">Branches ({branches.length})</h4>
      {branches.length === 0 ? (
        <div className="hub-empty">No branches.</div>
      ) : (
        <ul className="hub-list">
          {branches.slice(0, 10).map((b, i) => (
            <li key={b.id || b.name || i}>
              <code>{b.name || b.id}</code>
              {b.head && <small> @ {String(b.head).slice(0, 8)}</small>}
              {b.author && <small> · {b.author}</small>}
            </li>
          ))}
        </ul>
      )}

      <h4 className="hub-subtitle">Recent commits ({Math.min(sortedCommits.length, 5)} of {sortedCommits.length})</h4>
      {sortedCommits.length === 0 ? (
        <div className="hub-empty">No commits.</div>
      ) : (
        <ul className="hub-list">
          {sortedCommits.slice(0, 5).map((c, i) => (
            <li key={c.id || c.commit_hash || i}>
              <code>{String(c.commit_hash || c.id || "").slice(0, 8)}</code>{" "}
              {c.diff_summary || c.message || <em>(no message)</em>}
              {c.author && <small> · {c.author}</small>}
            </li>
          ))}
        </ul>
      )}

      {showOpen && (
        <OpenPRForm
          projectId={projectId}
          onDone={() => { setShowOpen(false); onChange && onChange(); }}
          onCancel={() => setShowOpen(false)}
        />
      )}
      {reviewFor && (
        <SubmitReviewForm
          projectId={projectId}
          prId={reviewFor}
          onDone={() => { setReviewFor(null); onChange && onChange(); }}
          onCancel={() => setReviewFor(null)}
        />
      )}
      {checkFor && (
        <RecordCheckForm
          projectId={projectId}
          prId={checkFor}
          onDone={() => { setCheckFor(null); onChange && onChange(); }}
          onCancel={() => setCheckFor(null)}
        />
      )}
    </HubCard>
  );
}

function OpenPRForm({ projectId, onDone, onCancel }) {
  const [branch, setBranch] = useState("");
  const [number, setNumber] = useState("");
  const [base, setBase] = useState("main");
  const [title, setTitle] = useState("");
  const [author, setAuthor] = useState("backend");
  const [reviewers, setReviewers] = useState("");
  const [linkedTasks, setLinkedTasks] = useState("");
  const [err, setErr] = useState("");

  async function submit() {
    setErr("");
    if (!branch.trim()) { setErr("branch is required"); return; }
    const body = {
      branch: branch.trim(),
      head: branch.trim(),
      target: base.trim() || "main",
      base: base.trim() || "main",
      title: title.trim(),
      author: author.trim() || "ui_user",
      reviewers: reviewers.split(",").map((x) => x.trim()).filter(Boolean),
      linked_tasks: linkedTasks.split(",").map((x) => x.trim()).filter(Boolean),
    };
    if (number.trim()) body.number = Number(number.trim());
    const data = await postJson(`/api/projects/${projectId}/codehub/pull_requests`, body);
    if (data && data.error) { setErr(`${data.error}${data.hint ? `: ${data.hint}` : ""}`); return; }
    onDone();
  }

  return (
    <HubForm
      title="Open Pull Request"
      error={err}
      onSubmit={submit}
      onCancel={onCancel}
      submitLabel="Open PR"
    >
      <input placeholder="branch / head (e.g. feat/login)" value={branch} onChange={(e) => setBranch(e.target.value)} />
      <input placeholder="base branch (default: main)" value={base} onChange={(e) => setBase(e.target.value)} />
      <input placeholder="PR number (optional)" value={number} onChange={(e) => setNumber(e.target.value)} />
      <input placeholder="title" value={title} onChange={(e) => setTitle(e.target.value)} />
      <input placeholder="author (default: backend)" value={author} onChange={(e) => setAuthor(e.target.value)} />
      <input placeholder="reviewers (comma-separated, need >=2)" value={reviewers} onChange={(e) => setReviewers(e.target.value)} />
      <input placeholder="linked_tasks (comma-separated task_ids)" value={linkedTasks} onChange={(e) => setLinkedTasks(e.target.value)} />
    </HubForm>
  );
}

function SubmitReviewForm({ projectId, prId, onDone, onCancel }) {
  const [reviewer, setReviewer] = useState("ui_user");
  const [state, setState] = useState("approved");
  const [reason, setReason] = useState("");
  const [commentsText, setCommentsText] = useState("");
  const [consideredAlts, setConsideredAlts] = useState("");
  const [inlineRows, setInlineRows] = useState([{ file: "", line: "", body: "" }]);
  const [err, setErr] = useState("");

  function updateInline(idx, key, val) {
    setInlineRows((rows) => rows.map((r, i) => (i === idx ? { ...r, [key]: val } : r)));
  }
  function addInline() {
    setInlineRows((rows) => [...rows, { file: "", line: "", body: "" }]);
  }
  function removeInline(idx) {
    setInlineRows((rows) => rows.filter((_, i) => i !== idx));
  }

  async function submit() {
    setErr("");
    const comments = commentsText
      .split("\n")
      .map((s) => s.trim())
      .filter(Boolean);
    const inline_comments = inlineRows
      .filter((r) => (r.file || "").trim() && (r.body || "").trim())
      .map((r) => ({
        file: r.file.trim(),
        line: r.line ? Number(r.line) : 0,
        body: r.body.trim(),
      }));
    const considered_alternatives = consideredAlts
      .split("\n")
      .map((s) => s.trim())
      .filter(Boolean);
    const data = await postJson(`/api/projects/${projectId}/codehub/pull_requests/${prId}/reviews`, {
      reviewer: reviewer.trim() || "ui_user",
      state,
      reason: reason.trim(),
      comments,
      inline_comments,
      considered_alternatives,
    });
    if (data && data.error) { setErr(data.error); return; }
    onDone();
  }
  return (
    <HubForm title={`Submit Review for ${prId}`} error={err} onSubmit={submit} onCancel={onCancel} submitLabel="Submit Review">
      <input placeholder="reviewer" value={reviewer} onChange={(e) => setReviewer(e.target.value)} />
      <select value={state} onChange={(e) => setState(e.target.value)}>
        <option value="approved">approved</option>
        <option value="changes_requested">changes_requested</option>
        <option value="commented">commented</option>
      </select>
      <textarea placeholder="reason (>=20 chars for approve/request_changes)" value={reason} onChange={(e) => setReason(e.target.value)} />
      <textarea placeholder="Comments (one per line)" value={commentsText} onChange={(e) => setCommentsText(e.target.value)} />
      <textarea placeholder="Considered alternatives (one per line, optional)" value={consideredAlts} onChange={(e) => setConsideredAlts(e.target.value)} />
      <div className="inline-comments-block">
        <label className="inline-comments-label">Inline comments</label>
        {inlineRows.map((r, i) => (
          <div key={i} className="inline-comment-row">
            <input placeholder="file (e.g. src/x.py)" value={r.file} onChange={(e) => updateInline(i, "file", e.target.value)} />
            <input placeholder="line" value={r.line} onChange={(e) => updateInline(i, "line", e.target.value)} style={{ maxWidth: 70 }} />
            <input placeholder="body" value={r.body} onChange={(e) => updateInline(i, "body", e.target.value)} />
            <button type="button" className="hub-op-btn small ghost" onClick={() => removeInline(i)} disabled={inlineRows.length === 1}>×</button>
          </div>
        ))}
        <button type="button" className="hub-op-btn small" onClick={addInline}>+ Add inline comment</button>
      </div>
    </HubForm>
  );
}

function RecordCheckForm({ projectId, prId, onDone, onCancel }) {
  const [name, setName] = useState("lint");
  const [status, setStatus] = useState("passed");
  const [evidence, setEvidence] = useState("");
  const [err, setErr] = useState("");
  async function submit() {
    setErr("");
    let evidenceObj = {};
    if (evidence.trim()) {
      try { evidenceObj = JSON.parse(evidence); } catch (e) { setErr("evidence must be valid JSON or empty"); return; }
    }
    const data = await postJson(`/api/projects/${projectId}/codehub/pull_requests/${prId}/checks`, {
      name: name.trim(),
      status,
      evidence: evidenceObj,
    });
    if (data && data.error) { setErr(data.error); return; }
    onDone();
  }
  return (
    <HubForm title={`Record Check for ${prId}`} error={err} onSubmit={submit} onCancel={onCancel} submitLabel="Record">
      <input placeholder="check name (e.g. lint, tests)" value={name} onChange={(e) => setName(e.target.value)} />
      <select value={status} onChange={(e) => setStatus(e.target.value)}>
        <option value="passed">passed</option>
        <option value="failed">failed</option>
        <option value="pending">pending</option>
      </select>
      <textarea placeholder='evidence JSON (optional, e.g. {"log_path":"..."})' value={evidence} onChange={(e) => setEvidence(e.target.value)} />
    </HubForm>
  );
}

// ---- RegistryHubPanel ----
function RegistryHubPanel({ snapshot, projectId, onChange }) {
  const s = snapshot || {};
  const endpoints = Object.values(s.endpoints || {});
  const tables = Object.values(s.tables || {});
  const consumers = Object.values(s.consumers || {});
  const providers = Object.values(s.providers || {});
  const mcpServers = providers.filter((p) => p && p.kind === "server");
  const [showForm, setShowForm] = useState(null);
  const [editEndpoint, setEditEndpoint] = useState(null);
  const [deprecateEndpoint, setDeprecateEndpoint] = useState(null);
  const [editTable, setEditTable] = useState(null);

  const consumersByEndpoint = {};
  for (const c of consumers) {
    const k = c.endpoint_id || "—";
    (consumersByEndpoint[k] = consumersByEndpoint[k] || []).push(c);
  }

  return (
    <HubCard
      title="RegistryHub"
      count={endpoints.length}
      subtitle={`${tables.length} tables · ${consumers.length} consumers · ${mcpServers.length} MCP servers`}
      accent="#f0c674"
    >
      <div className="hub-actions">
        <button type="button" className="hub-op-btn" onClick={() => setShowForm("endpoint")} disabled={!projectId}>+ Endpoint</button>
        <button type="button" className="hub-op-btn" onClick={() => setShowForm("table")} disabled={!projectId}>+ Table</button>
        <button type="button" className="hub-op-btn" onClick={() => setShowForm("consumer")} disabled={!projectId}>+ Consumer</button>
        <button type="button" className="hub-op-btn" onClick={() => setShowForm("mcp")} disabled={!projectId}>+ MCP Server</button>
      </div>

      <h4 className="hub-subtitle">Endpoints ({endpoints.length})</h4>
      {endpoints.length === 0 ? (
        <div className="hub-empty">No endpoints registered.</div>
      ) : (
        <table className="hub-table">
          <thead>
            <tr>
              <th>Method</th><th>Path</th><th>Provider</th><th>Status</th><th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {endpoints.map((e) => (
              <tr key={e.id}>
                <td><code>{e.method}</code></td>
                <td><code>{e.path}</code></td>
                <td>{e.provider || "—"}</td>
                <td><StatusPill value={e.status} kind="api" /></td>
                <td className="hub-row-actions">
                  <button type="button" className="hub-op-btn small" onClick={() => setEditEndpoint(e)}>Edit schema</button>
                  <button type="button" className="hub-op-btn small destructive" disabled={e.status === "deprecated"} onClick={() => setDeprecateEndpoint(e)}>Deprecate</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <h4 className="hub-subtitle">Tables ({tables.length})</h4>
      {tables.length === 0 ? (
        <div className="hub-empty">No tables.</div>
      ) : (
        <table className="hub-table">
          <thead>
            <tr><th>Name</th><th>Columns</th><th>Provider</th><th>Actions</th></tr>
          </thead>
          <tbody>
            {tables.map((t) => {
              const schema = t.schema || {};
              const cols = Array.isArray(schema.columns) ? schema.columns.length : Object.keys(schema).length;
              return (
                <tr key={t.id || t.name}>
                  <td><code>{t.name}</code></td>
                  <td>{cols}</td>
                  <td>{t.provider || "—"}</td>
                  <td className="hub-row-actions">
                    <button type="button" className="hub-op-btn small" onClick={() => setEditTable(t)}>Edit schema</button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}

      <h4 className="hub-subtitle">Consumers ({consumers.length})</h4>
      {consumers.length === 0 ? (
        <div className="hub-empty">No consumers registered.</div>
      ) : (
        <table className="hub-table">
          <thead><tr><th>Consumer</th><th>Depends on</th></tr></thead>
          <tbody>
            {Object.entries(consumersByEndpoint).map(([endpointId, cs]) => (
              <tr key={endpointId}>
                <td><small>{cs.map((c) => c.file_path || c.id).join(", ")}</small></td>
                <td><code>{endpointId}</code> <small>({cs.length})</small></td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {mcpServers.length > 0 && (
        <>
          <h4 className="hub-subtitle">MCP Servers ({mcpServers.length})</h4>
          <ul className="hub-list">
            {mcpServers.map((m, i) => (
              <li key={m.id || m.name || i}>
                <code>{m.name}</code>
                {m.transport && <small> ({m.transport})</small>}
                {m.endpoint && <small> · {m.endpoint}</small>}
                {m.status && <small> · {m.status}</small>}
              </li>
            ))}
          </ul>
        </>
      )}

      {showForm && (
        <RegistryHubForm
          kind={showForm}
          projectId={projectId}
          onDone={() => { setShowForm(null); onChange && onChange(); }}
          onCancel={() => setShowForm(null)}
        />
      )}
      {editEndpoint && (
        <EndpointSchemaForm
          projectId={projectId}
          endpoint={editEndpoint}
          onDone={() => { setEditEndpoint(null); onChange && onChange(); }}
          onCancel={() => setEditEndpoint(null)}
        />
      )}
      {deprecateEndpoint && (
        <DeprecateEndpointForm
          projectId={projectId}
          endpoint={deprecateEndpoint}
          endpoints={endpoints}
          onDone={() => { setDeprecateEndpoint(null); onChange && onChange(); }}
          onCancel={() => setDeprecateEndpoint(null)}
        />
      )}
      {editTable && (
        <TableSchemaForm
          projectId={projectId}
          table={editTable}
          onDone={() => { setEditTable(null); onChange && onChange(); }}
          onCancel={() => setEditTable(null)}
        />
      )}
    </HubCard>
  );
}

function EndpointSchemaForm({ projectId, endpoint, onDone, onCancel }) {
  const existing = endpoint.schema || {};
  const [requestJson, setRequestJson] = useState(
    JSON.stringify(existing.request || {}, null, 2)
  );
  const [responseJson, setResponseJson] = useState(
    JSON.stringify(existing.response || {}, null, 2)
  );
  const [agent, setAgent] = useState("ui_user");
  const [err, setErr] = useState("");

  async function submit() {
    setErr("");
    let request, response;
    try {
      request = requestJson.trim() ? JSON.parse(requestJson) : {};
    } catch (e) { setErr(`request JSON invalid: ${e.message}`); return; }
    try {
      response = responseJson.trim() ? JSON.parse(responseJson) : {};
    } catch (e) { setErr(`response JSON invalid: ${e.message}`); return; }
    const eid = encodeURIComponent(endpoint.id);
    const data = await postJson(
      `/api/projects/${projectId}/registryhub/endpoints/${eid}/schema`,
      { request, response, agent: agent.trim() || "ui_user" }
    );
    if (data && data.error) { setErr(data.error); return; }
    onDone();
  }

  return (
    <HubForm
      title={`Edit schema: ${endpoint.method} ${endpoint.path}`}
      error={err}
      onSubmit={submit}
      onCancel={onCancel}
      submitLabel="Save schema"
    >
      <div className="endpoint-edit-form">
        <label>request JSON</label>
        <textarea value={requestJson} onChange={(e) => setRequestJson(e.target.value)} />
        <label>response JSON</label>
        <textarea value={responseJson} onChange={(e) => setResponseJson(e.target.value)} />
        <input placeholder="agent (default: ui_user)" value={agent} onChange={(e) => setAgent(e.target.value)} />
      </div>
    </HubForm>
  );
}

function DeprecateEndpointForm({ projectId, endpoint, endpoints, onDone, onCancel }) {
  const [replacementId, setReplacementId] = useState("");
  const [sunset, setSunset] = useState("");
  const [agent, setAgent] = useState("ui_user");
  const [err, setErr] = useState("");

  async function submit() {
    setErr("");
    if (!window.confirm(`Deprecate ${endpoint.method} ${endpoint.path}?`)) return;
    const eid = encodeURIComponent(endpoint.id);
    const body = { agent: agent.trim() || "ui_user" };
    if (replacementId.trim()) body.replacement_id = replacementId.trim();
    if (sunset.trim()) body.sunset_date = sunset.trim();
    const data = await postJson(
      `/api/projects/${projectId}/registryhub/endpoints/${eid}/deprecate`,
      body
    );
    if (data && data.error) { setErr(data.error); return; }
    onDone();
  }

  return (
    <HubForm
      title={`Deprecate ${endpoint.id}`}
      error={err}
      onSubmit={submit}
      onCancel={onCancel}
      submitLabel="Deprecate"
      destructive
    >
      <select value={replacementId} onChange={(e) => setReplacementId(e.target.value)}>
        <option value="">— no replacement —</option>
        {endpoints.filter((e) => e.id !== endpoint.id).map((e) => (
          <option key={e.id} value={e.id}>{e.id}</option>
        ))}
      </select>
      <input placeholder="sunset_date (optional, e.g. 2026-12-31)" value={sunset} onChange={(e) => setSunset(e.target.value)} />
      <input placeholder="agent (default: ui_user)" value={agent} onChange={(e) => setAgent(e.target.value)} />
    </HubForm>
  );
}

function TableSchemaForm({ projectId, table, onDone, onCancel }) {
  const [schemaJson, setSchemaJson] = useState(
    JSON.stringify(table.schema || {}, null, 2)
  );
  const [agent, setAgent] = useState("ui_user");
  const [err, setErr] = useState("");

  async function submit() {
    setErr("");
    let schema;
    try {
      schema = schemaJson.trim() ? JSON.parse(schemaJson) : {};
    } catch (e) { setErr(`schema JSON invalid: ${e.message}`); return; }
    if (!schema || Object.keys(schema).length === 0) { setErr("schema required (cannot be empty)"); return; }
    const name = encodeURIComponent(table.name);
    const data = await postJson(
      `/api/projects/${projectId}/registryhub/tables/${name}/schema`,
      { schema, agent: agent.trim() || "ui_user" }
    );
    if (data && data.error) { setErr(data.error); return; }
    onDone();
  }

  return (
    <HubForm
      title={`Edit schema: ${table.name}`}
      error={err}
      onSubmit={submit}
      onCancel={onCancel}
      submitLabel="Save schema"
    >
      <textarea
        placeholder='schema JSON (e.g. {"columns": [...]})'
        value={schemaJson}
        onChange={(e) => setSchemaJson(e.target.value)}
        style={{ minHeight: 120 }}
      />
      <input placeholder="agent (default: ui_user)" value={agent} onChange={(e) => setAgent(e.target.value)} />
    </HubForm>
  );
}

function RegistryHubForm({ kind, projectId, onDone, onCancel }) {
  const [fields, setFields] = useState({});
  const [err, setErr] = useState("");

  function set(k, v) { setFields((cur) => ({ ...cur, [k]: v })); }

  async function submit() {
    setErr("");
    let url, body;
    try {
      if (kind === "endpoint") {
        if (!fields.method || !fields.path) { setErr("method and path required"); return; }
        url = `/api/projects/${projectId}/registryhub/endpoints`;
        body = {
          method: fields.method,
          path: fields.path,
          provider: fields.provider || "",
          status: fields.status || "defined",
          schema: fields.schema ? JSON.parse(fields.schema) : {},
        };
      } else if (kind === "table") {
        if (!fields.name) { setErr("name required"); return; }
        url = `/api/projects/${projectId}/registryhub/tables`;
        body = {
          name: fields.name,
          provider: fields.provider || "",
          status: fields.status || "defined",
          schema: fields.schema ? JSON.parse(fields.schema) : {},
        };
      } else if (kind === "consumer") {
        if (!fields.endpoint_id || !fields.file_path) { setErr("endpoint_id and file_path required"); return; }
        url = `/api/projects/${projectId}/registryhub/consumers`;
        body = {
          endpoint_id: fields.endpoint_id,
          file_path: fields.file_path,
          agent: fields.agent || "ui_user",
        };
      } else if (kind === "mcp") {
        if (!fields.name || !fields.transport) { setErr("name and transport required"); return; }
        url = `/api/projects/${projectId}/registryhub/mcp_servers`;
        body = {
          name: fields.name,
          transport: fields.transport,
          endpoint: fields.endpoint || "",
          provider: fields.provider || "",
        };
      }
    } catch (e) {
      setErr(`schema must be valid JSON: ${e.message}`); return;
    }
    const data = await postJson(url, body);
    if (data && data.error) { setErr(data.error); return; }
    onDone();
  }

  let body;
  if (kind === "endpoint") {
    body = (
      <>
        <input placeholder="method (GET/POST/...)" value={fields.method || ""} onChange={(e) => set("method", e.target.value)} />
        <input placeholder="path (e.g. /users)" value={fields.path || ""} onChange={(e) => set("path", e.target.value)} />
        <input placeholder="provider (e.g. backend)" value={fields.provider || ""} onChange={(e) => set("provider", e.target.value)} />
        <input placeholder="status (default: defined)" value={fields.status || ""} onChange={(e) => set("status", e.target.value)} />
        <textarea placeholder='schema JSON (optional, e.g. {"request":{}, "response":{}})' value={fields.schema || ""} onChange={(e) => set("schema", e.target.value)} />
      </>
    );
  } else if (kind === "table") {
    body = (
      <>
        <input placeholder="name (e.g. users)" value={fields.name || ""} onChange={(e) => set("name", e.target.value)} />
        <input placeholder="provider" value={fields.provider || ""} onChange={(e) => set("provider", e.target.value)} />
        <input placeholder="status (default: defined)" value={fields.status || ""} onChange={(e) => set("status", e.target.value)} />
        <textarea placeholder='schema JSON (optional, e.g. {"columns":[{"name":"id","type":"int"}]})' value={fields.schema || ""} onChange={(e) => set("schema", e.target.value)} />
      </>
    );
  } else if (kind === "consumer") {
    body = (
      <>
        <input placeholder="endpoint_id (e.g. GET /users)" value={fields.endpoint_id || ""} onChange={(e) => set("endpoint_id", e.target.value)} />
        <input placeholder="file_path (consumer file)" value={fields.file_path || ""} onChange={(e) => set("file_path", e.target.value)} />
        <input placeholder="agent (default: ui_user)" value={fields.agent || ""} onChange={(e) => set("agent", e.target.value)} />
      </>
    );
  } else if (kind === "mcp") {
    body = (
      <>
        <input placeholder="name" value={fields.name || ""} onChange={(e) => set("name", e.target.value)} />
        <input placeholder="transport (e.g. stdio, http)" value={fields.transport || ""} onChange={(e) => set("transport", e.target.value)} />
        <input placeholder="endpoint URL or command" value={fields.endpoint || ""} onChange={(e) => set("endpoint", e.target.value)} />
        <input placeholder="provider" value={fields.provider || ""} onChange={(e) => set("provider", e.target.value)} />
      </>
    );
  }

  return (
    <HubForm title={`+ Register ${kind}`} error={err} onSubmit={submit} onCancel={onCancel} submitLabel="Register">
      {body}
    </HubForm>
  );
}

// ---- BlockEditor (Cutover 37) ----
function BlockEditor({ projectId, page, blocks, onRefresh }) {
  const [editing, setEditing] = useState({});   // {block_id: draftText}
  const [appendDraft, setAppendDraft] = useState("");
  const [appendType, setAppendType] = useState("text");

  const pageBlocks = (Object.values(blocks || {}))
    .filter((b) => b.page_id === page.id)
    .sort((a, b) => (a.ord || 0) - (b.ord || 0));

  async function doPost(url, body) {
    const r = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "include",
      body: JSON.stringify(body),
    });
    return r.json();
  }

  async function saveBlock(blockId) {
    const draft = editing[blockId];
    if (draft === undefined) return;
    await doPost(
      `/api/projects/${encodeURIComponent(projectId)}/workhub/blocks/${encodeURIComponent(blockId)}`,
      { content: draft, agent: "ui_user" }
    );
    setEditing((prev) => { const c = { ...prev }; delete c[blockId]; return c; });
    if (window.LiveMonitorRefresh) window.LiveMonitorRefresh();
    if (onRefresh) onRefresh();
  }

  async function appendBlock() {
    if (!appendDraft.trim()) return;
    await doPost(
      `/api/projects/${encodeURIComponent(projectId)}/workhub/pages/${encodeURIComponent(page.id)}/blocks`,
      { type: appendType, content: appendDraft, agent: "ui_user" }
    );
    setAppendDraft("");
    if (window.LiveMonitorRefresh) window.LiveMonitorRefresh();
    if (onRefresh) onRefresh();
  }

  async function insertAfter(afterBlockId, type) {
    const content = window.prompt(`New ${type} block content:`);
    if (!content) return;
    await doPost(
      `/api/projects/${encodeURIComponent(projectId)}/workhub/pages/${encodeURIComponent(page.id)}/blocks/${encodeURIComponent(afterBlockId)}/after`,
      { type, content, agent: "ui_user" }
    );
    if (window.LiveMonitorRefresh) window.LiveMonitorRefresh();
    if (onRefresh) onRefresh();
  }

  return (
    <div className="block-editor">
      {pageBlocks.length === 0 && <div className="block-empty">(no blocks)</div>}
      {pageBlocks.map((b) => (
        <div key={b.id} className={`block block-${b.type || "text"}`}>
          <div className="block-meta">
            <span className="block-type-pill">{b.type || "text"}</span>
            <code className="block-id">{(b.id || "").substr(0, 12)}…</code>
          </div>
          {editing[b.id] !== undefined ? (
            <div className="block-edit">
              <textarea
                value={editing[b.id]}
                onChange={(e) => setEditing((prev) => ({ ...prev, [b.id]: e.target.value }))}
                rows={Math.max(3, (editing[b.id] || "").split("\n").length)}
              />
              <div className="block-edit-actions">
                <button type="button" onClick={() => saveBlock(b.id)} className="block-save-btn">Save</button>
                <button
                  type="button"
                  onClick={() => setEditing((prev) => { const c = { ...prev }; delete c[b.id]; return c; })}
                  className="block-cancel-btn"
                >Cancel</button>
              </div>
            </div>
          ) : (
            <pre
              className="block-content"
              onClick={() => setEditing((prev) => ({ ...prev, [b.id]: b.content || "" }))}
              title="Click to edit"
            >
              {b.content || "(empty)"}
            </pre>
          )}
          <div className="block-insert-after">
            <span>+ Insert after:</span>
            {["text", "code", "heading", "quote"].map((t) => (
              <button
                type="button"
                key={t}
                onClick={() => insertAfter(b.id, t)}
                className="block-insert-btn"
              >{t}</button>
            ))}
          </div>
        </div>
      ))}
      <div className="block-append">
        <select value={appendType} onChange={(e) => setAppendType(e.target.value)}>
          <option value="text">text</option>
          <option value="code">code</option>
          <option value="heading">heading</option>
          <option value="quote">quote</option>
        </select>
        <textarea
          value={appendDraft}
          onChange={(e) => setAppendDraft(e.target.value)}
          placeholder="New block content…"
          rows={3}
        />
        <button
          type="button"
          onClick={appendBlock}
          className="block-append-btn"
          disabled={!appendDraft.trim()}
        >+ Add block</button>
      </div>
    </div>
  );
}

// ---- Cutover 39: UserGatesSection ----
function UserGatesSection({ projectId }) {
  const [gates, setGates] = useState([]);
  const [showAdd, setShowAdd] = useState(false);
  const [name, setName] = useState("");
  const [type, setType] = useState("file_exists");
  const [params, setParams] = useState({});

  async function refresh() {
    if (!projectId) return;
    try {
      const r = await fetch(
        `/api/projects/${encodeURIComponent(projectId)}/user_gates`,
        { credentials: "include" }
      );
      const data = await r.json();
      setGates(data.gates || []);
    } catch (e) {
      setGates([]);
    }
  }
  useEffect(() => { refresh(); }, [projectId]);

  async function createGate() {
    if (!name.trim()) return;
    const data = await postJson(
      `/api/projects/${encodeURIComponent(projectId)}/user_gates`,
      { name, type, params }
    );
    if (data && data.error) { window.alert(data.error); return; }
    setShowAdd(false); setName(""); setParams({});
    refresh();
  }

  async function deleteGate(gid) {
    if (!window.confirm("Delete this gate?")) return;
    await deleteJson(
      `/api/projects/${encodeURIComponent(projectId)}/user_gates/${encodeURIComponent(gid)}`,
      {}
    );
    refresh();
  }

  function renderParamsForm() {
    if (type === "file_exists") {
      return <input placeholder="path (e.g. README.md)"
                    value={params.path || ""}
                    onChange={e => setParams({ path: e.target.value })} />;
    }
    if (type === "endpoint_exists") {
      return (
        <>
          <select value={params.method || "GET"}
                  onChange={e => setParams({ ...params, method: e.target.value })}>
            {["GET","POST","PUT","PATCH","DELETE"].map(m =>
              <option key={m} value={m}>{m}</option>)}
          </select>
          <input placeholder="/api/path" value={params.path || ""}
                 onChange={e => setParams({ ...params, path: e.target.value })} />
        </>
      );
    }
    if (type === "mcp_tool_exists") {
      return <input placeholder="tool name" value={params.name || ""}
                    onChange={e => setParams({ name: e.target.value })} />;
    }
    if (type === "visual_similarity") {
      return (
        <>
          <input placeholder="page_id" value={params.page_id || ""}
                 onChange={e => setParams({ ...params, page_id: e.target.value })} />
          <input type="number" min="0" max="1" step="0.05"
                 placeholder="min similarity (0-1)"
                 value={params.min_similarity ?? ""}
                 onChange={e => setParams({ ...params, min_similarity: parseFloat(e.target.value) })} />
        </>
      );
    }
    return null;
  }

  return (
    <div className="user-gates-section">
      <div className="user-gates-header">
        <strong>User Gates</strong>
        <button onClick={() => setShowAdd(!showAdd)} className="add-gate-btn">
          {showAdd ? "Cancel" : "+ Add Gate"}
        </button>
      </div>
      {showAdd && (
        <div className="add-gate-form">
          <input placeholder="Gate name" value={name}
                 onChange={e => setName(e.target.value)} />
          <select value={type} onChange={e => { setType(e.target.value); setParams({}); }}>
            <option value="file_exists">file_exists</option>
            <option value="endpoint_exists">endpoint_exists</option>
            <option value="mcp_tool_exists">mcp_tool_exists</option>
            <option value="visual_similarity">visual_similarity</option>
          </select>
          {renderParamsForm()}
          <button onClick={createGate} className="create-gate-btn">Create</button>
        </div>
      )}
      {gates.length === 0 && (
        <div className="empty-gates">(no user gates defined)</div>
      )}
      {gates.map(g => (
        <div key={g.id}
             className={"user-gate " + (g.status && g.status.passed ? "passed" : "failed")}>
          <div className="user-gate-row">
            <span className={"gate-pill " + (g.status && g.status.passed ? "pass" : "fail")}>
              {g.status && g.status.passed ? "PASS" : "FAIL"}
            </span>
            <strong>{g.name}</strong>
            <code className="gate-type">{g.type}</code>
            <button className="delete-gate-btn"
                    onClick={() => deleteGate(g.id)}>×</button>
          </div>
          <div className="user-gate-detail">
            <code>{JSON.stringify(g.params)}</code>
            <div className="user-gate-msg">{(g.status && g.status.message) || ""}</div>
          </div>
        </div>
      ))}
    </div>
  );
}


// ---- Cutover 40: ReferencesSection ----
function ReferencesSection({ projectId }) {
  const { useEffect, useState, useRef } = React;
  const [files, setFiles] = useState([]);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  const fileInputRef = useRef(null);

  async function refresh() {
    if (!projectId) return;
    try {
      const r = await fetch(`/api/projects/${encodeURIComponent(projectId)}/references`,
                            { credentials: "include" });
      const data = await r.json();
      setFiles(data.files || []);
      setError("");
    } catch (e) {
      setError(String(e));
    }
  }
  useEffect(() => { refresh(); }, [projectId]);

  function handleFile(file) {
    if (!file) return;
    if (file.size > 10 * 1024 * 1024) {
      setError(`${file.name} exceeds 10MB cap`);
      return;
    }
    setPending(true); setError("");
    const reader = new FileReader();
    reader.onload = async (ev) => {
      try {
        const dataUrl = ev.target.result;  // e.g. "data:image/png;base64,iVBOR..."
        const b64 = dataUrl.split(",")[1] || "";
        const r = await fetch(`/api/projects/${encodeURIComponent(projectId)}/references`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          credentials: "include",
          body: JSON.stringify({ filename: file.name, content_base64: b64 }),
        });
        const data = await r.json();
        if (data.error) { setError(data.error); }
        else { refresh(); }
      } catch (e) {
        setError(String(e));
      } finally {
        setPending(false);
      }
    };
    reader.onerror = () => { setError("file read failed"); setPending(false); };
    reader.readAsDataURL(file);
  }

  function onFileChange(e) {
    const f = e.target.files?.[0];
    if (f) handleFile(f);
    e.target.value = "";  // allow re-uploading same file
  }

  async function deleteFile(name) {
    if (!window.confirm(`Delete reference '${name}'?`)) return;
    await fetch(`/api/projects/${encodeURIComponent(projectId)}/references/${encodeURIComponent(name)}`,
                { method: "DELETE", credentials: "include" });
    refresh();
  }

  function fmtSize(n) {
    if (n < 1024) return `${n}B`;
    if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)}KB`;
    return `${(n / (1024 * 1024)).toFixed(1)}MB`;
  }

  return (
    <div className="references-section">
      <div className="references-header">
        <strong>References</strong>
        <input type="file" ref={fileInputRef} onChange={onFileChange} style={{ display: "none" }} />
        <button onClick={() => fileInputRef.current?.click()} className="ref-upload-btn" disabled={pending}>
          {pending ? "Uploading…" : "+ Upload"}
        </button>
      </div>
      {error && <div className="ref-error">{error}</div>}
      {files.length === 0 && <div className="ref-empty">(no reference files)</div>}
      {files.map(f => (
        <div key={f.name} className={"ref-file ref-cat-" + f.category}>
          <div className="ref-file-row">
            <span className={"ref-cat-pill cat-" + f.category}>{f.category}</span>
            <code className="ref-name">{f.name}</code>
            <span className="ref-size">{fmtSize(f.size)}</span>
            <button className="ref-delete-btn" onClick={() => deleteFile(f.name)}>×</button>
          </div>
          {f.preview && (
            <details className="ref-preview-details">
              <summary>preview</summary>
              <pre className="ref-preview">{f.preview}</pre>
            </details>
          )}
        </div>
      ))}
    </div>
  );
}


// ---- WorkHubPanel ----
function WorkHubPanel({ snapshot, projectId, onChange }) {
  const s = snapshot || {};
  const tasks = Object.values(s.tasks || {});
  // page→document rename: snapshot key is ``documents`` (legacy ``pages`` fallback).
  const pages = Object.values(s.documents || s.pages || {});
  const allComments = Object.values(s.comments || {});

  const columns = ["pending", "in_progress", "completed", "failed", "blocked"];
  const tasksByStatus = {};
  for (const c of columns) tasksByStatus[c] = [];
  for (const t of tasks) {
    const status = t.status || "pending";
    if (tasksByStatus[status]) tasksByStatus[status].push(t);
    else (tasksByStatus.pending).push(t);
  }
  const prioRank = { P0: 0, P1: 1, P2: 2, P3: 3 };
  for (const c of columns) {
    tasksByStatus[c].sort((a, b) => {
      const pa = prioRank[(a.metadata || {}).priority || "P2"] ?? 9;
      const pb = prioRank[(b.metadata || {}).priority || "P2"] ?? 9;
      if (pa !== pb) return pa - pb;
      return (b.created_at || 0) - (a.created_at || 0);
    });
  }

  const visuals = pages.filter((p) => p.kind === "visual_review");
  const recentReviews = pages
    .filter((p) => p.last_review || p.visual_review)
    .slice(-5)
    .reverse();

  const [showForm, setShowForm] = useState(null);
  const [reviewForPage, setReviewForPage] = useState(null); // { page_id }
  const [decisionForPage, setDecisionForPage] = useState(null);
  const [showPlanForm, setShowPlanForm] = useState(false);
  const [expandedPages, setExpandedPages] = useState({}); // Cutover 37: per-page block editor expand state

  async function setPriority(taskId, priority) {
    if (!projectId) return;
    const data = await postJson(`/api/projects/${projectId}/workhub/tasks/${taskId}/priority`, { priority });
    if (data && data.error) alert(`Set priority failed: ${data.error}`);
    onChange && onChange();
  }

  return (
    <HubCard
      title="WorkHub"
      count={tasks.length}
      subtitle={`${pages.length} pages · ${visuals.length} visual reviews`}
      accent="#6ed191"
    >
      <div className="hub-actions">
        <button type="button" className="hub-op-btn" onClick={() => setShowForm("task")} disabled={!projectId}>+ Task</button>
        <button type="button" className="hub-op-btn" onClick={() => setShowForm("page")} disabled={!projectId}>+ Page</button>
        <button type="button" className="hub-op-btn destructive" onClick={() => setShowForm("dead_code")} disabled={!projectId}>Mark Path Dead</button>
      </div>

      <UserGatesSection projectId={projectId} />
      <ReferencesSection projectId={projectId} />

      <h4 className="hub-subtitle">Tasks ({tasks.length})</h4>
      {tasks.length === 0 ? (
        <div className="hub-empty">No tasks yet.</div>
      ) : (
        <div className="kanban">
          {columns.map((col) => (
            <div key={col} className={`kanban-col kanban-col-${col}`}>
              <h5>{col} <em>{tasksByStatus[col].length}</em></h5>
              {tasksByStatus[col].length === 0 ? (
                <div className="kanban-empty">—</div>
              ) : (
                tasksByStatus[col].map((t) => (
                  <TaskCard
                    key={t.id}
                    task={t}
                    projectId={projectId}
                    comments={allComments}
                    onChange={onChange}
                    onSetPriority={setPriority}
                  />
                ))
              )}
            </div>
          ))}
        </div>
      )}

      <h4 className="hub-subtitle">Pages ({pages.length})</h4>
      {pages.length === 0 ? (
        <div className="hub-empty">No pages.</div>
      ) : (
        <table className="hub-table">
          <thead><tr><th>Page</th><th>Title</th><th>Kind</th><th>Status</th><th>Actions</th></tr></thead>
          <tbody>
            {pages.slice(0, 12).map((p) => (
              <React.Fragment key={p.id}>
                <tr>
                  <td><code>{shortId(p.id, 12)}</code></td>
                  <td>{p.title || <em>(untitled)</em>}</td>
                  <td>{p.kind || "general"}</td>
                  <td>{p.status || "—"}</td>
                  <td className="hub-row-actions">
                    {p.kind === "visual_review" && (
                      <button type="button" className="hub-op-btn small" onClick={() => setReviewForPage({ page_id: p.id })}>Visual review</button>
                    )}
                    <button type="button" className="hub-op-btn small" onClick={() => setDecisionForPage(p.id)}>+ Decision</button>
                    <button
                      type="button"
                      className="page-expand-btn"
                      onClick={() => setExpandedPages((prev) => ({ ...prev, [p.id]: !prev[p.id] }))}
                    >
                      {expandedPages[p.id] ? "▼ Hide blocks" : "▶ Show blocks"}
                    </button>
                  </td>
                </tr>
                {expandedPages[p.id] && (
                  <tr className="page-blocks-row">
                    <td colSpan={5}>
                      <BlockEditor
                        projectId={projectId}
                        page={p}
                        blocks={s.blocks || {}}
                        onRefresh={onChange}
                      />
                    </td>
                  </tr>
                )}
              </React.Fragment>
            ))}
          </tbody>
        </table>
      )}
      <div className="hub-actions" style={{ borderBottom: "none", marginTop: 6 }}>
        <button type="button" className="hub-op-btn" onClick={() => setShowPlanForm(true)} disabled={!projectId || pages.length === 0}>+ Plan</button>
      </div>

      {recentReviews.length > 0 && (
        <>
          <h4 className="hub-subtitle">Recent reviews ({recentReviews.length})</h4>
          <ul className="hub-list">
            {recentReviews.map((p) => {
              const review = p.last_review || p.visual_review || {};
              return (
                <li key={p.id}>
                  <code>{shortId(p.id, 10)}</code> <strong>{p.title}</strong>
                  <small> · {p.kind}</small>
                  {review.state && <small> · {review.state}</small>}
                  {review.reviewer && <small> · by {review.reviewer}</small>}
                </li>
              );
            })}
          </ul>
        </>
      )}

      {showForm && (
        <WorkHubForm
          kind={showForm}
          projectId={projectId}
          onDone={() => { setShowForm(null); onChange && onChange(); }}
          onCancel={() => setShowForm(null)}
        />
      )}
      {reviewForPage && (
        <PageReviewForm
          projectId={projectId}
          pageId={reviewForPage.page_id}
          onDone={() => { setReviewForPage(null); onChange && onChange(); }}
          onCancel={() => setReviewForPage(null)}
        />
      )}
      {decisionForPage && (
        <DecisionForm
          projectId={projectId}
          pageId={decisionForPage}
          onDone={() => { setDecisionForPage(null); onChange && onChange(); }}
          onCancel={() => setDecisionForPage(null)}
        />
      )}
      {showPlanForm && (
        <PlanForm
          projectId={projectId}
          pages={pages}
          onDone={() => { setShowPlanForm(false); onChange && onChange(); }}
          onCancel={() => setShowPlanForm(false)}
        />
      )}
    </HubCard>
  );
}

// ---- TaskCard (kanban entry with lifecycle + comments) ----
// Tier B B3b: expand panel that renders ``task.plan`` (the agent's
// per-task structured-think, persisted by PlanTool's periodic flush
// via ``WorkHub.update_task_plan``). Pure presentational — reads the
// plan dict already attached to the task; no extra fetch needed.
function TaskPlanExpand({ plan }) {
  if (!plan || typeof plan !== "object") return null;
  const stageOrder = Array.isArray(plan.stage_order) && plan.stage_order.length
    ? plan.stage_order
    : Object.keys(plan.stages || {});
  const currentStage = plan.current_stage_id || "";
  const acceptance = Array.isArray(plan.acceptance)
    ? plan.acceptance
    : (plan.acceptance && plan.acceptance.functional) || [];
  return (
    <details className="task-plan-expand">
      <summary>
        <span className="task-plan-chevron">▸</span>
        <span className="task-plan-title">
          {plan.title || plan.plan_name || "Plan"}
        </span>
        {currentStage && (
          <span className="task-plan-current"> · current:{currentStage}</span>
        )}
      </summary>
      <div className="task-plan-body">
        {acceptance.length > 0 && (
          <div className="task-plan-acceptance">
            <em>acceptance:</em>
            <ul>
              {acceptance.map((a, i) => {
                const status = (a && (a.status || a.state)) || "";
                const done = ["passed", "done", "accepted", "waived", "completed"].includes(
                  String(status).toLowerCase()
                );
                const text = (a && (a.text || a.criterion || a.description)) || JSON.stringify(a);
                return (
                  <li key={i} className={done ? "ac-done" : "ac-pending"}>
                    <span>{done ? "✓" : "○"}</span> {text}
                  </li>
                );
              })}
            </ul>
          </div>
        )}
        <div className="task-plan-stages">
          {stageOrder.map((sid) => {
            const stage = (plan.stages || {})[sid] || {};
            const stageStatus = stage.status || (sid === currentStage ? "in_progress" : "pending");
            const tasks = Object.entries(stage.tasks || {});
            const isCurrent = sid === currentStage;
            return (
              <div key={sid} className={`task-plan-stage stage-${stageStatus} ${isCurrent ? "stage-current" : ""}`}>
                <div className="task-plan-stage-header">
                  <span>{isCurrent ? "▼" : "▷"}</span>
                  <strong>{stage.name || sid}</strong>
                  <small>[{stageStatus}]</small>
                  {isCurrent && <small className="stage-current-tag">← current</small>}
                </div>
                {tasks.length > 0 && (
                  <ul className="task-plan-stage-tasks">
                    {tasks.map(([tid, t]) => {
                      const ts = (t && t.status) || "pending";
                      const marker = ts === "completed" ? "✓" : ts === "in_progress" ? "◐" : "·";
                      return (
                        <li key={tid} className={`pt-${ts}`}>
                          <span>{marker}</span> {(t && (t.description || tid)) || tid}
                        </li>
                      );
                    })}
                  </ul>
                )}
              </div>
            );
          })}
        </div>
        {plan._updated_at && (
          <small className="task-plan-footer">
            updated {new Date(plan._updated_at * 1000).toLocaleTimeString()}
            {plan._updated_by && ` by ${plan._updated_by}`}
          </small>
        )}
      </div>
    </details>
  );
}

function TaskCard({ task, projectId, comments, onChange, onSetPriority }) {
  const [busy, setBusy] = useState(false);
  const [commentText, setCommentText] = useState("");
  const status = task.status || "pending";
  const taskComments = (comments || []).filter((c) => c && c.resource_id === task.id);

  async function lifecycle(action) {
    if (!projectId || busy) return;
    let body = { agent: "ui_user" };
    if (action === "fail") {
      const reason = window.prompt("Fail reason (>=5 chars):");
      if (!reason) return;
      if (reason.length < 5) { alert("Reason too short."); return; }
      body.reason = reason;
    }
    setBusy(true);
    const data = await postJson(`/api/projects/${projectId}/workhub/tasks/${task.id}/${action}`, body);
    setBusy(false);
    if (data && data.error) { alert(`${action} failed: ${data.error}`); return; }
    if (window.LiveMonitorRefresh) window.LiveMonitorRefresh();
    else onChange && onChange();
  }

  async function sendComment() {
    if (!projectId) return;
    const body = commentText.trim();
    if (body.length < 3) { alert("Comment must be >=3 chars."); return; }
    const data = await postJson(
      `/api/projects/${projectId}/workhub/comments/${encodeURIComponent(task.id)}`,
      { body, agent: "ui_user" }
    );
    if (data && data.error) { alert(`Comment failed: ${data.error}`); return; }
    setCommentText("");
    if (window.LiveMonitorRefresh) window.LiveMonitorRefresh();
    else onChange && onChange();
  }

  return (
    <div className="task-card">
      <div className="task-card-row">
        <code className="task-id">{shortId(task.id, 14)}</code>
        <PriorityChip priority={(task.metadata || {}).priority} />
      </div>
      <div className="task-card-title">{task.title || <em>(untitled)</em>}</div>
      <div className="task-card-meta">
        <small>{task.assignee || task.claimed_by || "unassigned"}</small>
        {task.plan_id && <small> · plan:{shortId(task.plan_id, 8)}</small>}
      </div>
      {task.plan && <TaskPlanExpand plan={task.plan} />}
      <div className="task-card-actions task-lifecycle-actions">
        {status === "pending" && (
          <button type="button" className="hub-op-btn small task-lifecycle-btn" disabled={busy} onClick={() => lifecycle("claim")}>Claim</button>
        )}
        {status === "in_progress" && (
          <button type="button" className="hub-op-btn small task-lifecycle-btn" disabled={busy} onClick={() => lifecycle("complete")}>Complete</button>
        )}
        {(status === "pending" || status === "in_progress") && (
          <button type="button" className="hub-op-btn small task-lifecycle-btn destructive" disabled={busy} onClick={() => lifecycle("fail")}>Fail</button>
        )}
        {(status === "pending" || status === "in_progress" || status === "blocked") && (
          <button type="button" className="hub-op-btn small task-lifecycle-btn ghost" disabled={busy} onClick={() => lifecycle("cancel")}>Cancel</button>
        )}
        <select
          value={(task.metadata || {}).priority || "P2"}
          onChange={(e) => onSetPriority(task.id, e.target.value)}
          title="Set priority"
        >
          {["P0", "P1", "P2", "P3"].map((p) => <option key={p} value={p}>{p}</option>)}
        </select>
      </div>
      <details className="task-comments-details">
        <summary>Comments ({taskComments.length})</summary>
        <div className="task-comments-list">
          {taskComments.length === 0 ? (
            <div className="hub-empty">No comments yet.</div>
          ) : (
            taskComments.map((c) => (
              <div key={c.id} className="comment-row">
                <small>{c.agent || "—"}</small>
                <span> {c.body}</span>
              </div>
            ))
          )}
        </div>
        <div className="task-comment-input">
          <textarea
            placeholder="Add a comment (>=3 chars)"
            value={commentText}
            onChange={(e) => setCommentText(e.target.value)}
          />
          <button type="button" className="hub-op-btn small" onClick={sendComment}>Send</button>
        </div>
      </details>
    </div>
  );
}

function DecisionForm({ projectId, pageId, onDone, onCancel }) {
  const [title, setTitle] = useState("");
  const [optionsCsv, setOptionsCsv] = useState("");
  const [chosen, setChosen] = useState("");
  const [reason, setReason] = useState("");
  const [agent, setAgent] = useState("ui_user");
  const [err, setErr] = useState("");

  async function submit() {
    setErr("");
    const options = optionsCsv.split(",").map((s) => s.trim()).filter(Boolean);
    if (!title.trim() || !chosen.trim() || !reason.trim() || options.length === 0) {
      setErr("title, options, chosen, reason all required");
      return;
    }
    const data = await postJson(
      `/api/projects/${projectId}/workhub/pages/${encodeURIComponent(pageId)}/decisions`,
      {
        title: title.trim(),
        options,
        chosen: chosen.trim(),
        reason: reason.trim(),
        agent: agent.trim() || "ui_user",
      }
    );
    if (data && data.error) { setErr(data.error); return; }
    onDone();
  }

  return (
    <HubForm
      title={`+ Decision on ${pageId}`}
      error={err}
      onSubmit={submit}
      onCancel={onCancel}
      submitLabel="Record decision"
    >
      <input placeholder="title (required)" value={title} onChange={(e) => setTitle(e.target.value)} />
      <input placeholder="options (comma-separated)" value={optionsCsv} onChange={(e) => setOptionsCsv(e.target.value)} />
      <input placeholder="chosen (must be one of the options)" value={chosen} onChange={(e) => setChosen(e.target.value)} />
      <textarea placeholder="reason (required)" value={reason} onChange={(e) => setReason(e.target.value)} />
      <input placeholder="agent (default: ui_user)" value={agent} onChange={(e) => setAgent(e.target.value)} />
    </HubForm>
  );
}

function PlanForm({ projectId, pages, onDone, onCancel }) {
  const [pageId, setPageId] = useState((pages && pages[0] && pages[0].id) || "");
  const [title, setTitle] = useState("");
  const [stagesCsv, setStagesCsv] = useState("");
  const [agent, setAgent] = useState("ui_user");
  const [err, setErr] = useState("");

  async function submit() {
    setErr("");
    const stageNames = stagesCsv.split(",").map((s) => s.trim()).filter(Boolean);
    if (!pageId) { setErr("page_id required"); return; }
    if (stageNames.length === 0) { setErr("at least one stage required"); return; }
    const stages = stageNames.map((name, i) => ({ id: `s${i + 1}`, name }));
    const data = await postJson(`/api/projects/${projectId}/workhub/plans`, {
      page_id: pageId,
      title: title.trim(),
      stages,
      tasks: [],
      agent: agent.trim() || "ui_user",
    });
    if (data && data.error) { setErr(data.error); return; }
    onDone();
  }

  return (
    <HubForm
      title="+ New Plan"
      error={err}
      onSubmit={submit}
      onCancel={onCancel}
      submitLabel="Create plan"
    >
      <select value={pageId} onChange={(e) => setPageId(e.target.value)}>
        {(pages || []).map((p) => (
          <option key={p.id} value={p.id}>{p.title || p.id}</option>
        ))}
      </select>
      <input placeholder="title" value={title} onChange={(e) => setTitle(e.target.value)} />
      <input placeholder='stages (comma-separated, e.g. "design,build,test")' value={stagesCsv} onChange={(e) => setStagesCsv(e.target.value)} />
      <input placeholder="agent (default: ui_user)" value={agent} onChange={(e) => setAgent(e.target.value)} />
    </HubForm>
  );
}

function WorkHubForm({ kind, projectId, onDone, onCancel }) {
  const [fields, setFields] = useState({});
  const [err, setErr] = useState("");
  function set(k, v) { setFields((cur) => ({ ...cur, [k]: v })); }

  async function submit() {
    setErr("");
    let url, body;
    if (kind === "task") {
      if (!(fields.title || "").trim()) { setErr("title required"); return; }
      url = `/api/projects/${projectId}/workhub/tasks`;
      body = {
        title: fields.title.trim(),
        description: fields.description || "",
        agent: fields.agent || "ui_user",
        assignee: fields.assignee || "",
        domain: fields.domain || "ui",
        priority: fields.priority || "P2",
      };
    } else if (kind === "page") {
      if (!(fields.title || "").trim()) { setErr("title required"); return; }
      url = `/api/projects/${projectId}/workhub/pages`;
      body = {
        title: fields.title.trim(),
        kind: fields.kind || "general",
        attendees: (fields.attendees || "").split(",").map((s) => s.trim()).filter(Boolean),
      };
    } else if (kind === "dead_code") {
      const path = (fields.path || "").trim();
      const reason = (fields.reason || "").trim();
      if (!path) { setErr("path required"); return; }
      if (reason.length < 10) { setErr("reason must be >= 10 chars"); return; }
      if (!window.confirm(`Mark "${path}" as intentionally dead?\nThis BYPASSES the dead-code gate.\nReason: "${reason}"`)) return;
      url = `/api/projects/${projectId}/workhub/coverage_allowlist`;
      body = { path, reason, agent: "ui_user" };
    }
    const data = await postJson(url, body);
    if (data && data.error) { setErr(data.error); return; }
    onDone();
  }

  let body;
  if (kind === "task") {
    body = (
      <>
        <input placeholder="title (required)" value={fields.title || ""} onChange={(e) => set("title", e.target.value)} />
        <textarea placeholder="description" value={fields.description || ""} onChange={(e) => set("description", e.target.value)} />
        <input placeholder="agent (creator, default: ui_user)" value={fields.agent || ""} onChange={(e) => set("agent", e.target.value)} />
        <input placeholder="assignee" value={fields.assignee || ""} onChange={(e) => set("assignee", e.target.value)} />
        <input placeholder="domain (default: ui)" value={fields.domain || ""} onChange={(e) => set("domain", e.target.value)} />
        <select value={fields.priority || "P2"} onChange={(e) => set("priority", e.target.value)}>
          {["P0", "P1", "P2", "P3"].map((p) => <option key={p} value={p}>{p}</option>)}
        </select>
      </>
    );
  } else if (kind === "page") {
    body = (
      <>
        <input placeholder="title (required)" value={fields.title || ""} onChange={(e) => set("title", e.target.value)} />
        <select value={fields.kind || "general"} onChange={(e) => set("kind", e.target.value)}>
          <option value="general">general</option>
          <option value="visual_review">visual_review</option>
          <option value="meeting">meeting</option>
        </select>
        <input placeholder="attendees (comma-separated)" value={fields.attendees || ""} onChange={(e) => set("attendees", e.target.value)} />
      </>
    );
  } else if (kind === "dead_code") {
    body = (
      <>
        <input placeholder="path (e.g. src/foo.py)" value={fields.path || ""} onChange={(e) => set("path", e.target.value)} />
        <textarea placeholder="reason (>= 10 chars, explain why it's intentionally dead)" value={fields.reason || ""} onChange={(e) => set("reason", e.target.value)} />
      </>
    );
  }

  const titles = {
    task: "+ New Task",
    page: "+ New Page",
    dead_code: "Mark Path Intentionally Dead (DESTRUCTIVE)",
  };
  return (
    <HubForm
      title={titles[kind]}
      error={err}
      onSubmit={submit}
      onCancel={onCancel}
      submitLabel={kind === "dead_code" ? "Mark Dead" : "Create"}
      destructive={kind === "dead_code"}
    >
      {body}
    </HubForm>
  );
}

function PageReviewForm({ projectId, pageId, onDone, onCancel }) {
  const [reviewer, setReviewer] = useState("ui_user");
  const [state, setState] = useState("approved");
  const [summary, setSummary] = useState("");
  const [similarity, setSimilarity] = useState("");
  const [err, setErr] = useState("");

  async function submit() {
    setErr("");
    const url = `/api/projects/${projectId}/workhub/pages/${pageId}/visual_review`;
    const body = { reviewer, state, summary, deviations: [] };
    if (similarity) body.similarity_score = Number(similarity);
    const data = await postJson(url, body);
    if (data && data.error) { setErr(data.error); return; }
    onDone();
  }
  return (
    <HubForm
      title={`Submit Visual Review (${pageId})`}
      error={err}
      onSubmit={submit}
      onCancel={onCancel}
      submitLabel="Submit"
    >
      <input placeholder="reviewer" value={reviewer} onChange={(e) => setReviewer(e.target.value)} />
      <select value={state} onChange={(e) => setState(e.target.value)}>
        <option value="approved">approved</option>
        <option value="changes_requested">changes_requested</option>
        <option value="commented">commented</option>
      </select>
      <input placeholder="similarity_score (0-1)" value={similarity} onChange={(e) => setSimilarity(e.target.value)} />
      <textarea placeholder="summary" value={summary} onChange={(e) => setSummary(e.target.value)} />
      {/* TODO Cutover 30 final pass: surface deviations editor */}
    </HubForm>
  );
}

// ---- EventHubPanel ----
function EventHubPanel({ snapshot, projectId, onChange }) {
  const s = snapshot || {};
  const events = Object.values(s.events || {});
  const threads = Object.values(s.threads || {});
  const subscriptions = Object.values(s.subscriptions || {});
  const inboxes = Object.values(s.inboxes || {});

  const sortedThreads = [...threads].sort(
    (a, b) => (b.updated_at || b.created_at || 0) - (a.updated_at || a.created_at || 0)
  );

  const eventsById = {};
  for (const e of events) eventsById[e.id] = e;
  const sortedEvents = [...events].sort((a, b) => (b.created_at || 0) - (a.created_at || 0));

  const inboxCounts = inboxes.map((ib) => {
    const items = Object.values(ib.items || {});
    return {
      agent: ib.agent,
      total: items.length,
      unread: items.filter((it) => !it.read).length,
    };
  });

  const [agentFilter, setAgentFilter] = useState("");
  const [showSubscribe, setShowSubscribe] = useState(false);
  const selectedInbox = agentFilter ? inboxes.find((ib) => ib.agent === agentFilter) : null;
  const selectedItems = selectedInbox ? Object.values(selectedInbox.items || {}) : [];

  async function markRead(agent, eventId) {
    if (!projectId) return;
    const data = await postJson(`/api/projects/${projectId}/eventhub/inbox/${agent}/mark_read`, { event_id: eventId });
    if (data && data.error) alert(`Mark read failed: ${data.error}`);
    onChange && onChange();
  }
  async function markAllRead(agent) {
    if (!projectId) return;
    if (!window.confirm(`Mark all of ${agent}'s inbox items as read?`)) return;
    const data = await postJson(`/api/projects/${projectId}/eventhub/inbox/${agent}/mark_all_read`, {});
    if (data && data.error) alert(`Mark-all failed: ${data.error}`);
    onChange && onChange();
  }

  return (
    <HubCard
      title="EventHub"
      count={events.length}
      subtitle={`${threads.length} threads · ${subscriptions.length} subscriptions · ${inboxes.length} inboxes`}
      accent="#c594c5"
    >
      <div className="hub-actions">
        <button type="button" className="hub-op-btn" onClick={() => setShowSubscribe(true)} disabled={!projectId}>+ Subscribe agent</button>
      </div>

      <h4 className="hub-subtitle">Threads ({threads.length})</h4>
      {sortedThreads.length === 0 ? (
        <div className="hub-empty">No threads.</div>
      ) : (
        <table className="hub-table">
          <thead>
            <tr><th>Thread</th><th>Participants</th><th>Latest event</th><th>Updated</th></tr>
          </thead>
          <tbody>
            {sortedThreads.slice(0, 10).map((t) => {
              const eventIds = t.event_ids || [];
              const latestId = eventIds[eventIds.length - 1];
              const latest = latestId ? eventsById[latestId] : null;
              return (
                <tr key={t.id}>
                  <td><code>{shortId(t.id, 14)}</code></td>
                  <td><small>{(t.participants || []).join(", ") || "—"}</small></td>
                  <td>
                    {latest ? (
                      <span><code>{latest.event_type}</code> <small>from {latest.source_hub}</small></span>
                    ) : <em>—</em>}
                  </td>
                  <td><small>{fmtTime(t.updated_at || t.created_at)}</small></td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}

      <h4 className="hub-subtitle">Recent events ({Math.min(sortedEvents.length, 8)} of {sortedEvents.length})</h4>
      {sortedEvents.length === 0 ? (
        <div className="hub-empty">No events.</div>
      ) : (
        <ul className="hub-list">
          {sortedEvents.slice(0, 8).map((e) => (
            <li key={e.id} className={`event-row prio-${e.priority || "normal"}`}>
              <code>{shortId(e.id, 10)}</code>
              <small> · {e.source_hub}</small>
              <small> · </small>
              <strong>{e.event_type}</strong>
              <small> · {e.priority || "normal"}</small>
              {e.recipients && e.recipients.length > 0 && (
                <small> → {e.recipients.join(", ")}</small>
              )}
            </li>
          ))}
        </ul>
      )}

      <h4 className="hub-subtitle">Inboxes ({inboxes.length})</h4>
      {inboxCounts.length === 0 ? (
        <div className="hub-empty">No inboxes.</div>
      ) : (
        <>
          <ul className="hub-list">
            {inboxCounts.map((ic) => (
              <li key={ic.agent}>
                <strong>{ic.agent}</strong>
                <small> · {ic.total} items</small>
                {ic.unread > 0 && <span className="inbox-unread"> · {ic.unread} unread</span>}
              </li>
            ))}
          </ul>
          <div className="hub-inline-row">
            <select value={agentFilter} onChange={(e) => setAgentFilter(e.target.value)}>
              <option value="">— pick agent inbox —</option>
              {inboxes.map((ib) => <option key={ib.agent} value={ib.agent}>{ib.agent}</option>)}
            </select>
            {agentFilter && (
              <button type="button" className="hub-op-btn small" onClick={() => markAllRead(agentFilter)}>Mark all read</button>
            )}
          </div>
          {agentFilter && selectedItems.length > 0 && (
            <table className="hub-table">
              <thead><tr><th>Event</th><th>Read</th><th>Action</th></tr></thead>
              <tbody>
                {selectedItems.slice(0, 20).map((it) => (
                  <tr key={it.event_id}>
                    <td><code>{shortId(it.event_id, 14)}</code></td>
                    <td>{it.read ? "✓" : ""}</td>
                    <td>
                      <button type="button" className="hub-op-btn small" disabled={!!it.read} onClick={() => markRead(agentFilter, it.event_id)}>Mark read</button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </>
      )}

      {showSubscribe && (
        <SubscribeForm
          projectId={projectId}
          onDone={() => { setShowSubscribe(false); onChange && onChange(); }}
          onCancel={() => setShowSubscribe(false)}
        />
      )}
    </HubCard>
  );
}

function SubscribeForm({ projectId, onDone, onCancel }) {
  const [agent, setAgent] = useState("");
  const [sourceHub, setSourceHub] = useState("*");
  const [eventType, setEventType] = useState("*");
  const [priorityFloor, setPriorityFloor] = useState("low");
  const [err, setErr] = useState("");
  async function submit() {
    setErr("");
    if (!agent.trim()) { setErr("agent required"); return; }
    const data = await postJson(`/api/projects/${projectId}/eventhub/subscriptions`, {
      agent: agent.trim(),
      source_hub: sourceHub.trim() || "*",
      event_type: eventType.trim() || "*",
      priority_floor: priorityFloor,
    });
    if (data && data.error) { setErr(data.error); return; }
    onDone();
  }
  return (
    <HubForm title="Subscribe agent" error={err} onSubmit={submit} onCancel={onCancel} submitLabel="Subscribe">
      <input placeholder="agent (required)" value={agent} onChange={(e) => setAgent(e.target.value)} />
      <input placeholder="source_hub (default: *)" value={sourceHub} onChange={(e) => setSourceHub(e.target.value)} />
      <input placeholder="event_type (default: *)" value={eventType} onChange={(e) => setEventType(e.target.value)} />
      <select value={priorityFloor} onChange={(e) => setPriorityFloor(e.target.value)}>
        <option value="low">low</option>
        <option value="normal">normal</option>
        <option value="high">high</option>
        <option value="critical">critical</option>
      </select>
    </HubForm>
  );
}

// ---- RunHubPanel ----
function RunHubPanel({ snapshot, projectId, onChange }) {
  const s = snapshot || {};
  const runs = Object.values(s.runs || {});
  runs.sort((a, b) => (b.started_at || 0) - (a.started_at || 0));

  const statusTotals = runs.reduce((acc, r) => {
    const k = r.status || "unknown";
    acc[k] = (acc[k] || 0) + 1;
    return acc;
  }, {});
  const summary = Object.entries(statusTotals).map(([k, v]) => `${v} ${k}`).join(" · ");

  const [showForm, setShowForm] = useState(false);

  async function setRunStatus(runId, status) {
    if (!projectId) return;
    const data = await postJson(`/api/projects/${projectId}/runhub/runs/${runId}/status`, { status });
    if (data && data.error) alert(`Set status failed: ${data.error}`);
    onChange && onChange();
  }

  return (
    <HubCard
      title="RunHub"
      count={runs.length}
      subtitle={summary || "end-to-end run history"}
      accent="#ff8a8a"
    >
      <div className="hub-actions">
        <button type="button" className="hub-op-btn" onClick={() => setShowForm(true)} disabled={!projectId}>+ Record Run</button>
      </div>
      {runs.length === 0 ? (
        <div className="hub-empty">No runs recorded.</div>
      ) : (
        <table className="hub-table">
          <thead>
            <tr>
              <th>Run ID</th><th>Branch</th><th>Started</th><th>Duration</th><th>Status</th><th>Fails</th><th>Action</th>
            </tr>
          </thead>
          <tbody>
            {runs.slice(0, 15).map((r) => {
              const passed = r.status === "completed" && (r.fail_count || 0) === 0;
              const failed = r.status === "failed" || r.status === "aborted" || (r.fail_count || 0) > 0;
              const badge = passed ? "passed" : failed ? "failed" : r.status;
              return (
                <tr key={r.id} className="run-row">
                  <td><code>{shortId(r.id, 12)}</code></td>
                  <td><small>{r.branch || "—"}</small></td>
                  <td><small>{fmtTime(r.started_at)}</small></td>
                  <td><small>{fmtDuration(r.started_at, r.finished_at)}</small></td>
                  <td><span className={`hub-pill run-${badge}`}>{badge}</span></td>
                  <td>{r.fail_count || 0}</td>
                  <td>
                    <select value="" onChange={(e) => { if (e.target.value) setRunStatus(r.id, e.target.value); }}>
                      <option value="">— set status —</option>
                      {["running", "completed", "failed", "aborted"].map((st) => <option key={st} value={st}>{st}</option>)}
                    </select>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
      {showForm && (
        <RunHubForm
          projectId={projectId}
          onDone={() => { setShowForm(false); onChange && onChange(); }}
          onCancel={() => setShowForm(false)}
        />
      )}
    </HubCard>
  );
}

function RunHubForm({ projectId, onDone, onCancel }) {
  const [branch, setBranch] = useState("main");
  const [generatedDir, setGeneratedDir] = useState("");
  const [kind, setKind] = useState("ci");
  const [status, setStatus] = useState("running");
  const [err, setErr] = useState("");
  async function submit() {
    setErr("");
    if (!branch.trim()) { setErr("branch required"); return; }
    if (!generatedDir.trim()) { setErr("generated_dir required"); return; }
    const data = await postJson(`/api/projects/${projectId}/runhub/runs`, {
      branch: branch.trim(),
      generated_dir: generatedDir.trim(),
      kind: kind.trim() || "ci",
      status,
    });
    if (data && data.error) { setErr(data.error); return; }
    onDone();
  }
  return (
    <HubForm title="+ Record Run" error={err} onSubmit={submit} onCancel={onCancel} submitLabel="Record">
      <input placeholder="branch (required)" value={branch} onChange={(e) => setBranch(e.target.value)} />
      <input placeholder="generated_dir (required, e.g. /tmp/run42)" value={generatedDir} onChange={(e) => setGeneratedDir(e.target.value)} />
      <input placeholder="kind (default: ci)" value={kind} onChange={(e) => setKind(e.target.value)} />
      <select value={status} onChange={(e) => setStatus(e.target.value)}>
        <option value="running">running</option>
        <option value="completed">completed</option>
        <option value="failed">failed</option>
        <option value="aborted">aborted</option>
      </select>
    </HubForm>
  );
}

// ---- HubsTab ----
function HubsTab({ hubs, projectId, onRefresh }) {
  const h = hubs || {};
  return (
    <div className="hubs-grid">
      <CodeHubPanel snapshot={h.codehub} projectId={projectId} onChange={onRefresh} />
      <RegistryHubPanel snapshot={h.registryhub} projectId={projectId} onChange={onRefresh} />
      <WorkHubPanel snapshot={h.workhub} projectId={projectId} onChange={onRefresh} />
      <EventHubPanel snapshot={h.eventhub} projectId={projectId} onChange={onRefresh} />
      <RunHubPanel snapshot={h.runhub} projectId={projectId} onChange={onRefresh} />
    </div>
  );
}

window.LiveMonitorHubsTab = HubsTab;
// Expose forms for testing/reuse if needed
window.LiveMonitorOpenPRForm = OpenPRForm;
