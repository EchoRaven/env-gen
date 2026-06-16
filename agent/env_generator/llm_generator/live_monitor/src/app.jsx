const { useEffect, useRef, useState } = React;
const { useMonitorState } = window.MonitorApi;
const { Center, Inspector, Sidebar } = window.MonitorViews;

const LAYOUT_KEY = "envforger.monitor.layout";
const CENTER_COLLAPSED_WIDTH = 56;
const LEFT_COLLAPSED_WIDTH = 72;
const RIGHT_COLLAPSED_WIDTH = 72;
const CENTER_MIN_WIDTH = 180;
const HANDLE_WIDTH_TOTAL = 48;

function clamp(value, min, max) {
  return Math.max(min, Math.min(max, value));
}

function readLayout() {
  try {
    const raw = localStorage.getItem(LAYOUT_KEY);
    if (!raw) return { left: 280, right: 520 };
    const parsed = JSON.parse(raw);
    return {
      left: clamp(Number(parsed.left) || 280, 140, 2400),
      right: clamp(Number(parsed.right) || 520, 180, 2400),
      split: clamp(Number(parsed.split) || 0, 140, 2400),
    };
  } catch {
    return { left: 280, right: 520, split: 0 };
  }
}

function readViewportWidth() {
  return typeof window === "undefined" ? 1440 : window.innerWidth;
}

function MonitorApp() {
  // Cutover 35: auth gate — check /api/auth/me on mount. If auth is required
  // and we don't have a session, show <LoginScreen>. Otherwise fall through to
  // the existing route logic.
  const [authState, setAuthState] = useState({ checked: false, username: null, authRequired: false });

  useEffect(() => {
    async function check() {
      try {
        const r = await fetch("/api/auth/me", { credentials: "include" });
        if (r.status === 401) {
          setAuthState({ checked: true, username: null, authRequired: true });
          return;
        }
        const data = await r.json();
        setAuthState({ checked: true, username: data.username, authRequired: !!data.auth_required });
      } catch (e) {
        setAuthState({ checked: true, username: null, authRequired: false });
      }
    }
    check();
  }, []);

  // Cutover 28: hash-based route gating. #/ -> Homepage; #/projects/<id> -> per-project view.
  const route = window.LiveMonitorRouter.useRoute();

  if (!authState.checked) {
    return <div className="loading-screen">Loading…</div>;
  }
  if (authState.authRequired && !authState.username) {
    return <window.LoginScreen onLoggedIn={(name) => setAuthState({ checked: true, username: name, authRequired: true })} />;
  }

  if (route.kind === "home") {
    return <window.LiveMonitorHomepage />;
  }
  // Cutover 44: single project-creation page (start generation).
  if (route.kind === "new-project") {
    return <window.LiveMonitorNewProjectPage />;
  }
  // Host-wide persistent knowledge + skills browser/editor.
  if (route.kind === "knowledge") {
    return <window.LiveMonitorKnowledgePage />;
  }
  // Cutover 41: per-project routes now use ProjectShell (sidebar + per-section pages).
  if (route.kind === "project") {
    return <ProjectShellHost projectId={route.projectId} section={route.section || "overview"}
                              subResource={route.subResource} subResourceId={route.subResourceId} />;
  }
  return <window.LiveMonitorHomepage />;
}

// Cutover 41: Thin host that owns the monitor state subscription and forwards
// state / error / lastUpdated to <window.ProjectShell>. Preserves the existing
// useMonitorState wiring so SSE / polling behavior is unchanged.
function ProjectShellHost({ projectId, section, subResource, subResourceId }) {
  const { state, error, lastUpdated } = useMonitorState(projectId);
  return (
    <window.ProjectShell
      projectId={projectId}
      section={section}
      subResource={subResource}
      subResourceId={subResourceId}
      state={state}
      error={error}
      lastUpdated={lastUpdated}
    />
  );
}

function ProjectMonitor({ projectId }) {
  const { state, error, lastUpdated } = useMonitorState(projectId);
  const [selectedAgent, setSelectedAgent] = useState("");
  const [leftCollapsed, setLeftCollapsed] = useState(false);
  const [centerCollapsed, setCenterCollapsed] = useState(false);
  const [rightCollapsed, setRightCollapsed] = useState(true);
  const [layout, setLayout] = useState(readLayout);
  const [viewportWidth, setViewportWidth] = useState(readViewportWidth);
  const dragRef = useRef(null);
  const effectiveLeftWidth = leftCollapsed ? LEFT_COLLAPSED_WIDTH : layout.left;
  const effectiveRightWidth = rightCollapsed ? RIGHT_COLLAPSED_WIDTH : layout.right;
  const splitMinLeft = leftCollapsed ? LEFT_COLLAPSED_WIDTH : 140;
  const splitMinRight = rightCollapsed ? RIGHT_COLLAPSED_WIDTH : 180;
  const defaultSplit = Math.max(splitMinLeft, (viewportWidth - CENTER_COLLAPSED_WIDTH - HANDLE_WIDTH_TOTAL) / 2);
  const centerSplitLeft = centerCollapsed
    ? leftCollapsed
      ? LEFT_COLLAPSED_WIDTH
      : rightCollapsed
        ? Math.max(splitMinLeft, viewportWidth - CENTER_COLLAPSED_WIDTH - HANDLE_WIDTH_TOTAL - RIGHT_COLLAPSED_WIDTH)
        : clamp(layout.split || defaultSplit, splitMinLeft, viewportWidth - CENTER_COLLAPSED_WIDTH - HANDLE_WIDTH_TOTAL - splitMinRight)
    : null;

  useEffect(() => {
    localStorage.setItem(LAYOUT_KEY, JSON.stringify(layout));
  }, [layout]);

  useEffect(() => {
    function onResize() {
      setViewportWidth(readViewportWidth());
    }
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);

  useEffect(() => {
    function onPointerMove(event) {
      const drag = dragRef.current;
      if (!drag) return;
      event.preventDefault();
      if (drag.side === "left") {
        if (drag.centerCollapsed) {
          const nextSplit = clamp(
            drag.startSplit + event.clientX - drag.startX,
            drag.splitMinLeft,
            drag.viewportWidth - CENTER_COLLAPSED_WIDTH - HANDLE_WIDTH_TOTAL - drag.splitMinRight,
          );
          setLayout((current) => ({ ...current, split: nextSplit }));
          return;
        }
        const maxLeft = Math.max(140, drag.viewportWidth - HANDLE_WIDTH_TOTAL - drag.effectiveRightWidth - CENTER_MIN_WIDTH);
        const nextLeft = drag.startLeft + event.clientX - drag.startX;
        setLayout((current) => ({ ...current, left: clamp(nextLeft, 140, maxLeft) }));
      } else {
        if (drag.centerCollapsed) {
          const nextSplit = clamp(
            drag.startSplit + event.clientX - drag.startX,
            drag.splitMinLeft,
            drag.viewportWidth - CENTER_COLLAPSED_WIDTH - HANDLE_WIDTH_TOTAL - drag.splitMinRight,
          );
          setLayout((current) => ({ ...current, split: nextSplit }));
          return;
        }
        const nextRight = drag.startRight - (event.clientX - drag.startX);
        const maxRight = Math.max(180, drag.viewportWidth - HANDLE_WIDTH_TOTAL - drag.effectiveLeftWidth - CENTER_MIN_WIDTH);
        setLayout((current) => ({ ...current, right: clamp(nextRight, 180, maxRight) }));
      }
    }

    function onPointerUp() {
      if (!dragRef.current) return;
      dragRef.current = null;
      document.body.classList.remove("resizing-layout");
    }

    window.addEventListener("pointermove", onPointerMove);
    window.addEventListener("pointerup", onPointerUp);
    window.addEventListener("pointercancel", onPointerUp);
    return () => {
      window.removeEventListener("pointermove", onPointerMove);
      window.removeEventListener("pointerup", onPointerUp);
      window.removeEventListener("pointercancel", onPointerUp);
    };
  }, [layout.left, layout.right, layout.split, leftCollapsed, rightCollapsed, centerCollapsed, viewportWidth]);

  function startResize(side, event) {
    event.preventDefault();
    if (side === "left" && leftCollapsed) {
      setLeftCollapsed(false);
    }
    if (side === "right" && rightCollapsed) {
      setRightCollapsed(false);
    }
    dragRef.current = {
      side,
      startX: event.clientX,
      startLeft: layout.left,
      startRight: layout.right,
      startSplit: centerSplitLeft ?? layout.split ?? defaultSplit,
      centerCollapsed,
      splitMinLeft,
      splitMinRight,
      viewportWidth,
      effectiveLeftWidth,
      effectiveRightWidth,
    };
    document.body.classList.add("resizing-layout");
  }

  return (
    <div
      className={[
        "v0-page",
        leftCollapsed && "left-collapsed",
        centerCollapsed && "center-collapsed",
        rightCollapsed && "right-collapsed",
      ].filter(Boolean).join(" ")}
      style={{
        "--left-panel-width": `${layout.left}px`,
        "--right-panel-width": `${layout.right}px`,
        "--center-split-left": `${centerSplitLeft ?? defaultSplit}px`,
      }}
    >
      <Sidebar
        state={state}
        selectedAgent={selectedAgent}
        onSelectAgent={setSelectedAgent}
        collapsed={leftCollapsed}
        onToggleCollapsed={() => setLeftCollapsed((value) => !value)}
      />
      <button
        type="button"
        className="layout-resize-handle left"
        onPointerDown={(event) => startResize("left", event)}
        title="Drag to resize left panel"
        aria-label="Resize left panel"
      />
      {centerCollapsed ? (
        <button
          type="button"
          className="v0-center-collapsed"
          onClick={() => setCenterCollapsed(false)}
          title="Expand center panel"
        >
          <strong>›</strong>
          <span>Main</span>
        </button>
      ) : (
        <div className="v0-center-shell">
          <button
            type="button"
            className="center-collapse-toggle"
            onClick={() => setCenterCollapsed(true)}
            title="Collapse center panel"
          >
            <strong>‹›</strong>
            <span>Hide main</span>
          </button>
          <Center state={state} selectedAgent={selectedAgent} onSelectAgent={setSelectedAgent} lastUpdated={lastUpdated} error={error} />
        </div>
      )}
      <button
        type="button"
        className="layout-resize-handle right"
        onPointerDown={(event) => startResize("right", event)}
        title="Drag to resize right panel"
        aria-label="Resize right panel"
      />
      <Inspector state={state} collapsed={rightCollapsed} onToggleCollapsed={() => setRightCollapsed((value) => !value)} />
    </div>
  );
}

ReactDOM.createRoot(document.getElementById("root")).render(<MonitorApp />);
