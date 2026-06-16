// Cutover 41: ProjectShell — sidebar-driven layout for per-project / per-hub pages.
// Cutover 42: Notion-style grouped sidebar with workspace switcher, SVG icons,
// theme/logout/collapse moved to sidebar footer, slim topbar.
window.ProjectShell = (function () {
  const { useEffect, useState } = React;

  const NAV_GROUPS = [
    { header: null, items: [
      { key: "overview", label: "Overview", icon: "home" },
    ]},
    { header: "Hubs", items: [
      { key: "codehub",  label: "CodeHub",  icon: "code" },
      { key: "registryhub",   label: "RegistryHub",   icon: "api" },
      { key: "workhub",  label: "WorkHub",  icon: "workhub" },
      { key: "eventhub", label: "EventHub", icon: "inbox" },
      { key: "runhub",   label: "RunHub",   icon: "play" },
    ]},
    { header: "Workspace", items: [
      { key: "preview",    label: "Preview",    icon: "monitor" },
      { key: "history",    label: "History",    icon: "clipboard" },
      { key: "chat",       label: "Chat",       icon: "chat" },
      { key: "references", label: "References", icon: "file" },
      { key: "gates",      label: "Gates",      icon: "shield" },
    ]},
  ];

  function ProjectShell({ projectId, section, subResource, subResourceId, state, error, lastUpdated }) {
    const themeCtx = window.MonitorTheme.useTheme();
    const [collapsed, setCollapsed] = useState(false);

    function nav(k) {
      window.LiveMonitorRouter.navigateTo(`/projects/${encodeURIComponent(projectId)}/${k}`);
    }

    // Cutover 42 bug fix: render page content inline (computed value, not inner-defined
    // component) so children don't get a NEW function reference every render. A new
    // function = a new component type to React = full unmount+remount → local state
    // (form drafts, scroll, expanded sections) wipes every 1.8s poll. The visual
    // "flash" the user reported is this remount cycle.
    const Pages = window.HubPages || {};
    const CC = window.CrossCuttingPages || {};
    const SECTION_TO_PAGE = {
      overview: ["CC", "OverviewPage"],
      codehub: ["Pages", "CodeHubPage"],
      registryhub: ["Pages", "RegistryHubPage"],
      workhub: ["Pages", "WorkHubPage"],
      eventhub: ["Pages", "EventHubPage"],
      runhub: ["Pages", "RunHubPage"],
      preview: ["Pages", "PreviewPage"],
      history: ["CC", "HistoryPage"],
      chat: ["CC", "ChatPage"],
      references: ["CC", "ReferencesPage"],
      gates: ["CC", "GatesPage"],
    };
    const route = SECTION_TO_PAGE[section];
    let pageContent;
    if (route) {
      const ns = route[0] === "Pages" ? Pages : CC;
      if (ns[route[1]] === undefined) {
        pageContent = <div className="empty-state">Loading {section}…</div>;
      }
    }
    if (pageContent === undefined) {
      switch (section) {
        case "overview":   pageContent = <CC.OverviewPage projectId={projectId} state={state} />; break;
        case "codehub":    pageContent = <Pages.CodeHubPage projectId={projectId} hub={state?.hubs?.codehub} state={state} subResource={subResource} subResourceId={subResourceId} />; break;
        case "registryhub":     pageContent = <Pages.RegistryHubPage projectId={projectId} hub={state?.hubs?.registryhub} state={state} />; break;
        case "workhub":    pageContent = <Pages.WorkHubPage projectId={projectId} hub={state?.hubs?.workhub} state={state} subResource={subResource} subResourceId={subResourceId} />; break;
        case "eventhub":   pageContent = <Pages.EventHubPage projectId={projectId} hub={state?.hubs?.eventhub} state={state} />; break;
        case "runhub":     pageContent = <Pages.RunHubPage projectId={projectId} hub={state?.hubs?.runhub} state={state} subResource={subResource} subResourceId={subResourceId} />; break;
        case "preview":    pageContent = <Pages.PreviewPage projectId={projectId} hub={state?.hubs?.codehub} state={state} />; break;
        case "history":    pageContent = <CC.HistoryPage projectId={projectId} state={state} />; break;
        case "chat":       pageContent = <CC.ChatPage projectId={projectId} />; break;
        case "references": pageContent = <CC.ReferencesPage projectId={projectId} />; break;
        case "gates":      pageContent = <CC.GatesPage projectId={projectId} />; break;
        default:           pageContent = <CC.OverviewPage projectId={projectId} state={state} />;
      }
    }

    const Icons = window.Icons || {};

    return (
      <div className={"shell " + (collapsed ? "shell-collapsed" : "")}>
        <aside className="shell-sidebar">
          <div className="shell-workspace">
            <button className="shell-ws-switcher"
                    onClick={() => window.LiveMonitorRouter.navigateTo("/")}
                    title="Back to all projects">
              {!collapsed && Icons.chevronLeft && (
                <span className="shell-ws-back"><Icons.chevronLeft size={14} /></span>
              )}
              {!collapsed ? (
                <div className="shell-ws-meta">
                  <div className="shell-ws-name">{state?.projectName || projectId}</div>
                  <div className="shell-ws-sub">
                    {state?.projectStatus ? `· ${state.projectStatus}` : "project"}
                  </div>
                </div>
              ) : (
                Icons.chevronLeft && <Icons.chevronLeft size={16} />
              )}
            </button>
          </div>

          <nav className="shell-nav">
            {NAV_GROUPS.map((group, i) => (
              <div key={i} className="shell-nav-group">
                {group.header && !collapsed && (
                  <div className="shell-nav-header">{group.header}</div>
                )}
                {group.items.map(item => {
                  const IconComp = Icons[item.icon];
                  return (
                    <button key={item.key}
                            className={"shell-nav-item " + (section === item.key ? "active" : "")}
                            onClick={() => nav(item.key)}
                            title={item.label}>
                      <span className="shell-nav-icon">{IconComp ? <IconComp size={16} /> : null}</span>
                      {!collapsed && <span className="shell-nav-label">{item.label}</span>}
                    </button>
                  );
                })}
              </div>
            ))}
          </nav>

          <div className="shell-sidebar-footer">
            <button className="shell-icon-btn" onClick={themeCtx.toggle}
                    title={"Switch to " + (themeCtx.theme === "dark" ? "light" : "dark") + " mode"}>
              {themeCtx.theme === "dark"
                ? (Icons.sun ? <Icons.sun size={16} /> : "☀")
                : (Icons.moon ? <Icons.moon size={16} /> : "☾")}
            </button>
            <button className="shell-icon-btn" onClick={async () => {
              await fetch("/api/auth/logout", { method: "POST", credentials: "include" });
              window.location.reload();
            }} title="Logout">
              {Icons.logout ? <Icons.logout size={16} /> : "⎋"}
            </button>
            <button className="shell-icon-btn shell-collapse-btn"
                    onClick={() => setCollapsed(!collapsed)}
                    title={collapsed ? "Expand sidebar" : "Collapse sidebar"}>
              {collapsed
                ? (Icons.chevronRight ? <Icons.chevronRight size={16} /> : "»")
                : (Icons.chevronLeft ? <Icons.chevronLeft size={16} /> : "«")}
            </button>
          </div>
        </aside>
        <div className="shell-main">
          <header className="shell-topbar">
            <div className="shell-topbar-left">
              <h1 className="shell-page-title">
                {NAV_GROUPS.flatMap(g => g.items).find(n => n.key === section)?.label || section}
              </h1>
              {lastUpdated && <span className="shell-updated">Updated {lastUpdated}</span>}
            </div>
          </header>
          {error && <div className="shell-error-bar">Error: {error}</div>}
          <main className="shell-content">
            {pageContent}
          </main>
        </div>
      </div>
    );
  }

  return ProjectShell;
})();
