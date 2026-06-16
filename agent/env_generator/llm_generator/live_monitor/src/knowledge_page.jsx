// Top-level Knowledge & Skills page: inspect / edit / add / delete the
// host-wide persistent knowledge bank (sqlite) and bundled skills.
// Lives outside the per-project shell — global to the monitor host.
window.LiveMonitorKnowledgePage = (function () {
  const { useState, useEffect, useMemo } = React;
  const SEVERITY_OPTIONS = [
    { value: "low",      label: "low" },
    { value: "medium",   label: "medium" },
    { value: "high",     label: "high" },
    { value: "critical", label: "critical" },
  ];
  const CATEGORY_OPTIONS = [
    "tool_usage", "issue_solution", "integration", "best_practice", "docker",
    "api_pattern", "react_pattern", "ui_style", "db_schema", "seed_data",
  ].map(v => ({ value: v, label: v }));
  const SEV_COLOR = { low: "var(--text-muted)", medium: "var(--info)", high: "var(--warning)", critical: "var(--danger)" };
  const SEV_BG    = { low: "var(--bg-tertiary)", medium: "var(--info-soft)", high: "var(--warning-soft)", critical: "var(--danger-soft)" };

  async function call(path, body, method) {
    const r = await fetch(path, {
      method: method || (body ? "POST" : "GET"),
      headers: { "Content-Type": "application/json" },
      credentials: "include",
      body: body == null ? undefined : JSON.stringify(body),
    });
    const txt = await r.text();
    try { return [r.status, JSON.parse(txt)]; } catch (_) { return [r.status, { error: txt.slice(0, 300) }]; }
  }
  function fmtRel(ts) {
    if (!ts) return "—";
    const d = Date.now() / 1000 - ts;
    if (d < 60) return "just now";
    if (d < 3600) return `${Math.floor(d / 60)}m ago`;
    if (d < 86400) return `${Math.floor(d / 3600)}h ago`;
    return new Date(ts * 1000).toLocaleDateString();
  }

  // ============ Knowledge editor (used by both Add and Edit) ============
  function KnowledgeEditor({ initial, onSave, onCancel, saving }) {
    const UiSelect = window.HubUI?.UiSelect;
    const [v, setV] = useState({
      title: "", category: "tool_usage", severity: "medium",
      problem: "", solution: "", example_code: "", tags: "",
      ...(initial || {}),
    });
    const set = (k, val) => setV(p => ({ ...p, [k]: val }));
    const valid = (v.title || "").trim().length > 0 && (v.category || "").trim().length > 0;
    return (
      <div className="bg-bg-elevated border border-border rounded-lg p-5 mb-5 space-y-3">
        <div className="grid grid-cols-[1fr_180px_140px] gap-3">
          <div>
            <label className="block text-2xs uppercase tracking-wider font-medium text-fg-muted mb-1">Title<span className="text-danger ml-0.5">*</span></label>
            <input className="input-px w-full" value={v.title} onChange={e => set("title", e.target.value)} placeholder="e.g. apply_patch requires valid section headers" />
          </div>
          <div>
            <label className="block text-2xs uppercase tracking-wider font-medium text-fg-muted mb-1">Category<span className="text-danger ml-0.5">*</span></label>
            {UiSelect
              ? <UiSelect value={v.category} onChange={x => set("category", x)} options={CATEGORY_OPTIONS} inputStyle fullWidth minWidth={180} />
              : <input className="input-px w-full font-mono" value={v.category} onChange={e => set("category", e.target.value)} />}
          </div>
          <div>
            <label className="block text-2xs uppercase tracking-wider font-medium text-fg-muted mb-1">Severity</label>
            {UiSelect
              ? <UiSelect value={v.severity} onChange={x => set("severity", x)} options={SEVERITY_OPTIONS} inputStyle fullWidth minWidth={140} />
              : <input className="input-px w-full" value={v.severity} onChange={e => set("severity", e.target.value)} />}
          </div>
        </div>
        <div>
          <label className="block text-2xs uppercase tracking-wider font-medium text-fg-muted mb-1">Problem (optional)</label>
          <textarea className="input-px textarea-px w-full" rows={2} value={v.problem || ""} onChange={e => set("problem", e.target.value)} placeholder="What error / situation triggers this?" />
        </div>
        <div>
          <label className="block text-2xs uppercase tracking-wider font-medium text-fg-muted mb-1">Solution</label>
          <textarea className="input-px textarea-px w-full" rows={4} value={v.solution || ""} onChange={e => set("solution", e.target.value)} placeholder="The actual fix — concrete command / config / code path." />
        </div>
        <div>
          <label className="block text-2xs uppercase tracking-wider font-medium text-fg-muted mb-1">Example code (optional)</label>
          <textarea className="input-px textarea-px w-full font-mono text-xs" rows={3} value={v.example_code || ""} onChange={e => set("example_code", e.target.value)} placeholder="A short snippet showing the fix in use." />
        </div>
        <div>
          <label className="block text-2xs uppercase tracking-wider font-medium text-fg-muted mb-1">Tags (comma-separated)</label>
          <input className="input-px w-full" value={v.tags || ""} onChange={e => set("tags", e.target.value)} placeholder="docker, postgres, init" />
        </div>
        <div className="flex justify-end gap-2 pt-1">
          <button onClick={onCancel} className="btn-px btn-px-ghost">Cancel</button>
          <button onClick={() => onSave(v)} disabled={!valid || saving} className="btn-px btn-px-primary">
            {saving ? "Saving…" : (initial?.id ? "Save changes" : "Add entry")}
          </button>
        </div>
      </div>
    );
  }

  function KnowledgeRow({ entry, onEdit, onDelete, confirmingDel }) {
    const sevColor = SEV_COLOR[entry.severity] || SEV_COLOR.medium;
    const sevBg = SEV_BG[entry.severity] || SEV_BG.medium;
    const [open, setOpen] = useState(false);
    return (
      <div className="border border-border rounded-md bg-bg-elevated">
        <button onClick={() => setOpen(o => !o)} className="w-full text-left px-3 py-2.5 hover:bg-bg-hover transition-colors">
          <div className="flex items-center gap-3">
            <span className="text-2xs uppercase tracking-wider font-medium px-1.5 py-0.5 rounded shrink-0" style={{ color: sevColor, background: sevBg }}>{entry.severity}</span>
            <code className="text-2xs font-mono text-fg-muted shrink-0">{entry.category}</code>
            <span className="text-sm text-fg flex-1 min-w-0 truncate">{entry.title}</span>
            <span className="text-2xs text-fg-muted shrink-0">{fmtRel(entry.updated_at || entry.created_at)}</span>
            <span className="text-fg-muted text-2xs ml-1">{open ? "▾" : "▸"}</span>
          </div>
        </button>
        {open && (
          <div className="px-3 pb-3 pt-1 border-t border-border space-y-2">
            {entry.problem && <div><div className="text-2xs uppercase tracking-wider text-fg-muted mb-1">Problem</div><div className="text-sm text-fg-secondary whitespace-pre-wrap">{entry.problem}</div></div>}
            {entry.solution && <div><div className="text-2xs uppercase tracking-wider text-fg-muted mb-1">Solution</div><div className="text-sm text-fg-secondary whitespace-pre-wrap">{entry.solution}</div></div>}
            {entry.example_code && <div><div className="text-2xs uppercase tracking-wider text-fg-muted mb-1">Example</div><pre className="text-xs font-mono text-fg-secondary bg-bg p-2 rounded border border-border overflow-x-auto whitespace-pre-wrap">{entry.example_code}</pre></div>}
            <div className="flex items-center gap-3 pt-1">
              {entry.tags && <span className="text-2xs text-fg-muted font-mono">{entry.tags}</span>}
              <span className="text-2xs text-fg-muted">source: {entry.source || "—"}</span>
              <span className="text-2xs text-fg-muted">uses: {entry.usage_count || 0}</span>
              <span className="ml-auto flex items-center gap-2">
                <button onClick={() => onEdit(entry)} className="btn-px btn-px-ghost btn-px-sm">Edit</button>
                {confirmingDel
                  ? (<>
                      <span className="text-2xs text-danger">delete?</span>
                      <button onClick={() => onDelete(entry, true)} className="btn-px btn-px-danger btn-px-sm">Confirm</button>
                      <button onClick={() => onDelete(null, false)} className="btn-px btn-px-ghost btn-px-sm">No</button>
                    </>)
                  : <button onClick={() => onDelete(entry, false)} className="btn-px btn-px-danger-ghost btn-px-sm">Delete</button>}
              </span>
            </div>
          </div>
        )}
      </div>
    );
  }

  function KnowledgeTab() {
    const UiSelect = window.HubUI?.UiSelect;
    const Icons = window.Icons || {};
    const [data, setData] = useState({ entries: [], categories: [], total: 0 });
    const [q, setQ] = useState("");
    const [cat, setCat] = useState("");
    const [adding, setAdding] = useState(false);
    const [editing, setEditing] = useState(null);   // entry being edited
    const [confirmDel, setConfirmDel] = useState(null);  // id awaiting confirm
    const [busy, setBusy] = useState(false);
    const [err, setErr] = useState("");

    async function load() {
      const qs = new URLSearchParams();
      if (q.trim()) qs.set("q", q.trim());
      if (cat) qs.set("category", cat);
      const [, d] = await call(`/api/knowledge?${qs}`);
      if (!d.error) setData(d);
    }
    useEffect(() => { load(); /* eslint-disable-next-line */ }, [q, cat]);

    async function save(v) {
      setBusy(true); setErr("");
      const [, r] = await call("/api/knowledge", { ...v });
      setBusy(false);
      if (r.error) { setErr(r.error); return; }
      setAdding(false); setEditing(null);
      load();
    }
    async function doDelete(entry, confirmed) {
      if (!confirmed) { setConfirmDel(entry ? entry.id : null); return; }
      const [, r] = await call(`/api/knowledge/${encodeURIComponent(entry.id)}`, null, "DELETE");
      setConfirmDel(null);
      if (r.error) { setErr(r.error); return; }
      load();
    }

    const catOptions = [{ value: "", label: "All categories" }, ...data.categories.map(c => ({ value: c, label: c }))];

    return (
      <div>
        <div className="flex items-center gap-2 mb-4">
          <div className="flex items-center gap-2 px-2.5 h-8 bg-bg-elevated rounded-md border border-border focus-within:border-accent">
            {Icons.search && <span className="text-fg-muted"><Icons.search size={12} /></span>}
            <input className="bare text-sm placeholder:text-fg-muted w-64" placeholder="Filter by title / solution / tags…" value={q} onChange={e => setQ(e.target.value)} />
          </div>
          {UiSelect && <UiSelect value={cat} onChange={setCat} placeholder="All categories" size="md" minWidth={180} options={catOptions} />}
          <span className="text-2xs text-fg-muted ml-2">{data.entries.length} of {data.total}</span>
          <button onClick={() => { setAdding(true); setEditing(null); }} className="btn-px btn-px-primary ml-auto">
            {Icons.plus ? <Icons.plus size={12} /> : "+"} Add entry
          </button>
        </div>
        {err && <div className="mb-3 px-3 py-2 rounded-md bg-danger-soft text-danger text-sm">{err}</div>}
        {adding && <KnowledgeEditor onSave={save} onCancel={() => setAdding(false)} saving={busy} />}
        {editing && <KnowledgeEditor initial={editing} onSave={save} onCancel={() => setEditing(null)} saving={busy} />}
        <div className="space-y-1.5">
          {data.entries.length === 0
            ? <div className="text-center py-10 text-sm text-fg-muted">{data.total === 0 ? "No knowledge stored yet." : "No matches for the current filter."}</div>
            : data.entries.map(e => (
                <KnowledgeRow key={e.id} entry={e} onEdit={ev => setEditing(ev)} onDelete={doDelete} confirmingDel={confirmDel === e.id} />
              ))}
        </div>
      </div>
    );
  }

  // ============ Skills Tab (structured frontmatter + body editor) ============
  // SKILL.md files look like:
  //   ---
  //   name: <id>
  //   description: <one-liner>
  //   ---
  //
  //   # Title
  //   …body…
  // Parsing them into separate fields makes the editor easier to use AND keeps
  // the description editable as a real input, not a hand-edited YAML line.
  function parseSkill(text) {
    const m = (text || "").match(/^---\s*\n([\s\S]*?)\n---\s*\n?([\s\S]*)$/);
    if (!m) return { name: "", description: "", body: text || "" };
    const fm = {};
    for (const line of m[1].split("\n")) {
      const idx = line.indexOf(":");
      if (idx > 0) fm[line.slice(0, idx).trim()] = line.slice(idx + 1).trim();
    }
    return { name: fm.name || "", description: fm.description || "", body: (m[2] || "").replace(/^\n+/, "") };
  }
  function buildSkillText(name, description, body) {
    // Escape any : in the description if it would break YAML (rare; we still
    // keep it simple — the server's parser only splits on the first colon).
    return `---\nname: ${name}\ndescription: ${description}\n---\n\n${(body || "").replace(/^\n+/, "")}`;
  }

  function SkillsTab() {
    const Icons = window.Icons || {};
    const [list, setList] = useState([]);
    const [selected, setSelected] = useState(null);   // skill name being edited
    const [adding, setAdding] = useState(false);
    const [draft, setDraft] = useState({ name: "", description: "", body: "" });
    const [pristine, setPristine] = useState({ name: "", description: "", body: "" });
    const [busy, setBusy] = useState(false);
    const [err, setErr] = useState("");
    const [confirmDel, setConfirmDel] = useState(false);
    const dirty = JSON.stringify(draft) !== JSON.stringify(pristine);

    async function loadList() {
      const [, d] = await call("/api/skills");
      if (!d.error) setList(d.skills || []);
    }
    async function loadSkill(name) {
      const [, d] = await call(`/api/skills/${encodeURIComponent(name)}`);
      if (d.error) { setErr(d.error); return; }
      const parsed = parseSkill(d.content || "");
      const v = { name: parsed.name || name, description: parsed.description, body: parsed.body };
      setDraft(v); setPristine(v);
      setSelected(name); setAdding(false); setConfirmDel(false); setErr("");
    }
    useEffect(() => { loadList(); }, []);

    function startAdd() {
      const v = {
        name: "",
        description: "",
        body: "# New Skill\n\n**When to use**: …\n\n## Procedure\n\n1. …\n2. …\n3. …\n\n## Output expectations\n\n- …\n",
      };
      setDraft(v); setPristine({ name: "", description: "", body: "" });   // pristine is empty → dirty=true so Save is enabled
      setAdding(true); setSelected(null); setConfirmDel(false); setErr("");
    }
    async function save() {
      const name = (draft.name || "").trim();
      if (!name) { setErr("name is required"); return; }
      if (!/^[a-z0-9][a-z0-9._-]{0,60}$/.test(name)) {
        setErr("name must be kebab-case (a-z, 0-9, ., _, -; up to 60 chars)"); return;
      }
      const content = buildSkillText(name, draft.description || "", draft.body || "");
      setBusy(true); setErr("");
      const [, r] = await call(`/api/skills/${encodeURIComponent(name)}`, { content });
      setBusy(false);
      if (r.error) { setErr(r.error); return; }
      setPristine(draft);
      setAdding(false); setSelected(name);
      loadList();
    }
    async function doDelete() {
      if (!selected) return;
      const [, r] = await call(`/api/skills/${encodeURIComponent(selected)}`, null, "DELETE");
      if (r.error) { setErr(r.error); return; }
      setSelected(null); setDraft({ name: "", description: "", body: "" }); setPristine({ name: "", description: "", body: "" });
      setConfirmDel(false);
      loadList();
    }

    const editing = adding || selected;
    const set = (k, v) => setDraft(d => ({ ...d, [k]: v }));

    return (
      <div className="grid grid-cols-[280px_1fr] gap-5">
        {/* ===== LEFT: skills list ===== */}
        <aside>
          <div className="flex items-center justify-between mb-2">
            <span className="text-2xs uppercase tracking-wider font-medium text-fg-muted">Skills · {list.length}</span>
            <button onClick={startAdd} className="btn-px btn-px-ghost btn-px-sm">
              {Icons.plus ? <Icons.plus size={12} /> : "+"} New
            </button>
          </div>
          <div className="space-y-1.5">
            {list.length === 0 && <div className="text-2xs text-fg-muted px-2">No skills yet.</div>}
            {list.map(s => {
              const active = selected === s.name && !adding;
              return (
                <button key={s.name} onClick={() => loadSkill(s.name)}
                        className={"w-full text-left p-3 border rounded-md transition-all " +
                                   (active
                                     ? "border-accent bg-accent-soft/40 shadow-sm"
                                     : "border-border bg-bg-elevated hover:border-border-strong hover:bg-bg-hover")}>
                  <div className="flex items-center gap-2 mb-0.5">
                    {Icons.book ? <Icons.book size={12} className="text-fg-muted shrink-0" /> : null}
                    <code className="font-mono text-sm font-semibold text-fg truncate">{s.name}</code>
                  </div>
                  {s.description && <div className="text-2xs text-fg-secondary leading-snug line-clamp-2">{s.description}</div>}
                  <div className="text-2xs text-fg-muted mt-1.5 flex items-center gap-2">
                    <span>{s.lines} lines</span>
                    <span className="text-fg-muted/40">·</span>
                    <span>{fmtRel(s.updated_at)}</span>
                  </div>
                </button>
              );
            })}
          </div>
        </aside>

        {/* ===== RIGHT: editor ===== */}
        <section>
          {!editing ? (
            <div className="text-center py-20 text-sm text-fg-muted border border-border rounded-lg bg-bg-elevated">
              <div className="text-2xl mb-2">📚</div>
              Pick a skill on the left to view or edit, or click <b>+ New</b> to create one.
              <div className="text-2xs text-fg-muted/80 mt-3 max-w-md mx-auto leading-snug">
                Skills are reusable procedures (review checklists, validation playbooks).
                Agents read these on every relevant step, so they shape how the team works.
              </div>
            </div>
          ) : (
            <div className="bg-bg-elevated border border-border rounded-lg overflow-hidden">
              {/* Frontmatter card */}
              <div className="border-b border-border bg-bg-secondary/40">
                <div className="grid grid-cols-[1fr_2fr] gap-4 p-4">
                  <div>
                    <label className="block text-2xs uppercase tracking-wider font-medium text-fg-muted mb-1.5">
                      Name<span className="text-danger ml-0.5">*</span>
                    </label>
                    {adding ? (
                      <input className="input-px w-full font-mono"
                             placeholder="skill-name"
                             value={draft.name}
                             onChange={e => set("name", e.target.value.toLowerCase().replace(/[^a-z0-9._-]/g, ""))} />
                    ) : (
                      <code className="font-mono text-md font-semibold text-fg block leading-9">{draft.name}</code>
                    )}
                    <div className="text-2xs text-fg-muted mt-1 leading-snug">
                      kebab-case identifier
                    </div>
                  </div>
                  <div>
                    <label className="block text-2xs uppercase tracking-wider font-medium text-fg-muted mb-1.5">Description</label>
                    <input className="input-px w-full"
                           placeholder="One-liner shown when an agent picks the skill"
                           value={draft.description}
                           onChange={e => set("description", e.target.value)} />
                    <div className="text-2xs text-fg-muted mt-1 leading-snug">
                      shown in the skills picker and in <code className="font-mono">list_skills()</code>
                    </div>
                  </div>
                </div>
              </div>

              {/* Body editor */}
              <div className="px-4 pt-3 pb-1 flex items-center gap-3 text-2xs text-fg-muted">
                <span className="uppercase tracking-wider font-medium">SKILL.md body</span>
                <span className="text-fg-muted/40">·</span>
                <span>markdown — agents read this verbatim</span>
                <span className="ml-auto tabular-nums">
                  {(draft.body || "").length} chars · {((draft.body || "").match(/\n/g) || []).length + 1} lines
                </span>
              </div>
              <div className="px-4 pb-4">
                <textarea
                  className="w-full font-mono text-sm bg-bg p-3 rounded-md border border-border focus:border-accent focus:outline-none leading-relaxed"
                  rows={24}
                  spellCheck={false}
                  value={draft.body}
                  onChange={e => set("body", e.target.value)}
                  placeholder="# Title\n\n## When to use\n\n…"
                />
              </div>

              {err && <div className="mx-4 mb-3 px-3 py-2 rounded-md bg-danger-soft text-danger text-sm">{err}</div>}

              {/* Actions footer */}
              <div className="border-t border-border bg-bg-secondary/30 px-4 py-3 flex items-center gap-2">
                {!adding && (confirmDel
                  ? (<>
                      <span className="text-2xs text-danger">delete this skill permanently?</span>
                      <button onClick={doDelete} className="btn-px btn-px-danger btn-px-sm">Confirm delete</button>
                      <button onClick={() => setConfirmDel(false)} className="btn-px btn-px-ghost btn-px-sm">Cancel</button>
                    </>)
                  : <button onClick={() => setConfirmDel(true)} className="btn-px btn-px-danger-ghost btn-px-sm">Delete</button>)}
                <span className="ml-auto flex items-center gap-2">
                  {dirty && <span className="text-2xs text-fg-muted">unsaved changes</span>}
                  <button onClick={() => { setAdding(false); setSelected(null); setDraft({ name: "", description: "", body: "" }); setPristine({ name: "", description: "", body: "" }); }}
                          className="btn-px btn-px-ghost">Close</button>
                  <button onClick={save} disabled={busy || !dirty} className="btn-px btn-px-primary">
                    {busy ? "Saving…" : (adding ? "Create skill" : "Save changes")}
                  </button>
                </span>
              </div>
            </div>
          )}
        </section>
      </div>
    );
  }

  // ============ Page shell ============
  function KnowledgePage() {
    const Icons = window.Icons || {};
    const nav = (p) => window.LiveMonitorRouter.navigateTo(p);
    const [tab, setTab] = useState("knowledge");
    return (
      <div className="min-h-screen flex flex-col bg-bg-secondary">
        <header className="h-12 px-6 flex items-center gap-3 border-b border-border bg-bg sticky top-0 z-10">
          <button onClick={() => nav("/")} className="btn-px btn-px-ghost btn-px-sm">{Icons.arrowLeft ? <Icons.arrowLeft size={12} /> : "←"} Home</button>
          <h1 className="text-md font-semibold tracking-tight text-fg">Knowledge & Skills</h1>
          <span className="text-2xs text-fg-muted">host-wide · persists across runs</span>
        </header>
        <div className="page" style={{ maxWidth: 1480 }}>
          <div className="flex items-center gap-1 border-b border-border mb-5">
            {[{k:"knowledge",l:"Knowledge"},{k:"skills",l:"Skills"}].map(t => (
              <button key={t.k} onClick={() => setTab(t.k)}
                      className={"px-3 h-9 text-base font-medium flex items-center gap-2 border-b-2 -mb-px transition-colors " +
                                 (tab === t.k ? "text-fg border-accent" : "text-fg-secondary border-transparent hover:text-fg")}>
                {t.l}
              </button>
            ))}
          </div>
          {tab === "knowledge" ? <KnowledgeTab /> : <SkillsTab />}
        </div>
      </div>
    );
  }
  return KnowledgePage;
})();
