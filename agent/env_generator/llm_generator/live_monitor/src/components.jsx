const {
  classNames,
  formatPayload,
  formatStatus,
  summarizeValue,
  valueEntries,
} = window.MonitorUtils;

window.MonitorComponents = (() => {
  function StatusBadge({ status }) {
    return (
      <div className={classNames("status-badge", status)}>
        <span className="status-dot" />
        {formatStatus(status)}
      </div>
    );
  }

  function PayloadValue({ value }) {
    if (value === null || value === undefined || value === "") {
      return <span className="payload-empty">(empty)</span>;
    }

    if (Array.isArray(value) && value.length && value.every((item) => ["string", "number", "boolean"].includes(typeof item))) {
      return (
        <div className="payload-chip-row">
          {value.map((item, index) => (
            <span key={`${item}-${index}`} className="payload-chip mono">
              {String(item)}
            </span>
          ))}
        </div>
      );
    }

    if (typeof value === "string") {
      if (value.includes("\n") || value.length > 96) {
        const parsed = parseJsonLike(value);
        if (parsed.ok) {
          return <StructuredValue value={parsed.value} depth={0} />;
        }
        return <div className="payload-text-block">{value}</div>;
      }
      return <div className="payload-inline">{value}</div>;
    }

    if (typeof value === "object") {
      return <StructuredValue value={value} depth={0} />;
    }

    return <div className="payload-inline mono">{String(value)}</div>;
  }

  function parseJsonLike(value) {
    if (typeof value !== "string") return { ok: false, value };
    const trimmed = value.trim();
    if (!trimmed || !/^[\[{]/.test(trimmed)) return { ok: false, value };
    try {
      return { ok: true, value: JSON.parse(trimmed) };
    } catch (err) {
      const normalized = normalizePythonLiteral(trimmed);
      if (normalized) {
        try {
          return { ok: true, value: JSON.parse(normalized) };
        } catch (innerErr) {
          return { ok: false, value };
        }
      }
      return { ok: false, value };
    }
  }

  function normalizePythonLiteral(value) {
    if (!/[\{,]\s*'[^']+'\s*:/.test(value)) return "";
    return value
      .replace(/\bNone\b/g, "null")
      .replace(/\bTrue\b/g, "true")
      .replace(/\bFalse\b/g, "false")
      .replace(/'([^'\\]*(?:\\.[^'\\]*)*)'/g, (_, content) => JSON.stringify(content.replace(/\\'/g, "'")));
  }

  function StructuredValue({ value, depth = 0 }) {
    if (value === null || value === undefined || value === "") {
      return <span className="payload-empty">(empty)</span>;
    }
    if (typeof value !== "object") {
      return <ValueBadge value={value} />;
    }
    if (depth >= 2) {
      return <CompactStructuredValue value={value} />;
    }
    if (Array.isArray(value)) {
      if (!value.length) return <span className="payload-empty">Empty list</span>;
      return (
        <div className={classNames("structured-list", depth > 0 && "nested")}>
          {value.slice(0, 12).map((item, index) => (
            <div key={index} className="structured-list-item">
              <span className="structured-index">{index + 1}</span>
              <StructuredValue value={item} depth={depth + 1} />
            </div>
          ))}
          {value.length > 12 ? <div className="structured-more">+{value.length - 12} more items</div> : null}
        </div>
      );
    }

    const entries = Object.entries(value);
    if (!entries.length) return <span className="payload-empty">Empty object</span>;
    return (
      <div className={classNames("structured-object", depth > 0 && "nested")}>
        {entries.slice(0, 18).map(([key, item]) => (
          <div key={key} className="structured-field">
            <div className="structured-key">{humanizeKey(key)}</div>
            <div className="structured-value">
              <StructuredValue value={item} depth={depth + 1} />
            </div>
          </div>
        ))}
        {entries.length > 18 ? <div className="structured-more">+{entries.length - 18} more fields</div> : null}
      </div>
    );
  }

  function CompactStructuredValue({ value }) {
    const isArray = Array.isArray(value);
    const entries = isArray ? value : Object.entries(value || {});
    const count = entries.length;
    return (
      <div className="compact-structured">
        <div className="compact-structured-head">
          <span>{isArray ? "List" : "Object"}</span>
          <em>{count} {isArray ? "items" : "fields"}</em>
        </div>
        {isArray ? <CompactArray value={value} /> : <CompactObject value={value} />}
        <details className="compact-raw-details">
          <summary>Formatted JSON</summary>
          <pre className="compact-json mono">{stringifyCompact(value)}</pre>
        </details>
      </div>
    );
  }

  function CompactObject({ value }) {
    const entries = Object.entries(value || {});
    if (!entries.length) return <span className="payload-empty">Empty object</span>;
    return (
      <div className="compact-fields">
        {entries.slice(0, 8).map(([key, item]) => (
          <div key={key} className="compact-field">
            <span className="compact-key">{humanizeKey(key)}</span>
            <div className="compact-value">
              {Array.isArray(item) ? <CompactArray value={item} /> : compactValue(item)}
            </div>
          </div>
        ))}
        {entries.length > 8 ? <div className="structured-more">+{entries.length - 8} more fields</div> : null}
      </div>
    );
  }

  function CompactArray({ value }) {
    if (!value.length) return <span className="payload-empty">Empty list</span>;
    return (
      <div className="compact-array">
        {value.slice(0, 8).map((item, index) => (
          <div key={index} className="compact-array-item">
            <span className="structured-index">{index + 1}</span>
            <div className="compact-array-body">
              {item && typeof item === "object" && !Array.isArray(item) ? <CompactObject value={item} /> : compactValue(item)}
            </div>
          </div>
        ))}
        {value.length > 8 ? <div className="structured-more">+{value.length - 8} more items</div> : null}
      </div>
    );
  }

  function compactValue(value) {
    if (value === null || value === undefined || value === "") {
      return <span className="payload-empty">(empty)</span>;
    }
    if (Array.isArray(value)) {
      return <CompactArray value={value} />;
    }
    if (typeof value === "object") {
      const entries = Object.entries(value);
      if (!entries.length) return <span className="payload-empty">Empty object</span>;
      return (
        <div className="compact-chip-grid">
          {entries.slice(0, 4).map(([key, item]) => (
            <span key={key} className="compact-chip">
              <strong>{humanizeKey(key)}</strong>
              {summarizeCompact(item)}
            </span>
          ))}
          {entries.length > 4 ? <span className="compact-chip muted">+{entries.length - 4}</span> : null}
        </div>
      );
    }
    return <ValueBadge value={value} />;
  }

  function summarizeCompact(value) {
    if (value === null || value === undefined || value === "") return "(empty)";
    if (Array.isArray(value)) return `List ${value.length}`;
    if (typeof value === "object") return `Object ${Object.keys(value).length}`;
    return String(value);
  }

  function stringifyCompact(value) {
    try {
      return JSON.stringify(value, null, 2);
    } catch (err) {
      return String(value);
    }
  }

  function ValueBadge({ value }) {
    const type = typeof value;
    return <span className={classNames("value-badge", type)}>{String(value)}</span>;
  }

  function humanizeKey(key) {
    return String(key || "")
      .replace(/[_-]+/g, " ")
      .replace(/([a-z])([A-Z])/g, "$1 $2")
      .replace(/\b\w/g, (char) => char.toUpperCase());
  }

  function PayloadBlock({ title, value, fallback }) {
    const displayValue = value ?? fallback;
    const entries = valueEntries(value);

    return (
      <section className="tool-detail-card">
        <div className="tool-detail-head">
          <div className="eyebrow">{title}</div>
          <span className="pill subtle">{summarizeValue(displayValue)}</span>
        </div>
        {entries.length ? (
          <div className="payload-grid">
            {entries.map(([key, item]) => (
              <div key={key} className="payload-row">
                <div className="payload-key mono">{key}</div>
                <div className="payload-value">
                  <PayloadValue value={item} />
                </div>
              </div>
            ))}
          </div>
        ) : (
          <PayloadValue value={displayValue} />
        )}
      </section>
    );
  }

  function FileReadResult({ result }) {
    if (!result || typeof result !== "object") {
      return <PayloadValue value={result} />;
    }
    const content = String(result.content || "");
    const lines = content.split("\n").filter((line) => line.length > 0);
    return (
      <div className="file-read-card">
        <div className="file-read-head">
          <div>
            <div className="eyebrow">Read File</div>
            <strong>{result.file_path || "unknown file"}</strong>
          </div>
          <div className="file-read-stats">
            <span>{result.total_lines ?? lines.length} lines</span>
            <span>offset {result.offset ?? 1}</span>
            <span>limit {result.limit ?? "all"}</span>
          </div>
        </div>
        <div className="file-read-content">
          {lines.slice(0, 80).map((line, index) => {
            const match = /^(\d+):(.*)$/.exec(line);
            return (
              <div key={index} className="file-read-line">
                <span>{match ? match[1] : index + 1}</span>
                <code>{match ? match[2] : line}</code>
              </div>
            );
          })}
          {lines.length > 80 ? <div className="structured-more">+{lines.length - 80} more lines</div> : null}
        </div>
      </div>
    );
  }

  return { FileReadResult, PayloadBlock, PayloadValue, StatusBadge, StructuredValue, parseJsonLike };
})();
