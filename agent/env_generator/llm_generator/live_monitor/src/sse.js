window.MonitorSSE = (() => {
  const { useEffect, useRef, useState } = React;
  const flags = { connected: false };

  function useSSE(projectId, onEvent) {
    const [connected, setConnected] = useState(false);
    const onEventRef = useRef(onEvent);
    onEventRef.current = onEvent;

    useEffect(() => {
      if (!projectId) return undefined;
      let es = null;
      let reconnectTimer = null;
      let backoffMs = 500;
      const BACKOFF_MAX = 30000;
      let closed = false;

      function open() {
        if (closed) return;
        const url = `/api/projects/${encodeURIComponent(projectId)}/events`;
        try { es = new EventSource(url); } catch (err) { return; }
        es.onopen = () => { backoffMs = 500; flags.connected = true; setConnected(true); };
        es.onmessage = (e) => {
          try {
            const event = JSON.parse(e.data);
            if (onEventRef.current) onEventRef.current(event);
          } catch (_) {}
        };
        es.onerror = () => {
          flags.connected = false; setConnected(false);
          if (es) { try { es.close(); } catch (_) {} es = null; }
          if (closed) return;
          reconnectTimer = window.setTimeout(open, backoffMs);
          backoffMs = Math.min(backoffMs * 2, BACKOFF_MAX);
        };
      }

      open();
      return () => {
        closed = true;
        if (reconnectTimer) window.clearTimeout(reconnectTimer);
        if (es) { try { es.close(); } catch (_) {} }
        flags.connected = false; setConnected(false);
      };
    }, [projectId]);

    return { connected };
  }

  return { useSSE, isConnected: () => flags.connected === true };
})();
