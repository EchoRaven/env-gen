window.MonitorUtils = (() => {
  function classNames(...parts) {
    return parts.filter(Boolean).join(" ");
  }

  function formatStatus(status) {
    if (!status) return "Idle";
    return status.charAt(0).toUpperCase() + status.slice(1);
  }

  function formatRelativeTime(value) {
    if (!value) return "n/a";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return value;
    return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  }

  function agentTone(agent) {
    const tones = {
      orchestrator: "violet",
      design: "cyan",
      database: "emerald",
      backend: "amber",
      frontend: "pink",
      verifier: "blue",
      knowledge: "slate",
    };
    return tones[agent] || "slate";
  }

  function actionMeta(actionType) {
    const meta = {
      think: { icon: "◎", label: "Think" },
      inbox: { icon: "◌", label: "Inbox" },
      read: { icon: "◫", label: "Read" },
      write: { icon: "✦", label: "Write" },
      lint: { icon: "△", label: "Lint" },
      message: { icon: "➜", label: "Message" },
      plan: { icon: "◇", label: "Plan" },
      error: { icon: "!", label: "Error" },
      activity: { icon: "•", label: "Activity" },
    };
    return meta[actionType] || meta.activity;
  }

  function formatPayload(value) {
    if (value === null || value === undefined || value === "") return "(empty)";
    if (typeof value === "string") return value;
    try {
      return JSON.stringify(value, null, 2);
    } catch (err) {
      return String(value);
    }
  }

  function truncateText(value, max = 180) {
    const text = String(value ?? "").trim();
    if (!text) return "(empty)";
    return text.length > max ? `${text.slice(0, max - 1).trimEnd()}...` : text;
  }

  function summarizeValue(value) {
    if (value === null || value === undefined || value === "") return "empty";
    if (typeof value === "string") return `${value.length} chars`;
    if (Array.isArray(value)) return `${value.length} items`;
    if (typeof value === "object") return `${Object.keys(value).length} fields`;
    return String(value);
  }

  function valueEntries(value) {
    if (Array.isArray(value)) {
      return value.map((item, index) => [`item_${index}`, item]);
    }
    if (value && typeof value === "object") {
      return Object.entries(value);
    }
    return [];
  }

  function toolMeta(toolName) {
    const name = String(toolName || "").toLowerCase();
    if (/search|query|lookup|semantic|rg|glob|fetch|read/.test(name)) {
      return { label: "Retrieval", icon: "Q", tone: "cyan" };
    }
    if (/write|edit|patch|apply|create|delete/.test(name)) {
      return { label: "Mutation", icon: "W", tone: "pink" };
    }
    if (/run|exec|shell|command|npm|python/.test(name)) {
      return { label: "Execution", icon: ">", tone: "amber" };
    }
    if (/browser|navigate|click|snapshot/.test(name)) {
      return { label: "Browser", icon: "B", tone: "blue" };
    }
    if (/message|agent|plan|todo/.test(name)) {
      return { label: "Coordination", icon: "C", tone: "violet" };
    }
    return { label: "Runtime", icon: "*", tone: "slate" };
  }

  function eventTitle(item) {
    if (!item) return "Agent event";
    const label = actionMeta(item.actionType).label;
    if (item.actionType === "plan") return "Updated plan";
    if (item.actionType === "think") return "Thought for next move";
    if (item.actionType === "write") return "Created or updated file";
    if (item.actionType === "read") return "Inspected project context";
    if (item.stage) return `${label} · ${item.stage}`;
    return label;
  }

  function mergeV0Events(state, selectedAgent) {
    const workspace = selectedAgent ? state?.agentWorkspaces?.[selectedAgent] : null;
    const activities = selectedAgent
      ? workspace?.history || (state?.recentActivity || []).filter((item) => item.agent === selectedAgent)
      : state?.recentActivity || [];
    const tools = selectedAgent
      ? workspace?.toolCalls || (state?.toolCalls || []).filter((item) => item.agent === selectedAgent || item.ownerAgent === selectedAgent)
      : state?.toolCalls || [];

    const activityItems = activities.map((item, index) => ({
      id: `activity-${item.timestamp}-${item.agent}-${index}`,
      kind: item.actionType || "activity",
      timestamp: item.timestamp,
      agent: item.agent,
      title: eventTitle(item),
      summary: item.message,
      detail: item.message,
      stage: item.stage || "runtime",
      objects: item.objects || [],
    }));

    const toolItems = tools.map((call, index) => ({
      id: `tool-${call.id || index}`,
      kind: "tool",
      timestamp: formatRelativeTime(call.timestamp),
      agent: call.ownerAgent && call.ownerAgent !== call.agent ? `${call.ownerAgent} / ${call.agent}` : call.agent,
      title: call.toolName || "tool",
      summary: `${toolMeta(call.toolName).label} · ${truncateText(call.argsText || formatPayload(call.args), 120)}`,
      detail: {
        parameters: call.args ?? call.argsText,
        result: call.result ?? call.resultText,
        resultKind: call.resultKind || "structured",
        raw: call.rawContent,
      },
      stage: toolMeta(call.toolName).label,
      objects: [],
    }));

    return [...activityItems, ...toolItems].slice(-120).reverse();
  }

  function languageForPath(path) {
    const ext = String(path || "").split(".").pop();
    const map = { jsx: "jsx", js: "js", tsx: "tsx", ts: "ts", css: "css", json: "json", sql: "sql", md: "md", yml: "yaml", yaml: "yaml" };
    return map[ext] || "text";
  }

  return {
    actionMeta,
    agentTone,
    classNames,
    eventTitle,
    formatPayload,
    formatRelativeTime,
    formatStatus,
    languageForPath,
    mergeV0Events,
    summarizeValue,
    toolMeta,
    truncateText,
    valueEntries,
  };
})();
