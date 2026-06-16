window.CrossCuttingPages = (function () {
  const { useEffect, useState, useRef, useMemo } = React;

  function PageHero({ title, subtitle, actions }) {
    return (
      <div className="page-hero">
        <div className="page-hero-meta">
          <h1 className="page-hero-title">{title}</h1>
          {subtitle && <p className="page-hero-subtitle">{subtitle}</p>}
        </div>
        {actions && <div className="page-hero-actions">{actions}</div>}
      </div>
    );
  }

  // ------------------------- Overview -------------------------
  // ===========================================================================
  // Cutover 43.4: Overview redesign — live agent grid + activity stream + metrics
  // Bringing back the energy of the old CRDT-era MainDashboard:
  // pulse rings, per-agent action animations, real-time updates.
  // ===========================================================================
  function MilestoneStrip({ ms }) {
    const list = ms?.milestones || [];
    if (!list.length) return null;
    const tone = { released: "#10b981", active: "#f59e0b", planned: "#475569" };
    const label = { released: "released", active: "in progress", planned: "planned" };
    const pct = ms.total ? Math.round((ms.released_count / ms.total) * 100) : 0;
    return (
      <section className="bg-bg-elevated border border-border rounded-lg mb-5 px-4 py-3">
        <header className="flex items-center gap-3 mb-2.5">
          <h3 className="text-md font-semibold tracking-tight">Milestone roadmap</h3>
          <span className="text-sm text-fg-muted">
            {ms.released_count}/{ms.total} released
            {ms.source === "agent_planned" ? " · agent-planned" : ""}
          </span>
          <div className="ml-auto w-40 h-1.5 rounded-full bg-border overflow-hidden">
            <div style={{ width: pct + "%", background: "#10b981", height: "100%" }} />
          </div>
        </header>
        <div className="flex items-stretch gap-2 overflow-x-auto">
          {list.map((m, i) => (
            <React.Fragment key={m.index}>
              <div className="flex-1 min-w-[150px] rounded-md border px-3 py-2"
                   style={{ borderColor: tone[m.status], opacity: m.status === "planned" ? 0.65 : 1 }}>
                <div className="flex items-center gap-2">
                  <span className="w-2 h-2 rounded-full"
                        style={{ background: tone[m.status],
                                 animation: m.status === "active" ? "pulse 1.6s infinite" : "none" }} />
                  <span className="text-sm font-semibold truncate">{m.name}</span>
                </div>
                <div className="text-2xs text-fg-muted mt-1">
                  v{m.version} · {label[m.status]}
                  {m.released_at ? " · " + new Date(m.released_at * 1000).toLocaleTimeString() : ""}
                </div>
              </div>
              {i < list.length - 1 && (
                <div className="self-center text-fg-muted" style={{ fontSize: "11px" }}>→</div>
              )}
            </React.Fragment>
          ))}
        </div>
      </section>
    );
  }

  function OverviewPage({ projectId, state }) {
    const hubs = state?.hubs || {};
    const ch = hubs.codehub || {};
    const ah = hubs.registryhub || {};
    const wh = hubs.workhub || {};
    const eh = hubs.eventhub || {};
    const rh = hubs.runhub || {};
    const tasks = Object.values(wh.tasks || {});

    // Fetch agent profiles from the registry. Overview shows ONLY core/named
    // agents — the dynamic workers (analysis_worker, review_worker, "worker")
    // are spawned ad-hoc by orchestrators and would clutter the grid.
    const [allAgents, setAllAgents] = useState([]);
    useEffect(() => {
      fetch(`/api/projects/${encodeURIComponent(projectId)}/agents`, { credentials: "include" })
        .then(r => r.json()).then(d => setAllAgents(d.agents || [])).catch(() => {});
    }, [projectId]);
    const isWorker = (id) => id === "worker" || /(^|_)worker(_|$)/i.test(id);
    const agents = useMemo(() => allAgents.filter(a => !isWorker(a.id)), [allAgents]);

    const events = Object.values(eh.events || {})
      .sort((a, b) => (b.created_at || 0) - (a.created_at || 0));
    const recentEvents = events.slice(0, 30);

    // Compute per-agent activity from EventHub events. The ACTING agent lives in
    // the event payload (agent_id / assignee / …), NOT in source_hub — that's the
    // hub that emitted the event. agent_status events also carry focus_hub +
    // status, which drive the hub animation. (We intentionally don't use
    // state.toolCalls here: those timestamps are ISO strings, not epoch seconds,
    // so the recency math broke and agents never lit up.)
    const agentActivity = useMemo(() => {
      const map = {};
      const now = Date.now() / 1000;
      const agentIds = new Set(agents.map(a => a.id));
      const ensure = (aid) => (map[aid] || (map[aid] = {
        lastEventAt: 0, lastAction: "idle", lastEventType: null,
        eventCount: 0, focusHub: null, status: null,
      }));
      events.forEach(e => {
        const p = e.payload || {};
        let aid = p.agent_id || p.assignee || p.claimed_by || p.author || p._updated_by || e.agent || null;
        if (!aid && agentIds.has(e.source_hub)) aid = e.source_hub;
        if (!aid || !agentIds.has(aid)) return;
        const rec = ensure(aid);
        rec.eventCount += 1;
        const ts = Number(e.created_at) || 0;
        if (ts >= rec.lastEventAt) {
          rec.lastEventAt = ts;
          rec.lastEventType = e.event_type;
          rec.lastAction = classifyEventToAction(e.event_type);
          if (p.focus_hub) rec.focusHub = p.focus_hub;
          if (e.event_type === "agent_status" && p.status) rec.status = p.status;
        }
      });
      // Active = emitted an event within the last 90s (and not explicitly idle).
      Object.values(map).forEach(rec => {
        const fresh = rec.lastEventAt > 0 && (now - rec.lastEventAt) < 90;
        rec.active = fresh && rec.status !== "idle";
        rec.recent = rec.lastEventAt > 0 && (now - rec.lastEventAt) < 600;
        if (fresh && rec.status === "idle") rec.lastAction = "thinking";
      });
      return map;
    }, [events, agents]);

    // Hub metric values
    const metrics = [
      { label: "Tasks", value: tasks.length, sub: tasks.filter(t => t.status === "completed").length + " completed", icon: window.Icons?.workhub, hub: "workhub", tone: "info" },
      { label: "Registry Endpoints", value: Object.keys(ah.endpoints || {}).length, sub: Object.keys(ah.tables || {}).length + " tables", icon: window.Icons?.api, hub: "registryhub", tone: "info" },
      { label: "Events", value: events.length, sub: Object.keys(eh.threads || {}).length + " threads", icon: window.Icons?.inbox, hub: "eventhub", tone: "neutral" },
      { label: "Runs", value: Object.keys(rh.runs || {}).length, sub: Object.values(rh.runs || {}).filter(r => r.status === "completed").length + " passed", icon: window.Icons?.play, hub: "runhub", tone: Object.values(rh.runs || {}).some(r => r.fail_count > 0) ? "danger" : "neutral" },
      { label: "Pull requests", value: Object.keys(ch.pull_requests || {}).length, sub: Object.values(ch.pull_requests || {}).filter(p => p.merge_state === "merged").length + " merged", icon: window.Icons?.code, hub: "codehub", tone: "info" },
    ];

    // Active count restricted to core agents (workers filtered out above)
    const coreIds = new Set(agents.map(a => a.id));
    const activeAgentCount = Object.entries(agentActivity)
      .filter(([id, rec]) => rec.active && coreIds.has(id)).length;
    const totalAgents = agents.length || 10;

    return (
      <div className="page" style={{ maxWidth: "1480px" }}>
        {/* ============ HERO ============ */}
        <ProjectHero state={state} projectId={projectId} activeAgents={activeAgentCount} totalAgents={totalAgents} />

        {/* ============ MILESTONE ROADMAP ============ */}
        <MilestoneStrip ms={state?.milestones} />

        {/* ============ METRIC TILES ============ */}
        <div className="grid grid-cols-5 gap-3 mb-5">
          {metrics.map(m => (
            <OverviewMetric key={m.label} {...m} projectId={projectId} />
          ))}
        </div>

        {/* ============ RUN BUDGET ============ */}
        <RunBudgetCard projectId={projectId} />

        {/* ============ 2-column: Agents grid + Activity stream ============ */}
        <div className="grid grid-cols-[1fr_320px] gap-5 mb-5">
          {/* Live agent grid */}
          <section className="bg-bg-elevated border border-border rounded-lg overflow-hidden">
            <header className="px-4 h-11 flex items-center gap-3 border-b border-border">
              <h3 className="text-md font-semibold tracking-tight">Live agent activity</h3>
              <span className="text-sm text-fg-muted">{activeAgentCount}/{agents.length || 10} active</span>
              <span className="ml-auto text-2xs uppercase tracking-wider font-medium text-fg-muted flex items-center gap-1.5">
                <span className="w-1.5 h-1.5 rounded-full bg-success animate-pulse" />
                live
              </span>
            </header>
            <div className="p-4 grid grid-cols-3 lg:grid-cols-4 gap-3">
              {agents.length === 0 ? (
                <div className="col-span-full text-center py-8 text-sm text-fg-muted">Loading agents…</div>
              ) : agents.map(agent => (
                <AgentCard key={agent.id} agent={agent} activity={agentActivity[agent.id]} />
              ))}
            </div>
          </section>

          {/* Activity stream */}
          <section className="bg-bg-elevated border border-border rounded-lg overflow-hidden flex flex-col">
            <header className="px-4 h-11 flex items-center gap-3 border-b border-border shrink-0">
              <h3 className="text-md font-semibold tracking-tight">Activity</h3>
              <span className="ml-auto text-2xs uppercase tracking-wider font-medium text-fg-muted flex items-center gap-1.5">
                <span className="w-1.5 h-1.5 rounded-full bg-info live-dot" />
                last {recentEvents.length}
              </span>
            </header>
            <div className="overflow-y-auto max-h-[560px] p-2 space-y-1.5">
              {recentEvents.length === 0 ? (
                <div className="text-center py-10 text-sm text-fg-muted">No events yet.</div>
              ) : recentEvents.map((e, i) => (
                <ActivityRow key={e.id || i} event={e} index={i} />
              ))}
            </div>
          </section>
        </div>

        {/* ============ Task progress + Hub deltas ============ */}
        <div className="grid grid-cols-2 gap-5">
          <TaskProgressCard tasks={tasks} />
          <HubDeltasCard hubs={hubs} />
        </div>
      </div>
    );
  }

  // ============ Sub-components ============

  // ============ Run budget — usage vs cap + raise control (Claude-Code-style) ============
  function RunBudgetCard({ projectId }) {
    const [data, setData] = useState(null);
    const [editing, setEditing] = useState(false);
    const [wallMin, setWallMin] = useState("");
    const [ticks, setTicks] = useState("");
    const [saving, setSaving] = useState(false);
    const [err, setErr] = useState("");

    async function load() {
      try {
        const r = await fetch(`/api/projects/${encodeURIComponent(projectId)}/run_budget`, { credentials: "include" });
        const d = await r.json();
        if (!d.error) setData(d);
      } catch (_) {}
    }
    useEffect(() => {
      load();
      const t = setInterval(load, 8000);  // refresh while a run is active
      return () => clearInterval(t);
    }, [projectId]);

    if (!data) return null;
    const caps = data.caps || {};
    const usage = data.usage || {};
    const status = usage.status || "idle";
    const wallCap = Number(caps.max_wall_sec || 0);
    const wallUsed = Number(usage.elapsed_sec || 0);
    const tickCap = Number(caps.max_ticks || 0);
    const tickUsed = Number(usage.ticks || 0);
    const wallPct = wallCap > 0 ? Math.min(100, (wallUsed / wallCap) * 100) : 0;
    const tickPct = tickCap > 0 ? Math.min(100, (tickUsed / tickCap) * 100) : 0;
    const exceeded = status === "budget_exceeded";
    const running = status === "running";
    const unlimited = !!caps.unlimited;

    const fmtDur = (s) => {
      s = Math.max(0, Math.round(s));
      const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = s % 60;
      return h > 0 ? `${h}h ${m}m` : m > 0 ? `${m}m ${sec}s` : `${sec}s`;
    };
    const STATUS = {
      running: { label: "Running", cls: "text-success", dot: "var(--success)" },
      delivered: { label: "Delivered", cls: "text-info", dot: "var(--info)" },
      budget_exceeded: { label: "Budget exceeded", cls: "text-danger", dot: "var(--danger)" },
      idle: { label: "No active run", cls: "text-fg-muted", dot: "var(--text-muted)" },
    }[status] || { label: status, cls: "text-fg-muted", dot: "var(--text-muted)" };

    function startEdit() {
      setWallMin(String(Math.round(wallCap / 60)));
      setTicks(String(tickCap));
      setErr(""); setEditing(true);
    }
    async function save() {
      setSaving(true); setErr("");
      try {
        const body = {};
        if (wallMin !== "") body.max_wall_sec = Math.max(60, Math.round(Number(wallMin) * 60));
        if (ticks !== "") body.max_ticks = Math.max(1, Math.round(Number(ticks)));
        const r = await fetch(`/api/projects/${encodeURIComponent(projectId)}/run_budget`, {
          method: "POST", headers: { "Content-Type": "application/json" }, credentials: "include",
          body: JSON.stringify(body),
        });
        const d = await r.json();
        if (d.error) { setErr(d.error); setSaving(false); return; }
        setEditing(false); setSaving(false); load();
      } catch (e) { setErr(String(e)); setSaving(false); }
    }

    const Bar = ({ pct, tone }) => (
      <div className="h-1.5 rounded-full bg-bg-tertiary overflow-hidden">
        <div className="h-full rounded-full transition-all"
             style={{ width: `${pct}%`, background: tone }} />
      </div>
    );
    const barTone = (pct) => pct >= 90 ? "var(--danger)" : pct >= 70 ? "var(--warning)" : "var(--accent)";

    return (
      <div className={"bg-bg-elevated border rounded-lg p-4 mb-5 " + (exceeded ? "border-danger" : "border-border")}>
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-2">
            <span className="text-sm font-semibold tracking-tight text-fg">Run budget</span>
            <span className={"inline-flex items-center gap-1.5 text-2xs " + STATUS.cls}>
              <span className="w-1.5 h-1.5 rounded-full" style={{ background: STATUS.dot }} />
              {STATUS.label}
            </span>
          </div>
          {!editing && !unlimited && (
            <button onClick={startEdit} className="text-xs text-accent hover:underline">
              {exceeded ? "Raise cap to resume" : "Adjust caps"}
            </button>
          )}
        </div>

        {exceeded && (
          <div className="mb-3 text-xs text-danger">
            This run hit its budget and stopped. Raise a cap below — the orchestrator picks it up within a tick.
          </div>
        )}

        {unlimited ? (
          <div className="flex items-center gap-3 py-1">
            <span className="text-2xl leading-none text-accent">∞</span>
            <div>
              <div className="text-sm font-medium text-fg">Unlimited budget <span className="text-fg-muted font-normal">(admin run)</span></div>
              <div className="text-xs text-fg-muted tabular-nums">
                Used so far: {fmtDur(wallUsed)} · {tickUsed} ticks — no ceiling.
              </div>
            </div>
          </div>
        ) : (
          <div className="grid grid-cols-2 gap-5">
            <div>
              <div className="flex items-baseline justify-between text-xs mb-1.5">
                <span className="text-fg-secondary">Wall-clock</span>
                <span className="text-fg-muted tabular-nums">{fmtDur(wallUsed)} / {fmtDur(wallCap)}</span>
              </div>
              <Bar pct={wallPct} tone={barTone(wallPct)} />
            </div>
            <div>
              <div className="flex items-baseline justify-between text-xs mb-1.5">
                <span className="text-fg-secondary">Coordination ticks</span>
                <span className="text-fg-muted tabular-nums">{tickUsed} / {tickCap}</span>
              </div>
              <Bar pct={tickPct} tone={barTone(tickPct)} />
            </div>
          </div>
        )}

        {editing && (
          <div className="mt-4 pt-3 border-t border-border flex flex-wrap items-end gap-3">
            <label className="text-xs text-fg-secondary">
              <span className="block mb-1">Max wall-clock (min)</span>
              <input type="number" min="1" value={wallMin} onChange={e => setWallMin(e.target.value)}
                     className="input-px font-mono" style={{ width: "8rem", height: "30px", fontSize: "12px" }} />
            </label>
            <label className="text-xs text-fg-secondary">
              <span className="block mb-1">Max ticks</span>
              <input type="number" min="1" value={ticks} onChange={e => setTicks(e.target.value)}
                     className="input-px font-mono" style={{ width: "8rem", height: "30px", fontSize: "12px" }} />
            </label>
            <button onClick={save} disabled={saving}
                    className="btn-px btn-px-primary btn-px-sm">{saving ? "Saving…" : "Save"}</button>
            <button onClick={() => setEditing(false)} disabled={saving}
                    className="btn-px btn-px-ghost btn-px-sm">Cancel</button>
            {err && <span className="text-xs text-danger">{err}</span>}
          </div>
        )}
      </div>
    );
  }

  // Run controls — Stop a live run, or Continue a stopped/finished one in place
  // (relaunch with --no-fresh: hubs + git persist, agents pick up where they
  // left off, so a bug fix doesn't mean restarting from zero).
  function RunControls({ projectId }) {
    const Icons = window.Icons || {};
    const [runId, setRunId] = useState(null);
    const [running, setRunning] = useState(false);
    const [busy, setBusy] = useState(false);
    const [err, setErr] = useState("");
    const [needKey, setNeedKey] = useState(false);
    const [apiKey, setApiKey] = useState("");

    async function poll() {
      try {
        const r = await fetch(`/api/runs`, { credentials: "include" });
        const d = await r.json();
        const mine = (d.runs || d || []).filter(x => x.project_id === projectId);
        const live = mine.find(x => x.state === "running");
        setRunning(!!live);
        setRunId(live ? live.run_id : (mine[0] ? mine[0].run_id : null));
      } catch (_) {}
    }
    useEffect(() => {
      poll();
      const t = setInterval(poll, 5000);
      return () => clearInterval(t);
    }, [projectId]);

    async function stop() {
      if (!runId) return;
      setBusy(true); setErr("");
      try {
        const r = await fetch(`/api/runs/${encodeURIComponent(runId)}/stop`, {
          method: "POST", headers: { "Content-Type": "application/json" }, credentials: "include",
          body: JSON.stringify({ confirm: true }),
        });
        const d = await r.json();
        if (d.error) setErr(d.error); else { setRunning(false); poll(); }
      } catch (e) { setErr(String(e)); } finally { setBusy(false); }
    }
    async function cont() {
      setBusy(true); setErr("");
      try {
        const body = apiKey.trim() ? { api_key: apiKey.trim() } : {};
        const r = await fetch(`/api/projects/${encodeURIComponent(projectId)}/continue`, {
          method: "POST", headers: { "Content-Type": "application/json" }, credentials: "include",
          body: JSON.stringify(body),
        });
        const d = await r.json();
        if (d.error) {
          setErr(d.error);
          if (/api key/i.test(d.error)) setNeedKey(true);
        } else {
          setNeedKey(false); setApiKey(""); setRunning(true); poll();
        }
      } catch (e) { setErr(String(e)); } finally { setBusy(false); }
    }

    return (
      <div className="flex flex-col items-end gap-1.5">
        <div className="flex items-center gap-2">
          {needKey && !running && (
            <input type="password" value={apiKey} onChange={e => setApiKey(e.target.value)}
                   placeholder="API key to resume" className="input-px w-52 font-mono" />
          )}
          {running ? (
            <button onClick={stop} disabled={busy}
                    className="btn-px btn-px-danger btn-px-lg" title="Stop the running generation">
              {Icons.square ? <Icons.square size={14} /> : "■"} {busy ? "Stopping…" : "Stop run"}
            </button>
          ) : (
            <button onClick={cont} disabled={busy}
                    className="btn-px btn-px-primary btn-px-lg" title="Continue generation in place (keeps all prior work)">
              {Icons.play ? <Icons.play size={14} /> : "▶"} {busy ? "Resuming…" : "Continue run"}
            </button>
          )}
        </div>
        {err && <div className="text-2xs text-danger max-w-[260px] text-right leading-snug">{err}</div>}
      </div>
    );
  }

  function ProjectHero({ state, projectId, activeAgents, totalAgents }) {
    const status = state?.projectStatus || "active";
    const statusColors = {
      active:    { dot: "var(--success)",   text: "text-success" },
      completed: { dot: "var(--info)",      text: "text-info" },
      failed:    { dot: "var(--danger)",    text: "text-danger" },
      paused:    { dot: "var(--warning)",   text: "text-warning" },
      archived:  { dot: "var(--text-muted)", text: "text-fg-muted" },
    };
    const tone = statusColors[status] || statusColors.archived;
    return (
      <div className="bg-bg-elevated border border-border rounded-lg p-6 mb-5">
        <div className="flex items-center gap-3 mb-1">
          <h1 className="text-2xl font-semibold tracking-tight text-fg truncate">
            {state?.projectName || projectId}
          </h1>
          <span className={"inline-flex items-center gap-1.5 text-sm font-medium " + tone.text}>
            <span className="w-1.5 h-1.5 rounded-full" style={{ background: tone.dot }} />
            {status}
          </span>
          <div className="ml-auto shrink-0">
            <RunControls projectId={projectId} />
          </div>
        </div>
        <p className="text-md text-fg-secondary leading-relaxed">
          {state?.projectDescription || "Multi-agent generation workspace."}
        </p>
        <div className="flex items-center gap-4 mt-3 text-sm text-fg-muted">
          <span><span className="text-fg font-semibold tabular-nums">{activeAgents}</span> active agents</span>
          <span className="text-fg-muted/40">·</span>
          <span>of <span className="font-semibold tabular-nums">{totalAgents}</span> total</span>
          <span className="text-fg-muted/40">·</span>
          <code className="font-mono text-xs bg-bg-tertiary px-2 py-0.5 rounded">{projectId}</code>
        </div>
      </div>
    );
  }

  function OverviewMetric({ label, value, sub, icon: Icon, hub, tone, projectId }) {
    const nav = () => window.LiveMonitorRouter.navigateTo(`/projects/${encodeURIComponent(projectId)}/${hub}`);
    const toneCls = {
      info: "text-info", success: "text-success", danger: "text-danger", warning: "text-warning",
    }[tone] || "text-fg";
    return (
      <button onClick={nav}
              className="text-left bg-bg-elevated border border-border rounded-lg p-4 hover:border-border-strong hover:shadow-sm transition-all group">
        <div className="flex items-center justify-between mb-1.5">
          <span className="text-xs uppercase tracking-wider font-medium text-fg-muted">{label}</span>
          {Icon && <span className="text-fg-muted group-hover:text-accent transition-colors"><Icon size={14} /></span>}
        </div>
        <div className={"text-3xl font-semibold tabular-nums tracking-tight leading-none " + toneCls}>{value}</div>
        {sub && <div className="text-xs text-fg-muted mt-1.5">{sub}</div>}
      </button>
    );
  }

  // Map agent_id → semantic role icon (Cutover 43.6)
  const AGENT_ICON = {
    orchestrator: "network",
    design: "palette",
    database: "database",
    backend: "server",
    frontend: "monitor",
    verifier: "shieldCheck",
    knowledge: "book",
    debugger: "bug",
    orchestrator: "blueprint",
    verifier: "eye",
    analysis_worker: "search",
    review_worker: "clipboard",
    worker: "wrench",
  };
  function agentIcon(id) {
    return AGENT_ICON[id] || "user";
  }

  // ============ Agent card — restored CRDT-era little-person animation ============
  function AgentCard({ agent, activity }) {
    const rec = activity || { active: false, recent: false, lastAction: "idle", lastEventType: null, lastEventAt: 0, eventCount: 0 };
    const tone = agentTone(agent.id);
    // Force "idle" anim if not active so the person floats + dots oscillate
    const action = rec.active ? (rec.lastAction || "thinking") : "idle";
    const hub = rec.active ? agentHub(rec) : null;   // hub it's interacting with right now
    // Last hub it touched (for the idle "standby" tile). null only when no history at all.
    const lastHub = (rec.lastEventType || rec.eventCount > 0) ? agentHub(rec) : null;
    const hv = HUB_VISUAL[hub || lastHub] || null;
    const Icons = window.Icons || {};
    const RoleIcon = Icons[agentIcon(agent.id)] || Icons.user;
    // Active → colored hub icon; idle → greyed last-hub icon; no history → generic grid glyph.
    const HubIcon = hv ? (Icons[hv.icon] || Icons.grid) : (Icons.grid || null);
    return (
      <div className={"relative rounded-lg border p-3 transition-all flex flex-col gap-2.5 " +
                      (rec.active
                        ? "bg-bg-elevated border-accent shadow-sm"
                        : rec.recent
                          ? "bg-bg-elevated border-border-strong"
                          : "bg-bg-elevated border-border")}>
        {/* Top row: avatar + name + status */}
        <div className="flex items-center gap-2">
          <div className="relative w-9 h-9 rounded-lg flex items-center justify-center text-white shrink-0 shadow-sm"
               style={{ background: toneToHsl(tone) }}>
            {RoleIcon && <RoleIcon size={18} />}
            {rec.active && (
              <span className="absolute -right-0.5 -bottom-0.5 w-2.5 h-2.5 rounded-full bg-success border-2 border-bg-elevated animate-pulse-soft" />
            )}
          </div>
          <div className="flex-1 min-w-0">
            <div className="text-sm font-semibold text-fg truncate" title={agent.name || agent.id}>
              {agent.id}
            </div>
            <div className={"text-2xs " + (rec.active ? "text-success" : rec.recent ? "text-fg-secondary" : "text-fg-muted")}>
              {rec.active ? "active now" : rec.recent ? "recently" : "idle"}
            </div>
          </div>
          {agent.team_lead && <span className="text-2xs font-mono font-semibold text-accent">LEAD</span>}
        </div>

        {/* Little-person interacting with a HUB station — the actual animation */}
        <div className={"aa " + action}>
          <span className="aa-spark one" />
          <span className="aa-spark two" />
          <div className="aa-person">
            <span className="aa-head" />
            <span className="aa-body" />
            <span className="aa-arm left" />
            <span className="aa-arm right" />
          </div>
          {hub ? (
            <div className={"aa-hub aa-hub-" + hub}>
              <span className="aa-flow a" />
              <span className="aa-flow b" />
              <span className="aa-flow c" />
              <span className="aa-hub-ring" />
              <div className="aa-hub-tile">{HubIcon && <HubIcon size={17} />}</div>
            </div>
          ) : (
            <div className="aa-hub aa-hub-sleep">
              <div className="aa-hub-tile">{HubIcon ? <HubIcon size={16} /> : <span className="aa-zzz" />}</div>
            </div>
          )}
        </div>

        {/* Hub label + count */}
        <div className="flex items-center justify-between text-2xs">
          <span className={"inline-flex items-center gap-1.5 truncate " + (hub ? "text-fg-secondary" : "text-fg-muted")}>
            {(hub || lastHub) && (
              <span className="w-1.5 h-1.5 rounded-full"
                    style={{ background: hub ? hv.solid : "var(--text-muted)" }} />
            )}
            {hub ? hv.label : (lastHub ? hv.label : "Idle")}
          </span>
          <span className="text-fg-muted tabular-nums">{rec.eventCount} ev</span>
        </div>
      </div>
    );
  }

  // Hub identity for the agent-activity animation: icon (window.Icons key),
  // label, and accent color. One visual per hub.
  const HUB_VISUAL = {
    codehub:  { icon: "code",    label: "CodeHub",  solid: "#3178c6" },
    workhub:  { icon: "workhub", label: "WorkHub",  solid: "#8b5cf6" },
    registryhub:   { icon: "api",     label: "RegistryHub",   solid: "#06b6d4" },
    eventhub: { icon: "inbox",   label: "EventHub", solid: "#f59e0b" },
    runhub:   { icon: "play",    label: "RunHub",   solid: "#15803d" },
  };
  // Which hub is this agent interacting with — prefer the agent's last
  // reported focus_hub (from agent_status events); fall back to a heuristic
  // over the last event type for read-only activity (focus_hub is write-only).
  function agentHub(rec) {
    if (rec.focusHub && HUB_VISUAL[rec.focusHub]) return rec.focusHub;
    const s = ((rec.lastEventType || "") + " " + (rec.lastAction || "")).toLowerCase();
    if (/commit|pull|\bpr\b|merge|branch|release|review|code|conflict/.test(s)) return "codehub";
    if (/endpoint|table|schema|\bapi\b|contract|mcp|consumer|designing/.test(s)) return "registryhub";
    if (/run|deploy|compose|build|smoke/.test(s)) return "runhub";
    if (/message|reply|inbox|thread|subscri|mail|broadcast|chat/.test(s)) return "eventhub";
    if (/task|plan|page|decision|bug|block|writing|planning/.test(s)) return "workhub";
    return "workhub";
  }

  function actionLabel(a) {
    const labels = {
      writing: "Writing", reading: "Reading", messaging: "Messaging",
      running: "Running", thinking: "Thinking", planning: "Planning",
      mailing: "Reading mail", finishing: "Finishing", designing: "Designing",
      idle: "Idle",
    };
    return labels[a] || "Active";
  }

  function classifyEventToAction(t) {
    if (!t) return "idle";
    if (/commit|code|write|file/i.test(t)) return "writing";
    if (/task_created|plan/i.test(t)) return "planning";
    if (/message|chat|reply/i.test(t)) return "messaging";
    if (/run|deploy|test/i.test(t)) return "running";
    if (/endpoint|table|schema|api/i.test(t)) return "designing";
    if (/inbox|read|deliver/i.test(t)) return "mailing";
    if (/finish|complete/i.test(t)) return "finishing";
    return "thinking";
  }
  function classifyToolToAction(tool) {
    if (!tool) return "idle";
    const t = String(tool).toLowerCase();
    if (/write|edit|file/.test(t)) return "writing";
    if (/read|grep|search/.test(t)) return "reading";
    if (/message|broadcast|chat/.test(t)) return "messaging";
    if (/run|bash|exec/.test(t)) return "running";
    return "thinking";
  }
  function agentTone(id) {
    const tones = ["violet", "cyan", "amber", "pink", "blue-light", "red-light"];
    let h = 0;
    for (let i = 0; i < (id || "").length; i++) h = (h << 5) - h + id.charCodeAt(i);
    return tones[Math.abs(h) % tones.length];
  }
  function toneToHsl(tone) {
    return {
      violet: "linear-gradient(135deg, #8b5cf6, #6d28d9)",
      cyan:   "linear-gradient(135deg, #06b6d4, #0e7490)",
      amber:  "linear-gradient(135deg, #f59e0b, #b45309)",
      pink:   "linear-gradient(135deg, #ec4899, #be185d)",
      "blue-light": "linear-gradient(135deg, #60a5fa, #2563eb)",
      "red-light":  "linear-gradient(135deg, #f87171, #b91c1c)",
    }[tone] || "linear-gradient(135deg, #888, #555)";
  }

  function ActivityRow({ event, index }) {
    const t = event.event_type || "";
    const KIND_TONE = {
      project_created: "text-success", project_deleted: "text-danger",
      project_status_changed: "text-info", project_run_started: "text-info",
      project_run_finished: "text-success", deliverability_bypass: "text-warning",
      task_created: "text-fg-secondary", commit: "text-fg-secondary",
      review_submitted: "text-info", human_message: "text-accent", agent_reply: "text-success",
      block_appended: "text-fg-secondary", block_updated: "text-fg-secondary",
    };
    const cls = KIND_TONE[t] || "text-fg-secondary";
    function fmt(ts) {
      if (!ts) return "—";
      const d = Date.now() / 1000 - ts;
      if (d < 60) return "now";
      if (d < 3600) return Math.floor(d / 60) + "m";
      if (d < 86400) return Math.floor(d / 3600) + "h";
      return Math.floor(d / 86400) + "d";
    }
    return (
      <div className={"px-3 py-2 border border-border-strong rounded-md bg-bg-elevated hover:bg-bg-hover transition-all " + (index < 3 ? "activity-slide-in" : "")}>
        <div className="flex items-baseline gap-2 text-xs">
          <span className={"font-mono text-2xs font-medium " + cls}>{t}</span>
          <span className="text-fg-muted ml-auto tabular-nums">{fmt(event.created_at)}</span>
        </div>
        <div className="text-2xs text-fg-secondary mt-0.5 truncate">
          <span className="text-fg-muted">{event.source_hub || "—"}</span>
          {event.recipients && event.recipients.length > 0 && (
            <span> → {event.recipients.slice(0, 2).join(", ")}{event.recipients.length > 2 ? `+${event.recipients.length - 2}` : ""}</span>
          )}
        </div>
      </div>
    );
  }

  function TaskProgressCard({ tasks }) {
    const STATUSES = ["pending", "in_progress", "completed", "failed", "blocked"];
    const counts = Object.fromEntries(STATUSES.map(s => [s, tasks.filter(t => (t.status || "pending") === s).length]));
    const total = tasks.length || 1;
    const TONE = {
      pending: "var(--text-muted)", in_progress: "var(--info)",
      completed: "var(--success)", failed: "var(--danger)", blocked: "var(--warning)",
    };
    return (
      <section className="bg-bg-elevated border border-border rounded-lg overflow-hidden">
        <header className="px-4 h-11 flex items-center gap-3 border-b border-border">
          <h3 className="text-md font-semibold tracking-tight">Task progress</h3>
          <span className="text-sm text-fg-muted">{tasks.length} {tasks.length === 1 ? "task" : "tasks"}</span>
        </header>
        <div className="p-4">
          {/* Stacked bar overview */}
          <div className="h-2.5 rounded-full overflow-hidden flex bg-bg-tertiary mb-4">
            {STATUSES.map(s => counts[s] > 0 && (
              <div key={s} className="h-full" style={{ width: `${(counts[s] / total) * 100}%`, background: TONE[s] }} />
            ))}
          </div>
          <div className="space-y-2">
            {STATUSES.map(s => (
              <div key={s} className="flex items-center gap-3 text-sm">
                <span className="w-2 h-2 rounded-full" style={{ background: TONE[s] }} />
                <span className="capitalize text-fg-secondary flex-1">{s.replace("_", " ")}</span>
                <span className="text-fg font-semibold tabular-nums">{counts[s]}</span>
                <span className="text-xs text-fg-muted tabular-nums w-10 text-right">{Math.round((counts[s] / total) * 100)}%</span>
              </div>
            ))}
          </div>
        </div>
      </section>
    );
  }

  function HubDeltasCard({ hubs }) {
    // Last 5 commits / endpoints / tasks (whichever was most recently changed)
    const items = [];
    Object.values(hubs.codehub?.commits || {}).slice(-3).forEach(c => items.push({
      kind: "commit", title: c.message || c.sha?.substr(0, 7) || "(commit)", sub: "codehub", ts: c.created_at || c._updated_at, tone: "text-fg-secondary",
    }));
    Object.values(hubs.registryhub?.endpoints || {}).slice(-3).forEach(e => items.push({
      kind: "endpoint", title: `${e.method} ${e.path}`, sub: "registryhub", ts: e.created_at || e._updated_at, tone: "text-info",
    }));
    Object.values(hubs.workhub?.tasks || {}).slice(-3).forEach(t => items.push({
      kind: "task", title: t.title || t.id, sub: "workhub", ts: t.created_at || t._updated_at, tone: "text-fg-secondary",
    }));
    items.sort((a, b) => (b.ts || 0) - (a.ts || 0));
    const recent = items.slice(0, 6);
    function fmt(ts) {
      if (!ts) return "—";
      const d = Date.now() / 1000 - ts;
      if (d < 60) return "just now";
      if (d < 3600) return Math.floor(d / 60) + "m ago";
      if (d < 86400) return Math.floor(d / 3600) + "h ago";
      return Math.floor(d / 86400) + "d ago";
    }
    return (
      <section className="bg-bg-elevated border border-border rounded-lg overflow-hidden">
        <header className="px-4 h-11 flex items-center gap-3 border-b border-border">
          <h3 className="text-md font-semibold tracking-tight">Recent changes</h3>
          <span className="text-sm text-fg-muted">across hubs</span>
        </header>
        {recent.length === 0 ? (
          <div className="text-center py-10 text-sm text-fg-muted">No changes yet.</div>
        ) : (
          <ul className="p-2 space-y-1.5">
            {recent.map((item, i) => (
              <li key={i} className="px-3 py-2 flex items-start gap-3 border border-border-strong rounded-md bg-bg-elevated hover:bg-bg-hover transition-all">
                <span className={"text-2xs font-mono font-semibold uppercase tracking-wider mt-0.5 shrink-0 " + item.tone}>{item.kind}</span>
                <div className="flex-1 min-w-0">
                  <div className="text-sm text-fg truncate">{item.title}</div>
                  <div className="text-2xs text-fg-muted">{item.sub} · {fmt(item.ts)}</div>
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>
    );
  }

  // ------------------------- Chat -------------------------
  // Reuse the existing ChatPanel component verbatim — it works in a full-page context.
  function ChatPage({ projectId }) {
    return (
      <div className="max-w-[1480px] mx-auto p-6">
        <window.LiveMonitorChatPanel projectId={projectId} />
      </div>
    );
  }

  // ------------------------- References -------------------------
  const REF_CAT = {
    image:  { color: "var(--accent-on-soft)", bg: "var(--accent-soft)", icon: "palette" },
    spec:   { color: "var(--info)",   bg: "var(--info-soft)",   icon: "api" },
    doc:    { color: "var(--fg)",     bg: "var(--bg-tertiary)", icon: "file" },
    data:   { color: "var(--warning)",bg: "var(--warning-soft)",icon: "database" },
    python: { color: "var(--success)",bg: "var(--success-soft)",icon: "code" },
    other:  { color: "var(--text-muted)", bg: "var(--bg-tertiary)", icon: "file" },
  };
  function ReferencesPage({ projectId }) {
    const Icons = window.Icons || {};
    const [files, setFiles] = useState([]);
    const [sel, setSel] = useState(null);       // selected filename
    const [rawText, setRawText] = useState(null);
    const [pending, setPending] = useState(false);
    const [error, setError] = useState("");
    const [drag, setDrag] = useState(false);
    const [confirmDel, setConfirmDel] = useState(null);
    const fileInputRef = useRef(null);

    async function refresh() {
      try {
        const r = await fetch(`/api/projects/${encodeURIComponent(projectId)}/references`, { credentials: "include" });
        const data = await r.json();
        setFiles(data.files || []); setError("");
      } catch (e) { setError(String(e)); }
    }
    useEffect(() => { refresh(); }, [projectId]);
    // auto-select the first file so content is visible without an extra click
    useEffect(() => {
      if (sel && files.some(f => f.name === sel)) return;
      if (files.length > 0) setSel(files[0].name);
    }, [files]);

    const selFile = useMemo(() => files.find(f => f.name === sel) || null, [files, sel]);
    const isImage = (f) => f && (f.category === "image" || /\.(png|jpe?g|webp|gif|svg)$/i.test(f.name));
    const rawUrl = (name) => `/api/projects/${encodeURIComponent(projectId)}/references/${encodeURIComponent(name)}/raw`;

    // load full text for non-image selected files
    useEffect(() => {
      setRawText(null);
      if (!selFile || isImage(selFile)) return;
      let cancelled = false;
      fetch(rawUrl(selFile.name), { credentials: "include" })
        .then(r => r.text()).then(t => { if (!cancelled) setRawText(t); })
        .catch(() => {});
      return () => { cancelled = true; };
    }, [sel, files]);

    function handleFile(file) {
      if (!file) return;
      if (file.size > 10 * 1024 * 1024) { setError(`${file.name} exceeds the 10MB cap`); return; }
      setPending(true); setError("");
      const reader = new FileReader();
      reader.onload = async (ev) => {
        try {
          const b64 = (ev.target.result || "").split(",")[1] || "";
          const r = await fetch(`/api/projects/${encodeURIComponent(projectId)}/references`, {
            method: "POST", headers: { "Content-Type": "application/json" }, credentials: "include",
            body: JSON.stringify({ filename: file.name, content_base64: b64 }),
          });
          const data = await r.json();
          if (data.error) setError(data.error); else { await refresh(); setSel(file.name); }
        } catch (e) { setError(String(e)); }
        finally { setPending(false); }
      };
      reader.readAsDataURL(file);
    }
    async function doDelete(name) {
      await fetch(`/api/projects/${encodeURIComponent(projectId)}/references/${encodeURIComponent(name)}`, { method: "DELETE", credentials: "include" });
      setConfirmDel(null); if (sel === name) setSel(null); refresh();
    }
    function fmtSize(n) {
      if (n == null) return "";
      if (n < 1024) return `${n} B`;
      if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
      return `${(n / 1024 / 1024).toFixed(1)} MB`;
    }
    function catIcon(cat) { const c = REF_CAT[cat] || REF_CAT.other; const I = Icons[c.icon]; return { I, c }; }

    // group by category
    const groups = useMemo(() => {
      const m = {};
      for (const f of files) (m[f.category || "other"] = m[f.category || "other"] || []).push(f);
      return m;
    }, [files]);

    return (
      <div className="max-w-[1480px] mx-auto p-6">
        <input type="file" ref={fileInputRef} onChange={(e) => { handleFile(e.target.files?.[0]); e.target.value = ""; }} style={{ display: "none" }} />
        {/* metric tiles */}
        <div className="grid grid-cols-4 gap-3 mb-5">
          {["image","spec","doc","data"].map(cat => {
            const { I, c } = catIcon(cat); const n = (groups[cat] || []).length;
            return (
              <div key={cat} className="bg-bg-elevated border border-border rounded-lg p-4" style={{ boxShadow: "inset 0 1px 0 rgba(255,255,255,0.4)" }}>
                <div className="flex items-center justify-between mb-1.5">
                  <span className="text-xs uppercase tracking-wider font-medium text-fg-muted">{cat === "image" ? "Images" : cat === "spec" ? "Specs" : cat === "doc" ? "Docs" : "Data"}</span>
                  <span className="inline-flex items-center justify-center w-6 h-6 rounded-md" style={{ background: c.bg, color: c.color }}>{I && <I size={13} />}</span>
                </div>
                <div className="text-3xl font-semibold tabular-nums tracking-tight leading-none text-fg">{n}</div>
              </div>
            );
          })}
        </div>

        <div className="grid grid-cols-[320px_1fr] gap-4">
          {/* file list */}
          <section className="bg-bg-elevated border border-border rounded-lg overflow-hidden self-start">
            <header className="px-4 h-11 border-b border-border flex items-center gap-2">
              <h3 className="text-md font-semibold tracking-tight">Reference files</h3>
              <span className="text-sm text-fg-muted">{files.length}</span>
              <button onClick={() => fileInputRef.current?.click()} disabled={pending} className="btn-px btn-px-primary btn-px-sm ml-auto">
                {pending ? "Uploading…" : <>{Icons.plus && <Icons.plus size={12} />} Upload</>}
              </button>
            </header>
            {error && <div className="mx-3 mt-3 px-3 py-2 rounded-md bg-danger-soft text-danger text-xs">{error}</div>}
            {files.length === 0 ? (
              <div onClick={() => fileInputRef.current?.click()}
                   onDragOver={e => { e.preventDefault(); setDrag(true); }} onDragLeave={() => setDrag(false)}
                   onDrop={e => { e.preventDefault(); setDrag(false); handleFile(e.dataTransfer.files?.[0]); }}
                   className={"m-3 rounded-lg border-2 border-dashed px-4 py-10 text-center cursor-pointer transition-colors " + (drag ? "border-accent bg-accent-soft/30" : "border-border hover:border-border-strong")}>
                <div className="text-sm text-fg-secondary font-medium">Drop a file or click to upload</div>
                <div className="text-xs text-fg-muted mt-1">Images, specs, docs, data — up to 10MB. Auto-indexed for agents.</div>
              </div>
            ) : (
              <div className="py-1.5 max-h-[64vh] overflow-y-auto">
                {Object.keys(groups).sort().map(cat => {
                  const { I, c } = catIcon(cat);
                  return (
                    <div key={cat}>
                      <div className="px-3 pt-2 pb-1 text-2xs uppercase tracking-wider font-semibold text-fg-muted">{cat} <span className="text-fg-muted/60">{groups[cat].length}</span></div>
                      {groups[cat].map(f => {
                        const active = sel === f.name;
                        return (
                          <div key={f.name} className={"group flex items-center gap-2 px-3 py-1.5 cursor-pointer transition-colors " + (active ? "bg-accent-soft" : "hover:bg-bg-hover")}
                               onClick={() => setSel(f.name)}>
                            <span className="inline-flex items-center justify-center w-6 h-6 rounded-md shrink-0" style={{ background: c.bg, color: c.color }}>{I && <I size={12} />}</span>
                            <div className="flex-1 min-w-0">
                              <div className={"font-mono text-xs truncate " + (active ? "text-accent-on-soft font-medium" : "text-fg")}>{f.name}</div>
                              <div className="text-2xs text-fg-muted">{fmtSize(f.size)}</div>
                            </div>
                            {confirmDel === f.name ? (
                              <span onClick={e => e.stopPropagation()} className="flex items-center gap-1">
                                <button onClick={() => setConfirmDel(null)} className="btn-px btn-px-ghost btn-px-sm">No</button>
                                <button onClick={() => doDelete(f.name)} className="btn-px btn-px-danger-ghost btn-px-sm">Delete</button>
                              </span>
                            ) : (
                              <button onClick={e => { e.stopPropagation(); setConfirmDel(f.name); }} className="opacity-0 group-hover:opacity-100 transition-opacity text-fg-muted hover:text-danger text-xs shrink-0">×</button>
                            )}
                          </div>
                        );
                      })}
                    </div>
                  );
                })}
              </div>
            )}
          </section>

          {/* preview pane */}
          <section className="bg-bg-elevated border border-border rounded-lg overflow-hidden self-start">
            {!selFile ? (
              <div className="px-6 py-20 text-center">
                <div className="text-md text-fg font-semibold mb-1">Select a reference</div>
                <div className="text-sm text-fg-muted">Images render inline; text, specs, and data show their contents.</div>
              </div>
            ) : (
              <>
                <header className="px-4 h-11 border-b border-border flex items-center gap-3">
                  {(() => { const { I, c } = catIcon(selFile.category); return <span className="inline-flex items-center justify-center w-6 h-6 rounded-md shrink-0" style={{ background: c.bg, color: c.color }}>{I && <I size={13} />}</span>; })()}
                  <code className="font-mono text-sm text-fg font-medium truncate flex-1">{selFile.name}</code>
                  <span className="text-2xs text-fg-muted">{fmtSize(selFile.size)}</span>
                  <a href={rawUrl(selFile.name)} target="_blank" rel="noreferrer" className="btn-px btn-px-ghost btn-px-sm">Open raw</a>
                </header>
                <div className="p-4">
                  {isImage(selFile) ? (
                    <div className="rounded-md border border-border overflow-hidden bg-bg-secondary flex items-center justify-center" style={{ minHeight: 200 }}>
                      <img src={rawUrl(selFile.name)} alt={selFile.name} style={{ maxWidth: "100%", maxHeight: "70vh", display: "block" }} />
                    </div>
                  ) : selFile.preview === null && rawText === null ? (
                    <div className="text-sm text-fg-muted px-2 py-8 text-center">Binary file — {fmtSize(selFile.size)}. Use “Open raw” to download.</div>
                  ) : (
                    <div className="rounded-md border border-border overflow-hidden">
                      <pre className="p-4 m-0 overflow-auto text-xs leading-relaxed font-mono text-fg-secondary" style={{ background: "var(--bg-secondary)", maxHeight: "68vh" }}>
                        {rawText != null ? rawText : (selFile.preview || "")}
                      </pre>
                    </div>
                  )}
                </div>
              </>
            )}
          </section>
        </div>
      </div>
    );
  }

  // ------------------------- Delivery Gates -------------------------
  function GatesPage({ projectId }) {
    const Icons = window.Icons || {};
    const UiSelect = window.HubUI?.UiSelect;
    const [report, setReport] = useState(null);
    const [loadingReport, setLoadingReport] = useState(true);
    const [gates, setGates] = useState([]);
    const [showAdd, setShowAdd] = useState(false);
    const [gateRows, setGateRows] = useState([]);   // shared editor rows
    const [creating, setCreating] = useState(false);
    const [error, setError] = useState("");
    const Gates = window.EnvGenGates;
    const [confirmDel, setConfirmDel] = useState(null);
    const [delivering, setDelivering] = useState(false);
    const [forceMode, setForceMode] = useState(false);
    const [forceReason, setForceReason] = useState("");
    const [deliverMsg, setDeliverMsg] = useState("");

    async function refreshGates() {
      try {
        const r = await fetch(`/api/projects/${encodeURIComponent(projectId)}/user_gates`, { credentials: "include" });
        const data = await r.json(); setGates(data.gates || []);
      } catch (e) {}
    }
    async function refreshReport() {
      setLoadingReport(true);
      try {
        const r = await fetch(`/api/projects/${encodeURIComponent(projectId)}/deliverability`, { credentials: "include" });
        const data = await r.json(); setReport(data.error ? null : data);
      } catch (e) { setReport(null); }
      finally { setLoadingReport(false); }
    }
    useEffect(() => { refreshGates(); refreshReport(); }, [projectId]);

    async function createGates() {
      const list = Gates ? Gates.collectGates(gateRows) : [];
      if (!list.length) { setError("Add at least one complete gate (fill every field)."); return; }
      setCreating(true); setError("");
      const failed = [];
      for (const g of list) {
        try {
          const r = await fetch(`/api/projects/${encodeURIComponent(projectId)}/user_gates`, {
            method: "POST", headers: { "Content-Type": "application/json" }, credentials: "include",
            body: JSON.stringify(g),
          });
          const d = await r.json();
          if (d.error) failed.push(`${g.name}: ${d.error}`);
        } catch (e) { failed.push(`${g.name}: ${e}`); }
      }
      setCreating(false);
      if (failed.length) setError("Some gates failed — " + failed.join("; "));
      else { setShowAdd(false); setGateRows([]); }
      refreshGates(); refreshReport();
    }
    async function doDelete(gid) {
      await fetch(`/api/projects/${encodeURIComponent(projectId)}/user_gates/${encodeURIComponent(gid)}`, { method: "DELETE", credentials: "include" });
      setConfirmDel(null); refreshGates(); refreshReport();
    }
    async function deliver(force) {
      setDelivering(true); setDeliverMsg("");
      try {
        const body = force ? { force_deliver: true, agent: "ui_user", reason: forceReason.trim() } : {};
        const r = await fetch(`/api/projects/${encodeURIComponent(projectId)}/deliver`, {
          method: "POST", headers: { "Content-Type": "application/json" }, credentials: "include", body: JSON.stringify(body),
        });
        const data = await r.json();
        if (data.error) { setDeliverMsg("⚠ " + data.error); }
        else if (data.delivered) { setDeliverMsg(force ? "✓ Force-delivered (audited)." : "✓ Delivered — project marked completed."); setForceMode(false); setForceReason(""); }
        else { setDeliverMsg("Blocked — resolve the items below first."); }
        if (data.report) setReport(prev => ({ ...(prev || {}), ...data.report }));
        refreshReport();
      } catch (e) { setDeliverMsg("⚠ " + String(e)); }
      finally { setDelivering(false); }
    }

    const verdict = (report?.verdict || "").toLowerCase();
    const deliverable = verdict === "deliverable" || verdict === "ready";
    const blockers = report?.blockers || [];

    // sub-metric chips from the report
    const subMetrics = report ? [
      report.endpoint_probes && { label: "Endpoint probes", ok: (report.endpoint_probes.failed || 0) === 0, txt: `${report.endpoint_probes.passed || 0}/${report.endpoint_probes.total || 0} pass` },
      report.mcp_probes && { label: "MCP probes", ok: (report.mcp_probes.failed || 0) === 0, txt: `${report.mcp_probes.passed || 0}/${report.mcp_probes.total || 0} pass` },
      report.coverage && { label: "Coverage", ok: !!report.coverage.is_clean, txt: report.coverage.is_clean ? "clean" : "dead artifacts" },
      report.visual_reviews && { label: "Visual reviews", ok: (report.visual_reviews.pending || 0) === 0 && (report.visual_reviews.needs_revision || 0) === 0, txt: `${report.visual_reviews.approved || 0} approved` },
      typeof report.run_within_session === "boolean" && { label: "Run this session", ok: report.run_within_session, txt: report.run_within_session ? "yes" : "none" },
    ].filter(Boolean) : [];

    return (
      <div className="max-w-[1480px] mx-auto p-6">
        {/* ===== Deliverability hero ===== */}
        <div className="bg-bg-elevated border rounded-lg p-5 mb-5"
             style={{ borderColor: deliverable ? "color-mix(in srgb, var(--success) 35%, var(--border))" : (report ? "color-mix(in srgb, var(--danger) 25%, var(--border))" : "var(--border)"), boxShadow: "inset 0 1px 0 rgba(255,255,255,0.4)" }}>
          <div className="flex items-start gap-4">
            <span className="w-11 h-11 rounded-xl flex items-center justify-center shrink-0 text-lg font-bold"
                  style={{ background: deliverable ? "var(--success-soft)" : "var(--danger-soft)", color: deliverable ? "var(--success)" : "var(--danger)" }}>
              {loadingReport ? "…" : deliverable ? "✓" : "●"}
            </span>
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2 flex-wrap">
                <h1 className="text-xl font-semibold tracking-tight text-fg">Delivery readiness</h1>
                {report && (
                  <span className="text-2xs uppercase tracking-wider font-semibold px-2 py-0.5 rounded"
                        style={{ color: deliverable ? "var(--success)" : "var(--danger)", background: deliverable ? "var(--success-soft)" : "var(--danger-soft)" }}>
                    {deliverable ? "deliverable" : "blocked"}
                  </span>
                )}
              </div>
              <p className="text-sm text-fg-muted mt-0.5">
                {loadingReport ? "Computing deliverability…" : deliverable ? "All gates pass — the project can be delivered." : `${blockers.length} blocker${blockers.length === 1 ? "" : "s"} must be resolved before delivery.`}
              </p>
              {/* sub-metrics */}
              {subMetrics.length > 0 && (
                <div className="flex flex-wrap gap-2 mt-3">
                  {subMetrics.map((m, i) => (
                    <span key={i} className="inline-flex items-center gap-1.5 text-2xs px-2 py-1 rounded-md border border-border bg-bg-secondary/40">
                      <span className="w-1.5 h-1.5 rounded-full" style={{ background: m.ok ? "var(--success)" : "var(--danger)" }} />
                      <span className="text-fg-secondary font-medium">{m.label}</span>
                      <span className="text-fg-muted">{m.txt}</span>
                    </span>
                  ))}
                </div>
              )}
            </div>
            <div className="shrink-0 flex flex-col items-end gap-2">
              {!forceMode ? (
                <div className="flex items-center gap-2">
                  <button onClick={refreshReport} className="btn-px btn-px-ghost btn-px-sm">Re-check</button>
                  <button onClick={() => deliver(false)} disabled={delivering} className="btn-px btn-px-primary btn-px-sm">
                    {Icons.shieldCheck && <Icons.shieldCheck size={12} />} {delivering ? "Delivering…" : "Deliver"}
                  </button>
                </div>
              ) : null}
              {!deliverable && report && !forceMode && (
                <button onClick={() => setForceMode(true)} className="text-2xs text-fg-muted hover:text-danger">Force deliver…</button>
              )}
            </div>
          </div>

          {deliverMsg && <div className="mt-3 px-3 py-2 rounded-md text-sm" style={{ background: deliverMsg.startsWith("✓") ? "var(--success-soft)" : deliverMsg.startsWith("⚠") ? "var(--danger-soft)" : "var(--warning-soft)", color: deliverMsg.startsWith("✓") ? "var(--success)" : deliverMsg.startsWith("⚠") ? "var(--danger)" : "var(--warning)" }}>{deliverMsg}</div>}

          {/* force-merge inline */}
          {forceMode && (
            <div className="mt-3 p-3 rounded-md bg-warning-soft border border-warning/30 space-y-2.5">
              <div className="text-sm text-warning font-semibold">⚠ Force delivery bypasses all gates (audited)</div>
              <textarea value={forceReason} onChange={e => setForceReason(e.target.value)} rows={2} placeholder="Why are you overriding the gates? (≥5 chars)" className="input-px textarea-px w-full" />
              <div className="flex justify-end gap-2">
                <button onClick={() => { setForceMode(false); setForceReason(""); }} className="btn-px btn-px-ghost btn-px-sm">Cancel</button>
                <button onClick={() => deliver(true)} disabled={delivering || forceReason.trim().length < 5} className="btn-px btn-px-sm" style={{ background: "var(--danger)", color: "var(--text-on-accent)", border: "1px solid var(--danger)" }}>{delivering ? "Delivering…" : "Force deliver"}</button>
              </div>
            </div>
          )}

          {/* blockers list */}
          {blockers.length > 0 && (
            <div className="mt-4 pt-4 border-t border-border-subtle">
              <div className="text-2xs uppercase tracking-wider font-medium text-fg-muted mb-2">Blockers</div>
              <ul className="space-y-1.5">
                {blockers.map((b, i) => (
                  <li key={i} className="flex items-start gap-2 text-sm text-fg-secondary">
                    <span className="text-danger mt-0.5 shrink-0">✕</span>
                    <span>{b.startsWith("user_gate:") ? <><span className="text-2xs uppercase font-semibold text-warning mr-1.5">gate</span>{b.slice("user_gate:".length)}</> : b}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>

        {/* ===== User gates ===== */}
        <section className="bg-bg-elevated border border-border rounded-lg overflow-hidden">
          <header className="px-4 h-11 border-b border-border flex items-center gap-2">
            <h3 className="text-md font-semibold tracking-tight">Custom gates</h3>
            <span className="text-sm text-fg-muted">{gates.length}</span>
            <button onClick={() => { setShowAdd(s => !s); setError(""); }} className={"btn-px btn-px-sm ml-auto " + (showAdd ? "btn-px-ghost" : "btn-px-primary")}>
              {showAdd ? "Cancel" : <>{Icons.plus && <Icons.plus size={12} />} Add gate</>}
            </button>
          </header>

          {showAdd && (
            <div className="px-4 py-4 border-b border-border bg-bg-secondary space-y-3">
              {error && <div className="px-3 py-2 rounded-md bg-danger-soft text-danger text-sm">{error}</div>}
              {Gates
                ? <Gates.GateRowsEditor rows={gateRows} setRows={setGateRows} />
                : <div className="text-sm text-fg-muted">Gate editor unavailable.</div>}
              <div className="flex justify-end">
                {(() => {
                  const ready = Gates ? Gates.collectGates(gateRows).length : 0;
                  return (
                    <button onClick={createGates} disabled={creating || ready === 0} className="btn-px btn-px-primary btn-px-sm">
                      {creating ? "Creating…" : `Create ${ready || ""} gate${ready === 1 ? "" : "s"}`.replace(/\s+/g, " ")}
                    </button>
                  );
                })()}
              </div>
            </div>
          )}

          {gates.length === 0 && !showAdd ? (
            <div className="px-6 py-12 text-center">
              <div className="text-md text-fg font-semibold mb-1">No custom gates</div>
              <div className="text-sm text-fg-muted max-w-sm mx-auto">Add file/endpoint/MCP/visual checks. Any failing gate blocks delivery until resolved.</div>
            </div>
          ) : (
            <ul className="p-3 space-y-2">
              {gates.map(g => {
                const ok = g.status?.passed;
                return (
                  <li key={g.id} className="px-4 py-3 border border-border rounded-md bg-bg-elevated hover:border-border-strong transition-all flex items-center gap-3">
                    <span className="text-2xs font-mono font-semibold uppercase px-1.5 py-0.5 rounded w-12 text-center shrink-0"
                          style={{ color: ok ? "var(--success)" : "var(--danger)", background: ok ? "var(--success-soft)" : "var(--danger-soft)" }}>{ok ? "pass" : "fail"}</span>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="text-sm font-medium text-fg">{g.name}</span>
                        <code className="text-2xs font-mono text-fg-muted px-1.5 py-0.5 rounded bg-bg-tertiary">{g.type}</code>
                        {window.EnvGenData ? <window.EnvGenData.ParamChips params={g.params} /> : null}
                      </div>
                      {g.status?.message && <div className="text-xs text-fg-muted mt-0.5">{g.status.message}</div>}
                    </div>
                    {confirmDel === g.id ? (
                      <span className="flex items-center gap-1 shrink-0">
                        <button onClick={() => setConfirmDel(null)} className="btn-px btn-px-ghost btn-px-sm">Cancel</button>
                        <button onClick={() => doDelete(g.id)} className="btn-px btn-px-danger-ghost btn-px-sm">Delete</button>
                      </span>
                    ) : (
                      <button onClick={() => setConfirmDel(g.id)} className="btn-px btn-px-ghost btn-px-sm text-fg-muted shrink-0">Delete</button>
                    )}
                  </li>
                );
              })}
            </ul>
          )}
        </section>
      </div>
    );
  }

  // ===========================================================================
  // HistoryPage — flat timeline of every agent action (tool calls) across the
  // run. Filterable by agent + tool/free-text. Newest first. Expand a row to
  // see full args + result. Data comes from /state.toolCalls (the same source
  // the dashboard/overview reads) so it tracks the live run.
  // ===========================================================================
  const AGENT_HUE = {                         // tiny per-agent palette
    orchestrator: 280, design: 200, database: 30, backend: 145, frontend: 320,
    verifier: 0,    knowledge: 50, orchestrator: 240, verifier: 180,
    debugger: 15, worker: 220,
  };
  function agentChip(agent) {
    const h = AGENT_HUE[agent] != null ? AGENT_HUE[agent] : 220;
    return {
      color: `hsl(${h}, 80%, 38%)`,
      bg: `hsl(${h}, 70%, 92%)`,
    };
  }
  function fmtTime(ts) {                     // ISO -> "HH:MM:SS"
    if (!ts) return "";
    try {
      const d = new Date(ts);
      if (isNaN(d)) return String(ts).slice(11, 19);
      return d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false });
    } catch (_) { return String(ts); }
  }
  function shortJson(value, max = 240) {
    if (value == null) return "";
    try {
      const s = typeof value === "string" ? value : JSON.stringify(value);
      return s.length > max ? s.slice(0, max) + "…" : s;
    } catch (_) { return String(value); }
  }

  function HistoryRow({ tc, expanded, onToggle }) {
    const a = tc.agent || tc.ownerAgent || "—";
    const sty = agentChip(a);
    const tool = tc.toolName || "tool";
    const args = tc.args ?? tc.argsText;
    const result = tc.result ?? tc.resultText;
    return (
      <li className="border border-border rounded-md bg-bg-elevated">
        <button onClick={onToggle}
                className="w-full text-left px-3 py-2 flex items-center gap-3 hover:bg-bg-hover transition-colors">
          <span className="text-2xs tabular-nums text-fg-muted font-mono shrink-0 w-16">{fmtTime(tc.timestamp)}</span>
          <span className="text-2xs uppercase tracking-wider font-medium px-1.5 py-0.5 rounded shrink-0"
                style={{ color: sty.color, background: sty.bg }}>{a}</span>
          <code className="text-2xs font-mono text-fg shrink-0">{tool}</code>
          <span className="text-2xs text-fg-muted truncate flex-1 font-mono">{shortJson(args, 200)}</span>
          <span className="text-fg-muted text-2xs ml-1">{expanded ? "▾" : "▸"}</span>
        </button>
        {expanded && (
          <div className="px-3 pb-3 pt-1 border-t border-border bg-bg-tertiary/30 space-y-2">
            <div>
              <div className="text-2xs uppercase tracking-wider font-medium text-fg-muted mb-1">args</div>
              <pre className="text-2xs font-mono text-fg-secondary bg-bg p-2 rounded border border-border overflow-x-auto whitespace-pre-wrap break-all">{shortJson(args, 4000)}</pre>
            </div>
            <div>
              <div className="text-2xs uppercase tracking-wider font-medium text-fg-muted mb-1">result</div>
              <pre className="text-2xs font-mono text-fg-secondary bg-bg p-2 rounded border border-border overflow-x-auto whitespace-pre-wrap break-all">{shortJson(result, 4000)}</pre>
            </div>
          </div>
        )}
      </li>
    );
  }

  function HistoryPage({ projectId, state }) {
    const Icons = window.Icons || {};
    const UiSelect = window.HubUI?.UiSelect;
    const all = (state?.toolCalls || []);
    // newest first; stable across renders
    const ordered = useMemo(() =>
      [...all].sort((a, b) => String(b.timestamp || "").localeCompare(String(a.timestamp || ""))),
      [all]);
    const agents = useMemo(() => {
      const s = new Set();
      ordered.forEach(tc => { const a = tc.agent || tc.ownerAgent; if (a) s.add(a); });
      return [...s].sort();
    }, [ordered]);
    const [agent, setAgent] = useState("");
    const [search, setSearch] = useState("");
    const [expanded, setExpanded] = useState({});
    const filtered = useMemo(() => {
      const q = search.trim().toLowerCase();
      return ordered.filter(tc => {
        const a = tc.agent || tc.ownerAgent;
        if (agent && a !== agent) return false;
        if (q) {
          const blob = `${a} ${tc.toolName || ""} ${tc.argsText || ""} ${tc.resultText || ""}`.toLowerCase();
          if (!blob.includes(q)) return false;
        }
        return true;
      });
    }, [ordered, agent, search]);

    return (
      <div className="page" style={{ maxWidth: 1480 }}>
        <div className="bg-bg-elevated border border-border rounded-lg p-5 mb-5">
          <div className="flex items-center gap-3 mb-1 flex-wrap">
            <h1 className="text-2xl font-semibold tracking-tight text-fg">Action history</h1>
            <span className="text-sm text-fg-muted">{filtered.length} of {ordered.length} tool calls</span>
            <span className="ml-auto flex items-center gap-2">
              <div className="flex items-center gap-2 px-2.5 h-8 bg-bg-elevated rounded-md border border-border focus-within:border-accent">
                {Icons.search && <span className="text-fg-muted"><Icons.search size={12} /></span>}
                <input className="bare text-sm placeholder:text-fg-muted w-56" placeholder="Filter by tool, args, result…"
                       value={search} onChange={e => setSearch(e.target.value)} />
              </div>
              {UiSelect && (
                <UiSelect value={agent} onChange={setAgent} placeholder="All agents" size="md" minWidth={160}
                          options={[{ value: "", label: "All agents" }, ...agents.map(a => ({ value: a, label: a }))]} />
              )}
            </span>
          </div>
          <p className="text-sm text-fg-secondary mt-2">
            One row per tool call. Click a row to expand its full args + result. Source: <code className="font-mono">/state.toolCalls</code>.
          </p>
        </div>

        {filtered.length === 0 ? (
          <div className="text-center py-16 text-fg-muted text-sm border border-border rounded-md bg-bg-elevated">
            {ordered.length === 0 ? "No tool calls recorded yet." : "No matches for the current filter."}
          </div>
        ) : (
          <ul className="space-y-1.5">
            {filtered.slice(0, 500).map(tc => (
              <HistoryRow key={tc.id || `${tc.agent}-${tc.timestamp}-${tc.toolName}`} tc={tc}
                          expanded={!!expanded[tc.id]} onToggle={() => setExpanded(p => ({ ...p, [tc.id]: !p[tc.id] }))} />
            ))}
            {filtered.length > 500 && (
              <li className="text-center py-3 text-2xs text-fg-muted">Showing 500 most recent of {filtered.length} matching tool calls.</li>
            )}
          </ul>
        )}
      </div>
    );
  }

  return { OverviewPage, ChatPage, ReferencesPage, GatesPage, HistoryPage };
})();
