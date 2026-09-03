---
name: frontend-design
description: Use when building or styling a frontend page/component in a generated env and it needs to look production-grade rather than generic "AI slop" — about to write UI markup/CSS, choose fonts/color/layout/motion, or polish a page that looks default or templated; and when cloning a real product to fidelity against reference_images/ under visual_review_gate / visual_similarity. Triggers on "build the X page/dashboard/landing", "make the UI look real/polished/like Facebook", "style this component", and bland/cookie-cutter output. For the frontend lane; this is the aesthetics/fidelity skill — for state/hierarchy/spacing review use ui-ux-review, for the Vite+React skeleton use ui-bootstrap.
---

# Frontend Design

Create distinctive, production-grade frontend interfaces that avoid generic "AI slop" aesthetics. Implement real, working code with exceptional attention to aesthetic detail.

## env-gen FIRST: reference fidelity outranks distinctiveness

env-gen often generates an env that **clones a real product** (e.g. Facebook / Slack / PayPal). When a visual target exists, fidelity to it is the goal — NOT novelty.

**If the env has a visual target** — `reference_images/` for this env, a target product named in the task/spec, or the run is gated by `visual_review_gate` / `visual_similarity` / a `validation:ui_smoke` visual check — then:
- **Match the reference**: same layout, branding, color system, type feel, component shapes, and information density as the real product.
- Do **not** "reinterpret" it (a Facebook clone is not a brutalist art-deco redesign). Reinterpretation fails the visual gate.
- The "BOLD / never converge / be UNFORGETTABLE" guidance below does **NOT** apply here. Apply only the *craft* parts (clean typography rendering, real states, motion restraint, depth) in service of looking like the real thing.

**If the env is novel** (no reference product, no visual target) — then commit to a distinctive aesthetic per the rest of this skill.

When unsure which case you're in, check for `reference_images/` and the env's spec; if a real product is named, treat it as a clone.

## Design Thinking (novel envs)

Before coding, commit to a clear aesthetic direction:
- **Purpose**: What problem does this interface solve? Who uses it?
- **Tone**: Pick an extreme and execute it precisely — brutally minimal, maximalist, retro-futuristic, organic, luxury/refined, editorial, brutalist, art-deco/geometric, soft/pastel, industrial, etc.
- **Constraints**: Framework (env-gen frontends are Vite + React — see `ui-bootstrap`), performance, accessibility.
- **Differentiation**: What's the one thing someone will remember?

**CRITICAL**: Choose a clear conceptual direction and execute with precision. Bold maximalism and refined minimalism both work — the key is intentionality, not intensity.

Then implement working code that is production-grade and functional, visually striking, cohesive, and meticulously refined.

## Frontend Aesthetics Guidelines

These improve polish for BOTH clones and novel envs (for clones, every choice defers to the reference):

- **Typography**: Beautiful, distinctive, characterful fonts. Avoid generic defaults (Arial, Inter, system fonts) unless the cloned product uses them. Pair a display font with a refined body font.
- **Color & Theme**: Commit to a cohesive system via CSS variables. Dominant colors with sharp accents beat timid, evenly-distributed palettes.
- **Motion**: Animations for effects and micro-interactions. Prefer CSS-only for plain HTML; use the Motion library for React when available. High-impact moments (one orchestrated page-load with staggered `animation-delay` reveals) beat scattered micro-interactions. Surprising hover/scroll states.
- **Spatial Composition**: Unexpected layouts — asymmetry, overlap, diagonal flow, grid-breaking elements, generous negative space OR controlled density.
- **Backgrounds & Depth**: Atmosphere over flat solids — gradient meshes, noise/grain textures, geometric patterns, layered transparencies, dramatic shadows, decorative borders, custom cursors.

Always cover the real states (loading / empty / error / disabled / success) and responsive behavior — see `ui-ux-review`.

NEVER ship generic AI-generated aesthetics: overused fonts (Inter, Roboto, Arial, system), cliché schemes (purple gradients on white), predictable layouts, cookie-cutter patterns lacking context. For **novel** envs, vary between light/dark, fonts, and aesthetics across generations — never converge on one common look (e.g. always Space Grotesk).

**IMPORTANT**: Match implementation complexity to the aesthetic vision. Maximalist designs need elaborate code + animation; minimalist designs need restraint, precision, and careful spacing/typography. Elegance comes from executing the vision well.

## env-gen integration

- You are the **frontend** lane. Stack is Vite + React with the standard `api.js` wrapper — scaffold with `ui-bootstrap` first if the skeleton doesn't exist.
- Run `ui-ux-review` before sign-off (hierarchy, spacing, state coverage, consistency).
- **A prop the component does not destructure is silently dropped.** React raises nothing for it:
  no console error, no failed request, no crash — so every gate stays green while the feature does
  nothing. Measured across 117 generated environments: **152 such props in 47 of them**, e.g.
  `<PostHeader createdAt>` where PostHeader takes `{user}` (no timestamp ever renders),
  `<LoginForm setToken>` where it takes `{setIsRegister}` (the token is never stored),
  `<NetflixChrome title subtitle>` where it takes `{children, activeLabel}` (the page heading is
  simply absent). Whenever you pass a prop, open the component and confirm it is in the
  destructuring AND used. This is the single most common way a generated app looks finished and
  is not.
- **A page written inline gets replaced; a page built from `../components/` is kept.** The framework
  projects a page for every registered `ui_page` on every scaffold pass. It cannot tell a rich page
  it did not write from a stub, so it takes the file back — unless the page imports from
  `../components/`, which is the signal it defers to (#914/#1020). Measured: netflix-r32's
  138-line GenresPage was replaced by a 66-line projection three times, and that lane's version
  now survives in neither worktree nor any branch. Put the page body in a component under
  `src/components/`, import it, and render it from a thin page. The same content then survives
  every later pass, and it is also what fixes a `COMPONENT DRIFT` finding — one action, both
  problems.
- Your output is checked by `validation:ui_smoke` / `validation:ui_flow:*` and, for clones, the `visual_review_gate` / `visual_similarity` against `reference_images/`. Design to pass those, not just to look good in isolation.

Don't hold back on craft — but for a clone, the most impressive result is one indistinguishable from the real product.

---
*Adapted for env-gen from `anthropics/claude-code` `frontend-design` plugin skill (see that repo's LICENSE). env-gen reference-fidelity guidance added because env-gen clones real products under a visual-similarity gate.*
