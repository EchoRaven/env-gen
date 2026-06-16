window.HubPages = (function () {
  const { useState, useMemo, useEffect } = React;

  // ============ Shared atoms (Cutover 43.7) ============
  function HubLayout({ children }) {
    return <div className="max-w-[1480px] mx-auto p-6">{children}</div>;
  }

  function MetricTile({ label, value, sub, icon: Icon, tone = "neutral", onClick }) {
    const toneCls = { info: "text-info", success: "text-success", danger: "text-danger", warning: "text-warning", neutral: "text-fg" }[tone];
    const toneBg  = { info: "var(--info-soft)", success: "var(--success-soft)", danger: "var(--danger-soft)", warning: "var(--warning-soft)", neutral: "var(--bg-tertiary)" }[tone];
    return (
      <button onClick={onClick} disabled={!onClick}
              className="group text-left bg-bg-elevated border border-border rounded-lg p-4 transition-all disabled:cursor-default hover:border-border-strong"
              style={{ boxShadow: "inset 0 1px 0 rgba(255,255,255,0.4)" }}>
        <div className="flex items-center justify-between mb-1.5">
          <span className="text-xs uppercase tracking-wider font-medium text-fg-muted">{label}</span>
          {Icon && (
            <span className={"inline-flex items-center justify-center w-6 h-6 rounded-md transition-colors " + toneCls}
                  style={{ background: toneBg }}>
              <Icon size={13} />
            </span>
          )}
        </div>
        <div className={"text-3xl font-semibold tabular-nums tracking-tight leading-none " + toneCls}>{value}</div>
        {sub && <div className="text-xs text-fg-muted mt-1.5">{sub}</div>}
      </button>
    );
  }

  function TabBar({ tabs, current, onChange }) {
    return (
      <div className="flex gap-1 border-b border-border mb-5">
        {tabs.map(t => (
          <button key={t.key} onClick={() => onChange(t.key)}
                  className={"px-3 h-9 text-base font-medium flex items-center gap-2 border-b-2 -mb-px transition-colors " +
                             (current === t.key
                               ? "text-fg border-accent"
                               : "text-fg-secondary border-transparent hover:text-fg")}>
            {t.label}
            {t.count !== undefined && (
              <span className={"text-2xs tabular-nums px-1.5 py-0.5 rounded-full " +
                               (current === t.key ? "bg-accent-soft text-accent-on-soft" : "bg-bg-tertiary text-fg-muted")}>
                {t.count}
              </span>
            )}
          </button>
        ))}
      </div>
    );
  }

  function HubCard({ children, className = "" }) {
    return (
      <section className={"bg-bg-elevated border border-border rounded-lg overflow-hidden " + className}>
        {children}
      </section>
    );
  }

  function HubCardHeader({ title, subtitle, actions }) {
    return (
      <header className="flex items-center gap-3 px-4 h-11 border-b border-border">
        <h3 className="text-md font-semibold tracking-tight">{title}</h3>
        {subtitle && <span className="text-sm text-fg-muted">{subtitle}</span>}
        {actions && <div className="ml-auto">{actions}</div>}
      </header>
    );
  }

  function EmptyState({ icon: Icon, title, sub, actionLabel, onAction }) {
    return (
      <div className="text-center py-16 px-6">
        {Icon && (
          <div className="inline-flex items-center justify-center w-14 h-14 rounded-2xl mb-4 text-accent"
               style={{
                 background: "linear-gradient(135deg, color-mix(in srgb, var(--accent) 14%, transparent), color-mix(in srgb, var(--accent) 6%, transparent))",
                 boxShadow: "inset 0 1px 0 rgba(255,255,255,0.4), 0 1px 3px rgba(0,0,0,0.04)",
               }}>
            <Icon size={26} />
          </div>
        )}
        <div className="text-md text-fg font-semibold mb-1">{title}</div>
        {sub && <div className="text-sm text-fg-muted mb-5 max-w-sm mx-auto leading-relaxed">{sub}</div>}
        {actionLabel && onAction && (
          <button onClick={onAction} className="btn-px btn-px-primary">{actionLabel}</button>
        )}
      </div>
    );
  }

  function fmtRel(ts) {
    if (!ts) return "—";
    const d = Date.now() / 1000 - ts;
    if (d < 60) return "just now";
    if (d < 3600) return Math.floor(d / 60) + "m ago";
    if (d < 86400) return Math.floor(d / 3600) + "h ago";
    if (d < 86400 * 7) return Math.floor(d / 86400) + "d ago";
    return new Date(ts * 1000).toLocaleDateString(undefined, { month: "short", day: "numeric" });
  }
  function fmtFull(ts) { return ts ? new Date(ts * 1000).toLocaleString() : "—"; }

  // Cutover 43.12: ActorChip — pure text, no avatar circle (GitHub style).
  function ActorChip({ name }) {
    return <span className="text-fg-secondary text-xs font-medium">{name || "—"}</span>;
  }
  // AgentAvatar — only used in Overview where prominent icon makes sense.
  // No first-letter fallback: unknown agents get a generic user icon.
  function AgentAvatar({ name, size = 18 }) {
    const Icons = window.Icons || {};
    const Ico = window.AgentIcons?.iconFor(name) || Icons.user;
    const grad = window.AgentIcons?.gradient(name) || "linear-gradient(135deg, #888, #555)";
    const iconSize = Math.max(10, Math.floor(size * 0.62));
    return (
      <span className="inline-flex items-center justify-center text-white shrink-0 rounded-md"
            style={{
              width: size, height: size,
              background: grad,
              boxShadow: "inset 0 1px 0 rgba(255,255,255,0.18), 0 1px 2px rgba(0,0,0,0.12)",
            }}>
        {Ico ? <Ico size={iconSize} /> : null}
      </span>
    );
  }

  // PR state visual mapping
  function prStateVisual(s) {
    const map = {
      open:              { label: "open",            color: "var(--success)",  bg: "var(--success-soft)" },
      ready:             { label: "ready to merge",  color: "var(--success)",  bg: "var(--success-soft)" },
      merged:            { label: "merged",          color: "var(--accent)",   bg: "var(--accent-soft)" },
      closed:            { label: "closed",          color: "var(--text-muted)", bg: "var(--bg-tertiary)" },
      changes_requested: { label: "changes requested", color: "var(--warning)", bg: "var(--warning-soft)" },
    };
    return map[s] || map.open;
  }

  // ----- legacy bits (Section / DataTable / StatPill) — kept for other hubs until they're redesigned -----

  // ------------------------- helpers -------------------------

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

  function Section({ title, action, children }) {
    return (
      <section className="page-section">
        <div className="page-section-header">
          <h3>{title}</h3>
          {action}
        </div>
        <div className="page-section-body">{children}</div>
      </section>
    );
  }

  function DataTable({ columns, rows, empty }) {
    if (!rows || rows.length === 0) {
      return <div className="empty-state">{empty || "No data."}</div>;
    }
    return (
      <table className="data-table">
        <thead>
          <tr>{columns.map(c => <th key={c.key} style={{ width: c.width }}>{c.label}</th>)}</tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={row.id || i}>
              {columns.map(c => <td key={c.key}>{c.render ? c.render(row) : row[c.key]}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    );
  }

  function StatPill({ label, value, tone }) {
    return (
      <div className={"stat-pill stat-" + (tone || "neutral")}>
        <div className="stat-pill-value">{value}</div>
        <div className="stat-pill-label">{label}</div>
      </div>
    );
  }

  function fmtDate(ts) {
    if (!ts) return "—";
    return new Date(ts * 1000).toLocaleDateString();
  }

  // ===========================================================================
  // Cutover 43.25: UiSelect — custom dropdown (portal + fixed positioning) to
  // replace native <select>. options: [{value, label}]. Never clipped by an
  // ancestor's overflow:hidden.
  // ===========================================================================
  function UiSelect({ options, value, onChange, placeholder = "Select…", size = "sm", minWidth = 130, fullWidth = false, inputStyle = false }) {
    const Icons = window.Icons || {};
    const [open, setOpen] = useState(false);
    const [rect, setRect] = useState(null);
    const btnRef = React.useRef(null);
    const current = options.find(o => o.value === value);
    function openMenu() {
      const r = btnRef.current?.getBoundingClientRect();
      if (r) setRect({ left: r.left, top: r.bottom + 4, width: Math.max(r.width, minWidth) });
      setOpen(true);
    }
    function close() { setOpen(false); }
    // The panel is portal-rendered with CSS `fixed`, so it stays at viewport
    // coordinates while a page scroll moves the trigger underneath it. That
    // looks broken (panel detaches from its anchor). Close on any scroll or
    // resize — same UX as the native <select>. The capture phase catches
    // scrolls of inner scrollable containers too.
    useEffect(() => {
      if (!open) return;
      const onScroll = () => close();
      const onResize = () => close();
      window.addEventListener("scroll", onScroll, true);
      window.addEventListener("resize", onResize);
      return () => {
        window.removeEventListener("scroll", onScroll, true);
        window.removeEventListener("resize", onResize);
      };
    }, [open]);
    const panel = open && rect ? ReactDOM.createPortal(
      <>
        <div className="fixed inset-0 z-[200]" onClick={close} />
        <div className="fixed z-[201] bg-bg-elevated border border-border rounded-lg overflow-hidden py-1"
             style={{ left: rect.left, top: rect.top, minWidth: rect.width, boxShadow: "0 8px 28px rgba(0,0,0,0.16)" }}>
          <ul className="max-h-72 overflow-y-auto">
            {options.map(o => {
              const isCur = o.value === value;
              return (
                <li key={String(o.value)}>
                  <button onClick={() => { onChange(o.value); close(); }}
                          className={"w-full text-left px-3 py-1.5 flex items-center gap-2 text-sm transition-colors " +
                                     (isCur ? "bg-accent-soft text-accent-on-soft" : "text-fg-secondary hover:bg-bg-hover")}>
                    <span className="w-3 shrink-0 text-accent">{isCur ? "✓" : ""}</span>
                    <span className="truncate">{o.label}</span>
                  </button>
                </li>
              );
            })}
          </ul>
        </div>
      </>, document.body) : null;
    // inputStyle: render the trigger like an `input-px` field (36px, input border/bg)
    // so it lines up with sibling inputs (e.g. the gate editor's param fields).
    const triggerCls = inputStyle
      ? ("input-px ui-select-trigger justify-between" + (fullWidth ? " w-full" : ""))
      : ("btn-px btn-px-ghost ui-select-trigger " + (size === "sm" ? "btn-px-sm" : "") + " justify-between" + (fullWidth ? " w-full" : ""));
    const triggerStyle = inputStyle
      ? { display: "inline-flex", alignItems: "center", cursor: "pointer", width: fullWidth ? "100%" : minWidth }
      : (fullWidth ? undefined : { minWidth });
    return (
      <div className={"relative " + (fullWidth ? "block w-full" : "inline-block")}>
        <button ref={btnRef} onClick={() => open ? close() : openMenu()}
                className={triggerCls} style={triggerStyle}>
          <span className="truncate">{current ? current.label : placeholder}</span>
          <span className="text-fg-muted text-2xs ml-1.5">▾</span>
        </button>
        {panel}
      </div>
    );
  }

  // ===========================================================================
  // Cutover 43.17: BranchSelector — GitHub-style branch dropdown.
  // Searchable, default branch pinned + tagged, current branch checked,
  // owning agent shown as plain text on the right.
  // ===========================================================================
  // Derive the owning agent of a branch. Prefer recorded metadata; fall back
  // to the convention `agent/<id>` so the UI labels worktree branches even when
  // CodeHub hasn't (yet) recorded a Branch entity for them.
  function branchOwner(branch, metaByName) {
    const meta = metaByName?.[branch];
    if (meta?.owner) return meta.owner;
    const m = /^agent\/(.+)$/.exec(branch || "");
    return m ? m[1] : null;
  }

  function BranchSelector({ branches, value, defaultBranch, onChange, metaByName, size = "sm" }) {
    const Icons = window.Icons || {};
    const [open, setOpen] = useState(false);
    const [q, setQ] = useState("");
    const [rect, setRect] = useState(null);   // trigger position for fixed-positioned panel
    const btnRef = React.useRef(null);
    const currentOwner = branchOwner(value, metaByName);
    const list = useMemo(() => {
      const filtered = (branches || []).filter(b => b.toLowerCase().includes(q.toLowerCase()));
      return filtered.sort((a, b) =>
        a === defaultBranch ? -1 : b === defaultBranch ? 1 : a.localeCompare(b));
    }, [branches, q, defaultBranch]);

    function openMenu() {
      const r = btnRef.current?.getBoundingClientRect();
      if (r) setRect({ left: r.left, top: r.bottom + 4, width: Math.max(r.width, 256) });
      setOpen(true);
    }
    function closeMenu() { setOpen(false); setQ(""); }

    // The panel is rendered via a portal to document.body with fixed positioning
    // so it never gets clipped by an ancestor's overflow:hidden (e.g. HubCard).
    const panel = open && rect ? ReactDOM.createPortal(
      <>
        <div className="fixed inset-0 z-[200]" onClick={closeMenu} />
        <div className="fixed z-[201] w-72 bg-bg-elevated border border-border rounded-lg overflow-hidden"
             style={{ left: rect.left, top: rect.top, boxShadow: "0 8px 28px rgba(0,0,0,0.16)" }}>
          <div className="px-2.5 py-2 border-b border-border text-2xs uppercase tracking-wider font-medium text-fg-muted">
            Switch branches ({(branches || []).length})
          </div>
          <div className="p-2 border-b border-border">
            <div className="flex items-center gap-2 px-2 h-7 bg-bg-tertiary rounded-md border border-transparent focus-within:border-accent focus-within:bg-bg-elevated">
              {Icons.search && <span className="text-fg-muted shrink-0"><Icons.search size={11} /></span>}
              <input autoFocus className="bare text-sm placeholder:text-fg-muted w-full"
                     placeholder="Find a branch…" value={q} onChange={e => setQ(e.target.value)} />
            </div>
          </div>
          <ul className="max-h-64 overflow-y-auto py-1">
            {list.length === 0 ? (
              <li className="px-3 py-2 text-sm text-fg-muted">No branches match.</li>
            ) : list.map(b => {
              const owner = branchOwner(b, metaByName);
              const isCur = b === value;
              return (
                <li key={b}>
                  <button onClick={() => { onChange(b); closeMenu(); }}
                          className={"w-full text-left px-3 py-1.5 flex items-center gap-2 text-sm transition-colors " +
                                     (isCur ? "bg-accent-soft text-accent-on-soft" : "text-fg-secondary hover:bg-bg-hover")}>
                    <span className="w-3 shrink-0 text-accent">{isCur ? "✓" : ""}</span>
                    {Icons.branch && <span className="text-fg-muted shrink-0"><Icons.branch size={12} /></span>}
                    <span className="font-mono truncate flex-1 min-w-0">{b}</span>
                    {b === defaultBranch && (
                      <span className="text-2xs px-1.5 py-0.5 rounded-full bg-bg-tertiary text-fg-muted font-medium shrink-0">default</span>
                    )}
                    {owner && (
                      <span className="text-2xs px-1.5 py-0.5 rounded-md bg-accent-soft text-accent-on-soft font-medium shrink-0" title={`Owned by agent: ${owner}`}>
                        {owner}
                      </span>
                    )}
                  </button>
                </li>
              );
            })}
          </ul>
        </div>
      </>,
      document.body
    ) : null;

    return (
      <div className="relative inline-block">
        <button ref={btnRef} onClick={() => open ? closeMenu() : openMenu()}
                className={"btn-px btn-px-ghost " + (size === "sm" ? "btn-px-sm" : "") + " justify-between min-w-[150px]"}
                title="Switch branch">
          <span className="flex items-center gap-1.5 min-w-0">
            {Icons.branch && <Icons.branch size={12} />}
            <span className="font-mono truncate">{value}</span>
            {currentOwner && (
              <span className="text-2xs px-1.5 py-0.5 rounded-md bg-accent-soft text-accent-on-soft font-medium shrink-0" title={`Owned by agent: ${currentOwner}`}>
                {currentOwner}
              </span>
            )}
          </span>
          <span className="text-fg-muted text-2xs ml-1">▾</span>
        </button>
        {panel}
      </div>
    );
  }

  // ===========================================================================
  // Cutover 43.13/43.17: CodeBrowser — GitHub repo-page style, branch-aware.
  // Left: branch selector + "Go to file" search + expandable tree.
  // Right: directory listing table OR syntax-highlighted file content.
  // All tree/file/files fetches are scoped to the selected branch.
  // ===========================================================================
  function CodeBrowser({ projectId, branch, branchList, defaultBranch, onBranchChange, branchMeta, initialFile, onInitialFileConsumed }) {
    const Icons = window.Icons || {};
    const bq = branch ? `&branch=${encodeURIComponent(branch)}` : "";
    const [dirCache, setDirCache] = useState({});                 // path -> {loading, error, entries}
    const [expanded, setExpanded] = useState({ "": true });
    const [cwdPath, setCwdPath] = useState("");                   // dir shown in right pane
    const [filePath, setFilePath] = useState(null);               // file shown in right pane (overrides cwd)
    const [file, setFile] = useState(null);
    const [fileErr, setFileErr] = useState("");
    const [fileLoading, setFileLoading] = useState(false);
    const [filter, setFilter] = useState("");                     // "Go to file" filter input
    const [allFiles, setAllFiles] = useState(null);               // flat-list cache for fuzzy search
    const [allFilesLoading, setAllFilesLoading] = useState(false);

    // Reset all view state when the branch changes — tree/file/search caches
    // are branch-specific.
    useEffect(() => {
      setDirCache({}); setExpanded({ "": true }); setCwdPath("");
      setFilePath(null); setFile(null); setFileErr("");
      setAllFiles(null); setFilter("");
      loadDir("");
      /* eslint-disable-next-line */
    }, [branch]);

    // Cutover 43.21: open a deep-linked file (from APIHub etc.) — select it in
    // the viewer and expand its parent dirs in the tree.
    useEffect(() => {
      if (!initialFile) return;
      setFilePath(initialFile);
      const segs = initialFile.split("/").slice(0, -1);
      const exp = { "": true }; let acc = "";
      for (const s of segs) { acc = acc ? `${acc}/${s}` : s; exp[acc] = true; if (!dirCache[acc]) loadDir(acc); }
      setExpanded(prev => ({ ...prev, ...exp }));
      onInitialFileConsumed && onInitialFileConsumed();
      /* eslint-disable-next-line */
    }, [initialFile]);

    // Lazy-load the flat file list the first time the user types in the filter.
    useEffect(() => {
      if (!filter || allFiles !== null || allFilesLoading) return;
      setAllFilesLoading(true);
      fetch(`/api/projects/${encodeURIComponent(projectId)}/code/files?_=1${bq}`, { credentials: "include" })
        .then(r => r.json())
        .then(d => setAllFiles(d.files || []))
        .catch(() => setAllFiles([]))
        .finally(() => setAllFilesLoading(false));
    }, [filter, projectId, allFiles, allFilesLoading, branch]);

    // Compute search results: split on space, all tokens must match (case-insensitive)
    // and score by where the match lands — basename matches rank above path matches.
    const searchResults = useMemo(() => {
      const q = (filter || "").trim().toLowerCase();
      if (!q || !allFiles) return null;
      const tokens = q.split(/\s+/).filter(Boolean);
      const scored = [];
      for (const f of allFiles) {
        const p = f.path.toLowerCase();
        const base = p.split("/").pop();
        let score = 0, ok = true;
        for (const t of tokens) {
          const bi = base.indexOf(t);
          const pi = p.indexOf(t);
          if (pi === -1) { ok = false; break; }
          // Boost: basename match (smaller is better; basename start = 0)
          score += bi >= 0 ? bi * 2 : 1000 + pi;
        }
        if (ok) scored.push({ ...f, _score: score });
      }
      scored.sort((a, b) => a._score - b._score || a.path.localeCompare(b.path));
      return scored.slice(0, 50);
    }, [filter, allFiles]);

    function loadDir(p) {
      setDirCache(prev => ({ ...prev, [p]: { ...(prev[p] || {}), loading: true, error: "" } }));
      fetch(`/api/projects/${encodeURIComponent(projectId)}/code/tree?path=${encodeURIComponent(p)}${bq}`, { credentials: "include" })
        .then(r => r.json())
        .then(data => {
          setDirCache(prev => ({
            ...prev,
            [p]: data.error
              ? { loading: false, error: data.error, entries: [] }
              : { loading: false, error: "", entries: data.entries || [] },
          }));
        })
        .catch(e => {
          setDirCache(prev => ({ ...prev, [p]: { loading: false, error: String(e), entries: [] } }));
        });
    }
    useEffect(() => { loadDir(""); /* eslint-disable-next-line */ }, [projectId]);

    function toggleDir(p) {
      const isOpen = !!expanded[p];
      setExpanded(prev => ({ ...prev, [p]: !isOpen }));
      if (!isOpen && !dirCache[p]) loadDir(p);
    }
    // Navigate the right pane into a directory; auto-expand the path in the tree
    function navigateInto(p) {
      setFilePath(null);
      setCwdPath(p);
      if (!dirCache[p]) loadDir(p);
      // expand each parent up to p in the tree
      const segs = p.split("/").filter(Boolean);
      const exp = { "": true };
      let acc = "";
      for (const s of segs) { acc = acc ? `${acc}/${s}` : s; exp[acc] = true; }
      setExpanded(prev => ({ ...prev, ...exp }));
    }

    // Load file contents
    useEffect(() => {
      if (!filePath) { setFile(null); return; }
      let cancelled = false;
      setFileLoading(true); setFileErr("");
      fetch(`/api/projects/${encodeURIComponent(projectId)}/code/file?path=${encodeURIComponent(filePath)}${bq}`, { credentials: "include" })
        .then(r => r.json())
        .then(data => {
          if (cancelled) return;
          if (data.error) setFileErr(data.error);
          else setFile(data);
        })
        .catch(e => { if (!cancelled) setFileErr(String(e)); })
        .finally(() => { if (!cancelled) setFileLoading(false); });
      return () => { cancelled = true; };
    }, [projectId, filePath]);

    function entrySort(a, b) {
      if (a.type !== b.type) return a.type === "dir" ? -1 : 1;
      return a.name.localeCompare(b.name);
    }
    function joinPath(base, name) { return base ? `${base}/${name}` : name; }
    function parentOf(p) { return p.includes("/") ? p.slice(0, p.lastIndexOf("/")) : ""; }
    function fmtSize(n) {
      if (n == null) return "";
      if (n < 1024) return `${n} B`;
      if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
      return `${(n / 1024 / 1024).toFixed(2)} MB`;
    }
    function fmtMtime(s) {
      if (!s) return "—";
      const d = Date.now() / 1000 - s;
      if (d < 60) return "just now";
      if (d < 3600) return `${Math.floor(d / 60)} minutes ago`;
      if (d < 86400) return `${Math.floor(d / 3600)} hours ago`;
      if (d < 86400 * 7) return `${Math.floor(d / 86400)} days ago`;
      if (d < 86400 * 60) return `${Math.floor(d / 86400 / 7)} weeks ago`;
      return new Date(s * 1000).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
    }
    const EXT_LANG = {
      py: "python", js: "javascript", jsx: "javascript", mjs: "javascript",
      ts: "typescript", tsx: "typescript", json: "json", html: "xml", htm: "xml",
      xml: "xml", css: "css", scss: "scss", md: "markdown", markdown: "markdown",
      yml: "yaml", yaml: "yaml", toml: "ini", ini: "ini", env: "ini",
      go: "go", rs: "rust", java: "java", kt: "kotlin", swift: "swift",
      sh: "bash", bash: "bash", zsh: "bash", fish: "bash",
      c: "c", h: "c", cpp: "cpp", hpp: "cpp", cc: "cpp",
      php: "php", rb: "ruby", sql: "sql", graphql: "graphql", proto: "protobuf",
      dockerfile: "dockerfile", makefile: "makefile",
    };
    function hljsLangFor(name) {
      if (!name) return "";
      const fn = name.split("/").pop().toLowerCase();
      if (fn === "dockerfile") return "dockerfile";
      if (fn === "makefile") return "makefile";
      const ext = fn.includes(".") ? fn.split(".").pop() : "";
      return EXT_LANG[ext] || "";
    }
    // Re-highlight when file changes
    const codeRef = React.useRef(null);
    useEffect(() => {
      if (file && !file.binary && codeRef.current && window.hljs) {
        // Reset hljs state and re-highlight
        codeRef.current.removeAttribute("data-highlighted");
        try { window.hljs.highlightElement(codeRef.current); } catch (e) { /* noop */ }
      }
    }, [file]);

    // ------- recursive tree (left pane) -------
    function TreeNode({ path: dirPath, depth }) {
      const node = dirCache[dirPath];
      if (!node) return null;
      if (node.loading && (!node.entries || node.entries.length === 0)) {
        return <li style={{ paddingLeft: 12 + depth * 14 }} className="px-3 py-1 text-xs text-fg-muted">Loading…</li>;
      }
      if (node.error) {
        return <li style={{ paddingLeft: 12 + depth * 14 }} className="px-3 py-1 text-xs text-danger">{node.error}</li>;
      }
      const entries = [...(node.entries || [])].sort(entrySort);
      if (entries.length === 0 && dirPath !== "") {
        return <li style={{ paddingLeft: 12 + depth * 14 }} className="px-3 py-1 text-xs text-fg-muted/70 italic">empty</li>;
      }
      return entries.map(entry => {
        const full = joinPath(dirPath, entry.name);
        const isFile = entry.type === "file";
        const isOpen = !!expanded[full];
        const isSelectedFile = isFile && filePath === full;
        const isCwd = !isFile && cwdPath === full;
        return (
          <React.Fragment key={full}>
            <li>
              <button onClick={() => isFile ? setFilePath(full) : toggleDir(full)}
                      style={{ paddingLeft: 6 + depth * 14 }}
                      className={"w-full text-left pr-2 py-1 rounded text-sm flex items-center gap-1 transition-colors " +
                                 (isSelectedFile
                                   ? "bg-accent-soft text-accent-on-soft font-medium"
                                   : isCwd
                                     ? "bg-bg-tertiary text-fg font-medium"
                                     : "text-fg-secondary hover:bg-bg-hover")}>
                <span className="w-3 inline-flex justify-center shrink-0 text-fg-muted">
                  {isFile ? "" : (isOpen ? "▾" : "▸")}
                </span>
                <span className={"shrink-0 " + (isFile ? "text-fg-muted" : "text-fg-secondary")}>
                  {isFile
                    ? (Icons.file ? <Icons.file size={12} /> : "·")
                    : (Icons.folder ? <Icons.folder size={12} /> : "▪")}
                </span>
                <span className="font-mono truncate flex-1">{entry.name}</span>
              </button>
            </li>
            {!isFile && isOpen && <TreeNode path={full} depth={depth + 1} />}
          </React.Fragment>
        );
      });
    }

    // ------- right pane: dir table or file content -------
    const crumbs = useMemo(() => {
      const parts = (cwdPath || "").split("/").filter(Boolean);
      const out = [{ label: projectId, path: "" }];
      let acc = "";
      for (const p of parts) { acc = acc ? `${acc}/${p}` : p; out.push({ label: p, path: acc }); }
      return out;
    }, [cwdPath, projectId]);

    const cwd = dirCache[cwdPath];
    const cwdEntries = cwd ? [...(cwd.entries || [])].sort(entrySort) : [];
    const latestMtime = cwdEntries.reduce((m, e) => Math.max(m, e.mtime || 0), 0);

    return (
      <div className="grid grid-cols-[300px_1fr] gap-4">
        {/* ============== LEFT: tree pane ============== */}
        <HubCard className="self-start">
          <header className="px-2.5 h-11 border-b border-border flex items-center gap-2">
            {branchList && branchList.length > 0 ? (
              <BranchSelector branches={branchList} value={branch} defaultBranch={defaultBranch}
                              onChange={onBranchChange} metaByName={branchMeta} />
            ) : (
              <span className="text-2xs uppercase tracking-wider font-medium text-fg-muted px-1">Files</span>
            )}
          </header>
          <div className="p-2">
            <div className="flex items-center gap-2 px-2 h-7 bg-bg-tertiary rounded-md border border-transparent focus-within:border-accent focus-within:bg-bg-elevated">
              {Icons.search && <span className="text-fg-muted shrink-0"><Icons.search size={11} /></span>}
              <input className="bare text-sm placeholder:text-fg-muted w-full"
                     placeholder="Go to file"
                     value={filter} onChange={e => setFilter(e.target.value)} />
              {filter && (
                <button onClick={() => setFilter("")} className="text-fg-muted hover:text-fg shrink-0">×</button>
              )}
            </div>
          </div>
          {/* When filter is active, show flat fuzzy-matched results across the
              whole workspace. Otherwise show the regular expandable tree. */}
          {filter ? (
            allFilesLoading && !allFiles ? (
              <div className="px-4 py-6 text-sm text-fg-muted">Searching…</div>
            ) : !searchResults || searchResults.length === 0 ? (
              <div className="px-4 py-6 text-sm text-fg-muted">No files match "{filter}".</div>
            ) : (
              <ul className="px-2 pb-2 max-h-[68vh] overflow-y-auto">
                <li className="px-2 pt-1 pb-1.5 text-2xs uppercase tracking-wider font-medium text-fg-muted">
                  {searchResults.length} result{searchResults.length === 1 ? "" : "s"}
                </li>
                {searchResults.map(f => {
                  const base = f.path.split("/").pop();
                  const dir = f.path.includes("/") ? f.path.slice(0, f.path.lastIndexOf("/")) : "";
                  const isSelected = filePath === f.path;
                  return (
                    <li key={f.path}>
                      <button onClick={() => setFilePath(f.path)}
                              className={"w-full text-left px-2 py-1 rounded text-sm flex items-center gap-2 transition-colors " +
                                         (isSelected
                                           ? "bg-accent-soft text-accent-on-soft font-medium"
                                           : "text-fg-secondary hover:bg-bg-hover")}>
                        <span className="text-fg-muted shrink-0">
                          {Icons.file ? <Icons.file size={12} /> : "·"}
                        </span>
                        <span className="font-mono truncate flex-1 min-w-0">
                          <span className="text-fg">{base}</span>
                          {dir && <span className="text-fg-muted ml-1.5 text-2xs">{dir}</span>}
                        </span>
                      </button>
                    </li>
                  );
                })}
              </ul>
            )
          ) : !dirCache[""] || (dirCache[""].loading && (!dirCache[""]?.entries?.length)) ? (
            <div className="px-4 py-6 text-sm text-fg-muted">Loading…</div>
          ) : dirCache[""]?.error ? (
            <div className="px-4 py-6 text-sm text-danger">{dirCache[""].error}</div>
          ) : (
            <ul className="px-2 pb-2 max-h-[68vh] overflow-y-auto">
              <li>
                <button onClick={() => navigateInto("")}
                        className={"w-full text-left px-2 py-1 rounded text-sm flex items-center gap-1.5 transition-colors " +
                                   (cwdPath === "" && !filePath
                                     ? "bg-bg-tertiary text-fg font-medium"
                                     : "text-fg-secondary hover:bg-bg-hover")}>
                  <span className="text-fg-muted">/</span>
                  <span className="font-mono">{projectId}</span>
                </button>
              </li>
              <TreeNode path="" depth={0} />
            </ul>
          )}
        </HubCard>

        {/* ============== RIGHT: dir table OR file viewer ============== */}
        <HubCard className="self-start">
          {/* Breadcrumb header */}
          <header className="px-4 h-11 border-b border-border flex items-center gap-2 text-sm overflow-x-auto whitespace-nowrap bg-bg-secondary/40">
            {crumbs.map((c, i) => (
              <React.Fragment key={c.path}>
                {i > 0 && <span className="text-fg-muted/60">/</span>}
                <button onClick={() => { setFilePath(null); setCwdPath(c.path); }}
                        className={"font-mono px-1 rounded hover:underline " +
                                   (i === crumbs.length - 1 && !filePath ? "text-fg font-semibold" : "text-accent")}>
                  {c.label}
                </button>
              </React.Fragment>
            ))}
            {filePath && (
              <>
                <span className="text-fg-muted/60">/</span>
                <code className="font-mono px-1 text-fg font-semibold">{filePath.split("/").pop()}</code>
              </>
            )}
          </header>

          {/* ----- FILE VIEW ----- */}
          {filePath ? (
            fileLoading && !file ? (
              <div className="px-4 py-8 text-sm text-fg-muted">Loading {filePath}…</div>
            ) : fileErr ? (
              <div className="px-4 py-8">
                <div className="text-sm text-danger">{fileErr}</div>
                <button onClick={() => setFilePath(null)} className="btn-px btn-px-ghost btn-px-sm mt-3">Close</button>
              </div>
            ) : file ? (
              <>
                <div className="px-4 h-9 flex items-center gap-3 border-b border-border text-2xs text-fg-muted bg-bg">
                  <span className="tabular-nums">{fmtSize(file.size)}</span>
                  {file.lines != null && !file.binary && (
                    <><span className="text-fg-muted/40">·</span><span className="tabular-nums">{file.lines} lines</span></>
                  )}
                  {file.truncated && (
                    <span className="ml-auto px-1.5 py-0.5 rounded bg-warning-soft text-warning font-medium">truncated</span>
                  )}
                  {file.binary && (
                    <span className="ml-auto px-1.5 py-0.5 rounded bg-bg-tertiary text-fg-muted font-medium">binary</span>
                  )}
                </div>
                {file.binary ? (
                  <div className="px-4 py-8 text-sm text-fg-muted">Binary file — preview not shown.</div>
                ) : (
                  <div className="p-3">
                    <div className="rounded-md border border-border overflow-hidden bg-bg">
                      <pre className="p-4 m-0 overflow-auto text-xs leading-relaxed font-mono"
                           style={{ maxHeight: "70vh" }}>
                        <code ref={codeRef}
                              className={"hljs " + (hljsLangFor(file.path) ? `language-${hljsLangFor(file.path)}` : "")}>
                          {file.content}
                        </code>
                      </pre>
                    </div>
                  </div>
                )}
              </>
            ) : null
          ) : (
            /* ----- DIRECTORY TABLE VIEW ----- */
            <>
              {/* Commit banner */}
              <div className="px-4 h-10 flex items-center gap-2.5 border-b border-border text-xs text-fg-muted bg-bg">
                {Icons.branch && <span className="text-fg-muted"><Icons.branch size={12} /></span>}
                <span className="text-fg-secondary">workspace files</span>
                <span className="text-fg-muted/40">·</span>
                <span>{cwdEntries.length} item{cwdEntries.length === 1 ? "" : "s"}</span>
                {latestMtime > 0 && (
                  <>
                    <span className="text-fg-muted/40">·</span>
                    <span>updated {fmtMtime(latestMtime)}</span>
                  </>
                )}
              </div>

              {!cwd || (cwd.loading && (!cwd.entries || cwd.entries.length === 0)) ? (
                <div className="px-4 py-8 text-sm text-fg-muted">Loading…</div>
              ) : cwd.error ? (
                <div className="px-4 py-8 text-sm text-danger">{cwd.error}</div>
              ) : cwdEntries.length === 0 ? (
                <div className="px-4 py-10 text-sm text-fg-muted text-center">Empty directory.</div>
              ) : (
                <ul className="divide-y divide-border">
                  {cwdPath !== "" && (
                    <li>
                      <button onClick={() => navigateInto(parentOf(cwdPath))}
                              className="w-full text-left px-4 py-2 flex items-center gap-3 hover:bg-bg-hover transition-colors text-sm">
                        <span className="w-4 inline-flex justify-center text-fg-muted">↰</span>
                        <code className="font-mono text-accent">..</code>
                      </button>
                    </li>
                  )}
                  {cwdEntries.map(entry => {
                    const full = joinPath(cwdPath, entry.name);
                    const isFile = entry.type === "file";
                    return (
                      <li key={entry.name}>
                        <button onClick={() => isFile ? setFilePath(full) : navigateInto(full)}
                                className="w-full text-left px-4 py-2 grid grid-cols-[1fr_180px] gap-3 items-center hover:bg-bg-hover transition-colors text-sm">
                          <div className="flex items-center gap-3 min-w-0">
                            <span className={"w-4 inline-flex justify-center shrink-0 " + (isFile ? "text-fg-muted" : "text-info")}>
                              {isFile
                                ? (Icons.file ? <Icons.file size={14} /> : "·")
                                : (Icons.folder ? <Icons.folder size={14} /> : "▪")}
                            </span>
                            <code className={"font-mono truncate " + (isFile ? "text-fg" : "text-accent font-medium")}>{entry.name}</code>
                          </div>
                          <div className="text-2xs text-fg-muted text-right tabular-nums">
                            {isFile && <span className="mr-3">{fmtSize(entry.size)}</span>}
                            {entry.mtime ? <span>{fmtMtime(entry.mtime)}</span> : null}
                          </div>
                        </button>
                      </li>
                    );
                  })}
                </ul>
              )}
            </>
          )}
        </HubCard>
      </div>
    );
  }

  // ===========================================================================
  // Cutover 43.7+10: CodeHub — GitHub-style list + PR detail view (sub-route)
  // ===========================================================================
  function CodeHubPage({ projectId, hub, state, subResource, subResourceId }) {
    // Sub-resource routing: PR detail, branch detail, or list view.
    if (subResource === "pr" && subResourceId) {
      return <PRDetailView projectId={projectId} hub={hub} state={state} prId={subResourceId} />;
    }
    if (subResource === "branch" && subResourceId) {
      return <BranchDetailView projectId={projectId} hub={hub} state={state} branchName={subResourceId} />;
    }
    return <CodeHubListView projectId={projectId} hub={hub} state={state} />;
  }

  function CodeHubListView({ projectId, hub, state }) {
    const Icons = window.Icons || {};
    const prs = Object.values(hub?.pull_requests || {});
    const commits = Object.values(hub?.commits || {}).sort((a, b) => (b.created_at || 0) - (a.created_at || 0));
    const branches = Object.values(hub?.branches || {});
    const reviews = Object.values(hub?.code_reviews || {});
    const checks = Object.values(hub?.checks || {});
    const releases = Object.values(hub?.releases || {}).sort((a, b) => (b.created_at || 0) - (a.created_at || 0));

    const openPRs = prs.filter(p => p.merge_state !== "merged" && p.merge_state !== "closed");
    const mergedPRs = prs.filter(p => p.merge_state === "merged");
    const closedPRs = prs.filter(p => p.merge_state === "closed");

    // --- Branch state (shared across Code / Commits / Branches tabs) ---
    const [branchList, setBranchList] = useState([]);
    const [defaultBranch, setDefaultBranch] = useState("main");
    const [branch, setBranch] = useState("main");
    const [gitBacked, setGitBacked] = useState(false);
    useEffect(() => {
      fetch(`/api/projects/${encodeURIComponent(projectId)}/code/branches`, { credentials: "include" })
        .then(r => r.json())
        .then(d => {
          const list = d.branches || [];
          setBranchList(list);
          setGitBacked(!!d.git);
          const def = d.default || "main";
          setDefaultBranch(def);
          setBranch(prev => (list.includes(prev) ? prev : def));
        })
        .catch(() => {});
    }, [projectId]);
    // branchName -> metadata (owner, head, commits, _updated_at). Branch ids are
    // "repo:name"; key by the .name field.
    const branchMeta = useMemo(() => {
      const m = {};
      for (const b of branches) if (b.name) m[b.name] = b;
      return m;
    }, [branches]);
    // PRs indexed by source branch (for the Branches tab)
    const prBySourceBranch = useMemo(() => {
      const m = {};
      for (const p of prs) {
        const src = p.source_branch || p.head;
        if (src && !m[src]) m[src] = p;
      }
      return m;
    }, [prs]);

    // Cutover 43.21: deep-link from elsewhere (e.g. APIHub consumer/test file)
    // lands here with a pending file to open in the code browser.
    const pendingFile = useMemo(() => {
      const p = window.__envgenPendingCodeFile;
      if (p) { window.__envgenPendingCodeFile = null; return p; }
      return null;
    }, []);
    const [tab, setTab] = useState(pendingFile ? "code" : "code");
    const [initialFile, setInitialFile] = useState(pendingFile?.path || null);
    const [prFilter, setPrFilter] = useState("open"); // open | merged | closed | all
    const [search, setSearch] = useState("");
    const [showOpenForm, setShowOpenForm] = useState(false);
    const [pfTitle, setPfTitle] = useState("");
    const [pfHead, setPfHead] = useState("feature");
    const [pfBase, setPfBase] = useState("main");
    const [pfAuthor, setPfAuthor] = useState("ui_user");
    const [pfPending, setPfPending] = useState(false);
    const [pfError, setPfError] = useState("");
    const nav = (p) => window.LiveMonitorRouter.navigateTo(p);

    const filteredPRs = useMemo(() => {
      let list = prs;
      if (prFilter === "open") list = openPRs;
      else if (prFilter === "merged") list = mergedPRs;
      else if (prFilter === "closed") list = closedPRs;
      if (search.trim()) {
        const q = search.trim().toLowerCase();
        list = list.filter(p =>
          (p.title || "").toLowerCase().includes(q) ||
          (p.id || "").toLowerCase().includes(q) ||
          (p.author || "").toLowerCase().includes(q) ||
          (p.head || "").toLowerCase().includes(q));
      }
      return list.sort((a, b) => (b.created_at || 0) - (a.created_at || 0));
    }, [prs, openPRs, mergedPRs, closedPRs, prFilter, search]);

    function resetForm() {
      setPfTitle(""); setPfHead("feature"); setPfBase("main");
      setPfAuthor("ui_user"); setPfError("");
    }
    async function submitOpenPR() {
      if (!pfTitle.trim()) { setPfError("Title is required."); return; }
      if (!pfHead.trim()) { setPfError("Head branch is required."); return; }
      setPfPending(true); setPfError("");
      try {
        const number = String(Date.now() % 100000);
        const r = await fetch(`/api/projects/${encodeURIComponent(projectId)}/codehub/pull_requests`, {
          method: "POST", headers: { "Content-Type": "application/json" }, credentials: "include",
          body: JSON.stringify({ number, title: pfTitle.trim(), head: pfHead.trim(), base: pfBase.trim() || "main", author: pfAuthor.trim() }),
        });
        const data = await r.json();
        if (data.error) { setPfError(data.error); setPfPending(false); return; }
        setShowOpenForm(false); resetForm();
        window.LiveMonitorRefresh?.();
      } catch (e) { setPfError(String(e)); }
      finally { setPfPending(false); }
    }

    // Per-row inline merge confirm + error state (no popups)
    const [confirmingMerge, setConfirmingMerge] = useState(null); // pr.id
    const [rowError, setRowError] = useState(null);                // {pr_id, msg}
    const [rowPending, setRowPending] = useState(null);            // pr.id
    async function mergePR(pr_id) {
      setRowPending(pr_id);
      setRowError(null);
      try {
        const r = await fetch(`/api/projects/${encodeURIComponent(projectId)}/codehub/pull_requests/${encodeURIComponent(pr_id)}/merge`, {
          method: "POST", headers: { "Content-Type": "application/json" }, credentials: "include",
          body: JSON.stringify({}),
        });
        const data = await r.json();
        if (data.error) setRowError({ pr_id, msg: data.error });
        else { window.LiveMonitorRefresh?.(); setConfirmingMerge(null); }
      } catch (e) { setRowError({ pr_id, msg: String(e) }); }
      finally { setRowPending(null); }
    }

    return (
      <HubLayout>
        {/* Metric tiles */}
        <div className="grid grid-cols-4 gap-3 mb-5">
          <MetricTile label="Open PRs" value={openPRs.length} sub={openPRs.length === 0 ? "all clear" : `${openPRs.filter(p => p.merge_state === "ready").length} ready to merge`}
                      icon={Icons.code} tone={openPRs.length > 0 ? "info" : "neutral"} />
          <MetricTile label="Merged" value={mergedPRs.length} sub="all-time" icon={Icons.shieldCheck} tone="success" />
          <MetricTile label="Branches" value={branches.length} sub={`${commits.length} commits total`} icon={Icons.workhub} />
          <MetricTile label="Reviews" value={reviews.length} sub={`${reviews.filter(r => r.state === "approve").length} approved`} icon={Icons.clipboard} />
        </div>

        {/* Tab bar */}
        <TabBar current={tab} onChange={setTab} tabs={[
          { key: "code", label: "Code" },
          { key: "prs", label: "Pull requests", count: prs.length },
          { key: "commits", label: "Commits", count: commits.length },
          { key: "branches", label: "Branches", count: branches.length },
          { key: "reviews", label: "Reviews", count: reviews.length },
          { key: "checks", label: "Checks", count: checks.length },
          { key: "releases", label: "Releases", count: releases.length },
        ]} />

        {/* ===== Code tab ===== */}
        {tab === "code" && (
          <CodeBrowser projectId={projectId} branch={branch} branchList={branchList}
                       defaultBranch={defaultBranch} onBranchChange={setBranch} branchMeta={branchMeta}
                       initialFile={initialFile} onInitialFileConsumed={() => setInitialFile(null)} />
        )}

        {/* ===== PR tab ===== */}
        {tab === "prs" && (
          <HubCard>
            <HubCardHeader title="Pull requests" actions={
              <div className="flex items-center gap-2">
                {/* Filter chips */}
                <div className="flex items-center gap-1 mr-2">
                  {[
                    { key: "open", label: "Open", count: openPRs.length },
                    { key: "merged", label: "Merged", count: mergedPRs.length },
                    { key: "closed", label: "Closed", count: closedPRs.length },
                    { key: "all", label: "All", count: prs.length },
                  ].map(f => (
                    <button key={f.key} onClick={() => setPrFilter(f.key)}
                            className={"h-7 px-2.5 text-sm rounded-md transition-colors " +
                                       (prFilter === f.key
                                         ? "bg-bg-tertiary text-fg font-medium"
                                         : "text-fg-secondary hover:bg-bg-hover")}>
                      {f.label} <span className="text-2xs text-fg-muted tabular-nums ml-0.5">{f.count}</span>
                    </button>
                  ))}
                </div>
                <div className="flex items-center gap-2 px-2 h-8 bg-bg-tertiary rounded-md border border-transparent focus-within:border-accent focus-within:bg-bg-elevated">
                  {Icons.search && <span className="text-fg-muted"><Icons.search size={12} /></span>}
                  <input className="bare text-sm placeholder:text-fg-muted w-44"
                         placeholder="Filter PRs..." value={search} onChange={e => setSearch(e.target.value)} />
                </div>
                <button onClick={() => { setShowOpenForm(s => !s); setPfError(""); }}
                        className={"btn-px btn-px-sm " + (showOpenForm ? "btn-px-ghost" : "btn-px-primary")}>
                  {showOpenForm ? "Cancel" : <>{Icons.plus && <Icons.plus size={12} />} Open PR</>}
                </button>
              </div>
            } />

            {/* Inline "Open PR" form */}
            {showOpenForm && (
              <div className="px-4 py-4 border-b border-border bg-bg-secondary/40">
                <div className="text-md font-semibold text-fg mb-3">Open a new pull request</div>
                {pfError && (
                  <div className="mb-3 px-3 py-2 rounded-md bg-danger-soft text-danger text-base">{pfError}</div>
                )}
                <div className="grid grid-cols-2 gap-3">
                  <div className="col-span-2">
                    <label className="block text-sm font-medium text-fg mb-1.5">Title <span className="text-danger">*</span></label>
                    <input className="input-px w-full" value={pfTitle} onChange={e => setPfTitle(e.target.value)}
                           placeholder="What does this PR do?" autoFocus />
                  </div>
                  <div>
                    <label className="block text-sm font-medium text-fg mb-1.5">Head branch <span className="text-danger">*</span></label>
                    <input className="input-px w-full font-mono" value={pfHead} onChange={e => setPfHead(e.target.value)}
                           placeholder="feature/...." />
                  </div>
                  <div>
                    <label className="block text-sm font-medium text-fg mb-1.5">Base branch</label>
                    <input className="input-px w-full font-mono" value={pfBase} onChange={e => setPfBase(e.target.value)}
                           placeholder="main" />
                  </div>
                  <div>
                    <label className="block text-sm font-medium text-fg mb-1.5">Author</label>
                    <input className="input-px w-full" value={pfAuthor} onChange={e => setPfAuthor(e.target.value)}
                           placeholder="ui_user" />
                  </div>
                </div>
                <div className="mt-4 flex justify-end gap-2">
                  <button onClick={() => { setShowOpenForm(false); resetForm(); }}
                          className="btn-px btn-px-ghost btn-px-sm">Cancel</button>
                  <button onClick={submitOpenPR} disabled={pfPending || !pfTitle.trim() || !pfHead.trim()}
                          className="btn-px btn-px-primary btn-px-sm">
                    {pfPending ? "Opening…" : <>{Icons.plus && <Icons.plus size={12} />} Open pull request</>}
                  </button>
                </div>
              </div>
            )}

            {filteredPRs.length === 0 && !showOpenForm ? (
              <EmptyState icon={Icons.code}
                title={prFilter === "open" ? "No open pull requests" : `No ${prFilter} PRs`}
                sub={prs.length === 0 ? "Agents open PRs as they finish features. Or open one manually." : "Try a different filter or search term."}
                actionLabel={prs.length === 0 ? "Open the first PR" : null}
                onAction={prs.length === 0 ? () => setShowOpenForm(true) : null} />
            ) : filteredPRs.length === 0 ? null : (
              <ul className="p-3 space-y-2">
                {filteredPRs.map(pr => {
                  const visual = prStateVisual(pr.merge_state || "open");
                  const prReviews = reviews.filter(r => r.pr_id === pr.id);
                  const approved = prReviews.filter(r => r.state === "approve").length;
                  const isConfirming = confirmingMerge === pr.id;
                  const showError = rowError?.pr_id === pr.id;
                  const isPending = rowPending === pr.id;
                  return (
                    <li key={pr.id} className="group relative border border-border-strong rounded-md bg-bg-elevated hover:shadow-sm transition-all overflow-hidden">
                      <div onClick={() => nav(`/projects/${encodeURIComponent(projectId)}/codehub/pr/${encodeURIComponent(pr.id)}`)}
                           className="flex items-start gap-3 px-4 py-3 hover:bg-bg-hover transition-colors cursor-pointer">
                        <span className="absolute left-0 top-0 bottom-0 w-0.5 bg-transparent group-hover:bg-accent transition-colors" />
                        {/* state icon */}
                        <span className="mt-0.5 w-6 h-6 rounded-full flex items-center justify-center shrink-0 text-xs font-semibold"
                              style={{
                                background: visual.bg, color: visual.color,
                                boxShadow: `inset 0 1px 0 rgba(255,255,255,0.4), 0 0 0 1px ${visual.color === "var(--text-muted)" ? "var(--border)" : `color-mix(in srgb, ${visual.color} 30%, transparent)`}`,
                              }}>
                          {pr.merge_state === "merged" ? "✓" :
                           pr.merge_state === "closed" ? "✕" :
                           pr.merge_state === "changes_requested" ? "!" : "●"}
                        </span>
                        {/* main */}
                        <div className="flex-1 min-w-0">
                          <div className="flex items-baseline gap-2 mb-1">
                            <span className="text-md font-semibold text-fg truncate tracking-tight group-hover:text-accent transition-colors">{pr.title || "(untitled)"}</span>
                            <code className="font-mono text-xs text-fg-muted shrink-0">#{(pr.number || pr.id || "").toString().substr(0, 8)}</code>
                          </div>
                          <div className="flex items-center flex-wrap gap-x-2 gap-y-1 text-xs text-fg-muted">
                            <span style={{ color: visual.color }} className="font-medium">{visual.label}</span>
                            <span className="text-fg-muted/40">·</span>
                            <ActorChip name={pr.author || "system"} size={14} />
                            <span className="text-fg-muted/40">·</span>
                            <span className="inline-flex items-center gap-1">
                              <code className="font-mono">{pr.head || "?"}</code>
                              <span className="text-fg-muted/60">→</span>
                              <code className="font-mono">{pr.base || "main"}</code>
                            </span>
                            <span className="text-fg-muted/40">·</span>
                            <span>opened {fmtRel(pr.created_at)}</span>
                            {prReviews.length > 0 && (
                              <>
                                <span className="text-fg-muted/40">·</span>
                                <span className={approved === prReviews.length ? "text-success" : "text-warning"}>
                                  {approved}/{prReviews.length} approvals
                                </span>
                              </>
                            )}
                          </div>
                        </div>
                        {/* hover actions / inline confirm — merge only when truly ready */}
                        <div onClick={(e) => e.stopPropagation()} className="flex items-center gap-1.5 shrink-0">
                          {isConfirming ? (
                            <>
                              <span className="text-xs text-fg-secondary mr-1">Merge to <code className="font-mono">{pr.base}</code>?</span>
                              <button onClick={() => { setConfirmingMerge(null); setRowError(null); }}
                                      className="btn-px btn-px-ghost btn-px-sm">Cancel</button>
                              <button onClick={() => mergePR(pr.id)} disabled={isPending}
                                      className="btn-px btn-px-primary btn-px-sm">{isPending ? "Merging…" : "Confirm merge"}</button>
                            </>
                          ) : (
                            pr.merge_state === "ready" && (
                              <button onClick={() => { setConfirmingMerge(pr.id); setRowError(null); }}
                                      className="opacity-0 group-hover:opacity-100 transition-opacity btn-px btn-px-primary btn-px-sm">
                                {Icons.shieldCheck && <Icons.shieldCheck size={12} />} Merge
                              </button>
                            )
                          )}
                        </div>
                      </div>
                      {/* inline error */}
                      {showError && (
                        <div className="px-4 pb-3 -mt-1">
                          <div className="px-3 py-2 rounded-md bg-danger-soft text-danger text-xs flex items-center justify-between">
                            <span>⚠ {rowError.msg}</span>
                            <button onClick={() => setRowError(null)} className="text-danger hover:opacity-70">×</button>
                          </div>
                        </div>
                      )}
                    </li>
                  );
                })}
              </ul>
            )}
          </HubCard>
        )}

        {/* ===== Commits tab (branch-scoped) ===== */}
        {tab === "commits" && (() => {
          const scoped = commits.filter(c => !branch || c.branch === branch);
          return (
            <HubCard>
              <header className="flex items-center gap-3 px-4 h-11 border-b border-border">
                <h3 className="text-md font-semibold tracking-tight">Commits</h3>
                {branchList.length > 0 && (
                  <BranchSelector branches={branchList} value={branch} defaultBranch={defaultBranch}
                                  onChange={setBranch} metaByName={branchMeta} />
                )}
                <span className="text-sm text-fg-muted">{scoped.length} on <code className="font-mono">{branch}</code></span>
              </header>
              {scoped.length === 0 ? (
                <EmptyState icon={Icons.code} title="No commits on this branch"
                  sub="Switch branch above, or commits will appear here once agents write code on this branch." />
              ) : (
                <ul className="p-3 space-y-2">
                  {scoped.slice(0, 50).map(c => (
                    <li key={c.id || c.sha} className="flex items-start gap-3 px-4 py-3 border border-border rounded-md bg-bg-elevated hover:border-border-strong hover:bg-bg-hover transition-all">
                      <ActorChip name={c.author || "system"} />
                      <div className="flex-1 min-w-0">
                        <div className="text-md text-fg leading-snug truncate">{c.diff_summary || c.message || c.msg || "(no message)"}</div>
                        <div className="text-xs text-fg-muted flex items-center gap-2 mt-0.5">
                          <code className="font-mono">{(c.commit_hash || c.sha || c.id || "").substr(0, 8)}</code>
                          <span className="text-fg-muted/40">·</span>
                          <span>{fmtRel(c.created_at)}</span>
                          {c.branch && <>
                            <span className="text-fg-muted/40">·</span>
                            <code className="font-mono">{c.branch}</code>
                          </>}
                        </div>
                      </div>
                    </li>
                  ))}
                  {scoped.length > 50 && (
                    <li className="px-4 py-3 text-center text-sm text-fg-muted">Showing 50 of {scoped.length} commits.</li>
                  )}
                </ul>
              )}
            </HubCard>
          );
        })()}

        {/* ===== Branches tab ===== */}
        {tab === "branches" && (
          <HubCard>
            <HubCardHeader title="Branches" subtitle={`${branches.length} total`} />
            {branches.length === 0 ? (
              <EmptyState icon={Icons.workhub} title="No branches" sub="Branches appear once an agent calls CodeHub.create_branch." />
            ) : (
              <ul className="p-3 space-y-2">
                {branches.map(b => {
                  const isDefault = b.name === "main" || b.name === b.base;
                  const branchCommits = commits.filter(c => c.branch === b.name);
                  const branchPRs = prs.filter(p => p.head === b.name);
                  return (
                    <li key={b.id || b.name}
                        onClick={() => nav(`/projects/${encodeURIComponent(projectId)}/codehub/branch/${encodeURIComponent(b.name)}`)}
                        className="group flex items-center gap-3 px-4 py-3 border border-border-strong rounded-md bg-bg-elevated hover:bg-bg-hover hover:shadow-sm transition-all cursor-pointer">
                      {Icons.branch && <span className="text-fg-muted shrink-0"><Icons.branch size={14} /></span>}
                      <div className="flex-1 min-w-0">
                        <div className="flex items-baseline gap-2">
                          <span className="font-mono text-md font-semibold text-fg truncate group-hover:text-accent transition-colors">{b.name}</span>
                          {isDefault && <span className="text-2xs uppercase tracking-wider font-semibold px-1.5 py-0.5 rounded bg-bg-tertiary text-fg-muted">default</span>}
                        </div>
                        <div className="text-xs text-fg-muted flex items-center gap-2 mt-0.5">
                          <code className="font-mono">{(b.head || "").substr(0, 8)}</code>
                          {b.owner && (<><span className="text-fg-muted/40">·</span><span>owner <span className="text-fg-secondary">{b.owner}</span></span></>)}
                          {b.base && !isDefault && (<><span className="text-fg-muted/40">·</span><span>from <code className="font-mono">{b.base}</code></span></>)}
                          <span className="text-fg-muted/40">·</span>
                          <span>{(b.commits?.length ?? branchCommits.length)} commit{(b.commits?.length ?? branchCommits.length) === 1 ? "" : "s"}</span>
                          <span className="text-fg-muted/40">·</span>
                          <span>updated {fmtRel(b._updated_at || b.created_at)}</span>
                        </div>
                      </div>
                      {/* actions */}
                      <div onClick={(e) => e.stopPropagation()} className="flex items-center gap-1.5 shrink-0">
                        <button onClick={() => { setBranch(b.name); setTab("code"); }}
                                className="btn-px btn-px-ghost btn-px-sm opacity-0 group-hover:opacity-100 transition-opacity"
                                title="Browse this branch's files">
                          Browse files
                        </button>
                        {branchPRs.length > 0 ? (
                          <span className="text-2xs text-info font-medium">
                            {branchPRs.length} open PR{branchPRs.length === 1 ? "" : "s"}
                          </span>
                        ) : !isDefault ? (
                          <span className="text-2xs text-fg-muted">no PR</span>
                        ) : null}
                      </div>
                      {Icons.chevronRight && <span className="text-fg-muted shrink-0 opacity-0 group-hover:opacity-100 transition-opacity"><Icons.chevronRight size={14} /></span>}
                    </li>
                  );
                })}
              </ul>
            )}
          </HubCard>
        )}

        {/* ===== Reviews tab ===== */}
        {tab === "reviews" && (
          <HubCard>
            <HubCardHeader title="Code reviews" subtitle={`${reviews.length} total`} />
            {reviews.length === 0 ? (
              <EmptyState icon={Icons.clipboard} title="No reviews yet" sub="Reviews appear when agents submit them via CodeHub.submit_review." />
            ) : (
              <ul className="p-3 space-y-2">
                {reviews.sort((a,b)=> ((b.created_at||b.submitted_at||b._updated_at||0)-(a.created_at||a.submitted_at||a._updated_at||0))).slice(0, 30).map(r => {
                  const tone = { approve: "text-success", request_changes: "text-warning", comment: "text-info" }[r.state] || "text-fg-secondary";
                  return (
                    <li key={r.id} className="px-4 py-3 border border-border-strong rounded-md bg-bg-elevated hover:bg-bg-hover transition-all">
                      <div className="flex items-center gap-2.5 mb-1">
                        <ActorChip name={r.reviewer || "system"} />
                        <span className={"text-xs font-mono font-semibold " + tone}>{r.state}</span>
                        <code className="font-mono text-xs text-fg-muted ml-auto">PR {(r.pr_id || "").substr(0, 8)}</code>
                        <span className="text-xs text-fg-muted">{fmtRel(r.created_at || r.submitted_at || r._updated_at)}</span>
                      </div>
                      {r.reason && <div className="text-sm text-fg-secondary mt-1 line-clamp-2">{r.reason}</div>}
                      {Array.isArray(r.inline_comments) && r.inline_comments.length > 0 && (
                        <div className="text-2xs text-fg-muted mt-1">{r.inline_comments.length} inline comment{r.inline_comments.length === 1 ? "" : "s"}</div>
                      )}
                    </li>
                  );
                })}
              </ul>
            )}
          </HubCard>
        )}

        {/* ===== Checks tab ===== */}
        {tab === "checks" && (
          <HubCard>
            <HubCardHeader title="Checks" subtitle={`${checks.length} recorded`} />
            {checks.length === 0 ? (
              <EmptyState icon={Icons.shieldCheck} title="No checks yet" sub="CI / verification checks recorded by agents land here." />
            ) : (
              <ul className="p-3 space-y-2">
                {checks.sort((a,b)=> (b.updated_at||0)-(a.updated_at||0)).slice(0, 50).map(c => {
                  const tone = { passed: "text-success", failed: "text-danger", skipped: "text-fg-muted", error: "text-danger" }[c.status] || "text-fg-secondary";
                  return (
                    <li key={c.id || c.name + c.pr_id} className="px-4 py-3 flex items-start gap-3 border border-border-strong rounded-md bg-bg-elevated hover:bg-bg-hover transition-all">
                      <span className={"text-xs font-mono font-semibold mt-0.5 " + tone}>{c.status}</span>
                      <div className="flex-1 min-w-0">
                        <div className="text-md text-fg">{c.name || "(unnamed check)"}</div>
                        <div className="text-xs text-fg-muted flex items-center gap-2 mt-0.5">
                          {c.pr_id && <code className="font-mono">PR {(c.pr_id || "").substr(0, 8)}</code>}
                          <ActorChip name={c.agent || "system"} />
                          <span>{fmtRel(c.updated_at || c.created_at)}</span>
                        </div>
                      </div>
                    </li>
                  );
                })}
              </ul>
            )}
          </HubCard>
        )}

        {/* ===== Releases tab ===== */}
        {tab === "releases" && (
          <HubCard>
            <HubCardHeader title="Releases" subtitle={`${releases.length} tagged`} />
            {releases.length === 0 ? (
              <EmptyState icon={Icons.shieldCheck} title="No releases yet"
                sub="Agents cut releases via codehub_create_release — version tag, notes, and the commit it points to." />
            ) : (
              <ul className="p-3 space-y-2">
                {releases.map(r => (
                  <li key={r.id || r.tag || r.version} className="px-4 py-3 border border-border rounded-md bg-bg-elevated hover:border-border-strong hover:bg-bg-hover transition-all">
                    <div className="flex items-center gap-2.5 flex-wrap">
                      <span className="font-mono text-md font-semibold text-accent">{r.tag || r.version || r.name}</span>
                      {r.target && <code className="font-mono text-2xs text-fg-muted">{(r.target || "").substr(0, 8)}</code>}
                      {r.branch && <code className="font-mono text-2xs text-fg-muted">{r.branch}</code>}
                      <ActorChip name={r.created_by || r.author || "system"} />
                      <span className="text-2xs text-fg-muted ml-auto">{fmtRel(r.created_at)}</span>
                    </div>
                    {(r.notes || r.description) && (
                      <div className="text-sm text-fg-secondary mt-1.5 leading-snug">{r.notes || r.description}</div>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </HubCard>
        )}
      </HubLayout>
    );
  }

  // ===========================================================================
  // Cutover 43.10: PR Detail view — full pipeline visibility for one PR
  // ===========================================================================
  function PRDetailView({ projectId, hub, state, prId }) {
    const Icons = window.Icons || {};
    const prs = hub?.pull_requests || {};
    const pr = prs[prId];
    const reviews = Object.values(hub?.code_reviews || {}).filter(r => r.pr_id === prId)
                          .sort((a, b) => (a.created_at || 0) - (b.created_at || 0));
    const checks = Object.values(hub?.checks || {}).filter(c => c.pr_id === prId)
                          .sort((a, b) => (b.updated_at || a.updated_at || 0) - (a.updated_at || a.updated_at || 0));
    // Commits on the PR's head branch
    const commits = Object.values(hub?.commits || {})
      .filter(c => !pr?.head || c.branch === pr.head || c.repo_id === pr.repo_id)
      .filter(c => !pr?.head || c.branch === pr.head)
      .sort((a, b) => (b.created_at || 0) - (a.created_at || 0));
    // EventHub events related to this PR
    const events = Object.values(state?.hubs?.eventhub?.events || {})
      .filter(e => {
        const p = e.payload || {};
        return (p.pr_id === prId) || (p.id === prId);
      })
      .sort((a, b) => (b.created_at || 0) - (a.created_at || 0));

    const nav = (p) => window.LiveMonitorRouter.navigateTo(p);
    const backToList = () => nav(`/projects/${encodeURIComponent(projectId)}/codehub`);

    if (!pr) {
      return (
        <HubLayout>
          <button onClick={backToList} className="flex items-center gap-1.5 text-sm text-fg-secondary hover:text-accent mb-4">
            {Icons.chevronLeft && <Icons.chevronLeft size={14} />} Back to pull requests
          </button>
          <EmptyState icon={Icons.code} title="PR not found"
            sub={`No PR with id ${prId} exists in this project.`}
            actionLabel="Back to CodeHub" onAction={backToList} />
        </HubLayout>
      );
    }

    const visual = prStateVisual(pr.merge_state || "open");
    const approved = reviews.filter(r => r.state === "approve").length;
    const requested = reviews.filter(r => r.state === "request_changes").length;
    const passedChecks = checks.filter(c => c.status === "passed").length;
    const failedChecks = checks.filter(c => c.status === "failed").length;

    // Action inline state — all inline, no popups
    const [confirmMerge, setConfirmMerge] = useState(false);
    const [forceMode, setForceMode] = useState(false);
    const [forceReason, setForceReason] = useState("");
    const [showReview, setShowReview] = useState(false);
    const [actionError, setActionError] = useState("");
    const [actionPending, setActionPending] = useState(false);
    const [successMsg, setSuccessMsg] = useState("");

    async function doMerge() {
      setActionPending(true); setActionError("");
      try {
        const r = await fetch(`/api/projects/${encodeURIComponent(projectId)}/codehub/pull_requests/${encodeURIComponent(prId)}/merge`, {
          method: "POST", headers: { "Content-Type": "application/json" }, credentials: "include",
          body: JSON.stringify({}),
        });
        const data = await r.json();
        if (data.error) setActionError(data.error);
        else { setSuccessMsg("Merged."); setConfirmMerge(false); window.LiveMonitorRefresh?.(); }
      } catch (e) { setActionError(String(e)); }
      finally { setActionPending(false); }
    }
    async function doForceMerge() {
      if (forceReason.trim().length < 5) { setActionError("Reason must be ≥5 chars."); return; }
      setActionPending(true); setActionError("");
      try {
        const r = await fetch(`/api/projects/${encodeURIComponent(projectId)}/codehub/pull_requests/${encodeURIComponent(prId)}/force_merge`, {
          method: "POST", headers: { "Content-Type": "application/json" }, credentials: "include",
          body: JSON.stringify({ force: true, agent: "ui_user", reason: forceReason.trim() }),
        });
        const data = await r.json();
        if (data.error) setActionError(data.error);
        else { setSuccessMsg("Force-merged. Audit event published."); setForceMode(false); setForceReason(""); window.LiveMonitorRefresh?.(); }
      } catch (e) { setActionError(String(e)); }
      finally { setActionPending(false); }
    }

    return (
      <HubLayout>
        {/* Back nav */}
        <button onClick={backToList}
                className="flex items-center gap-1.5 text-sm text-fg-secondary hover:text-accent mb-4 transition-colors">
          {Icons.chevronLeft && <Icons.chevronLeft size={14} />}
          <span>Pull requests</span>
        </button>

        {/* Header card */}
        <div className="bg-bg-elevated border border-border rounded-lg p-5 mb-4"
             style={{ boxShadow: "inset 0 1px 0 rgba(255,255,255,0.4)" }}>
          <div className="flex items-start gap-4">
            {/* state icon — pushed down so its center sits near the title's
                visual midline (title is text-2xl with line-height 1.3 → 26px,
                icon is 36px tall, so we offset half the diff downward). */}
            <span className="w-9 h-9 rounded-full flex items-center justify-center shrink-0 text-md font-bold"
                  style={{
                    background: visual.bg, color: visual.color,
                    boxShadow: `inset 0 1px 0 rgba(255,255,255,0.4), 0 0 0 1px color-mix(in srgb, ${visual.color} 30%, transparent)`,
                    marginTop: "6px",
                  }}>
              {pr.merge_state === "merged" ? "✓" : pr.merge_state === "closed" ? "✕" : pr.merge_state === "changes_requested" ? "!" : "●"}
            </span>
            <div className="flex-1 min-w-0">
              <div className="flex items-baseline gap-3 flex-wrap mb-1.5">
                <h1 className="text-2xl font-semibold tracking-tight text-fg">{pr.title || "(untitled)"}</h1>
                <code className="font-mono text-md text-fg-muted">#{(pr.number || pr.id || "").toString().substr(0, 10)}</code>
              </div>
              <div className="flex items-center flex-wrap gap-x-3 gap-y-1 text-sm text-fg-secondary">
                <span style={{ color: visual.color }} className="font-medium uppercase tracking-wider text-xs">{visual.label}</span>
                <span className="text-fg-muted/40">·</span>
                <span className="inline-flex items-center gap-1.5">opened by <ActorChip name={pr.author || "system"} size={16} /></span>
                <span className="text-fg-muted/40">·</span>
                <span><code className="font-mono">{pr.head}</code> → <code className="font-mono">{pr.base || "main"}</code></span>
                <span className="text-fg-muted/40">·</span>
                <span>{fmtRel(pr.created_at)}</span>
              </div>
              {Array.isArray(pr.reviewers) && pr.reviewers.length > 0 && (
                <div className="mt-3 flex items-center gap-2 text-xs">
                  <span className="text-fg-muted">Required reviewers:</span>
                  {pr.reviewers.map(rv => (
                    <ActorChip key={rv} name={rv} size={14} />
                  ))}
                </div>
              )}
            </div>
          </div>

          {/* Status banner */}
          <div className="mt-4 grid grid-cols-4 gap-3">
            <SummaryStat label="Approvals" value={`${approved}/${pr.reviewers?.length || reviews.length}`} tone={approved >= (pr.reviewers?.length || 0) && approved > 0 ? "success" : "neutral"} />
            <SummaryStat label="Changes req" value={requested} tone={requested > 0 ? "warning" : "neutral"} />
            <SummaryStat label="Checks passed" value={`${passedChecks}/${checks.length}`} tone={failedChecks === 0 && checks.length > 0 ? "success" : "neutral"} />
            <SummaryStat label="Commits" value={commits.length} tone="neutral" />
          </div>

          {/* Merge conflict banner */}
          {(pr.status === "conflict" || (pr.conflict_files || []).length > 0) && (
            <div className="mt-4 px-4 py-3 rounded-lg bg-danger-soft border border-danger/30">
              <div className="text-sm font-semibold text-danger flex items-center gap-1.5 mb-1.5">⚠ Merge conflicts</div>
              {(pr.conflict_files || []).length > 0 ? (
                <ul className="space-y-1">
                  {(pr.conflict_files || []).map((f, i) => (
                    <li key={i} className="flex items-center gap-2">
                      {Icons.file && <span className="text-danger shrink-0"><Icons.file size={12} /></span>}
                      <button onClick={() => window.LiveMonitorRouter.openCodeFile(projectId, f, pr.source_branch || pr.head)}
                              className="font-mono text-xs text-fg hover:text-accent transition-colors" title="Open in CodeHub">{f}</button>
                    </li>
                  ))}
                </ul>
              ) : (
                <div className="text-xs text-fg-secondary">This PR has conflicts with <code className="font-mono">{pr.target_branch || pr.base || "main"}</code> that must be resolved before merging.</div>
              )}
              {pr.conflict_resolved_by && (
                <div className="text-2xs text-success mt-1.5">Resolved by {pr.conflict_resolved_by} {fmtRel(pr.conflict_resolved_at)}</div>
              )}
            </div>
          )}

          {/* Action area — fully inline */}
          {pr.merge_state !== "merged" && pr.merge_state !== "closed" && (
            <div className="mt-5 pt-4 border-t border-border">
              {successMsg && (
                <div className="mb-3 px-3 py-2 rounded-md bg-success-soft text-success text-base flex items-center justify-between">
                  <span>✓ {successMsg}</span>
                  <button onClick={() => setSuccessMsg("")} className="text-success hover:opacity-70">×</button>
                </div>
              )}
              {actionError && (
                <div className="mb-3 px-3 py-2 rounded-md bg-danger-soft text-danger text-base flex items-center justify-between">
                  <span>⚠ {actionError}</span>
                  <button onClick={() => setActionError("")} className="text-danger hover:opacity-70">×</button>
                </div>
              )}
              {!confirmMerge && !forceMode && !showReview && (() => {
                const isReady = pr.merge_state === "ready";
                const blocker = (() => {
                  if (pr.merge_state === "changes_requested") return "Changes requested — address review feedback before merging.";
                  const need = (pr.reviewers || []).length;
                  if (need > 0 && approved < need) return `Awaiting approvals (${approved}/${need} so far).`;
                  if (failedChecks > 0) return `${failedChecks} check${failedChecks === 1 ? "" : "s"} failing — fix before merging.`;
                  if (checks.length === 0) return "No checks recorded yet.";
                  return "Not yet ready to merge.";
                })();
                return (
                  <div className="flex items-center gap-2 flex-wrap">
                    {isReady ? (
                      <button onClick={() => setConfirmMerge(true)} className="btn-px btn-px-primary btn-px-sm">
                        {Icons.shieldCheck && <Icons.shieldCheck size={12} />} Merge pull request
                      </button>
                    ) : (
                      <div className="flex items-center gap-2 px-3 py-1.5 rounded-md bg-bg-tertiary text-fg-secondary text-sm">
                        <span className="text-warning">●</span>
                        <span>{blocker}</span>
                      </div>
                    )}
                    <button onClick={() => setShowReview(true)} className="btn-px btn-px-ghost btn-px-sm">
                      {Icons.clipboard && <Icons.clipboard size={12} />} Add review
                    </button>
                    <button onClick={() => setForceMode(true)} className="btn-px btn-px-ghost btn-px-sm text-fg-muted ml-auto">
                      Force merge…
                    </button>
                  </div>
                );
              })()}
              {/* Inline merge confirm */}
              {confirmMerge && (
                <div className="flex items-center gap-3 p-3 rounded-md bg-bg-tertiary">
                  <span className="text-sm text-fg">
                    Merge <code className="font-mono">{pr.head}</code> into <code className="font-mono">{pr.base || "main"}</code>?
                  </span>
                  <div className="ml-auto flex gap-2">
                    <button onClick={() => setConfirmMerge(false)} className="btn-px btn-px-ghost btn-px-sm">Cancel</button>
                    <button onClick={doMerge} disabled={actionPending} className="btn-px btn-px-primary btn-px-sm">
                      {actionPending ? "Merging…" : "Confirm merge"}
                    </button>
                  </div>
                </div>
              )}
              {/* Inline force-merge */}
              {forceMode && (
                <div className="p-3 rounded-md bg-warning-soft border border-warning/30 space-y-2.5">
                  <div className="text-sm text-warning font-semibold flex items-center gap-1.5">
                    <span>⚠</span> Force merge bypasses all approval gates
                  </div>
                  <textarea
                    value={forceReason} onChange={e => setForceReason(e.target.value)}
                    placeholder="Why are you force-merging? (≥5 chars, will be audited)"
                    rows={2}
                    className="input-px textarea-px w-full" />
                  <div className="flex justify-end gap-2">
                    <button onClick={() => { setForceMode(false); setForceReason(""); }} className="btn-px btn-px-ghost btn-px-sm">Cancel</button>
                    <button onClick={doForceMerge} disabled={actionPending || forceReason.trim().length < 5} className="btn-px btn-px-sm"
                            style={{ background: "var(--danger)", color: "var(--text-on-accent)", border: "1px solid var(--danger)" }}>
                      {actionPending ? "Force-merging…" : "Force merge"}
                    </button>
                  </div>
                </div>
              )}
              {/* Inline add review */}
              {showReview && (
                <AddReviewForm projectId={projectId} prId={prId} pr={pr}
                  onCancel={() => setShowReview(false)}
                  onSubmitted={() => { setShowReview(false); setSuccessMsg("Review submitted."); window.LiveMonitorRefresh?.(); }} />
              )}
            </div>
          )}
        </div>

        {/* Linked items */}
        {((pr.linked_tasks || []).length + (pr.linked_apis || []).length + (pr.linked_pages || []).length + (pr.linked_consumers || []).length) > 0 && (
          <HubCard className="mb-4">
            <HubCardHeader title="Linked items" subtitle="Cross-hub references" />
            <div className="px-4 py-3 grid grid-cols-4 gap-3 text-sm">
              {[
                { key: "linked_tasks",     label: "Tasks",     hub: "workhub", chip: "var(--info-soft)", chipText: "var(--info)" },
                { key: "linked_apis",      label: "APIs",      hub: "registryhub",  chip: "var(--accent-soft)", chipText: "var(--accent-on-soft)" },
                { key: "linked_pages",     label: "Pages",     hub: "workhub", chip: "var(--neutral-soft)", chipText: "var(--text-secondary)" },
                { key: "linked_consumers", label: "Consumers", hub: "registryhub",  chip: "var(--neutral-soft)", chipText: "var(--text-secondary)" },
              ].map(g => {
                const items = pr[g.key] || [];
                if (items.length === 0) return null;
                return (
                  <div key={g.key}>
                    <div className="text-2xs uppercase tracking-wider font-medium text-fg-muted mb-1.5">{g.label}</div>
                    <div className="flex flex-col gap-1">
                      {items.map(it => (
                        <button key={it} onClick={() => nav(`/projects/${encodeURIComponent(projectId)}/${g.hub}`)}
                                className="text-left text-xs px-2 py-1 rounded font-mono truncate"
                                style={{ background: g.chip, color: g.chipText }}>
                          {it}
                        </button>
                      ))}
                    </div>
                  </div>
                );
              })}
            </div>
          </HubCard>
        )}

        {/* 2-column: Reviews + Checks */}
        <div className="grid grid-cols-2 gap-4 mb-4">
          {/* Reviews */}
          <HubCard>
            <HubCardHeader title="Reviews" subtitle={`${reviews.length} total · ${approved} approved · ${requested} changes requested`} />
            {reviews.length === 0 ? (
              <EmptyState icon={Icons.clipboard} title="No reviews yet"
                sub="When reviewers submit a review, it shows up here with full inline comments." />
            ) : (
              <ul className="p-3 space-y-2">
                {reviews.map(rv => <ReviewCard key={rv.id} review={rv} />)}
              </ul>
            )}
          </HubCard>

          {/* Checks */}
          <HubCard>
            <HubCardHeader title="Checks" subtitle={`${passedChecks} passed · ${failedChecks} failed`} />
            {checks.length === 0 ? (
              <EmptyState icon={Icons.shieldCheck} title="No checks yet"
                sub="CI / verification checks recorded against this PR land here." />
            ) : (
              <ul className="p-3 space-y-2">
                {checks.map(c => <CheckCard key={c.id || c.name} check={c} />)}
              </ul>
            )}
          </HubCard>
        </div>

        {/* Commits + Activity timeline */}
        <div className="grid grid-cols-2 gap-4 mb-4">
          <HubCard>
            <HubCardHeader title="Commits" subtitle={`on ${pr.head}`} />
            {commits.length === 0 ? (
              <EmptyState icon={Icons.code} title="No commits" sub="No commits recorded on the head branch yet." />
            ) : (
              <ul className="p-3 space-y-2">
                {commits.slice(0, 20).map(c => (
                  <li key={c.id || c.sha} className="px-4 py-2.5 flex items-start gap-2.5 border border-border-strong rounded-md bg-bg-elevated hover:bg-bg-hover transition-all">
                    <AgentAvatar name={c.author_id || c.author || "system"} size={20} />
                    <div className="flex-1 min-w-0">
                      <div className="text-sm text-fg truncate">{c.diff_summary || c.message || c.msg || "(no message)"}</div>
                      <div className="text-2xs text-fg-muted flex items-center gap-2 mt-0.5">
                        <code className="font-mono">{(c.commit_hash || c.sha || c.id || "").substr(0, 8)}</code>
                        <span className="text-fg-muted/40">·</span>
                        <span>{fmtRel(c.created_at)}</span>
                      </div>
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </HubCard>

          <HubCard>
            <HubCardHeader title="Activity" subtitle={`${events.length} events`} />
            {events.length === 0 ? (
              <EmptyState icon={Icons.inbox} title="No EventHub events"
                sub="EventHub events referencing this PR will appear here." />
            ) : (
              <ul className="p-3 space-y-2">
                {events.slice(0, 20).map((e, i) => (
                  <li key={e.id || i} className="px-4 py-2.5 border border-border-strong rounded-md bg-bg-elevated">
                    <div className="flex-1 min-w-0">
                      <div className="text-xs">
                        <span className="font-mono font-medium text-fg">{e.event_type}</span>
                      </div>
                      <div className="text-2xs text-fg-muted mt-0.5 flex items-center gap-1.5">
                        <span>by {e.source_hub || "—"}</span>
                        <span className="text-fg-muted/40">·</span>
                        <span>{fmtRel(e.created_at)}</span>
                      </div>
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </HubCard>
        </div>

        {/* Files changed — the actual diff (head vs target) */}
        <PRDiffView projectId={projectId} prId={prId} headLabel={pr.head} targetLabel={pr.target_branch || pr.base || "main"} />
      </HubLayout>
    );
  }

  // ===========================================================================
  // Cutover 43.19: PRDiffView — GitHub "Files changed" view.
  // Fetches the unified diff and renders it per-file with line-number gutters
  // and +add / -del coloring. Backed by the same data as the codehub_get_diff
  // agent tool, so humans and agents read the exact same diff.
  // ===========================================================================
  function parseUnifiedDiff(text) {
    // Returns [{ path, oldPath, status, additions, deletions, hunks:[{header, lines:[{type, oldNo, newNo, text}]}] }]
    const files = [];
    let cur = null, hunk = null, oldNo = 0, newNo = 0;
    const lines = (text || "").split("\n");
    for (const raw of lines) {
      if (raw.startsWith("diff --git")) {
        cur = { path: "", oldPath: "", status: "modified", additions: 0, deletions: 0, hunks: [] };
        files.push(cur);
        hunk = null;
        // diff --git a/x b/y
        const m = raw.match(/^diff --git a\/(.+?) b\/(.+)$/);
        if (m) { cur.oldPath = m[1]; cur.path = m[2]; }
        continue;
      }
      if (!cur) continue;
      if (raw.startsWith("new file")) { cur.status = "added"; continue; }
      if (raw.startsWith("deleted file")) { cur.status = "deleted"; continue; }
      if (raw.startsWith("rename ")) { cur.status = "renamed"; continue; }
      if (raw.startsWith("index ") || raw.startsWith("similarity ")) continue;
      if (raw.startsWith("--- ")) { const p = raw.slice(4); if (p !== "/dev/null") cur.oldPath = p.replace(/^a\//, ""); continue; }
      if (raw.startsWith("+++ ")) { const p = raw.slice(4); if (p !== "/dev/null") cur.path = p.replace(/^b\//, ""); continue; }
      if (raw.startsWith("@@")) {
        const m = raw.match(/^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@(.*)$/);
        oldNo = m ? parseInt(m[1], 10) : 0;
        newNo = m ? parseInt(m[2], 10) : 0;
        hunk = { header: raw, lines: [] };
        cur.hunks.push(hunk);
        continue;
      }
      if (!hunk) continue;
      if (raw.startsWith("\\")) continue; // "\ No newline at end of file"
      const c0 = raw[0];
      if (c0 === "+") { hunk.lines.push({ type: "add", oldNo: null, newNo: newNo++, text: raw.slice(1) }); cur.additions++; }
      else if (c0 === "-") { hunk.lines.push({ type: "del", oldNo: oldNo++, newNo: null, text: raw.slice(1) }); cur.deletions++; }
      else { hunk.lines.push({ type: "ctx", oldNo: oldNo++, newNo: newNo++, text: raw.slice(1) }); }
    }
    return files;
  }

  function PRDiffView({ projectId, prId, headLabel, targetLabel }) {
    const Icons = window.Icons || {};
    const [data, setData] = useState(null);
    const [err, setErr] = useState("");
    const [loading, setLoading] = useState(true);
    const [collapsed, setCollapsed] = useState({});
    useEffect(() => {
      let cancelled = false;
      setLoading(true); setErr("");
      fetch(`/api/projects/${encodeURIComponent(projectId)}/codehub/pull_requests/${encodeURIComponent(prId)}/diff`, { credentials: "include" })
        .then(r => r.json())
        .then(d => { if (cancelled) return; if (d.error) setErr(d.error); else setData(d); })
        .catch(e => { if (!cancelled) setErr(String(e)); })
        .finally(() => { if (!cancelled) setLoading(false); });
      return () => { cancelled = true; };
    }, [projectId, prId]);

    const files = useMemo(() => data?.diff ? parseUnifiedDiff(data.diff) : [], [data]);
    const totalAdd = files.reduce((n, f) => n + f.additions, 0);
    const totalDel = files.reduce((n, f) => n + f.deletions, 0);

    return (
      <HubCard className="mb-4">
        <header className="flex items-center gap-3 px-4 h-11 border-b border-border">
          <h3 className="text-md font-semibold tracking-tight">Files changed</h3>
          {files.length > 0 && (
            <span className="text-sm text-fg-muted flex items-center gap-2">
              <span>{files.length} file{files.length === 1 ? "" : "s"}</span>
              <span className="text-success font-medium">+{totalAdd}</span>
              <span className="text-danger font-medium">−{totalDel}</span>
            </span>
          )}
          <span className="ml-auto text-2xs text-fg-muted font-mono">
            {targetLabel} ← {(headLabel || "").toString().substr(0, 10)}
          </span>
        </header>

        {loading ? (
          <div className="px-4 py-8 text-sm text-fg-muted">Loading diff…</div>
        ) : err ? (
          <div className="px-4 py-6">
            <div className="text-sm text-fg-secondary mb-1">Diff unavailable</div>
            <div className="text-xs text-fg-muted font-mono bg-bg-secondary rounded p-2 whitespace-pre-wrap">{err}</div>
            <div className="text-2xs text-fg-muted mt-2">
              Diffs require a real git head commit. Metadata-only PRs (synthetic commit ids) can't be diffed.
            </div>
          </div>
        ) : files.length === 0 ? (
          <EmptyState icon={Icons.code} title="No changes" sub="This PR's diff is empty." />
        ) : (
          <div className="p-3 space-y-3">
            {data.truncated && (
              <div className="px-3 py-2 rounded-md bg-warning-soft text-warning text-xs">
                {data.truncation_marker || "Diff truncated."}
              </div>
            )}
            {files.map((f, fi) => {
              const isCollapsed = !!collapsed[fi];
              const statusTone = { added: "text-success", deleted: "text-danger", renamed: "text-info", modified: "text-fg-muted" }[f.status];
              return (
                <div key={fi} className="border border-border rounded-md overflow-hidden bg-bg-elevated">
                  <button onClick={() => setCollapsed(c => ({ ...c, [fi]: !c[fi] }))}
                          className="w-full flex items-center gap-2 px-3 h-9 bg-bg-secondary/60 border-b border-border hover:bg-bg-hover transition-colors text-left">
                    <span className="text-fg-muted text-2xs w-3">{isCollapsed ? "▸" : "▾"}</span>
                    {Icons.file && <span className="text-fg-muted shrink-0"><Icons.file size={12} /></span>}
                    <code className="font-mono text-sm text-fg truncate flex-1">{f.path || f.oldPath}</code>
                    <span className={"text-2xs uppercase tracking-wider font-medium shrink-0 " + statusTone}>{f.status}</span>
                    <span className="text-2xs font-mono shrink-0"><span className="text-success">+{f.additions}</span> <span className="text-danger">−{f.deletions}</span></span>
                  </button>
                  {!isCollapsed && (
                    <div className="overflow-x-auto">
                      <table className="w-full border-collapse font-mono text-xs leading-relaxed" style={{ background: "var(--bg-secondary)" }}>
                        <tbody>
                          {f.hunks.map((h, hi) => (
                            <React.Fragment key={hi}>
                              <tr className="select-none">
                                <td className="text-right pr-2 pl-3 text-fg-muted/60 w-12 bg-bg-tertiary/40" />
                                <td className="text-right pr-2 text-fg-muted/60 w-12 bg-bg-tertiary/40" />
                                <td className="px-3 text-info/80 bg-info-soft/30">{h.header}</td>
                              </tr>
                              {h.lines.map((ln, li) => {
                                const bg = ln.type === "add" ? "rgba(34,197,94,0.10)" : ln.type === "del" ? "rgba(239,68,68,0.10)" : "transparent";
                                const sign = ln.type === "add" ? "+" : ln.type === "del" ? "−" : " ";
                                const signColor = ln.type === "add" ? "text-success" : ln.type === "del" ? "text-danger" : "text-fg-muted/40";
                                return (
                                  <tr key={li} style={{ background: bg }}>
                                    <td className="text-right pr-2 pl-3 text-fg-muted/50 w-12 select-none tabular-nums">{ln.oldNo ?? ""}</td>
                                    <td className="text-right pr-2 text-fg-muted/50 w-12 select-none tabular-nums">{ln.newNo ?? ""}</td>
                                    <td className="px-2 whitespace-pre text-fg-secondary">
                                      <span className={"select-none mr-1 " + signColor}>{sign}</span>{ln.text}
                                    </td>
                                  </tr>
                                );
                              })}
                            </React.Fragment>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </HubCard>
    );
  }

  // ===========================================================================
  // Cutover 43.18: BranchDetailView — GitHub-style branch page.
  // Shows commits on the branch, ahead/behind comparison vs. base, and an
  // "Open pull request" CTA when there's no open PR from this branch.
  // ===========================================================================
  function BranchDetailView({ projectId, hub, state, branchName }) {
    const Icons = window.Icons || {};
    const branches = hub?.branches || {};
    const branch = Object.values(branches).find(b => b.name === branchName);
    const allCommits = Object.values(hub?.commits || {});
    const branchCommits = allCommits
      .filter(c => c.branch === branchName)
      .sort((a, b) => (b.created_at || 0) - (a.created_at || 0));
    const baseName = branch?.base || "main";
    const baseCommits = allCommits.filter(c => c.branch === baseName);
    // "Ahead" = commits on this branch not on base (by id)
    const baseIds = new Set(baseCommits.map(c => c.id));
    const aheadCommits = branchCommits.filter(c => !baseIds.has(c.id));
    // Related PRs
    const allPRs = Object.values(hub?.pull_requests || {});
    const branchPRs = allPRs.filter(p => p.head === branchName);
    const openPR = branchPRs.find(p => p.merge_state !== "merged" && p.merge_state !== "closed");

    const nav = (p) => window.LiveMonitorRouter.navigateTo(p);
    const backToList = () => nav(`/projects/${encodeURIComponent(projectId)}/codehub`);

    // Inline "Open PR" form state
    const [showOpenForm, setShowOpenForm] = useState(false);
    const [pfTitle, setPfTitle] = useState(branchName.replace(/^feature\//, "").replace(/[-_]/g, " "));
    const [pfBase, setPfBase] = useState(baseName);
    const [pfAuthor, setPfAuthor] = useState("ui_user");
    const [pfPending, setPfPending] = useState(false);
    const [pfError, setPfError] = useState("");
    async function submitOpenPR() {
      if (!pfTitle.trim()) { setPfError("Title is required."); return; }
      setPfPending(true); setPfError("");
      try {
        const number = String(Date.now() % 100000);
        const r = await fetch(`/api/projects/${encodeURIComponent(projectId)}/codehub/pull_requests`, {
          method: "POST", headers: { "Content-Type": "application/json" }, credentials: "include",
          body: JSON.stringify({ number, title: pfTitle.trim(), head: branchName, base: pfBase.trim() || "main", author: pfAuthor.trim() }),
        });
        const data = await r.json();
        if (data.error) { setPfError(data.error); setPfPending(false); return; }
        setShowOpenForm(false);
        window.LiveMonitorRefresh?.();
      } catch (e) { setPfError(String(e)); }
      finally { setPfPending(false); }
    }

    if (!branch) {
      return (
        <HubLayout>
          <button onClick={backToList} className="flex items-center gap-1.5 text-sm text-fg-secondary hover:text-accent mb-4">
            {Icons.chevronLeft && <Icons.chevronLeft size={14} />} Back to branches
          </button>
          <EmptyState icon={Icons.branch} title="Branch not found"
            sub={`No branch named ${branchName} in this project.`}
            actionLabel="Back to CodeHub" onAction={backToList} />
        </HubLayout>
      );
    }

    const isDefault = branchName === baseName;

    return (
      <HubLayout>
        <button onClick={backToList}
                className="flex items-center gap-1.5 text-sm text-fg-secondary hover:text-accent mb-4 transition-colors">
          {Icons.chevronLeft && <Icons.chevronLeft size={14} />}
          <span>Branches</span>
        </button>

        {/* Header card */}
        <div className="bg-bg-elevated border border-border rounded-lg p-5 mb-4">
          <div className="flex items-start gap-4">
            {Icons.branch && (
              <span className="w-9 h-9 rounded-full flex items-center justify-center shrink-0 text-info bg-info-soft"
                    style={{ marginTop: "6px" }}>
                <Icons.branch size={16} />
              </span>
            )}
            <div className="flex-1 min-w-0">
              <div className="flex items-baseline gap-3 flex-wrap mb-1.5">
                <h1 className="text-2xl font-mono font-semibold tracking-tight text-fg">{branchName}</h1>
                {isDefault && <span className="text-2xs uppercase tracking-wider font-semibold px-2 py-0.5 rounded bg-bg-tertiary text-fg-muted">default branch</span>}
              </div>
              <div className="flex items-center flex-wrap gap-x-3 gap-y-1 text-sm text-fg-secondary">
                {!isDefault && (
                  <>
                    <span>based on <code className="font-mono">{baseName}</code></span>
                    <span className="text-fg-muted/40">·</span>
                  </>
                )}
                <span><code className="font-mono">{(branch.head || "").substr(0, 8)}</code></span>
                <span className="text-fg-muted/40">·</span>
                <span>updated {fmtRel(branch._updated_at || branch.created_at)}</span>
                {branch.owner && (<>
                  <span className="text-fg-muted/40">·</span>
                  <span>owner <ActorChip name={branch.owner} /></span>
                </>)}
              </div>
            </div>
          </div>

          {/* Summary stats */}
          <div className="mt-4 grid grid-cols-3 gap-3">
            <SummaryStat label="Commits" value={branchCommits.length} tone="neutral" />
            <SummaryStat label={`Ahead of ${baseName}`} value={isDefault ? "—" : aheadCommits.length} tone={aheadCommits.length > 0 ? "success" : "neutral"} />
            <SummaryStat label="Pull requests" value={branchPRs.length} tone={openPR ? "info" : "neutral"} />
          </div>

          {/* Action area */}
          {!isDefault && (
            <div className="mt-5 pt-4 border-t border-border">
              {openPR ? (
                <div className="flex items-center gap-3 p-3 rounded-md bg-info-soft/40">
                  <span className="text-sm text-fg-secondary">PR already open from this branch:</span>
                  <button onClick={() => nav(`/projects/${encodeURIComponent(projectId)}/codehub/pr/${encodeURIComponent(openPR.id)}`)}
                          className="btn-px btn-px-primary btn-px-sm">
                    View PR #{(openPR.number || openPR.id || "").toString().substr(0, 8)}
                  </button>
                </div>
              ) : showOpenForm ? (
                <div className="space-y-3">
                  <div className="text-md font-semibold text-fg">Open a pull request from <code className="font-mono">{branchName}</code></div>
                  {pfError && <div className="px-3 py-2 rounded-md bg-danger-soft text-danger text-base">{pfError}</div>}
                  <div>
                    <label className="block text-sm font-medium text-fg mb-1.5">Title <span className="text-danger">*</span></label>
                    <input className="input-px w-full" value={pfTitle} onChange={e => setPfTitle(e.target.value)} placeholder="What does this PR do?" autoFocus />
                  </div>
                  <div className="grid grid-cols-2 gap-3">
                    <div>
                      <label className="block text-sm font-medium text-fg mb-1.5">Base branch</label>
                      <input className="input-px w-full font-mono" value={pfBase} onChange={e => setPfBase(e.target.value)} />
                    </div>
                    <div>
                      <label className="block text-sm font-medium text-fg mb-1.5">Author</label>
                      <input className="input-px w-full" value={pfAuthor} onChange={e => setPfAuthor(e.target.value)} />
                    </div>
                  </div>
                  <div className="flex justify-end gap-2">
                    <button onClick={() => setShowOpenForm(false)} className="btn-px btn-px-ghost btn-px-sm">Cancel</button>
                    <button onClick={submitOpenPR} disabled={pfPending || !pfTitle.trim()} className="btn-px btn-px-primary btn-px-sm">
                      {pfPending ? "Opening…" : "Open pull request"}
                    </button>
                  </div>
                </div>
              ) : (
                <div className="flex items-center gap-3">
                  <button onClick={() => setShowOpenForm(true)} className="btn-px btn-px-primary btn-px-sm">
                    {Icons.plus && <Icons.plus size={12} />} Open pull request
                  </button>
                  <span className="text-sm text-fg-muted">
                    {aheadCommits.length > 0
                      ? `${aheadCommits.length} commit${aheadCommits.length === 1 ? "" : "s"} ahead of ${baseName}`
                      : `nothing new vs. ${baseName}`}
                  </span>
                </div>
              )}
            </div>
          )}
        </div>

        {/* Commits on this branch */}
        <HubCard className="mb-4">
          <HubCardHeader title="Commits" subtitle={`on ${branchName}`} />
          {branchCommits.length === 0 ? (
            <EmptyState icon={Icons.code} title="No commits" sub="No commits recorded on this branch yet." />
          ) : (
            <ul className="p-3 space-y-2">
              {branchCommits.map(c => (
                <li key={c.id || c.sha} className="px-4 py-3 border border-border-strong rounded-md bg-bg-elevated">
                  <div className="text-md text-fg leading-snug">{c.diff_summary || c.message || c.msg || "(no message)"}</div>
                  <div className="text-xs text-fg-muted flex items-center gap-2 mt-1">
                    <code className="font-mono">{(c.commit_hash || c.sha || c.id || "").substr(0, 8)}</code>
                    <span className="text-fg-muted/40">·</span>
                    <ActorChip name={c.author_id || c.author || "system"} />
                    <span className="text-fg-muted/40">·</span>
                    <span>{fmtRel(c.created_at)}</span>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </HubCard>

        {/* All PRs from this branch */}
        {branchPRs.length > 0 && (
          <HubCard>
            <HubCardHeader title="Pull requests from this branch" subtitle={`${branchPRs.length} total`} />
            <ul className="p-3 space-y-2">
              {branchPRs.map(pr => {
                const v = prStateVisual(pr.merge_state || "open");
                return (
                  <li key={pr.id}
                      onClick={() => nav(`/projects/${encodeURIComponent(projectId)}/codehub/pr/${encodeURIComponent(pr.id)}`)}
                      className="group flex items-center gap-3 px-4 py-3 border border-border-strong rounded-md bg-bg-elevated hover:bg-bg-hover hover:shadow-sm cursor-pointer transition-all">
                    <span className="font-medium" style={{ color: v.color }}>{v.label}</span>
                    <span className="text-md font-semibold text-fg truncate group-hover:text-accent transition-colors flex-1 min-w-0">{pr.title}</span>
                    <code className="font-mono text-xs text-fg-muted shrink-0">#{(pr.number || pr.id || "").toString().substr(0, 8)}</code>
                  </li>
                );
              })}
            </ul>
          </HubCard>
        )}
      </HubLayout>
    );
  }

  function SummaryStat({ label, value, tone }) {
    const cls = { success: "text-success", warning: "text-warning", danger: "text-danger", neutral: "text-fg" }[tone];
    return (
      <div className="px-3 py-2 rounded-md bg-bg-tertiary/50 border border-border">
        <div className="text-2xs uppercase tracking-wider font-medium text-fg-muted mb-0.5">{label}</div>
        <div className={"text-lg font-semibold tabular-nums " + cls}>{value}</div>
      </div>
    );
  }

  function ReviewCard({ review: rv }) {
    const tone = { approve: "var(--success)", request_changes: "var(--warning)", comment: "var(--info)" }[rv.state] || "var(--text-muted)";
    const toneBg = { approve: "var(--success-soft)", request_changes: "var(--warning-soft)", comment: "var(--info-soft)" }[rv.state] || "var(--bg-tertiary)";
    return (
      <li className="p-4 border border-border-strong rounded-md bg-bg-elevated">
        <div className="flex items-center gap-2 mb-2">
          <ActorChip name={rv.reviewer || "system"} size={18} />
          <span className="text-xs font-mono font-semibold uppercase tracking-wider px-2 py-0.5 rounded"
                style={{ background: toneBg, color: tone }}>{rv.state}</span>
          <span className="text-xs text-fg-muted ml-auto">{fmtRel(rv.created_at || rv.submitted_at || rv._updated_at)}</span>
        </div>
        {/* free-form comments */}
        {Array.isArray(rv.comments) && rv.comments.length > 0 && (
          <div className="space-y-1 mb-2">
            {rv.comments.map((c, i) => (
              <div key={i} className="text-sm text-fg-secondary border-l-2 border-border-strong pl-3 py-0.5">
                {c.body || (typeof c === "string" ? c : "(no body)")}
              </div>
            ))}
          </div>
        )}
        {/* inline comments */}
        {Array.isArray(rv.inline_comments) && rv.inline_comments.length > 0 && (
          <div className="space-y-1.5 mt-2">
            <div className="text-2xs uppercase tracking-wider font-medium text-fg-muted">Inline comments</div>
            {rv.inline_comments.map((c, i) => (
              <div key={i} className="bg-bg-tertiary rounded-md p-2.5">
                <div className="text-2xs font-mono text-fg-muted mb-1">
                  <code className="bg-bg-primary px-1.5 py-0.5 rounded">{c.file}</code>
                  <span className="mx-1.5">·</span>
                  <span>line {c.line}</span>
                </div>
                <div className="text-sm text-fg">{c.body || "(no body)"}</div>
              </div>
            ))}
          </div>
        )}
        {/* considered alternatives */}
        {Array.isArray(rv.considered_alternatives) && rv.considered_alternatives.filter(Boolean).length > 0 && (
          <details className="mt-2 text-2xs">
            <summary className="cursor-pointer text-fg-muted hover:text-fg-secondary">
              Considered alternatives ({rv.considered_alternatives.filter(Boolean).length})
            </summary>
            <ul className="mt-1.5 pl-4 list-disc text-fg-secondary space-y-0.5">
              {rv.considered_alternatives.filter(Boolean).map((alt, i) => <li key={i}>{alt}</li>)}
            </ul>
          </details>
        )}
      </li>
    );
  }

  function CheckCard({ check: c }) {
    const tone = { passed: "text-success", failed: "text-danger", skipped: "text-fg-muted", error: "text-danger" }[c.status] || "text-fg-secondary";
    const toneBg = { passed: "var(--success-soft)", failed: "var(--danger-soft)", skipped: "var(--bg-tertiary)", error: "var(--danger-soft)" }[c.status] || "var(--bg-tertiary)";
    return (
      <li className="px-4 py-3 flex items-start gap-3 border border-border-strong rounded-md bg-bg-elevated">
        <span className={"text-2xs font-mono font-semibold uppercase tracking-wider px-2 py-0.5 rounded mt-0.5 " + tone}
              style={{ background: toneBg }}>{c.status}</span>
        <div className="flex-1 min-w-0">
          <div className="text-sm text-fg font-medium">{c.name || "(unnamed)"}</div>
          <div className="text-2xs text-fg-muted flex items-center gap-2 mt-0.5">
            <ActorChip name={c.agent || "system"} size={14} />
            <span className="text-fg-muted/40">·</span>
            <span>{fmtRel(c.updated_at || c.created_at)}</span>
          </div>
          {c.evidence?.summary && (
            <div className="text-xs text-fg-secondary mt-1.5 bg-bg-tertiary rounded px-2 py-1 line-clamp-2">{c.evidence.summary}</div>
          )}
        </div>
      </li>
    );
  }

  function AddReviewForm({ projectId, prId, pr, onCancel, onSubmitted }) {
    const [state, setState] = useState("comment");
    const [reviewer, setReviewer] = useState("ui_user");
    const [reasonText, setReasonText] = useState("");
    const [alts, setAlts] = useState("");
    const [inlineComments, setInlineComments] = useState([{ file: "", line: "", body: "" }]);
    const [pending, setPending] = useState(false);
    const [error, setError] = useState("");

    function addRow() { setInlineComments([...inlineComments, { file: "", line: "", body: "" }]); }
    function removeRow(i) { setInlineComments(inlineComments.filter((_, idx) => idx !== i)); }
    function updateRow(i, field, val) {
      const c = [...inlineComments]; c[i] = { ...c[i], [field]: val }; setInlineComments(c);
    }

    async function submit() {
      setPending(true); setError("");
      try {
        const inline = inlineComments
          .filter(c => c.file && c.line && c.body)
          .map(c => ({ file: c.file.trim(), line: Number(c.line), body: c.body.trim() }));
        const considered = alts.split("\n").map(s => s.trim()).filter(Boolean);
        if (state === "approve" && inline.length === 0) {
          setError("Approve requires ≥1 inline comment."); setPending(false); return;
        }
        if (state === "approve" && considered.length === 0) {
          setError("Approve requires ≥1 considered alternative."); setPending(false); return;
        }
        const body = {
          reviewer: reviewer.trim() || "ui_user",
          state,
          comments: reasonText.trim() ? [{ body: reasonText.trim() }] : [],
          inline_comments: inline,
          considered_alternatives: considered,
        };
        const r = await fetch(`/api/projects/${encodeURIComponent(projectId)}/codehub/pull_requests/${encodeURIComponent(prId)}/reviews`, {
          method: "POST", headers: { "Content-Type": "application/json" }, credentials: "include",
          body: JSON.stringify(body),
        });
        const data = await r.json();
        if (data.error) setError(data.error); else onSubmitted();
      } catch (e) { setError(String(e)); }
      finally { setPending(false); }
    }
    return (
      <div className="p-4 rounded-md bg-bg-tertiary/50 border border-border">
        <div className="text-sm font-semibold text-fg mb-3">New review</div>
        {error && <div className="mb-3 px-3 py-2 rounded-md bg-danger-soft text-danger text-base">{error}</div>}
        <div className="grid grid-cols-2 gap-3 mb-3">
          <div>
            <label className="block text-2xs uppercase tracking-wider font-medium text-fg-muted mb-1">Reviewer</label>
            <input className="input-px w-full" value={reviewer} onChange={e => setReviewer(e.target.value)} />
          </div>
          <div>
            <label className="block text-2xs uppercase tracking-wider font-medium text-fg-muted mb-1">State</label>
            <UiSelect value={state} onChange={setState} minWidth={200} inputStyle fullWidth
                      options={[{ value: "comment", label: "Comment" }, { value: "approve", label: "Approve" }, { value: "request_changes", label: "Request changes" }]} />
          </div>
        </div>
        <div className="mb-3">
          <label className="block text-2xs uppercase tracking-wider font-medium text-fg-muted mb-1">Summary comment</label>
          <textarea className="input-px textarea-px w-full" rows={2}
                    value={reasonText} onChange={e => setReasonText(e.target.value)}
                    placeholder="Optional summary..." />
        </div>
        <div className="mb-3">
          <label className="block text-2xs uppercase tracking-wider font-medium text-fg-muted mb-1">
            Inline comments {state === "approve" && <span className="text-danger ml-1">(at least 1 required)</span>}
          </label>
          <div className="space-y-2">
            {inlineComments.map((c, i) => (
              <div key={i} className="grid grid-cols-[2fr_60px_3fr_24px] gap-2">
                <input className="input-px font-mono" placeholder="path/to/file" value={c.file} onChange={e => updateRow(i, "file", e.target.value)} />
                <input className="input-px font-mono" placeholder="line" type="number" value={c.line} onChange={e => updateRow(i, "line", e.target.value)} />
                <input className="input-px" placeholder="comment" value={c.body} onChange={e => updateRow(i, "body", e.target.value)} />
                <button onClick={() => removeRow(i)} className="text-fg-muted hover:text-danger text-xl leading-none">×</button>
              </div>
            ))}
            <button onClick={addRow} className="btn-px btn-px-ghost btn-px-sm">+ Add inline comment</button>
          </div>
        </div>
        {state === "approve" && (
          <div className="mb-3">
            <label className="block text-2xs uppercase tracking-wider font-medium text-fg-muted mb-1">
              Considered alternatives <span className="text-danger ml-1">(at least 1 required)</span>
            </label>
            <textarea className="input-px textarea-px w-full" rows={2}
                      value={alts} onChange={e => setAlts(e.target.value)}
                      placeholder="One per line — e.g. 'rejected approach X because Y'" />
          </div>
        )}
        <div className="flex justify-end gap-2">
          <button onClick={onCancel} className="btn-px btn-px-ghost btn-px-sm">Cancel</button>
          <button onClick={submit} disabled={pending} className="btn-px btn-px-primary btn-px-sm">
            {pending ? "Submitting…" : "Submit review"}
          </button>
        </div>
      </div>
    );
  }

  // ------------------------- APIHub -------------------------
  // ===========================================================================
  // Cutover 43.20: RegistryHub — Apifox-style API workspace.
  // Left: searchable tree (Endpoints grouped by resource + Tables + MCP).
  // Right: rich detail — method/path, status, request/response schema (JSON-
  // highlighted), consumers, contract tests, breaking changes.
  // ===========================================================================
  function apiMethodTone(m) {
    return {
      GET:    { color: "var(--info)",        bg: "var(--info-soft)" },
      POST:   { color: "var(--success)",     bg: "var(--success-soft)" },
      PUT:    { color: "var(--warning)",     bg: "var(--warning-soft)" },
      PATCH:  { color: "var(--accent-on-soft)", bg: "var(--accent-soft)" },
      DELETE: { color: "var(--danger)",      bg: "var(--danger-soft)" },
    }[(m || "").toUpperCase()] || { color: "var(--text-muted)", bg: "var(--bg-tertiary)" };
  }
  function apiStatusVisual(s) {
    return {
      defined:     { label: "defined",     color: "var(--text-muted)", bg: "var(--bg-tertiary)" },
      implemented: { label: "implemented", color: "var(--info)",       bg: "var(--info-soft)" },
      tested:      { label: "tested",      color: "var(--warning)",    bg: "var(--warning-soft)" },
      verified:    { label: "verified",    color: "var(--success)",    bg: "var(--success-soft)" },
      deprecated:  { label: "deprecated",  color: "var(--danger)",     bg: "var(--danger-soft)" },
    }[s] || { label: s || "—", color: "var(--text-muted)", bg: "var(--bg-tertiary)" };
  }
  function MethodChip({ method, size = "sm" }) {
    const t = apiMethodTone(method);
    return (
      <span className={"font-mono font-semibold uppercase tracking-wide rounded shrink-0 " +
                       (size === "sm" ? "text-2xs px-1.5 py-0.5" : "text-xs px-2 py-0.5")}
            style={{ color: t.color, background: t.bg }}>
        {(method || "?").toUpperCase()}
      </span>
    );
  }
  function StatusBadge({ status }) {
    const v = apiStatusVisual(status);
    return (
      <span className="text-2xs uppercase tracking-wider font-medium px-1.5 py-0.5 rounded shrink-0"
            style={{ color: v.color, background: v.bg }}>{v.label}</span>
    );
  }
  // Data block: readable pretty view by default, with a one-click "raw" toggle.
  // (Replaces the old raw-JSON-only renderer; falls back to JSON if EnvGenData
  // isn't loaded yet.)
  function JsonBlock({ value, empty }) {
    const [raw, setRaw] = useState(false);
    const ref = React.useRef(null);
    const isEmpty = value == null
      || (typeof value === "object" && !Array.isArray(value) && Object.keys(value).length === 0)
      || (Array.isArray(value) && value.length === 0);
    const text = useMemo(() => {
      try { return JSON.stringify(value, null, 2); } catch { return String(value); }
    }, [value]);
    useEffect(() => {
      if (raw && ref.current && window.hljs) {
        ref.current.removeAttribute("data-highlighted");
        try { window.hljs.highlightElement(ref.current); } catch (e) {}
      }
    }, [text, raw]);
    if (isEmpty) {
      return <div className="text-xs text-fg-muted italic px-3 py-2">{empty || "No schema defined."}</div>;
    }
    const Pretty = window.EnvGenData && window.EnvGenData.PrettyData;
    return (
      <div className="rounded-md border border-border overflow-hidden bg-bg-elevated">
        <div className="flex justify-end px-2 py-1 border-b border-border-subtle">
          <button onClick={() => setRaw(r => !r)} className="text-2xs text-fg-muted hover:text-accent transition-colors">
            {raw ? "← pretty view" : "{ } raw"}
          </button>
        </div>
        {(!raw && Pretty)
          ? <div className="p-3 overflow-auto" style={{ maxHeight: "340px" }}><Pretty data={value} /></div>
          : <pre className="p-3 m-0 overflow-auto text-xs leading-relaxed font-mono" style={{ background: "var(--bg-secondary)", maxHeight: "340px" }}>
              <code ref={ref} className="hljs language-json">{text}</code>
            </pre>}
      </div>
    );
  }

  function RegistryHubPage({ projectId, hub, state }) {
    const Icons = window.Icons || {};
    const endpoints = Object.values(hub?.endpoints || {});
    const tables = Object.values(hub?.tables || {});
    const consumers = Object.values(hub?.consumers || {});
    const contractTests = Object.values(hub?.contract_tests || {});
    const breakingChanges = Object.values(hub?.breaking_changes || {});
    const apiReviews = Object.values(hub?.api_reviews || {});
    const mcpRegistry = Object.values(hub?.mcp_registry || {});
    const mcpServers = mcpRegistry.filter(p => p.kind === "server");
    const mcpTools = mcpRegistry.filter(p => p.kind === "tool");
    const mcpConsumers = mcpRegistry.filter(p => p.kind === "consumer");
    // FRONTEND CONTRACT (mechanism #50/#52): the ui_page / ui_component
    // lifecycle registries live on RegistryHub's ui_pages/ui_components
    // stores — surface them here because they ARE contract surface
    // (declared, framework-audited defined→implemented), exactly like
    // endpoints/tables. The ``title: name`` alias keeps downstream
    // ``.title`` usages working against the registry record's ``name``.
    const uiPages = Object.values(hub?.ui_pages || {}).map(p => ({ ...p, title: p.name }));
    const uiComponents = Object.values(hub?.ui_components || {}).map(c => ({ ...c, title: c.name }));
    const uiImpl = uiPages.filter(p => p.status === "implemented").length;
    const chains = Object.values(hub?.verification_chains || {});
    const chainsPassing = chains.filter(c => c.status === "passing").length;
    const compImpl = uiComponents.filter(p => p.status === "implemented").length;

    const [filter, setFilter] = useState("");
    const [sel, setSel] = useState(null); // {type:'endpoint'|'table'|'mcp'|'uipage'|'uicomp', id}
    const [openPages, setOpenPages] = useState({}); // ui_page folder expand state

    // group endpoints by resource (first two path segments)
    const groups = useMemo(() => {
      const m = {};
      for (const ep of endpoints) {
        const parts = (ep.path || "").split("/").filter(Boolean);
        const key = "/" + parts.slice(0, 2).join("/");
        (m[key] = m[key] || []).push(ep);
      }
      for (const k of Object.keys(m)) m[k].sort((a, b) => (a.path || "").localeCompare(b.path) || (a.method||"").localeCompare(b.method));
      return m;
    }, [endpoints]);

    const matchesFilter = (s) => !filter || (s || "").toLowerCase().includes(filter.toLowerCase());

    // default selection: first endpoint
    useEffect(() => {
      if (sel || endpoints.length === 0) return;
      setSel({ type: "endpoint", id: endpoints[0].id });
    }, [endpoints, sel]);

    const testPassRate = contractTests.length
      ? Math.round(100 * contractTests.filter(t => (t.result?.passed ?? t.result?.status === "passed")).length / contractTests.length)
      : null;

    const selected = useMemo(() => {
      if (!sel) return null;
      if (sel.type === "endpoint") return endpoints.find(e => e.id === sel.id);
      if (sel.type === "table") return tables.find(t => (t.id || t.name) === sel.id);
      if (sel.type === "mcp") return mcpServers.find(s => s.name === sel.id);
      if (sel.type === "uipage") return uiPages.find(p => p.id === sel.id);
      if (sel.type === "uicomp") return uiComponents.find(c => c.id === sel.id);
      return null;
    }, [sel, endpoints, tables, mcpServers, uiPages, uiComponents]);

    return (
      <HubLayout>
        {/* Metric tiles */}
        <div className="grid grid-cols-7 gap-3 mb-5">
          <MetricTile label="UI pages" value={uiPages.length}
            sub={`${uiImpl} implemented · ${uiComponents.length} components`}
            icon={Icons.layout || Icons.home} tone={uiPages.length && uiImpl === uiPages.length ? "success" : "info"} />
          <MetricTile label="Endpoints" value={endpoints.length}
            sub={`${endpoints.filter(e => e.status === "verified").length} verified`} icon={Icons.api} tone="info" />
          <MetricTile label="Tables" value={tables.length} sub="DB schema" icon={Icons.database} />
          <MetricTile label="Verification chains" value={chains.length}
            sub={chains.length ? `${chainsPassing} passing` : "verifier designs these"}
            icon={Icons.shieldCheck}
            tone={chains.length && chainsPassing === chains.length ? "success" : (chains.length ? "warning" : "neutral")} />
          <MetricTile label="Contract tests" value={contractTests.length}
            sub={testPassRate == null ? "none yet" : `${testPassRate}% pass`} icon={Icons.shieldCheck}
            tone={testPassRate != null && testPassRate < 100 ? "warning" : "success"} />
          <MetricTile label="MCP servers" value={mcpServers.length} sub={`${mcpTools.length} tools`} icon={Icons.server} />
          <MetricTile label="Breaking changes" value={breakingChanges.length}
            sub={breakingChanges.length ? "needs attention" : "all clear"} icon={Icons.bug}
            tone={breakingChanges.length ? "danger" : "neutral"} />
        </div>

        {/* 2-pane: tree + detail */}
        <div className="grid grid-cols-[320px_1fr] gap-4">
          {/* ===== LEFT: API tree ===== */}
          <HubCard className="self-start">
            <div className="p-2 border-b border-border">
              <div className="flex items-center gap-2 px-2 h-7 bg-bg-tertiary rounded-md border border-transparent focus-within:border-accent focus-within:bg-bg-elevated">
                {Icons.search && <span className="text-fg-muted shrink-0"><Icons.search size={11} /></span>}
                <input className="bare text-sm placeholder:text-fg-muted w-full"
                       placeholder="Find endpoint, table…" value={filter} onChange={e => setFilter(e.target.value)} />
                {filter && <button onClick={() => setFilter("")} className="text-fg-muted hover:text-fg shrink-0">×</button>}
              </div>
            </div>
            <div className="py-1.5 max-h-[68vh] overflow-y-auto">
              {/* Endpoints */}
              <div className="px-3 pt-1.5 pb-1 text-2xs uppercase tracking-wider font-semibold text-fg-muted">
                Endpoints <span className="text-fg-muted/60">{endpoints.length}</span>
              </div>
              {Object.keys(groups).sort().map(g => {
                const eps = groups[g].filter(e => matchesFilter(e.path) || matchesFilter(e.method));
                if (eps.length === 0) return null;
                return (
                  <div key={g} className="mb-1">
                    <div className="px-3 py-1 text-2xs font-mono text-fg-muted/70 flex items-center gap-1.5">
                      {Icons.folder && <Icons.folder size={11} />}{g}
                    </div>
                    {eps.map(ep => {
                      const isSel = sel?.type === "endpoint" && sel.id === ep.id;
                      const dep = ep.status === "deprecated";
                      return (
                        <button key={ep.id} onClick={() => setSel({ type: "endpoint", id: ep.id })}
                                className={"w-full text-left pl-5 pr-3 py-1.5 flex items-center gap-2 text-sm transition-colors " +
                                           (isSel ? "bg-accent-soft text-accent-on-soft" : "text-fg-secondary hover:bg-bg-hover")}>
                          <MethodChip method={ep.method} />
                          <code className={"font-mono truncate flex-1 min-w-0 " + (dep ? "line-through text-fg-muted" : "")}>{ep.path}</code>
                          <span className="w-1.5 h-1.5 rounded-full shrink-0" style={{ background: apiStatusVisual(ep.status).color }} />
                        </button>
                      );
                    })}
                  </div>
                );
              })}

              {/* Tables */}
              {tables.length > 0 && <>
                <div className="px-3 pt-3 pb-1 text-2xs uppercase tracking-wider font-semibold text-fg-muted border-t border-border mt-1">
                  Tables <span className="text-fg-muted/60">{tables.length}</span>
                </div>
                {tables.filter(t => matchesFilter(t.name || t.id)).map(t => {
                  const id = t.id || t.name; const isSel = sel?.type === "table" && sel.id === id;
                  return (
                    <button key={id} onClick={() => setSel({ type: "table", id })}
                            className={"w-full text-left px-3 py-1.5 flex items-center gap-2 text-sm transition-colors " +
                                       (isSel ? "bg-accent-soft text-accent-on-soft" : "text-fg-secondary hover:bg-bg-hover")}>
                      {Icons.database && <span className="text-fg-muted shrink-0"><Icons.database size={12} /></span>}
                      <code className="font-mono truncate flex-1">{t.name || id}</code>
                    </button>
                  );
                })}
              </>}

              {/* MCP servers */}
              {mcpServers.length > 0 && <>
                <div className="px-3 pt-3 pb-1 text-2xs uppercase tracking-wider font-semibold text-fg-muted border-t border-border mt-1">
                  MCP servers <span className="text-fg-muted/60">{mcpServers.length}</span>
                </div>
                {mcpServers.filter(s => matchesFilter(s.name)).map(s => {
                  const isSel = sel?.type === "mcp" && sel.id === s.name;
                  return (
                    <button key={s.name} onClick={() => setSel({ type: "mcp", id: s.name })}
                            className={"w-full text-left px-3 py-1.5 flex items-center gap-2 text-sm transition-colors " +
                                       (isSel ? "bg-accent-soft text-accent-on-soft" : "text-fg-secondary hover:bg-bg-hover")}>
                      {Icons.server && <span className="text-fg-muted shrink-0"><Icons.server size={12} /></span>}
                      <code className="font-mono truncate flex-1">{s.name}</code>
                    </button>
                  );
                })}
              </>}

              {/* UI pages — folders; components nest underneath (mechanism #52:
                  page → components → apis; status dots are framework-audited) */}
              {uiPages.length > 0 && <>
                <div className="px-3 pt-3 pb-1 text-2xs uppercase tracking-wider font-semibold text-fg-muted border-t border-border mt-1">
                  UI pages <span className="text-fg-muted/60">{uiPages.length}</span>
                  <span className="ml-1 text-fg-muted/60 normal-case tracking-normal">· {uiImpl} implemented</span>
                </div>
                {uiPages.filter(pg => matchesFilter(pg.title) || matchesFilter(pg.route)).map(pg => {
                  const isSel = sel?.type === "uipage" && sel.id === pg.id;
                  const kids = (pg.components || [])
                    .map(cid => uiComponents.find(c => c.title === cid || c.id === `component:ui:${cid}`))
                    .filter(Boolean);
                  const open = openPages[pg.id] ?? true;
                  const dot = (st) => st === "implemented" ? "#10b981" : "#f59e0b";
                  return (
                    <div key={pg.id} className="mb-0.5">
                      <div className={"w-full flex items-center gap-1 pr-3 text-sm transition-colors " +
                                      (isSel ? "bg-accent-soft text-accent-on-soft" : "text-fg-secondary hover:bg-bg-hover")}>
                        <button className="pl-3 py-1.5 shrink-0 text-fg-muted"
                                onClick={() => setOpenPages(o => ({ ...o, [pg.id]: !open }))}>
                          <span style={{ display: "inline-block", transition: "transform .15s",
                                         transform: open ? "rotate(90deg)" : "none" }}>▸</span>
                        </button>
                        <button className="flex-1 min-w-0 text-left py-1.5 flex items-center gap-2"
                                onClick={() => setSel({ type: "uipage", id: pg.id })}>
                          {Icons.folder && <Icons.folder size={12} />}
                          <span className="font-medium truncate">{pg.title}</span>
                          {pg.route && <code className="text-2xs text-fg-muted truncate">{pg.route}</code>}
                          <span className="ml-auto w-1.5 h-1.5 rounded-full shrink-0"
                                style={{ background: dot(pg.status) }} />
                        </button>
                      </div>
                      {open && kids.map(c => {
                        const cSel = sel?.type === "uicomp" && sel.id === c.id;
                        return (
                          <button key={c.id} onClick={() => setSel({ type: "uicomp", id: c.id })}
                                  className={"w-full text-left pl-9 pr-3 py-1 flex items-center gap-2 text-sm transition-colors " +
                                             (cSel ? "bg-accent-soft text-accent-on-soft" : "text-fg-muted hover:bg-bg-hover")}>
                            <span className="text-fg-muted/60">⬡</span>
                            <span className="truncate">{c.title}</span>
                            <span className="ml-auto w-1.5 h-1.5 rounded-full shrink-0"
                                  style={{ background: dot(c.status) }} />
                          </button>
                        );
                      })}
                      {open && (pg.components || []).length > 0 && kids.length === 0 && (
                        <div className="pl-9 pr-3 py-1 text-2xs text-fg-muted">
                          {pg.status === "implemented"
                            ? <span>inline component(s): {(pg.components || []).join(", ")} (built into the page, not shared)</span>
                            : <span>components declared but not yet registered: {(pg.components || []).join(", ")}</span>}
                        </div>
                      )}
                    </div>
                  );
                })}
                {/* orphan components (not referenced by any page) */}
                {(() => {
                  const referenced = new Set(uiPages.flatMap(pg => pg.components || []));
                  const orphans = uiComponents.filter(c => !referenced.has(c.title));
                  if (!orphans.length) return null;
                  return (<>
                    <div className="px-3 pt-2 pb-1 text-2xs text-fg-muted/70">shared / unreferenced components</div>
                    {orphans.map(c => {
                      const cSel = sel?.type === "uicomp" && sel.id === c.id;
                      return (
                        <button key={c.id} onClick={() => setSel({ type: "uicomp", id: c.id })}
                                className={"w-full text-left pl-6 pr-3 py-1 flex items-center gap-2 text-sm transition-colors " +
                                           (cSel ? "bg-accent-soft text-accent-on-soft" : "text-fg-muted hover:bg-bg-hover")}>
                          <span className="text-fg-muted/60">⬡</span>
                          <span className="truncate">{c.title}</span>
                          <span className="ml-auto w-1.5 h-1.5 rounded-full shrink-0"
                                style={{ background: c.status === "implemented" ? "#10b981" : "#f59e0b" }} />
                        </button>
                      );
                    })}
                  </>);
                })()}
              </>}

              {endpoints.length === 0 && tables.length === 0 && mcpServers.length === 0 && uiPages.length === 0 && (
                <div className="px-4 py-6 text-sm text-fg-muted">No contract surface registered yet.</div>
              )}
            </div>
          </HubCard>

          {/* ===== RIGHT: detail ===== */}
          <div className="self-start">
            {!selected ? (
              <HubCard><EmptyState icon={Icons.api} title="Select an endpoint"
                sub="Pick an endpoint, table, or MCP server from the left to see its full contract." /></HubCard>
            ) : sel.type === "endpoint" ? (
              <EndpointDetail ep={selected} consumers={consumers} contractTests={contractTests}
                              examples={Object.values(hub?.examples || {})} mocks={Object.values(hub?.mocks || {})}
                              apiReviews={apiReviews} state={state} projectId={projectId} />
            ) : sel.type === "table" ? (
              <TableDetail table={selected} hub={hub} projectId={projectId} />
            ) : sel.type === "uipage" ? (
              <UiPageDetail page={selected} components={uiComponents} projectId={projectId} />
            ) : sel.type === "uicomp" ? (
              <UiComponentDetail comp={selected} pages={uiPages} projectId={projectId} />
            ) : (
              <McpDetail server={selected} tools={mcpTools} consumers={mcpConsumers} projectId={projectId} />
            )}
          </div>
        </div>
      </HubLayout>
    );
  }

  function UiPageDetail({ page, components, projectId }) {
    const Icons = window.Icons || {};
    const dot = (st) => st === "implemented" ? "#10b981" : "#f59e0b";
    const kids = (page.components || [])
      .map(cid => components.find(c => c.title === cid) || { title: cid, status: "defined", _missing: true });
    return (
      <HubCard>
        <header className="px-4 h-12 flex items-center gap-3 border-b border-border">
          {Icons.folder && <Icons.folder size={14} />}
          <h3 className="text-md font-semibold">{page.title}</h3>
          {page.route && <code className="text-sm text-fg-muted">{page.route}</code>}
          <span className="ml-auto text-sm font-medium" style={{ color: dot(page.status) }}>{page.status}</span>
        </header>
        <div className="p-4 space-y-4">
          <div className="grid grid-cols-2 gap-3 text-sm">
            <div><div className="text-2xs uppercase text-fg-muted mb-1">Root component</div>
              <code>{page.component || "—"}</code></div>
            <div><div className="text-2xs uppercase text-fg-muted mb-1">Source path</div>
              <code className="truncate">{page.path || "—"}</code></div>
          </div>
          <div>
            <div className="text-2xs uppercase text-fg-muted mb-1.5">Page-level APIs</div>
            {(page.apis_used || []).length ? (page.apis_used || []).map(a =>
              <code key={a} className="inline-block mr-2 mb-1 px-1.5 py-0.5 rounded bg-bg-tertiary text-sm">{a}</code>)
              : <span className="text-sm text-fg-muted">none declared</span>}
          </div>
          <div>
            <div className="text-2xs uppercase text-fg-muted mb-1.5">Components ({kids.length})</div>
            {kids.length ? kids.map(c => (
              <div key={c.title} className="flex items-center gap-2 text-sm py-1 border-b border-border/40 last:border-0">
                <span className="w-1.5 h-1.5 rounded-full" style={{ background: dot(c.status) }} />
                <span>{c.title}</span>
                {c._missing && <span className="text-2xs text-warning">declared, not registered</span>}
                <span className="ml-auto text-2xs text-fg-muted">{c.status}</span>
              </div>
            )) : <span className="text-sm text-fg-muted">page composes no declared components</span>}
          </div>
          <div className="text-2xs text-fg-muted">
            Lifecycle is FRAMEWORK-AUDITED: implemented = component exists + route wired in App.jsx +
            every declared API referenced + controls bound (and all referenced components implemented).
          </div>
        </div>
      </HubCard>
    );
  }

  function UiComponentDetail({ comp, pages, projectId }) {
    const dot = (st) => st === "implemented" ? "#10b981" : "#f59e0b";
    const usedBy = pages.filter(p => (p.components || []).includes(comp.title));
    return (
      <HubCard>
        <header className="px-4 h-12 flex items-center gap-3 border-b border-border">
          <span>⬡</span>
          <h3 className="text-md font-semibold">{comp.title}</h3>
          {comp.component && <code className="text-sm text-fg-muted">{comp.component}</code>}
          <span className="ml-auto text-sm font-medium" style={{ color: dot(comp.status) }}>{comp.status}</span>
        </header>
        <div className="p-4 space-y-4 text-sm">
          {comp.comp_kind && <div><span className="text-2xs uppercase text-fg-muted mr-2">Kind</span>{comp.comp_kind}</div>}
          <div>
            <div className="text-2xs uppercase text-fg-muted mb-1.5">APIs this component calls</div>
            {(comp.apis_used || []).length ? (comp.apis_used || []).map(a =>
              <code key={a} className="inline-block mr-2 mb-1 px-1.5 py-0.5 rounded bg-bg-tertiary">{a}</code>)
              : <span className="text-fg-muted">none declared</span>}
          </div>
          {(comp.children || []).length > 0 && (
            <div><div className="text-2xs uppercase text-fg-muted mb-1.5">Nested components</div>
              {(comp.children || []).join(", ")}</div>
          )}
          <div>
            <div className="text-2xs uppercase text-fg-muted mb-1.5">Used by pages</div>
            {usedBy.length ? usedBy.map(p => p.title).join(", ")
              : <span className="text-fg-muted">no page references it yet</span>}
          </div>
        </div>
      </HubCard>
    );
  }

  // TestCard — renders a contract/smoke test with "what it tests" (target) and
  // "what code ran" (command + test_file, the file link opening in CodeHub).
  function TestCard({ kind, passed, statusLabel, agent, note, when, evidence, result, projectId }) {
    const Icons = window.Icons || {};
    const ev = evidence || {};
    const target = ev.target || ev.tests || ev.description || (result && result.target);
    const command = ev.command || ev.cmd || ev.run;
    const testFile = ev.test_file || ev.file || ev.code_file;
    const cases = Array.isArray(ev.cases) ? ev.cases : (Array.isArray(ev.assertions) ? ev.assertions : null);
    // remaining evidence keys for the expandable raw view
    const known = new Set(["summary", "target", "tests", "description", "command", "cmd", "run", "test_file", "file", "code_file", "cases", "assertions"]);
    const extra = Object.fromEntries(Object.entries(ev).filter(([k]) => !known.has(k)));
    return (
      <li className="px-3 py-2.5 border border-border rounded-md bg-bg-elevated">
        <div className="flex items-center gap-2.5 flex-wrap">
          <span className={"text-2xs font-mono font-semibold uppercase px-1.5 py-0.5 rounded " + (passed ? "text-success" : "text-danger")}
                style={{ background: passed ? "var(--success-soft)" : "var(--danger-soft)" }}>{statusLabel}</span>
          <code className="text-xs font-mono text-fg-secondary font-medium">{kind}</code>
          {agent && <ActorChip name={agent} />}
          {note && <span className="text-2xs text-fg-muted">{note}</span>}
          <span className="text-2xs text-fg-muted ml-auto">{fmtRel(when)}</span>
        </div>
        {/* what it tests */}
        {target && (
          <div className="text-xs text-fg-secondary mt-1.5">
            <span className="text-fg-muted">tests:</span> {target}
          </div>
        )}
        {ev.summary && (
          <div className="text-xs text-fg-secondary mt-1.5 bg-bg-tertiary rounded px-2 py-1">{ev.summary}</div>
        )}
        {/* the code that ran */}
        {command && (
          <div className="mt-1.5 font-mono text-2xs text-fg-secondary bg-bg-secondary rounded px-2 py-1 overflow-x-auto whitespace-pre">
            <span className="text-fg-muted select-none">$ </span>{command}
          </div>
        )}
        {testFile && (
          <button onClick={() => window.LiveMonitorRouter.openCodeFile(projectId, testFile)}
                  title="Open test file in CodeHub"
                  className="mt-1.5 inline-flex items-center gap-1.5 text-2xs font-mono text-accent hover:underline">
            {Icons.file && <Icons.file size={11} />}{testFile}
          </button>
        )}
        {cases && cases.length > 0 && (
          <ul className="mt-1.5 space-y-0.5">
            {cases.map((c, i) => {
              const ok = typeof c === "object" ? (c.passed ?? c.ok) : true;
              const label = typeof c === "object" ? (c.name || c.case || JSON.stringify(c)) : String(c);
              return (
                <li key={i} className="text-2xs text-fg-secondary flex items-center gap-1.5">
                  <span className={ok ? "text-success" : "text-danger"}>{ok ? "✓" : "✕"}</span>{label}
                </li>
              );
            })}
          </ul>
        )}
        {Object.keys(extra).length > 0 && (
          <details className="mt-1.5">
            <summary className="cursor-pointer text-2xs text-fg-muted hover:text-fg-secondary">Raw evidence</summary>
            <pre className="mt-1 text-2xs font-mono bg-bg-secondary rounded p-2 overflow-x-auto" style={{ maxHeight: 200 }}>
              {JSON.stringify(extra, null, 2)}
            </pre>
          </details>
        )}
      </li>
    );
  }

  function EndpointDetail({ ep, consumers, contractTests, examples = [], mocks = [], apiReviews = [], state, projectId }) {
    const Icons = window.Icons || {};
    const nav = (p) => window.LiveMonitorRouter.navigateTo(p);
    const myConsumers = consumers.filter(c => c.endpoint_id === ep.id);
    const myTests = contractTests.filter(t => t.endpoint_id === ep.id)
      .sort((a, b) => (b.created_at || 0) - (a.created_at || 0));
    const myExamples = examples.filter(e => e.endpoint_id === ep.id);
    const myMocks = mocks.filter(m => m.endpoint_id === ep.id);
    const myReviews = apiReviews.filter(r => r.endpoint_id === ep.id)
      .sort((a, b) => (b.created_at || 0) - (a.created_at || 0));
    const bc = ep.breaking_change;

    // Cross-hub dependencies: PRs + WorkHub tasks that link this endpoint, and
    // CodeHub api_smoke checks on those PRs.
    const ch = state?.hubs?.codehub || {};
    const wh = state?.hubs?.workhub || {};
    const linkedPRs = Object.values(ch.pull_requests || {}).filter(p => (p.linked_apis || []).includes(ep.id));
    const linkedTasks = Object.values(wh.tasks || {}).filter(t => (t.linked_apis || []).includes(ep.id));
    const prIds = new Set(linkedPRs.map(p => p.id));
    const smokeChecks = Object.values(ch.checks || {})
      .filter(c => prIds.has(c.pr_id) && /smoke|health/i.test(c.name || ""))
      .sort((a, b) => (b.updated_at || 0) - (a.updated_at || 0));
    const hasDeps = linkedPRs.length || linkedTasks.length;

    return (
      <div className="space-y-4">
        {/* Header */}
        <HubCard>
          <div className="p-4">
            <div className="flex items-center gap-3 mb-2">
              <MethodChip method={ep.method} size="lg" />
              <code className="font-mono text-lg font-semibold text-fg truncate flex-1 min-w-0">{ep.path}</code>
              <StatusBadge status={ep.status} />
            </div>
            <div className="flex items-center flex-wrap gap-x-3 gap-y-1 text-xs text-fg-muted">
              <span>provider <span className="text-fg-secondary">{ep.provider || "—"}</span></span>
              {ep.metadata?.auth_required != null && <>
                <span className="text-fg-muted/40">·</span>
                <span>{ep.metadata.auth_required ? "🔒 auth required" : "public"}</span>
              </>}
              {ep.metadata?.response_key && <>
                <span className="text-fg-muted/40">·</span>
                <span>response key <code className="font-mono">{ep.metadata.response_key}</code></span>
              </>}
              <span className="text-fg-muted/40">·</span>
              <span>updated {fmtRel(ep._updated_at)}</span>
            </div>
          </div>
        </HubCard>

        {/* Breaking change warning */}
        {bc?.is_breaking && (
          <div className="px-4 py-3 rounded-lg bg-danger-soft border border-danger/30 text-sm">
            <div className="font-semibold text-danger flex items-center gap-1.5 mb-1">⚠ Breaking change detected</div>
            <ul className="text-xs text-fg-secondary list-disc pl-5 space-y-0.5">
              {(bc.removed_response_fields || []).length > 0 && <li>Removed response fields: {bc.removed_response_fields.join(", ")}</li>}
              {(bc.type_changed_fields || []).length > 0 && <li>Type changed: {bc.type_changed_fields.join(", ")}</li>}
              {(bc.required_added_in_request || []).length > 0 && <li>New required request fields: {bc.required_added_in_request.join(", ")}</li>}
              {bc.method_changed && <li>HTTP method changed</li>}
              {bc.path_changed && <li>Path changed</li>}
              {bc.auth_added && <li>Auth requirement added</li>}
            </ul>
          </div>
        )}

        {/* Contract review (API review workflow) */}
        {myReviews.length > 0 && (
          <HubCard>
            <HubCardHeader title="Contract review" subtitle={`${myReviews.length}`} />
            <ul className="p-3 space-y-2">
              {myReviews.map((r, i) => {
                const tone = { approve: "var(--success)", request_changes: "var(--warning)", comment: "var(--info)", pending: "var(--text-muted)" }[r.status] || "var(--text-muted)";
                const toneBg = { approve: "var(--success-soft)", request_changes: "var(--warning-soft)", comment: "var(--info-soft)", pending: "var(--bg-tertiary)" }[r.status] || "var(--bg-tertiary)";
                return (
                  <li key={i} className="px-3 py-2.5 border border-border rounded-md bg-bg-elevated">
                    <div className="flex items-center gap-2.5 flex-wrap">
                      <span className="text-2xs font-mono font-semibold uppercase px-1.5 py-0.5 rounded" style={{ color: tone, background: toneBg }}>{r.status}</span>
                      {r.created_by && <span className="text-xs text-fg-secondary">requested by <ActorChip name={r.created_by} /></span>}
                      <span className="text-2xs text-fg-muted ml-auto">{fmtRel(r.created_at)}</span>
                    </div>
                    {r.reason && <div className="text-xs text-fg-secondary mt-1.5">{r.reason}</div>}
                    <div className="flex items-center gap-2 mt-1.5 flex-wrap text-2xs text-fg-muted">
                      <span>reviewers:</span>
                      {(r.reviewers || []).map(rv => (
                        <span key={rv} className={"px-1.5 py-0.5 rounded " + ((r.reviewed_by || []).includes(rv) ? "bg-success-soft text-success" : "bg-bg-tertiary text-fg-muted")}>{rv}</span>
                      ))}
                    </div>
                    {Array.isArray(r.comments) && r.comments.filter(Boolean).length > 0 && (
                      <ul className="mt-1.5 space-y-1">
                        {r.comments.filter(Boolean).map((c, ci) => (
                          <li key={ci} className="text-xs text-fg-secondary border-l-2 border-border-strong pl-2">{typeof c === "string" ? c : (c.body || JSON.stringify(c))}</li>
                        ))}
                      </ul>
                    )}
                  </li>
                );
              })}
            </ul>
          </HubCard>
        )}

        {/* Request / Response schema */}
        <div className="grid grid-cols-2 gap-4">
          <HubCard>
            <HubCardHeader title="Request" subtitle="schema" />
            <div className="p-3"><JsonBlock value={ep.schema?.request} empty="No request body." /></div>
          </HubCard>
          <HubCard>
            <HubCardHeader title="Response" subtitle="schema" />
            <div className="p-3"><JsonBlock value={ep.schema?.response} empty="No response schema." /></div>
          </HubCard>
        </div>

        {/* Smoke / contract tests — what it tests + the code/command it ran */}
        <HubCard>
          <HubCardHeader title="Tests" subtitle={`${myTests.length} contract · ${smokeChecks.length} smoke`} />
          {myTests.length === 0 && smokeChecks.length === 0 ? (
            <EmptyState icon={Icons.shieldCheck} title="No tests yet"
              sub="Contract tests (verifier) and api_smoke checks (from linked PRs) appear here." />
          ) : (
            <ul className="p-3 space-y-2">
              {myTests.slice(0, 10).map((t, i) => {
                const passed = t.result?.passed ?? t.result?.status === "passed";
                return (
                  <TestCard key={"t" + i} kind="contract test" passed={passed}
                    statusLabel={passed ? "passed" : (t.result?.status || "failed")}
                    agent={t.agent || "verifier"} when={t.created_at} evidence={t.evidence}
                    result={t.result} projectId={projectId} />
                );
              })}
              {smokeChecks.map((c, i) => (
                <TestCard key={"s" + i} kind={c.name || "api_smoke"} passed={c.status === "passed"}
                  statusLabel={c.status} note={`smoke · PR ${(c.pr_id || "").substr(0, 8)}`}
                  when={c.updated_at} evidence={c.evidence} projectId={projectId} />
              ))}
            </ul>
          )}
        </HubCard>

        {/* Declaration — examples & mocks (the declared request/response contract) */}
        <HubCard>
          <HubCardHeader title="Declaration" subtitle={`${myExamples.length} example${myExamples.length === 1 ? "" : "s"}${myMocks.length ? ` · ${myMocks.length} mock` : ""}`} />
          {myExamples.length === 0 && myMocks.length === 0 ? (
            <EmptyState icon={Icons.clipboard} title="No examples declared"
              sub="Agents declare request/response examples and mocks via registryhub_add_example." />
          ) : (
            <div className="p-3 space-y-3">
              {myExamples.map((ex, i) => (
                <div key={"e" + i} className="border border-border rounded-md overflow-hidden">
                  <div className="px-3 h-8 flex items-center gap-2 bg-bg-secondary/60 border-b border-border text-2xs uppercase tracking-wider font-medium text-fg-muted">
                    Example {myExamples.length > 1 ? i + 1 : ""}
                    {ex.created_by && <span className="ml-auto"><ActorChip name={ex.created_by} /></span>}
                  </div>
                  <div className="grid grid-cols-2 gap-3 p-3">
                    <div>
                      <div className="text-2xs uppercase tracking-wider font-medium text-fg-muted mb-1">Request</div>
                      <JsonBlock value={ex.request} empty="—" />
                    </div>
                    <div>
                      <div className="text-2xs uppercase tracking-wider font-medium text-fg-muted mb-1">Response</div>
                      <JsonBlock value={ex.response} empty="—" />
                    </div>
                  </div>
                </div>
              ))}
              {myMocks.map((mk, i) => (
                <div key={"m" + i} className="border border-border rounded-md overflow-hidden">
                  <div className="px-3 h-8 flex items-center gap-2 bg-bg-secondary/60 border-b border-border text-2xs uppercase tracking-wider font-medium text-fg-muted">
                    Mock response
                  </div>
                  <div className="p-3"><JsonBlock value={mk.response} empty="—" /></div>
                </div>
              ))}
            </div>
          )}
        </HubCard>

        {/* Dependencies & links — consumers + cross-hub PRs/tasks */}
        <HubCard>
          <HubCardHeader title="Dependencies & links" subtitle={`${myConsumers.length} consumer${myConsumers.length === 1 ? "" : "s"}`} />
          <div className="p-3 space-y-3">
            {/* consumers (who calls this endpoint) */}
            <div>
              <div className="text-2xs uppercase tracking-wider font-medium text-fg-muted mb-1.5">Consumed by</div>
              {myConsumers.length === 0 ? (
                <div className="text-xs text-fg-muted italic">No files registered as depending on this endpoint.</div>
              ) : (
                <div className="space-y-2">
                  {myConsumers.map((c, i) => (
                    <button key={i} onClick={() => window.LiveMonitorRouter.openCodeFile(projectId, c.file_path)}
                            title="Open in CodeHub"
                            className="w-full text-left px-3 py-2 border border-border rounded-md bg-bg-elevated hover:border-border-strong hover:bg-bg-hover transition-all flex items-center gap-2 group">
                      {Icons.file && <span className="text-fg-muted shrink-0"><Icons.file size={12} /></span>}
                      <code className="font-mono text-xs text-fg truncate flex-1 group-hover:text-accent transition-colors">{c.file_path}</code>
                      <ActorChip name={c.agent} />
                      {Icons.chevronRight && <span className="text-fg-muted opacity-0 group-hover:opacity-100 transition-opacity shrink-0"><Icons.chevronRight size={12} /></span>}
                    </button>
                  ))}
                </div>
              )}
            </div>
            {/* linked PRs */}
            {linkedPRs.length > 0 && (
              <div>
                <div className="text-2xs uppercase tracking-wider font-medium text-fg-muted mb-1.5">Pull requests</div>
                <div className="space-y-2">
                  {linkedPRs.map(p => (
                    <button key={p.id} onClick={() => nav(`/projects/${encodeURIComponent(projectId)}/codehub/pr/${encodeURIComponent(p.id)}`)}
                            className="w-full text-left px-3 py-2 border border-border rounded-md bg-bg-elevated hover:border-border-strong hover:bg-bg-hover transition-all flex items-center gap-2">
                      {Icons.code && <span className="text-fg-muted shrink-0"><Icons.code size={12} /></span>}
                      <span className="text-xs text-fg truncate flex-1">{p.title || p.id}</span>
                      <span className="text-2xs font-mono text-fg-muted">{p.source_branch || p.head}</span>
                    </button>
                  ))}
                </div>
              </div>
            )}
            {/* linked WorkHub tasks */}
            {linkedTasks.length > 0 && (
              <div>
                <div className="text-2xs uppercase tracking-wider font-medium text-fg-muted mb-1.5">Tasks</div>
                <div className="space-y-2">
                  {linkedTasks.map(t => (
                    <button key={t.id} onClick={() => nav(`/projects/${encodeURIComponent(projectId)}/workhub`)}
                            className="w-full text-left px-3 py-2 border border-border rounded-md bg-bg-elevated hover:border-border-strong hover:bg-bg-hover transition-all flex items-center gap-2">
                      {Icons.workhub && <span className="text-fg-muted shrink-0"><Icons.workhub size={12} /></span>}
                      <span className="text-xs text-fg truncate flex-1">{t.title || t.id}</span>
                      <span className="text-2xs font-mono text-fg-muted">{t.status}</span>
                    </button>
                  ))}
                </div>
              </div>
            )}
            {!hasDeps && myConsumers.length === 0 && (
              <div className="text-xs text-fg-muted italic">No cross-hub links yet. Endpoints get linked to PRs/tasks via <code className="font-mono">linked_apis</code>.</div>
            )}
          </div>
        </HubCard>
      </div>
    );
  }

  function TableDetail({ table, hub, projectId }) {
    const Icons = window.Icons || {};
    // schema can arrive in several shapes from different agents:
    //   1. JSON string  — '{"columns": [...]}'   (agents that JSON-encode)
    //   2. {columns: [{name, type, primary?, ...}, ...]}   (real shape)
    //   3. {columns: [string, ...]}                          (legacy list-of-names)
    //   4. {columns: {colName: {type, ...} | "TYPE"}}        (dict form)
    //   5. {col: type}                                       (very legacy flat)
    // The previous renderer assumed #3 only and rendered objects as React
    // children — which throws "Objects are not valid as a React child" and
    // whites out the whole detail view. Normalize all shapes to a uniform
    // [{name, type, extra}] list here.
    let raw = table.schema || {};
    if (typeof raw === "string") {
      try { raw = JSON.parse(raw); } catch (_) { raw = {}; }
    }
    const colsSrc = (raw && typeof raw === "object" && "columns" in raw) ? raw.columns : raw;
    let cols = [];
    if (Array.isArray(colsSrc)) {
      cols = colsSrc.map((c, i) => {
        if (c == null) return { name: `col_${i}`, type: "" };
        if (typeof c === "string") return { name: c, type: "" };
        if (typeof c === "object") {
          const { name, type, ...rest } = c;
          return { name: String(name ?? `col_${i}`), type: String(type ?? ""), extra: rest };
        }
        return { name: String(c), type: "" };
      });
    } else if (colsSrc && typeof colsSrc === "object") {
      cols = Object.entries(colsSrc).map(([name, def]) => {
        if (def && typeof def === "object") {
          const { type, ...rest } = def;
          return { name, type: String(type ?? ""), extra: rest };
        }
        return { name, type: String(def ?? "") };
      });
    }
    const tname = table.name || table.id;
    const tableConsumers = Object.values(hub?.table_consumers || {}).filter(c => c.table_name === tname);
    const seed = Object.values(hub?.seed_registrations || {}).filter(s => s.table_name === tname)
      .sort((a, b) => (b.registered_at || 0) - (a.registered_at || 0));
    const tableBreaks = Object.values(hub?.table_breaking_changes || {}).filter(b => (b.table_name || b.table) === tname)
      .sort((a, b) => (b.created_at || 0) - (a.created_at || 0));
    return (
      <div className="space-y-4">
        <HubCard>
          <div className="p-4">
            <div className="flex items-center gap-3 mb-2">
              {Icons.database && <span className="text-info shrink-0"><Icons.database size={18} /></span>}
              <code className="font-mono text-lg font-semibold text-fg flex-1">{table.name || table.id}</code>
              <StatusBadge status={table.status} />
            </div>
            <div className="text-xs text-fg-muted">
              provider <span className="text-fg-secondary">{table.provider || "—"}</span>
              <span className="text-fg-muted/40 mx-2">·</span>
              {cols.length} column{cols.length === 1 ? "" : "s"}
              <span className="text-fg-muted/40 mx-2">·</span>
              updated {fmtRel(table._updated_at)}
            </div>
          </div>
        </HubCard>
        <HubCard>
          <HubCardHeader title="Columns" subtitle={`${cols.length}`} />
          {cols.length === 0 ? (
            <EmptyState icon={Icons.database} title="No columns" sub="No schema columns defined." />
          ) : (
            <ul className="divide-y divide-border">
              {cols.map((c, i) => {
                const flags = [];
                const ex = c.extra || {};
                if (ex.primary || ex.primary_key) flags.push("PK");
                if (ex.unique) flags.push("UNIQUE");
                if (ex.nullable) flags.push("NULL");
                if (ex.references) flags.push("→ " + String(ex.references));
                return (
                  <li key={i} className="px-4 py-2.5 flex items-center gap-3">
                    <code className="font-mono text-sm text-fg flex-1">{c.name}</code>
                    {flags.map((f, j) => (
                      <span key={j} className="text-2xs uppercase tracking-wider font-medium px-1.5 py-0.5 rounded bg-bg-tertiary text-fg-muted shrink-0">{f}</span>
                    ))}
                    {c.type && <code className="font-mono text-xs text-info bg-info-soft px-2 py-0.5 rounded shrink-0">{c.type}</code>}
                  </li>
                );
              })}
            </ul>
          )}
        </HubCard>
        {tableConsumers.length > 0 && (
          <HubCard>
            <HubCardHeader title="Consumers" subtitle={`${tableConsumers.length} file${tableConsumers.length === 1 ? "" : "s"}`} />
            <ul className="p-3 space-y-2">
              {tableConsumers.map((c, i) => (
                <li key={i} className="px-3 py-2 border border-border rounded-md bg-bg-elevated flex items-center gap-2">
                  {Icons.file && <span className="text-fg-muted shrink-0"><Icons.file size={12} /></span>}
                  <button onClick={() => window.LiveMonitorRouter.openCodeFile(projectId, c.file_path)}
                          className="font-mono text-xs text-fg truncate flex-1 text-left hover:text-accent transition-colors" title="Open in CodeHub">{c.file_path}</button>
                  <ActorChip name={c.agent} />
                </li>
              ))}
            </ul>
          </HubCard>
        )}
        {/* Seed data (DB seeding audit) */}
        {seed.length > 0 && (
          <HubCard>
            <HubCardHeader title="Seed data" subtitle={`${seed.length} registration${seed.length === 1 ? "" : "s"}`} />
            <ul className="p-3 space-y-2">
              {seed.map((s, i) => (
                <li key={i} className="px-3 py-2.5 border border-border rounded-md bg-bg-elevated">
                  <div className="flex items-center gap-2.5 text-xs">
                    <span className="font-semibold text-fg tabular-nums">{s.row_count} rows</span>
                    <ActorChip name={s.registered_by} />
                    <span className="text-2xs text-fg-muted ml-auto">{fmtRel(s.registered_at)}</span>
                  </div>
                  {Array.isArray(s.sample_excerpt) && s.sample_excerpt.length > 0 && (
                    <div className="mt-1.5"><JsonBlock value={s.sample_excerpt} /></div>
                  )}
                </li>
              ))}
            </ul>
          </HubCard>
        )}
        {/* Schema breaking changes */}
        {tableBreaks.length > 0 && (
          <div className="px-4 py-3 rounded-lg bg-danger-soft border border-danger/30 text-sm">
            <div className="font-semibold text-danger flex items-center gap-1.5 mb-1">⚠ Schema breaking changes ({tableBreaks.length})</div>
            <ul className="text-xs text-fg-secondary space-y-1">
              {tableBreaks.map((b, i) => {
                const info = b.breaking || b;
                return (
                  <li key={i} className="flex items-center gap-2">
                    <span className="text-2xs text-fg-muted">{fmtRel(b.created_at)}</span>
                    <span>{(info.removed_columns || []).length ? `removed: ${info.removed_columns.join(", ")}` : ""}
                          {(info.type_changed_columns || []).length ? ` · type changed: ${info.type_changed_columns.join(", ")}` : ""}</span>
                  </li>
                );
              })}
            </ul>
          </div>
        )}
      </div>
    );
  }

  function McpDetail({ server, tools, consumers = [], projectId }) {
    const Icons = window.Icons || {};
    const myTools = tools.filter(t => t.server_name === server.name);
    const myConsumers = consumers.filter(c => c.server_name === server.name);
    return (
      <div className="space-y-4">
        <HubCard>
          <div className="p-4">
            <div className="flex items-center gap-3 mb-2">
              {Icons.server && <span className="text-accent shrink-0"><Icons.server size={18} /></span>}
              <code className="font-mono text-lg font-semibold text-fg flex-1">{server.name}</code>
              <StatusBadge status={server.status} />
            </div>
            <div className="text-xs text-fg-muted flex items-center gap-2 flex-wrap">
              <span className="px-1.5 py-0.5 rounded bg-bg-tertiary font-mono">{server.transport}</span>
              <code className="font-mono text-fg-secondary">{server.endpoint}</code>
              <span className="text-fg-muted/40">·</span>
              <span>provider {server.provider || "—"}</span>
            </div>
          </div>
        </HubCard>
        <HubCard>
          <HubCardHeader title="Tools" subtitle={`${myTools.length}`} />
          {myTools.length === 0 ? (
            <EmptyState icon={Icons.wrench || Icons.server} title="No tools" sub="No MCP tools registered on this server." />
          ) : (
            <ul className="p-3 space-y-2">
              {myTools.map((t, i) => (
                <li key={i} className="px-3 py-2.5 border border-border rounded-md bg-bg-elevated">
                  <div className="flex items-center gap-2 mb-1">
                    <code className="font-mono text-sm font-medium text-fg flex-1">{t.tool_name}</code>
                    <StatusBadge status={t.status} />
                  </div>
                  {t.schema && Object.keys(t.schema).length > 0 && <JsonBlock value={t.schema} />}
                </li>
              ))}
            </ul>
          )}
        </HubCard>
        {/* MCP consumers — files that call this server's tools */}
        {myConsumers.length > 0 && (
          <HubCard>
            <HubCardHeader title="Consumers" subtitle={`${myConsumers.length} file${myConsumers.length === 1 ? "" : "s"}`} />
            <ul className="p-3 space-y-2">
              {myConsumers.map((c, i) => (
                <li key={i} className="px-3 py-2 border border-border rounded-md bg-bg-elevated flex items-center gap-2">
                  {Icons.file && <span className="text-fg-muted shrink-0"><Icons.file size={12} /></span>}
                  <button onClick={() => window.LiveMonitorRouter.openCodeFile(projectId, c.file_path)}
                          className="font-mono text-xs text-fg truncate flex-1 text-left hover:text-accent transition-colors" title="Open in CodeHub">{c.file_path}</button>
                  {c.tool_name && <code className="text-2xs text-fg-muted font-mono">{c.tool_name}</code>}
                  <ActorChip name={c.agent} />
                </li>
              ))}
            </ul>
          </HubCard>
        )}
      </div>
    );
  }

  // ===========================================================================
  // Cutover 43.23: WorkHub — Jira-style work tracker.
  // Board (kanban) + Backlog + Plans (epics) + Pages, plus a full issue detail.
  // ===========================================================================
  function workPriorityVisual(p) {
    return {
      P0: { label: "P0", name: "Highest", color: "var(--danger)",  bg: "var(--danger-soft)",  arrow: "⤒" },
      P1: { label: "P1", name: "High",    color: "var(--warning)", bg: "var(--warning-soft)", arrow: "↑" },
      P2: { label: "P2", name: "Medium",  color: "var(--info)",    bg: "var(--info-soft)",    arrow: "=" },
      P3: { label: "P3", name: "Low",     color: "var(--text-muted)", bg: "var(--bg-tertiary)", arrow: "↓" },
    }[p] || { label: p || "P2", name: "Medium", color: "var(--info)", bg: "var(--info-soft)", arrow: "=" };
  }
  function workStatusVisual(s) {
    return {
      pending:     { label: "To do",       color: "var(--text-muted)", bg: "var(--bg-tertiary)" },
      in_progress: { label: "In progress", color: "var(--info)",       bg: "var(--info-soft)" },
      completed:   { label: "Done",        color: "var(--success)",    bg: "var(--success-soft)" },
      failed:      { label: "Failed",      color: "var(--danger)",     bg: "var(--danger-soft)" },
      cancelled:   { label: "Cancelled",   color: "var(--text-muted)", bg: "var(--bg-tertiary)" },
    }[s] || { label: s || "To do", color: "var(--text-muted)", bg: "var(--bg-tertiary)" };
  }
  function PriorityChip({ priority }) {
    const v = workPriorityVisual(priority);
    return (
      <span className="inline-flex items-center gap-1 text-2xs font-mono font-semibold px-1.5 py-0.5 rounded shrink-0"
            style={{ color: v.color, background: v.bg }} title={v.name + " priority"}>
        <span>{v.arrow}</span>{v.label}
      </span>
    );
  }
  function TaskTypeIcon({ task, size = 13 }) {
    const Icons = window.Icons || {};
    const isBug = (task.metadata?.kind === "bug");
    const I = isBug ? Icons.bug : Icons.workhub;
    return <span className={isBug ? "text-danger" : "text-info"} title={isBug ? "Bug" : "Task"}>{I ? <I size={size} /> : (isBug ? "🐛" : "▪")}</span>;
  }
  function shortKey(id) {
    // Jira-like key: take the id tail, uppercase
    const s = (id || "").replace(/^plan:.*:/, "").replace(/^task_/, "");
    return "WORK-" + s.substr(0, 8);
  }

  function WorkHubPage({ projectId, hub, state, subResource, subResourceId }) {
    if (subResource === "task" && subResourceId) {
      return <TaskDetailView projectId={projectId} hub={hub} state={state} taskId={subResourceId} />;
    }
    if (subResource === "page" && subResourceId) {
      return <PageDetailView projectId={projectId} hub={hub} state={state} pageId={subResourceId} />;
    }
    return <WorkHubBoard projectId={projectId} hub={hub} state={state} />;
  }

  function WorkHubBoard({ projectId, hub, state }) {
    const Icons = window.Icons || {};
    const tasks = Object.values(hub?.tasks || {});
    const plans = Object.values(hub?.plans || {});
    const pages = Object.values(hub?.pages || {});
    const decisions = Object.values(hub?.decisions || {});
    const nav = (p) => window.LiveMonitorRouter.navigateTo(p);

    const [tab, setTab] = useState("board");
    const [q, setQ] = useState("");
    const [assigneeFilter, setAssigneeFilter] = useState("");

    // dependency helpers
    const byId = useMemo(() => Object.fromEntries(tasks.map(t => [t.id, t])), [tasks]);
    const isBlocked = (t) => (t.status === "pending") && (t.depends_on || []).some(d => byId[d] && byId[d].status !== "completed");

    const assignees = useMemo(() => {
      const s = new Set();
      tasks.forEach(t => { const a = t.claimed_by || t.assignee; if (a) s.add(a); });
      return [...s].sort();
    }, [tasks]);

    const filtered = useMemo(() => {
      let list = tasks;
      if (q.trim()) { const lq = q.toLowerCase(); list = list.filter(t => (t.title||"").toLowerCase().includes(lq) || (t.id||"").toLowerCase().includes(lq) || (t.description||"").toLowerCase().includes(lq)); }
      if (assigneeFilter) list = list.filter(t => (t.claimed_by || t.assignee) === assigneeFilter);
      return list;
    }, [tasks, q, assigneeFilter]);

    const PRI_RANK = { P0: 0, P1: 1, P2: 2, P3: 3 };
    const sortTasks = (arr) => [...arr].sort((a, b) =>
      (PRI_RANK[a.metadata?.priority] ?? 2) - (PRI_RANK[b.metadata?.priority] ?? 2) || (b.created_at||0) - (a.created_at||0));

    const cols = [
      { key: "pending", label: "To do" },
      { key: "in_progress", label: "In progress" },
      { key: "completed", label: "Done" },
      { key: "failed", label: "Failed / Cancelled", match: (t) => t.status === "failed" || t.status === "cancelled" },
    ];
    const colTasks = (c) => sortTasks(filtered.filter(c.match ? c.match : (t => (t.status || "pending") === c.key)));

    const done = tasks.filter(t => t.status === "completed").length;
    const inProg = tasks.filter(t => t.status === "in_progress").length;
    const blocked = tasks.filter(isBlocked).length;
    const pct = tasks.length ? Math.round(100 * done / tasks.length) : 0;

    function TaskCard({ t }) {
      const blk = isBlocked(t);
      return (
        <button onClick={() => nav(`/projects/${encodeURIComponent(projectId)}/workhub/task/${encodeURIComponent(t.id)}`)}
                className="w-full text-left bg-bg-elevated border border-border rounded-md p-2.5 hover:border-border-strong hover:shadow-sm transition-all group">
          <div className="text-sm text-fg font-medium leading-snug mb-2 group-hover:text-accent transition-colors line-clamp-2">{t.title || t.id}</div>
          {/* labels */}
          <div className="flex items-center flex-wrap gap-1 mb-2">
            {blk && <span className="text-2xs font-medium px-1.5 py-0.5 rounded bg-danger-soft text-danger">⛔ blocked</span>}
            {(t.linked_apis || []).length > 0 && <span className="text-2xs px-1.5 py-0.5 rounded bg-accent-soft text-accent-on-soft">{(t.linked_apis||[]).length} API</span>}
            {t.linked_pr && <span className="text-2xs px-1.5 py-0.5 rounded bg-info-soft text-info">PR</span>}
            {(t.depends_on || []).length > 0 && <span className="text-2xs px-1.5 py-0.5 rounded bg-bg-tertiary text-fg-muted">{(t.depends_on||[]).length} dep</span>}
          </div>
          <div className="flex items-center gap-2">
            <TaskTypeIcon task={t} />
            <code className="text-2xs font-mono text-fg-muted">{shortKey(t.id)}</code>
            <PriorityChip priority={t.metadata?.priority} />
            <span className="ml-auto text-2xs text-fg-secondary">{t.claimed_by || t.assignee || "unassigned"}</span>
          </div>
        </button>
      );
    }

    return (
      <HubLayout>
        {/* Metric tiles */}
        <div className="grid grid-cols-5 gap-3 mb-5">
          <MetricTile label="Total tasks" value={tasks.length} sub={`${pct}% done`} icon={Icons.workhub} tone="info" />
          <MetricTile label="In progress" value={inProg} sub="active now" icon={Icons.play} tone={inProg ? "info" : "neutral"} />
          <MetricTile label="Done" value={done} sub="completed" icon={Icons.shieldCheck} tone="success" />
          <MetricTile label="Blocked" value={blocked} sub={blocked ? "needs attention" : "all clear"} icon={Icons.bug} tone={blocked ? "warning" : "neutral"} />
          <MetricTile label="Plans" value={plans.length} sub={`${pages.length} pages`} icon={Icons.file} />
        </div>

        {/* Tabs + filters */}
        <div className="flex items-center gap-3 border-b border-border mb-5">
          <div className="flex gap-1">
            {[{k:"board",l:"Board"},{k:"backlog",l:"Backlog"},{k:"plans",l:"Plans"},{k:"pages",l:"Pages"},{k:"decisions",l:"Decisions"}].map(t => (
              <button key={t.k} onClick={() => setTab(t.k)}
                      className={"px-3 h-9 text-base font-medium flex items-center gap-2 border-b-2 -mb-px transition-colors " +
                                 (tab === t.k ? "text-fg border-accent" : "text-fg-secondary border-transparent hover:text-fg")}>
                {t.l}
              </button>
            ))}
          </div>
          {(tab === "board" || tab === "backlog") && (
            <div className="ml-auto flex items-center gap-2 pb-1.5">
              <div className="flex items-center gap-2 px-2.5 h-8 bg-bg-elevated rounded-md border border-border focus-within:border-accent">
                {Icons.search && <span className="text-fg-muted"><Icons.search size={12} /></span>}
                <input className="bare text-sm placeholder:text-fg-muted w-40" placeholder="Search tasks…" value={q} onChange={e => setQ(e.target.value)} />
              </div>
              <UiSelect value={assigneeFilter} onChange={setAssigneeFilter} placeholder="All assignees" size="md"
                        options={[{ value: "", label: "All assignees" }, ...assignees.map(a => ({ value: a, label: a }))]} />
            </div>
          )}
        </div>

        {/* ===== Board ===== */}
        {tab === "board" && (
          <div className="grid grid-cols-4 gap-3 items-start">
            {cols.map(c => {
              const list = colTasks(c);
              return (
                <div key={c.key} className="bg-bg-secondary/40 rounded-lg border border-border">
                  <div className="px-3 h-9 flex items-center gap-2 border-b border-border">
                    <span className="text-2xs uppercase tracking-wider font-semibold text-fg-muted">{c.label}</span>
                    <span className="text-2xs tabular-nums text-fg-muted bg-bg-tertiary rounded-full px-1.5">{list.length}</span>
                  </div>
                  <div className="p-2 space-y-2 min-h-[80px]">
                    {list.map(t => <TaskCard key={t.id} t={t} />)}
                  </div>
                </div>
              );
            })}
          </div>
        )}

        {/* ===== Backlog (flat ranked list) ===== */}
        {tab === "backlog" && (
          <HubCard>
            <HubCardHeader title="Backlog" subtitle={`${filtered.length} task${filtered.length === 1 ? "" : "s"}`} />
            {filtered.length === 0 ? (
              <EmptyState icon={Icons.workhub} title="No tasks" sub="Tasks created by the orchestrator/agents appear here." />
            ) : (
              <ul className="p-3 space-y-2">
                {sortTasks(filtered).map(t => {
                  const sv = workStatusVisual(t.status);
                  const blk = isBlocked(t);
                  return (
                    <li key={t.id}>
                      <button onClick={() => nav(`/projects/${encodeURIComponent(projectId)}/workhub/task/${encodeURIComponent(t.id)}`)}
                              className="w-full text-left px-3 py-2.5 border border-border rounded-md bg-bg-elevated hover:border-border-strong hover:bg-bg-hover transition-all flex items-center gap-3 group">
                        <TaskTypeIcon task={t} />
                        <code className="text-2xs font-mono text-fg-muted shrink-0 w-24 truncate">{shortKey(t.id)}</code>
                        <span className="text-sm text-fg font-medium flex-1 min-w-0 truncate group-hover:text-accent transition-colors">{t.title || t.id}</span>
                        {blk && <span className="text-2xs font-medium px-1.5 py-0.5 rounded bg-danger-soft text-danger shrink-0">blocked</span>}
                        {(t.linked_apis||[]).length > 0 && <span className="text-2xs px-1.5 py-0.5 rounded bg-accent-soft text-accent-on-soft shrink-0">{(t.linked_apis||[]).length} API</span>}
                        <PriorityChip priority={t.metadata?.priority} />
                        <span className="text-2xs uppercase tracking-wider font-medium px-1.5 py-0.5 rounded shrink-0" style={{ color: sv.color, background: sv.bg }}>{sv.label}</span>
                        <span className="text-2xs text-fg-secondary w-20 text-right truncate shrink-0">{t.claimed_by || t.assignee || "—"}</span>
                      </button>
                    </li>
                  );
                })}
              </ul>
            )}
          </HubCard>
        )}

        {/* ===== Plans (epics) ===== */}
        {tab === "plans" && (() => {
          // Hide the empty placeholder snapshots the step pipeline writes every
          // tick — they have no stages, no tasks, and just clutter the view.
          const realPlans = plans.filter(p =>
            p && p.has_plan !== false && (
              (p.task_ids && p.task_ids.length) ||
              (p.stages && (Array.isArray(p.stages) ? p.stages.length : Object.keys(p.stages).length)) ||
              (p.stage_order && p.stage_order.length)
            )
          );
          if (realPlans.length === 0) {
            return <HubCard><EmptyState icon={Icons.file} title="No plans yet"
              sub={`Plans group tasks into stages. ${plans.length > 0 ? `${plans.length} empty plan snapshot(s) auto-synced; will populate once an agent calls plan(...).` : "Created via the plan(...) tool."}`} /></HubCard>;
          }
          // Each plan snapshot is shaped as: { plan_name, current_stage_id,
          // stage_order: [...], stages: { <id>: { name, status, party_active,
          // tasks: { <task_id>: { status, assignee, acceptance } } } },
          // acceptance_summary: {...} }. Earlier render only walked
          // top-level `task_ids` (which is null in the real payload), so
          // even fully populated plans looked empty.
          return (
            <div className="space-y-4">
              {realPlans.map(pl => {
                const stageOrder = pl.stage_order && pl.stage_order.length
                  ? pl.stage_order
                  : (pl.stages && !Array.isArray(pl.stages) ? Object.keys(pl.stages) : []);
                const stagesMap = (pl.stages && !Array.isArray(pl.stages)) ? pl.stages : {};
                // Flatten stages → all tasks for header progress
                const allTasks = [];
                stageOrder.forEach(sid => {
                  const s = stagesMap[sid] || {};
                  const tasks = (s.tasks && !Array.isArray(s.tasks)) ? s.tasks : {};
                  Object.entries(tasks).forEach(([tid, t]) => allTasks.push({ stage: sid, id: tid, ...t }));
                });
                const pdone = allTasks.filter(t => t.status === "completed").length;
                const ppct = allTasks.length ? Math.round(100 * pdone / allTasks.length) : 0;
                const cur = pl.current_stage_id;
                const acc = pl.acceptance_summary || {};
                return (
                  <HubCard key={pl.id || pl.agent_id}>
                    <div className="px-4 py-3 border-b border-border">
                      <div className="flex items-center gap-2.5 flex-wrap">
                        <span className="text-accent shrink-0">{Icons.file && <Icons.file size={15} />}</span>
                        <span className="text-md font-semibold text-fg">{pl.plan_name || pl.title || `${pl.agent_id || pl.id} plan`}</span>
                        {cur && (
                          <span className="text-2xs uppercase tracking-wider font-medium px-1.5 py-0.5 rounded bg-accent-soft text-accent-on-soft">
                            current: {cur}
                          </span>
                        )}
                        {pl.active_party && (
                          <span className="text-2xs text-fg-muted">party: {pl.active_party}</span>
                        )}
                        <span className="ml-auto text-2xs text-fg-muted">
                          {pdone}/{allTasks.length} tasks
                          {acc.required ? ` · ${acc.resolved||0}/${acc.required} acceptance` : ""}
                        </span>
                      </div>
                      <div className="mt-2 h-1.5 rounded-full bg-bg-tertiary overflow-hidden">
                        <div className="h-full bg-success transition-all" style={{ width: `${ppct}%` }} />
                      </div>
                      {pl.plan_description && (
                        <div className="text-2xs text-fg-secondary mt-2 leading-snug">{pl.plan_description}</div>
                      )}
                    </div>

                    {stageOrder.length === 0 ? (
                      <div className="px-4 py-6 text-center text-2xs text-fg-muted">
                        Plan registered but has no stages yet.
                      </div>
                    ) : (
                      <ul className="p-3 space-y-3">
                        {stageOrder.map(sid => {
                          const stage = stagesMap[sid] || {};
                          const stageTasks = (stage.tasks && !Array.isArray(stage.tasks))
                            ? Object.entries(stage.tasks) : [];
                          const sStatus = (stage.status || "pending");
                          const sv = workStatusVisual(sStatus);
                          const isCurrent = sid === cur;
                          return (
                            <li key={sid} className={"border rounded-md " + (isCurrent ? "border-accent bg-accent-soft/30" : "border-border bg-bg-elevated")}>
                              <div className="px-3 py-2 flex items-center gap-2 border-b border-border">
                                <code className="text-2xs font-mono text-fg-secondary">{sid}</code>
                                {stage.name && <span className="text-sm font-medium text-fg">{stage.name}</span>}
                                {isCurrent && <span className="text-2xs uppercase tracking-wider font-medium text-accent">current</span>}
                                <span className="ml-auto text-2xs uppercase tracking-wider font-medium px-1.5 py-0.5 rounded"
                                      style={{ color: sv.color, background: sv.bg }}>{sv.label}</span>
                                <span className="text-2xs text-fg-muted tabular-nums">
                                  {stageTasks.filter(([, t]) => t.status === "completed").length}/{stageTasks.length}
                                </span>
                              </div>
                              {stageTasks.length === 0 ? (
                                <div className="px-3 py-2 text-2xs text-fg-muted">No tasks in this stage yet.</div>
                              ) : (
                                <ul className="p-2 space-y-1">
                                  {stageTasks.map(([tid, t]) => {
                                    const tv = workStatusVisual(t.status || "pending");
                                    return (
                                      <li key={tid} className="px-2 py-1.5 flex items-center gap-2 text-sm">
                                        <code className="text-2xs font-mono text-fg-muted shrink-0">{tid}</code>
                                        {t.assignee && <span className="text-2xs text-fg-muted">→ {t.assignee}</span>}
                                        <span className="ml-auto text-2xs uppercase tracking-wider font-medium px-1.5 py-0.5 rounded"
                                              style={{ color: tv.color, background: tv.bg }}>{tv.label}</span>
                                      </li>
                                    );
                                  })}
                                </ul>
                              )}
                            </li>
                          );
                        })}
                      </ul>
                    )}
                  </HubCard>
                );
              })}
            </div>
          );
        })()}

        {/* ===== Pages ===== */}
        {tab === "pages" && (
          <HubCard>
            <HubCardHeader title="Pages" subtitle={`${pages.length}`} />
            {pages.length === 0 ? (
              <EmptyState icon={Icons.file} title="No pages" sub="Design docs, plans, retros, and knowledge pages live here." />
            ) : (
              <ul className="p-3 space-y-2">
                {pages.map(p => {
                  const decCount = ((p.metadata || {}).decisions || []).length;
                  return (
                    <li key={p.id}>
                      <button onClick={() => nav(`/projects/${encodeURIComponent(projectId)}/workhub/page/${encodeURIComponent(p.id)}`)}
                              className="w-full text-left px-3 py-2.5 border border-border rounded-md bg-bg-elevated hover:border-border-strong hover:bg-bg-hover transition-all flex items-center gap-3 group">
                        {Icons.file && <span className="text-fg-muted shrink-0"><Icons.file size={14} /></span>}
                        <span className="text-sm text-fg font-medium flex-1 truncate group-hover:text-accent transition-colors">{p.title || p.id}</span>
                        <span className="text-2xs uppercase tracking-wider font-medium px-1.5 py-0.5 rounded bg-bg-tertiary text-fg-muted shrink-0">{p.kind || "general"}</span>
                        <StatusBadge status={p.status} />
                        {(p.attendees||[]).length > 0 && <span className="text-2xs text-fg-muted">{(p.attendees||[]).length} attendees</span>}
                        {decCount > 0 && <span className="text-2xs text-fg-muted">· {decCount} decision{decCount === 1 ? "" : "s"}</span>}
                      </button>
                    </li>
                  );
                })}
              </ul>
            )}
          </HubCard>
        )}

        {/* ===== Decisions ===== */}
        {tab === "decisions" && (
          <HubCard>
            <HubCardHeader title="Decisions" subtitle={`${decisions.length}`} />
            {decisions.length === 0 ? (
              <EmptyState icon={Icons.clipboard} title="No decisions" sub="Architectural decisions recorded by agents (options considered + chosen) land here." />
            ) : (
              <ul className="p-3 space-y-2">
                {decisions.sort((a,b)=>(b.created_at||0)-(a.created_at||0)).map(d => (
                  <li key={d.id} className="px-4 py-3 border border-border rounded-md bg-bg-elevated">
                    <div className="flex items-center gap-2 mb-1">
                      <span className="text-md font-semibold text-fg flex-1">{d.title}</span>
                      <ActorChip name={d.agent} />
                      <span className="text-2xs text-fg-muted">{fmtRel(d.created_at)}</span>
                    </div>
                    <div className="text-xs text-fg-secondary mb-1.5">
                      Chosen: <span className="text-success font-medium">{d.chosen}</span>
                      {Array.isArray(d.options) && d.options.length > 0 && (
                        <span className="text-fg-muted"> · of {d.options.join(", ")}</span>
                      )}
                    </div>
                    {d.reason && <div className="text-xs text-fg-secondary bg-bg-tertiary rounded px-2 py-1">{d.reason}</div>}
                  </li>
                ))}
              </ul>
            )}
          </HubCard>
        )}
      </HubLayout>
    );
  }

  // ===========================================================================
  // Cutover 43.23: TaskDetailView — Jira issue page.
  // ===========================================================================
  function TaskDetailView({ projectId, hub, state, taskId }) {
    const Icons = window.Icons || {};
    const tasks = hub?.tasks || {};
    const t = tasks[taskId];
    const nav = (p) => window.LiveMonitorRouter.navigateTo(p);
    const back = () => nav(`/projects/${encodeURIComponent(projectId)}/workhub`);

    if (!t) {
      return (
        <HubLayout>
          <button onClick={back} className="flex items-center gap-1.5 text-sm text-fg-secondary hover:text-accent mb-4">
            {Icons.chevronLeft && <Icons.chevronLeft size={14} />} Back to board
          </button>
          <EmptyState icon={Icons.workhub} title="Task not found" sub={`No task ${taskId} in this project.`} actionLabel="Back to WorkHub" onAction={back} />
        </HubLayout>
      );
    }

    const sv = workStatusVisual(t.status);
    const deps = (t.depends_on || []).map(id => tasks[id]).filter(Boolean);
    const blockedBy = Object.values(tasks).filter(x => (x.depends_on || []).includes(taskId));
    const comments = Object.values(hub?.comments || {}).filter(c => c.resource_id === taskId && !c.parent_id)
      .sort((a, b) => (a.created_at || 0) - (b.created_at || 0));
    const allComments = Object.values(hub?.comments || {});
    const reactions = Object.values(hub?.reactions || {});
    const repliesOf = (cid) => allComments.filter(c => c.parent_id === cid).sort((a,b)=>(a.created_at||0)-(b.created_at||0));
    // cross-hub
    const ch = state?.hubs?.codehub || {};
    const linkedPR = t.linked_pr ? Object.values(ch.pull_requests || {}).find(p => p.id === t.linked_pr || p.number === t.linked_pr) : null;
    // events referencing this task
    const events = Object.values(state?.hubs?.eventhub?.events || {})
      .filter(e => { const p = e.payload || {}; return p.task_id === taskId || p.id === taskId; })
      .sort((a, b) => (b.created_at || 0) - (a.created_at || 0));

    return (
      <HubLayout>
        <button onClick={back} className="flex items-center gap-1.5 text-sm text-fg-secondary hover:text-accent mb-4 transition-colors">
          {Icons.chevronLeft && <Icons.chevronLeft size={14} />} <span>Board</span>
        </button>

        <div className="grid grid-cols-[1fr_300px] gap-4 items-start">
          {/* ===== Main column ===== */}
          <div className="space-y-4">
            {/* Header */}
            <HubCard>
              <div className="p-4">
                <div className="flex items-center gap-2 mb-2 text-2xs text-fg-muted">
                  <TaskTypeIcon task={t} />
                  <code className="font-mono">{shortKey(t.id)}</code>
                  {t.plan_id && <><span className="text-fg-muted/40">·</span><span>in plan {t.plan_id}</span></>}
                </div>
                <h1 className="text-2xl font-semibold tracking-tight text-fg">{t.title || t.id}</h1>
              </div>
            </HubCard>

            {/* Description */}
            <HubCard>
              <HubCardHeader title="Description" />
              <div className="px-4 py-3 text-sm text-fg-secondary leading-relaxed whitespace-pre-wrap">
                {t.description || <span className="text-fg-muted italic">No description provided.</span>}
              </div>
            </HubCard>

            {/* Result / evidence (completed) */}
            {t.status === "completed" && (t.result || t.evidence) && (
              <HubCard>
                <HubCardHeader title="Result & evidence" subtitle="on completion" />
                <div className="p-3 space-y-3">
                  {t.result && Object.keys(t.result).length > 0 && (
                    <div><div className="text-2xs uppercase tracking-wider font-medium text-fg-muted mb-1">Result</div><JsonBlock value={t.result} /></div>
                  )}
                  {t.evidence && Object.keys(t.evidence).length > 0 && (
                    <div><div className="text-2xs uppercase tracking-wider font-medium text-fg-muted mb-1">Evidence</div><JsonBlock value={t.evidence} /></div>
                  )}
                </div>
              </HubCard>
            )}

            {/* Failure */}
            {t.status === "failed" && (
              <div className="px-4 py-3 rounded-lg bg-danger-soft border border-danger/30 text-sm">
                <div className="font-semibold text-danger mb-1">Failed</div>
                <div className="text-xs text-fg-secondary">{t.fail_reason || "No reason recorded."}</div>
              </div>
            )}

            {/* Dependencies */}
            {(deps.length > 0 || blockedBy.length > 0) && (
              <HubCard>
                <HubCardHeader title="Dependencies" />
                <div className="p-3 space-y-3">
                  {deps.length > 0 && (
                    <div>
                      <div className="text-2xs uppercase tracking-wider font-medium text-fg-muted mb-1.5">Blocked by (waits for)</div>
                      <div className="space-y-2">
                        {deps.map(d => {
                          const dv = workStatusVisual(d.status);
                          return (
                            <button key={d.id} onClick={() => nav(`/projects/${encodeURIComponent(projectId)}/workhub/task/${encodeURIComponent(d.id)}`)}
                                    className="w-full text-left px-3 py-2 border border-border rounded-md bg-bg-elevated hover:border-border-strong transition-all flex items-center gap-2">
                              {d.status === "completed" ? <span className="text-success">✓</span> : <span className="text-warning">●</span>}
                              <span className="text-xs text-fg flex-1 truncate">{d.title}</span>
                              <span className="text-2xs uppercase px-1.5 py-0.5 rounded" style={{ color: dv.color, background: dv.bg }}>{dv.label}</span>
                            </button>
                          );
                        })}
                      </div>
                    </div>
                  )}
                  {blockedBy.length > 0 && (
                    <div>
                      <div className="text-2xs uppercase tracking-wider font-medium text-fg-muted mb-1.5">Blocks (these wait for this)</div>
                      <div className="space-y-2">
                        {blockedBy.map(d => (
                          <button key={d.id} onClick={() => nav(`/projects/${encodeURIComponent(projectId)}/workhub/task/${encodeURIComponent(d.id)}`)}
                                  className="w-full text-left px-3 py-2 border border-border rounded-md bg-bg-elevated hover:border-border-strong transition-all flex items-center gap-2">
                            <span className="text-fg-muted">→</span>
                            <span className="text-xs text-fg flex-1 truncate">{d.title}</span>
                          </button>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              </HubCard>
            )}

            {/* Comments */}
            <HubCard>
              <HubCardHeader title="Comments" subtitle={`${comments.length}`} />
              {comments.length === 0 ? (
                <EmptyState icon={Icons.chat} title="No comments" sub="Agents discuss the task here via workhub_comment." />
              ) : (
                <ul className="p-3 space-y-3">
                  {comments.map(c => {
                    const replies = repliesOf(c.id);
                    const cReacts = reactions.filter(r => r.comment_id === c.id);
                    return (
                      <li key={c.id} className="border border-border rounded-md bg-bg-elevated overflow-hidden">
                        <div className="px-3 py-2">
                          <div className="flex items-center gap-2 mb-1">
                            <ActorChip name={c.agent} />
                            <span className="text-2xs text-fg-muted ml-auto">{fmtRel(c.created_at)}</span>
                          </div>
                          <div className="text-sm text-fg-secondary whitespace-pre-wrap">{c.body}</div>
                          {cReacts.length > 0 && (
                            <div className="flex items-center gap-1 mt-1.5">
                              {cReacts.map((r, i) => <span key={i} className="text-2xs px-1.5 py-0.5 rounded bg-bg-tertiary">{r.reaction} {r.agent}</span>)}
                            </div>
                          )}
                        </div>
                        {replies.length > 0 && (
                          <div className="border-t border-border bg-bg-secondary/40 pl-5 pr-3 py-2 space-y-2">
                            {replies.map(rp => (
                              <div key={rp.id}>
                                <div className="flex items-center gap-2 mb-0.5"><ActorChip name={rp.agent} /><span className="text-2xs text-fg-muted ml-auto">{fmtRel(rp.created_at)}</span></div>
                                <div className="text-xs text-fg-secondary whitespace-pre-wrap">{rp.body}</div>
                              </div>
                            ))}
                          </div>
                        )}
                      </li>
                    );
                  })}
                </ul>
              )}
            </HubCard>

            {/* Activity */}
            {events.length > 0 && (
              <HubCard>
                <HubCardHeader title="Activity" subtitle={`${events.length} events`} />
                <ul className="p-3 space-y-2">
                  {events.slice(0, 20).map((e, i) => (
                    <li key={e.id || i} className="px-3 py-2 border border-border rounded-md bg-bg-elevated flex items-center gap-2 text-xs">
                      <span className="font-mono font-medium text-fg">{e.event_type}</span>
                      <span className="text-fg-muted">by {e.source_hub || "—"}</span>
                      <span className="text-2xs text-fg-muted ml-auto">{fmtRel(e.created_at)}</span>
                    </li>
                  ))}
                </ul>
              </HubCard>
            )}
          </div>

          {/* ===== Side panel ===== */}
          <div className="space-y-3">
            <HubCard>
              <div className="p-3 space-y-3">
                <DetailField label="Status">
                  <span className="text-xs uppercase tracking-wider font-medium px-2 py-1 rounded" style={{ color: sv.color, background: sv.bg }}>{sv.label}</span>
                </DetailField>
                <DetailField label="Priority"><PriorityChip priority={t.metadata?.priority} /></DetailField>
                <DetailField label="Assignee"><span className="text-sm text-fg">{t.claimed_by || t.assignee || "Unassigned"}</span></DetailField>
                <DetailField label="Reporter"><span className="text-sm text-fg">{t.created_by || "—"}</span></DetailField>
                {t.metadata?.kind === "bug" && t.metadata?.severity && (
                  <DetailField label="Severity"><span className="text-sm text-danger font-medium">{t.metadata.severity}</span></DetailField>
                )}
                {t.metadata?.domain && <DetailField label="Domain"><span className="text-sm text-fg-secondary">{t.metadata.domain}</span></DetailField>}
                <DetailField label="Created"><span className="text-xs text-fg-secondary">{fmtFull(t.created_at)}</span></DetailField>
                {t.claimed_at && <DetailField label="Claimed"><span className="text-xs text-fg-secondary">{fmtRel(t.claimed_at)}</span></DetailField>}
                {t.completed_at && <DetailField label="Completed"><span className="text-xs text-fg-secondary">{fmtRel(t.completed_at)}</span></DetailField>}
              </div>
            </HubCard>

            {/* Links */}
            {(t.linked_pr || (t.linked_apis || []).length > 0) && (
              <HubCard>
                <HubCardHeader title="Links" />
                <div className="p-3 space-y-2">
                  {linkedPR && (
                    <button onClick={() => nav(`/projects/${encodeURIComponent(projectId)}/codehub/pr/${encodeURIComponent(linkedPR.id)}`)}
                            className="w-full text-left px-3 py-2 border border-border rounded-md bg-bg-elevated hover:border-border-strong transition-all flex items-center gap-2">
                      {Icons.code && <span className="text-fg-muted"><Icons.code size={12} /></span>}
                      <span className="text-xs text-fg truncate flex-1">{linkedPR.title || t.linked_pr}</span>
                    </button>
                  )}
                  {t.linked_pr && !linkedPR && (
                    <div className="px-3 py-2 border border-border rounded-md bg-bg-elevated text-xs text-fg-secondary font-mono">{t.linked_pr}</div>
                  )}
                  {(t.linked_apis || []).map(api => (
                    <button key={api} onClick={() => nav(`/projects/${encodeURIComponent(projectId)}/registryhub`)}
                            className="w-full text-left px-3 py-1.5 border border-border rounded-md bg-bg-elevated hover:border-border-strong transition-all">
                      <code className="text-2xs font-mono text-accent">{api}</code>
                    </button>
                  ))}
                </div>
              </HubCard>
            )}
          </div>
        </div>
      </HubLayout>
    );
  }

  function DetailField({ label, children }) {
    return (
      <div className="flex items-start gap-2">
        <span className="text-2xs uppercase tracking-wider font-medium text-fg-muted w-20 shrink-0 pt-1">{label}</span>
        <div className="flex-1 min-w-0">{children}</div>
      </div>
    );
  }

  // ============================================================================
  // PageDetailView — drill-down view for a single WorkHub page (workhub/page/<id>).
  //
  // Centerpiece is the Decisions stream: each `metadata.decisions[]` entry is a
  // {section, agent, content, recorded_at, ...} row that an attendee (or the
  // orchestrator-driven phase machine) appended via workhub_add_meeting_decision.
  // Sections are color-coded per role (design/backend/frontend/verifier/
  // acceptance_predicates/phase_transition). Right sidebar carries the round-8a
  // phase state machine as a vertical timeline (open → finalizing → finalized
  // | partial_failure | timeout_fallback) so a failed kickoff is visible at a
  // glance rather than buried in logs. See pipeline_supervision_charter.md §5
  // for the phase semantics this view renders.
  // ============================================================================
  function PageDetailView({ projectId, hub, state, pageId }) {
    const Icons = window.Icons || {};
    const pages = hub?.pages || {};
    const page = pages[pageId];
    const nav = (p) => window.LiveMonitorRouter.navigateTo(p);
    const back = () => nav(`/projects/${encodeURIComponent(projectId)}/workhub`);

    const [filterAgent, setFilterAgent] = useState("");
    const [expandedDecisions, setExpandedDecisions] = useState({});

    if (!page) {
      return (
        <HubLayout>
          <button onClick={back} className="flex items-center gap-1.5 text-sm text-fg-secondary hover:text-accent mb-4">
            {Icons.chevronLeft && <Icons.chevronLeft size={14} />} Back to WorkHub
          </button>
          <EmptyState icon={Icons.file} title="Page not found" sub={`No page ${pageId} in this project.`} actionLabel="Back to WorkHub" onAction={back} />
        </HubLayout>
      );
    }

    const meta = page.metadata || {};
    const rawDecisions = Array.isArray(meta.decisions) ? meta.decisions : [];
    const decisions = rawDecisions.slice().sort(
      (a, b) => (a.recorded_at || 0) - (b.recorded_at || 0)
    );
    const attendees = page.attendees || meta.attendees || [];
    const milestoneIndex = meta.milestone_index !== undefined ? meta.milestone_index : page.milestone_index;
    const phase = meta.phase || page.phase;
    const producedArtifacts = meta.produced_artifacts || [];

    // Per-agent decision count, excluding phase_transition (those are
    // orchestrator-driver bookkeeping, not attendee contributions).
    const contributionByAgent = {};
    for (const d of decisions) {
      const sec = decisionSection(d);
      if (sec === "phase_transition") continue;
      const ag = decisionAgent(d);
      if (!ag) continue;
      contributionByAgent[ag] = (contributionByAgent[ag] || 0) + 1;
    }

    // Phase-transition decisions become the right-sidebar timeline.
    const phaseTimeline = decisions.filter(d => decisionSection(d) === "phase_transition");

    // Tasks that explicitly back-reference this meeting (forward-compatible —
    // if finalize_kickoff starts stamping metadata.kickoff_meeting_id on tasks,
    // this fills in automatically).
    const allTasks = Object.values(hub?.tasks || {});
    const attachedTasks = allTasks.filter(t => {
      const tm = t.metadata || {};
      return tm.kickoff_meeting_id === pageId || tm.meeting_id === pageId;
    });

    // Events referencing this page (kickoff_request / kickoff_complete /
    // kickoff_failed / meeting_decision_added).
    const allEvents = Object.values(state?.hubs?.eventhub?.events || {});
    const pageEvents = allEvents
      .filter(e => {
        const pl = e.payload || {};
        return pl.meeting_id === pageId || pl.page_id === pageId;
      })
      .sort((a, b) => (b.created_at || 0) - (a.created_at || 0));

    // Comments threaded on this page.
    const allComments = Object.values(hub?.comments || {});
    const pageComments = allComments
      .filter(c => c.resource_id === pageId && !c.parent_id)
      .sort((a, b) => (a.created_at || 0) - (b.created_at || 0));

    const filteredDecisions = filterAgent
      ? decisions.filter(d => decisionAgent(d) === filterAgent)
      : decisions;

    return (
      <HubLayout>
        <button onClick={back} className="flex items-center gap-1.5 text-sm text-fg-secondary hover:text-accent mb-4 transition-colors">
          {Icons.chevronLeft && <Icons.chevronLeft size={14} />} <span>WorkHub</span>
        </button>

        <div className="grid grid-cols-[1fr_300px] gap-4 items-start">
          {/* ===== Main column ===== */}
          <div className="space-y-4">
            {/* Title header */}
            <HubCard>
              <div className="p-4">
                <div className="flex items-center gap-2 mb-2 text-2xs text-fg-muted">
                  {Icons.file && <Icons.file size={14} />}
                  <span className="uppercase tracking-wider font-medium">{page.kind || "general"}</span>
                  {milestoneIndex !== undefined && (
                    <><span className="text-fg-muted/40">·</span><span>M{milestoneIndex}</span></>
                  )}
                  <span className="text-fg-muted/40">·</span>
                  <code className="font-mono">{shortKey(page.id)}</code>
                </div>
                <h1 className="text-2xl font-semibold tracking-tight text-fg" style={{ fontFamily: "var(--font-serif)" }}>
                  {page.title || page.id}
                </h1>
              </div>
            </HubCard>

            {/* Attendees */}
            {attendees.length > 0 && (
              <HubCard>
                <HubCardHeader title="Attendees" subtitle={`${attendees.length}`} />
                <ul className="p-3 grid grid-cols-2 gap-2">
                  {attendees.map(a => {
                    const cnt = contributionByAgent[a] || 0;
                    const has = cnt > 0;
                    const active = filterAgent === a;
                    return (
                      <li key={a}>
                        <button
                          type="button"
                          onClick={() => setFilterAgent(active ? "" : a)}
                          className={"w-full text-left px-3 py-2 border rounded-md transition-all flex items-center gap-2 text-xs " +
                            (active
                              ? "border-accent bg-accent-soft"
                              : "border-border bg-bg-elevated hover:border-border-strong")}>
                          <span className={has ? "text-success" : "text-fg-muted"}>{has ? "●" : "○"}</span>
                          <ActorChip name={a} />
                          <span className={"ml-auto text-2xs " + (has ? "text-fg-secondary" : "text-fg-muted")}>
                            {has ? `${cnt} decision${cnt === 1 ? "" : "s"}` : "no decision yet"}
                          </span>
                        </button>
                      </li>
                    );
                  })}
                </ul>
              </HubCard>
            )}

            {/* Decisions stream — the centerpiece */}
            <HubCard>
              <HubCardHeader
                title="Decisions"
                subtitle={filterAgent
                  ? `${filteredDecisions.length}/${decisions.length} · filter: ${filterAgent}`
                  : `${decisions.length}`}
                actions={filterAgent ? (
                  <button onClick={() => setFilterAgent("")} className="text-2xs text-fg-muted hover:text-accent transition-colors">
                    clear filter
                  </button>
                ) : null}
              />
              {decisions.length === 0 ? (
                <EmptyState icon={Icons.file} title="No decisions yet"
                  sub="Attendees record decisions via workhub_add_meeting_decision; they appear here as they arrive." />
              ) : (
                <ul className="p-3 space-y-2">
                  {filteredDecisions.map((d, i) => {
                    const sec = decisionSection(d) || "general";
                    const agent = decisionAgent(d) || "—";
                    const content = decisionContent(d);
                    const kindLabel = d.kind || d.decision?.kind;
                    const palette = sectionPalette(sec);
                    const summary = summarizeDecisionContent(sec, content);
                    const key = `${sec}_${agent}_${d.recorded_at || i}`;
                    const expanded = !!expandedDecisions[key];
                    return (
                      <li key={key} className="border border-border rounded-md bg-bg-elevated overflow-hidden">
                        <div className="px-3 py-2">
                          <div className="flex items-center gap-2 mb-1.5">
                            <span
                              className="text-2xs uppercase tracking-wider font-medium px-1.5 py-0.5 rounded font-mono"
                              style={{ background: palette.bg, color: palette.fg }}
                              title={sec}>
                              {truncateSection(sec)}
                            </span>
                            <ActorChip name={agent} />
                            {kindLabel && <span className="text-2xs text-fg-muted">{kindLabel}</span>}
                            <span className="text-2xs text-fg-muted ml-auto">{fmtRel(d.recorded_at)}</span>
                          </div>
                          <div className="text-xs text-fg-secondary leading-relaxed font-mono">
                            {summary || <span className="text-fg-muted italic">(no summary)</span>}
                          </div>
                          <button
                            type="button"
                            onClick={() => setExpandedDecisions(prev => ({ ...prev, [key]: !prev[key] }))}
                            className="mt-1.5 text-2xs text-fg-muted hover:text-accent transition-colors">
                            {expanded ? "▼ Hide content" : "▶ Expand content"}
                          </button>
                          {expanded && (
                            <div className="mt-2">
                              <JsonBlock value={content} />
                            </div>
                          )}
                        </div>
                      </li>
                    );
                  })}
                </ul>
              )}
            </HubCard>

            {/* Comments */}
            {pageComments.length > 0 && (
              <HubCard>
                <HubCardHeader title="Comments" subtitle={`${pageComments.length}`} />
                <ul className="p-3 space-y-3">
                  {pageComments.map(c => (
                    <li key={c.id} className="border border-border rounded-md bg-bg-elevated p-3">
                      <div className="flex items-center gap-2 mb-1">
                        <ActorChip name={c.agent} />
                        <span className="text-2xs text-fg-muted ml-auto">{fmtRel(c.created_at)}</span>
                      </div>
                      <div className="text-sm text-fg-secondary whitespace-pre-wrap">{c.body}</div>
                    </li>
                  ))}
                </ul>
              </HubCard>
            )}

            {/* Activity — events referencing this page */}
            {pageEvents.length > 0 && (
              <HubCard>
                <HubCardHeader title="Activity" subtitle={`${pageEvents.length} events`} />
                <ul className="p-3 space-y-2">
                  {pageEvents.slice(0, 20).map((e, i) => (
                    <li key={e.id || i} className="px-3 py-2 border border-border rounded-md bg-bg-elevated flex items-center gap-2 text-xs">
                      <span className="font-mono font-medium text-fg">{e.event_type}</span>
                      <span className="text-fg-muted">from {e.source_hub || "—"}</span>
                      <span className="text-2xs text-fg-muted ml-auto">{fmtRel(e.created_at)}</span>
                    </li>
                  ))}
                </ul>
              </HubCard>
            )}
          </div>

          {/* ===== Right sidebar ===== */}
          <div className="space-y-4">
            {/* Properties */}
            <HubCard>
              <HubCardHeader title="Properties" />
              <dl className="p-3 space-y-2 text-xs">
                <PageDetailRow label="Kind" value={page.kind || "general"} mono />
                <PageDetailRow label="Status" value={<StatusBadge status={page.status} />} />
                {milestoneIndex !== undefined && (
                  <PageDetailRow label="Milestone" value={`M${milestoneIndex}`} mono />
                )}
                {phase && <PageDetailRow label="Phase" value={<PhaseChip phase={phase} />} />}
                {page.agent && <PageDetailRow label="Author" value={<ActorChip name={page.agent} />} />}
                {page.created_at && <PageDetailRow label="Created" value={fmtRel(page.created_at)} />}
                {page.closed_at && <PageDetailRow label="Closed" value={fmtRel(page.closed_at)} />}
              </dl>
            </HubCard>

            {/* Phase timeline (round-8a state machine made visual) */}
            {phaseTimeline.length > 0 && (
              <HubCard>
                <HubCardHeader title="Phase timeline" subtitle={`${phaseTimeline.length}`} />
                <ol className="p-3 space-y-2">
                  {phaseTimeline.map((d, i) => {
                    const c = decisionContent(d) || {};
                    const newPhase = c.phase || c.to || c.new_phase || "—";
                    const fromPhase = c.from || c.old_phase || c.previous;
                    return (
                      <li key={i} className="flex items-center gap-2 text-xs">
                        <PhaseChip phase={newPhase} dot />
                        <span className="text-fg-secondary font-mono">
                          {fromPhase ? `${fromPhase} → ${newPhase}` : newPhase}
                        </span>
                        <span className="ml-auto text-2xs text-fg-muted shrink-0">{fmtRel(d.recorded_at)}</span>
                      </li>
                    );
                  })}
                </ol>
              </HubCard>
            )}

            {/* Attached tasks (forward-compatible — empty until tasks carry meeting_id) */}
            {attachedTasks.length > 0 && (
              <HubCard>
                <HubCardHeader title="Attached tasks" subtitle={`${attachedTasks.length}`} />
                <ul className="p-3 space-y-1.5">
                  {attachedTasks.map(t => (
                    <li key={t.id}>
                      <button onClick={() => nav(`/projects/${encodeURIComponent(projectId)}/workhub/task/${encodeURIComponent(t.id)}`)}
                              className="w-full text-left px-2.5 py-1.5 border border-border rounded bg-bg-elevated hover:border-border-strong transition-all flex items-center gap-2 text-xs group">
                        <span className="text-fg-muted shrink-0">▢</span>
                        <span className="text-fg truncate group-hover:text-accent transition-colors">{t.title || t.id}</span>
                      </button>
                    </li>
                  ))}
                </ul>
              </HubCard>
            )}

            {/* Produced artifacts (set on close_meeting) */}
            {producedArtifacts.length > 0 && (
              <HubCard>
                <HubCardHeader title="Produced artifacts" subtitle={`${producedArtifacts.length}`} />
                <ul className="p-3 space-y-1">
                  {producedArtifacts.map((a, i) => (
                    <li key={i} className="flex items-center gap-2 text-xs">
                      <span className="text-success">✓</span>
                      <span className="font-mono text-fg-secondary">{a}</span>
                    </li>
                  ))}
                </ul>
              </HubCard>
            )}
          </div>
        </div>
      </HubLayout>
    );
  }

  // ---- PageDetailView helpers ----

  function PageDetailRow({ label, value, mono }) {
    return (
      <div className="flex items-center gap-2">
        <dt className="text-2xs uppercase tracking-wider text-fg-muted w-20 shrink-0">{label}</dt>
        <dd className={"text-fg flex-1 min-w-0 truncate " + (mono ? "font-mono" : "")}>{value}</dd>
      </div>
    );
  }

  // Color-coded chip for the round-8a state-machine phases. `dot=true` returns
  // a 2x2 indicator for the right-sidebar timeline; otherwise renders a chip
  // label suitable for the Properties card.
  function PhaseChip({ phase, dot }) {
    const PALETTE = {
      open:              { bg: "var(--bg-tertiary)",  fg: "var(--text-muted)" },
      synthesizing:      { bg: "var(--info-soft)",    fg: "var(--info)" },
      finalizing:        { bg: "var(--warning-soft)", fg: "var(--warning)" },
      finalized:         { bg: "var(--success-soft)", fg: "var(--success)" },
      partial_failure:   { bg: "var(--danger-soft)",  fg: "var(--danger)" },
      timeout_fallback:  { bg: "var(--danger-soft)",  fg: "var(--danger)" },
    };
    const p = PALETTE[phase] || { bg: "var(--bg-tertiary)", fg: "var(--text-muted)" };
    if (dot) {
      return <span className="inline-block w-2 h-2 rounded-full shrink-0" style={{ background: p.fg }} />;
    }
    return (
      <span className="text-2xs uppercase tracking-wider font-medium px-1.5 py-0.5 rounded font-mono"
            style={{ background: p.bg, color: p.fg }}>
        {phase}
      </span>
    );
  }

  // Section-to-color mapping. Uses the palette tokens defined in
  // design-tokens.css so the chips ride the same theme as everything else.
  function sectionPalette(section) {
    const MAP = {
      design:                { bg: "rgba(139, 92, 246, 0.14)", fg: "var(--palette-violet)" },
      backend:               { bg: "rgba(6, 182, 212, 0.14)",  fg: "var(--palette-cyan)" },
      frontend:              { bg: "rgba(245, 158, 11, 0.14)", fg: "var(--palette-amber)" },
      verifier:              { bg: "rgba(236, 72, 153, 0.14)", fg: "var(--palette-pink)" },
      acceptance_predicates: { bg: "var(--accent-soft)",       fg: "var(--accent-on-soft)" },
      phase_transition:      { bg: "var(--bg-tertiary)",       fg: "var(--text-secondary)" },
    };
    return MAP[section] || { bg: "var(--bg-tertiary)", fg: "var(--text-muted)" };
  }

  function truncateSection(s) {
    if (!s) return "—";
    if (s.length <= 14) return s;
    return s.slice(0, 13) + "…";
  }

  // The decision record shape from workhub.add_meeting_decision is either flat
  // ({section, agent, content, recorded_at, recorded_by, kind?}) OR nested
  // ({decision: {section, content, ...}, recorded_at, recorded_by}). Handle
  // both via accessors so the UI doesn't care which the backend produced.
  function decisionSection(d) {
    if (!d) return null;
    return d.section || (d.decision && d.decision.section) || null;
  }
  function decisionAgent(d) {
    if (!d) return null;
    return d.agent || d.recorded_by || (d.decision && d.decision.agent) || null;
  }
  function decisionContent(d) {
    if (!d) return null;
    if (d.content !== undefined) return d.content;
    if (d.decision && d.decision.content !== undefined) return d.decision.content;
    return d.decision || null;
  }

  // Section-aware one-line summary. Mirrors what the cross_check_suite
  // extractors look at, so what you see in the decision card is the same data
  // shape the synthesizer reads. Never throws — every section returns "—" on
  // shape mismatch so a malformed decision still renders cleanly.
  function summarizeDecisionContent(section, content) {
    if (content == null) return "—";
    if (typeof content !== "object") return String(content).slice(0, 80);
    try {
      if (section === "design") {
        const flows = content.user_flows || content.flows || [];
        const critical = Array.isArray(flows) ? flows.filter(f => f && f.critical).length : 0;
        const pages = content.ui_pages || content.pages || [];
        const auth = content.auth ? (content.auth.method || JSON.stringify(content.auth).slice(0, 40)) : null;
        const parts = [];
        if (Array.isArray(flows) && flows.length) parts.push(`user_flows: ${flows.length}${critical ? ` (${critical} critical)` : ""}`);
        if (Array.isArray(pages) && pages.length) parts.push(`ui_pages: ${pages.length}`);
        if (auth) parts.push(`auth: ${auth}`);
        return parts.join(" · ") || "—";
      }
      if (section === "backend") {
        const endpoints = content.api_endpoints || content.endpoints || [];
        const dm = content.data_model || {};
        const tables = dm.tables || content.tables || [];
        const parts = [];
        if (Array.isArray(endpoints) && endpoints.length) parts.push(`api_endpoints: ${endpoints.length}`);
        if (Array.isArray(tables) && tables.length) parts.push(`data_model: ${tables.length} table${tables.length === 1 ? "" : "s"}`);
        return parts.join(" · ") || "—";
      }
      if (section === "frontend") {
        const screens = content.screens || [];
        const pages = content.ui_pages || [];
        const parts = [];
        if (Array.isArray(screens) && screens.length) parts.push(`screens: ${screens.length}`);
        if (Array.isArray(pages) && pages.length) parts.push(`ui_pages: ${pages.length}`);
        return parts.join(" · ") || "—";
      }
      if (section === "verifier" || section === "acceptance_predicates") {
        const preds = content.predicates || [];
        if (!Array.isArray(preds)) return "—";
        const apiPreds = preds.filter(p => (p && p.kind === "api_smoke") || (p && p.type === "api_smoke")).length;
        const uiPreds = preds.filter(p => (p && p.kind === "ui_flow") || (p && p.type === "ui_flow")).length;
        const extras = [];
        if (apiPreds) extras.push(`${apiPreds} api_smoke`);
        if (uiPreds) extras.push(`${uiPreds} ui_flow`);
        const suffix = extras.length ? ` (${extras.join(", ")})` : "";
        return `predicates: ${preds.length}${suffix}`;
      }
      if (section === "phase_transition") {
        const from_ = content.from || content.old_phase || content.previous;
        const to_ = content.phase || content.to || content.new_phase;
        if (from_ && to_) return `${from_} → ${to_}`;
        if (to_) return `→ ${to_}`;
        return "—";
      }
      // Generic fallback — first two scalar/length-summary fields.
      const keys = Object.keys(content).slice(0, 3);
      return keys.map(k => {
        const v = content[k];
        let vs;
        if (Array.isArray(v)) vs = `[${v.length}]`;
        else if (v && typeof v === "object") vs = `{${Object.keys(v).length}}`;
        else vs = String(v).slice(0, 24);
        return `${k}: ${vs}`;
      }).join(" · ");
    } catch (e) {
      return "—";
    }
  }

  // ------------------------- EventHub -------------------------
  // ===========================================================================
  // Cutover 43.24: EventHub — hybrid activity feed + agent conversations.
  // Stream (filterable event timeline) · Conversations (chat transcripts) ·
  // Inboxes (per-agent read/unread) · Subscriptions.
  // ===========================================================================
  function eventPriorityVisual(p) {
    return {
      low:        { label: "low",     color: "var(--text-muted)", dot: "var(--text-muted)" },
      normal:     { label: "normal",  color: "var(--info)",       dot: "var(--info)" },
      high:       { label: "high",    color: "var(--warning)",    dot: "var(--warning)" },
      critical:   { label: "critical",color: "var(--danger)",     dot: "var(--danger)" },
      human_user: { label: "human",   color: "var(--accent-on-soft)", dot: "var(--accent)" },
    }[p] || { label: p || "normal", color: "var(--info)", dot: "var(--info)" };
  }
  function hubIconFor(src) {
    const Icons = window.Icons || {};
    return { codehub: Icons.code, registryhub: Icons.api, workhub: Icons.workhub, runhub: Icons.play, eventhub: Icons.inbox, system: Icons.settings, human_user: Icons.user }[src] || Icons.inbox;
  }
  // Build a human-readable summary + cross-hub link target from an event payload
  function eventSummary(e) {
    const p = e.payload || {};
    const t = e.event_type || "";
    if (t === "human_message") return { text: p.text || "(message)", chat: true, from: p.from_user || "human" };
    if (t === "agent_reply" || t === "thread_reply") return { text: p.text || p.body || "(reply)", chat: true, from: p.reply_from || p.from || "agent" };
    if (t === "agent_status") return { text: `${p.agent_id || "agent"} — ${p.status || p.action || "status update"}` };
    if (t.startsWith("task_")) return { text: p.title || p.id || "", ref: p.id ? { hub: "workhub", kind: "task", id: p.id } : null };
    if (t.startsWith("pr_") || t.startsWith("pull_request")) return { text: p.title || p.id || "", ref: p.id ? { hub: "codehub", kind: "pr", id: p.id } : { hub: "codehub" } };
    if (t.startsWith("review")) return { text: p.id || ("review on " + (p.pr_id || "PR")), ref: p.pr_id ? { hub: "codehub", kind: "pr", id: p.pr_id } : { hub: "codehub" } };
    if (t.startsWith("check") || t === "merge" || t.startsWith("merge")) return { text: p.name || p.id || "", ref: p.pr_id ? { hub: "codehub", kind: "pr", id: p.pr_id } : { hub: "codehub" } };
    if (t === "endpoint_registered" || t.startsWith("endpoint") || t.startsWith("breaking") || t.startsWith("mcp") || t.startsWith("table")) return { text: (p.method ? `${p.method} ${p.path}` : p.endpoint_id || p.name || p.id || ""), ref: { hub: "registryhub" } };
    // fallback: first stringy payload field
    const k = ["text", "message", "title", "name", "id"].find(k => typeof p[k] === "string");
    return { text: k ? p[k] : "" };
  }
  // Curated key→value fields for an event payload, rendered as the "email body".
  function eventFields(payload) {
    const p = payload || {};
    const DENY = new Set(["_updated_by", "_updated_at", "claim_token", "schema", "payload", "text", "body", "from_user", "reply_from"]);
    const out = [];
    for (const [k, v] of Object.entries(p)) {
      if (DENY.has(k) || k.startsWith("_")) continue;
      if (v == null || v === "") continue;
      if (typeof v === "object" && !Array.isArray(v)) {
        // flatten one level of small objects (e.g. metadata)
        if (k === "metadata") { for (const [mk, mv] of Object.entries(v)) { if (mv != null && typeof mv !== "object") out.push([mk, String(mv)]); } continue; }
        continue;
      }
      if (Array.isArray(v)) { if (v.length === 0) continue; out.push([k, v.join(", ")]); continue; }
      out.push([k, String(v)]);
    }
    return out.slice(0, 14);
  }

  function EventHubPage({ projectId, hub, state }) {
    const Icons = window.Icons || {};
    const events = Object.values(hub?.events || {}).sort((a, b) => (b.created_at || 0) - (a.created_at || 0));
    const threadsRaw = hub?.threads || {};
    const threads = Object.values(threadsRaw);
    const inboxes = Object.values(hub?.inboxes || {});
    const subs = Object.values(hub?.subscriptions || {});
    const eventsById = useMemo(() => Object.fromEntries(events.map(e => [e.id, e])), [events]);
    const nav = (p) => window.LiveMonitorRouter.navigateTo(p);

    const [tab, setTab] = useState("stream");
    const [srcFilter, setSrcFilter] = useState("");
    const [priFilter, setPriFilter] = useState("");
    const [expanded, setExpanded] = useState({});
    const [activeThread, setActiveThread] = useState(null);
    const [mailAgent, setMailAgent] = useState(null);  // selected mailbox
    const [mailMsg, setMailMsg] = useState(null);       // selected message event_id
    const [mailUnreadOnly, setMailUnreadOnly] = useState(false);
    const [sentAgent, setSentAgent] = useState(null);   // selected "Sent" sender
    const [sentMsg, setSentMsg] = useState(null);       // selected sent event id

    const sources = useMemo(() => [...new Set(events.map(e => e.source_hub).filter(Boolean))].sort(), [events]);
    // Events grouped by author (source_hub) — the "Sent" view (mirror of inboxes).
    const sentBySource = useMemo(() => {
      const m = {};
      for (const e of events) { const s = e.source_hub; if (!s) continue; (m[s] = m[s] || []).push(e); }
      return m;
    }, [events]);

    const filteredEvents = useMemo(() => events.filter(e =>
      (!srcFilter || e.source_hub === srcFilter) && (!priFilter || e.priority === priFilter)), [events, srcFilter, priFilter]);

    // Conversations = threads with >1 event OR started by human_user
    const conversations = useMemo(() => {
      return threads.map(th => {
        const evs = (th.event_ids || []).map(id => eventsById[id]).filter(Boolean).sort((a, b) => (a.created_at || 0) - (b.created_at || 0));
        const last = evs[evs.length - 1];
        return { ...th, evs, last };
      }).filter(th => th.evs.length > 1 || th.evs.some(e => e.source_hub === "human_user" || e.event_type === "human_message" || e.event_type === "agent_reply"))
        .sort((a, b) => (b.last?.created_at || 0) - (a.last?.created_at || 0));
    }, [threads, eventsById]);

    const totalUnread = inboxes.reduce((n, ib) => n + Object.values(ib.items || {}).filter(it => !it.read).length, 0);

    useEffect(() => {
      if (tab === "conversations" && !activeThread && conversations.length) setActiveThread(conversations[0].id);
    }, [tab, conversations, activeThread]);
    useEffect(() => {
      if (tab !== "inboxes" || mailAgent) return;
      // default to the mailbox with the most unread, else the first
      const ranked = [...inboxes].sort((a, b) =>
        Object.values(b.items || {}).filter(i => !i.read).length - Object.values(a.items || {}).filter(i => !i.read).length);
      if (ranked[0]) setMailAgent(ranked[0].agent);
    }, [tab, inboxes, mailAgent]);
    useEffect(() => {
      if (tab !== "sent" || sentAgent) return;
      // default to the most prolific sender
      const ranked = Object.entries(sentBySource).sort((a, b) => b[1].length - a[1].length);
      if (ranked[0]) setSentAgent(ranked[0][0]);
    }, [tab, sentBySource, sentAgent]);

    function EventRow({ e, showThreadLink }) {
      const pv = eventPriorityVisual(e.priority);
      const HubI = hubIconFor(e.source_hub);
      const sum = eventSummary(e);
      const isExp = !!expanded[e.id];
      return (
        <li className="border border-border rounded-md bg-bg-elevated overflow-hidden">
          <div className="px-3 py-2 flex items-start gap-2.5">
            <span className="w-1.5 h-1.5 rounded-full mt-1.5 shrink-0" style={{ background: pv.dot }} title={pv.label + " priority"} />
            <span className="text-fg-muted shrink-0 mt-0.5">{HubI ? <HubI size={13} /> : null}</span>
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2 flex-wrap">
                <code className="text-xs font-mono font-medium text-fg">{e.event_type}</code>
                <span className="text-2xs text-fg-muted">{e.source_hub}</span>
                {e.priority && e.priority !== "normal" && (
                  <span className="text-2xs px-1.5 py-0.5 rounded font-medium" style={{ color: pv.color, background: "color-mix(in srgb, " + pv.dot + " 14%, transparent)" }}>{pv.label}</span>
                )}
                <span className="text-2xs text-fg-muted ml-auto">{fmtRel(e.created_at)}</span>
              </div>
              {sum.text && <div className="text-sm text-fg-secondary mt-0.5 truncate">{sum.text}</div>}
              <div className="flex items-center gap-2 mt-1 flex-wrap">
                {(e.recipients || []).length > 0 && (
                  <span className="text-2xs text-fg-muted">→ {(e.recipients || []).join(", ")}</span>
                )}
                {sum.ref && (
                  <button onClick={() => nav(sum.ref.kind === "pr" ? `/projects/${encodeURIComponent(projectId)}/codehub/pr/${encodeURIComponent(sum.ref.id)}`
                                       : sum.ref.kind === "task" ? `/projects/${encodeURIComponent(projectId)}/workhub/task/${encodeURIComponent(sum.ref.id)}`
                                       : `/projects/${encodeURIComponent(projectId)}/${sum.ref.hub}`)}
                          className="text-2xs text-accent hover:underline">view in {sum.ref.hub} →</button>
                )}
                {showThreadLink && e.thread_id && (
                  <button onClick={() => { setTab("conversations"); setActiveThread(e.thread_id); }}
                          className="text-2xs text-fg-muted hover:text-accent">thread</button>
                )}
                <button onClick={() => setExpanded(x => ({ ...x, [e.id]: !x[e.id] }))}
                        className="text-2xs text-fg-muted hover:text-fg-secondary ml-auto">{isExp ? "hide payload" : "payload"}</button>
              </div>
              {isExp && <div className="mt-1.5"><JsonBlock value={e.payload} empty="(empty payload)" /></div>}
            </div>
          </div>
        </li>
      );
    }

    return (
      <HubLayout>
        {/* Metrics */}
        <div className="grid grid-cols-4 gap-3 mb-5">
          <MetricTile label="Events" value={events.length} sub="all-time" icon={Icons.inbox} tone="info" />
          <MetricTile label="Conversations" value={conversations.length} sub={`${threads.length} threads`} icon={Icons.chat} />
          <MetricTile label="Unread" value={totalUnread} sub={`${inboxes.length} inboxes`} icon={Icons.inbox} tone={totalUnread ? "warning" : "neutral"} />
          <MetricTile label="Subscriptions" value={subs.length} sub="fan-out rules" icon={Icons.shield} />
        </div>

        {/* Tabs */}
        <div className="flex items-center gap-3 border-b border-border mb-5">
          <div className="flex gap-1">
            {[{k:"stream",l:"Stream"},{k:"conversations",l:"Conversations"},{k:"inboxes",l:"Inboxes"},{k:"sent",l:"Sent"},{k:"subscriptions",l:"Subscriptions"}].map(t => (
              <button key={t.k} onClick={() => setTab(t.k)}
                      className={"px-3 h-9 text-base font-medium flex items-center gap-2 border-b-2 -mb-px transition-colors " +
                                 (tab === t.k ? "text-fg border-accent" : "text-fg-secondary border-transparent hover:text-fg")}>
                {t.l}
                {t.k === "conversations" && conversations.length > 0 && <span className="text-2xs tabular-nums px-1.5 rounded-full bg-bg-tertiary text-fg-muted">{conversations.length}</span>}
              </button>
            ))}
          </div>
          {tab === "stream" && (
            <div className="ml-auto flex items-center gap-2 pb-1.5">
              <UiSelect value={srcFilter} onChange={setSrcFilter} placeholder="All sources" size="md"
                        options={[{ value: "", label: "All sources" }, ...sources.map(s => ({ value: s, label: s }))]} />
              <UiSelect value={priFilter} onChange={setPriFilter} placeholder="Any priority" size="md"
                        options={[{ value: "", label: "Any priority" }, ...["low","normal","high","critical","human_user"].map(p => ({ value: p, label: p }))]} />
            </div>
          )}
        </div>

        {/* ===== Stream ===== */}
        {tab === "stream" && (
          <HubCard>
            <HubCardHeader title="Event stream" subtitle={`${filteredEvents.length} of ${events.length}`} />
            {filteredEvents.length === 0 ? (
              <EmptyState icon={Icons.inbox} title="No events" sub="Hub events (task/PR/endpoint changes, messages) stream here." />
            ) : (
              <ul className="p-3 space-y-2">
                {filteredEvents.slice(0, 100).map(e => <EventRow key={e.id} e={e} showThreadLink />)}
                {filteredEvents.length > 100 && <li className="text-center text-sm text-fg-muted py-2">Showing 100 of {filteredEvents.length}.</li>}
              </ul>
            )}
          </HubCard>
        )}

        {/* ===== Conversations (chat) ===== */}
        {tab === "conversations" && (
          conversations.length === 0 ? (
            <HubCard><EmptyState icon={Icons.chat} title="No conversations"
              sub="Multi-message threads (human↔agent, agent↔agent) appear here as chat transcripts." /></HubCard>
          ) : (
            <div className="grid grid-cols-[300px_1fr] gap-4 items-start">
              {/* thread list */}
              <HubCard className="self-start">
                <div className="px-3 h-9 flex items-center border-b border-border text-2xs uppercase tracking-wider font-medium text-fg-muted">Threads</div>
                <ul className="py-1 max-h-[68vh] overflow-y-auto">
                  {conversations.map(c => {
                    const isSel = activeThread === c.id;
                    const lastSum = c.last ? eventSummary(c.last) : {};
                    return (
                      <li key={c.id}>
                        <button onClick={() => setActiveThread(c.id)}
                                className={"w-full text-left px-3 py-2 transition-colors " + (isSel ? "bg-accent-soft" : "hover:bg-bg-hover")}>
                          <div className="flex items-center gap-2">
                            <span className="text-sm font-medium text-fg truncate flex-1">{(c.participants || []).join(", ") || "thread"}</span>
                            <span className="text-2xs text-fg-muted">{c.evs.length}</span>
                          </div>
                          {lastSum.text && <div className="text-2xs text-fg-muted truncate mt-0.5">{lastSum.text}</div>}
                        </button>
                      </li>
                    );
                  })}
                </ul>
              </HubCard>
              {/* transcript */}
              <HubCard className="self-start">
                {(() => {
                  const conv = conversations.find(c => c.id === activeThread) || conversations[0];
                  if (!conv) return null;
                  return (
                    <>
                      <header className="px-4 h-11 border-b border-border flex items-center gap-2">
                        <span className="text-md font-semibold text-fg">{(conv.participants || []).join(", ") || "Conversation"}</span>
                        <span className="text-2xs text-fg-muted ml-auto">{conv.evs.length} messages</span>
                      </header>
                      <div className="p-4 space-y-3 max-h-[64vh] overflow-y-auto">
                        {conv.evs.map(ev => {
                          const sum = eventSummary(ev);
                          const isHuman = ev.source_hub === "human_user" || ev.event_type === "human_message";
                          const who = sum.from || ev.source_hub || "system";
                          return (
                            <div key={ev.id} className={"flex flex-col " + (isHuman ? "items-end" : "items-start")}>
                              <div className="flex items-center gap-1.5 mb-0.5">
                                <span className="text-2xs font-medium text-fg-secondary">{who}</span>
                                <span className="text-2xs text-fg-muted">{fmtRel(ev.created_at)}</span>
                              </div>
                              <div className={"max-w-[78%] px-3 py-2 rounded-lg text-sm whitespace-pre-wrap " +
                                              (isHuman ? "bg-accent-soft text-accent-on-soft rounded-br-sm" : "bg-bg-tertiary text-fg-secondary rounded-bl-sm")}>
                                {sum.chat ? sum.text : (
                                  <span className="text-xs"><code className="font-mono text-fg-muted">{ev.event_type}</code>{sum.text ? " · " + sum.text : ""}</span>
                                )}
                              </div>
                            </div>
                          );
                        })}
                      </div>
                    </>
                  );
                })()}
              </HubCard>
            </div>
          )
        )}

        {/* ===== Inboxes — email-client layout (mailboxes | message list | reading pane) ===== */}
        {tab === "inboxes" && (
          inboxes.length === 0 ? (
            <HubCard><EmptyState icon={Icons.inbox} title="No inboxes" sub="Per-agent inboxes collect delivered events." /></HubCard>
          ) : (() => {
            const curIb = inboxes.find(ib => ib.agent === mailAgent) || inboxes[0];
            const msgs = curIb ? Object.values(curIb.items || {}).sort((a, b) => (b.received_at || 0) - (a.received_at || 0)) : [];
            const openMsg = msgs.find(m => m.event_id === mailMsg) || null;
            const openEv = openMsg ? eventsById[openMsg.event_id] : null;
            const openSum = openEv ? eventSummary(openEv) : {};
            const openSender = openSum.from || openEv?.source_hub || "system";
            return (
              <div className="grid grid-cols-[200px_340px_1fr] gap-0 border border-border rounded-lg overflow-hidden bg-bg-elevated" style={{ minHeight: "70vh" }}>
                {/* Pane 1: mailboxes */}
                <div className="border-r border-border bg-bg-secondary/40">
                  <div className="px-3 h-10 flex items-center text-2xs uppercase tracking-wider font-semibold text-fg-muted border-b border-border">Mailboxes</div>
                  <ul className="py-1">
                    {inboxes.map(ib => {
                      const its = Object.values(ib.items || {});
                      const u = its.filter(i => !i.read).length;
                      const sel = curIb && ib.agent === curIb.agent;
                      return (
                        <li key={ib.agent}>
                          <button onClick={() => { setMailAgent(ib.agent); setMailMsg(null); }}
                                  className={"w-full text-left px-3 py-2 flex items-center gap-2 text-sm transition-colors " + (sel ? "bg-accent-soft text-accent-on-soft font-medium" : "text-fg-secondary hover:bg-bg-hover")}>
                            {Icons.inbox && <span className={sel ? "" : "text-fg-muted"}><Icons.inbox size={13} /></span>}
                            <span className="truncate flex-1">{ib.agent}</span>
                            {u > 0 && <span className="text-2xs px-1.5 rounded-full bg-warning-soft text-warning font-semibold tabular-nums">{u}</span>}
                          </button>
                        </li>
                      );
                    })}
                  </ul>
                </div>

                {/* Pane 2: message list */}
                <div className="border-r border-border flex flex-col">
                  <div className="px-3 h-10 flex items-center gap-2 border-b border-border">
                    <span className="text-sm font-semibold text-fg">{curIb?.agent}</span>
                    <span className="text-2xs text-fg-muted">{msgs.filter(m => !mailUnreadOnly || !m.read).length} {mailUnreadOnly ? "unread" : "messages"}</span>
                    <button onClick={() => setMailUnreadOnly(v => !v)}
                            className={"ml-auto text-2xs px-2 py-0.5 rounded-full transition-colors " + (mailUnreadOnly ? "bg-accent-soft text-accent-on-soft font-medium" : "text-fg-muted hover:bg-bg-hover")}>
                      Unread only
                    </button>
                  </div>
                  <ul className="overflow-y-auto divide-y divide-border" style={{ maxHeight: "calc(70vh - 40px)" }}>
                    {msgs.filter(m => !mailUnreadOnly || !m.read).length === 0 ? (
                      <li className="px-4 py-6 text-sm text-fg-muted">{mailUnreadOnly ? "No unread messages." : "Empty mailbox."}</li>
                    ) : msgs.filter(m => !mailUnreadOnly || !m.read).map(it => {
                      const ev = eventsById[it.event_id];
                      const sum = ev ? eventSummary(ev) : {};
                      const sender = sum.from || ev?.source_hub || "system";
                      const sel = openMsg && it.event_id === openMsg.event_id;
                      const HubI = hubIconFor(ev?.source_hub);
                      return (
                        <li key={it.event_id}>
                          <button onClick={() => setMailMsg(it.event_id)}
                                  className={"w-full text-left px-3 py-2.5 transition-colors relative " + (sel ? "bg-accent-soft/60" : "hover:bg-bg-hover")}>
                            {!it.read && <span className="absolute left-0 top-0 bottom-0 w-0.5 bg-accent" />}
                            <div className="flex items-center gap-2 mb-0.5">
                              {HubI && <span className="text-fg-muted shrink-0"><HubI size={12} /></span>}
                              <span className={"text-sm truncate flex-1 " + (it.read ? "text-fg-secondary" : "text-fg font-semibold")}>{sender}</span>
                              {it.priority && it.priority !== "normal" && <span className="w-1.5 h-1.5 rounded-full shrink-0" style={{ background: eventPriorityVisual(it.priority).dot }} title={it.priority} />}
                              <span className="text-2xs text-fg-muted shrink-0">{fmtRel(it.received_at)}</span>
                            </div>
                            <div className={"text-xs truncate " + (it.read ? "text-fg-muted" : "text-fg-secondary font-medium")}>{ev?.event_type || it.event_id}</div>
                            {sum.text && <div className="text-2xs text-fg-muted truncate mt-0.5">{sum.text}</div>}
                          </button>
                        </li>
                      );
                    })}
                  </ul>
                </div>

                {/* Pane 3: reading pane */}
                <div className="flex flex-col">
                  {!openEv ? (
                    <div className="flex-1 flex items-center justify-center text-sm text-fg-muted">Select a message to read.</div>
                  ) : (
                    <div className="overflow-y-auto" style={{ maxHeight: "70vh" }}>
                      <div className="px-5 py-4 border-b border-border">
                        <div className="flex items-center gap-2 mb-2">
                          {hubIconFor(openEv.source_hub) && <span className="text-fg-muted">{React.createElement(hubIconFor(openEv.source_hub), { size: 14 })}</span>}
                          <code className="text-sm font-mono font-semibold text-fg">{openEv.event_type}</code>
                          <span className="text-2xs px-1.5 py-0.5 rounded font-medium" style={{ color: eventPriorityVisual(openMsg.priority).color, background: "color-mix(in srgb, " + eventPriorityVisual(openMsg.priority).dot + " 14%, transparent)" }}>{openMsg.priority}</span>
                          <span className="ml-auto text-2xs text-fg-muted" title={openMsg.delivered ? "delivered via message bus" : "queued"}>{openMsg.delivered ? "✓ delivered" : "queued"}</span>
                        </div>
                        <div className="text-xs text-fg-muted flex items-center gap-2 flex-wrap">
                          <span><span className="text-fg-muted">from</span> <span className="text-fg-secondary font-medium">{openSender}</span></span>
                          {(openEv.recipients || []).length > 0 && <><span>·</span><span><span className="text-fg-muted">to</span> {openEv.recipients.join(", ")}</span></>}
                          <span>·</span><span>{fmtFull(openMsg.received_at)}</span>
                          {openMsg.read_at && <><span>·</span><span>read {fmtRel(openMsg.read_at)}</span></>}
                        </div>
                      </div>
                      <div className="px-5 py-4 space-y-4">
                        {/* the message body — for chat, the text; otherwise a subject line */}
                        {openSum.chat ? (
                          <div className="text-sm text-fg leading-relaxed whitespace-pre-wrap">{openSum.text}</div>
                        ) : openSum.text ? (
                          <div className="text-md font-semibold text-fg leading-snug">{openSum.text}</div>
                        ) : null}

                        {/* structured fields (the "email body") */}
                        {(() => {
                          const fields = openSum.chat ? [] : eventFields(openEv.payload);
                          if (fields.length === 0) return null;
                          return (
                            <div className="border border-border rounded-md divide-y divide-border bg-bg-secondary/30">
                              {fields.map(([k, v], i) => (
                                <div key={i} className="px-3 py-1.5 flex items-start gap-3 text-xs">
                                  <span className="text-fg-muted w-32 shrink-0 truncate">{k}</span>
                                  <span className="text-fg-secondary font-mono break-all flex-1">{v}</span>
                                </div>
                              ))}
                            </div>
                          );
                        })()}

                        {/* actions */}
                        <div className="flex items-center gap-2 flex-wrap">
                          {openSum.ref && (
                            <button onClick={() => nav(openSum.ref.kind === "pr" ? `/projects/${encodeURIComponent(projectId)}/codehub/pr/${encodeURIComponent(openSum.ref.id)}`
                                                 : openSum.ref.kind === "task" ? `/projects/${encodeURIComponent(projectId)}/workhub/task/${encodeURIComponent(openSum.ref.id)}`
                                                 : `/projects/${encodeURIComponent(projectId)}/${openSum.ref.hub}`)}
                                    className="btn-px btn-px-primary btn-px-sm">
                              {(() => { const I = hubIconFor(openSum.ref.hub); return I ? <I size={12} /> : null; })()} Open in {openSum.ref.hub}
                            </button>
                          )}
                          {openEv.thread_id && (
                            <button onClick={() => { setTab("conversations"); setActiveThread(openEv.thread_id); }}
                                    className="btn-px btn-px-ghost btn-px-sm">{Icons.chat && <Icons.chat size={12} />} Open thread</button>
                          )}
                        </div>

                        {/* raw payload — collapsible */}
                        <details>
                          <summary className="cursor-pointer text-2xs uppercase tracking-wider font-medium text-fg-muted hover:text-fg-secondary">Raw payload</summary>
                          <div className="mt-1.5"><JsonBlock value={openEv.payload} empty="(no payload)" /></div>
                        </details>
                      </div>
                    </div>
                  )}
                </div>
              </div>
            );
          })()
        )}

        {/* ===== Sent (events grouped by author) ===== */}
        {tab === "sent" && (
          Object.keys(sentBySource).length === 0 ? (
            <HubCard><EmptyState icon={Icons.inbox} title="Nothing sent yet" sub="Outgoing events authored by each hub/agent appear here." /></HubCard>
          ) : (() => {
            const senders = Object.entries(sentBySource).sort((a, b) => b[1].length - a[1].length);
            const cur = sentAgent && sentBySource[sentAgent] ? sentAgent : (senders[0] && senders[0][0]);
            const list = sentBySource[cur] || [];
            const openEv = list.find(e => e.id === sentMsg) || null;
            const openSum = openEv ? eventSummary(openEv) : {};
            return (
              <div className="grid grid-cols-[200px_340px_1fr] gap-0 border border-border rounded-lg overflow-hidden bg-bg-elevated" style={{ minHeight: "70vh" }}>
                {/* Pane 1: senders */}
                <div className="border-r border-border bg-bg-secondary/40">
                  <div className="px-3 h-10 flex items-center text-2xs uppercase tracking-wider font-semibold text-fg-muted border-b border-border">Senders</div>
                  <ul className="py-1">
                    {senders.map(([src, evs]) => {
                      const sel = src === cur;
                      const HubI = hubIconFor(src);
                      return (
                        <li key={src}>
                          <button onClick={() => { setSentAgent(src); setSentMsg(null); }}
                                  className={"w-full text-left px-3 py-2 flex items-center gap-2 text-sm transition-colors " + (sel ? "bg-accent-soft text-accent-on-soft font-medium" : "text-fg-secondary hover:bg-bg-hover")}>
                            {HubI && <span className={sel ? "" : "text-fg-muted"}><HubI size={13} /></span>}
                            <span className="truncate flex-1">{src}</span>
                            <span className="text-2xs px-1.5 rounded-full bg-bg-tertiary text-fg-muted tabular-nums">{evs.length}</span>
                          </button>
                        </li>
                      );
                    })}
                  </ul>
                </div>
                {/* Pane 2: sent message list */}
                <div className="border-r border-border flex flex-col">
                  <div className="px-3 h-10 flex items-center gap-2 border-b border-border">
                    <span className="text-sm font-semibold text-fg">{cur}</span>
                    <span className="text-2xs text-fg-muted">{list.length} sent</span>
                  </div>
                  <ul className="overflow-y-auto divide-y divide-border" style={{ maxHeight: "calc(70vh - 40px)" }}>
                    {list.map(e => {
                      const sum = eventSummary(e); const sel = openEv && e.id === openEv.id;
                      const HubI = hubIconFor(e.source_hub);
                      return (
                        <li key={e.id}>
                          <button onClick={() => setSentMsg(e.id)}
                                  className={"w-full text-left px-3 py-2.5 transition-colors " + (sel ? "bg-accent-soft/60" : "hover:bg-bg-hover")}>
                            <div className="flex items-center gap-2 mb-0.5">
                              {HubI && <span className="text-fg-muted shrink-0"><HubI size={12} /></span>}
                              <code className="text-xs font-mono font-medium text-fg truncate flex-1">{e.event_type}</code>
                              <span className="text-2xs text-fg-muted shrink-0">{fmtRel(e.created_at)}</span>
                            </div>
                            {(e.recipients || []).length > 0 && <div className="text-2xs text-fg-muted truncate">→ {(e.recipients || []).join(", ")}</div>}
                            {sum.text && <div className="text-2xs text-fg-muted truncate mt-0.5">{sum.text}</div>}
                          </button>
                        </li>
                      );
                    })}
                  </ul>
                </div>
                {/* Pane 3: reading pane */}
                <div className="flex flex-col">
                  {!openEv ? (
                    <div className="flex-1 flex items-center justify-center text-sm text-fg-muted">Select a sent event to read.</div>
                  ) : (
                    <div className="overflow-y-auto" style={{ maxHeight: "70vh" }}>
                      <div className="px-5 py-4 border-b border-border">
                        <div className="flex items-center gap-2 mb-2">
                          {hubIconFor(openEv.source_hub) && <span className="text-fg-muted">{React.createElement(hubIconFor(openEv.source_hub), { size: 14 })}</span>}
                          <code className="text-sm font-mono font-semibold text-fg">{openEv.event_type}</code>
                          <span className="text-2xs px-1.5 py-0.5 rounded font-medium" style={{ color: eventPriorityVisual(openEv.priority).color, background: "color-mix(in srgb, " + eventPriorityVisual(openEv.priority).dot + " 14%, transparent)" }}>{eventPriorityVisual(openEv.priority).label}</span>
                        </div>
                        <div className="text-xs text-fg-muted flex items-center gap-2 flex-wrap">
                          <span><span className="text-fg-muted">from</span> <span className="text-fg-secondary font-medium">{openEv.source_hub}</span></span>
                          {(openEv.recipients || []).length > 0 && <><span>·</span><span><span className="text-fg-muted">to</span> {openEv.recipients.join(", ")}</span></>}
                          <span>·</span><span>{fmtFull(openEv.created_at)}</span>
                        </div>
                      </div>
                      <div className="px-5 py-4 space-y-4">
                        {openSum.chat ? (
                          <div className="text-sm text-fg leading-relaxed whitespace-pre-wrap">{openSum.text}</div>
                        ) : openSum.text ? (
                          <div className="text-md font-semibold text-fg leading-snug">{openSum.text}</div>
                        ) : null}
                        {(() => {
                          const fields = openSum.chat ? [] : eventFields(openEv.payload);
                          if (fields.length === 0) return null;
                          return (
                            <div className="border border-border rounded-md divide-y divide-border bg-bg-secondary/30">
                              {fields.map(([k, v], i) => (
                                <div key={i} className="px-3 py-1.5 flex items-start gap-3 text-xs">
                                  <span className="text-fg-muted w-32 shrink-0 truncate">{k}</span>
                                  <span className="text-fg-secondary font-mono break-all flex-1">{v}</span>
                                </div>
                              ))}
                            </div>
                          );
                        })()}
                        <div className="flex items-center gap-2 flex-wrap">
                          {openSum.ref && (
                            <button onClick={() => nav(openSum.ref.kind === "pr" ? `/projects/${encodeURIComponent(projectId)}/codehub/pr/${encodeURIComponent(openSum.ref.id)}`
                                                 : openSum.ref.kind === "task" ? `/projects/${encodeURIComponent(projectId)}/workhub/task/${encodeURIComponent(openSum.ref.id)}`
                                                 : `/projects/${encodeURIComponent(projectId)}/${openSum.ref.hub}`)}
                                    className="btn-px btn-px-primary btn-px-sm">
                              {(() => { const I = hubIconFor(openSum.ref.hub); return I ? <I size={12} /> : null; })()} Open in {openSum.ref.hub}
                            </button>
                          )}
                          {openEv.thread_id && (
                            <button onClick={() => { setTab("conversations"); setActiveThread(openEv.thread_id); }}
                                    className="btn-px btn-px-ghost btn-px-sm">{Icons.chat && <Icons.chat size={12} />} Open thread</button>
                          )}
                        </div>
                        <details>
                          <summary className="cursor-pointer text-2xs uppercase tracking-wider font-medium text-fg-muted hover:text-fg-secondary">Raw payload</summary>
                          <div className="mt-1.5"><JsonBlock value={openEv.payload} empty="(no payload)" /></div>
                        </details>
                      </div>
                    </div>
                  )}
                </div>
              </div>
            );
          })()
        )}

        {/* ===== Subscriptions ===== */}
        {tab === "subscriptions" && (
          subs.length === 0 ? (
            <HubCard><EmptyState icon={Icons.shield} title="No subscriptions"
              sub="Agents subscribe to hub events (source + type + priority floor) to control fan-out into their inbox." /></HubCard>
          ) : (
            <HubCard>
              <HubCardHeader title="Subscriptions" subtitle={`${subs.length} rules`} />
              <ul className="p-3 space-y-2">
                {subs.map((s, i) => (
                  <li key={s.id || i} className="px-3 py-2.5 border border-border rounded-md bg-bg-elevated flex items-center gap-3 flex-wrap text-sm">
                    <span className="font-medium text-fg">{s.agent}</span>
                    <span className="text-fg-muted">subscribes to</span>
                    <code className="text-xs font-mono px-1.5 py-0.5 rounded bg-bg-tertiary">{s.source_hub === "*" ? "all hubs" : s.source_hub}</code>
                    <span className="text-fg-muted/60">/</span>
                    <code className="text-xs font-mono px-1.5 py-0.5 rounded bg-bg-tertiary">{s.event_type === "*" ? "all types" : s.event_type}</code>
                    <span className="text-2xs text-fg-muted">≥ {s.priority_floor || "low"}</span>
                    <span className="text-2xs px-1.5 py-0.5 rounded bg-bg-tertiary text-fg-muted ml-auto">{s.delivery || "live"}</span>
                  </li>
                ))}
              </ul>
            </HubCard>
          )
        )}
      </HubLayout>
    );
  }

  // ===========================================================================
  // Cutover 43.26: RunHub — CI/CD-style end-to-end run history.
  // Run list + run detail (pipeline timeline + healthcheck + probe table + MCP).
  // ===========================================================================
  const RUN_STAGES = [
    { key: "starting",         label: "Init" },
    { key: "starting_compose", label: "Compose" },
    { key: "healthy",          label: "Health" },
    { key: "probing",          label: "Probe" },
    { key: "done",             label: "Done" },
  ];
  function runStatusVisual(s) {
    return {
      starting:         { label: "starting",  color: "var(--text-muted)", bg: "var(--bg-tertiary)", dot: "var(--text-muted)" },
      starting_compose: { label: "composing", color: "var(--info)",       bg: "var(--info-soft)",   dot: "var(--info)" },
      healthy:          { label: "healthy",   color: "var(--info)",       bg: "var(--info-soft)",   dot: "var(--info)" },
      probing:          { label: "probing",   color: "var(--info)",       bg: "var(--info-soft)",   dot: "var(--info)" },
      completed:        { label: "passed",    color: "var(--success)",    bg: "var(--success-soft)",dot: "var(--success)" },
      failed:           { label: "failed",    color: "var(--danger)",     bg: "var(--danger-soft)", dot: "var(--danger)" },
      aborted:          { label: "aborted",   color: "var(--warning)",    bg: "var(--warning-soft)",dot: "var(--warning)" },
    }[s] || { label: s || "—", color: "var(--text-muted)", bg: "var(--bg-tertiary)", dot: "var(--text-muted)" };
  }
  function fmtDuration(a, b) {
    if (!a) return "—";
    const end = b || Date.now() / 1000;
    const s = Math.max(0, end - a);
    if (s < 60) return `${s.toFixed(1)}s`;
    if (s < 3600) return `${Math.floor(s / 60)}m ${Math.round(s % 60)}s`;
    return `${Math.floor(s / 3600)}h ${Math.floor((s % 3600) / 60)}m`;
  }
  const sevTone = { P0: "var(--danger)", P1: "var(--warning)", P2: "var(--info)", P3: "var(--text-muted)" };

  function RunHubPage({ projectId, hub, state, subResource, subResourceId }) {
    if (subResource === "run" && subResourceId) {
      return <RunDetailView projectId={projectId} hub={hub} runId={subResourceId} />;
    }
    return <RunHubList projectId={projectId} hub={hub} />;
  }

  function RunHubList({ projectId, hub }) {
    const Icons = window.Icons || {};
    const runs = Object.values(hub?.runs || {}).sort((a, b) => (b.started_at || 0) - (a.started_at || 0));
    const nav = (p) => window.LiveMonitorRouter.navigateTo(p);
    const passed = runs.filter(r => r.status === "completed" && (r.fail_count || 0) === 0).length;
    const failed = runs.filter(r => r.status === "failed" || r.status === "aborted" || (r.fail_count || 0) > 0).length;
    const running = runs.filter(r => ["starting", "starting_compose", "healthy", "probing"].includes(r.status)).length;
    const passRate = runs.length ? Math.round(100 * passed / runs.length) : null;

    const [tab, setTab] = useState("verification");
    const [genRuns, setGenRuns] = useState([]);
    const [logRun, setLogRun] = useState(null);
    // Orchestrator generation runs (live agent-framework subprocesses) for this project.
    useEffect(() => {
      let alive = true;
      const load = () => fetch(`/api/runs`, { credentials: "include" })
        .then(r => r.json())
        .then(d => { if (alive) setGenRuns((d.runs || []).filter(r => r.project_id === projectId)); })
        .catch(() => {});
      load();
      const poll = setInterval(load, 5000);
      return () => { alive = false; clearInterval(poll); };
    }, [projectId]);

    function probeSummary(r) {
      const ps = r.probes || [];
      return { pass: ps.filter(p => p.verdict === "pass").length, fail: ps.filter(p => p.verdict === "fail").length, skip: ps.filter(p => p.verdict === "skipped").length, total: ps.length };
    }
    const genStateVisual = (s) => ({ running: "var(--info)", completed: "var(--success)", failed: "var(--danger)" }[s] || "var(--text-muted)");

    return (
      <HubLayout>
        <div className="grid grid-cols-4 gap-3 mb-5">
          <MetricTile label="Verification runs" value={runs.length} sub={passRate == null ? "no runs" : `${passRate}% pass rate`} icon={Icons.shieldCheck} tone="info" />
          <MetricTile label="Passed" value={passed} sub="all probes green" icon={Icons.shieldCheck} tone="success" />
          <MetricTile label="Failed" value={failed} sub={failed ? "needs attention" : "all clear"} icon={Icons.bug} tone={failed ? "danger" : "neutral"} />
          <MetricTile label="Generation runs" value={genRuns.length} sub={genRuns.some(r => r.state === "running") ? "in flight" : "agent framework"} icon={Icons.play} tone={genRuns.some(r => r.state === "running") ? "info" : "neutral"} />
        </div>

        <TabBar current={tab} onChange={setTab} tabs={[
          { key: "verification", label: "Verification runs", count: runs.length },
          { key: "generation", label: "Generation runs", count: genRuns.length },
        ]} />

        {tab === "generation" && (
          <HubCard>
            <HubCardHeader title="Generation runs" subtitle="agent-framework end-to-end runs (orchestrator subprocess)" />
            {genRuns.length === 0 ? (
              <EmptyState icon={Icons.play} title="No generation runs"
                sub="When a project generation is launched, the orchestrator run appears here with a live, streaming log." />
            ) : (
              <ul className="p-3 space-y-2">
                {genRuns.map(r => {
                  const c = genStateVisual(r.state);
                  const open = logRun === r.run_id;
                  return (
                    <li key={r.run_id} className="border border-border rounded-md bg-bg-elevated overflow-hidden">
                      <div className="px-4 py-3 flex items-center gap-3">
                        <span className="w-7 h-7 rounded-full flex items-center justify-center shrink-0 text-xs font-bold" style={{ background: `color-mix(in srgb, ${c} 14%, transparent)`, color: c }}>
                          {r.state === "completed" ? "✓" : r.state === "failed" ? "✕" : <span className="w-1.5 h-1.5 rounded-full animate-pulse" style={{ background: c }} />}
                        </span>
                        <div className="flex-1 min-w-0">
                          <div className="flex items-baseline gap-2">
                            <code className="text-md font-mono font-semibold text-fg">{(r.run_id || "").substr(0, 16)}</code>
                            <span className="text-xs font-medium" style={{ color: c }}>{r.state}{r.returncode != null ? ` (rc ${r.returncode})` : ""}</span>
                          </div>
                          <div className="text-xs text-fg-muted mt-0.5">started {fmtRel(r.started_at)}{r.log_path ? " · " + r.log_path.split("/").pop() : ""}</div>
                        </div>
                        <button onClick={() => setLogRun(open ? null : r.run_id)} className="btn-px btn-px-ghost btn-px-sm shrink-0">
                          {open ? "Hide log" : "View log"}
                        </button>
                      </div>
                      {open && window.RunLogStream && (
                        <div className="border-t border-border">
                          <window.RunLogStream runId={r.run_id} onClose={() => setLogRun(null)} />
                        </div>
                      )}
                    </li>
                  );
                })}
              </ul>
            )}
          </HubCard>
        )}

        {tab === "verification" && (
        <HubCard>
          <HubCardHeader title="Verification runs" subtitle={`${runs.length}`} />
          {runs.length === 0 ? (
            <EmptyState icon={Icons.play} title="No runs yet"
              sub="End-to-end runs (compose up → healthcheck → endpoint probes) are recorded here as agents verify the app." />
          ) : (
            <ul className="p-3 space-y-2">
              {runs.map(r => {
                const sv = runStatusVisual(r.status);
                const ps = probeSummary(r);
                const terminal = ["completed", "failed", "aborted"].includes(r.status);
                return (
                  <li key={r.id}>
                    <button onClick={() => nav(`/projects/${encodeURIComponent(projectId)}/runhub/run/${encodeURIComponent(r.id)}`)}
                            className="w-full text-left px-4 py-3 border border-border rounded-md bg-bg-elevated hover:border-border-strong hover:shadow-sm transition-all flex items-center gap-3 group">
                      {/* status icon */}
                      <span className="w-7 h-7 rounded-full flex items-center justify-center shrink-0 text-xs font-bold"
                            style={{ background: sv.bg, color: sv.color, boxShadow: `inset 0 1px 0 rgba(255,255,255,0.4), 0 0 0 1px color-mix(in srgb, ${sv.color} 30%, transparent)` }}>
                        {r.status === "completed" ? "✓" : r.status === "failed" ? "✕" : r.status === "aborted" ? "!" : <span className="w-1.5 h-1.5 rounded-full animate-pulse" style={{ background: sv.color }} />}
                      </span>
                      <div className="flex-1 min-w-0">
                        <div className="flex items-baseline gap-2 mb-0.5">
                          <code className="text-md font-mono font-semibold text-fg group-hover:text-accent transition-colors">{(r.id || "").substr(0, 14)}</code>
                          <span className="text-xs font-medium" style={{ color: sv.color }}>{sv.label}</span>
                        </div>
                        <div className="flex items-center flex-wrap gap-x-2.5 gap-y-1 text-xs text-fg-muted">
                          {Icons.branch && <span className="inline-flex items-center gap-1"><Icons.branch size={11} /><code className="font-mono">{r.branch || "—"}</code></span>}
                          <span className="text-fg-muted/40">·</span>
                          <span>by {r.started_by || "system"}</span>
                          <span className="text-fg-muted/40">·</span>
                          <span>started {fmtRel(r.started_at)}</span>
                          <span className="text-fg-muted/40">·</span>
                          <span>{terminal ? "took" : "running"} {fmtDuration(r.started_at, r.finished_at)}</span>
                        </div>
                      </div>
                      {/* probe summary */}
                      {ps.total > 0 && (
                        <div className="flex items-center gap-2 text-xs shrink-0">
                          <span className="text-success font-medium">{ps.pass}✓</span>
                          {ps.fail > 0 && <span className="text-danger font-medium">{ps.fail}✕</span>}
                          {ps.skip > 0 && <span className="text-fg-muted">{ps.skip}⊘</span>}
                        </div>
                      )}
                      {r.healthcheck && (
                        <span className={"text-2xs px-1.5 py-0.5 rounded shrink-0 " + (r.healthcheck.healthy ? "bg-success-soft text-success" : "bg-danger-soft text-danger")}>
                          {r.healthcheck.healthy ? "health ok" : "unhealthy"}
                        </span>
                      )}
                      {Icons.chevronRight && <span className="text-fg-muted shrink-0 opacity-0 group-hover:opacity-100 transition-opacity"><Icons.chevronRight size={14} /></span>}
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
        </HubCard>
        )}
      </HubLayout>
    );
  }

  // ----- Pipeline timeline -----
  function RunPipeline({ run }) {
    // derive per-stage state from run.status + results
    const reached = {
      starting: true,
      starting_compose: ["starting_compose", "healthy", "probing", "completed", "failed", "aborted"].includes(run.status) || run.status !== "starting",
      healthy: run.healthcheck != null || ["healthy", "probing", "completed", "failed"].includes(run.status),
      probing: (run.probes || []).length > 0 || ["probing", "completed", "failed"].includes(run.status),
      done: ["completed", "failed", "aborted"].includes(run.status),
    };
    const stageState = (key) => {
      if (key === "healthy" && run.healthcheck && !run.healthcheck.healthy) return "fail";
      if (key === "done") return run.status === "completed" ? "pass" : run.status === "failed" || run.status === "aborted" ? "fail" : "pending";
      if (key === "probing" && (run.fail_count || 0) > 0) return "fail";
      if (reached[key]) return run.status === "failed" && key === "done" ? "fail" : "pass";
      return "pending";
    };
    const active = !["completed", "failed", "aborted"].includes(run.status);
    return (
      <div className="flex items-center gap-0 px-1">
        {RUN_STAGES.map((st, i) => {
          const stt = stageState(st.key);
          const color = stt === "fail" ? "var(--danger)" : stt === "pass" ? "var(--success)" : "var(--border-strong)";
          const isCurrent = active && reached[st.key] && !reached[RUN_STAGES[i + 1]?.key];
          return (
            <React.Fragment key={st.key}>
              <div className="flex flex-col items-center gap-1.5">
                <span className="w-7 h-7 rounded-full flex items-center justify-center text-xs font-bold shrink-0"
                      style={{ background: stt === "pending" ? "var(--bg-tertiary)" : `color-mix(in srgb, ${color} 14%, transparent)`, color, boxShadow: `0 0 0 1px color-mix(in srgb, ${color} 35%, transparent)` }}>
                  {stt === "pass" ? "✓" : stt === "fail" ? "✕" : isCurrent ? <span className="w-1.5 h-1.5 rounded-full animate-pulse" style={{ background: color }} /> : (i + 1)}
                </span>
                <span className="text-2xs font-medium" style={{ color: stt === "pending" ? "var(--text-muted)" : color }}>{st.label}</span>
              </div>
              {i < RUN_STAGES.length - 1 && (
                <div className="flex-1 h-0.5 mx-1 rounded-full -mt-4" style={{ background: reached[RUN_STAGES[i + 1].key] ? color : "var(--border)" }} />
              )}
            </React.Fragment>
          );
        })}
      </div>
    );
  }

  function RunDetailView({ projectId, hub, runId }) {
    const Icons = window.Icons || {};
    const run = (hub?.runs || {})[runId];
    const nav = (p) => window.LiveMonitorRouter.navigateTo(p);
    const back = () => nav(`/projects/${encodeURIComponent(projectId)}/runhub`);
    if (!run) {
      return (
        <HubLayout>
          <button onClick={back} className="flex items-center gap-1.5 text-sm text-fg-secondary hover:text-accent mb-4">{Icons.chevronLeft && <Icons.chevronLeft size={14} />} Back to runs</button>
          <EmptyState icon={Icons.play} title="Run not found" sub={`No run ${runId}.`} actionLabel="Back to RunHub" onAction={back} />
        </HubLayout>
      );
    }
    const sv = runStatusVisual(run.status);
    const probes = run.probes || [];
    const mcp = run.mcp_probes || [];
    const hc = run.healthcheck;
    const passN = probes.filter(p => p.verdict === "pass").length;
    const failN = probes.filter(p => p.verdict === "fail").length;
    const skipN = probes.filter(p => p.verdict === "skipped").length;
    // sort: failures first (by severity), then pass, then skipped
    const sevRank = { P0: 0, P1: 1, P2: 2, P3: 3 };
    const sortedProbes = [...probes].sort((a, b) => {
      const order = { fail: 0, pass: 1, skipped: 2 };
      return (order[a.verdict] - order[b.verdict]) || ((sevRank[a.severity] ?? 9) - (sevRank[b.severity] ?? 9));
    });

    return (
      <HubLayout>
        <button onClick={back} className="flex items-center gap-1.5 text-sm text-fg-secondary hover:text-accent mb-4 transition-colors">{Icons.chevronLeft && <Icons.chevronLeft size={14} />} <span>Runs</span></button>

        {/* Header */}
        <div className="bg-bg-elevated border border-border rounded-lg p-5 mb-4" style={{ boxShadow: "inset 0 1px 0 rgba(255,255,255,0.4)" }}>
          <div className="flex items-start gap-4 mb-4">
            <span className="w-9 h-9 rounded-full flex items-center justify-center shrink-0 text-md font-bold mt-0.5"
                  style={{ background: sv.bg, color: sv.color, boxShadow: `inset 0 1px 0 rgba(255,255,255,0.4), 0 0 0 1px color-mix(in srgb, ${sv.color} 30%, transparent)` }}>
              {run.status === "completed" ? "✓" : run.status === "failed" ? "✕" : run.status === "aborted" ? "!" : "●"}
            </span>
            <div className="flex-1 min-w-0">
              <div className="flex items-baseline gap-3 flex-wrap mb-1">
                <h1 className="text-2xl font-mono font-semibold tracking-tight text-fg">{(run.id || "").substr(0, 16)}</h1>
                <span className="text-sm font-medium uppercase tracking-wider" style={{ color: sv.color }}>{sv.label}</span>
              </div>
              <div className="flex items-center flex-wrap gap-x-3 gap-y-1 text-sm text-fg-secondary">
                {Icons.branch && <span className="inline-flex items-center gap-1"><Icons.branch size={12} /><code className="font-mono">{run.branch || "—"}</code></span>}
                <span className="text-fg-muted/40">·</span>
                <span>by {run.started_by || "system"}</span>
                <span className="text-fg-muted/40">·</span>
                <span>{fmtRel(run.started_at)}</span>
                <span className="text-fg-muted/40">·</span>
                <span>took {fmtDuration(run.started_at, run.finished_at)}</span>
              </div>
              {run.generated_dir && <div className="mt-1.5 text-2xs font-mono text-fg-muted truncate">{run.generated_dir}</div>}
            </div>
          </div>
          {/* pipeline */}
          <div className="pt-4 border-t border-border-subtle">
            <RunPipeline run={run} />
          </div>
        </div>

        {/* Summary stats */}
        <div className="grid grid-cols-4 gap-3 mb-4">
          <SummaryStat label="Probes passed" value={`${passN}/${probes.length}`} tone={failN === 0 && probes.length > 0 ? "success" : "neutral"} />
          <SummaryStat label="Failed" value={failN} tone={failN > 0 ? "danger" : "neutral"} />
          <SummaryStat label="Skipped" value={skipN} tone="neutral" />
          <SummaryStat label="MCP probes" value={mcp.length ? `${mcp.filter(m => m.verdict === "pass").length}/${mcp.length}` : "—"} tone="neutral" />
        </div>

        {/* Healthcheck */}
        {hc && (
          <HubCard className="mb-4">
            <HubCardHeader title="Healthcheck" subtitle={hc.healthy ? "service came up" : "service failed to start"} />
            <div className="px-4 py-3 grid grid-cols-4 gap-3 text-sm">
              <div><div className="text-2xs uppercase tracking-wider text-fg-muted mb-0.5">Status</div><span className={"font-medium " + (hc.healthy ? "text-success" : "text-danger")}>{hc.healthy ? "healthy" : "unhealthy"}</span></div>
              <div><div className="text-2xs uppercase tracking-wider text-fg-muted mb-0.5">HTTP</div><code className="font-mono">{hc.status_code ?? "—"}</code></div>
              <div><div className="text-2xs uppercase tracking-wider text-fg-muted mb-0.5">Attempts</div><span className="tabular-nums">{hc.attempts ?? "—"}</span></div>
              <div><div className="text-2xs uppercase tracking-wider text-fg-muted mb-0.5">Elapsed</div><span className="tabular-nums">{hc.elapsed_s != null ? hc.elapsed_s.toFixed(1) + "s" : "—"}</span></div>
              {hc.last_error && <div className="col-span-4 text-xs text-danger bg-danger-soft rounded px-2 py-1 font-mono">{hc.last_error}</div>}
            </div>
          </HubCard>
        )}

        {/* Probes table */}
        <HubCard className="mb-4">
          <HubCardHeader title="Endpoint probes" subtitle={`${passN} passed · ${failN} failed · ${skipN} skipped`} />
          {probes.length === 0 ? (
            <EmptyState icon={Icons.api} title="No probes" sub="Endpoint probes run after the service is healthy." />
          ) : (
            <ul className="divide-y divide-border">
              {sortedProbes.map((p, i) => {
                const vtone = p.verdict === "pass" ? "var(--success)" : p.verdict === "fail" ? "var(--danger)" : "var(--text-muted)";
                const vbg = p.verdict === "pass" ? "var(--success-soft)" : p.verdict === "fail" ? "var(--danger-soft)" : "var(--bg-tertiary)";
                return (
                  <li key={i} className="px-4 py-2.5 flex items-center gap-3">
                    <span className="text-2xs font-mono font-semibold uppercase px-1.5 py-0.5 rounded w-14 text-center shrink-0" style={{ color: vtone, background: vbg }}>
                      {p.verdict === "skipped" ? "skip" : p.verdict}
                    </span>
                    <MethodChip method={p.method} />
                    <code className="font-mono text-sm text-fg flex-1 min-w-0 truncate">{p.path}</code>
                    {p.verdict === "fail" && p.severity && (
                      <span className="text-2xs font-mono font-semibold px-1.5 py-0.5 rounded shrink-0" style={{ color: sevTone[p.severity], background: `color-mix(in srgb, ${sevTone[p.severity]} 14%, transparent)` }}>{p.severity}</span>
                    )}
                    {p.status_code != null && <code className="text-2xs font-mono text-fg-muted shrink-0">{p.status_code}</code>}
                    {p.transport_error && <span className="text-2xs text-danger shrink-0">{p.transport_error}</span>}
                    {p.latency_ms != null && <span className="text-2xs text-fg-muted tabular-nums shrink-0 w-16 text-right">{p.latency_ms.toFixed(0)}ms</span>}
                  </li>
                );
              })}
            </ul>
          )}
          {/* failure notes */}
          {sortedProbes.some(p => p.verdict === "fail" && p.note) && (
            <div className="px-4 py-3 border-t border-border-subtle space-y-1.5">
              <div className="text-2xs uppercase tracking-wider font-medium text-fg-muted">Failure notes</div>
              {sortedProbes.filter(p => p.verdict === "fail" && p.note).map((p, i) => (
                <div key={i} className="text-xs text-fg-secondary"><code className="font-mono text-danger">{p.method} {p.path}</code> — {p.note}</div>
              ))}
            </div>
          )}
        </HubCard>

        {/* MCP probes */}
        {mcp.length > 0 && (
          <HubCard className="mb-4">
            <HubCardHeader title="MCP server probes" subtitle={`${mcp.filter(m => m.verdict === "pass").length}/${mcp.length} alive`} />
            <ul className="divide-y divide-border">
              {mcp.map((m, i) => {
                const vtone = m.verdict === "pass" ? "var(--success)" : m.verdict === "fail" ? "var(--danger)" : "var(--text-muted)";
                const vbg = m.verdict === "pass" ? "var(--success-soft)" : m.verdict === "fail" ? "var(--danger-soft)" : "var(--bg-tertiary)";
                return (
                  <li key={i} className="px-4 py-2.5 flex items-center gap-3">
                    <span className="text-2xs font-mono font-semibold uppercase px-1.5 py-0.5 rounded w-14 text-center shrink-0" style={{ color: vtone, background: vbg }}>{m.verdict === "skipped" ? "skip" : m.verdict}</span>
                    {Icons.server && <span className="text-fg-muted shrink-0"><Icons.server size={13} /></span>}
                    <code className="font-mono text-sm text-fg flex-1 truncate">{m.server}</code>
                    <span className="text-2xs px-1.5 py-0.5 rounded bg-bg-tertiary text-fg-muted font-mono shrink-0">{m.transport}</span>
                    {(m.detail || m.reason) && <span className="text-2xs text-fg-muted shrink-0 truncate max-w-[40%]">{m.detail || m.reason}</span>}
                  </li>
                );
              })}
            </ul>
          </HubCard>
        )}

        {/* compose stderr on failure */}
        {run.compose_stderr && (
          <HubCard className="mb-4">
            <HubCardHeader title="Compose stderr" />
            <div className="p-3">
              <pre className="p-3 m-0 rounded-md border border-border overflow-auto text-2xs font-mono text-danger" style={{ background: "var(--bg-secondary)", maxHeight: 240 }}>{run.compose_stderr}</pre>
            </div>
          </HubCard>
        )}
      </HubLayout>
    );
  }

  // ===========================================================================
  // Preview — the deployable face of the project: the running app, pinned to the
  // content of the CURRENT release branch (release-v<tag>). Releases are cut by
  // the orchestrator and gated on a successful render+functional run, so this
  // page only ever shows vetted snapshots. Two views: the live running app
  // (iframe) and the source tree as it exists on the release branch.
  // ===========================================================================
  function PreviewPage({ projectId, hub, state }) {
    const Icons = window.Icons || {};
    const releases = Object.values(hub?.releases || {})
      .sort((a, b) => (b.created_at || 0) - (a.created_at || 0));
    const [selectedTag, setSelectedTag] = useState(null);
    const [view, setView] = useState("live");           // live | source
    const [iframeKey, setIframeKey] = useState(0);       // bump to force reload

    const selected = useMemo(() => {
      if (!releases.length) return null;
      if (selectedTag) {
        const hit = releases.find(r => (r.tag || r.id) === selectedTag);
        if (hit) return hit;
      }
      return releases[0];
    }, [releases, selectedTag]);

    const previewUrl = state?.previewUrl || "http://127.0.0.1:3000";
    const branch = selected?.branch || null;

    if (!releases.length) {
      return (
        <HubLayout>
          <HubCard>
            <EmptyState icon={Icons.shieldCheck} title="No release to preview yet"
              sub="Preview renders the current release branch. The orchestrator cuts a release (release-v<tag>) once a run renders the frontend and passes its functional checks — it will appear here automatically." />
          </HubCard>
        </HubLayout>
      );
    }

    const branchOptions = releases.map(r => ({
      value: r.tag || r.id,
      label: `${r.tag || r.id}${r.branch ? "  ·  " + r.branch : ""}`,
    }));

    return (
      <HubLayout>
        {/* Release header */}
        <HubCard className="mb-4">
          <div className="p-4 flex items-start gap-4 flex-wrap">
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2.5 flex-wrap">
                <span className="font-mono text-lg font-semibold text-accent">{selected.tag || selected.id}</span>
                {selected.branch && (
                  <code className="font-mono text-2xs px-1.5 py-0.5 rounded bg-bg-tertiary text-fg-secondary">{selected.branch}</code>
                )}
                {selected.branch_sha && (
                  <code className="font-mono text-2xs text-fg-muted" title={selected.branch_sha}>{String(selected.branch_sha).slice(0, 8)}</code>
                )}
                <ActorChip name={selected._updated_by || selected.created_by || "orchestrator"} />
                <span className="text-2xs text-fg-muted">{fmtRel(selected.created_at)}</span>
              </div>
              {selected.notes && <div className="text-sm text-fg-secondary mt-1.5 leading-snug">{selected.notes}</div>}
              {selected.branch_error && (
                <div className="text-2xs text-danger mt-1.5">Release branch was not cut: {selected.branch_error}</div>
              )}
            </div>
            {releases.length > 1 && (
              <div className="shrink-0">
                <div className="text-2xs text-fg-muted mb-1">Release</div>
                {UiSelect
                  ? <UiSelect value={selected.tag || selected.id} onChange={setSelectedTag} options={branchOptions} minWidth={220} inputStyle />
                  : null}
              </div>
            )}
          </div>
        </HubCard>

        {/* View toggle */}
        <TabBar current={view} onChange={setView} tabs={[
          { key: "live", label: "Live app" },
          { key: "source", label: "Source @ release" },
        ]} />

        {view === "live" && (
          <HubCard>
            <HubCardHeader title="Running app" subtitle={previewUrl} actions={
              <div className="flex items-center gap-2">
                <button onClick={() => setIframeKey(k => k + 1)} className="btn-px btn-px-ghost btn-px-sm">
                  {Icons.refresh ? <Icons.refresh size={12} /> : "↻"} Reload
                </button>
                <a href={previewUrl} target="_blank" rel="noreferrer" className="btn-px btn-px-ghost btn-px-sm">
                  Open in new tab
                </a>
              </div>
            } />
            <div className="p-3">
              <div className="text-2xs text-fg-muted mb-2 leading-snug">
                The live app reflects the running deployment (RunHub compose-up). It corresponds to <code className="font-mono">{branch || "main"}</code> when the latest release was the most recent successful run.
              </div>
              <div className="rounded-md border border-border overflow-hidden bg-white" style={{ height: 640 }}>
                <iframe key={iframeKey} title="Release preview" src={previewUrl}
                        style={{ width: "100%", height: "100%", border: 0 }} />
              </div>
            </div>
          </HubCard>
        )}

        {view === "source" && (
          branch ? (
            <CodeBrowser projectId={projectId} branch={branch}
                         branchList={[branch]} defaultBranch={branch}
                         onBranchChange={() => {}} branchMeta={{}} />
          ) : (
            <HubCard>
              <EmptyState icon={Icons.code} title="No release branch"
                sub="This release was recorded without a git branch, so its source can't be browsed. Live app view still works." />
            </HubCard>
          )
        )}
      </HubLayout>
    );
  }

  // Cutover 43.27: expose shared atoms so cross-cutting pages share the look.
  window.HubUI = { HubLayout, HubCard, HubCardHeader, MetricTile, EmptyState, TabBar, UiSelect, ActorChip, fmtRel, fmtFull };

  return { CodeHubPage, RegistryHubPage, WorkHubPage, EventHubPage, RunHubPage, PreviewPage };
})();
