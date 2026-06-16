const { useMemo, useRef, useState } = React;
const {
  actionMeta,
  agentTone,
  classNames,
  formatPayload,
  languageForPath,
  mergeV0Events,
  toolMeta,
  truncateText,
} = window.MonitorUtils;
const { FileReadResult, PayloadBlock, StatusBadge, StructuredValue, parseJsonLike } = window.MonitorComponents;

window.MonitorViews = (() => {
  const AGENT_ORDER = ["orchestrator", "design", "database", "backend", "frontend", "verifier", "knowledge"];

  function normalizeAgentName(agent) {
    return String(agent || "").trim();
  }

  function agentDisplayName(agent) {
    return normalizeAgentName(agent).replace(/_/g, " ");
  }

  function agentLatestAction(agentId, workspace, state) {
    const history = workspace?.history || (state?.recentActivity || []).filter((item) => item.agent === agentId);
    const tools = workspace?.toolCalls || [];
    const latestTool = tools[tools.length - 1];
    const latestHistory = history[history.length - 1];
    if (latestTool) {
      const tool = String(latestTool.toolName || "").toLowerCase();
      if (/finish|deliver|complete/.test(tool)) return "finish";
      if (/wait|sleep|poll/.test(tool)) return "wait";
      if (/inbox|mail|message_box|check_inbox/.test(tool)) return "mail";
      if (/write|edit|patch|create|delete/.test(tool)) return "write";
      if (/read|search|query|fetch|glob/.test(tool)) return "read";
      if (/lint|test|verify|docker|browser|snapshot/.test(tool)) return "verify";
      if (/message|broadcast|agent|team/.test(tool)) return "message";
      if (/plan/.test(tool)) return "plan";
      return "execute";
    }
    const action = latestHistory?.actionType || "activity";
    const message = String(latestHistory?.message || "").toLowerCase();
    if (/finish|deliver|complete/.test(message)) return "finish";
    if (/wait|idle|sleep|blocked/.test(message)) return "wait";
    if (/inbox|mail|message box/.test(message) || action === "inbox") return "mail";
    return action;
  }

  function agentCards(state) {
    const core = state?.coreAgents || [];
    const known = new Set([...AGENT_ORDER, ...core.map((item) => item.agent)].filter(Boolean));
    return [...known].map((agentId) => {
      const workspace = state?.agentWorkspaces?.[agentId] || {};
      const coreInfo = core.find((item) => item.agent === agentId) || {};
      const history = workspace.history || (state?.recentActivity || []).filter((item) => item.agent === agentId);
      const toolCalls = workspace.toolCalls || (state?.toolCalls || []).filter((item) => item.agent === agentId || item.ownerAgent === agentId);
      const plan = workspace.plan || {};
      const mailbox = workspace.mailbox || {};
      const unread = mailbox.counts?.unread ?? (mailbox.inbox || []).filter((item) => item.read === false).length;
      const activeCount = history.slice(-20).filter((item) => item.actionType !== "error").length + toolCalls.slice(-20).length;
      const latest = history[history.length - 1] || toolCalls[toolCalls.length - 1] || {};
      return {
        id: agentId,
        status: coreInfo.status || "idle",
        events: coreInfo.events || history.length,
        historyCount: history.length,
        toolCount: toolCalls.length,
        planTasks: plan.totalTasks || 0,
        planDone: plan.completedTasks || 0,
        planPercent: plan.progressPercent || 0,
        unread,
        activeCount,
        latestSummary: latest.message || latest.toolName || "Waiting for activity",
        latestAction: agentLatestAction(agentId, workspace, state),
      };
    });
  }

  function actionLabel(action) {
    const labels = {
      write: "Writing code",
      read: "Reading context",
      verify: "Verifying build",
      mail: "Reading mail",
      wait: "Waiting",
      finish: "Finishing",
      message: "Routing messages",
      plan: "Planning work",
      execute: "Running tools",
      think: "Thinking",
      inbox: "Checking inbox",
      error: "Needs attention",
      activity: "Monitoring",
    };
    return labels[action] || "Active";
  }

  function Sidebar({ state, selectedAgent, onSelectAgent, collapsed, onToggleCollapsed }) {
    const agents = state?.coreAgents || [];
    return (
      <aside className={classNames("v0-sidebar", collapsed && "collapsed")}>
        <button type="button" className="sidebar-collapse-toggle" onClick={onToggleCollapsed} title={collapsed ? "Expand left panel" : "Collapse left panel"}>
          <span>{collapsed ? "Show" : "Hide"}</span>
          <strong>{collapsed ? "›" : "‹"}</strong>
        </button>
        <div className="v0-section-title">Agent Dock</div>
        <div className="v0-agent-list">
          <button
            type="button"
            className={classNames("v0-agent", !selectedAgent && "active")}
            onClick={() => onSelectAgent("")}
          >
            <span className="v0-agent-dot all" />
            <span>All agents</span>
            <em>{state?.recentActivity?.length || 0}</em>
          </button>
          {agents.map((agent) => (
            <button
              key={agent.agent}
              type="button"
              className={classNames("v0-agent", selectedAgent === agent.agent && "active")}
              onClick={() => onSelectAgent(selectedAgent === agent.agent ? "" : agent.agent)}
            >
              <span className={classNames("v0-agent-dot", agentTone(agent.agent), agent.status)} />
              <span>{agent.agent}</span>
              <em>{agent.events}</em>
            </button>
          ))}
        </div>

        <AllPlansPanel state={state} />

        <div className="v0-sidebar-footer">
          <div className="v0-muted">Spawned workers</div>
          <strong>{state?.spawnedAgents?.length || 0}</strong>
          <div className="v0-muted">Agent teams</div>
          <strong>{state?.agentTeams?.length || 0}</strong>
        </div>
      </aside>
    );
  }

  function PlanPanel({ plan, phases }) {
    const [openStages, setOpenStages] = useState({});
    const fallbackStages = phases.length
      ? phases.map((phase) => ({ id: phase.name, name: phase.name, status: phase.status, tasks: [], completedTasks: phase.status === "completed" ? 1 : 0, totalTasks: 1 }))
      : [{ id: "waiting", name: "Waiting for plan", status: "running", tasks: [], completedTasks: 0, totalTasks: 1 }];
    const stages = plan?.hasPlan ? plan.stages || [] : fallbackStages;
    const completed = plan?.hasPlan ? plan.completedTasks || 0 : fallbackStages.filter((stage) => stage.status === "completed").length;
    const total = plan?.hasPlan ? plan.totalTasks || 0 : fallbackStages.length;
    const progress = plan?.hasPlan ? plan.progressPercent || 0 : Math.round((completed / Math.max(total, 1)) * 100);

    return (
      <section className="v0-plan-panel">
        <div className="v0-section-title">Plan</div>
        <div className="v0-plan-summary">
          <div>
            <strong>{plan?.name || "Generation plan"}</strong>
            <span>{completed}/{total || stages.length} tasks complete</span>
          </div>
          <em>{progress}%</em>
        </div>
        <div className="v0-plan-meter">
          <i style={{ width: `${Math.max(2, Math.min(100, progress))}%` }} />
        </div>
        <div className="v0-plan-list">
          {stages.map((stage, index) => {
            const isOpen = openStages[stage.id] ?? index === 0;
            const tasks = stage.tasks || [];
            return (
              <div key={`${stage.id}-${index}`} className={classNames("v0-plan-stage", isOpen && "open")}>
                <button
                  type="button"
                  className="v0-plan-step"
                  onClick={() => setOpenStages((current) => ({ ...current, [stage.id]: !isOpen }))}
                >
                  <span className={classNames("v0-check", stage.status)}>{stage.status === "completed" ? "✓" : ""}</span>
                  <div>
                    <strong title={stage.name}>{truncateText(stage.name, 44)}</strong>
                    <small>{stage.completedTasks || 0}/{stage.totalTasks || tasks.length || 0} complete · {stage.status || "pending"}</small>
                  </div>
                  <em>{isOpen ? "−" : "+"}</em>
                </button>
                {isOpen ? (
                  <div className="v0-plan-tasks">
                    {tasks.length ? tasks.map((task) => (
                      <div key={task.id} className="v0-plan-task">
                        <span className={classNames("v0-task-dot", task.status)} />
                        <div>
                          <strong title={task.id}>{truncateText(task.id, 34)}</strong>
                          <small title={task.description}>{task.description}</small>
                          {task.assignee ? <small>Owner: {task.assignee}</small> : null}
                        </div>
                      </div>
                    )) : <div className="v0-plan-empty">No task details captured yet.</div>}
                  </div>
                ) : null}
              </div>
            );
          })}
        </div>
      </section>
    );
  }

  function AllPlansPanel({ state }) {
    const [selected, setSelected] = useState("history");
    const planHistory = state?.planHistory || [];
    const historyByAgent = planHistory.reduce((groups, item) => {
      const agent = item.agent || "system";
      groups[agent] = groups[agent] || [];
      groups[agent].push(item);
      return groups;
    }, {});
    const plans = [
      { id: "history", label: "All History", isHistory: true },
      { id: "global", label: "Global", plan: state?.planSummary, phases: state?.phases || [] },
      ...agentCards(state)
        .filter((agent) => state?.agentWorkspaces?.[agent.id]?.plan?.hasPlan || state?.agentWorkspaces?.[agent.id]?.plan?.totalTasks)
        .map((agent) => ({
          id: agent.id,
          label: agentDisplayName(agent.id),
          plan: state?.agentWorkspaces?.[agent.id]?.plan,
          phases: [],
        })),
    ];
    const active = plans.find((item) => item.id === selected) || plans[0];
    const agentPlanCounts = Object.keys(historyByAgent).length;
    return (
      <section className="all-plans-panel">
        <div className="v0-section-title">Plan Atlas</div>
        <div className="plan-switcher">
          {plans.map((item) => (
            <button key={item.id} type="button" className={classNames(selected === item.id && "active")} onClick={() => setSelected(item.id)}>
              <span>{item.label}</span>
              <em>{item.isHistory ? `${planHistory.length}` : `${Math.round(item.plan?.progressPercent || 0)}%`}</em>
            </button>
          ))}
        </div>
        <div className="plan-scroll-shell">
          {active?.isHistory ? (
            <PlanHistoryView historyByAgent={historyByAgent} totalPlans={planHistory.length} agentCount={agentPlanCounts} />
          ) : (
            <PlanPanel plan={active?.plan} phases={active?.phases || []} />
          )}
        </div>
      </section>
    );
  }

  function PlanHistoryView({ historyByAgent, totalPlans, agentCount }) {
    const [openAgents, setOpenAgents] = useState({});
    const agents = Object.keys(historyByAgent).sort((a, b) => {
      const latestA = historyByAgent[a]?.[historyByAgent[a].length - 1]?.timestamp || "";
      const latestB = historyByAgent[b]?.[historyByAgent[b].length - 1]?.timestamp || "";
      return latestB.localeCompare(latestA);
    });
    return (
      <section className="plan-history-atlas">
        <div className="plan-history-summary">
          <strong>{totalPlans}</strong>
          <span>historical plan events across {agentCount} agents</span>
        </div>
        {agents.length ? agents.map((agent, index) => {
          const items = (historyByAgent[agent] || []).slice().reverse();
          const isOpen = openAgents[agent] ?? index < 3;
          return (
            <div key={agent} className={classNames("plan-history-agent", isOpen && "open")}>
              <button type="button" className="plan-history-agent-head" onClick={() => setOpenAgents((current) => ({ ...current, [agent]: !isOpen }))}>
                <span className={classNames("v0-agent-dot", agentTone(agent))} />
                <strong>{agentDisplayName(agent)}</strong>
                <em>{items.length} plans</em>
              </button>
              {isOpen ? (
                <div className="plan-history-list">
                  {items.map((item) => (
                    <article key={item.id} className="plan-history-item">
                      <div>
                        <span>{item.action?.replace(/_/g, " ") || "plan"}</span>
                        <strong title={item.title}>{truncateText(item.title, 44)}</strong>
                      </div>
                      {item.description ? <p title={item.description}>{truncateText(item.description, 90)}</p> : null}
                      <small>
                        {item.timestamp || "no time"}
                        {item.stageId ? ` · stage ${item.stageId}` : ""}
                        {item.taskId ? ` · task ${item.taskId}` : ""}
                        {item.assignee ? ` · ${item.assignee}` : ""}
                      </small>
                    </article>
                  ))}
                </div>
              ) : null}
            </div>
          );
        }) : (
          <div className="v0-plan-empty">No historical plan tool calls captured yet.</div>
        )}
      </section>
    );
  }

  function EventCard({ item }) {
    const [open, setOpen] = useState(item.kind === "plan");
    const meta = item.kind === "tool" ? toolMeta(item.title) : actionMeta(item.kind);
    return (
      <article className={classNames("v0-event-card", item.kind, item.agent && agentTone(item.agent))}>
        <button type="button" className="v0-event-main" onClick={() => setOpen(!open)}>
          <span className={classNames("v0-event-icon", item.kind === "tool" ? meta.tone : item.kind)}>{meta.icon}</span>
          <span className="v0-event-copy">
            <span className="v0-event-title">{item.title}</span>
            <span className="v0-event-summary">{truncateText(item.summary, 190)}</span>
            <span className="v0-event-meta">{item.agent} · {item.stage} · {item.timestamp}</span>
          </span>
          <span className="v0-expand">{open ? "Hide" : "Open"}</span>
        </button>
        {item.objects?.length ? (
          <div className="v0-object-strip">
            {item.objects.map((object, index) => (
              <span key={`${object.label}-${index}`}>{object.label}</span>
            ))}
          </div>
        ) : null}
        {open ? (
          <div className="v0-event-detail">
            {item.kind === "tool" ? (
              <ToolDetail detail={item.detail} />
            ) : (
              <pre className="v0-think-block">{formatPayload(item.detail)}</pre>
            )}
          </div>
        ) : null}
      </article>
    );
  }

  function ToolDetail({ detail }) {
    return (
      <div className="v0-tool-detail">
        <PayloadBlock title="Request" value={detail.parameters} />
        {detail.resultKind === "file_read" ? (
          <section className="tool-detail-card">
            <FileReadResult result={detail.result} />
          </section>
        ) : (
          <PayloadBlock title="Response" value={detail.result} />
        )}
        <details className="v0-raw-details">
          <summary>Raw invocation</summary>
          <pre className="v0-raw-block mono">{formatPayload(detail.raw)}</pre>
        </details>
      </div>
    );
  }

  function AgentActionAnimation({ action, tone }) {
    return (
      <div className={classNames("agent-action-animation", action, tone)}>
        <div className="anim-spark one" />
        <div className="anim-spark two" />
        <div className="anim-person">
          <span className="anim-head" />
          <span className="anim-body" />
          <span className="anim-arm left" />
          <span className="anim-arm right" />
        </div>
        <div className="anim-surface">
          <span />
          <span />
          <span />
        </div>
      </div>
    );
  }

  function AgentCarouselCard({ agent, selected, onSelect }) {
    const tone = agentTone(agent.id);
    return (
      <button type="button" className={classNames("agent-carousel-card", tone, selected && "selected")} onClick={() => onSelect(agent.id)}>
        <div className="agent-card-top">
          <div>
            <span className="eyebrow">{agent.status}</span>
            <h3>{agentDisplayName(agent.id)}</h3>
          </div>
          <span className={classNames("agent-card-pulse", tone, agent.status)} />
        </div>
        <AgentActionAnimation action={agent.latestAction} tone={tone} />
        <div className="agent-action-label">{actionLabel(agent.latestAction)}</div>
        <p>{truncateText(agent.latestSummary, 96)}</p>
        <div className="agent-card-stats">
          <span><strong>{agent.unread}</strong> inbox</span>
          <span><strong>{agent.planTasks}</strong> plan</span>
          <span><strong>{agent.toolCount}</strong> tools</span>
          <span><strong>{agent.activeCount}</strong> active</span>
        </div>
        <div className="agent-card-meter">
          <i style={{ width: `${Math.max(4, Math.min(100, agent.planPercent || 0))}%` }} />
        </div>
      </button>
    );
  }

  function AgentRail({ agents, onSelectAgent }) {
    const [activeIndex, setActiveIndex] = useState(0);
    const railRef = useRef(null);
    const dragRef = useRef({ down: false, startX: 0, scrollLeft: 0, moved: false });

    function focusIndex(nextIndex) {
      const bounded = Math.max(0, Math.min(agents.length - 1, nextIndex));
      setActiveIndex(bounded);
      const rail = railRef.current;
      const card = rail?.children?.[bounded];
      if (card && rail) {
        card.scrollIntoView({ behavior: "smooth", block: "nearest", inline: "center" });
      }
    }

    function onDragStart(event) {
      const rail = railRef.current;
      if (!rail) return;
      event.preventDefault();
      rail.setPointerCapture?.(event.pointerId);
      dragRef.current = {
        down: true,
        startX: event.clientX,
        scrollLeft: rail.scrollLeft,
        moved: false,
      };
      rail.classList.add("dragging");
    }

    function onDragMove(event) {
      const rail = railRef.current;
      const drag = dragRef.current;
      if (!rail || !drag.down) return;
      event.preventDefault();
      const delta = event.clientX - drag.startX;
      if (Math.abs(delta) > 4) {
        drag.moved = true;
      }
      rail.scrollLeft = drag.scrollLeft - delta;
    }

    function endDrag(event) {
      const rail = railRef.current;
      if (!rail) return;
      if (event?.pointerId !== undefined) {
        rail.releasePointerCapture?.(event.pointerId);
      }
      dragRef.current.down = false;
      rail.classList.remove("dragging");
      const cards = Array.from(rail.querySelectorAll(".agent-carousel-card"));
      if (!cards.length) return;
      const railCenter = rail.scrollLeft + rail.clientWidth / 2;
      const nearestIndex = cards.reduce((best, card, index) => {
        const center = card.offsetLeft + card.offsetWidth / 2;
        const distance = Math.abs(center - railCenter);
        return distance < best.distance ? { index, distance } : best;
      }, { index: activeIndex, distance: Number.POSITIVE_INFINITY }).index;
      setActiveIndex(nearestIndex);
    }

    function onRailWheel(event) {
      const rail = railRef.current;
      if (!rail) return;
      const delta = Math.abs(event.deltaX) > Math.abs(event.deltaY) ? event.deltaX : event.deltaY;
      if (!delta) return;
      const before = rail.scrollLeft;
      rail.scrollLeft += delta;
      if (rail.scrollLeft !== before) {
        event.preventDefault();
      }
    }

    function onRailClickCapture(event) {
      if (dragRef.current.moved) {
        event.preventDefault();
        event.stopPropagation();
        dragRef.current.moved = false;
      }
    }

    return (
      <>
        <div className="agent-rail-controls">
          <button type="button" onClick={() => focusIndex(activeIndex - 1)} disabled={activeIndex === 0} aria-label="Previous agent">‹</button>
          <div className="agent-rail-tabs">
            {agents.map((agent, index) => (
              <button key={agent.id} type="button" className={classNames(index === activeIndex && "active")} onClick={() => focusIndex(index)}>
                {agentDisplayName(agent.id)}
              </button>
            ))}
          </div>
          <button type="button" onClick={() => focusIndex(activeIndex + 1)} disabled={activeIndex >= agents.length - 1} aria-label="Next agent">›</button>
        </div>
        <div className="agent-carousel-wrap">
          <button type="button" className="rail-edge-button left" onClick={() => focusIndex(activeIndex - 1)} disabled={activeIndex === 0} aria-label="Previous agent">‹</button>
          <div
            className="agent-carousel"
            ref={railRef}
            onPointerDown={onDragStart}
            onPointerMove={onDragMove}
            onPointerUp={endDrag}
            onPointerCancel={endDrag}
            onWheel={onRailWheel}
            onClickCapture={onRailClickCapture}
          >
            {agents.map((agent, index) => (
              <AgentCarouselCard key={agent.id} agent={agent} selected={index === activeIndex} onSelect={onSelectAgent} />
            ))}
          </div>
          <button type="button" className="rail-edge-button right" onClick={() => focusIndex(activeIndex + 1)} disabled={activeIndex >= agents.length - 1} aria-label="Next agent">›</button>
        </div>
      </>
    );
  }

  function milestoneType(item) {
    const text = `${item.title || ""} ${item.summary || ""} ${item.stage || ""} ${item.kind || ""}`.toLowerCase();
    if (/deliver|finish|complete|done|success/.test(text)) return "finish";
    if (/fail|error|blocked/.test(text)) return "error";
    if (/verify|test|lint|docker|browser/.test(text)) return "verify";
    if (/plan|stage/.test(text)) return "plan";
    return "";
  }

  function milestoneSummary(item, type) {
    const raw = String(item.summary || item.detail || item.title || "").trim();
    if (!raw || raw.startsWith("{") || raw.startsWith("[")) {
      const fallbacks = {
        finish: "A delivery or completion checkpoint was reached.",
        error: "A blocker or failure needs attention.",
        verify: "A validation step ran or changed state.",
        plan: "The working plan changed.",
      };
      return fallbacks[type] || "Checkpoint recorded.";
    }
    return raw.replace(/^Runtime\s*·\s*/i, "").replace(/^Coordination\s*·\s*/i, "");
  }

  function buildMilestones(events, state) {
    const selected = [];
    const seen = new Set();
    for (const item of events.slice().reverse()) {
      const type = milestoneType(item);
      if (!type) continue;
      const key = `${type}:${item.agent}:${item.title}:${item.timestamp}`;
      if (seen.has(key)) continue;
      seen.add(key);
      selected.push({
        id: item.id,
        type,
        agent: item.agent || "system",
        title: type === "finish" ? "Delivery checkpoint" : type === "verify" ? "Validation checkpoint" : item.title || actionLabel(type),
        summary: milestoneSummary(item, type),
        time: item.timestamp || "",
      });
      if (selected.length >= 5) break;
    }
    if (!selected.length) {
      const phases = state?.phases || [];
      return phases.slice(-5).map((phase, index) => ({
        id: `phase-${phase.name}-${index}`,
        type: phase.status === "completed" ? "finish" : "plan",
        agent: "system",
        title: phase.name || "Workflow phase",
        summary: phase.status || "pending",
        time: "",
      }));
    }
    return selected;
  }

  function MilestoneTimeline({ events, state }) {
    const milestones = buildMilestones(events, state);
    const done = milestones.filter((item) => item.type === "finish").length;
    return (
      <section className="milestone-timeline">
        <div className="section-head">
          <div>
            <span className="eyebrow">Build timeline</span>
            <h3>Key checkpoints</h3>
          </div>
          <span>{milestones.length} key nodes · {done} finished</span>
        </div>
        <div className="timeline-rail">
          {milestones.map((item, index) => (
            <article key={item.id || index} className={classNames("timeline-node", item.type)}>
              <div className="timeline-pin">
                <span>{item.type === "finish" ? "✓" : item.type === "error" ? "!" : index + 1}</span>
              </div>
              <div className="timeline-card">
                <div>
                  <strong>{item.title}</strong>
                  <em>{item.agent}</em>
                </div>
                <p title={item.summary}>{truncateText(item.summary, 64)}</p>
                {item.time ? <small>{item.time}</small> : null}
              </div>
            </article>
          ))}
        </div>
      </section>
    );
  }

  function MainDashboard({ state, events, readyArtifacts, onSelectAgent }) {
    const agents = agentCards(state);
    const activeAgents = agents.filter((agent) => agent.activeCount > 0 || agent.status === "active" || agent.status === "running").length;
    const plan = state?.planSummary || {};
    return (
      <div className="envforger-dashboard">
        <section className="envforger-hero">
          <div>
            <div className="v0-prompt-label">EnvForger command center</div>
            <h2>{state?.projectName?.replace(/-/g, " ") || "web app"} build is being forged</h2>
            <p>
              A compact view of agent motion, inbox pressure, plan progress, and recent execution. Select any agent card to open the detailed workspace.
            </p>
          </div>
          <div className="forge-orb" aria-hidden="true">
            <span />
            <span />
            <span />
          </div>
        </section>

        <section className="forge-metrics">
          <div><strong>{activeAgents}</strong><span>active agents</span></div>
          <div><strong>{Math.round(plan.progressPercent || 0)}%</strong><span>plan progress</span></div>
          <div><strong>{readyArtifacts}/{state?.artifacts?.length || 0}</strong><span>artifacts</span></div>
          <div><strong>{state?.toolCalls?.length || 0}</strong><span>tool calls</span></div>
          <div><strong>{events.length}</strong><span>recent signals</span></div>
        </section>

        <MilestoneTimeline events={events} state={state} />

        <section className="agent-carousel-section">
          <div className="section-head">
            <div>
              <span className="eyebrow">Live agent rail</span>
              <h3>Drag the rail to browse agents</h3>
            </div>
            <span>drag horizontally · click card for detail</span>
          </div>
          <AgentRail agents={agents} onSelectAgent={onSelectAgent} />
        </section>

        <section className="activity-radar">
          <div className="section-head">
            <div>
              <span className="eyebrow">Activity radar</span>
              <h3>Recent pulse</h3>
            </div>
            <span>last {Math.min(12, events.length)} events</span>
          </div>
          <div className="radar-list">
            {events.slice(0, 12).map((item) => (
              <div key={item.id} className={classNames("radar-row", item.kind)}>
                <span className={classNames("radar-dot", item.kind)} />
                <strong>{item.agent || "system"}</strong>
                <p>{truncateText(item.summary || item.title, 110)}</p>
              </div>
            ))}
            {!events.length ? <EmptyPanel title="Waiting for agent activity." compact /> : null}
          </div>
        </section>
      </div>
    );
  }

  // Cutover 34: per-project Deliver + Force-Deliver controls (project header).
  function DeliverButton({ projectId }) {
    const [pending, setPending] = useState(false);
    const [report, setReport] = useState(null);
    const [forceMode, setForceMode] = useState(false);
    const [reason, setReason] = useState("");
    const [error, setError] = useState("");
    const [success, setSuccess] = useState("");

    async function tryDeliver(force) {
      if (force && !window.confirm("Force-deliver bypasses all gates. Continue?")) return;
      if (force && reason.trim().length < 5) {
        setError("reason must be at least 5 chars");
        return;
      }
      setPending(true);
      setError("");
      setSuccess("");
      try {
        const body = force
          ? { force_deliver: true, reason: reason.trim(), agent: "ui_user" }
          : {};
        const r = await fetch(`/api/projects/${encodeURIComponent(projectId)}/deliver`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          credentials: "include",
          body: JSON.stringify(body),
        });
        const data = await r.json();
        setReport(data.report || null);
        if (data.ok) {
          setForceMode(false);
          setReason("");
          setSuccess(force ? "Force-delivered." : "Delivered. Project marked completed.");
          if (typeof window.LiveMonitorRefresh === "function") {
            window.LiveMonitorRefresh();
          }
        } else if (data.error) {
          setError(data.error);
        }
      } catch (e) {
        setError(String(e));
      } finally {
        setPending(false);
      }
    }

    return (
      <div className="deliver-section">
        <div className="deliver-row">
          <button
            type="button"
            onClick={() => tryDeliver(false)}
            disabled={pending}
            className="deliver-btn"
          >
            {pending ? "Checking…" : "Deliver"}
          </button>
          <button
            type="button"
            onClick={() => { setForceMode(!forceMode); setError(""); }}
            className="force-deliver-toggle"
          >
            {forceMode ? "Cancel force" : "Force"}
          </button>
        </div>
        {forceMode ? (
          <div className="force-deliver-form">
            <input
              type="text"
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder="reason (≥5 chars)"
            />
            <button
              type="button"
              onClick={() => tryDeliver(true)}
              disabled={pending}
              className="deliver-btn destructive"
            >
              Force Deliver
            </button>
          </div>
        ) : null}
        {error ? <div className="deliver-error">{error}</div> : null}
        {success ? <div className="deliver-success">{success}</div> : null}
        {report && report.verdict ? (
          <div className={`deliver-report verdict-${report.verdict}`}>
            <strong>Verdict: {report.verdict}</strong>
            {report.blockers && report.blockers.length > 0 ? (
              <ul className="blockers-list">
                {report.blockers.map((b, i) => <li key={i}>{String(b)}</li>)}
              </ul>
            ) : null}
          </div>
        ) : null}
      </div>
    );
  }

  function Center({ state, selectedAgent, onSelectAgent, lastUpdated, error }) {
    const events = useMemo(() => mergeV0Events(state, selectedAgent), [state, selectedAgent]);
    const readyArtifacts = (state?.artifacts || []).filter((artifact) => artifact.exists).length;
    const workspace = selectedAgent ? state?.agentWorkspaces?.[selectedAgent] : null;
    const memory = selectedAgent ? state?.memoryBank?.agents?.[selectedAgent] : null;
    // Cutover 36: open the SSE log modal for the currently selected run, if any.
    const [openRunLog, setOpenRunLog] = useState(null);
    return (
      <main className="v0-center">
        <header className="v0-topbar">
          <div>
            <div className="v0-breadcrumb">EnvForger / {state?.projectName || "project"}</div>
            <h1>Forge {state?.projectName?.replace(/-/g, " ") || "web app"}</h1>
          </div>
          <div className="v0-top-actions">
            <StatusBadge status={state?.status} />
            <span className="v0-updated">{lastUpdated || "--"}</span>
            {state?.active_runs && state.active_runs.length > 0 ? (
              <div className="active-runs">
                {state.active_runs.map((r) => (
                  <button
                    key={r.run_id}
                    className={"run-pill state-" + r.state}
                    onClick={() => setOpenRunLog(r.run_id)}
                    title={`View logs for ${r.run_id} (${r.state})`}
                  >
                    {r.run_id.substr(0, 10)}… ({r.state})
                  </button>
                ))}
              </div>
            ) : null}
            {state?.projectId ? <DeliverButton projectId={state.projectId} /> : null}
          </div>
        </header>

        {selectedAgent ? (
          <AgentWorkspace agentId={selectedAgent} workspace={workspace} memory={memory} events={events} />
        ) : (
          <>
            {error ? <div className="v0-error">{error}</div> : null}
            <MainDashboard state={state} events={events} readyArtifacts={readyArtifacts} onSelectAgent={onSelectAgent} />
          </>
        )}

        {openRunLog && window.RunLogStream ? (
          <window.RunLogStream runId={openRunLog} onClose={() => setOpenRunLog(null)} />
        ) : null}
      </main>
    );
  }

  function AgentWorkspace({ agentId, workspace, memory, events }) {
    const [tab, setTab] = useState("history");
    const tabs = [
      ["history", "History & Tools"],
      ["plan", "Plan"],
      ["mailbox", "Message Box"],
      ["runtime", "Spawn & Teams"],
      ["memory", "Memory Bank"],
    ];
    return (
      <section className="agent-workspace">
        <div className="agent-workspace-head">
          <div>
            <div className="v0-breadcrumb">Agents / {agentId}</div>
            <h2>{agentId} workspace</h2>
          </div>
          <div className="agent-mini-stats">
            <span>{workspace?.history?.length || 0} history</span>
            <span>{workspace?.toolCalls?.length || 0} tools</span>
            <span>{workspace?.mailbox?.counts?.unread || 0} unread</span>
          </div>
        </div>

        <div className="agent-tabs">
          {tabs.map(([key, label]) => (
            <button key={key} type="button" className={classNames(tab === key && "active")} onClick={() => setTab(key)}>
              {label}
            </button>
          ))}
        </div>

        {tab === "history" ? (
          <div className="v0-stream agent-tab-body">
            {events.length ? events.map((item) => <EventCard key={item.id} item={item} />) : <EmptyPanel title="No history yet" body="Waiting for this agent to emit activity or tool calls." />}
          </div>
        ) : null}

        {tab === "plan" ? <AgentPlanView plan={workspace?.plan} /> : null}
        {tab === "mailbox" ? <MailboxView mailbox={workspace?.mailbox} /> : null}
        {tab === "runtime" ? <RuntimeView runtime={workspace?.runtime} /> : null}
        {tab === "memory" ? <AgentMemoryView memory={memory} agentId={agentId} /> : null}
      </section>
    );
  }

  function AgentMemoryView({ memory, agentId }) {
    const files = memory?.files || [];
    const [fileKey, setFileKey] = useState("");
    const selectedFile = files.find((file) => file.key === fileKey) || files.find((file) => file.key === "active_context") || files[0];
    return (
      <div className="agent-tab-body agent-memory-panel">
        <div className="agent-memory-head">
          <div>
            <span className="eyebrow">Agent private memory</span>
            <h3>{agentId} memory bank</h3>
          </div>
          <span>{memory?.summary?.files || 0} files</span>
        </div>
        <div className="agent-memory-layout">
          <div className="agent-memory-files">
            {files.length ? files.map((file) => (
              <button key={file.key} type="button" className={classNames(selectedFile?.key === file.key && "active")} onClick={() => setFileKey(file.key)}>
                <span>{file.key.replace(/_/g, " ")}</span>
                <em>{file.size}b</em>
              </button>
            )) : <EmptyPanel title="No memory files for this agent yet." compact />}
          </div>
          <div className="agent-memory-content">
            <div className="v0-code-head">
              <strong>{selectedFile?.path || `memory-bank/${agentId}`}</strong>
              <span>markdown</span>
            </div>
            <pre className="memory-markdown mono">{selectedFile?.content || "Waiting for this agent memory bank..."}</pre>
          </div>
        </div>
      </div>
    );
  }

  function AgentPlanView({ plan }) {
    return (
      <div className="agent-tab-body">
        <PlanPanel plan={plan} phases={[]} />
      </div>
    );
  }

  function MailboxView({ mailbox }) {
    return (
      <div className="mailbox-grid agent-tab-body">
        <MessageColumn title="Inbox" items={mailbox?.inbox || []} empty="No inbox messages captured." direction="from" />
        <MessageColumn title="Sent" items={mailbox?.sent || []} empty="No sent messages captured." direction="to" />
        <MessageColumn title="Broadcasts" items={mailbox?.broadcasts || []} empty="No broadcasts captured." direction="broadcast" />
      </div>
    );
  }

  function MessageColumn({ title, items, empty, direction }) {
    return (
      <section className="message-column">
        <div className="message-column-head">
          <strong>{title}</strong>
          <span>{items.length}</span>
        </div>
        <div className="message-list">
          {items.length ? items.map((item, index) => (
            <article key={`${title}-${item.id || item.timestamp || index}`} className={classNames("message-card", item.read === false && "unread")}>
              <div className="message-meta">
                <span>{direction === "from" ? `from ${item.from || "unknown"}` : direction === "to" ? `to ${item.to || "unknown"}` : "broadcast"}</span>
                <em>{item.type || item.priority || item.status || "message"}</em>
              </div>
              <p>{truncateText(item.content, 260)}</p>
              <small>{item.timestamp || "no timestamp"}</small>
            </article>
          )) : <EmptyPanel title={empty} compact />}
        </div>
      </section>
    );
  }

  function RuntimeView({ runtime }) {
    const calls = runtime?.toolCalls || [];
    const runtimes = runtime?.spawnedAgents || [];
    const resident = runtimes.filter((item) => item.resident);
    const workers = runtimes.filter((item) => !item.resident);
    return (
      <div className="runtime-dashboard agent-tab-body">
        <section className="runtime-hero">
          <div>
            <span className="eyebrow">Runtime Topology</span>
            <h3>{resident.length} resident lanes · {workers.length} workers · {(runtime?.agentTeams || []).length} teams</h3>
          </div>
          <div className="runtime-orbit">
            {runtimes.slice(0, 7).map((item) => (
              <span key={item.id || item.name} className={classNames("runtime-orbit-dot", item.status)} title={item.name} />
            ))}
          </div>
        </section>

        <section className="runtime-card wide">
          <div className="runtime-card-head">
            <div>
              <span className="eyebrow">Always-on lanes</span>
              <h3>Resident Agents</h3>
            </div>
            <span className="runtime-count">{resident.length}</span>
          </div>
          <RuntimeCards items={resident} empty="No resident lanes captured." />
        </section>

        <section className="runtime-card">
          <div className="runtime-card-head">
            <div>
              <span className="eyebrow">Ephemeral execution</span>
              <h3>Dynamic Workers</h3>
            </div>
            <span className="runtime-count">{workers.length}</span>
          </div>
          <RuntimeCards items={workers} empty="No dynamic workers captured." compact />
        </section>

        <section className="runtime-card">
          <div className="runtime-card-head">
            <div>
              <span className="eyebrow">Managed groups</span>
              <h3>Agent Teams</h3>
            </div>
            <span className="runtime-count">{(runtime?.agentTeams || []).length}</span>
          </div>
          <TeamCards items={runtime?.agentTeams || []} empty="No managed teams captured." />
        </section>

        <section className="runtime-card wide">
          <div className="runtime-card-head">
            <div>
              <span className="eyebrow">Orchestration trace</span>
              <h3>Runtime Tool Calls</h3>
            </div>
            <span className="runtime-count">{calls.length}</span>
          </div>
          {calls.length ? (
            <div className="runtime-call-timeline">
              {calls.map((call) => (
                <article key={call.id} className="runtime-call-row">
                  <div className="runtime-call-dot" />
                  <div>
                    <strong>{call.toolName}</strong>
                    <p>{truncateText(call.argsText || formatPayload(call.args), 180)}</p>
                    <small>{call.timestamp}</small>
                  </div>
                </article>
              ))}
            </div>
          ) : <EmptyPanel title="No runtime tool calls captured." body="When this agent creates workers or teams, their calls will appear here as a compact timeline." compact />}
        </section>
      </div>
    );
  }

  function RuntimeCards({ items, empty, compact }) {
    if (!items.length) return <EmptyPanel title={empty} compact />;
    return (
      <div className={classNames("runtime-card-grid", compact && "compact")}>
        {items.map((item, index) => (
          <div key={`${item.id || item.name}-${index}`} className="runtime-agent-card">
            <div className="runtime-agent-top">
              <span className={classNames("runtime-status-dot", item.status)} />
              <strong>{item.label || item.name}</strong>
              <em>{item.status || "unknown"}</em>
            </div>
            <div className="runtime-agent-meta">
              <span>{item.resident ? "resident lane" : "worker"}</span>
              {item.requestedType ? <span>type {item.requestedType}</span> : null}
              {item.configProfile ? <span>profile {item.configProfile}</span> : null}
            </div>
          </div>
        ))}
      </div>
    );
  }

  function TeamCards({ items, empty }) {
    if (!items.length) return <EmptyPanel title={empty} compact />;
    return (
      <div className="team-card-list">
        {items.map((item, index) => (
          <div key={`${item.id || item.name}-${index}`} className="team-card">
            <div>
              <strong>{item.label || item.name}</strong>
              <span>{item.kind || "team"}</span>
            </div>
            <em>{item.status || "active"}</em>
          </div>
        ))}
      </div>
    );
  }

  function EmptyPanel({ title, body, compact }) {
    return (
      <div className={classNames("empty-panel", compact && "compact")}>
        <strong>{title}</strong>
        {body ? <p>{body}</p> : null}
      </div>
    );
  }

  function Inspector({ state, collapsed, onToggleCollapsed }) {
    const [tab, setTab] = useState("preview");
    const files = state?.projectFiles || [];
    const selectedDefault = files.find((file) => file.kind === "code") || files[0];
    const [selectedPath, setSelectedPath] = useState("");
    const selectedFile = files.find((file) => file.path === selectedPath) || selectedDefault;
    const codeFiles = files;

    return (
      <aside className={classNames("v0-inspector", collapsed && "collapsed")}>
        <button type="button" className="inspector-collapse-toggle" onClick={onToggleCollapsed} title={collapsed ? "Expand right panel" : "Collapse right panel"}>
          <strong>{collapsed ? "‹" : "›"}</strong>
          <span>{collapsed ? "Preview" : "Hide"}</span>
        </button>
        <div className="v0-tabs">
          {["preview", "code", "hubs", "chat", "logs"].map((item) => (
            <button key={item} type="button" className={classNames(tab === item && "active")} onClick={() => setTab(item)}>
              {item}
            </button>
          ))}
        </div>

        {tab === "preview" ? (
          <div className="v0-preview-pane">
            <div className="v0-browser-bar">
              <span />
              <span />
              <span />
              <strong>{state?.previewUrl || "http://127.0.0.1:3000"}</strong>
            </div>
            <iframe title="Generated app preview" src={state?.previewUrl || "http://127.0.0.1:3000"} />
          </div>
        ) : null}

        {tab === "code" ? (
          <FileInspector
            files={codeFiles}
            selectedFile={selectedFile}
            onSelect={setSelectedPath}
            emptyMessage="Waiting for generated code..."
          />
        ) : null}

        {tab === "hubs" ? (
          <window.LiveMonitorHubsTab
            hubs={state?.hubs}
            projectId={state?.projectId}
            onRefresh={() => window.LiveMonitorRefresh && window.LiveMonitorRefresh()}
          />
        ) : null}
        {tab === "chat" ? <window.LiveMonitorChatPanel projectId={state?.projectId} /> : null}

        {tab === "logs" ? (
          <div className="v0-log-pane mono">
            {(state?.recentLogLines || []).length ? state.recentLogLines.join("\n") : "Waiting for logs..."}
          </div>
        ) : null}
      </aside>
    );
  }

  // Cutover 28: CrdtInspector replaced by HubsTab (window.LiveMonitorHubsTab) and ChatPanel.

  function FileInspector({ files, selectedFile, onSelect, emptyMessage }) {
    const parsed = selectedFile?.preview ? parseJsonLike(selectedFile.preview) : { ok: false };
    const isSpecLike = parsed.ok || selectedFile?.kind === "spec" || /\.json$/i.test(selectedFile?.path || "");
    const tree = useMemo(() => buildFileTree(files), [files]);
    return (
      <div className="v0-code-pane">
        <div className="v0-file-list">
          <FileTree nodes={tree} selectedPath={selectedFile?.path} onSelect={onSelect} />
        </div>
        <div className="v0-code-window">
          <div className="v0-code-head">
            <strong>{selectedFile?.path || "No file selected"}</strong>
            <span>{isSpecLike ? "structured" : languageForPath(selectedFile?.path)}</span>
          </div>
          {isSpecLike && parsed.ok ? (
            <div className="v0-structured-file">
              <StructuredValue value={parsed.value} />
              <details className="v0-raw-details">
                <summary>Show formatted JSON</summary>
                <pre className="v0-raw-block mono">{selectedFile.preview}</pre>
              </details>
            </div>
          ) : (
            <pre className="mono">{selectedFile?.preview || emptyMessage}</pre>
          )}
        </div>
      </div>
    );
  }

  function buildFileTree(files) {
    const root = { name: "project", type: "dir", children: {}, depth: 0 };
    for (const file of files) {
      const parts = String(file.path || file.name || "").split("/").filter(Boolean);
      let cursor = root;
      parts.forEach((part, index) => {
        const isFile = index === parts.length - 1;
        if (!cursor.children[part]) {
          cursor.children[part] = {
            name: part,
            type: isFile ? "file" : "dir",
            file: isFile ? file : null,
            children: {},
            depth: index,
          };
        }
        cursor = cursor.children[part];
      });
    }
    return Object.values(root.children).sort(sortTreeNode);
  }

  function sortTreeNode(a, b) {
    if (a.type !== b.type) return a.type === "dir" ? -1 : 1;
    return a.name.localeCompare(b.name);
  }

  function FileTree({ nodes, selectedPath, onSelect }) {
    const [collapsed, setCollapsed] = useState({});
    if (!nodes.length) return <div className="v0-file-empty">No files yet</div>;
    return (
      <div className="v0-file-tree">
        {nodes.map((node) => (
          <FileTreeNode
            key={`${node.type}:${node.name}:${node.depth}`}
            node={node}
            selectedPath={selectedPath}
            collapsed={collapsed}
            onToggle={(key) => setCollapsed((current) => ({ ...current, [key]: !current[key] }))}
            onSelect={onSelect}
          />
        ))}
      </div>
    );
  }

  function FileTreeNode({ node, selectedPath, collapsed, onToggle, onSelect }) {
    const key = `${node.depth}:${node.name}`;
    const children = Object.values(node.children || {}).sort(sortTreeNode);
    const isCollapsed = collapsed[key];
    const paddingLeft = 8 + node.depth * 14;
    if (node.type === "dir") {
      return (
        <div className="v0-tree-group">
          <button type="button" className="v0-tree-row dir" style={{ paddingLeft }} onClick={() => onToggle(key)}>
            <span className="v0-tree-caret">{isCollapsed ? "›" : "⌄"}</span>
            <span className="v0-tree-icon">▦</span>
            <span>{node.name}</span>
          </button>
          {!isCollapsed ? children.map((child) => (
            <FileTreeNode
              key={`${child.type}:${child.name}:${child.depth}`}
              node={child}
              selectedPath={selectedPath}
              collapsed={collapsed}
              onToggle={onToggle}
              onSelect={onSelect}
            />
          )) : null}
        </div>
      );
    }
    return (
      <button
        type="button"
        className={classNames("v0-tree-row file", selectedPath === node.file?.path && "active")}
        style={{ paddingLeft }}
        onClick={() => onSelect(node.file.path)}
      >
        <span className="v0-tree-caret" />
        <span className="v0-tree-icon">{fileIcon(node.file?.path)}</span>
        <span>{node.name}</span>
      </button>
    );
  }

  function fileIcon(path) {
    if (/\.json$/i.test(path || "")) return "{}";
    if (/\.sql$/i.test(path || "")) return "db";
    if (/\.(jsx|tsx)$/i.test(path || "")) return "⌘";
    if (/\.css$/i.test(path || "")) return "#";
    return "•";
  }

  return { Center, Inspector, Sidebar };
})();
