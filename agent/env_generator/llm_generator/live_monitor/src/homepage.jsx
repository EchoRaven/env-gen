// Cutover 43.2: GitHub/Jira-hybrid dense homepage — 3 columns, card-framed sections,
// metric tiles, activity feed, running runs, quick links. Industrial maturity.
const { useEffect, useState, useMemo } = window.React;

function hueFromString(s) {
  let h = 0;
  for (let i = 0; i < (s || "").length; i++) h = ((h << 5) - h + s.charCodeAt(i)) | 0;
  return Math.abs(h) % 360;
}
const LANG_COLORS = {
  python: "#3572A5", typescript: "#3178c6", javascript: "#f1e05a",
  go: "#00ADD8", rust: "#dea584", java: "#b07219", swift: "#F05138",
  ruby: "#701516", html: "#e34c26", shell: "#89e051",
};

// Status color (single source of truth)
const STATUS_TONE = {
  active:    { dot: "var(--success)", text: "text-success" },
  completed: { dot: "var(--info)",    text: "text-info" },
  failed:    { dot: "var(--danger)",  text: "text-danger" },
  paused:    { dot: "var(--warning)", text: "text-warning" },
  archived:  { dot: "var(--text-muted)", text: "text-fg-muted" },
};

function Homepage() {
  const { theme, toggle: toggleTheme } = window.MonitorTheme.useTheme();
  const Icons = window.Icons || {};
  const UiSelect = window.HubUI?.UiSelect;
  const [projects, setProjects] = useState([]);
  const [runs, setRuns] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [filter, setFilter] = useState("all");
  const [query, setQuery] = useState("");
  const [sortBy, setSortBy] = useState("updated");
  const [activity, setActivity] = useState([]);  // last events from /api/events
  // Inline confirm flow (no native popups): { id, action: "archive"|"delete", typed, error, busy }
  const [pending, setPending] = useState(null);

  async function refresh() {
    try {
      const [pr, ru] = await Promise.all([
        fetch("/api/projects", { credentials: "include" }).then(r => r.json()),
        fetch("/api/runs", { credentials: "include" }).then(r => r.json()).catch(() => ({ runs: [] })),
      ]);
      setProjects(pr.projects || []);
      setRuns(ru.runs || []);
      setError(null);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    let alive = true;
    refresh();
    let pollMs = 5000;
    const pick = () => (window.MonitorSSE && window.MonitorSSE.isConnected() ? 30000 : 5000);
    let timer = window.setInterval(function tick() {
      if (!alive) return;
      refresh();
      const next = pick();
      if (next !== pollMs) { window.clearInterval(timer); pollMs = next; timer = window.setInterval(tick, pollMs); }
    }, pollMs);
    return () => { alive = false; window.clearInterval(timer); };
  }, []);

  // SSE for activity feed + project lifecycle refresh
  useEffect(() => {
    let es = null, reconnectTimer = null, backoffMs = 500, closed = false;
    function open() {
      if (closed) return;
      try { es = new EventSource("/api/events"); } catch (_) { return; }
      es.onopen = () => { backoffMs = 500; };
      es.onmessage = (e) => {
        try {
          const ev = JSON.parse(e.data);
          if (ev && ev.event_type) {
            setActivity(prev => [{ ...ev, _at: Date.now() }, ...prev].slice(0, 25));
            const t = ev.event_type;
            if (t === "project_created" || t === "project_deleted" || t === "project_status_changed") refresh();
            if (t === "project_run_started" || t === "project_run_finished") refresh();
          }
        } catch (_) {}
      };
      es.onerror = () => {
        if (es) { try { es.close(); } catch (_) {} es = null; }
        if (closed) return;
        reconnectTimer = window.setTimeout(open, backoffMs);
        backoffMs = Math.min(backoffMs * 2, 30000);
      };
    }
    open();
    return () => { closed = true; if (reconnectTimer) clearTimeout(reconnectTimer); if (es) { try { es.close(); } catch (_) {} } };
  }, []);

  function fmtRel(ts) {
    if (!ts) return "—";
    const diff = Date.now() / 1000 - ts;
    if (diff < 60) return "just now";
    if (diff < 3600) return `${Math.floor(diff/60)}m`;
    if (diff < 86400) return `${Math.floor(diff/3600)}h`;
    if (diff < 86400*7) return `${Math.floor(diff/86400)}d`;
    return new Date(ts*1000).toLocaleDateString(undefined, { month: "short", day: "numeric" });
  }
  function fmtRelMs(ms) { return fmtRel(ms / 1000); }

  // Inline confirm helpers — no native confirm/prompt/alert.
  const askArchive = (pid) => setPending({ id: pid, action: "archive", typed: "", error: null, busy: false });
  const askDelete  = (pid) => setPending({ id: pid, action: "delete",  typed: "", error: null, busy: false });
  const cancelPending = () => setPending(null);

  async function confirmArchive(pid) {
    setPending(p => p ? { ...p, busy: true, error: null } : p);
    try {
      const r = await fetch(`/api/projects/${pid}/status`, {
        method: "POST", headers: { "Content-Type": "application/json" }, credentials: "include",
        body: JSON.stringify({ status: "archived" }),
      });
      const data = await r.json();
      if (data.error) { setPending(p => p ? { ...p, busy: false, error: data.error } : p); return; }
      setPending(null);
      refresh();
    } catch (e) { setPending(p => p ? { ...p, busy: false, error: String(e) } : p); }
  }
  async function confirmDelete(pid, name) {
    setPending(p => p ? { ...p, busy: true, error: null } : p);
    try {
      const r = await fetch(`/api/projects/${pid}`, {
        method: "DELETE", headers: { "Content-Type": "application/json" }, credentials: "include",
        body: JSON.stringify({ confirm: true, confirm_name: name }),
      });
      const data = await r.json();
      if (data.error) { setPending(p => p ? { ...p, busy: false, error: data.error } : p); return; }
      setPending(null);
      refresh();
    } catch (e) { setPending(p => p ? { ...p, busy: false, error: String(e) } : p); }
  }
  async function logout() {
    try { await fetch("/api/auth/logout", { method: "POST", credentials: "include" }); } catch (_) {}
    window.location.reload();
  }

  const counts = useMemo(() => {
    const c = { all: projects.length, active: 0, completed: 0, paused: 0, failed: 0, archived: 0 };
    projects.forEach(p => { if (c[p.status] !== undefined) c[p.status]++; });
    return c;
  }, [projects]);

  const runningRuns = useMemo(() => runs.filter(r => r.state === "running"), [runs]);
  const completedRuns = useMemo(() => runs.filter(r => r.state === "completed"), [runs]);

  const visibleProjects = useMemo(() => {
    let list = projects;
    if (filter !== "all") list = list.filter(p => p.status === filter);
    if (query.trim()) {
      const q = query.trim().toLowerCase();
      list = list.filter(p =>
        (p.name || "").toLowerCase().includes(q) ||
        (p.id || "").toLowerCase().includes(q) ||
        (p.description || "").toLowerCase().includes(q));
    }
    if (sortBy === "updated") list = [...list].sort((a, b) => (b.last_active_at || 0) - (a.last_active_at || 0));
    else if (sortBy === "name") list = [...list].sort((a, b) => (a.name || "").localeCompare(b.name || ""));
    else if (sortBy === "created") list = [...list].sort((a, b) => (b.created_at || 0) - (a.created_at || 0));
    return list;
  }, [projects, filter, query, sortBy]);

  const nav = (p) => window.LiveMonitorRouter.navigateTo(p);
  const projectsById = useMemo(() => Object.fromEntries(projects.map(p => [p.id, p])), [projects]);

  return (
    <div className="min-h-screen flex flex-col bg-bg-secondary">
      {/* ============ TOP BAR ============ */}
      <header className="h-12 px-4 flex items-center gap-4 border-b border-border bg-bg sticky top-0 z-10">
        <div className="flex items-center gap-2 mr-2">
          <span className="w-2.5 h-2.5 rounded-full bg-accent ring-2 ring-accent/20" />
          <span className="text-md font-semibold tracking-tight">env<span className="text-accent">forger</span></span>
        </div>
        <div className="flex-1 max-w-md">
          <div className="flex items-center gap-2 px-2.5 h-8 bg-bg-tertiary rounded-md border border-transparent focus-within:border-accent focus-within:bg-bg-elevated transition-colors">
            {Icons.search && <span className="text-fg-muted shrink-0"><Icons.search size={13} /></span>}
            <input
              className="bare flex-1 text-base placeholder:text-fg-muted"
              placeholder="Find a project, run, or event..."
              value={query} onChange={(e) => setQuery(e.target.value)} />
            {query && <button onClick={() => setQuery("")} className="text-fg-muted hover:text-fg text-base leading-none px-1">×</button>}
          </div>
        </div>
        <div className="flex items-center gap-1">
          <IconButton onClick={toggleTheme} title={theme === "dark" ? "Light mode" : "Dark mode"}>
            {theme === "dark" ? (Icons.sun ? <Icons.sun size={14} /> : "☀") : (Icons.moon ? <Icons.moon size={14} /> : "☾")}
          </IconButton>
          <AuthWidget />
        </div>
      </header>

      {/* ============ BODY: 3-column ============ */}
      <div className="flex-1 flex max-w-[1800px] w-full mx-auto px-8 py-7 gap-6 min-h-0">

        {/* ===== LEFT RAIL ===== */}
        <aside className="w-[232px] shrink-0 flex flex-col gap-5">
          <Card>
            <CardHeader title="Views" />
            <div className="px-2 py-2 space-y-1">
              <RailItem icon={Icons.grid}   label="All projects" active={filter==="all"}       count={counts.all}       onClick={() => setFilter("all")} />
              <RailItem dotColor="var(--success)" label="Active"  active={filter==="active"}    count={counts.active}    onClick={() => setFilter("active")} />
              <RailItem dotColor="var(--info)"    label="Completed" active={filter==="completed"} count={counts.completed} onClick={() => setFilter("completed")} />
              <RailItem dotColor="var(--warning)" label="Paused"   active={filter==="paused"}    count={counts.paused}    onClick={() => setFilter("paused")} />
              <RailItem dotColor="var(--danger)"  label="Failed"   active={filter==="failed"}    count={counts.failed}    onClick={() => setFilter("failed")} />
              <RailItem dotColor="var(--text-muted)" label="Archived" active={filter==="archived"} count={counts.archived} onClick={() => setFilter("archived")} />
            </div>
          </Card>

          <Card>
            <CardHeader title="Quick actions" />
            <div className="px-2 py-2 space-y-1">
              <RailItem icon={Icons.plus} label="New project" onClick={() => nav("/new")} />
              <RailItem icon={Icons.book || Icons.file} label="Knowledge & skills" onClick={() => nav("/knowledge")} />
              <ProjectHubPickerAction
                icon={Icons.grid}
                label="Open project hub"
                projects={projects}
                onPick={(pid, sec) => nav(`/projects/${encodeURIComponent(pid)}/${sec}`)} />
              <ProjectPickerAction
                icon={Icons.chat}
                label="Chat with agents"
                projects={projects}
                onPick={(pid) => nav(`/projects/${encodeURIComponent(pid)}/chat`)} />
              <ProjectPickerAction
                icon={Icons.shield}
                label="Manage gates"
                projects={projects}
                onPick={(pid) => nav(`/projects/${encodeURIComponent(pid)}/gates`)} />
              <ProjectPickerAction
                icon={Icons.file}
                label="Upload references"
                projects={projects}
                onPick={(pid) => nav(`/projects/${encodeURIComponent(pid)}/references`)} />
            </div>
          </Card>

          <Card>
            <CardHeader title="System" />
            <div className="px-4 py-4 space-y-3 text-sm">
              <KV label="Projects" value={counts.all} />
              <KV label="Running" value={runningRuns.length} highlight={runningRuns.length > 0} />
              <KV label="Completed runs" value={completedRuns.length} />
              <KV label="Events seen" value={activity.length} />
            </div>
          </Card>
        </aside>

        {/* ===== MAIN ===== */}
        <main className="flex-1 min-w-0 flex flex-col gap-4">
          {/* Metric tiles */}
          <div className="grid grid-cols-4 gap-3">
            <Metric label="Total projects" value={counts.all} icon={Icons.grid} />
            <Metric label="Active" value={counts.active} icon={Icons.play} tone="success" />
            <Metric label="Runs in flight" value={runningRuns.length} icon={Icons.inbox} tone={runningRuns.length > 0 ? "info" : "neutral"} />
            <Metric label="Failures" value={counts.failed} icon={Icons.shield} tone={counts.failed > 0 ? "danger" : "neutral"} />
          </div>

          {/* Projects card */}
          <Card>
            <CardHeader
              title={filter === "all" ? "Projects" : filter[0].toUpperCase() + filter.slice(1)}
              subtitle={`${visibleProjects.length} ${visibleProjects.length === 1 ? "project" : "projects"}`}
              actions={
                <div className="flex items-center gap-2">
                  {UiSelect ? (
                    <UiSelect
                      value={sortBy}
                      onChange={setSortBy}
                      size="md"
                      minWidth={140}
                      options={[
                        { value: "updated", label: "Last updated" },
                        { value: "name", label: "Name" },
                        { value: "created", label: "Created" },
                      ]}
                    />
                  ) : (
                    <select value={sortBy} onChange={(e) => setSortBy(e.target.value)} className="select-px">
                      <option value="updated">Last updated</option>
                      <option value="name">Name</option>
                      <option value="created">Created</option>
                    </select>
                  )}
                  <Btn variant="primary" onClick={() => nav("/new")}>
                    {Icons.plus ? <Icons.plus size={13} /> : "+"} New project
                  </Btn>
                </div>
              }
            />
            {/* Active filter chip */}
            {query && (
              <div className="px-4 pt-3 -mb-1">
                <span className="inline-flex items-center gap-2 text-xs px-2 py-1 bg-accent-soft text-accent-on-soft rounded-md">
                  search:<code className="font-mono text-xs">{query}</code>
                  <button onClick={() => setQuery("")} className="hover:text-accent leading-none">×</button>
                </span>
              </div>
            )}
            {/* Project list */}
            {loading && <div className="text-center py-10 text-sm text-fg-muted">Loading projects…</div>}
            {error && <div className="text-center py-10 text-sm text-danger">Error: {error}</div>}
            {!loading && !error && visibleProjects.length === 0 && (
              <div className="text-center py-12">
                <div className="text-md text-fg-secondary mb-1">
                  {query ? "No matches" : counts.all === 0 ? "Nothing here yet." : "No projects in this view."}
                </div>
                {counts.all === 0 && !query && (
                  <Btn variant="primary" onClick={() => nav("/new")} className="mt-3">
                    {Icons.plus ? <Icons.plus size={13} /> : "+"} Create your first project
                  </Btn>
                )}
              </div>
            )}
            {!loading && visibleProjects.length > 0 && (
              <ul className="p-3 space-y-2">
                {visibleProjects.map(p => {
                  const pend = pending && pending.id === p.id ? pending : null;
                  const isDelete = pend && pend.action === "delete";
                  const isArchive = pend && pend.action === "archive";
                  const nameOk = isDelete && pend.typed === p.name;
                  return (
                  <li key={p.id}
                      onClick={() => { if (!pend) nav(`/projects/${encodeURIComponent(p.id)}/overview`); }}
                      className={"group relative flex items-center gap-3 px-4 py-3 border rounded-md transition-all "
                        + (pend
                            ? "border-border-strong bg-bg-elevated cursor-default"
                            : "border-border-strong bg-bg-elevated hover:bg-bg-hover hover:shadow-sm cursor-pointer")}>
                    <span className={"absolute left-0 top-0 bottom-0 w-0.5 transition-colors "
                      + (isDelete ? "bg-danger" : "bg-transparent group-hover:bg-accent")} />
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 mb-0.5">
                        <span className="text-md font-semibold tracking-tight text-fg truncate">{p.name || p.id}</span>
                        <StatusInline status={p.status} />
                      </div>
                      {p.description && (
                        <div className="text-sm text-fg-secondary truncate leading-snug mb-1">{p.description}</div>
                      )}
                      <div className="flex items-center gap-3 text-xs text-fg-muted">
                        <span className="inline-flex items-center gap-1.5">
                          <span className="w-2 h-2 rounded-full" style={{ background: LANG_COLORS[(p.lang || "python").toLowerCase()] || "#888" }} />
                          {p.lang || "Python"}
                        </span>
                        <Sep />
                        <code className="font-mono text-xs bg-bg-tertiary text-fg-secondary px-1.5 py-0.5 rounded">{p.id}</code>
                        <Sep />
                        <span>Updated {fmtRel(p.last_active_at)} ago</span>
                      </div>
                      {pend && pend.error && (
                        <div className="mt-2 text-xs text-danger">{isArchive ? "Archive" : "Delete"} failed: {pend.error}</div>
                      )}
                    </div>

                    {/* Budget + gate rings (Claude-Code-style) */}
                    {!pend && <ProjectRing projectId={p.id} />}

                    {/* Default hover actions */}
                    {!pend && (
                      <div className="opacity-0 group-hover:opacity-100 transition-opacity flex items-center gap-1 shrink-0">
                        {p.status !== "archived" && (
                          <Btn variant="ghost" size="sm"
                               onClick={(e) => { e.stopPropagation(); askArchive(p.id); }}>
                            Archive
                          </Btn>
                        )}
                        <Btn variant="danger-ghost" size="sm"
                             onClick={(e) => { e.stopPropagation(); askDelete(p.id); }}>
                          Delete
                        </Btn>
                      </div>
                    )}

                    {/* Inline archive confirm */}
                    {isArchive && (
                      <div className="flex items-center gap-2 shrink-0" onClick={(e) => e.stopPropagation()}>
                        <span className="text-xs text-fg-secondary">Archive this project?</span>
                        <Btn variant="ghost" size="sm" disabled={pend.busy} onClick={cancelPending}>Cancel</Btn>
                        <Btn variant="primary" size="sm" disabled={pend.busy} onClick={() => confirmArchive(p.id)}>
                          {pend.busy ? "Archiving…" : "Confirm archive"}
                        </Btn>
                      </div>
                    )}

                    {/* Inline delete confirm — type-to-confirm */}
                    {isDelete && (
                      <div className="flex items-center gap-2 shrink-0" onClick={(e) => e.stopPropagation()}>
                        <span className="text-xs text-fg-muted">Type <code className="font-mono text-fg-secondary">{p.name}</code> to delete:</span>
                        <input
                          autoFocus
                          value={pend.typed}
                          disabled={pend.busy}
                          placeholder={p.name}
                          onChange={(e) => setPending(x => x ? { ...x, typed: e.target.value } : x)}
                          onKeyDown={(e) => {
                            if (e.key === "Enter" && nameOk && !pend.busy) confirmDelete(p.id, p.name);
                            if (e.key === "Escape") cancelPending();
                          }}
                          className="input-px input-px-danger font-mono"
                          style={{ width: "11rem", height: "28px", fontSize: "12px" }}
                        />
                        <Btn variant="ghost" size="sm" disabled={pend.busy} onClick={cancelPending}>Cancel</Btn>
                        <Btn variant="danger" size="sm" disabled={!nameOk || pend.busy} onClick={() => confirmDelete(p.id, p.name)}>
                          {pend.busy ? "Deleting…" : "Delete"}
                        </Btn>
                      </div>
                    )}
                  </li>
                  );
                })}
              </ul>
            )}
          </Card>
        </main>

        {/* ===== RIGHT RAIL ===== */}
        <aside className="w-[320px] shrink-0 flex flex-col gap-5">
          {/* Running now */}
          <Card>
            <CardHeader title="Running now" badge={runningRuns.length} />
            {runningRuns.length === 0 ? (
              <div className="px-4 py-6 text-center text-xs text-fg-muted">
                No generations in flight.<br />
                <button onClick={() => nav("/new")} className="text-accent hover:underline mt-1">Start one →</button>
              </div>
            ) : (
              <ul className="p-2 space-y-1.5">
                {runningRuns.slice(0, 5).map(r => (
                  <li key={r.run_id}
                      onClick={() => nav(`/projects/${encodeURIComponent(r.project_id)}/runhub`)}
                      className="px-3 py-2 border border-border-strong rounded-md bg-bg-elevated cursor-pointer hover:bg-bg-hover transition-all">
                    <div className="flex items-center gap-2 text-sm text-fg">
                      <span className="w-1.5 h-1.5 rounded-full bg-success animate-pulse" />
                      <span className="font-medium truncate">{projectsById[r.project_id]?.name || r.project_id}</span>
                    </div>
                    <div className="text-2xs text-fg-muted mt-0.5 flex items-center gap-1.5">
                      <code className="font-mono">{r.run_id.substr(0, 10)}</code>
                      <Sep />
                      <span>started {fmtRel(r.started_at)} ago</span>
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </Card>

          {/* Activity feed */}
          <Card>
            <CardHeader title="Activity" subtitle="Live across all projects" />
            {activity.length === 0 ? (
              <div className="px-4 py-6 text-center text-xs text-fg-muted">
                Nothing yet. Events appear here in real time.
              </div>
            ) : (
              <ul className="p-2 space-y-1.5 max-h-[360px] overflow-y-auto">
                {activity.slice(0, 12).map((ev, i) => (
                  <li key={i} className="px-3 py-2 border border-border-strong rounded-md bg-bg-elevated hover:bg-bg-hover transition-all cursor-default">
                    <div className="flex items-center gap-1.5 text-xs">
                      <EventTypeChip type={ev.event_type} />
                      <span className="text-fg-muted text-2xs ml-auto">{fmtRelMs(Date.now() - (Date.now() - ev._at))} ago</span>
                    </div>
                    {ev.project_id && (
                      <div className="text-2xs text-fg-secondary mt-0.5 truncate">
                        {projectsById[ev.project_id]?.name || ev.project_id}
                      </div>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </Card>

        </aside>
      </div>
    </div>
  );
}

// ============ Reusable shell ============
function Card({ children, className = "" }) {
  return (
    <section className={"bg-bg-elevated border border-border rounded-lg overflow-hidden " + className}>
      {children}
    </section>
  );
}
function CardHeader({ title, subtitle, badge, actions }) {
  return (
    <header className="flex items-center gap-3 px-4 h-11 border-b border-border">
      <h3 className="text-md font-semibold tracking-tight text-fg">{title}</h3>
      {badge !== undefined && (
        <span className="inline-flex items-center justify-center min-w-[20px] h-5 px-1.5 text-2xs font-semibold rounded-full bg-bg-tertiary text-fg-secondary tabular-nums">
          {badge}
        </span>
      )}
      {subtitle && <span className="text-sm text-fg-muted tabular-nums">{subtitle}</span>}
      {actions && <div className="ml-auto">{actions}</div>}
    </header>
  );
}

// ============ Reusable atoms ============
function Btn({ children, variant = "ghost", size = "md", onClick, disabled, className = "" }) {
  // Premium button system — see .btn-px* in design-tokens.css
  const sizeCls = size === "sm" ? "btn-px-sm" : size === "lg" ? "btn-px-lg" : "";
  const variantCls =
    variant === "primary" ? "btn-px-primary" :
    variant === "danger" ? "btn-px-danger" :
    variant === "danger-ghost" ? "btn-px-danger-ghost" :
    "btn-px-ghost";
  return (
    <button onClick={onClick} disabled={disabled}
            className={["btn-px", variantCls, sizeCls, className].join(" ")}>
      {children}
    </button>
  );
}

function IconButton({ children, onClick, title }) {
  return (
    <button onClick={onClick} title={title} className="btn-icon">
      {children}
    </button>
  );
}

// Optional sign-in: login is not required (guest works), but signing in as an
// admin unlocks unlimited run budget. Shows a sign-in popover for guests, and
// "username · role" + logout once signed in.
function AuthWidget() {
  const Icons = window.Icons || {};
  const [me, setMe] = useState(null);            // { username, role }
  const [open, setOpen] = useState(false);
  const [u, setU] = useState("");
  const [p, setP] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  async function loadMe() {
    try {
      const r = await fetch("/api/auth/me", { credentials: "include" });
      setMe(await r.json());
    } catch (_) {}
  }
  useEffect(() => { loadMe(); }, []);

  const role = me && me.role;
  const signedIn = role && role !== "guest";

  async function doLogin() {
    setBusy(true); setErr("");
    try {
      const r = await fetch("/api/auth/login", {
        method: "POST", headers: { "Content-Type": "application/json" }, credentials: "include",
        body: JSON.stringify({ username: u.trim(), password: p }),
      });
      const d = await r.json();
      if (d.error) { setErr(d.error); setBusy(false); return; }
      setOpen(false); setU(""); setP(""); setBusy(false);
      window.location.reload();  // re-fetch /me everywhere with the new session
    } catch (e) { setErr(String(e)); setBusy(false); }
  }
  async function doLogout() {
    try { await fetch("/api/auth/logout", { method: "POST", credentials: "include" }); } catch (_) {}
    window.location.reload();
  }

  if (signedIn) {
    return (
      <div className="flex items-center gap-2 pl-1">
        <span className="inline-flex items-center gap-1.5 text-xs text-fg-secondary">
          <span className="font-medium text-fg">{me.username}</span>
          <span className={"px-1.5 py-0.5 rounded text-2xs font-semibold " +
            (role === "admin" ? "bg-accent-soft text-accent-on-soft" : "bg-bg-tertiary text-fg-muted")}>
            {role}
          </span>
        </span>
        <IconButton onClick={doLogout} title="Sign out">
          {Icons.logout ? <Icons.logout size={14} /> : "⎋"}
        </IconButton>
      </div>
    );
  }

  return (
    <div className="relative">
      <button onClick={() => setOpen(o => !o)}
              className="btn-px btn-px-ghost btn-px-sm">Sign in</button>
      {open && (
        <div className="absolute right-0 mt-2 w-64 bg-bg-elevated border border-border rounded-lg p-3 z-50"
             style={{ boxShadow: "0 8px 28px rgba(0,0,0,0.18)" }}>
          <div className="text-xs text-fg-muted mb-2">Sign in for admin (unlimited run budget). Guests can still use everything else.</div>
          <input autoFocus value={u} onChange={e => setU(e.target.value)} placeholder="username"
                 className="input-px w-full mb-2" style={{ height: "30px", fontSize: "12px" }} />
          <input type="password" value={p} onChange={e => setP(e.target.value)} placeholder="password"
                 onKeyDown={e => { if (e.key === "Enter" && u.trim() && p) doLogin(); }}
                 className="input-px w-full mb-2" style={{ height: "30px", fontSize: "12px" }} />
          {err && <div className="text-2xs text-danger mb-2">{err}</div>}
          <div className="flex items-center gap-2 justify-end">
            <button onClick={() => { setOpen(false); setErr(""); }} className="btn-px btn-px-ghost btn-px-sm">Cancel</button>
            <button onClick={doLogin} disabled={busy || !u.trim() || !p} className="btn-px btn-px-primary btn-px-sm">
              {busy ? "…" : "Sign in"}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

// Cutover 43.8: inline project picker for workspace-scoped quick actions.
// Clicking the rail item expands to show a project list; clicking a project navigates.
function ProjectPickerAction({ icon: Icon, label, projects, onPick }) {
  const [open, setOpen] = useState(false);
  const [filter, setFilter] = useState("");
  const filtered = useMemo(() => {
    const list = projects.filter(p => p.status !== "archived");
    if (!filter.trim()) return list;
    const q = filter.trim().toLowerCase();
    return list.filter(p =>
      (p.name || "").toLowerCase().includes(q) ||
      (p.id || "").toLowerCase().includes(q));
  }, [projects, filter]);
  function pick(pid) {
    setOpen(false); setFilter("");
    onPick(pid);
  }
  return (
    <div>
      <button onClick={() => setOpen(o => !o)}
              className={"w-full flex items-center gap-2.5 px-2 py-2 rounded-md text-sm transition-colors " +
                         (open ? "bg-bg-tertiary text-fg font-medium" : "text-fg-secondary hover:text-fg hover:bg-bg-hover")}>
        {Icon ? <span className="text-fg-muted"><Icon size={14} /></span> : <span className="w-3.5 h-3.5" />}
        <span className="flex-1 text-left">{label}</span>
        <span className="text-fg-muted text-2xs">{open ? "▼" : "›"}</span>
      </button>
      {open && (
        <div className="mt-1.5 mx-1 border border-border rounded-md bg-bg-secondary overflow-hidden">
          {projects.length === 0 ? (
            <div className="px-3 py-3 text-xs text-fg-muted">No projects yet.</div>
          ) : (
            <>
              <div className="px-2 py-1.5 border-b border-border">
                <input className="bare w-full text-xs placeholder:text-fg-muted px-1.5 py-1"
                       placeholder="Filter projects..." value={filter}
                       onChange={e => setFilter(e.target.value)} autoFocus />
              </div>
              {filtered.length === 0 ? (
                <div className="px-3 py-2 text-xs text-fg-muted">No matches.</div>
              ) : (
                <div className="max-h-48 overflow-y-auto">
                  {filtered.slice(0, 12).map(p => (
                    <button key={p.id} onClick={() => pick(p.id)}
                            className="w-full flex items-center gap-2 px-2.5 py-1.5 hover:bg-bg-hover text-left transition-colors">
                      <span className="w-1.5 h-1.5 rounded-full shrink-0"
                            style={{ background: p.status === "active" ? "var(--success)" : "var(--text-muted)" }} />
                      <span className="text-xs text-fg truncate flex-1">{p.name || p.id}</span>
                    </button>
                  ))}
                  {filtered.length > 12 && (
                    <div className="px-2.5 py-1 text-2xs text-fg-muted text-center">+ {filtered.length - 12} more</div>
                  )}
                </div>
              )}
            </>
          )}
        </div>
      )}
    </div>
  );
}

// Sections a project can open — used by the 2-level "Open project hub" picker.
const PROJECT_SECTIONS = [
  { id: "overview", label: "Overview", icon: "home" },
  { id: "codehub", label: "CodeHub", icon: "code" },
  { id: "registryhub", label: "RegistryHub", icon: "api" },
  { id: "workhub", label: "WorkHub", icon: "workhub" },
  { id: "eventhub", label: "EventHub", icon: "inbox" },
  { id: "runhub", label: "RunHub", icon: "play" },
  { id: "chat", label: "Chat", icon: "chat" },
  { id: "references", label: "References", icon: "file" },
  { id: "gates", label: "Gates", icon: "shield" },
];

// 2-level picker: pick a project, it expands a grid of its sections (hubs +
// chat/references/gates); pick one to jump straight there.
function ProjectHubPickerAction({ icon: Icon, label, projects, onPick }) {
  const Icons = window.Icons || {};
  const [open, setOpen] = useState(false);
  const [sel, setSel] = useState(null);
  const [filter, setFilter] = useState("");
  const list = useMemo(() => {
    const l = projects.filter(p => p.status !== "archived");
    const q = filter.trim().toLowerCase();
    return q ? l.filter(p => (p.name || "").toLowerCase().includes(q) || (p.id || "").toLowerCase().includes(q)) : l;
  }, [projects, filter]);
  return (
    <div>
      <button onClick={() => { setOpen(o => !o); setSel(null); }}
              className={"w-full flex items-center gap-2.5 px-2 py-2 rounded-md text-sm transition-colors " +
                         (open ? "bg-bg-tertiary text-fg font-medium" : "text-fg-secondary hover:text-fg hover:bg-bg-hover")}>
        {Icon ? <span className="text-fg-muted"><Icon size={14} /></span> : <span className="w-3.5 h-3.5" />}
        <span className="flex-1 text-left">{label}</span>
        <span className="text-fg-muted text-2xs">{open ? "▼" : "›"}</span>
      </button>
      {open && (
        <div className="mt-1.5 mx-1 border border-border rounded-md bg-bg-secondary overflow-hidden">
          {projects.length === 0 ? (
            <div className="px-3 py-3 text-xs text-fg-muted">No projects yet.</div>
          ) : (
            <>
              <div className="px-2 py-1.5 border-b border-border">
                <input className="bare w-full text-xs placeholder:text-fg-muted px-1.5 py-1"
                       placeholder="Filter projects..." value={filter} onChange={e => setFilter(e.target.value)} />
              </div>
              <div className="max-h-60 overflow-y-auto">
                {list.slice(0, 12).map(p => (
                  <div key={p.id} className="border-b border-border last:border-0">
                    <button onClick={() => setSel(s => s === p.id ? null : p.id)}
                            className="w-full flex items-center gap-2 px-2.5 py-1.5 hover:bg-bg-hover text-left transition-colors">
                      <span className="w-1.5 h-1.5 rounded-full shrink-0"
                            style={{ background: p.status === "active" ? "var(--success)" : "var(--text-muted)" }} />
                      <span className="text-xs text-fg truncate flex-1">{p.name || p.id}</span>
                      <span className="text-fg-muted text-2xs">{sel === p.id ? "▾" : "›"}</span>
                    </button>
                    {sel === p.id && (
                      <div className="grid grid-cols-3 gap-1 px-2 pb-2 pt-0.5">
                        {PROJECT_SECTIONS.map(s => {
                          const SI = Icons[s.icon];
                          return (
                            <button key={s.id} onClick={() => { setOpen(false); setSel(null); onPick(p.id, s.id); }}
                                    title={s.label}
                                    className="flex flex-col items-center gap-1 py-1.5 rounded-md text-fg-secondary hover:text-fg hover:bg-bg-hover transition-colors">
                              {SI ? <SI size={13} /> : <span className="w-3 h-3" />}
                              <span style={{ fontSize: "10px", lineHeight: 1 }}>{s.label}</span>
                            </button>
                          );
                        })}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </>
          )}
        </div>
      )}
    </div>
  );
}

// Claude-Code-style dual ring on each project card: outer arc = run-budget used,
// inner arc = delivery gates passing. Fetches both light endpoints per project.
function ProjectRing({ projectId }) {
  const [bud, setBud] = useState(null);
  const [gates, setGates] = useState(null);
  useEffect(() => {
    let alive = true;
    Promise.all([
      fetch(`/api/projects/${encodeURIComponent(projectId)}/run_budget`, { credentials: "include" }).then(r => r.json()).catch(() => null),
      fetch(`/api/projects/${encodeURIComponent(projectId)}/user_gates`, { credentials: "include" }).then(r => r.json()).catch(() => null),
    ]).then(([b, g]) => { if (alive) { setBud(b); setGates(g); } });
    return () => { alive = false; };
  }, [projectId]);

  const caps = (bud && bud.caps) || {};
  const usage = (bud && bud.usage) || {};
  const unlimited = !!caps.unlimited;
  const wall = caps.max_wall_sec ? Math.min(1, (usage.elapsed_sec || 0) / caps.max_wall_sec) : 0;
  const ticks = caps.max_ticks ? Math.min(1, (usage.ticks || 0) / caps.max_ticks) : 0;
  const budPct = Math.max(wall, ticks);
  const hasBudget = unlimited || (bud && bud.present) || (usage.status && usage.status !== "idle");

  const list = (gates && gates.gates) || [];
  const total = list.length;
  const passed = list.filter(x => x.status && x.status.passed).length;
  const gatePct = total > 0 ? passed / total : null;

  const R1 = 17, R2 = 11, SW = 3.5;
  const C1 = 2 * Math.PI * R1, C2 = 2 * Math.PI * R2;
  const budColor = unlimited ? "var(--accent)" : (budPct >= 0.9 ? "var(--danger)" : budPct >= 0.7 ? "var(--warning)" : "var(--accent)");
  const gateColor = gatePct == null ? "var(--border-strong)" : (passed === total ? "var(--success)" : "var(--warning)");
  const title = [
    unlimited ? "Budget: unlimited (admin)" : (hasBudget ? `Budget used: ${Math.round(budPct * 100)}%` : "Budget: idle"),
    total > 0 ? `Gates: ${passed}/${total} passing` : "Gates: none",
  ].join("  ·  ");

  return (
    <div className="shrink-0 flex items-center gap-2.5" title={title} onClick={e => e.stopPropagation()}>
      <div className="text-2xs leading-tight space-y-0.5">
        <div className="flex items-center gap-1.5 justify-end">
          <span className="w-1.5 h-1.5 rounded-full" style={{ background: budColor }} />
          <span className="text-fg-muted tabular-nums">{unlimited ? "∞" : hasBudget ? `${Math.round(budPct * 100)}%` : "—"}</span>
        </div>
        <div className="flex items-center gap-1.5 justify-end">
          <span className="w-1.5 h-1.5 rounded-full" style={{ background: gateColor }} />
          <span className="text-fg-muted tabular-nums">{total > 0 ? `${passed}/${total}` : "—"}</span>
        </div>
      </div>
      <svg width="44" height="44" viewBox="0 0 44 44" style={{ transform: "rotate(-90deg)" }}>
        <circle cx="22" cy="22" r={R1} fill="none" stroke="var(--bg-tertiary)" strokeWidth={SW} />
        <circle cx="22" cy="22" r={R2} fill="none" stroke="var(--bg-tertiary)" strokeWidth={SW} />
        {hasBudget && (
          <circle cx="22" cy="22" r={R1} fill="none" stroke={budColor} strokeWidth={SW} strokeLinecap="round"
                  strokeDasharray={`${(unlimited ? 1 : budPct) * C1} ${C1}`} />
        )}
        {gatePct != null && (
          <circle cx="22" cy="22" r={R2} fill="none" stroke={gateColor} strokeWidth={SW} strokeLinecap="round"
                  strokeDasharray={`${gatePct * C2} ${C2}`} />
        )}
      </svg>
    </div>
  );
}

function RailItem({ icon: Icon, label, active, count, onClick, dotColor }) {
  return (
    <button onClick={onClick}
            className={"w-full flex items-center gap-2.5 px-2 py-2 rounded-md text-sm transition-colors " +
                       (active ? "bg-accent-soft text-accent-on-soft font-medium" : "text-fg-secondary hover:text-fg hover:bg-bg-hover")}>
      {dotColor ? <span className="w-1.5 h-1.5 rounded-full shrink-0" style={{ background: dotColor }} /> :
        Icon ? <span className="text-fg-muted"><Icon size={14} /></span> : <span className="w-3.5 h-3.5" />}
      <span className="flex-1 text-left truncate">{label}</span>
      {count !== undefined && (
        <span className={"text-xs tabular-nums px-1.5 rounded " + (active ? "text-accent-on-soft" : "text-fg-muted")}>
          {count}
        </span>
      )}
    </button>
  );
}

function Metric({ label, value, icon: Icon, tone = "neutral" }) {
  const tones = {
    neutral: "text-fg",
    success: "text-success",
    info: "text-info",
    danger: "text-danger",
  };
  return (
    <div className="bg-bg-elevated border border-border rounded-lg px-4 py-3 transition-colors hover:border-border-strong">
      <div className="flex items-center justify-between mb-1.5">
        <span className="text-xs uppercase tracking-wider font-medium text-fg-muted">{label}</span>
        {Icon && <span className="text-fg-muted opacity-60"><Icon size={14} /></span>}
      </div>
      <div className={"text-3xl font-semibold tabular-nums tracking-tight " + tones[tone]}>{value}</div>
    </div>
  );
}

function StatusInline({ status }) {
  const tone = STATUS_TONE[status] || STATUS_TONE.archived;
  return (
    <span className={"inline-flex items-center gap-1.5 text-xs font-medium " + tone.text}>
      <span className="w-1.5 h-1.5 rounded-full" style={{ background: tone.dot }} />
      {status}
    </span>
  );
}

function Sep() { return <span className="text-fg-muted/40">·</span>; }

function KV({ label, value, highlight }) {
  return (
    <div className="flex items-center justify-between">
      <span className="text-fg-secondary text-sm">{label}</span>
      <span className={"tabular-nums text-md font-semibold " + (highlight ? "text-accent" : "text-fg")}>{value}</span>
    </div>
  );
}

function EventTypeChip({ type }) {
  const KIND_TONE = {
    project_created: "text-success",
    project_deleted: "text-danger",
    project_status_changed: "text-info",
    project_run_started: "text-info",
    project_run_finished: "text-success",
    deliverability_bypass: "text-warning",
    task_created: "text-fg-secondary",
    commit: "text-fg-secondary",
    review_submitted: "text-info",
    human_message: "text-accent",
    agent_reply: "text-success",
  };
  const cls = KIND_TONE[type] || "text-fg-secondary";
  return <span className={"font-mono text-2xs font-medium " + cls}>{type}</span>;
}

function QuickLink({ href, icon: Icon, label, sub, external }) {
  return (
    <a href={href} target={external ? "_blank" : undefined} rel={external ? "noopener noreferrer" : undefined}
       className="flex items-start gap-2.5 px-2 py-1.5 rounded-md hover:bg-bg-hover transition-colors group">
      <span className="text-fg-muted mt-0.5 shrink-0 group-hover:text-accent transition-colors">
        {Icon ? <Icon size={14} /> : "→"}
      </span>
      <div className="flex-1 min-w-0">
        <div className="text-sm text-fg font-medium truncate">{label}{external && <span className="text-fg-muted ml-1">↗</span>}</div>
        <div className="text-2xs text-fg-muted truncate">{sub}</div>
      </div>
    </a>
  );
}

window.LiveMonitorHomepage = Homepage;
