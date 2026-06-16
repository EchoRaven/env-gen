"""Pilot failure classifier — implementation of docs/pilot_classifier_spec.md §3-§5.

Pure function from a FailureContext (assembled by runner.py at the moment of
failure) to a Verdict. NO side effects, NO docker calls, NO log reading — the
runner gathers evidence; the classifier judges. This separation makes the
acceptance tests in test_classifier_acceptance.py independently exercise
every §3 signature + negative guard without needing real docker.

Evaluation order (load-bearing per spec §1):
  Step 0: Oracle JUnit <failure> → FUNCTIONAL unconditional (the flow-assertion
          result IS the signal; no env signature may swallow it).
  Step 1: Own-cgroup OOM carve-out → FUNCTIONAL (evaluated BEFORE env.oom).
  Step 2: §3 ENV signatures in id order (first match wins, after guard clears).
  Step 3: Terminal default → FUNCTIONAL.

Spec SHA (DRAFT pin): a048316b (committed 2026-05-30). Every Verdict carries
classifier_spec_sha so post-freeze amendments are detectable in data.

R1 round-14 (this commit, still DRAFT — closes round-4 daemon_down sentinel):
  - env.daemon_down: removed the "back-compat / transitional sentinel /
    legacy post-hoc retries" path that emitted env when
    daemon_up_at_failure_time was None but 3 docker_version_retries failed.
    That path contradicted spec §3 row 228 (False is a hard AND-conjunct,
    not a fallback) and §3 prereq #5 ("Post-hoc docker version retries are
    corroborating evidence only, never gating"). On a CI host without
    systemctl + 3 transient docker-version blips the path silently inflated
    as env.daemon_down. Closed: when daemon_up_at_failure_time is None or
    True, _check_daemon_down returns None (→ functional default).
    Pinned by V_round5_daemon_down_no_T0_probe_retries_all_fail_is_functional.

R1 round-12 remediation:
  - B-1/B-7: env.daemon_down requires daemon_up_at_failure_time=False (T+0
    synchronous measurement); raw_evidence excluded; negative-guard adds
    `Error response from daemon:`; step-0 uses element-presence sentinel.
  - B-2: env.image_pull negative guard extended (`: not found`, `insufficient_scope`,
    `denied`, bare `403`, `error pulling image configuration`).
  - B-3: env.oom consults docker_inspect_state.OOMKilled (authoritative);
    own-cgroup carve-out short-circuits when OOMKilled==True.
  - B-3a (R1 round-13): env.oom honors OOMKilled=False as the daemon's
    authoritative veto in the opposite direction — when the daemon says
    this container was NOT OOMKilled, a parallel host CONSTRAINT_NONE
    window is co-tenant noise that didn't target us → FUNCTIONAL.
  - B-3b (R1 round-13): env.oom positive matching is restricted to the
    CONTAINER-EXIT channel (transport stderr OR
    docker_inspect_state.ExitCode==137); raw_evidence (compose-logs /
    app output) is NEVER sufficient on its own. Closes the "documented
    exception" channel-provenance hole that let app-emitted '137 Killed'
    text launder into env/env.oom under a noisy-neighbor host
    CONSTRAINT_NONE window.
  - B-3c (R2 round-13): env.oom requires the runner to have injected a
    symmetric mem_limit (FailureContext.runner_injected_mem_limit). Without
    that, dmesg CONSTRAINT_NONE is structurally indistinguishable from an
    app self-leak escaping to host pressure; default → FUNCTIONAL.
  - B-4: env.disk_full requires df ≥90% corroboration; RUN-step ENOSPC is
    precedence-stealer; tar/register paths require /var/lib/docker/ scope.
  - B-5: buildkit_recurrence node variant requires SIGABRT + RUN-step prefix.
  - B-6: env.daemon_5xx DELETED entirely (R1 round-12 — channel-provenance
    laundering vector with no transport discriminator).
  - Channel provenance: env signatures match only build_stderr + up_stderr
    (CLI transport buffers); raw_evidence excluded.
  - Latent: port_conflict positive regex requires literal injected port P.
  - B-8: Verdict schema extended to §2 (run_id/spec_id/arm/phase_reached/outcome);
    sink (append_to_sink) + ITT (compute_itt_delta) for §5.1 backstop.
"""

from __future__ import annotations

import json
import os
import re
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Tuple, Union


# Spec SHA — FROZEN 2026-05-30 after R1 round-14 CLEAR + R2 round-14 CLEAR.
#
# The DRAFT SHA was "a048316b-draft" (the original spec commit; see git log
# d787be79 → a048316b → de5aa82e → 00ce5a12 → 102ce90b → de05b9a9 → e50fe23f
# → 7ec7fee6 → 4c1c3370 for the full pre-registration paper trail).
#
# Bump rationale (per spec §6 freeze protocol + R1+R2 round-14 verdict):
#   - §6.1 criterion (1)-(4) satisfied: V green (197+/0), residual immaterial
#     (round-5 found dead-code hygiene only — R2 round-13 predicted floor),
#     §5.1 backstop in position (R1 round-14 independently verified ITT
#     evaporates a planted +25.7pp spurious win; asymmetry gate blocks),
#     wins gated on both rates.
#   - R1 round-14: "§6.1 (1)-(4) CLEAR on substance ... I co-sign the SHA-pin"
#     conditioned on the CI-import fix (commit 4c1c3370 — landed before this).
#   - R2 round-14: "FREEZE-READY" (all 4 R2 findings landed faithfully + spec
#     §6 freeze criterion is the round-13 meta-review encoded).
#
# Pin value = the SHA of commit 4c1c3370 (CI import fix landed on top of the
# round-4/5 + §6 substance commit e50fe23f). Every Verdict from this commit
# onward records this SHA. Post-freeze amendments per §6 require
# re-classification of all already-collected runs under the new SHA — the
# metric is never a mix of rulesets.
#
# Pinning to a parent SHA rather than the freeze commit's own SHA is the
# convention here (chicken-and-egg: the freeze commit can't reference its
# own not-yet-computed SHA). The freeze commit's diff IS this constant
# change + its commit message; readers diffing classifier.py see the
# state transition explicitly.
CLASSIFIER_SPEC_SHA = "4c1c3370"


@dataclass
class FailureContext:
    """All evidence the classifier needs. Assembled by runner.py at failure
    time; passed verbatim to classify(). Fields default to None / empty so
    fixtures only populate what's relevant to a given §3 / §4 case."""

    # §2 schema fields (NEW B-8 — runner populates, classifier passes through):
    run_id: str = ""               # uuid4 hex; runner assigns
    spec_id: str = "simple_blog"
    arm: str = "ab_new"            # known_good | known_broken | cross_stack_calibration | ab_old | ab_new | spike
    phase_reached: str = "app_build"  # infra_setup | app_build | app_runtime | oracle
    outcome: str = "fail"          # classifier only runs on failure; pass-rows synthesized at sink

    # Combined evidence stream (compose-logs / app stdout / etc — NOT used for
    # transport-channel env signatures per round-12 channel-provenance fix).
    raw_evidence: str = ""

    # Phase-specific docker-CLI stderr buffers. THESE are the env-eligible
    # transport buffers; raw_evidence is NEVER searched for env tokens.
    build_stderr: Optional[str] = None
    up_stderr: Optional[str] = None

    # Out-of-band probes (gathered at the moment of failure):
    dmesg_recent: Optional[str] = None
    df_var_lib_docker: Optional[str] = None
    docker_version_retries: List[Tuple[int, str]] = field(default_factory=list)
    docker_inspect_state: Optional[dict] = None
    docker_ps_filter_output: Optional[str] = None
    compose_project_name: Optional[str] = None

    # Daemon-window provenance (env.daemon_down — measured AT failure time, not after):
    # True = systemctl is-active reported `active` during the failure window.
    # False = explicit measurement that daemon was down at T+0.
    # None = no synchronous measurement available → conservative functional.
    daemon_up_at_failure_time: Optional[bool] = None
    journal_dockerd_window: Optional[str] = None

    # Port management (env.port_conflict admissibility):
    injected_port: Optional[int] = None
    retry_count: int = 0
    second_collision_on_free_port: bool = False
    foreign_holder_found: Optional[bool] = None
    reassign_retry_success: Optional[bool] = None

    # Oracle JUnit output:
    junit_failure_text: Optional[str] = None  # <failure>  → step-0 FUNCTIONAL
    junit_error_text: Optional[str] = None    # <error> in oracle code

    # Oracle infra control-group reproduction (for env.oracle_infra):
    reproduces_against_reference_impl: Optional[bool] = None

    # Compose-declared mem_limit (own-cgroup OOM carve-out):
    app_has_mem_limit: bool = False

    # R2 round-13 (RUNNER_MEM_LIMIT) by-construction: the symmetric mem_limit
    # the runner injected onto every app container for this run. When set,
    # env.oom evaluation may proceed (app self-leaks short-circuit via
    # step-1 own-cgroup carve-out so a surviving CONSTRAINT_NONE is
    # genuinely co-tenant). When None, env.oom defaults to FUNCTIONAL —
    # without symmetric injection, host CONSTRAINT_NONE is structurally
    # ambiguous between co-tenant pressure and app-self-leak.
    runner_injected_mem_limit: Optional[str] = None


@dataclass
class Verdict:
    """§2 schema verbatim. Every field maps 1:1 to spec §2 keys.

    `run_id`, `spec_id`, `arm`, `phase_reached`, `outcome` are runner-supplied
    via FailureContext; classify() copies them through verbatim so the JSONL
    sink can emit §2 rows without additional ceremony.
    """

    verdict: str  # functional | env | uncertain
    # §2 fields (passed through from FailureContext):
    run_id: str = ""
    spec_id: str = ""
    arm: str = ""
    phase_reached: str = ""
    outcome: str = "fail"
    # Existing fields:
    matched_signature: Optional[str] = None
    negative_guard_evidence: Optional[str] = None
    raw_evidence: str = ""
    retry_count: int = 0
    classifier_spec_sha: str = CLASSIFIER_SPEC_SHA

    def to_dict(self) -> dict:
        """Emit a dict whose key set EXACTLY matches the §2 schema."""
        return {
            "run_id": self.run_id,
            "spec_id": self.spec_id,
            "arm": self.arm,
            "phase_reached": self.phase_reached,
            "outcome": self.outcome,
            "verdict": self.verdict,
            "matched_signature": self.matched_signature,
            "raw_evidence": self.raw_evidence,
            "negative_guard_evidence": self.negative_guard_evidence,
            "retry_count": self.retry_count,
            "classifier_spec_sha": self.classifier_spec_sha,
        }


def synthesize_pass_verdict(
    *,
    run_id: str,
    spec_id: str,
    arm: str,
    phase_reached: str = "oracle",
    retry_count: int = 0,
) -> Verdict:
    """Runner uses this on pass-paths so the JSONL sink stores BOTH pass and
    fail rows. ITT counts total_runs per arm = passes + functional + env.
    classify() itself is failure-only (no fixture for pass-paths)."""
    return Verdict(
        verdict="pass",
        run_id=run_id,
        spec_id=spec_id,
        arm=arm,
        phase_reached=phase_reached,
        outcome="pass",
        retry_count=retry_count,
        raw_evidence="",
        matched_signature=None,
        negative_guard_evidence=None,
    )


# ---------------------------------------------------------------------------
# §3 signature checks. Each returns Verdict (env) on match OR None to fall
# through. The terminal default in classify() is FUNCTIONAL.
# ---------------------------------------------------------------------------

# Phase scopes — first match dictionary.
# env.daemon_5xx removed in R1 round-12 (channel-provenance laundering vector
# with no transport discriminator separable from app-printed 500 strings;
# genuine dockerd panics surface as env.daemon_down via socket dial failure
# corroborated by systemctl/journalctl probes the runner now collects).
_PHASES = {
    "env.daemon_down": ("infra_setup", "app_build"),
    "env.port_conflict": ("infra_setup", "app_runtime"),
    "env.image_pull": ("infra_setup", "app_build"),
    "env.oom": ("infra_setup", "app_build", "app_runtime", "oracle"),
    "env.disk_full": ("infra_setup", "app_build", "app_runtime", "oracle"),
    "env.buildkit_recurrence": ("app_build",),
    "env.oracle_infra": ("oracle",),
}


def _in_phase(ctx: FailureContext, sig_id: str) -> bool:
    return ctx.phase_reached in _PHASES[sig_id]


def _transport_stderr(ctx: FailureContext) -> str:
    """Channel-provenance helper (R1 round-12 cross-cutting fix).

    Returns the union of docker-CLI transport stderr buffers. env signatures
    that diagnose transport-level failure (daemon_down, image_pull, disk_full
    storage-driver path, port_conflict, buildkit_recurrence) must search ONLY
    this — never raw_evidence (which carries `docker compose logs` = app
    output and can launder transport-shaped strings into env verdicts).
    """
    return (ctx.build_stderr or "") + "\n" + (ctx.up_stderr or "")


def _populate_schema_kwargs(ctx: FailureContext) -> dict:
    """Common kwargs every Verdict construction inherits from FailureContext
    so §2 fields are carried through to the sink consistently."""
    return {
        "run_id": ctx.run_id,
        "spec_id": ctx.spec_id,
        "arm": ctx.arm,
        "phase_reached": ctx.phase_reached,
        "outcome": ctx.outcome,
    }


# env.daemon_down ----------------------------------------------------------

_DAEMON_DOWN_POSITIVE = re.compile(
    r"Cannot connect to the Docker daemon at unix://"
    r"|dial unix /var/run/docker\.sock: connect: "
    r"(permission denied|no such file or directory|connection refused)",
    re.IGNORECASE,
)
_DAEMON_DOWN_NEGATIVE = re.compile(
    r"executor failed running"
    r"|failed to solve"
    r"|returned a non-zero code"
    r"|The command '/bin/sh -c"
    r"|Cannot find module"
    r"|context deadline exceeded"
    r"|i/o timeout"
    r"|client timeout exceeded"
    r"|Error response from daemon:",   # NEW (B-1): daemon answered → daemon is up
    re.IGNORECASE,
)


def _check_daemon_down(ctx: FailureContext) -> Optional[Verdict]:
    if not _in_phase(ctx, "env.daemon_down"):
        return None
    # Channel provenance (B-1): ONLY look at CLI transport stderr.
    # raw_evidence carries `docker compose logs` (app output); searching it
    # would let an app's own debug print of "Cannot connect to the Docker
    # daemon at unix://" launder a functional bug into env.daemon_down.
    ev = _transport_stderr(ctx)
    if not _DAEMON_DOWN_POSITIVE.search(ev):
        return None
    if _DAEMON_DOWN_NEGATIVE.search(ev):
        return None
    # Tied-to-window guard (B-1, hardened R1 round-14): env.daemon_down is a
    # closed AND-conjunct on `daemon_up_at_failure_time is False`. This is the
    # ONLY admissible positive — there is NO fallback on `docker_version_retries`.
    #
    # Spec §3 row 228: `daemon_up_at_failure_time == False` is a hard
    # AND-conjunct, not a fallback.
    # Spec §3 prereq #5: "Post-hoc docker version retries are corroborating
    # evidence only, never gating."
    #
    # Round-13 closed the "back-compat / transitional sentinel / legacy post-hoc
    # retries path" hole that round-4 caught: on a CI host without systemctl,
    # 3 transient docker-version blips would silently inflate as env.daemon_down
    # despite no T+0 proof. The function now returns None (→ functional default)
    # whenever daemon_up_at_failure_time is None — corroborating retries may
    # appear in negative_guard_evidence for the False branch, never as a gate.
    if ctx.daemon_up_at_failure_time is not False:
        # is True  → daemon demonstrably up during failure window → functional.
        # is None  → no synchronous T+0 proof → functional (conservative).
        return None
    # daemon_up_at_failure_time is False → confirmed env.daemon_down.
    return Verdict(
        verdict="env",
        matched_signature="env.daemon_down",
        negative_guard_evidence=(
            "daemon_up_at_failure_time=False at T+0 (synchronous probe); "
            f"post-hoc docker version ×{len(ctx.docker_version_retries)} corroborates"
        ),
        raw_evidence=_excerpt(ev, _DAEMON_DOWN_POSITIVE),
        retry_count=ctx.retry_count,
        **_populate_schema_kwargs(ctx),
    )


# env.port_conflict --------------------------------------------------------

# R1 round-12 latent fix: every positive alternative MUST name the injected
# port literally. Bare-substring `port is already allocated` / `bind: address
# already in use` cannot satisfy the positive — an app self-inflicted
# collision on a different port can't launder into env.port_conflict.
def _build_port_conflict_pattern(port: int) -> re.Pattern:
    return re.compile(
        r"(?:Bind for 0\.0\.0\.0:{p}\b"
        r"|Bind for \[::\]:{p}\b"
        r"|listen tcp [^\n]*:{p}: bind: address already in use"
        r"|0\.0\.0\.0:{p}[^\n]{{0,80}}(?:port is already allocated|address already in use)"
        r"|:{p}\b[^\n]{{0,80}}(?:port is already allocated|address already in use))".format(p=port),
        re.IGNORECASE,
    )


EPHEMERAL_FLOOR = 32768  # Linux ip_local_port_range typical lower bound; spec mandates run-unique.


def _check_port_conflict(ctx: FailureContext) -> Optional[Verdict]:
    if not _in_phase(ctx, "env.port_conflict"):
        return None
    if ctx.injected_port is None or ctx.injected_port < EPHEMERAL_FLOOR:
        return None  # INADMISSIBLE → FUNCTIONAL (V9).
    ev = _transport_stderr(ctx)
    # Cheap pre-filter: the literal injected port must appear in transport stderr.
    if str(ctx.injected_port) not in ev:
        return None
    port_pat = _build_port_conflict_pattern(ctx.injected_port)
    if not port_pat.search(ev):
        return None
    # Foreign-holder check.
    if ctx.foreign_holder_found is False:
        return None  # Holder is in our own compose-project = self-inflicted (§4).
    if ctx.foreign_holder_found is None:
        return None  # No probe = ambiguous, default-functional preserves conservatism.
    # Second collision on a fresh verified-free port = app's own bug.
    if ctx.second_collision_on_free_port:
        return None  # V8 — free port can't be pre-owned, so the second collision is app fault.
    # Reassign-and-retry on fresh free port must SUCCEED.
    if ctx.reassign_retry_success is not True:
        return None
    return Verdict(
        verdict="env",
        matched_signature="env.port_conflict",
        negative_guard_evidence=(
            f"port {ctx.injected_port} held by foreign project; retry on free port succeeded"
        ),
        raw_evidence=_excerpt(ev, port_pat),
        retry_count=ctx.retry_count,
        **_populate_schema_kwargs(ctx),
    )


# env.image_pull -----------------------------------------------------------

_BASE_REGISTRY_HOSTS = re.compile(
    r"registry-1\.docker\.io"
    r"|index\.docker\.io"
    r"|ghcr\.io"
    r"|quay\.io"
    r"|gcr\.io"
    r"|[\w-]+\.dkr\.ecr\.[\w-]+\.amazonaws\.com"
    r"|[\w-]+-docker\.pkg\.dev"
    r"|mcr\.microsoft\.com"
    r"|public\.ecr\.aws",
    re.IGNORECASE,
)
_PACKAGE_INDEX_HOSTS = re.compile(
    r"pypi\.org"
    r"|files\.pythonhosted\.org"
    r"|registry\.npmjs\.org"
    r"|deb\.debian\.org"
    r"|archive\.ubuntu\.com"
    r"|security\.ubuntu\.com",
    re.IGNORECASE,
)
_IMAGE_PULL_TRANSIENT = re.compile(
    r"TLS handshake timeout"
    r"|dial tcp .*(i/o timeout|connection refused|no route to host)"
    r"|failed to (resolve|fetch) .*registry"
    r"|temporary failure in name resolution"
    r"|received unexpected HTTP status: (429|5\d\d)",
    re.IGNORECASE,
)
# Round-2 tightening (B-2): dockerd/containerd/BuildKit image-pull subsystem
# markers. The image_pull positive check now REQUIRES at least one of these
# strings to appear in transport_stderr — an app curl/wget that lands its
# stderr in build_stderr never emits these (they are dockerd/containerd
# internal phrases). This is a necessary condition gating the host+transient
# line check below.
_IMAGE_PULL_DOCKERD_MARKER = re.compile(
    r"failed to do request:"
    r"|failed to resolve reference"
    r"|failed to copy:"
    r"|failed to pull and unpack image"
    r"|pulling from"
    r"|error pulling image configuration"
    r"|getting image from registry"
    r"|image-manifest"
    r"|manifest-blob"
    r"|dockerd_pulling",
    re.IGNORECASE,
)
_IMAGE_PULL_GLOBAL_NEG = re.compile(
    r"manifest unknown"
    r"|pull access denied"
    r"|repository .* not found"
    r"|401 Unauthorized"
    r"|404 Not Found.*(manifest|blob)"
    r"|:\s*not found\b"                                              # NEW (B-2): ':vfake: not found' tail
    r"|insufficient_scope"                                           # NEW (B-2): OCI auth content
    r"|denied:\s*requested access to the resource is denied"         # NEW (B-2)
    r"|\b403\s+(Forbidden|denied)"                                   # NEW (B-2): bare HTTP 403 from registry
    r"|error pulling image configuration",                           # NEW (B-2): BuildKit wrapper
    re.IGNORECASE,
)


def _check_image_pull(ctx: FailureContext) -> Optional[Verdict]:
    if not _in_phase(ctx, "env.image_pull"):
        return None
    # Channel provenance (round-12): only docker-CLI transport stderr.
    ev = _transport_stderr(ctx)
    # Global negative: any of these anywhere → functional (V22, V23, V31-V35).
    if _IMAGE_PULL_GLOBAL_NEG.search(ev):
        return None
    # Round-2 (B-2) necessary condition: at least one dockerd/containerd/BuildKit
    # image-pull subsystem marker must appear somewhere in transport_stderr.
    # An app curl/wget shelling out from a RUN step will produce a base-registry
    # host + transient line, but it will NOT emit any of these dockerd-internal
    # phrases — gating on the marker rejects the launder vector.
    if not _IMAGE_PULL_DOCKERD_MARKER.search(ev):
        return None
    # Must find a single line containing both a base-registry host AND a transient token.
    matched_line = None
    for line in ev.splitlines():
        if _BASE_REGISTRY_HOSTS.search(line) and _IMAGE_PULL_TRANSIENT.search(line):
            matched_line = line
            break
    if matched_line is None:
        return None
    return Verdict(
        verdict="env",
        matched_signature="env.image_pull",
        negative_guard_evidence=(
            "base-image-registry host + transient + dockerd-pull marker; "
            "no package-index, no manifest-unknown"
        ),
        raw_evidence=matched_line[:500],
        retry_count=ctx.retry_count,
        **_populate_schema_kwargs(ctx),
    )


# env.oom ------------------------------------------------------------------

_OOM_POSITIVE = re.compile(
    r"exit (137|code 137)"
    r"|\bKilled\b"
    r"|signal 9"
    r"|OOMKilled"
    r"|cannot allocate memory"
    r"|fork: retry: Resource temporarily unavailable",
    re.IGNORECASE,
)
_OOM_DMESG_HOST = re.compile(
    r"oom-kill:.*constraint=CONSTRAINT_NONE",
    re.IGNORECASE,
)
_OOM_DMESG_CGROUP = re.compile(
    r"constraint=CONSTRAINT_MEMCG"
    r"|oom_memcg=/docker/",
    re.IGNORECASE,
)


def _matches_own_cgroup_oom(ctx: FailureContext) -> bool:
    """Step-1 carve-out: own-cgroup OOM is FUNCTIONAL, evaluated BEFORE env.oom.

    Round-12 (B-3): consult docker_inspect_state.OOMKilled FIRST — it's the
    daemon's own authoritative verdict that THIS container hit its cgroup OOM.
    Even if a parallel host CONSTRAINT_NONE window also exists, OOMKilled=True
    is the docker-layer authority on which cgroup OOMed.
    """
    # OOM positive token must appear somewhere. raw_evidence is permitted here
    # (asymmetric with env.oom — see R1 round-13). The asymmetry is
    # intentional and safe: this is a FUNCTIONAL carve-out, so over-recognition
    # of own-cgroup-OOM tokens in app logs can only launder a run OUT of env,
    # never INTO env — bias-conservative for the dangerous direction.
    ev_oom = ctx.raw_evidence + (ctx.build_stderr or "") + (ctx.up_stderr or "")
    if not _OOM_POSITIVE.search(ev_oom):
        return False
    # Authoritative: docker daemon flagged this container as OOMKilled (own-cgroup).
    if ctx.docker_inspect_state and ctx.docker_inspect_state.get("OOMKilled") is True:
        return True
    if ctx.app_has_mem_limit:
        return True
    if ctx.dmesg_recent and _OOM_DMESG_CGROUP.search(ctx.dmesg_recent):
        return True
    return False


def _check_oom(ctx: FailureContext) -> Optional[Verdict]:
    if not _in_phase(ctx, "env.oom"):
        return None
    # R1 round-13 (channel-provenance + D1+D2): env.oom positive matching is
    # restricted to the CONTAINER-EXIT channel — docker daemon's authoritative
    # ExitCode plus docker-CLI transport stderr (build_stderr / up_stderr).
    # raw_evidence (= compose-logs = app stdout/stderr) is EXCLUDED from the
    # positive (an app self-printing 'Killed' or 'exit 137' is content, not
    # infra). The earlier "documented exception" framing was a self-adversarial
    # carve-out; see spec §3 row + §3 prereq #2.
    transport_ev = _transport_stderr(ctx)
    inspect = ctx.docker_inspect_state or {}
    inspect_exit_code = inspect.get("ExitCode")
    has_container_exit_137 = (inspect_exit_code == 137)
    if not _OOM_POSITIVE.search(transport_ev) and not has_container_exit_137:
        return None
    # Authoritative own-cgroup short-circuit (B-3, mirrors step 1 — defense
    # in depth even though _matches_own_cgroup_oom already handles this).
    if inspect.get("OOMKilled") is True:
        return None  # own-cgroup OOM → FUNCTIONAL (carved out)
    # R1 round-13 D1 veto: docker daemon's OOMKilled bit is authoritative in
    # BOTH directions. OOMKilled=False means the daemon affirmatively says
    # this container was NOT the kernel's OOM victim, so a parallel host
    # CONSTRAINT_NONE window can only be co-tenant pressure that didn't
    # target us — exclusionary, FUNCTIONAL. Only OOMKilled is None (no
    # inspect data) may fall through to the dmesg heuristic.
    if inspect.get("OOMKilled") is False:
        return None
    # Negative guard A: own-cgroup OOM = functional.
    if ctx.app_has_mem_limit:
        return None
    if ctx.dmesg_recent and _OOM_DMESG_CGROUP.search(ctx.dmesg_recent):
        return None
    # R2 round-13 by-construction precondition: env.oom requires the runner
    # to have injected a symmetric mem_limit on the app container. Without
    # it, dmesg CONSTRAINT_NONE is structurally indistinguishable from app
    # self-leak (an unconstrained app leaks → triggers host CONSTRAINT_NONE
    # that incidentally is the app's own functional bug). Conservative
    # default = FUNCTIONAL.
    if not getattr(ctx, "runner_injected_mem_limit", None):
        return None
    # Positive: must have host-level dmesg evidence.
    if not ctx.dmesg_recent or not _OOM_DMESG_HOST.search(ctx.dmesg_recent):
        return None  # 137+Killed alone is also app-cgroup OOM or SIGKILL → functional.
    return Verdict(
        verdict="env",
        matched_signature="env.oom",
        negative_guard_evidence=(
            "dmesg CONSTRAINT_NONE (host-wide), no app mem_limit, "
            "OOMKilled not True, OOMKilled not False (None/unknown), "
            f"runner_injected_mem_limit={ctx.runner_injected_mem_limit}, "
            "positive matched in container-exit channel (transport stderr "
            "or docker_inspect_state.ExitCode==137; raw_evidence excluded)"
        ),
        raw_evidence=_excerpt(ctx.dmesg_recent, _OOM_DMESG_HOST),
        retry_count=ctx.retry_count,
        **_populate_schema_kwargs(ctx),
    )


# env.disk_full ------------------------------------------------------------

# Round-12 (B-4): tar / register / write arms ALL require /var/lib/docker/ in
# the same line (storage-driver path scope). A `tar: no space left on device`
# writing to /app/dist is app content, not env.
_DISK_FULL_STORAGE_DRIVER = re.compile(
    r"failed to register layer:[^\n]*/var/lib/docker/(overlay2|aufs|btrfs|devicemapper|zfs)/[^\n]*no space left on device"
    r"|Error processing tar file[^\n]*/var/lib/docker/[^\n]*no space left on device"
    r"|write /var/lib/docker/(overlay2|aufs|btrfs|devicemapper|zfs)/[^\n]*no space left on device",
    re.IGNORECASE,
)
_DISK_FULL_RUN_STEP_RE = re.compile(
    r"^[#\s]*\d+\s+\d+\.\d+\s+(.*\bENOSPC|.*Errno 28|.*no space left on device)",
    re.IGNORECASE | re.MULTILINE,
)
_FILE_WATCHER_LIMIT = re.compile(
    r"System limit for number of file watchers",
    re.IGNORECASE,
)


def _df_shows_pressure(df_text: Optional[str], threshold_pct: int = 90) -> bool:
    """Parse `df -P` output and return True iff Capacity ≥ threshold_pct.

    `df -P` POSIX format (with header):
      Filesystem 1024-blocks Used Available Capacity Mounted-on
      /dev/sda1     ...        ...   ...     95%      /var/lib/docker

    Tolerant of header-absent input (fixture / single-line callers): we look
    for any token shaped ``NNN%`` on any line, returning True on first
    ≥ threshold. A ``Capacity`` literal in the line marks the header and is
    skipped.
    """
    if not df_text:
        return False
    pct_re = re.compile(r"\b(\d{1,3})%")
    for line in df_text.splitlines():
        # Skip a header row if present.
        if "Capacity" in line and "Filesystem" in line:
            continue
        m = pct_re.search(line)
        if not m:
            continue
        try:
            if int(m.group(1)) >= threshold_pct:
                return True
        except ValueError:
            continue
    return False


def _check_disk_full(ctx: FailureContext) -> Optional[Verdict]:
    if not _in_phase(ctx, "env.disk_full"):
        return None
    # Channel provenance: only CLI transport stderr.
    ev = _transport_stderr(ctx)
    if _FILE_WATCHER_LIMIT.search(ev):
        return None
    # Precedence-stealer (B-4): RUN-step ENOSPC ALWAYS wins → app content
    # fills the layer/disk, not host env. Evaluated BEFORE storage-driver match.
    if _DISK_FULL_RUN_STEP_RE.search(ev):
        return None
    m = _DISK_FULL_STORAGE_DRIVER.search(ev)
    if not m:
        return None
    # Df-corroboration (B-4): storage-driver positive without ≥90% used →
    # unverified → FUNCTIONAL default. Storage-driver phrases can come from
    # overlayfs quirks rather than a truly full disk.
    if not _df_shows_pressure(ctx.df_var_lib_docker, threshold_pct=90):
        return None
    return Verdict(
        verdict="env",
        matched_signature="env.disk_full",
        negative_guard_evidence=(
            "storage-driver path ENOSPC + df ≥90% on /var/lib/docker; "
            "not RUN-step Errno 28, not inotify limit"
        ),
        raw_evidence=m.group(0)[:500],
        retry_count=ctx.retry_count,
        **_populate_schema_kwargs(ctx),
    )


# env.buildkit_recurrence --------------------------------------------------

_RICH_THREAD = re.compile(
    # Rich frame anywhere within 500 chars of the RuntimeError (any direction):
    # rich-frame ... RuntimeError, OR RuntimeError ... rich-frame.
    r"pip[/\\]_vendor[/\\]rich[/\\][\s\S]{0,500}?RuntimeError:\s*can'?t start new thread"
    r"|RuntimeError:\s*can'?t start new thread[\s\S]{0,500}?pip[/\\]_vendor[/\\]rich[/\\]",
    re.IGNORECASE,
)
_APT_POST_INVOKE = re.compile(
    r"APT::Update::Post-Invoke",
    re.IGNORECASE,
)
# Apt download proof — any unit (B/kB/MB/GB). Spec said `\bkB` but apt's actual
# output uses whatever unit fits the total; the intent is "download succeeded".
_APT_FETCHED = re.compile(
    r"Fetched\b[^\n]*\b(B|kB|MB|GB)\b",
    re.IGNORECASE,
)
_APT_DNS_NEG = re.compile(
    r"Could not resolve"
    r"|Failed to fetch"
    r"|404",
    re.IGNORECASE,
)
_UV_THREAD_ASSERT = re.compile(
    r"Assertion failed:\s*\(0\)\s*==\s*\(uv_thread_create",
    re.IGNORECASE,
)
# Round-12 (B-5): node variant requires SIGABRT marker — uv assertion calls
# abort(), which surfaces as exit code 134 / "Aborted (core dumped)" /
# "signal: aborted". Without an abort marker the assertion is likely echoed
# from a different crash path (e.g. an app's own log).
_NODE_SIGABRT = re.compile(
    r"Aborted \(core dumped\)"
    r"|signal:\s*aborted"
    r"|\bexit code:?\s*134\b"
    r"|\b(exited|exit status)\s+134\b",
    re.IGNORECASE,
)
# Round-2 tightening (B-5): the line must BE the docker CLI RUN command line
# itself (or the BuildKit ERROR wrapper naming that command), not any
# BuildKit-prefixed line that merely contains the substring `node`/`npm` etc.
# An app preflight script that prints `node v20.0.0 OK` on a BuildKit-prefixed
# stdout line would otherwise launder a functional crash into env.
# Accepted shapes:
#   (a) `#N M.MMM [RUN ]npm install|ci|run|test|exec|i|build ...`
#   (b) `#N M.MMM [RUN ]yarn install|build|run|test|start ...`
#   (c) `#N M.MMM [RUN ]pnpm install|i|build|run ...`
#   (d) `#N M.MMM [RUN ]node <file>.js|.cjs|.mjs|.ts ...`
#   (e) BuildKit ERROR wrapper: `#N ERROR: (executor failed running|process)
#       [/bin/sh -c (npm|node|yarn|pnpm) ...`
# Rejected: app content like `#8 0.40 Assertion failed: ...` or
#          `#8 0.20 node v20.0.0 OK` or
#          `#8 ERROR: process "/bin/sh -c bash scripts/preflight.sh"`
_NPM_NODE_RUN_STEP = re.compile(
    r"^#\d+\s+\d+\.\d+\s+(?:RUN\s+)?"
    r"(?:npm\s+(?:install|ci|run|test|exec|i|build)"
    r"|yarn\s+(?:install|build|run|test|start)"
    r"|pnpm\s+(?:install|i|build|run)"
    r"|node\s+\S+\.(?:js|cjs|mjs|ts))\b"
    r"|^#\d+\s+ERROR:?\s+(?:executor failed running|process)\s+"
    r"[\[\"']*/bin/sh\s+-c\s+(?:npm|node|yarn|pnpm)\b",
    re.IGNORECASE | re.MULTILINE,
)


def _check_buildkit_recurrence(ctx: FailureContext) -> Optional[Verdict]:
    if not _in_phase(ctx, "env.buildkit_recurrence"):
        return None
    # Channel provenance: env.buildkit_recurrence must match the docker CLI
    # transport (build) stderr only. raw_evidence (= build stdout =
    # app-controlled) was previously concatenated here with a back-compat
    # comment; the round-2 adversarial caught three PoCs that smuggled the
    # rich frame / apt Post-Invoke / uv_thread_create markers through
    # raw_evidence and over-included as env. Channel provenance invariant
    # now applies uniformly to ALL env signatures — use _transport_stderr()
    # like every other env check (daemon_down, image_pull, disk_full,
    # port_conflict).
    ev = _transport_stderr(ctx)
    # Variant 1: pip rich thread (requires rich frame anchor — V1 vs V2).
    if _RICH_THREAD.search(ev):
        return Verdict(
            verdict="env",
            matched_signature="env.buildkit_recurrence",
            negative_guard_evidence="pip rich frame + can't-start-new-thread",
            raw_evidence=_excerpt(ev, _RICH_THREAD),
            retry_count=ctx.retry_count,
            **_populate_schema_kwargs(ctx),
        )
    # Variant 2: apt Post-Invoke (requires download proof AND no DNS-token negative).
    if _APT_POST_INVOKE.search(ev) and _APT_FETCHED.search(ev) and not _APT_DNS_NEG.search(ev):
        return Verdict(
            verdict="env",
            matched_signature="env.buildkit_recurrence",
            negative_guard_evidence="APT::Update::Post-Invoke + Fetched-proof; no DNS-token negative",
            raw_evidence=_excerpt(ev, _APT_POST_INVOKE),
            retry_count=ctx.retry_count,
            **_populate_schema_kwargs(ctx),
        )
    # Variant 3 — tightened (B-5): uv_thread_create assertion + SIGABRT marker
    # + a BuildKit RUN-step prefix line invoking npm/node/yarn/pnpm.
    if (
        _UV_THREAD_ASSERT.search(ev)
        and _NODE_SIGABRT.search(ev)
        and _NPM_NODE_RUN_STEP.search(ev)
    ):
        return Verdict(
            verdict="env",
            matched_signature="env.buildkit_recurrence",
            negative_guard_evidence=(
                "uv_thread_create assertion + SIGABRT/exit 134 + BuildKit RUN-step npm/node prefix"
            ),
            raw_evidence=_excerpt(ev, _UV_THREAD_ASSERT),
            retry_count=ctx.retry_count,
            **_populate_schema_kwargs(ctx),
        )
    return None


# env.daemon_5xx -----------------------------------------------------------
# DELETED in R1 round-12 (B-6). Rationale:
#   1. No transport discriminator strong enough to separate app-printed 500s
#      from docker CLI receiving 500s — laundering vector.
#   2. Genuine dockerd panics during the run window also surface as
#      env.daemon_down (socket dial failure), which IS captured by the
#      runner's systemctl/journalctl out-of-band probes.
#   3. Removing the signature eliminates a known over-exclude vector.
# The function is retained as a return-None stub so the checker tuple in
# classify() can keep its same shape (and to make the deletion auditable in
# diffs).


def _check_daemon_5xx(ctx: FailureContext) -> Optional[Verdict]:
    """DELETED in R1 round-12. See module docstring B-6 for rationale."""
    return None


# env.oracle_infra ---------------------------------------------------------

_ORACLE_CODE_PATH = re.compile(
    r'File "[^"]*tests/north_star/[^"]+"',
    re.IGNORECASE,
)
_PLAYWRIGHT_LAUNCH = re.compile(
    r"Executable doesn't exist"
    r"|Failed to launch"
    r"|No usable sandbox",
    re.IGNORECASE,
)


def _check_oracle_infra(ctx: FailureContext) -> Optional[Verdict]:
    if not _in_phase(ctx, "env.oracle_infra"):
        return None
    if not ctx.junit_error_text:
        return None  # <failure> not <error>; step-0 already handled <failure>.
    in_oracle_code = bool(_ORACLE_CODE_PATH.search(ctx.junit_error_text))
    is_playwright_launch = bool(_PLAYWRIGHT_LAUNCH.search(ctx.junit_error_text))
    if not (in_oracle_code or is_playwright_launch):
        return None
    # Control-group reproduction required: must reproduce against reference_impl.
    if ctx.reproduces_against_reference_impl is not True:
        return None  # App-triggered → functional (V25).
    return Verdict(
        verdict="env",
        matched_signature="env.oracle_infra",
        negative_guard_evidence="reproduces against reference_impl control (oracle bug)",
        raw_evidence=ctx.junit_error_text[:500],
        retry_count=ctx.retry_count,
        **_populate_schema_kwargs(ctx),
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def classify(ctx: FailureContext) -> Verdict:
    """Classify a failed run per pilot_classifier_spec.md §1 evaluation order.

    Step 0: Oracle JUnit <failure> trumps all → FUNCTIONAL.
    Step 1: Own-cgroup OOM carve-out → FUNCTIONAL.
    Step 2: §3 ENV signatures, in id order.
    Step 3: Terminal default → FUNCTIONAL.
    """
    # Ensure §2 schema fields are populated even when callers built a
    # FailureContext without a run_id (legacy fixtures).
    if not ctx.run_id:
        ctx.run_id = uuid.uuid4().hex

    schema_kwargs = _populate_schema_kwargs(ctx)

    # Step 0: oracle <failure> is the flow-assertion result; never excluded.
    # Round-12 (B-7): element-presence sentinel (`is not None`) — an empty
    # <failure/> body (xUnit emits self-closing tags) is still the oracle
    # reporting a flow assertion.
    if ctx.junit_failure_text is not None:
        return Verdict(
            verdict="functional",
            matched_signature=None,
            negative_guard_evidence="step-0 invariant: oracle <failure> always FUNCTIONAL",
            raw_evidence=(
                ctx.junit_failure_text[:500]
                if ctx.junit_failure_text
                else "<failure/> (empty body)"
            ),
            retry_count=ctx.retry_count,
            **schema_kwargs,
        )

    # Step 1: own-cgroup OOM carve-out (BEFORE env.oom can fire).
    if _matches_own_cgroup_oom(ctx):
        ev_oom = ctx.raw_evidence + (ctx.build_stderr or "") + (ctx.up_stderr or "")
        return Verdict(
            verdict="functional",
            matched_signature=None,
            negative_guard_evidence=(
                "own-cgroup OOM (OOMKilled=True OR CONSTRAINT_MEMCG OR app mem_limit)"
            ),
            raw_evidence=_excerpt(ev_oom, _OOM_POSITIVE),
            retry_count=ctx.retry_count,
            **schema_kwargs,
        )

    # Step 2: §3 signatures, in id order.
    for checker in (
        _check_daemon_down,
        _check_port_conflict,
        _check_image_pull,
        _check_oom,
        _check_disk_full,
        _check_buildkit_recurrence,
        _check_daemon_5xx,  # DELETED — stub returns None (R1 round-12 B-6)
        _check_oracle_infra,
    ):
        verdict = checker(ctx)
        if verdict is not None:
            return verdict

    # Step 3: terminal default — FUNCTIONAL.
    fallback_ev = (
        ctx.build_stderr
        or ctx.up_stderr
        or ctx.raw_evidence
        or ctx.junit_error_text
        or ""
    )
    return Verdict(
        verdict="functional",
        matched_signature=None,
        negative_guard_evidence="terminal default — no §3 signature matched",
        raw_evidence=fallback_ev[-500:],
        retry_count=ctx.retry_count,
        **schema_kwargs,
    )


# ---------------------------------------------------------------------------
# Sink (B-8) — JSONL writer/reader so pilot ITT can recompute per-arm rates.
# ---------------------------------------------------------------------------


def append_to_sink(verdict: Verdict, sink_path: Union[str, Path]) -> None:
    """Atomically append one JSON line for the §2 schema row.

    POSIX O_APPEND + a single write() < PIPE_BUF (4096 on Linux) is atomic so
    concurrent pilot runners (one classifier per run) cannot interleave
    lines. raw_evidence is hard-capped here as a safety belt — the classifier
    already excerpts to ~500 chars, but if a caller bypasses that, we truncate
    rather than risk crossing PIPE_BUF.
    """
    sink_path = Path(sink_path)
    sink_path.parent.mkdir(parents=True, exist_ok=True)
    payload = verdict.to_dict()
    line = json.dumps(payload, separators=(",", ":")) + "\n"
    data = line.encode("utf-8")
    if len(data) > 3500:
        payload["raw_evidence"] = payload.get("raw_evidence", "")[:1000] + "...[truncated]"
        line = json.dumps(payload, separators=(",", ":")) + "\n"
        data = line.encode("utf-8")
    fd = os.open(str(sink_path), os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
    try:
        os.write(fd, data)
    finally:
        os.close(fd)


def read_sink(sink_path: Union[str, Path]) -> Iterator[dict]:
    """Iterate JSONL rows back as dicts. Malformed lines are silently skipped
    (defence-in-depth against truncated/interrupted writes); ITT counts only
    well-formed rows."""
    sink_path = Path(sink_path)
    with open(sink_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


# ---------------------------------------------------------------------------
# ITT + asymmetry gate (B-8 / §5.1) — pilot decisive backstop.
# ---------------------------------------------------------------------------


ASYMMETRY_REL_X = 2.0   # >2× relative env-exclusion-rate ratio blocks
ASYMMETRY_ABS_PP = 5.0  # >5pp absolute env-exclusion-rate gap blocks


def _per_arm_counts(sink_path: Path, arm: str) -> dict:
    total = func_fail = env_excl = uncertain = passes = 0
    for row in read_sink(sink_path):
        if row.get("arm") != arm:
            continue
        total += 1
        if row.get("outcome") == "pass":
            passes += 1
        else:  # fail
            v = row.get("verdict")
            if v == "env":
                env_excl += 1
            elif v == "uncertain":
                uncertain += 1
                func_fail += 1  # §5.0 — uncertain counts AGAINST rate
            else:  # functional
                func_fail += 1
    return {
        "total_runs": total,
        "passes": passes,
        "functional_failures": func_fail,
        "env_excluded": env_excl,
        "uncertain": uncertain,
    }


def _as_classified_rate(c: dict) -> float:
    """passes / (total - env_excluded). env-excluded runs are removed from
    the denominator; this is what naive aggregation reports."""
    denom = c["total_runs"] - c["env_excluded"]
    return c["passes"] / denom if denom > 0 else 0.0


def _itt_rate(c: dict) -> float:
    """Worst-case ITT: ALL excluded runs counted as functional FAILURES (no
    denominator reduction). §5.1 — the metric a flawed signature cannot game."""
    denom = c["total_runs"]
    return c["passes"] / denom if denom > 0 else 0.0


def compute_itt_delta(
    sink_path: Union[str, Path], arm_old: str, arm_new: str
) -> Dict:
    """§5.1 contract: per-arm counts + as-classified delta + ITT-worst-case
    delta + large-asymmetry gate result.

    Returns a dict with keys per_arm / as_classified / itt / asymmetry / blocked.
    `blocked` is True iff the asymmetry gate fires (>2× relative OR >5pp abs
    env-exclusion gap). When blocked, downstream comparisons MUST NOT report
    the as-classified delta as a win — the asymmetry signals that a §3
    signature may be quietly absorbing content failures on the heavier arm.
    """
    sink_path = Path(sink_path)
    old = _per_arm_counts(sink_path, arm_old)
    new = _per_arm_counts(sink_path, arm_new)
    as_old = _as_classified_rate(old)
    as_new = _as_classified_rate(new)
    itt_old = _itt_rate(old)
    itt_new = _itt_rate(new)
    excl_rate_old = old["env_excluded"] / old["total_runs"] if old["total_runs"] else 0.0
    excl_rate_new = new["env_excluded"] / new["total_runs"] if new["total_runs"] else 0.0
    abs_pp = abs(excl_rate_new - excl_rate_old) * 100.0
    if min(excl_rate_old, excl_rate_new) > 0:
        ratio = max(excl_rate_old, excl_rate_new) / min(excl_rate_old, excl_rate_new)
    else:
        # 0-vs-nonzero asymmetry: inf if either arm has any exclusions, else 1.0.
        ratio = float("inf") if max(excl_rate_old, excl_rate_new) > 0 else 1.0
    triggered = ratio > ASYMMETRY_REL_X or abs_pp > ASYMMETRY_ABS_PP
    return {
        "per_arm": {arm_old: old, arm_new: new},
        "as_classified": {
            arm_old: as_old,
            arm_new: as_new,
            "delta_pp": (as_new - as_old) * 100.0,
        },
        "itt": {
            arm_old: itt_old,
            arm_new: itt_new,
            "delta_pp": (itt_new - itt_old) * 100.0,
        },
        "asymmetry": {"ratio": ratio, "pp": abs_pp, "triggered": triggered},
        "blocked": triggered,
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _excerpt(text: str, pattern: re.Pattern) -> str:
    """Return a ~200-char window around the first regex hit (auditable evidence)."""
    m = pattern.search(text)
    if not m:
        return text[:200]
    start = max(0, m.start() - 60)
    end = min(len(text), m.end() + 140)
    return text[start:end]
