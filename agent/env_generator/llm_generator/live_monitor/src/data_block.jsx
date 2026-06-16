// Shared data renderers — replace raw JSON dumps with readable UI.
//   PrettyData  : object/array → humanized key/value rows (recursive).
//   DataBlock   : collapsible card (default collapsed) wrapping PrettyData,
//                 with a "{} raw" toggle for the underlying JSON.
//   ParamChips  : compact inline key·value chips for small flat objects.
// Exposed as window.EnvGenData. Styled with the current design tokens.
const { useState } = window.React;

function humanizeKey(k) {
  return String(k)
    .replace(/[_\-]+/g, " ")
    .replace(/([a-z0-9])([A-Z])/g, "$1 $2")
    .replace(/\s+/g, " ")
    .trim()
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

function DataValue({ v }) {
  if (v === null || v === undefined || v === "") return <span className="text-fg-muted italic">—</span>;
  if (typeof v === "boolean") return <span className="font-medium" style={{ color: v ? "var(--success)" : "var(--danger)" }}>{v ? "yes" : "no"}</span>;
  if (typeof v === "number") return <span className="font-mono text-info">{v}</span>;
  const s = String(v);
  const looksCode = /[\/{}<>:]/.test(s) || s.startsWith("$");
  return <span className={"break-words " + (looksCode ? "font-mono text-fg-secondary" : "text-fg")}>{s}</span>;
}

// One row. Primitive → inline "label: value" (value wraps freely). Object/array
// → a collapsible disclosure (chevron + label + count) so deep/long content never
// squishes; nested levels start collapsed.
function DataRow({ label, value, depth }) {
  const complex = value && typeof value === "object";
  const [open, setOpen] = useState(depth < 1);
  if (!complex) {
    return (
      <div className="flex items-baseline gap-2 leading-snug">
        {label != null && <span className="text-2xs text-fg-muted shrink-0">{label}</span>}
        <span className="text-sm min-w-0 break-words"><DataValue v={value} /></span>
      </div>
    );
  }
  const n = Array.isArray(value) ? value.length : Object.keys(value).length;
  if (n === 0) {
    return (
      <div className="flex items-baseline gap-2 leading-snug">
        {label != null && <span className="text-2xs text-fg-muted shrink-0">{label}</span>}
        <span className="text-sm text-fg-muted italic">{Array.isArray(value) ? "empty list" : "empty"}</span>
      </div>
    );
  }
  return (
    <div>
      <button onClick={() => setOpen(o => !o)} className="flex items-center gap-1.5 text-2xs text-fg-muted hover:text-fg transition-colors">
        <span style={{ transform: open ? "rotate(90deg)" : "none", display: "inline-block", transition: "transform 120ms" }}>▶</span>
        <span className="font-medium">{label != null ? label : (Array.isArray(value) ? "List" : "Object")}</span>
        <span className="opacity-70">{Array.isArray(value) ? `${n} items` : `${n} fields`}</span>
      </button>
      {open && (
        <div className="pl-3 ml-1 mt-1 border-l border-border-subtle">
          <PrettyData data={value} depth={depth + 1} />
        </div>
      )}
    </div>
  );
}

function PrettyData({ data, depth = 0 }) {
  if (data === null || typeof data !== "object") return <DataValue v={data} />;
  if (Array.isArray(data)) {
    if (!data.length) return <span className="text-fg-muted italic text-sm">empty</span>;
    return (
      <div className="space-y-1.5">
        {data.slice(0, 50).map((it, i) => <DataRow key={i} label={`#${i + 1}`} value={it} depth={depth} />)}
        {data.length > 50 && <div className="text-2xs text-fg-muted">+{data.length - 50} more items</div>}
      </div>
    );
  }
  const entries = Object.entries(data);
  if (!entries.length) return <span className="text-fg-muted italic text-sm">empty</span>;
  return (
    <div className="space-y-1.5">
      {entries.slice(0, 80).map(([k, v]) => <DataRow key={k} label={humanizeKey(k)} value={v} depth={depth} />)}
      {entries.length > 80 && <div className="text-2xs text-fg-muted">+{entries.length - 80} more fields</div>}
    </div>
  );
}

function ParamChips({ params }) {
  const entries = Object.entries(params || {});
  if (!entries.length) return null;
  return (
    <span className="inline-flex flex-wrap items-center gap-x-2.5 gap-y-1 align-middle">
      {entries.map(([k, v]) => (
        <span key={k} className="inline-flex items-center gap-1 text-2xs">
          <span className="text-fg-muted">{humanizeKey(k)}</span>
          <code className="font-mono text-fg-secondary bg-bg-tertiary px-1.5 py-0.5 rounded">{String(v)}</code>
        </span>
      ))}
    </span>
  );
}

function DataBlock({ label, data, summary, defaultOpen = false, accent }) {
  const [open, setOpen] = useState(!!defaultOpen);
  const [raw, setRaw] = useState(false);
  const count = data && typeof data === "object"
    ? (Array.isArray(data) ? `${data.length} items` : `${Object.keys(data).length} fields`)
    : null;
  return (
    <div className="border border-border rounded-md overflow-hidden bg-bg-elevated">
      <button onClick={() => setOpen((o) => !o)}
              className="w-full flex items-center gap-2 px-3 py-2 hover:bg-bg-hover transition-colors text-left">
        <span className="text-fg-muted text-2xs"
              style={{ transform: open ? "rotate(90deg)" : "none", display: "inline-block", transition: "transform 120ms" }}>▶</span>
        <span className="text-sm font-medium text-fg flex-1 truncate">{label}</span>
        <span className="text-2xs text-fg-muted">{summary || count}</span>
      </button>
      {open && (
        <div className="px-3 pb-3 pt-2 border-t border-border-subtle">
          <div className="flex justify-end mb-2">
            <button onClick={() => setRaw((r) => !r)} className="text-2xs text-fg-muted hover:text-accent transition-colors">
              {raw ? "← pretty view" : "{ } raw"}
            </button>
          </div>
          {raw
            ? <pre className="text-xs font-mono bg-bg-tertiary rounded-md p-2.5 overflow-x-auto whitespace-pre-wrap break-words" style={{ maxHeight: 360 }}>{JSON.stringify(data, null, 2)}</pre>
            : <PrettyData data={data} />}
        </div>
      )}
    </div>
  );
}

window.EnvGenData = { humanizeKey, PrettyData, ParamChips, DataBlock };
