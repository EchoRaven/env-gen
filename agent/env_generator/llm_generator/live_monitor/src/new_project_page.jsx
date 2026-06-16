// Cutover 43.3 / 44: "Start generation" page — generation-config only (no empty
// workspace mode). Sections: Required identity, LLM configuration (two-way
// model↔provider sync + typeable model combobox), References, and Delivery gates
// (buffered locally, persisted via /user_gates after the run is created).
const { useState, useRef, useEffect } = window.React;

// ---- Model catalog: which provider serves each known model ----
// Ordered newest / most capable first within each provider (the combobox
// renders suggestions in this order). Free-text entry is still allowed for
// models not listed here.
const MODEL_CATALOG = [
  // OpenAI (gpt-5.x family + 4.1)
  { model: "gpt-5.5", provider: "openai" },
  { model: "gpt-5.5-pro", provider: "openai" },
  { model: "gpt-5.4", provider: "openai" },
  { model: "gpt-5.4-pro", provider: "openai" },
  { model: "gpt-5.4-mini", provider: "openai" },
  { model: "gpt-5.4-nano", provider: "openai" },
  { model: "gpt-5.3", provider: "openai" },
  { model: "gpt-5.2", provider: "openai" },
  { model: "gpt-5.2-pro", provider: "openai" },
  { model: "gpt-5.1", provider: "openai" },
  { model: "gpt-5", provider: "openai" },
  { model: "gpt-5-pro", provider: "openai" },
  { model: "gpt-5-mini", provider: "openai" },
  { model: "gpt-5-nano", provider: "openai" },
  { model: "gpt-4.1", provider: "openai" },
  // Anthropic (Claude 4.x)
  { model: "claude-opus-4-7", provider: "anthropic" },
  { model: "claude-opus-4-6", provider: "anthropic" },
  { model: "claude-sonnet-4-6", provider: "anthropic" },
  { model: "claude-opus-4-5", provider: "anthropic" },
  { model: "claude-sonnet-4-5", provider: "anthropic" },
  { model: "claude-haiku-4-5", provider: "anthropic" },
  { model: "claude-haiku-3-5", provider: "anthropic" },
  // Google (Gemini 3.x / 2.5)
  { model: "gemini-3.5-flash", provider: "google" },
  { model: "gemini-3.1-pro", provider: "google" },
  { model: "gemini-3.1-flash-lite", provider: "google" },
  { model: "gemini-2.5-pro", provider: "google" },
  { model: "gemini-2.5-flash", provider: "google" },
  { model: "gemini-2.5-flash-lite", provider: "google" },
  // OpenRouter (vendor/model slugs — any slug works, these are popular picks)
  { model: "anthropic/claude-opus-4-7", provider: "openrouter" },
  { model: "anthropic/claude-sonnet-4-6", provider: "openrouter" },
  { model: "openai/gpt-5.5", provider: "openrouter" },
  { model: "openai/gpt-5.4", provider: "openrouter" },
  { model: "google/gemini-3.5-flash", provider: "openrouter" },
  { model: "google/gemini-3.1-pro", provider: "openrouter" },
  { model: "openai/gpt-oss-120b", provider: "openrouter" },
  { model: "deepseek/deepseek-v3", provider: "openrouter" },
  { model: "meta-llama/llama-3.3-70b-instruct", provider: "openrouter" },
  { model: "x-ai/grok-4", provider: "openrouter" },
];
// openai/google/anthropic/openrouter have curated catalogs; azure & local use
// free-form deployment/model names. Placeholders fall back for those two.
const PROVIDERS = ["openai", "google", "anthropic", "openrouter", "azure", "local"];
// Only these clouds are auto-inferred from a bare model name (e.g. "gpt-…").
// openrouter slugs ("openai/…") and azure/local names must not flip the provider.
const INFERABLE_PROVIDERS = new Set(["openai", "google", "anthropic"]);
const PROVIDER_ENV = {
  openai: "OPENAI_API_KEY",
  google: "GEMINI_API_KEY",
  anthropic: "ANTHROPIC_API_KEY",
  openrouter: "OPENROUTER_API_KEY",
  azure: "AZURE_OPENAI_API_KEY",
  local: null,
};
const PROVIDER_PLACEHOLDER = { azure: "deployment-name", local: "model name" };

// Infer the provider from a (possibly partial) model string. Returns null when
// the model is unknown / ambiguous, so callers can leave the provider untouched.
function inferProvider(model) {
  const m = (model || "").trim().toLowerCase();
  if (!m) return null;
  const exact = MODEL_CATALOG.find((x) => x.model.toLowerCase() === m);
  if (exact) return exact.provider;
  if (/^(gpt|o1|o3|o4|text-|davinci)/.test(m)) return "openai";
  if (m.startsWith("gemini")) return "google";
  if (m.startsWith("claude")) return "anthropic";
  return null;
}
// Placeholder for the model field: the provider's top catalog model, or a
// free-form hint for providers without a catalog (azure/local).
function modelPlaceholder(prov) {
  const m = MODEL_CATALOG.find((x) => x.provider === prov);
  return m ? m.model : (PROVIDER_PLACEHOLDER[prov] || "model name");
}

// Reference categories — mirrors the in-project References page (REF_CAT).
const REF_META = {
  image: { label: "Image", icon: "palette", color: "var(--accent-on-soft)", bg: "var(--accent-soft)" },
  spec: { label: "Spec", icon: "api", color: "var(--info)", bg: "var(--info-soft)" },
  doc: { label: "Doc", icon: "file", color: "var(--fg)", bg: "var(--bg-tertiary)" },
  data: { label: "Data", icon: "database", color: "var(--warning)", bg: "var(--warning-soft)" },
  code: { label: "Code", icon: "code", color: "var(--success)", bg: "var(--success-soft)" },
  other: { label: "File", icon: "file", color: "var(--text-muted)", bg: "var(--bg-tertiary)" },
};
function refCategory(name) {
  const n = (name || "").toLowerCase();
  if (/\.(png|jpe?g|webp|gif|svg|bmp)$/.test(n)) return "image";
  if (/\.(json|ya?ml|toml)$/.test(n)) return "spec";
  if (/\.(md|txt|rst|pdf|docx?)$/.test(n)) return "doc";
  if (/\.(csv|tsv|db|sqlite|sql|parquet)$/.test(n)) return "data";
  if (/\.(py|js|ts|jsx|tsx|go|rs|java|rb)$/.test(n)) return "code";
  return "other";
}
function fmtSize(n) {
  if (n == null) return "";
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

// Delivery-gate logic (types, validation, parsing, the rows editor) lives in the
// shared window.EnvGenGates module (gate_editor.jsx) so this page and the
// in-project Gates page stay in lockstep — new gate types appear in both
// automatically. Do NOT re-implement gate helpers here.

function NewProjectPage() {
  const Icons = window.Icons || {};
  const { theme, toggle: toggleTheme } = window.MonitorTheme.useTheme();

  const [owner] = useState("envforger");
  const [name, setName] = useState("");
  const [projectId, setProjectId] = useState("");
  const [description, setDescription] = useState("");
  const [model, setModel] = useState("");
  const [provider, setProvider] = useState("openai");
  const [apiKey, setApiKey] = useState("");
  // Run budget caps — the orchestrator fails the run deterministically past these;
  // adjustable live from the project Overview afterwards.
  const [maxWallMin, setMaxWallMin] = useState("120");
  const [maxTicks, setMaxTicks] = useState("240");

  // Reference files staged locally, uploaded to /references after creation.
  const [refs, setRefs] = useState([]); // { filename, category, size, dataUrl, b64 }
  const [refDrag, setRefDrag] = useState(false);
  const [refError, setRefError] = useState("");
  const refInputRef = useRef(null);

  // Delivery gates as repeatable rows (CodeHub-inline-comment style). Each row
  // is { type, params }; the shared GateRowsEditor owns add/remove/bulk-paste,
  // and rows are validated + persisted on submit. Invalid/empty rows are
  // skipped so they never block creation.
  const [gateRows, setGateRows] = useState([]);

  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);

  const nav = (p) => window.LiveMonitorRouter.navigateTo(p);

  const suggestedId = name.trim().toLowerCase().replace(/[^a-z0-9-]+/g, "-").replace(/^-+|-+$/g, "");
  const effectiveId = (projectId.trim() || suggestedId).slice(0, 64);

  // ---- two-way model ↔ provider sync ----
  function onModelChange(next) {
    setModel(next);
    const inferred = inferProvider(next);
    if (inferred && INFERABLE_PROVIDERS.has(provider)) setProvider(inferred);
  }
  function onProviderChange(next) {
    setProvider(next);
    // Providers with a catalog (openai/google/anthropic/openrouter): if the
    // current model isn't one of theirs, clear it so the placeholder + full
    // list show. azure/local have no catalog → keep whatever was typed.
    const hasCatalog = MODEL_CATALOG.some((x) => x.provider === next);
    if (!hasCatalog) return;
    const belongs = MODEL_CATALOG.some((x) => x.provider === next && x.model === model);
    if (!belongs) setModel("");
  }

  // ---- reference staging ----
  function stageFiles(fileList) {
    const list = Array.from(fileList || []);
    if (!list.length) return;
    setRefError("");
    for (const file of list) {
      if (file.size > 10 * 1024 * 1024) { setRefError(`${file.name} exceeds the 10MB cap`); continue; }
      const reader = new FileReader();
      reader.onload = (ev) => {
        const dataUrl = ev.target.result || "";
        const b64 = String(dataUrl).split(",")[1] || "";
        setRefs((rs) => rs.some((r) => r.filename === file.name)
          ? rs
          : [...rs, { filename: file.name, category: refCategory(file.name), size: file.size, dataUrl, b64 }]);
      };
      reader.readAsDataURL(file);
    }
  }
  function removeRef(name) { setRefs((rs) => rs.filter((r) => r.filename !== name)); }

  // Valid, normalized, auto-named gates to persist (incomplete rows skipped),
  // via the shared collector so behavior matches the in-project Gates page.
  function collectGates() {
    return window.EnvGenGates ? window.EnvGenGates.collectGates(gateRows) : [];
  }

  async function submit() {
    if (!name.trim()) { setError("Project name is required."); return; }
    if (!description.trim()) { setError("A generation prompt is required — describe in detail what to build."); return; }
    setError(""); setPending(true);
    try {
      const r = await fetch("/api/runs", {
        method: "POST", headers: { "Content-Type": "application/json" }, credentials: "include",
        body: JSON.stringify({
          name, description, model, provider, api_key: apiKey.trim(),
          max_wall_sec: Math.max(60, Math.round((Number(maxWallMin) || 120) * 60)),
          max_ticks: Math.max(1, Math.round(Number(maxTicks) || 240)),
        }),
      });
      const data = await r.json();
      if (data.error) { setError(data.error); setPending(false); return; }
      const pid = data.project_id;
      // Upload staged reference files into the freshly-created workspace.
      if (pid && refs.length) {
        for (const f of refs) {
          try {
            await fetch(`/api/projects/${encodeURIComponent(pid)}/references`, {
              method: "POST", headers: { "Content-Type": "application/json" }, credentials: "include",
              body: JSON.stringify({ filename: f.filename, content_base64: f.b64 }),
            });
          } catch (e) { /* visible later on the References page */ }
        }
      }
      // Persist delivery gates to the freshly-created workspace (best effort —
      // a gate failure should not block entering the project).
      const gatesToCreate = collectGates();
      if (pid && gatesToCreate.length) {
        for (const g of gatesToCreate) {
          try {
            await fetch(`/api/projects/${encodeURIComponent(pid)}/user_gates`, {
              method: "POST", headers: { "Content-Type": "application/json" }, credentials: "include",
              body: JSON.stringify(g),
            });
          } catch (e) { /* surfaced later on the project's Gates page */ }
        }
      }
      nav(`/projects/${encodeURIComponent(pid)}/overview`);
    } catch (e) { setError(String(e)); }
    finally { setPending(false); }
  }

  const apiKeyEnv = PROVIDER_ENV[provider];

  return (
    <div className="min-h-screen flex flex-col bg-bg-secondary">
      {/* Clean topbar — brand only, theme toggle on right */}
      <header className="h-12 px-6 flex items-center justify-between border-b border-border bg-bg sticky top-0 z-10">
        <button onClick={() => nav("/")} className="flex items-center gap-2 group">
          <span className="w-2.5 h-2.5 rounded-full bg-accent ring-2 ring-accent/20 transition-transform group-hover:scale-110" />
          <span className="text-md font-semibold tracking-tight text-fg">
            env<span className="text-accent">forger</span>
          </span>
        </button>
        <button onClick={toggleTheme} className="btn-icon" title={theme === "dark" ? "Light mode" : "Dark mode"}>
          {theme === "dark"
            ? (Icons.sun ? <Icons.sun size={14} /> : "☀")
            : (Icons.moon ? <Icons.moon size={14} /> : "☾")}
        </button>
      </header>

      <div className="max-w-[920px] w-full mx-auto px-6 py-8">
        {/* Breadcrumb */}
        <nav className="flex items-center gap-1.5 text-sm text-fg-secondary mb-3">
          <button onClick={() => nav("/")} className="hover:text-accent transition-colors">Projects</button>
          <span className="text-fg-muted">{Icons.chevronRight ? <Icons.chevronRight size={12} /> : "/"}</span>
          <span className="text-fg font-medium">Start generation</span>
        </nav>

        {/* Hero */}
        <div className="mb-6">
          <h1 className="text-3xl font-semibold tracking-tight mb-2 text-fg">Start a generation</h1>
          <p className="text-md text-fg-secondary leading-relaxed max-w-prose">
            Configure the workspace, the model that drives the agents, optional reference files, and the
            delivery gates that must pass before the project can ship. Starting will spawn the multi-agent
            orchestrator subprocess immediately.
          </p>
        </div>

        {error && (
          <div className="mb-5 flex items-start gap-2 px-3 py-2.5 rounded-md bg-danger-soft text-danger text-base border border-danger/30">
            <span className="shrink-0 leading-none mt-0.5">⚠</span>
            <span>{error}</span>
          </div>
        )}

        {/* ============ Section cards ============ */}
        <div className="space-y-4">
          <SectionCard title="Required" subtitle="The project name and the generation prompt. The prompt is the detailed brief every agent works from — it drives the entire build.">
            <Field label="Owner / Project name" required>
              <div className="flex items-center gap-2">
                <div className="field-prefix">{owner}</div>
                <span className="text-fg-muted text-lg shrink-0">/</span>
                <input value={name} onChange={(e) => setName(e.target.value)} placeholder="my-todo-app" autoFocus className="input-px flex-1" />
              </div>
              <FieldHint>
                Short and memorable.{" "}
                {name && (<>URL will be <code className="font-mono text-2xs bg-bg-tertiary px-1 py-0.5 rounded">/projects/{effectiveId}</code></>)}
              </FieldHint>
            </Field>

            <Field label="Generation prompt" required>
              <textarea
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                placeholder={"Describe in detail what to build — this is the brief the agents work from.\n\nInclude:\n• Purpose & target users\n• Key pages / screens and what each shows\n• Core features and user flows\n• Main data entities (with important fields / relationships)\n• Roles & permissions, plus any specific behaviors or constraints\n\nThe more concrete the detail, the closer the result."}
                rows={10}
                className="input-px textarea-px leading-relaxed" />
              <FieldHint>
                Required. This drives the whole generation — a detailed spec yields a far better app than a one-liner.
              </FieldHint>
            </Field>

            <Field label="Project ID" hint="Auto-generated from the name; override only if you need a specific URL slug.">
              <input value={projectId} onChange={(e) => setProjectId(e.target.value)} placeholder={suggestedId || "auto"} className="input-px font-mono" />
            </Field>
          </SectionCard>

          <SectionCard title="LLM configuration" subtitle="Which model drives the agents. Provider is kept in sync with the model; the server reads the matching API-key env var.">
            <div className="grid grid-cols-2 gap-4">
              <Field label="Model" required>
                <ModelCombobox value={model} onChange={onModelChange} provider={provider} placeholder={modelPlaceholder(provider)} />
                <FieldHint>Type any model or pick from the list. Choosing a model auto-selects its provider.</FieldHint>
              </Field>
              <Field label="Provider" required>
                {/* Custom dropdown with an input-styled trigger (36px) so it
                    matches the model input exactly and is not clipped. */}
                <Select value={provider} onChange={onProviderChange}
                        options={PROVIDERS.map((p) => ({ value: p, label: p }))} />
                <FieldHint>Selecting a provider filters the model list.</FieldHint>
              </Field>
            </div>
            {apiKeyEnv ? (
              <Field label="API key">
                <input type="password" value={apiKey} onChange={(e) => setApiKey(e.target.value)}
                       placeholder={`Paste your ${provider} key, or leave blank to use ${apiKeyEnv}`}
                       autoComplete="off" spellCheck={false} className="input-px w-full font-mono" />
                <FieldHint>
                  Used only to launch this run and passed straight to the generator process —
                  never written to the project or logs. Leave blank to use{" "}
                  <code className="font-mono bg-bg-tertiary px-1 rounded text-2xs">{apiKeyEnv}</code> from the server.
                </FieldHint>
              </Field>
            ) : (
              <FieldHint className="mt-1">Uses a locally-hosted endpoint; no cloud API key required.</FieldHint>
            )}
          </SectionCard>

          <SectionCard title="Run budget" subtitle="Hard ceilings so a confused run fails fast instead of burning credits. You can raise these live from the project Overview while it runs.">
            <div className="grid grid-cols-2 gap-4">
              <Field label="Max wall-clock (minutes)">
                <input type="number" min="1" value={maxWallMin} onChange={(e) => setMaxWallMin(e.target.value)}
                       placeholder="120" className="input-px w-full font-mono" />
                <FieldHint>Total run time before the orchestrator aborts. Default 120 min.</FieldHint>
              </Field>
              <Field label="Max coordination ticks">
                <input type="number" min="1" value={maxTicks} onChange={(e) => setMaxTicks(e.target.value)}
                       placeholder="240" className="input-px w-full font-mono" />
                <FieldHint>Idle delivery-coordination ticks (~60s each) before abort. Default 240.</FieldHint>
              </Field>
            </div>
          </SectionCard>

          <SectionCard title="References" subtitle="Optional. Upload images, specs, docs, or data the design agents should follow. Images render as thumbnails; everything else is auto-indexed.">
            <input type="file" multiple ref={refInputRef} style={{ display: "none" }}
                   onChange={(e) => { stageFiles(e.target.files); e.target.value = ""; }} />
            {refError && <div className="mb-2 px-3 py-2 rounded-md bg-danger-soft text-danger text-sm">{refError}</div>}

            <div
              onClick={() => refInputRef.current?.click()}
              onDragOver={(e) => { e.preventDefault(); setRefDrag(true); }}
              onDragLeave={() => setRefDrag(false)}
              onDrop={(e) => { e.preventDefault(); setRefDrag(false); stageFiles(e.dataTransfer.files); }}
              className={"rounded-lg border-2 border-dashed px-4 py-7 text-center cursor-pointer transition-colors " +
                         (refDrag ? "border-accent bg-accent-soft/30" : "border-border hover:border-border-strong")}>
              <div className="flex items-center justify-center mb-1.5 text-fg-muted">
                {Icons.upload ? <Icons.upload size={18} /> : (Icons.plus ? <Icons.plus size={18} /> : "⬆")}
              </div>
              <div className="text-sm text-fg-secondary font-medium">Drop files or click to upload</div>
              <div className="text-xs text-fg-muted mt-0.5">Images, specs, docs, data — up to 10MB each.</div>
            </div>

            {refs.length > 0 && (
              <div className="grid grid-cols-2 gap-2 mt-3">
                {refs.map((f) => {
                  const meta = REF_META[f.category] || REF_META.other;
                  const I = Icons[meta.icon];
                  return (
                    <div key={f.filename} className="flex items-center gap-2.5 px-2.5 py-2 border border-border rounded-md bg-bg-elevated">
                      {f.category === "image" ? (
                        <img src={f.dataUrl} alt={f.filename}
                             className="w-9 h-9 rounded object-cover border border-border shrink-0" />
                      ) : (
                        <span className="inline-flex items-center justify-center w-9 h-9 rounded shrink-0"
                              style={{ background: meta.bg, color: meta.color }}>{I && <I size={15} />}</span>
                      )}
                      <div className="flex-1 min-w-0">
                        <div className="font-mono text-xs text-fg truncate">{f.filename}</div>
                        <div className="text-2xs text-fg-muted">{meta.label} · {fmtSize(f.size)}</div>
                      </div>
                      <button onClick={() => removeRef(f.filename)}
                              className="text-fg-muted hover:text-danger text-sm shrink-0 leading-none px-1">×</button>
                    </div>
                  );
                })}
              </div>
            )}
          </SectionCard>

          <SectionCard title="Delivery gates" subtitle="Optional. Typed checks that must pass before the project can be delivered. Add one row per check (pick a type, fill it, click + for the next), or paste a list to create many at once.">
            {window.EnvGenGates
              ? <window.EnvGenGates.GateRowsEditor rows={gateRows} setRows={setGateRows} />
              : <div className="text-sm text-fg-muted">Gate editor unavailable.</div>}
          </SectionCard>
        </div>

        {/* Footer */}
        <div className="mt-6 pt-5 border-t border-border flex justify-end gap-2.5">
          <button onClick={() => nav("/")} className="btn-px btn-px-ghost">Cancel</button>
          <button onClick={submit} disabled={pending || !name.trim() || !description.trim()} className="btn-px btn-px-primary">
            {pending ? "Working…" : (<>{Icons.play ? <Icons.play size={11} /> : "▶"} Create &amp; generate</>)}
          </button>
        </div>
      </div>
    </div>
  );
}

// ============ Shared anchored dropdown (portal — escapes card overflow) ============
// Both the model combobox and the provider select use this so their menus are
// not clipped by the SectionCard's `overflow-hidden`, and so they share one
// consistent custom look (no native <select>).
function useAnchoredMenu(triggerRef) {
  const [open, setOpen] = useState(false);
  const [rect, setRect] = useState(null);

  const reposition = () => {
    const r = triggerRef.current?.getBoundingClientRect();
    if (r) setRect({ left: r.left, top: r.bottom + 4, width: r.width });
  };
  const openMenu = () => { reposition(); setOpen(true); };
  const close = () => setOpen(false);

  useEffect(() => {
    if (!open) return;
    function onDoc(e) {
      if (triggerRef.current && triggerRef.current.contains(e.target)) return;
      if (e.target.closest && e.target.closest("[data-envgen-menu]")) return;
      setOpen(false);
    }
    // On scroll/resize, follow the trigger instead of closing — but ignore the
    // menu's OWN internal scroll (dragging its scrollbar) so it doesn't vanish.
    function onReflow(e) {
      if (e && e.target && e.target.closest && e.target.closest("[data-envgen-menu]")) return;
      reposition();
    }
    document.addEventListener("mousedown", onDoc);
    window.addEventListener("scroll", onReflow, true);
    window.addEventListener("resize", onReflow);
    return () => {
      document.removeEventListener("mousedown", onDoc);
      window.removeEventListener("scroll", onReflow, true);
      window.removeEventListener("resize", onReflow);
    };
  }, [open]);

  return { open, setOpen, rect, openMenu, close, reposition };
}

function AnchoredMenu({ rect, children }) {
  if (!rect) return null;
  return window.ReactDOM.createPortal(
    <div data-envgen-menu className="fixed z-[201] bg-bg-elevated border border-border rounded-lg py-1 max-h-72 overflow-y-auto"
         style={{ left: rect.left, top: rect.top, minWidth: rect.width, boxShadow: "0 8px 28px rgba(0,0,0,0.16)" }}>
      {children}
    </div>,
    document.body
  );
}

// ============ Model combobox (typeable + filtered suggestions) ============
function ModelCombobox({ value, onChange, provider, placeholder = "gpt-5.5" }) {
  const ref = useRef(null);
  const { open, setOpen, rect, openMenu, reposition } = useAnchoredMenu(ref);

  const q = (value || "").toLowerCase();
  const suggestions = MODEL_CATALOG
    .filter((x) => !provider || x.provider === provider)
    .filter((x) => !q || x.model.toLowerCase().includes(q));

  return (
    <div ref={ref}>
      <input
        value={value}
        onChange={(e) => { onChange(e.target.value); reposition(); setOpen(true); }}
        onFocus={openMenu}
        placeholder={placeholder}
        className="input-px w-full font-mono"
      />
      {open && suggestions.length > 0 && (
        <AnchoredMenu rect={rect}>
          {suggestions.map((s) => (
            <button
              type="button" key={s.model}
              onClick={() => { onChange(s.model); setOpen(false); }}
              className={"w-full text-left px-3 py-1.5 text-sm font-mono flex items-center justify-between hover:bg-bg-hover " +
                         (s.model === value ? "text-accent" : "text-fg")}>
              <span>{s.model}</span>
              <span className="text-2xs text-fg-muted ml-2">{s.provider}</span>
            </button>
          ))}
        </AnchoredMenu>
      )}
    </div>
  );
}

// ============ Generic custom select (input-styled trigger + portal menu) ============
// One control used for every dropdown on this page (provider, gate type, HTTP
// method) so they all share the input look: 36px height, 6px radius, 13px text,
// single border — no btn-ghost frame, no native <select>.
function Select({ value, onChange, options, placeholder = "Select…", className = "", style = {} }) {
  const ref = useRef(null);
  const { open, setOpen, rect, openMenu } = useAnchoredMenu(ref);
  const current = options.find((o) => o.value === value);
  return (
    <div ref={ref} className={className} style={style}>
      <button
        type="button"
        onClick={() => (open ? setOpen(false) : openMenu())}
        className="input-px w-full"
        style={{ display: "flex", alignItems: "center", justifyContent: "space-between", cursor: "pointer" }}>
        <span className={current ? "text-fg" : "text-fg-muted"}>{current ? current.label : placeholder}</span>
        <span className="text-fg-muted text-2xs ml-1.5">▾</span>
      </button>
      {open && (
        <AnchoredMenu rect={rect}>
          {options.map((o) => (
            <button
              type="button" key={String(o.value)}
              onClick={() => { onChange(o.value); setOpen(false); }}
              className={"w-full text-left px-3 py-1.5 flex items-center gap-2 text-sm " +
                         (o.value === value ? "bg-accent-soft text-accent-on-soft" : "text-fg-secondary hover:bg-bg-hover")}>
              <span className="w-3 shrink-0 text-accent">{o.value === value ? "✓" : ""}</span>
              <span className="truncate">{o.label}</span>
            </button>
          ))}
        </AnchoredMenu>
      )}
    </div>
  );
}

// ============ Section Card ============
function SectionCard({ title, subtitle, children }) {
  return (
    <section className="bg-bg-elevated border border-border rounded-lg overflow-hidden">
      <div className="grid grid-cols-[220px_1fr] gap-8 p-6">
        <div>
          <h2 className="text-md font-semibold tracking-tight text-fg mb-1">{title}</h2>
          {subtitle && <p className="text-sm text-fg-muted leading-snug">{subtitle}</p>}
        </div>
        <div className="space-y-4 min-w-0">{children}</div>
      </div>
    </section>
  );
}

function Field({ label, required, hint, children }) {
  return (
    <div>
      <label className="block text-sm font-medium text-fg mb-1.5">
        {label}{required && <span className="text-danger ml-0.5">*</span>}
      </label>
      {children}
      {hint && <FieldHint>{hint}</FieldHint>}
    </div>
  );
}

function FieldHint({ children, className = "" }) {
  return <div className={"text-xs text-fg-muted mt-1.5 leading-snug " + className}>{children}</div>;
}

window.LiveMonitorNewProjectPage = NewProjectPage;
