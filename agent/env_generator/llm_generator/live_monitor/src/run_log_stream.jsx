window.RunLogStream = (function () {
  const { useState, useEffect, useRef } = React;

  function RunLogStream({ runId, onClose }) {
    const [lines, setLines] = useState("");
    const [finished, setFinished] = useState(false);
    const [returncode, setReturncode] = useState(null);
    const [error, setError] = useState("");
    const preRef = useRef(null);
    const followRef = useRef(true);  // auto-scroll while user is at the bottom

    useEffect(() => {
      if (!runId) return undefined;
      let es = null, reconnectTimer = null, backoffMs = 500, closed = false;

      function open() {
        if (closed) return;
        try {
          es = new EventSource(`/api/runs/${encodeURIComponent(runId)}/log/stream`, { withCredentials: true });
        } catch (e) {
          setError(String(e));
          return;
        }
        es.onopen = () => { backoffMs = 500; };
        es.onmessage = (e) => {
          try {
            const event = JSON.parse(e.data);
            if (event._end) {
              setFinished(true);
              setReturncode(event.returncode);
              if (es) { try { es.close(); } catch (_) {} es = null; }
              return;
            }
            if (event.chunk) {
              setLines(prev => prev + event.chunk);
            }
          } catch (_) {}
        };
        es.onerror = () => {
          if (es) { try { es.close(); } catch (_) {} es = null; }
          if (closed || finished) return;
          reconnectTimer = window.setTimeout(open, backoffMs);
          backoffMs = Math.min(backoffMs * 2, 30000);
        };
      }
      open();

      return () => {
        closed = true;
        if (reconnectTimer) window.clearTimeout(reconnectTimer);
        if (es) { try { es.close(); } catch (_) {} }
      };
    }, [runId]);

    // Auto-scroll to bottom whenever new content arrives (unless user scrolled up)
    useEffect(() => {
      const el = preRef.current;
      if (el && followRef.current) {
        el.scrollTop = el.scrollHeight;
      }
    }, [lines]);

    function onScroll() {
      const el = preRef.current;
      if (!el) return;
      const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 40;
      followRef.current = atBottom;
    }

    return (
      <div className="run-log-modal-backdrop" onClick={(e) => {
        if (e.target === e.currentTarget) onClose?.();
      }}>
        <div className="run-log-modal">
          <div className="run-log-header">
            <span className="run-log-title">Run {runId}</span>
            <span className={"run-log-state state-" + (finished ? (returncode === 0 ? "ok" : "fail") : "running")}>
              {finished
                ? (returncode === 0 ? "Completed" : `Failed (rc=${returncode})`)
                : "Running…"}
            </span>
            <button className="run-log-close" onClick={() => onClose?.()}>Close</button>
          </div>
          {error && <div className="run-log-error">{error}</div>}
          <pre ref={preRef} onScroll={onScroll} className="run-log-pre">{lines || "(waiting for output…)"}</pre>
        </div>
      </div>
    );
  }

  return RunLogStream;
})();
