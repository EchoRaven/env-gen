---
name: ui-ux-review
description: Use when reviewing or speccing a page/component/flow's UX for the frontend lane or as a reviewer (codehub_review_pr) before sign-off — checking hierarchy, one-primary-action, consistent spacing/typography, and that loading/empty/error/disabled/success states all exist. Triggers on "review this UI", "does this look right", missing states, inconsistent spacing, unclear primary action, poor responsive behavior, or a validation:ui_smoke / ui_flow:* failure that's a UX gap not a clone-fidelity gap. NOT for making a page look distinctive or matching a cloned product's look (that's frontend-design); NOT for scaffolding the Vite+React skeleton (ui-bootstrap). Pairs with frontend-design, ui-bootstrap, and api-contract-guard (the data the UI renders).
---

# UI/UX Review

Use this skill when designing or reviewing pages, components, and flows for correctness and usability.

## env-gen integration

- You run as the **frontend** lane (self-review before sign-off) or as a **reviewer** doing `codehub_review_pr`. State-coverage and hierarchy gaps are exactly what a reviewer should reject.
- Your review backstops `validation:ui_smoke` and `validation:ui_flow:<flow>` (recorded via `codehub_record_check`, aggregated by the delivery gate `_validate_delivery_gate`). A flow that renders but has no empty/error state passes the smoke check yet is still a UX defect — catch it here.
- File concrete defects as `bug_create` (eventhub) tied to the component/file, not vague aesthetic notes.

## Core checks

1. Start with hierarchy:
   - one primary action per view
   - obvious page title and section grouping
   - clear visual contrast between primary, secondary, and passive controls
2. Check consistency:
   - spacing follows a small reusable scale
   - typography has distinct heading/body/caption levels
   - button variants and form controls are reused rather than re-invented
3. Check states:
   - loading, empty, error, success, and disabled states all exist where needed *(a screen can pass `validation:ui_smoke` while still missing its empty/error state — that's the gap this review catches)*
   - interactive controls have hover/focus/active feedback
4. Check responsive behavior:
   - layout does not depend on one viewport width
   - cards, tables, and forms remain usable on narrower screens

## Not this skill

- **Distinctiveness / production-grade look, font/color/motion choices, or matching a *cloned* product** → `frontend-design` (reference-fidelity under `visual_review_gate` / `visual_similarity` lives there, not here). This skill is craft-agnostic structure: hierarchy, states, consistency, responsiveness.
- **Scaffolding the Vite+React skeleton, api.js, tenant picker, nginx proxy** → `ui-bootstrap`.
- **The shape/fields of the data a screen renders** (and its failure payloads, which the empty/error states depend on) → `api-contract-guard`.

## Output expectations

- When writing specs, include explicit notes for spacing, hierarchy, empty/error states, and responsive behavior.
- When reviewing (as a reviewer via `codehub_review_pr`, or self-reviewing in the frontend lane), cite concrete problems tied to a file/component and the specific missing state or hierarchy issue — not generic aesthetic opinions. Defer look-and-feel / clone-fidelity verdicts to `frontend-design`.
- Prefer small, reusable design-system decisions over one-off visual tweaks.
