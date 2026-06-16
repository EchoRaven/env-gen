"""North-star calibration runner.

Brings a docker-composed app up, polls its health endpoint until
ready, and returns (api_url, app_path) for the oracle to consume.
Provides a teardown helper that runs ``docker compose down -v``.

Design intent (R2 round-5/6 alignment + R1 round-12 remediation):

  * Distinguish FIXTURE FAILURE from ORACLE JUDGMENT. If docker
    refuses to come up, we return (None, None, reason) — the caller
    MUST count that as a fixture failure (arm_4_fixture_reliability),
    NOT as a flow failure inside arms 1a/1b/2. Mixing the two is the
    selection-bias risk R2 named.
  * Each arm gets a CLEAN container teardown so port collisions can't
    silently couple arms.
  * The runner does NOT know what convention the app uses — the
    oracle's ``resolve_base`` does that. We just hand off the bare
    base URL (host:port).

R1 round-12 channel/window/sink contract:
  * build_stderr and up_stderr carry ONLY the corresponding subprocess's
    stderr stream. Stdout is now routed to raw_evidence so the classifier's
    transport-only env signatures cannot match app-printed strings.
  * On failure, _capture_daemon_window() runs SYNCHRONOUSLY at T+0
    (systemctl is-active docker + journalctl tail) so env.daemon_down has
    in-window evidence, not post-hoc retries.
  * Port-conflict failure path now attempts ONE reassign-retry on a fresh
    ephemeral port and threads foreign_holder_found / reassign_retry_success /
    second_collision_on_free_port into FailureContext so the classifier's
    guards have data to read.
  * After classification, the Verdict is appended to PILOT_VERDICT_SINK (env
    var); pass-paths also write a synthesized pass-row so ITT can count
    total_runs per arm. Sink writes are no-ops when the env var is unset
    (spike back-compat preserved).
"""

import json
import logging
import os
import re
import shutil
import socket
import subprocess
import time
import uuid
from pathlib import Path
from typing import List, Optional, Tuple

import requests

_logger = logging.getLogger(__name__)

# Per-process set of (probe_name, exception_type_name) keys we have already
# logged a warning for. Probe helpers are best-effort by design (the classifier
# treats probe-None as conservative-functional), but a probe regression that
# silently zeroes every run's evidence-window is invisible without ONE warning
# per (probe, error-class) per process. See _log_probe_swallow_once below.
_PROBE_SWALLOW_LOGGED: set = set()


def _log_probe_swallow_once(probe_name: str, exc: BaseException) -> None:
    """Log a single warning per (probe_name, exception type) per process so
    a probe that always errors is observable in the pilot log-tail without
    drowning out every other diagnostic. The classifier still treats the
    probe as None / unknown — this only adds an observability signal, not a
    behavioural change."""
    key = (probe_name, type(exc).__name__)
    if key in _PROBE_SWALLOW_LOGGED:
        return
    _PROBE_SWALLOW_LOGGED.add(key)
    _logger.warning(
        "swallowed (once-per-process): probe %s failed: %r", probe_name, exc
    )

# Module-level container for the last failure context, populated on every
# failed run_app() call. Pilot's classifier reads this via
# get_last_failure_context(). Spike callers ignore it (back-compat).
_last_failure_context = None
# Module-level Verdict (post-classification) for the most recent run.
_last_verdict = None
# Module-level project name for the most recent run_app invocation so
# teardown() can reach the run-unique compose project without forcing a
# signature change on existing spike callers.
_last_compose_project: Optional[str] = None


def get_last_failure_context():
    """Return the FailureContext built during the most recent failed run_app
    call, or None if no failure has been recorded since process start (or the
    last run succeeded). Pilot pipeline uses this to feed
    tests.north_star.classifier.classify().
    """
    return _last_failure_context


def get_last_verdict():
    """Return the Verdict produced by the most recent classify() call from
    inside run_app (success-path synthesizes a pass Verdict; failure-path
    runs the full classifier). None if the runner has not been invoked or if
    the classifier could not be imported.
    """
    return _last_verdict


# ---------------------------------------------------------------------------
# Daemon-window probe (B-1 / R1 round-12) — synchronous T+0 measurement.
# Must be called the instant subprocess.run returns non-zero, with NO sleeps
# between failure detection and this helper.
# ---------------------------------------------------------------------------


def _capture_daemon_window() -> dict:
    """Synchronously probe daemon liveness AT failure time.

    Returns ``{"daemon_up_at_failure_time": bool|None,
              "journal_dockerd_window": str|None}``.

    * True ⇒ systemctl/service reports the daemon `active` during the failure
      window.
    * False ⇒ explicit measurement that the daemon was down at T+0.
    * None ⇒ no measurement could be taken (privilege / missing tool); the
      classifier treats None as conservative-functional (won't claim
      env.daemon_down without explicit T+0 proof).
    """
    out: dict = {
        "daemon_up_at_failure_time": None,
        "journal_dockerd_window": None,
    }
    # Try systemctl first; fall back to `service docker status` for
    # systems without systemd.
    try:
        r = subprocess.run(
            ["systemctl", "is-active", "docker"],
            capture_output=True,
            timeout=3,
            encoding="utf-8",
            errors="replace",
        )
        out["daemon_up_at_failure_time"] = (
            r.returncode == 0 and r.stdout.strip() == "active"
        )
    except Exception as _e:
        _log_probe_swallow_once("systemctl_is_active", _e)
        try:
            r = subprocess.run(
                ["service", "docker", "status"],
                capture_output=True,
                timeout=3,
                encoding="utf-8",
                errors="replace",
            )
            # service prints various forms; treat rc==0 as alive.
            out["daemon_up_at_failure_time"] = r.returncode == 0
        except Exception as _e2:
            _log_probe_swallow_once("service_docker_status", _e2)
            out["daemon_up_at_failure_time"] = None
    try:
        r = subprocess.run(
            ["journalctl", "-u", "docker", "--since", "60 seconds ago", "--no-pager"],
            capture_output=True,
            timeout=5,
            encoding="utf-8",
            errors="replace",
        )
        if r.returncode == 0:
            out["journal_dockerd_window"] = r.stdout[-4000:]
    except Exception as _e:
        _log_probe_swallow_once("journalctl_window", _e)
    return out


def _build_failure_context(
    app_path: Path,
    phase_reached: str,
    build_stderr: Optional[str] = None,
    up_stderr: Optional[str] = None,
    raw_evidence: str = "",
    injected_port: Optional[int] = None,
    compose_project: Optional[str] = None,
    *,
    run_id: str = "",
    arm: str = "spike",
    daemon_up_at_failure_time: Optional[bool] = None,
    journal_dockerd_window: Optional[str] = None,
    foreign_holder_found: Optional[bool] = None,
    reassign_retry_success: Optional[bool] = None,
    second_collision_on_free_port: bool = False,
    retry_count: int = 0,
    runner_injected_mem_limit: Optional[str] = None,
):
    """Assemble a classifier.FailureContext from runner-captured evidence +
    out-of-band probes. Import is local so this module stays importable
    even if classifier.py hasn't landed yet (DRAFT-phase robustness).
    """
    try:
        from classifier import FailureContext  # type: ignore
    except Exception as e_first:
        try:
            import sys as _sys
            _ns_dir = Path(__file__).resolve().parent.parent  # tests/north_star
            if str(_ns_dir) not in _sys.path:
                _sys.path.insert(0, str(_ns_dir))
            from classifier import FailureContext  # type: ignore
        except Exception as e_second:
            _logger.warning(
                "swallowed: classifier.FailureContext import failed both "
                "paths (first=%r, after sys.path inject=%r) — failure "
                "context will be None, _classify_and_emit will mark verdict "
                "INERT:no_context",
                e_first,
                e_second,
            )
            return None  # classifier not present — return None, runner still works

    probes = _gather_probes(app_path)
    inspect_state = _docker_inspect_state(app_path, compose_project or "")
    docker_ps_out = _docker_ps_for_port(injected_port) if injected_port else ""

    # Detect whether the app declares mem_limit in compose (own-cgroup OOM
    # carve-out evidence per §1 step 1).
    #
    # R2 round-13: the runner now injects a symmetric mem_limit via the
    # `${RUNNER_MEM_LIMIT:-2g}` template on every compose file. That
    # injection is tracked separately on FailureContext.runner_injected_mem_limit
    # so we MUST NOT count the templated form as an app-declared mem_limit
    # (otherwise the env.oom negative guard would short-circuit every run
    # and env.oom could never fire — but the by-construction precondition
    # for env.oom is that runner-injected mem_limit is set AND the
    # app-declared mem_limit guard does NOT apply). Detection therefore
    # strips the `${RUNNER_MEM_LIMIT...}` literal before scanning.
    app_has_mem_limit = False
    try:
        compose_text = (app_path / "docker-compose.yml").read_text()
        # Strip the runner-injected templated mem_limit so we only detect
        # app-author-declared mem_limits (numeric or non-RUNNER_MEM_LIMIT
        # variable forms).
        stripped = re.sub(
            r"mem_limit\s*:\s*\$\{RUNNER_MEM_LIMIT[^}]*\}\s*",
            "",
            compose_text,
        )
        if re.search(r"mem_limit\s*:", stripped) or re.search(
            r"deploy\s*:[\s\S]*?resources\s*:[\s\S]*?limits\s*:[\s\S]*?memory\s*:",
            stripped,
        ):
            app_has_mem_limit = True
    except Exception as _e:
        _log_probe_swallow_once("mem_limit_detect", _e)

    return FailureContext(
        run_id=run_id or uuid.uuid4().hex,
        spec_id="simple_blog",
        arm=arm,
        phase_reached=phase_reached,
        outcome="fail",
        raw_evidence=raw_evidence,
        build_stderr=build_stderr,
        up_stderr=up_stderr,
        dmesg_recent=probes.get("dmesg_recent"),
        df_var_lib_docker=probes.get("df_var_lib_docker"),
        docker_version_retries=probes.get("docker_version_retries", []),
        docker_inspect_state=inspect_state,
        docker_ps_filter_output=docker_ps_out,
        compose_project_name=compose_project,
        daemon_up_at_failure_time=daemon_up_at_failure_time,
        journal_dockerd_window=journal_dockerd_window,
        injected_port=injected_port,
        retry_count=retry_count,
        second_collision_on_free_port=second_collision_on_free_port,
        foreign_holder_found=foreign_holder_found,
        reassign_retry_success=reassign_retry_success,
        app_has_mem_limit=app_has_mem_limit,
        runner_injected_mem_limit=runner_injected_mem_limit,
    )


def _allocate_ephemeral_port() -> int:
    """Allocate a run-unique ephemeral port per spec §3 env.port_conflict
    admissibility requirement. socket.bind(('', 0)) lets the kernel pick a
    free port; we close immediately and return the number. TOCTOU exists
    between this allocation and docker's actual bind, but that race is
    exactly what env.port_conflict's foreign-holder check is designed to
    catch (V7 case). Port floor is the kernel's ip_local_port_range minimum
    (typically 32768) so this satisfies the EPHEMERAL_FLOOR in classifier.
    """
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("", 0))
        return s.getsockname()[1]
    finally:
        s.close()


def _gather_probes(app_path: Path) -> dict:
    """Out-of-band evidence the classifier's §3 negative guards need but
    aren't in subprocess stderr. Best-effort: any probe that times out or
    errors returns None rather than blocking failure-context assembly.

    Returned dict matches FailureContext field names so the caller can
    splat it in.
    """
    probes: dict = {}
    try:
        r = subprocess.run(
            ["dmesg", "-T", "--ctime"],
            capture_output=True, timeout=5, encoding="utf-8", errors="replace",
        )
        if r.returncode == 0:
            probes["dmesg_recent"] = "\n".join(r.stdout.splitlines()[-100:])
    except Exception as _e:
        _log_probe_swallow_once("dmesg", _e)
    try:
        r = subprocess.run(
            ["df", "-P", "/var/lib/docker"],
            capture_output=True, timeout=5, encoding="utf-8", errors="replace",
        )
        if r.returncode == 0:
            probes["df_var_lib_docker"] = r.stdout.strip()
    except Exception as _e:
        _log_probe_swallow_once("df_var_lib_docker", _e)
    retries: List[Tuple[int, str]] = []
    for _ in range(3):
        try:
            r = subprocess.run(
                ["docker", "version", "--format", "{{.Server.Version}}"],
                capture_output=True, timeout=5, encoding="utf-8", errors="replace",
            )
            retries.append((r.returncode, (r.stdout or r.stderr).strip()[:200]))
        except Exception as e:
            _log_probe_swallow_once("docker_version", e)
            retries.append((1, f"{type(e).__name__}: {e}"))
        if retries[-1][0] == 0:
            break  # healed blip — record success and stop early
    probes["docker_version_retries"] = retries
    return probes


def _docker_inspect_state(app_path: Path, compose_project: str) -> Optional[dict]:
    """Capture State.{Status,ExitCode,OOMKilled} for the first container in
    the compose project so §4's app-boot-crash rule has data."""
    try:
        ps = subprocess.run(
            ["docker", "compose", "ps", "-q"],
            cwd=str(app_path), capture_output=True, timeout=10,
            encoding="utf-8", errors="replace",
        )
        cids = [c for c in (ps.stdout or "").splitlines() if c.strip()]
        if not cids:
            return None
        inspect = subprocess.run(
            ["docker", "inspect", "--format",
             "{{json .State}}", cids[0]],
            capture_output=True, timeout=10, encoding="utf-8", errors="replace",
        )
        if inspect.returncode == 0:
            return json.loads(inspect.stdout)
    except Exception as _e:
        _log_probe_swallow_once("docker_compose_ps", _e)
    return None


def _docker_ps_for_port(port: int) -> str:
    """Capture `docker ps --filter publish=<P>` for env.port_conflict
    foreign-holder check. Returns the raw output; classifier's caller
    parses for project labels."""
    try:
        r = subprocess.run(
            ["docker", "ps", "--filter", f"publish={port}",
             "--format", "{{.Names}}\t{{.Labels}}"],
            capture_output=True, timeout=5, encoding="utf-8", errors="replace",
        )
        return r.stdout or ""
    except Exception as _e:
        _log_probe_swallow_once("docker_ps_filter", _e)
        return ""


def _parse_foreign_holder(docker_ps_output: str, ourproj: str) -> Optional[bool]:
    """Inspect docker ps output for the holder's compose project label.
    Returns True iff a holder exists whose project != ours, False if every
    holder is in our project, None if no holder lines were seen at all
    (TOCTOU / ambiguous).
    """
    if not docker_ps_output.strip():
        return None
    found_any = False
    for line in docker_ps_output.splitlines():
        m = re.search(r"com\.docker\.compose\.project=([^,\s]+)", line)
        if not m:
            continue
        found_any = True
        if m.group(1) != ourproj:
            return True
    if found_any:
        return False
    return None


_PORT_CONFLICT_RUNNER_RE_TMPL = (
    r"Bind for 0\.0\.0\.0:{p}\b"
    r"|Bind for \[::\]:{p}\b"
    r"|listen tcp [^\n]*:{p}: bind: address already in use"
    r"|0\.0\.0\.0:{p}[^\n]{{0,80}}(?:port is already allocated|address already in use)"
    r"|:{p}\b[^\n]{{0,80}}(?:port is already allocated|address already in use)"
)


def _port_conflict_re(port: int) -> re.Pattern:
    return re.compile(_PORT_CONFLICT_RUNNER_RE_TMPL.format(p=port), re.IGNORECASE)


def _published_port(compose_path: Path) -> Optional[int]:
    """Best-effort: parse the first ``- "HOST:CONTAINER"`` ports entry
    out of the compose file. We don't import PyYAML to keep this
    runner dependency-free; the compose files in this suite have a
    very regular shape, so a regex is enough.

    Returns the host-side port, or None if it can't be determined.
    """
    try:
        text = compose_path.read_text()
    except Exception:
        return None
    m = re.search(r'-\s*"?(\d+):\d+"?', text)
    if m:
        try:
            return int(m.group(1))
        except ValueError:
            return None
    return None


def _health_url_candidates(api_url: str) -> list:
    """Return the ordered list of health URLs to probe."""
    return [f"{api_url}/health", f"{api_url}/api/health"]


def _wait_for_ready(api_url: str, timeout_s: float = 30.0) -> Optional[str]:
    """Poll candidate /health endpoints until one returns 2xx or 3xx.

    Returns the successful health URL on success, None on timeout.
    """
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        for url in _health_url_candidates(api_url):
            try:
                r = requests.get(url, timeout=2)
                if 200 <= r.status_code < 400:
                    return url
            except Exception:
                pass
        time.sleep(1.0)
    return None


# ---------------------------------------------------------------------------
# Classifier integration helpers (B-8) — runs only if classifier importable.
# ---------------------------------------------------------------------------


def _classify_and_emit(ctx) -> None:
    """Run classify() on ctx, store the Verdict in module state, and append
    it to PILOT_VERDICT_SINK if set.

    LOUD-on-swallow contract (R1 round-13, D4 audit): every fail-soft branch
    MUST emit ``logger.warning`` AND set ``_last_verdict`` to a sentinel
    string starting with ``"INERT:"`` so the pilot driver can detect that
    the measurement gate fired but did not produce a real ``Verdict``. The
    pilot's preflight assertion (D2) refuses to ship a run whose
    ``_last_verdict`` matches ``"INERT:*"``.
    """
    global _last_verdict
    if ctx is None:
        _logger.warning(
            "swallowed: _classify_and_emit called with ctx=None — "
            "failure context not built"
        )
        _last_verdict = "INERT:no_context"
        return
    try:
        from classifier import classify, append_to_sink
    except Exception as e:
        _logger.warning(
            "swallowed: classifier import failed in _classify_and_emit: %r", e
        )
        _last_verdict = f"INERT:classifier_import:{type(e).__name__}"
        return
    try:
        verdict = classify(ctx)
    except Exception as e:
        _logger.warning(
            "swallowed: classify(ctx) raised %r — ctx.phase_reached=%s",
            e,
            getattr(ctx, "phase_reached", "?"),
        )
        _last_verdict = f"INERT:classify_raised:{type(e).__name__}"
        return
    _last_verdict = verdict
    sink = os.environ.get("PILOT_VERDICT_SINK")
    if sink:
        try:
            append_to_sink(verdict, Path(sink))
        except Exception as e:
            _logger.warning(
                "swallowed: append_to_sink failed for sink=%s: %r", sink, e
            )
            # Verdict IS computed; only the persistence step failed. Mark on
            # the verdict itself so the pilot driver can detect; the
            # _last_verdict still holds the real Verdict (not an INERT
            # sentinel) because the measurement DID happen — we just failed
            # to persist it.
            try:
                setattr(verdict, "_sink_write_failed", repr(e))
            except Exception:
                pass


def _emit_pass_verdict(run_id: str, arm: str) -> None:
    """On the success path synthesize a pass-Verdict so ITT counts total_runs
    per arm correctly. Pass-path classify() is not run (classifier is
    failure-only); the sink write is gated on PILOT_VERDICT_SINK.

    LOUD-on-swallow contract (D4 audit): every fail-soft branch warns AND
    sets ``_last_verdict='INERT:*'`` sentinel. Pilot preflight asserts no
    run ends INERT.
    """
    global _last_verdict
    try:
        from classifier import synthesize_pass_verdict, append_to_sink
    except Exception as e:
        _logger.warning(
            "swallowed: classifier import failed in _emit_pass_verdict "
            "(arm=%s, run_id=%s): %r",
            arm,
            run_id,
            e,
        )
        _last_verdict = f"INERT:pass_classifier_import:{type(e).__name__}"
        return
    try:
        v = synthesize_pass_verdict(
            run_id=run_id,
            spec_id="simple_blog",
            arm=arm,
            phase_reached="oracle",
        )
    except Exception as e:
        _logger.warning(
            "swallowed: synthesize_pass_verdict raised %r "
            "(arm=%s, run_id=%s)",
            e,
            arm,
            run_id,
        )
        _last_verdict = f"INERT:synth_pass_raised:{type(e).__name__}"
        return
    _last_verdict = v
    sink = os.environ.get("PILOT_VERDICT_SINK")
    if sink:
        try:
            append_to_sink(v, Path(sink))
        except Exception as e:
            _logger.warning(
                "swallowed: append_to_sink (pass) failed for sink=%s: %r",
                sink,
                e,
            )
            try:
                setattr(v, "_sink_write_failed", repr(e))
            except Exception:
                pass


def run_app(
    app_dir: str,
    health_timeout_s: float = 30.0,
    api_base_suffix: Optional[str] = None,
    use_ephemeral_port: bool = True,
    *,
    arm: str = "spike",
    run_id: Optional[str] = None,
) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """Bring the app under ``app_dir`` up via docker compose and wait
    for readiness.

    Returns a 3-tuple:
      (api_url, app_path, reason)

    On success:  (api_url, app_path, None)
       api_url has any required suffix (e.g. ``/api``) appended IF
       the caller passed ``api_base_suffix`` (we don't infer — the
       oracle's ``resolve_base`` is the authority on prefix).
       app_path is the absolute path to ``app_dir`` (str).

    On fixture failure:  (None, None, reason)
       reason is a short string describing what went wrong. The full
       FailureContext is stashed in ``_last_failure_context``; the
       post-classification Verdict (per §2 schema) is stashed in
       ``_last_verdict``. If ``PILOT_VERDICT_SINK`` is set in the
       process env, the Verdict is also JSONL-appended to that file.

    Pilot integration (B-8):
      - ``arm`` flows into FailureContext.arm and Verdict.arm so the §5.1
        ITT/asymmetry recompute can attribute exclusions to the correct arm.
      - ``run_id`` is a uuid4 hex by default; callers may supply their own.
      - PILOT_VERDICT_SINK (env var) names the JSONL file to which the
        Verdict is appended. Unset → no sink write (spike back-compat).
    """
    global _last_failure_context, _last_compose_project, _last_verdict

    _last_failure_context = None
    _last_verdict = None
    if run_id is None:
        run_id = uuid.uuid4().hex

    app_path = Path(app_dir).resolve()
    compose = app_path / "docker-compose.yml"
    if not compose.is_file():
        return (None, None, f"no docker-compose.yml at {compose}")

    if use_ephemeral_port:
        port = _allocate_ephemeral_port()
    else:
        port = _published_port(compose)
        if port is None:
            return (None, None, f"could not parse host port from {compose}")

    if shutil.which("docker") is None:
        return (None, None, "docker binary not found on PATH")

    compose_project = f"northstar-{uuid.uuid4().hex[:8]}"
    _last_compose_project = compose_project

    docker_env = os.environ.copy()
    docker_env["DOCKER_BUILDKIT"] = "0"
    docker_env["COMPOSE_DOCKER_CLI_BUILD"] = "0"
    docker_env["RUNNER_HOST_PORT"] = str(port)
    docker_env["COMPOSE_PROJECT_NAME"] = compose_project
    # R2 round-13 by-construction: inject a symmetric mem_limit on every app
    # container so an app self-leak surfaces as own-cgroup OOM (OOMKilled=True
    # → step-1 carve-out → FUNCTIONAL) and dmesg CONSTRAINT_NONE becomes the
    # genuinely co-tenant case. Default 2g is generous for simple_blog scale;
    # both arms get the same value so no A/B asymmetry is introduced.
    injected_mem_limit = os.environ.get("RUNNER_MEM_LIMIT", "2g")
    docker_env["RUNNER_MEM_LIMIT"] = injected_mem_limit

    subprocess.run(
        ["docker", "compose", "down", "-v"],
        cwd=str(app_path),
        capture_output=True,
        timeout=60,
        env=docker_env,
    )

    # ----- BUILD phase ----------------------------------------------------
    build = subprocess.run(
        ["docker", "compose", "build"],
        cwd=str(app_path),
        capture_output=True,
        timeout=300,
        env=docker_env,
    )
    build_stderr_full = build.stderr.decode("utf-8", errors="replace") if build.stderr else ""
    build_stdout_full = build.stdout.decode("utf-8", errors="replace") if build.stdout else ""
    if build.returncode != 0:
        # T+0 daemon-window probe — synchronous, no sleeps before.
        window = _capture_daemon_window()
        _last_failure_context = _build_failure_context(
            app_path=app_path,
            phase_reached="app_build",
            # Channel-provenance fix: stderr is stderr, stdout flows to raw_evidence.
            build_stderr=build_stderr_full,
            up_stderr=None,
            raw_evidence=build_stdout_full,
            injected_port=port,
            compose_project=compose_project,
            run_id=run_id,
            arm=arm,
            daemon_up_at_failure_time=window["daemon_up_at_failure_time"],
            journal_dockerd_window=window["journal_dockerd_window"],
            runner_injected_mem_limit=injected_mem_limit,
        )
        _classify_and_emit(_last_failure_context)
        return (None, None, f"docker compose build failed (rc={build.returncode}); see get_last_failure_context()")

    # ----- UP phase -------------------------------------------------------
    up = subprocess.run(
        ["docker", "compose", "up", "-d"],
        cwd=str(app_path),
        capture_output=True,
        timeout=300,
        env=docker_env,
    )
    up_stderr_full = up.stderr.decode("utf-8", errors="replace") if up.stderr else ""
    up_stdout_full = up.stdout.decode("utf-8", errors="replace") if up.stdout else ""
    if up.returncode != 0:
        # T+0 daemon-window probe (synchronous).
        window = _capture_daemon_window()

        # Port-conflict reassign retry (D5). Bounded to a single attempt to
        # avoid unbounded loops.
        port_conflict_re = _port_conflict_re(port)
        foreign_found: Optional[bool] = None
        reassign_ok: Optional[bool] = None
        second_collision = False
        retries_consumed = 0
        # Buffers carrying the FINAL (post-retry) port and stderr — used to
        # build the FailureContext below.
        active_port = port
        active_up_stderr = up_stderr_full
        active_up_stdout = up_stdout_full

        if port_conflict_re.search(up_stderr_full):
            ps_out = _docker_ps_for_port(port)
            foreign_found = _parse_foreign_holder(ps_out, compose_project)
            if foreign_found:
                # Tear down first to release any partial state.
                subprocess.run(
                    ["docker", "compose", "down", "-v"],
                    cwd=str(app_path),
                    capture_output=True,
                    timeout=60,
                    env=docker_env,
                )
                new_port = _allocate_ephemeral_port()
                docker_env["RUNNER_HOST_PORT"] = str(new_port)
                retries_consumed = 1
                up2 = subprocess.run(
                    ["docker", "compose", "up", "-d"],
                    cwd=str(app_path),
                    capture_output=True,
                    timeout=300,
                    env=docker_env,
                )
                up2_stderr = up2.stderr.decode("utf-8", errors="replace") if up2.stderr else ""
                up2_stdout = up2.stdout.decode("utf-8", errors="replace") if up2.stdout else ""
                if up2.returncode == 0:
                    ok2 = _wait_for_ready(
                        f"http://localhost:{new_port}", health_timeout_s
                    )
                    reassign_ok = ok2 is not None
                    if reassign_ok:
                        # SUCCESS via retry — emit a pass Verdict (B-8 sink).
                        api_url2 = f"http://localhost:{new_port}"
                        if api_base_suffix:
                            api_url2 = f"{api_url2}{api_base_suffix.rstrip('/')}"
                        _emit_pass_verdict(run_id=run_id, arm=arm)
                        return (api_url2, str(app_path), None)
                else:
                    if _port_conflict_re(new_port).search(up2_stderr):
                        second_collision = True
                    reassign_ok = False
                active_port = new_port
                active_up_stderr = up2_stderr
                active_up_stdout = up2_stdout

        _last_failure_context = _build_failure_context(
            app_path=app_path,
            phase_reached="infra_setup",
            build_stderr=build_stderr_full,
            up_stderr=active_up_stderr,
            raw_evidence=active_up_stdout,
            injected_port=active_port,
            compose_project=compose_project,
            run_id=run_id,
            arm=arm,
            daemon_up_at_failure_time=window["daemon_up_at_failure_time"],
            journal_dockerd_window=window["journal_dockerd_window"],
            foreign_holder_found=foreign_found,
            reassign_retry_success=reassign_ok,
            second_collision_on_free_port=second_collision,
            retry_count=retries_consumed,
            runner_injected_mem_limit=injected_mem_limit,
        )
        _classify_and_emit(_last_failure_context)
        return (
            None,
            None,
            f"docker compose up failed (rc={up.returncode}); see get_last_failure_context()",
        )

    # ----- HEALTH phase ---------------------------------------------------
    api_url = f"http://localhost:{port}"
    if api_base_suffix:
        api_url = f"{api_url}{api_base_suffix.rstrip('/')}"

    probe_url = f"http://localhost:{port}"
    ok_url = _wait_for_ready(probe_url, timeout_s=health_timeout_s)
    if ok_url is None:
        window = _capture_daemon_window()
        logs = subprocess.run(
            ["docker", "compose", "logs", "--tail=200"],
            cwd=str(app_path),
            capture_output=True,
            timeout=30,
            env=docker_env,
        )
        tail = logs.stdout.decode("utf-8", errors="replace")
        _last_failure_context = _build_failure_context(
            app_path=app_path,
            phase_reached="app_runtime",
            build_stderr=build_stderr_full,
            up_stderr=up_stderr_full,
            raw_evidence=tail,
            injected_port=port,
            compose_project=compose_project,
            run_id=run_id,
            arm=arm,
            daemon_up_at_failure_time=window["daemon_up_at_failure_time"],
            journal_dockerd_window=window["journal_dockerd_window"],
            runner_injected_mem_limit=injected_mem_limit,
        )
        _classify_and_emit(_last_failure_context)
        teardown(str(app_path))
        return (
            None,
            None,
            (
                f"health probe never returned 2xx/3xx within "
                f"{health_timeout_s}s; logs tail: {tail}"
            ),
        )

    # ----- SUCCESS --------------------------------------------------------
    _emit_pass_verdict(run_id=run_id, arm=arm)
    return (api_url, str(app_path), None)


def teardown(app_dir: str, compose_project: Optional[str] = None) -> None:
    """Run ``docker compose down -v`` from inside ``app_dir``.

    Never raises — teardown failures are logged via the returncode of
    the subprocess but swallowed so a failed teardown of arm N can't
    prevent arm N+1 from running. The arm_4 reliability count is
    where teardown flakiness surfaces, not as a hard crash.

    If ``compose_project`` is not given, defaults to the project of the
    most recent ``run_app`` call (so spike callers preserve back-compat
    without needing to thread the project through). Pilot callers may
    pass explicit project names to tear down out-of-order runs.
    """
    docker_env = os.environ.copy()
    project = compose_project or _last_compose_project
    if project:
        docker_env["COMPOSE_PROJECT_NAME"] = project
    try:
        r = subprocess.run(
            ["docker", "compose", "down", "-v"],
            cwd=str(app_dir),
            capture_output=True,
            timeout=60,
            env=docker_env,
        )
        if r.returncode != 0:
            _logger.warning(
                "teardown: docker compose down exited rc=%d (project=%s); "
                "arm_4 reliability counter SHOULD increment. stderr=%r",
                r.returncode,
                project,
                (r.stderr or b"")[:500],
            )
    except Exception as e:
        _logger.warning(
            "swallowed: teardown raised %r (project=%s) — arm coupling risk",
            e,
            project,
        )


# ---------------------------------------------------------------------------
# Probe helpers used by arm 3 (airbnb auth-helper smoke).
# ---------------------------------------------------------------------------

def probe_login_endpoint(api_url: str) -> Optional[str]:
    """Probe whether the running app at ``api_url`` has a /login or
    /api/login endpoint.

    Returns the matching base (e.g. ``http://localhost:3000`` or
    ``http://localhost:3000/api``) on which a POST to ``{base}/login``
    plausibly exists, or None if neither shape responded with
    anything other than 404 / connection error.

    "Plausibly exists" = the endpoint returned ANY status other than
    404 to a POST with a JSON body. 4xx other than 404 (e.g. 400
    "missing email", 401 "wrong creds", 422 "validation") all count
    as evidence the route is wired. 5xx counts too — that means the
    route exists but errored; the auth helper will encounter that.
    """
    for base in (api_url, f"{api_url}/api"):
        url = f"{base}/login"
        try:
            r = requests.post(url, json={"email": "probe@example.com",
                                         "password": "probe"},
                              timeout=5)
            if r.status_code != 404:
                return base
        except Exception:
            continue
    return None
