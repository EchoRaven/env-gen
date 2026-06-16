# Sysadmin Ticket: Upgrade Host Docker Daemon + Kernel HWE Stack

**Owner of record (requester):** haibotong@virtueai.com
**Target executor:** host sysadmin with root + tenant-coordination authority
**Filed:** 2026-05-30
**Source of truth:** diagnostic workflow `wyqzbwmt3` (synthesizer + adversarial revise), R2 round-11 review.
**Priority:** Medium — not pilot-blocking (env-gen has a narrow workaround). True durable fix; do not let this slip indefinitely.

---

## 1. TL;DR

The host's Docker daemon (20.10.8, July 2021) running on Ubuntu 20.04 Focal (post-EOL ESM) with HWE kernel 5.11.0-37 is the root cause of repeated `BuildKit` failures on hand-written Dockerfiles (0/5 success in the spike). The env-gen pilot has a narrow, in-pipeline workaround — `DOCKER_BUILDKIT=0` plus a post-generation lint to keep templates free of BuildKit-only constructs — so this is **not pilot-blocking**. However, the workaround is not the durable fix: any future env-gen target that needs BuildKit features (e.g. `RUN --mount=type=cache`, already used in the openenv subtree) will fail until the host is upgraded. The upgrade requires a maintenance window with tenant sign-off (17+ live containers, including a long-running eval pool job and red-team workloads), disk reclamation work, and at least one separate follow-up window to safely retire the `seccomp-allow-all` profile. haibotong cannot execute this unilaterally: not in the `docker` group, no passwordless sudo, no authority to coordinate other tenants' downtime.

---

## 2. Current state (verified)

All values below were captured from the diagnostic workflow on the production host.

| Component | Observed | Notes |
|---|---|---|
| Docker CE | **20.10.8** (build 3967b7d) | released 2021-07; ~5 years stale |
| containerd | bundled with above | ditto |
| OS | **Ubuntu 20.04.3 LTS (Focal)** | standard support EOL April 2025; on ESM |
| Kernel | **5.11.0-37-generic** (HWE) | HWE 5.11 line EOL; current Focal HWE is 5.15 |
| cgroup driver | **cgroup v1** primary | v2 not enabled |
| seccomp profile | **custom allow-all** | broad security relaxation, predates current ops |
| Docker socket perms | **chmod 0666 /var/run/docker.sock** | world-writable; effectively root-equivalent for any user |
| Live containers | **17+** | red-team, whatsapp eval pools (job 1724244), robinhood, x-x, paypal [×2 unhealthy], gdocs, ... |
| `/dev/sda2` | **94% full** (1.6T / 1.8T, ~109G free) | will block kernel/docker package install if not reclaimed first |
| haibotong perms | **not in `docker` group; no passwordless sudo** | cannot self-serve any of this |
| apt sources | nvidia-*.list points at **ubuntu18.04** path on a focal host; `docker.list` duplicated | will misbehave on `apt update` |

---

## 3. Why it matters / what fails without the upgrade

- **Spike result (env-gen, Phase 0.2):** 0/5 BuildKit success on hand-written Dockerfiles. The failure mode is `fork`/`exec`/thread creation errors during `pip`, `apt`, and `npm` install steps — the combination of Docker 20.10.8 + kernel 5.11 + the allow-all seccomp profile triggers it. Standard remediations (clamping `MAKEFLAGS`, `--ulimit nofile`, retrying) did not fix it.
- **Pilot workaround (already in place, narrow):** env-gen pipeline forces `DOCKER_BUILDKIT=0` for runner builds, *and* a post-generation lint enforces that templates emit zero BuildKit-only constructs (`--mount=type=cache`, heredocs, `--mount=type=secret`, etc.). 31/31 demos build under the classic builder. This works because env-gen's generated Dockerfiles are deliberately classic-syntax-only.
- **Where the workaround does NOT save us:** the `openenv` subtree (vendored upstream) *does* use `RUN --mount=type=cache`. If a future env-gen target builds or rebases on an openenv image on this host, the classic builder will fail and there is no clean retry. Today the blast radius is scoped to the env-gen runner only — that scope will grow.
- **Security debt:** `seccomp=unconfined`-equivalent (allow-all) plus `0666` on the daemon socket is a real, broad security relaxation. The allow-all profile is likely load-bearing for some red-team workloads (bpf/perf/ptrace syscalls). Reverting it is not a one-line fix; it needs a per-workload syscall audit. That work is **separate** from this ticket.

---

## 4. Pre-upgrade BLOCKERS (must clear before scheduling the window)

These are gates. Do not schedule the maintenance window until all are green.

1. **Disk reclamation.** `/dev/sda2` at 94%. Operator-reviewed prune required:
   - `docker volume ls` shows 183 volumes — many likely orphaned. Operator must confirm before `docker volume prune`.
   - `docker image prune -a` on un-tagged / dangling images.
   - Target: `/var/lib/docker` usage <85% before kernel/Docker package install begins.
2. **Owner-of-record map for every live container.** See §7 below. At minimum: job 1724244 (whatsapp eval pool), red-team containers, both unhealthy paypal containers.
3. **Investigate the 2 unhealthy paypal containers** *separately* from this ticket. They are not caused by the upgrade, but the upgrade reboot will restart them; we want to know now whether they will come back healthy.
4. **Fix apt sources** (this is cheap and lowers reboot risk):
   - `/etc/apt/sources.list.d/nvidia-*.list` currently references `ubuntu18.04` on a focal host — repoint to `ubuntu20.04`.
   - `/etc/apt/sources.list.d/docker.list` is duplicated — dedupe.
   - Run `apt update` and confirm zero 404s before scheduling.

---

## 5. Proposed upgrade steps

Derived from the diagnostic workflow synthesizer plan, **with the adversarial-revise corrections applied** (downtime estimate raised from 45min to 90-120min; seccomp removal split into its own window; cgroup v2 deferred).

### Step 0 — already done (no action for sysadmin)
env-gen pilot proceeds with `DOCKER_BUILDKIT=0` narrowly scoped to runner builds, plus post-gen lint blocking BuildKit-only template constructs. Implementer has shipped this.

### Step 1 — Reclaim disk (pre-window, with operator)
- Operator-reviewed prune of the 183 volumes.
- `docker image prune -a`, `docker builder prune`.
- **Target:** `/var/lib/docker` <85%.
- **Risk:** accidentally pruning a volume that an offline tenant still owns. **Mitigation:** name-by-name operator review before any `prune`; keep a 7-day off-host backup of `docker volume ls -q` output.
- **Rollback:** restore from the volume-name list and tenant backups (per-tenant; not centrally restorable).

### Step 2 — Fix apt sources (pre-window)
- Repoint `nvidia-*.list` 18.04 → 20.04.
- Dedupe `docker.list`.
- `apt update`; require zero 404s.
- **Risk:** new repo URLs may still 404 if the user is on an unusual nvidia channel. **Mitigation:** dry-run, confirm package availability of `nvidia-driver-470` and `nvidia-docker2 2.13` from the corrected source *before* the window.
- **Rollback:** restore the `/etc/apt/sources.list.d/*.list` files from the snapshot taken in Step 3.

### Step 3 — Snapshot daemon state (pre-window)
Capture and off-host these artifacts:
- `/etc/docker/daemon.json`
- the custom seccomp profile (path referenced from daemon.json)
- any systemd drop-ins under `/etc/systemd/system/docker.service.d/`
- `docker info` and `docker version` full output
- `docker ps -a --format ...` (full container inventory with image, mounts, restart policy)
- `/etc/apt/sources.list.d/*.list`
- **Risk:** missing a drop-in means post-upgrade daemon comes up with different flags. **Mitigation:** also `systemctl cat docker.service` and store its output.
- **Rollback:** these snapshots are the rollback path for steps 5-8.

### Step 4 — Schedule maintenance window with tenant owners
- **Downtime estimate: 90-120 minutes**, not 45 (adversarial-revise: factoring in nvidia driver reinstall, reboot, and per-container restart verification).
- All tenants from §7 must acknowledge in writing.
- Quiesce workloads — gracefully stop, do not just `docker kill`.
- **Risk:** job 1724244 (whatsapp eval pool) may be mid-run; killing it loses progress. **Mitigation:** owner sign-off includes "safe to interrupt at time T".
- **Rollback:** none needed — workloads are quiesced, not modified.

### Step 5 — Kernel upgrade
- `apt autoremove` old kernel 5.8.0-43 (frees ~200-300MB; required for headroom).
- `apt install linux-image-generic-hwe-20.04` → kernel 5.15.
- Do NOT reboot yet (combine with Step 6).
- **Risk:** kernel install fails for disk space → mitigated by Step 1. New kernel fails to boot → mitigated by GRUB still listing 5.11 as fallback.
- **Rollback:** boot the previous kernel from GRUB menu, `apt remove` the new one, reinstate.

### Step 6 — Docker + nvidia stack upgrade
Install (versions per adversarial-revise; confirm exact patch with `apt madison` at execution time):
- `docker-ce 28.1.1`
- `containerd.io 1.7.27`
- `docker-buildx-plugin`
- `docker-compose-plugin`
- `nvidia-docker2 2.13`
- `nvidia-kernel-common-470`
- `nvidia-driver-470`
- **Risk:** new daemon comes up with different defaults; in particular Docker 28 changes some defaults around `live-restore` and logging. **Mitigation:** restore `/etc/docker/daemon.json` from Step 3 snapshot, then `systemctl restart docker`.
- **Rollback:** `apt install docker-ce=5:20.10.8~* containerd.io=1.4.*` etc., pinned to versions captured in Step 3 snapshot; reboot to previous kernel via GRUB.

### Step 7 — Reboot and verify
- Reboot.
- Verify: `nvidia-smi` returns expected GPUs, `docker version` shows 28.x server + client, `docker info` shows cgroup driver still v1.
- **cgroup v2 migration is OUT OF SCOPE for this ticket** (separate optional ticket — many of the workloads have not been validated under v2).
- **Risk:** nvidia driver fails to load against the new kernel. **Mitigation:** `dkms status` check; rollback path is to boot 5.11 again.
- **Rollback:** GRUB → 5.11 kernel; `apt install` previous docker-ce / containerd versions.

### Step 8a — Same window: tighten socket perms
- Drop `chmod 0666 /var/run/docker.sock`.
- Restore mode `0660`, group `docker`.
- Add the actual human users (haibotong, and any others identified during tenant coordination) to the `docker` group.
- **Risk:** scripts that relied on world-writable socket break. **Mitigation:** grep `/etc` and tenant home dirs for `chmod 0666 .*docker.sock` before the window; flag offenders to their owners.
- **Rollback:** `chmod 0666 /var/run/docker.sock` (trivial).

### Step 8b — SEPARATE later window: remove seccomp-allow-all
- **Do NOT bundle this with Step 8a.** Requires per-workload syscall audit first.
- Allow-all is almost certainly load-bearing for red-team workloads using `bpf`, `perf_event_open`, `ptrace`, raw sockets, etc.
- Tenant sign-off needed, plus an audit (`strace` or seccomp-bpf logging) of every tenant container.
- This is a *follow-up ticket*, not part of this one.

### Step 9 — Validate env-gen pilot under new daemon
- After Step 7, run the env-gen pilot **without** `DOCKER_BUILDKIT=0` on Docker 28.x.
- Expectation: it works, because the generated Dockerfiles are classic-syntax-only and BuildKit 28.x accepts that strict subset.
- If it works: file a follow-up to drop the `DOCKER_BUILDKIT=0` runner-build override (lint should stay; it's cheap insurance).
- If it doesn't work: keep the override, file a fresh investigation ticket.

---

## 6. Risk + rollback summary

| Step | Primary risk | Mitigation | Rollback |
|---|---|---|---|
| 1 | Prune destroys an owned volume | Operator name-by-name review; off-host `volume ls` backup | Per-tenant restore from their own backups |
| 2 | apt source still 404s after fix | Dry-run before window | Restore `*.list` from snapshot |
| 3 | Missed drop-in / config | `systemctl cat` + drop-in dir capture | N/A (snapshot is the rollback) |
| 4 | Workload mid-flight when killed | Owner-signed "safe to interrupt at T" | N/A |
| 5 | New kernel won't boot | GRUB keeps 5.11 | GRUB menu → 5.11 |
| 6 | Docker 28 default change breaks tenant | Restore `daemon.json` from snapshot | Pin-reinstall old versions |
| 7 | nvidia driver / kernel mismatch | `dkms status` check | GRUB → 5.11 + old packages |
| 8a | Script depended on 0666 socket | Pre-window grep for `chmod 0666` on socket | `chmod 0666` again |
| 8b | Tenant workload depends on allow-all syscall | Per-workload syscall audit before this step | Restore allow-all profile |
| 9 | Pilot fails on 28.x classic builder | Lint kept; rare given strict subset | Re-enable `DOCKER_BUILDKIT=0` |

---

## 7. Tenant coordination — container inventory + owner-of-record

Best-known mapping at filing time. Sysadmin must confirm and fill in every `?` before scheduling.

| Container (name / pattern) | Best-known owner | Notes |
|---|---|---|
| `red-team-*` | red-team workstream lead (?) | Likely depends on seccomp-allow-all — confirm before Step 8b |
| `whatsapp` eval pool, **job 1724244** | eval pools owner (?) | Long-running; needs explicit "safe to interrupt at T" |
| `robinhood-*` | ? | |
| `x-x` (a.k.a. `twitter-x`?) | ? | |
| `paypal-*` (×2) | ? | Both currently **unhealthy** — investigate *before* upgrade |
| `gdocs-*` | ? | |
| (remaining containers from `docker ps` not enumerated here) | ? | Sysadmin to complete from live `docker ps` at window-scheduling time |

Action: sysadmin owns building this table. haibotong does not have visibility into other tenants' workstreams.

---

## 8. Definition of Done

All of the following must be true at ticket close:

- [ ] `/dev/sda2` usage <85%; `/var/lib/docker` usage <85%.
- [ ] `apt update` returns zero 404s; nvidia + docker repos resolve correctly for Focal.
- [ ] Kernel is 5.15.x HWE; previous kernel 5.8.0-43 removed; 5.11 retained as GRUB fallback for at least 14 days.
- [ ] `docker version` shows server **28.x** + matching client; `containerd 1.7.x`.
- [ ] `docker info` confirms cgroup driver v1 (v2 migration deferred — see §9).
- [ ] `nvidia-smi` returns all expected GPUs with driver 470.
- [ ] All containers from §7 are restarted; their owners have signed off that they are healthy. The 2 previously-unhealthy paypal containers have a known status (healthy, or filed under a separate fix ticket).
- [ ] `/var/run/docker.sock` is mode `0660`, group `docker`; haibotong + any other identified human users are in the `docker` group; `chmod 0666` on the socket is gone.
- [ ] env-gen pilot has been run on the new daemon, both **with** and **without** `DOCKER_BUILDKIT=0`. Results are recorded in this ticket. If BuildKit works, a follow-up to drop the override is filed.
- [ ] **BuildKit-on-default-builder smoke** (the spike's positive test: hand-written Dockerfile builds via `docker compose up --build` without `DOCKER_BUILDKIT=0` and without fork/exec errors) passes on the upgraded daemon. If it fails even on Docker 28.x with the new kernel, the seccomp-allow-all removal (Step 8b follow-up) becomes the *next* required follow-up before the env-gen `DOCKER_BUILDKIT=0` override can be dropped. (Per pre-pilot workflow `wdk87hg1c` adversarial verifier.)
- [ ] Snapshots from Step 3 are archived off-host with a documented restore path.
- [ ] Two follow-up tickets are filed (see §9).
- [ ] No regressions reported by any tenant within 7 days of the window closing.

---

## 9. NOT in scope of this ticket (file as separate follow-ups)

- **cgroup v2 migration.** Many workloads have not been validated under v2. Treat as a separate optional ticket *after* this upgrade has bedded in.
- **Default seccomp rollout (removing allow-all).** Requires per-workload syscall audit and tenant sign-off — see Step 8b. Separate ticket.
- **Migration from `nvidia-docker2` to modern `nvidia-container-toolkit`.** `nvidia-docker2` is deprecated upstream but still works; not blocking. Separate ticket.
- Any env-gen-side changes. The pipeline workaround and lint are already merged and are not part of the sysadmin's work.

---

## 10. References

- Diagnostic workflow: `wyqzbwmt3` (synthesizer plan + adversarial revise).
- R2 round-11 review note: "host 升级 = 真正的耐久解,但非 pilot-blocking ... defer 合理,但记成一张明确的 sysadmin ticket,别无限期".
- Spike result: 0/5 BuildKit success, env-gen Phase 0.2 (shipped 2026-05-30).
- Related env-gen docs: `docs/phase_0_2_gate_validation.md`, `docs/spike_r2_postfix_briefing.md`.
