# Phase 4.7-slim HumanConsole Design Notes (Path A SHIPPED; Path C OPEN)

**Status:** ✅ Path A bridge SHIPPED at `960dc566` (2026-06-01) per
user 2026-05-31 directive ("用Path C，但你从短期过渡到长期的想法是合理的"
— ship the env-var bridge now, plan Path C later). The gate at
`eventhub.publish_human_message` rejects phantom `from_user` (literal
`"human_user"` OR empty) at phase>=4.7; HumanConsole captures the
project's 甲方 via `ENVGEN_HUMAN_USER_ID` env var or
`human_user_id=` kwarg. Anchor O.

**✅ Path C SHIPPED 2026-06-01** (commit-pending after this doc
update): session-derived identity from live_monitor cookie/auth at
request time. The live_monitor session-auth track was already wired
(Cutover 35 `_apply_request_user` at `live_monitor_server.py:4680`
already stamps `body["agent"] = username` for authed requests) —
Path C is a 5-LOC extension that ALSO stamps
`body["from_user"] = username`. The HTTP shims
`start_conversation_call` / `send_message_call` were flipped from
`body.get("from_user") or "human_user"` (literal phantom) to
`body.get("from_user") or None` so HumanConsole's Path A chain
(env var) takes over when no Path C identity is supplied.

**Precedence at the HumanConsole publish path**: Path C (authed
session username) > body-supplied `from_user` > Path A
(`ENVGEN_HUMAN_USER_ID` env var) > literal `"human_user"`
(rejected by the 4.7 gate). Multi-user pipelines get per-request
identity; the headless/CLI/test paths keep the env-var bridge.

**Original DEFER rationale (preserved for context):** Research notes.
Phase 4.7-slim HumanConsole `from_user` identity gate was scoped via
workflow `wrvk6badj` (7 agents, 198k tokens). Workflow recommended
**DEFER**, not because the surface doesn't exist (it does, and is
well-mapped below), but because the gating answer needs product-judgment
input on what an "authoritative human identity" means in this codebase.

Captures the discovery so the next implementer can pick up with full context.

## Current surface (well-mapped, NOT a phantom)

**HumanConsole class** lives at
[`runtime/human_console.py:15`](../agent/env_generator/llm_generator/multi_agent/runtime/human_console.py).
Instantiated by `HubRegistry.__init__` at hub_registry.py:124-125 as
`self.human_console = HumanConsole(self)`. Re-exported from runtime/__init__.py.

**`from_user` is a kwarg** (string identity label, NOT a method or
authenticated session ID). Flow:

```
HumanConsole.start_conversation(from_user=...)
   ↓
HumanConsole.send_message(from_user=...)
   ↓
EventHub.publish_human_message(from_user=...)
   ↓
event.payload["from_user"]  (verbatim, no check)
```

Default value at every layer: `"human_user"`.

### Three write-side methods (gate-relevant)

| Method | File:line | Current from_user default | Caller-override? |
|---|---|---|---|
| `HumanConsole.start_conversation` | `human_console.py:22-39` | `"human_user"` | Yes (kwarg) |
| `HumanConsole.send_message` | `human_console.py:41-72` | `"human_user"` | Yes (kwarg) |
| `HumanConsole.mark_resolved` | `human_console.py:128-139` | hardcoded `"human_user"` | **No** — no override |
| `EventHub.publish_human_message` | `eventhub.py:317-341` | `"human_user"` | Yes (kwarg) |

`mark_resolved` is the spicy one — it hardpins `actor="human_user"` with
no caller attribution.

### NO existing gate

Grep across human_console.py + eventhub.py for role|identity|auth|
permission|gate|allowlist|whitelist returns only unrelated transcript-
builder labels. **Any code path reaching publish_human_message can mint
an event downstream consumers treat as a real human turn under whatever
`from_user` label it chooses.**

## Production callers (3-layer surface)

```
UI → live_monitor_server HTTP shim → HumanConsole → EventHub
```

**No agent-side tool wrappers call this surface.** Strictly the
UI→server→runtime path (Cutover 27/28).

| Layer | File:line | from_user value |
|---|---|---|
| HTTP `POST /api/projects/<id>/conversations` | `live_monitor_server.py:1652-1665` | `body.get("from_user")` or literal `"human_user"` |
| HTTP `POST .../conversations/<thread>/messages` | `live_monitor_server.py:1668-1683` | same phantom default |
| HTTP `DELETE .../conversations/<thread>` (mark_resolved) | `live_monitor_server.py:1686-1696` | no actor field at all |
| HumanConsole wrappers | `human_console.py:22, 41, 128` | default `"human_user"` |
| EventHub event producer | `eventhub.py:322, 335, 339` | hard-pinned `"human_user"` for source_hub + priority |

### The `"ui_user"` vs `"human_user"` distinction

| Phantom literal | Used by | Phase 4.x treatment |
|---|---|---|
| `"ui_user"` (~30 occurrences) | other agent-action HTTP shims (workhub_*, codehub_*, user_gates, etc.) | Phase 4.5 / 4.6 flipped to `""` for review-verdict shims |
| `"human_user"` (~5 occurrences) | HumanConsole HTTP shims at L1662, L1678 + EventHub source_hub/priority pins | **NOT yet flipped** — Phase 4.7-slim's open question |

## Why DEFER instead of ship

Three design questions block autonomous shipping:

### Q1. What is the authoritative "human" identity?

Three plausible answers, none chosen by anyone yet:

- **Runtime-only `"human"`** — mirror RunHub.record_probe (runtime-only
  idiom). Gate would only admit `agent == "human"`. Other actors raise.
  But this departs from the existing `"human_user"` literal — would need
  to flip the default at every layer + every test fixture.
- **Allowlist `{human_user, orchestrator}`** — keep `human_user` literal,
  admit orchestrator for "system speaks as human" cases. Closest to
  current state. But "human_user" is structurally indistinguishable from
  a non-authenticated label — gating on it doesn't actually verify
  humanness.
- **Session-derived identity** — flip HTTP shim defaults to `""` (Phase
  4.5/4.6 pattern), require the UI to pass a session-derived identity.
  Doesn't ship until session auth lands; out-of-scope for "slim".

### Q2. Does `mark_resolved` need a separate gate?

`mark_resolved` hardcodes `actor="human_user"` with no kwarg. It mutates
thread status — a verdict-bearing write. Either:
- Gate it separately under the runtime-only idiom (system mutates own
  state — admit empty or `"human_console_runtime"`).
- Leave ungated (mutator hardpin is the existing "no caller override"
  contract; adding a phase gate is a no-op since no agent can vary the
  actor).

### Q3. Does the EventHub `source_hub="human_user"` pin need a gate?

`publish_human_message` hardpins `source_hub="human_user"` (eventhub.py:335).
Downstream code in `list_conversations` (eventhub.py:393) identifies a
thread as a "human conversation" purely by `first.get("source_hub") ==
"human_user"`. **Any code path that calls publish_event with
source_hub="human_user" creates a thread the UI treats as a human
conversation.** This is a separate spoof surface from `from_user`. A
slim Phase 4.7 gate addresses `from_user` only; a full Phase 4.7
would also tighten `publish_event(source_hub="human_user")` callers.

## Recommended next-PR scope

If/when Phase 4.7-slim ships, the smallest-scope path:

1. **HTTP shim flip** — `live_monitor_server.py:1662 + :1678` default
   `body.get("from_user")` to `""` instead of `"human_user"`. Add early
   validation: reject empty-from_user with `{error: "from_user_required"}`
   so the UI gets a clear error rather than a silent spoof acceptance.
2. **HumanConsole signature change** — drop the default at
   `start_conversation` / `send_message` (positional or required-kwarg).
3. **NO runtime gate at EventHub.publish_human_message** — the gate
   lives at the HumanConsole layer instead. EventHub stays trusting
   (any caller can still publish events with `source_hub="human_user"`
   if they directly import; mitigation belongs in a follow-up).
4. **Per-anchor test** + `_MECHANISMS` entry + activation log section.

## Why this wasn't shipped autonomously

The workflow caught the operator-judgment gap honestly. Adding a gate
without choosing Q1's answer would either:
- (a) Ship the runtime-only idiom and break ~5 callers + every test
  using the `"human_user"` default (high churn for unclear value).
- (b) Ship the allowlist `{human_user}` which doesn't actually verify
  humanness (gate-for-gates-sake without security benefit).
- (c) Ship the session-derived empty-fallthrough which is identical to
  no-gate at all at phase>=4.7 since UI still passes "human_user"
  literal everywhere.

None of (a)/(b)/(c) match the audit-driven approach the prior Phase 4.x
gates used. The next implementer should pick Q1 by talking to the UI
session-auth track.

## Out of scope

- Full "session-attested human identity" attestation primitive — the
  roadmap explicitly excluded this. Stays scoped out.
- Tightening `EventHub.publish_event(source_hub="human_user")` callers —
  separate surface, not in Phase 4.7-slim.
