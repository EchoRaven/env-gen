window.MonitorApi = (() => {
  const { useEffect, useState } = React;

  function useMonitorState(projectId) {
    const [state, setState] = useState(null);
    const [error, setError] = useState("");
    const [lastUpdated, setLastUpdated] = useState("");

    useEffect(() => {
      let alive = true;

      async function load() {
        try {
          // Cutover 28: if a projectId is supplied (workspaces-root mode), use the
          // per-project endpoint; otherwise fall back to the legacy single-project endpoint.
          const url = projectId
            ? `/api/projects/${encodeURIComponent(projectId)}/state`
            : "/api/state";
          const response = await fetch(url, { cache: "no-store", credentials: "include" });
          if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
          }
          const payload = await response.json();
          if (!alive) return;
          setState(payload);
          setError("");
          setLastUpdated(new Date().toLocaleTimeString());
        } catch (err) {
          if (!alive) return;
          setError(err.message || String(err));
        }
      }

      load();
      // Cutover 30: expose immediate-refresh hook for mutation forms to call after a POST.
      window.LiveMonitorRefresh = load;

      // Cutover 31: dynamic polling — fast (1.8s) while SSE is disconnected, slow
      // (30s) fallback once SSE is connected. Re-evaluates on every tick.
      let pollMs = 1800;
      function pickInterval() {
        return window.MonitorSSE && window.MonitorSSE.isConnected() ? 30000 : 1800;
      }
      let timer = window.setInterval(function tick() {
        load();
        const next = pickInterval();
        if (next !== pollMs) {
          window.clearInterval(timer);
          pollMs = next;
          timer = window.setInterval(tick, pollMs);
        }
      }, pollMs);

      // Cutover 31: open one EventSource per projectId. Any event triggers an
      // immediate refetch of state. Reconnect with exponential backoff on error.
      let sseCleanup = null;
      if (projectId) {
        const url = `/api/projects/${encodeURIComponent(projectId)}/events`;
        let es = null;
        let reconnectTimer = null;
        let backoffMs = 500;
        let closed = false;

        function open() {
          if (closed) return;
          try { es = new EventSource(url); } catch (e) { return; }
          es.onopen = () => { backoffMs = 500; };
          es.onmessage = () => { if (alive) load(); };
          es.onerror = () => {
            if (es) { try { es.close(); } catch (_) {} es = null; }
            if (closed) return;
            reconnectTimer = window.setTimeout(open, backoffMs);
            backoffMs = Math.min(backoffMs * 2, 30000);
          };
        }
        open();
        sseCleanup = () => {
          closed = true;
          if (reconnectTimer) window.clearTimeout(reconnectTimer);
          if (es) { try { es.close(); } catch (_) {} }
        };
      }

      return () => {
        alive = false;
        if (window.LiveMonitorRefresh === load) {
          window.LiveMonitorRefresh = null;
        }
        window.clearInterval(timer);
        if (sseCleanup) sseCleanup();
      };
    }, [projectId]);

    return { state, error, lastUpdated };
  }

  return { useMonitorState };
})();
