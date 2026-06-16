# Known Deferred (EXT) Register — env-gen

Single canonical registry for items intentionally deferred to a follow-up
PR / EXT phase. Each entry has a stable id, a scope, and a clear close-out
condition so future-me and future-R1/R2 can hit one source rather than
re-discovering the deferral by archaeology.

**Rule:** if a deferred item is referenced anywhere else (sysadmin ticket,
plan doc, SHIPPED disclosure, this-file SHA-pin), the reference is by `EXT-id`
and points back here. This file is the single source of truth.

**Cross-referenced from:**
- `docs/sysadmin_ticket_docker_upgrade.md` §9 — bullets `EXT-RUNTIME-001` (the host-upgrade ticket itself is the executor for several EXT items)
- `docs/progressive_elaboration_refactor.md` Phase 0.2 SHIPPED disclosure — `EXT-SEC-CALL-AUTH-001`
- `agent/tests/test_monitor_call_gate_invariant.py` `KNOWN_DEFERRED_TO_EXT` frozenset — pinned to `EXT-SEC-CALL-AUTH-001`

---

## EXT-SEC-EXEC-SHELL-001 — `shell=True` on the build/exec subprocess paths

**Scope:** `agent/env_generator/llm_generator/tools/runtime_tools.py:272` (process_start; long-running servers — Popen with shell=True) + `:1036` (ExecuteBashTool sudo branch) + `:1048` (ExecuteBashTool non-sudo branch).

**Surfaced by:** R1 round-12 pre-pilot review (during pilot Day 1 routing).

**Why deferred:** local/loopback build context; same EXT-ish posture as the original Phase 0.2 security review's local-trust-boundary assumption. Fix A (the round-11 BuildKit determinism pin at the same call sites) neutralized the determinism risk; the `shell=True` injection risk is a separate concern that does not block pilot.

**Risk if not closed:** shell metacharacter injection via agent-controlled command strings (e.g., agent constructs `execute_bash(f"docker compose -f {user_provided_path} build")` with metachars in `user_provided_path`). Mitigated today by:
- shell=True paths run under the loopback-only auth boundary (Phase 0.2 SHIPPED disclosure)
- ExecuteBashTool already restricts to non-interactive sudo with `sudo -n`
- env-gen pipeline agents are trusted local components, not attacker-controlled

**Close-out condition:** replace `shell=True` with `shell=False` + token-list `subprocess.run([...])` invocation, OR keep `shell=True` only with a documented `shlex.quote`-enforced sanitizer wrapper for any agent-supplied argument. Add a structural invariant test (`agent/tests/test_runtime_shell_safety.py`) that fails if either site reintroduces unquoted agent-supplied substitution.

**Related EXT items:** `EXT-SEC-CALL-AUTH-001` (broader unauth control-plane chain — different posture, same risk class).

---

## EXT-SEC-CALL-AUTH-001 — Monitor `*_call` mutation chain (unauthenticated)

**Scope:** ~53 monitor mutation paths enumerated by `KNOWN_DEFERRED_TO_EXT` frozenset in `agent/tests/test_monitor_call_gate_invariant.py`. The chain is open → approve → merge across multiple monitor endpoints; per-call authz is missing.

**Surfaced by:** Phase 0.2 review rounds 4-5 (R1+R2). Closed-by-construction reasoning showed exhaustive per-endpoint authz adds is the structural pin; the 53-set is the temporary enumeration until that lands.

**Why deferred:** Phase 0.2 shipped (commit `47fea645`, 2026-05-30) with the **narrow** scope: structural write-gate invariants (tool/method/monitor layer) + class-level base fail-closed + bidirectional acceptance tests. The 53-set is the deferred-to-EXT slice that the structural invariants point at but don't gate.

**Risk if not closed:** monitor control plane is unauthenticated; safe only bound to loopback for a single trusted local user. Off-loopback `--host` requires `ENVGEN_AUTH_TOKEN`. See Phase 0.2 SHIPPED disclosure for the verbatim language.

**Close-out condition:** Phase 0.2-EXT security PR — full per-call authz on every `*_call` mutation; remove `KNOWN_DEFERRED_TO_EXT` set (or shrink to empty); the bidirectional acceptance invariant in `test_monitor_call_gate_invariant.py` flips from "53 known" to "0 unauthenticated mutations".

**Verification artifact pinned:** `KNOWN_DEFERRED_TO_EXT` frozenset (cardinality 53 as of `47fea645`). Pin-count set-equality invariant catches drift in either direction.

---

## EXT-INFRA-DOCKER-DAEMON-001 — Host Docker daemon + kernel HWE upgrade

**Scope:** `docs/sysadmin_ticket_docker_upgrade.md` is the executor; this entry is the EXT-register anchor.

**Surfaced by:** Round-11 spike diagnostic workflow `wyqzbwmt3` + post-fix briefing `docs/spike_r2_postfix_briefing.md`. Host: Docker CE 20.10.8 (2021-07) + Ubuntu 20.04 Focal-ESM + kernel 5.11.0-37 HWE + custom seccomp-allow-all + cgroup v1 → deterministic BuildKit fork/exec/thread failures on hand-written Dockerfiles.

**Why deferred:** durable fix not pilot-blocking. Pilot proceeds via Fix A (DOCKER_BUILDKIT=0 narrow-scoped on the 5 pipeline build subprocess sites — runhub/compose.py + docker_tools.py + database_tools.py + 2× runtime_tools.py) + post-generation Dockerfile lint at the canonical-file-tools chokepoint. Sysadmin handoff blocked by: 94% root disk, 17+ live tenant containers, no passwordless sudo for haibotong.

**Risk if not closed:** Docker 28.x + cgroup v2 + default seccomp profile not benefited; openenv subtree's `RUN --mount=type=cache` BuildKit-only syntax remains unbuildable on this host (today narrowly scoped out of env-gen's path; will bite if env-gen ever generates onto openenv base images).

**Close-out condition:** sysadmin ticket DoD (`docs/sysadmin_ticket_docker_upgrade.md` §8) satisfied — including the BuildKit-on-default-builder smoke check that gates whether the env-gen `DOCKER_BUILDKIT=0` override can be dropped post-upgrade.

**Related EXT items:** `EXT-SEC-EXEC-SHELL-001` (same call sites, different risk dimension).

---

## Register maintenance

- Adding an entry: pick a stable id (`EXT-<area>-<kind>-NNN`), fill all five sections (Scope / Surfaced by / Why deferred / Risk / Close-out), and cross-reference from any other doc that currently mentions the deferral.
- Closing an entry: leave the entry in place with a **CLOSED** banner + the closing commit SHA + date; do NOT delete (the audit trail is the value).
- Discovery during review: if an R1/R2 review mentions an EXT-class item, add the entry here in the same routing-back loop. Otherwise it evaporates ("keeps resurfacing" — R1 round-12).
