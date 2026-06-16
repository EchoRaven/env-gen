const { useState, useEffect, useRef, useMemo } = window.React;

// Cutover 43.28: ChatPanel — Gemini-style. Centered single conversation column,
// user messages as soft pills on the right, agent replies as plain text on the
// left with a small role glyph, big rounded composer pinned at the bottom.
function ChatPanel({ projectId }) {
  const [conversations, setConversations] = useState([]);
  const [activeThread, setActiveThread] = useState(null);
  const [messages, setMessages] = useState([]);
  const [draft, setDraft] = useState("");
  const [composing, setComposing] = useState(true);     // new-conversation mode (default)
  const [selectedAgents, setSelectedAgents] = useState([]);
  const [knownAgents, setKnownAgents] = useState([]);
  const [error, setError] = useState(null);
  const [sending, setSending] = useState(false);
  const [railOpen, setRailOpen] = useState(true);
  const [mention, setMention] = useState(null);   // { query } when typing "@…"
  // "Agent is thinking…" indicators, keyed by agent_id. Set when the user sends
  // a message, cleared when that agent's reply arrives (or after a timeout).
  // Live `currentTask` / `focusHub` come from the SSE agent_status stream so
  // the indicator can show what the agent is actually doing right now.
  const [typingAgents, setTypingAgents] = useState({});
  // Live tool-call steps emitted by the chat mini-loop while an agent is
  // replying. Keyed by thread_id → array of {agent, tool, args_preview,
  // status, result_preview, ts}. Cleared on agent_reply (so the dots
  // collapse into the final reply) and on thread switch.
  const [chatSteps, setChatSteps] = useState({});
  const endRef = useRef(null);
  const taRef = useRef(null);
  const Icons = window.Icons || {};

  useEffect(() => {
    if (!projectId) return;
    let alive = true;
    (async () => {
      try {
        const r = await fetch(`/api/projects/${projectId}/agents`, { credentials: "include" });
        const data = await r.json();
        if (!alive) return;
        const isWorker = (id) => id === "worker" || /(^|_)worker(_|$)/i.test(id);
        setKnownAgents((data.agents || []).map(a => a.id).filter(id => !isWorker(id)));
      } catch (_) {}
    })();
    return () => { alive = false; };
  }, [projectId]);

  async function refreshConversations() {
    if (!projectId) return;
    try {
      const r = await fetch(`/api/projects/${projectId}/conversations`, { credentials: "include" });
      const data = await r.json();
      setConversations((data.conversations || []).filter(c => c.status !== "resolved")); setError(null);
    } catch (e) { setError(String(e)); }
  }
  async function refreshMessages(tid) {
    if (!projectId || !tid) return;
    try {
      const r = await fetch(`/api/projects/${projectId}/conversations/${tid}/messages`, { credentials: "include" });
      const data = await r.json();
      setMessages(data.messages || []);
      setTimeout(() => endRef.current?.scrollIntoView({ behavior: "smooth" }), 60);
    } catch (e) { setError(String(e)); }
  }
  useEffect(() => { refreshConversations(); const p = setInterval(refreshConversations, 30000); return () => clearInterval(p); }, [projectId]);
  useEffect(() => { if (!activeThread) return; refreshMessages(activeThread); const p = setInterval(() => refreshMessages(activeThread), 30000); return () => clearInterval(p); }, [activeThread, projectId]);
  window.MonitorSSE && window.MonitorSSE.useSSE(projectId, (event) => {
    const t = event && event.event_type;
    if (t === "human_message" || t === "agent_reply") {
      refreshConversations();
      if (activeThread && event.thread_id === activeThread) refreshMessages(activeThread);
      // Reply from an agent we were waiting on → clear its typing
      // indicator AND its accumulated tool-call steps (the steps were
      // the "what they were doing while typing"; the reply replaces them).
      if (t === "agent_reply") {
        const replyFrom = (event.payload || {}).reply_from || event.source_hub;
        if (replyFrom) setTypingAgents(p => { if (!p[replyFrom]) return p; const n = { ...p }; delete n[replyFrom]; return n; });
        const tid = event.thread_id;
        if (tid) setChatSteps(prev => { if (!prev[tid]) return prev; const n = { ...prev }; delete n[tid]; return n; });
      }
    }
    // Live tool-call step from the chat mini-loop → append under the agent's
    // pending typing indicator so the user sees what's being done.
    if (t === "agent_chat_step") {
      const p = event.payload || {};
      const tid = event.thread_id;
      if (!tid || !p.agent) return;
      // Three filters before we accept the event into state:
      //   1. The thread must be the one the user is currently looking at
      //      (no point storing steps for a background thread — the user
      //      can't see them, and accumulation across threads would leak
      //      indefinitely).
      //   2. The emitting agent must be one we're actively waiting on
      //      (in typingAgents). Otherwise the step is for some other
      //      agent-to-agent chat we don't care about rendering.
      //   3. Per-thread cap (CHAT_STEP_CAP) — defends against a crashed
      //      mini-loop that emits forever without a reply.
      if (tid !== activeThread) return;
      if (!typingAgents[p.agent]) return;
      const CHAT_STEP_CAP = 50;
      setChatSteps(prev => {
        const list = prev[tid] || [];
        const next = list.concat([{
          agent: p.agent,
          tool: p.tool,
          args_preview: p.args_preview || "",
          status: p.status || "done",
          result_preview: p.result_preview || "",
          ts: event.created_at || Date.now() / 1000,
        }]);
        const trimmed = next.length > CHAT_STEP_CAP ? next.slice(-CHAT_STEP_CAP) : next;
        return { ...prev, [tid]: trimmed };
      });
    }
    // Live status updates → show what the agent is currently doing.
    if (t === "agent_status") {
      const p = event.payload || {};
      const aid = p.agent_id;
      if (!aid) return;
      setTypingAgents(prev => {
        if (!prev[aid]) return prev;   // only track agents we're waiting on
        return {
          ...prev,
          [aid]: { ...prev[aid], status: p.status, currentTask: p.current_task, focusHub: p.focus_hub, lastSeen: Date.now() / 1000 },
        };
      });
    }
  });

  // Expire stale typing indicators (in case a reply event was missed).
  useEffect(() => {
    if (Object.keys(typingAgents).length === 0) return;
    const t = setInterval(() => {
      const now = Date.now() / 1000;
      setTypingAgents(prev => {
        let changed = false;
        const next = { ...prev };
        for (const [aid, info] of Object.entries(prev)) {
          if (now - (info.sentAt || 0) > 300) { delete next[aid]; changed = true; }   // 5 min cap
        }
        return changed ? next : prev;
      });
    }, 5000);
    return () => clearInterval(t);
  }, [typingAgents]);
  // Clear indicators when switching threads.
  useEffect(() => { setTypingAgents({}); setChatSteps({}); }, [activeThread]);

  // auto-grow textarea
  useEffect(() => { const ta = taRef.current; if (!ta) return; ta.style.height = "auto"; ta.style.height = Math.min(ta.scrollHeight, 200) + "px"; }, [draft]);

  async function startNew() {
    if (!draft.trim() || selectedAgents.length === 0 || sending) return;
    setSending(true);
    try {
      const r = await fetch(`/api/projects/${projectId}/conversations`, {
        method: "POST", headers: { "Content-Type": "application/json" }, credentials: "include",
        body: JSON.stringify({ target_agents: selectedAgents, text: draft }),
      });
      const data = await r.json();
      if (data.error) { setError(data.error); return; }
      // Optimistic typing indicators for every target agent.
      const now = Date.now() / 1000;
      setTypingAgents(p => { const n = { ...p }; selectedAgents.forEach(a => { n[a] = { sentAt: now, status: "thinking…" }; }); return n; });
      setDraft(""); setComposing(false); setSelectedAgents([]);
      await refreshConversations(); setActiveThread(data.thread_id);
    } catch (e) { setError(String(e)); } finally { setSending(false); }
  }
  // parse "@agent" mentions in the draft that match this thread's participants
  function parseMentions(text, participants) {
    const found = [];
    const re = /@([A-Za-z0-9_]+)/g; let m;
    while ((m = re.exec(text)) !== null) { if (participants.includes(m[1]) && !found.includes(m[1])) found.push(m[1]); }
    return found;
  }
  async function sendInThread() {
    if (!draft.trim() || !activeThread || sending) return;
    setSending(true);
    try {
      const parts = (conversations.find(c => c.thread_id === activeThread)?.participants || []).filter(p => p !== "human_user");
      const mentions = parseMentions(draft, parts);
      const body = { text: draft };
      if (mentions.length > 0 && mentions.length < parts.length) body.target_agents = mentions; // directed
      const r = await fetch(`/api/projects/${projectId}/conversations/${activeThread}/messages`, {
        method: "POST", headers: { "Content-Type": "application/json" }, credentials: "include",
        body: JSON.stringify(body),
      });
      const data = await r.json();
      if (data.error) { setError(data.error); return; }
      // Optimistic typing indicators for the agents we just messaged.
      const targets = (mentions.length > 0 && mentions.length < parts.length) ? mentions : parts;
      const now = Date.now() / 1000;
      setTypingAgents(p => { const n = { ...p }; targets.forEach(a => { n[a] = { sentAt: now, status: "thinking…" }; }); return n; });
      setDraft(""); setMention(null); await refreshMessages(activeThread);
    } catch (e) { setError(String(e)); } finally { setSending(false); }
  }
  function newConversation() {
    // Full reset so no prior transcript/draft/mention lingers behind the hero.
    setActiveThread(null); setComposing(true); setSelectedAgents([]);
    setDraft(""); setMessages([]); setMention(null); setError(null);
  }
  async function deleteConversation(tid, e) {
    if (e) e.stopPropagation();
    try { await fetch(`/api/projects/${projectId}/conversations/${encodeURIComponent(tid)}`, { method: "DELETE", credentials: "include" }); } catch (_) {}
    if (activeThread === tid) newConversation();
    refreshConversations();
  }
  function toggleAgent(n) { setSelectedAgents(p => p.includes(n) ? p.filter(a => a !== n) : [...p, n]); }

  function fmtRel(ts) {
    if (!ts) return "";
    const d = Date.now() / 1000 - ts;
    if (d < 60) return "just now";
    if (d < 3600) return Math.floor(d / 60) + "m";
    if (d < 86400) return Math.floor(d / 3600) + "h";
    return new Date(ts * 1000).toLocaleDateString(undefined, { month: "short", day: "numeric" });
  }
  function AgentGlyph({ name, size = 30 }) {
    const Ico = window.AgentIcons?.iconFor(name) || Icons.user;
    const grad = window.AgentIcons?.gradient(name) || "linear-gradient(135deg,#6366f1,#3b82f6)";
    return (
      <span className="inline-flex items-center justify-center text-white shrink-0 rounded-full"
            style={{ width: size, height: size, background: grad, boxShadow: "0 1px 3px rgba(0,0,0,0.12)" }}>
        {Ico ? <Ico size={Math.floor(size * 0.52)} /> : null}
      </span>
    );
  }

  const canSend = draft.trim() && !sending && (composing ? selectedAgents.length > 0 : !!activeThread);
  const activeConv = conversations.find(c => c.thread_id === activeThread);
  const activeAgents = (activeConv?.participants || []).filter(p => p !== "human_user");

  // Slack-style @mention: "@" (at word start) opens the participant list; keep
  // typing to filter; ↑/↓ to move; Enter/Tab to pick.
  const MENTION_RE = /(^|\s)@([A-Za-z0-9_]*)$/;
  const mentionCands = useMemo(() => {
    if (composing || !mention) return [];
    const q = (mention.query || "").toLowerCase();
    return activeAgents.filter(a => a.toLowerCase().includes(q));
  }, [composing, mention, activeAgents]);
  function pickMention(a) {
    if (!a) return;
    const v = draft.replace(MENTION_RE, (_m, pre) => pre + "@" + a + " ");
    setDraft(v); setMention(null);
    setTimeout(() => taRef.current?.focus(), 0);
  }
  function onDraftChange(v) {
    setDraft(v);
    if (composing) return;
    const m = v.match(MENTION_RE);
    setMention(m ? { query: m[2], index: 0 } : null);
  }
  function onComposerKeyDown(e) {
    // Skip ALL Enter handling while an IME is composing (Chinese/Japanese/
    // Korean pinyin etc. — the user is pressing Enter to confirm a candidate,
    // not to send). Both checks: `isComposing` is the standard property;
    // keyCode 229 is the legacy fallback some browsers set during composition.
    const composingIME = e.isComposing || (e.nativeEvent && e.nativeEvent.isComposing) || e.keyCode === 229;
    if (!composing && mention && mentionCands.length > 0) {
      if (e.key === "ArrowDown") { e.preventDefault(); setMention(x => ({ ...x, index: Math.min((x.index || 0) + 1, mentionCands.length - 1) })); return; }
      if (e.key === "ArrowUp")   { e.preventDefault(); setMention(x => ({ ...x, index: Math.max((x.index || 0) - 1, 0) })); return; }
      if ((e.key === "Enter" || e.key === "Tab") && !composingIME) { e.preventDefault(); pickMention(mentionCands[mention.index || 0]); return; }
      if (e.key === "Escape")    { e.preventDefault(); setMention(null); return; }
    }
    if (e.key === "Escape") { setMention(null); return; }
    if (e.key === "Enter" && !e.shiftKey && !composingIME) { e.preventDefault(); composing ? startNew() : sendInThread(); }
  }

  // ---- Composer (shared by empty + thread states) ----
  const Composer = (
    <div className="w-full max-w-[760px] mx-auto">
      {composing && knownAgents.length > 0 && (
        <div className="flex flex-wrap items-center gap-1.5 mb-3 justify-center">
          <span className="text-2xs text-fg-muted mr-1">To:</span>
          {knownAgents.map(a => {
            const on = selectedAgents.includes(a);
            return (
              <button key={a} onClick={() => toggleAgent(a)}
                      className={"inline-flex items-center gap-1.5 pl-1 pr-2.5 h-7 rounded-full text-xs transition-all border " +
                                 (on ? "bg-accent-soft text-accent-on-soft border-accent" : "bg-bg-elevated text-fg-secondary border-border hover:border-border-strong")}>
                <AgentGlyph name={a} size={18} />{a}
              </button>
            );
          })}
        </div>
      )}
      {/* @mention autocomplete (thread mode) — Slack-style */}
      {!composing && mention && mentionCands.length > 0 && (
        <div className="mb-2 bg-bg-elevated border border-border rounded-xl overflow-hidden" style={{ boxShadow: "0 8px 24px rgba(0,0,0,0.12)" }}>
          <div className="px-3 py-1.5 text-2xs uppercase tracking-wider font-medium text-fg-muted border-b border-border flex items-center justify-between">
            <span>Send only to…</span><span className="text-fg-muted/60 normal-case tracking-normal">↑↓ to move · Enter to pick</span>
          </div>
          <ul className="py-1 max-h-56 overflow-y-auto">
            {mentionCands.map((a, i) => {
              const hl = (mention.index || 0) === i;
              return (
                <li key={a}>
                  <button onMouseDown={(e) => { e.preventDefault(); pickMention(a); }}
                          onMouseEnter={() => setMention(x => ({ ...x, index: i }))}
                          className={"w-full text-left px-3 py-1.5 flex items-center gap-2 text-sm transition-colors " + (hl ? "bg-accent-soft text-accent-on-soft" : "text-fg-secondary hover:bg-bg-hover")}>
                    <AgentGlyph name={a} size={18} /> <span className={hl ? "font-medium text-accent-on-soft" : "font-medium text-fg"}>{a}</span>
                  </button>
                </li>
              );
            })}
          </ul>
        </div>
      )}
      <div className="flex items-end gap-2 bg-bg-elevated border border-border rounded-[26px] px-4 py-2.5 transition-all focus-within:border-border-strong"
           style={{ boxShadow: "0 1px 3px rgba(0,0,0,0.05), 0 6px 20px rgba(0,0,0,0.04)" }}>
        <textarea ref={taRef} value={draft} rows={1}
                  onChange={e => onDraftChange(e.target.value)}
                  onKeyDown={onComposerKeyDown}
                  placeholder={composing ? "Message the agents…" : "Reply…  (type @ to message one agent)"}
                  className="bare flex-1 text-md leading-relaxed resize-none py-1.5 max-h-[200px]" style={{ minHeight: 24 }} />
        <button onClick={() => composing ? startNew() : sendInThread()} disabled={!canSend}
                title="Send (Enter)"
                className="shrink-0 grid place-items-center w-9 h-9 rounded-full transition-all disabled:opacity-40 disabled:cursor-not-allowed active:scale-95"
                style={{ background: canSend ? "var(--accent)" : "var(--bg-tertiary)", color: canSend ? "var(--text-on-accent)" : "var(--text-muted)" }}>
          {/* symmetric upward arrow, centered in a 24×24 box */}
          <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor"
               strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" style={{ display: "block" }}>
            <path d="M12 19V6" />
            <path d="M6 12l6-6 6 6" />
          </svg>
        </button>
      </div>
      <div className="text-2xs text-fg-muted text-center mt-2">Human messages route at top priority to every chosen agent's inbox · Enter to send</div>
    </div>
  );

  return (
    <div className="flex gap-0" style={{ height: "calc(100vh - 150px)", minHeight: 520 }}>
      {/* ===== History rail ===== */}
      <div className={"shrink-0 transition-all overflow-hidden flex flex-col " + (railOpen ? "w-[248px]" : "w-[52px]")}>
        <div className="flex items-center gap-1 pl-0.5 pr-2 pb-3">
          <button onClick={() => setRailOpen(o => !o)} className="btn-icon shrink-0" title={railOpen ? "Collapse" : "Expand"}>
            {Icons.chevronLeft ? <span style={{ transform: railOpen ? "" : "rotate(180deg)", display: "inline-flex" }}><Icons.chevronLeft size={16} /></span> : "≡"}
          </button>
          {railOpen && (
            <button onClick={newConversation} className="btn-px btn-px-ghost btn-px-sm flex-1 justify-start gap-1.5">
              {Icons.plus && <Icons.plus size={13} />} New chat
            </button>
          )}
        </div>
        {railOpen && (
          <div className="flex-1 overflow-y-auto px-2 space-y-0.5">
            <div className="px-2 pb-1 text-2xs uppercase tracking-wider font-medium text-fg-muted">Recent</div>
            {conversations.length === 0 && <div className="px-2 py-2 text-xs text-fg-muted">No conversations.</div>}
            {conversations.map(c => {
              const sel = activeThread === c.thread_id && !composing;
              const others = (c.participants || []).filter(p => p !== "human_user");
              return (
                <div key={c.thread_id}
                     onClick={() => { setActiveThread(c.thread_id); setComposing(false); }}
                     className={"group/conv w-full px-2.5 py-2 rounded-full transition-colors flex items-center gap-2 cursor-pointer " + (sel ? "bg-accent-soft" : "hover:bg-bg-hover")}>
                  {Icons.chat && <span className={sel ? "text-accent-on-soft shrink-0" : "text-fg-muted shrink-0"}><Icons.chat size={13} /></span>}
                  <span className={"text-sm truncate flex-1 " + (sel ? "text-accent-on-soft font-medium" : "text-fg-secondary")}>{others.join(", ") || "conversation"}</span>
                  <button onClick={(e) => deleteConversation(c.thread_id, e)} title="Delete conversation"
                          className="shrink-0 opacity-0 group-hover/conv:opacity-100 transition-opacity text-fg-muted hover:text-danger leading-none px-0.5">×</button>
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* ===== Conversation column ===== */}
      <div className="flex-1 min-w-0 flex flex-col bg-bg-elevated border border-border rounded-2xl overflow-hidden">
        {error && <div className="px-4 py-2 bg-danger-soft text-danger text-sm flex items-center justify-between shrink-0"><span>{error}</span><button onClick={() => setError(null)}>×</button></div>}

        {/* header for active thread */}
        {!composing && activeThread && (
          <header className="px-6 h-12 flex items-center gap-2 shrink-0 border-b border-border-subtle">
            <div className="flex -space-x-1.5">{activeAgents.slice(0, 4).map(a => <AgentGlyph key={a} name={a} size={20} />)}</div>
            <span className="text-md font-semibold text-fg">{activeAgents.join(", ") || "Conversation"}</span>
          </header>
        )}

        {/* transcript / empty */}
        <div className="flex-1 overflow-y-auto">
          {(composing && messages.length === 0) || (!composing && !activeThread) ? (
            <div className="h-full flex flex-col items-center justify-center px-6">
              <div className="w-full max-w-[760px] text-center mb-8">
                <div className="inline-flex items-center justify-center w-12 h-12 rounded-2xl mb-4"
                     style={{ background: "linear-gradient(135deg, var(--accent), color-mix(in srgb, var(--accent) 60%, #3b82f6))", color: "#fff" }}>
                  {Icons.chat ? <Icons.chat size={24} /> : "✦"}
                </div>
                <h1 className="text-3xl font-semibold tracking-tight"
                    style={{ background: "linear-gradient(95deg, var(--accent), color-mix(in srgb, var(--accent) 55%, #3b82f6))", WebkitBackgroundClip: "text", WebkitTextFillColor: "transparent", backgroundClip: "text" }}>How can the agents help?</h1>
                <p className="text-sm text-fg-muted mt-2">Pick the agents to message, type below, and send.</p>
              </div>
              {Composer}
            </div>
          ) : (
            <div className="px-6 py-8">
              <div className="max-w-[760px] mx-auto space-y-8">
                {messages.map(m => {
                  const human = m.source === "human_user";
                  if (human) {
                    const directed = Array.isArray(m.to) && m.to.length > 0 && m.to.length < activeAgents.length;
                    return (
                      <div key={m.message_id} className="flex flex-col items-end">
                        {directed && (
                          <div className="flex items-center gap-1 mb-1 mr-1 text-2xs text-fg-muted">
                            <span>directed to</span>
                            {m.to.map(a => <span key={a} className="px-1.5 py-0.5 rounded-full bg-accent-soft text-accent-on-soft font-medium">@{a}</span>)}
                          </div>
                        )}
                        <div className="max-w-[80%] px-5 py-2.5 rounded-[20px] text-md leading-relaxed whitespace-pre-wrap break-words bg-bg-tertiary text-fg">{m.text}</div>
                      </div>
                    );
                  }
                  return (
                    <div key={m.message_id} className="flex gap-4">
                      <AgentGlyph name={m.source} size={30} />
                      <div className="flex-1 min-w-0 pt-0.5">
                        <div className="flex items-center gap-2 mb-1">
                          <span className="text-sm font-semibold text-fg">{m.source}</span>
                          <span className="text-2xs text-fg-muted">{fmtRel(m.created_at)}</span>
                        </div>
                        <div className="text-md text-fg-secondary leading-relaxed whitespace-pre-wrap break-words">{m.text}</div>
                      </div>
                    </div>
                  );
                })}
                {/* Live "<agent> is thinking…" indicators for any agent we're
                    waiting on a reply from. The status text updates as agent_status
                    events arrive (e.g. "writing", "focus: workhub", etc.).
                    Below the dots: real-time tool-call list from the chat
                    mini-loop so the user sees what's actually happening. */}
                {Object.entries(typingAgents).map(([aid, info]) => {
                  const sub = info.currentTask
                    ? `${info.status || "working"} · ${info.currentTask}${info.focusHub ? ` @ ${info.focusHub}` : ""}`
                    : (info.status || "thinking…");
                  const steps = (chatSteps[activeThread] || []).filter(s => s.agent === aid);
                  return (
                    <div key={`typing-${aid}`} className="flex gap-4 items-start">
                      <AgentGlyph name={aid} size={30} />
                      <div className="flex-1 min-w-0 pt-0.5">
                        <div className="flex items-center gap-2 mb-1">
                          <span className="text-sm font-semibold text-fg">{aid}</span>
                          <span className="text-2xs text-fg-muted">{sub}</span>
                        </div>
                        <div className="typing-dots"><span className="dot" /><span className="dot" /><span className="dot" /></div>
                        {steps.length > 0 && (
                          <ul className="chat-steps">
                            {steps.map((s, i) => (
                              <li key={`step-${aid}-${i}`} className={`chat-step chat-step--${s.status}`}>
                                <code className="chat-step__tool">{s.tool}</code>
                                {s.args_preview && (
                                  <span className="chat-step__args">({s.args_preview})</span>
                                )}
                                {s.result_preview && (
                                  <span className="chat-step__result">→ {s.result_preview}</span>
                                )}
                              </li>
                            ))}
                          </ul>
                        )}
                      </div>
                    </div>
                  );
                })}
                <div ref={endRef} />
              </div>
            </div>
          )}
        </div>

        {/* composer pinned (when in a thread or composing-with-messages) */}
        {((!composing && activeThread) || (composing && messages.length > 0)) && (
          <div className="px-6 py-4 shrink-0 border-t border-border-subtle">{Composer}</div>
        )}
      </div>
    </div>
  );
}

window.LiveMonitorChatPanel = ChatPanel;
