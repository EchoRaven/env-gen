"""Deterministic api_smoke validation runner (§6, framework-driven).

The verifier used to drive validation as a free-agentic multi-step LLM loop
(docker_up → test_api per endpoint → judge) and reliably STALLED before reaching
the runtime checks (smoke #7). This module is the ``[P]`` (procedural) form from
the §0.5 execution model: ONE deterministic procedure that brings the env up
clean, exercises the embedded-AS auth + every business endpoint, and returns a
structured verdict. The verifier LLM's role shrinks to "call it + record the
verdict" — no multi-step orchestration to drift through.

What it checks (the api_smoke contract):
  1. ``docker compose down -v && up -d --build`` — a CLEAN boot (no stale pg vol).
  2. backend ``/health`` reachable (else the backend crashed → FAIL, with logs).
  3. ``POST /auth/register`` mints an access token (embedded AS works).
  4. every business endpoint is REACHABLE with the token (status < 500 — a 4xx is
     a validation/shape response, NOT a crash; a 5xx or connection error IS a
     failure: the endpoint isn't wired or the handler throws) AND — GATE-C1 —
     actually IMPLEMENTED when its registration says so: a 404/405 from a
     ``status=implemented`` endpoint is a contract lie, not a pass (a 404 on a
     path WITH params stays soft — the probe substitutes dummy ids; endpoints
     not yet claiming implemented, i.e. later-milestone work, stay soft too).
  5. a business endpoint WITHOUT a token returns 401 (auth enforced).

Pure stdlib (subprocess + urllib) so it has no extra deps and runs anywhere the
generator runs. Returns a report; never raises (failures are recorded, not thrown).
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple
# #936: docker is absent on a podman gen host; resolve the runtime instead of assuming.
from env_generator.llm_generator.multi_agent.runtime.container_runtime import runtime_bin as _rt936
from .message_format import join_capped  # #1034

_LOG = logging.getLogger(__name__)


def pick_auth_probe_endpoint_1202ih(gets):
    """The GET whose CONTRACT promises a denial, or None when none does.

    #1202ih. Module-level and named so a test can exercise THIS, not a copy of it: the
    first draft of the test file re-implemented the selection inline, so reverting the
    production code to the blind first-GET left every case green. Two of three
    counter-proofs passed on a stand-in.
    """
    try:
        from .route_projector import _stated_auth_1202hi
    except Exception:
        return None
    for _e in gets or []:
        try:
            if _stated_auth_1202hi(_e) is True:
                return _e
        except Exception:
            continue
    return None

# A cold docker build for a heavy app (React npm-install+build + backend + postgres + staged assets)
# can exceed the old 300s cut-off mid-`up --build` (r6: 6/6 api_smoke attempts timed out at 300s →
# validation never ran → the visual gate never ran → no delivery). Reliability > speed: let the
# build finish. Override with ENVGEN_DOCKER_UP_TIMEOUT.
_DOCKER_UP_TIMEOUT = int(os.environ.get("ENVGEN_DOCKER_UP_TIMEOUT", "1200") or 1200)

# #566l (netflix r122 run_validation 20-min hang): the old `up -d --build` re-ran the app's
# network package installs (frontend `npm install`, backend `uv pip install`) on EVERY validation
# with no caching, so a flaky registry/proxy window hung the build for the full 1200s docker-up cap
# → no successful run → M1 gate wedged. Fixes: (a) build with RETRY so a transient blip recovers and
# the classic layer cache makes retries resume from completed layers (offline-capable once warm);
# (b) FAIL-FAST — a dedicated, shorter build timeout + a short up-only timeout with a clear
# "build hung on npm/uv (network)" diagnostic instead of burning the whole cap; (c) SKIP the rebuild
# entirely when the app source is unchanged since the last SUCCESSFUL build (reuse the cached image).
# All env-overridable; raise ENVGEN_DOCKER_BUILD_TIMEOUT if a legit cold build needs longer.
_DOCKER_BUILD_TIMEOUT = int(os.environ.get("ENVGEN_DOCKER_BUILD_TIMEOUT", "900") or 900)
_UP_ONLY_TIMEOUT = int(os.environ.get("ENVGEN_DOCKER_UP_ONLY_TIMEOUT", "240") or 240)
_BUILD_RETRIES = int(os.environ.get("ENVGEN_DOCKER_BUILD_RETRIES", "1") or 1)

# #1046: successful container rebuilds, so the stuck-abort's forward-PROGRESS signature can see
# a DEPLOY. `_deliver_progress_sig` keys on app SOURCE + contract + chain versions, none of which
# move when an already-written route is finally built into the image — and that build is the one
# event that can flip a "route 404s" blocker. r177 died on exactly that gap: `main.py` had
# `@app.post("/api/continue-watching")` from 08:12, the 404 evidence behind its terminal
# `business_chain_failing` was last observed at 09:22:45, the image was rebuilt at 10:08:53, and
# the STUCK detector aborted at 10:09:10 — 17 seconds later, on 46-minute-old evidence, without
# the grace that a rebuild should have earned. The rebuilt image DOES serve the route (verified:
# it answers 401, not 404).
#
# Process-global on purpose: one generation per process, and threading a counter through the
# compose helpers would put it in five signatures for one integer.
_BUILDS_OK_1046: int = 0


def _note_build_ok_1046() -> None:
    global _BUILDS_OK_1046
    _BUILDS_OK_1046 += 1


def builds_completed_1046() -> int:
    """Count of successful container builds this run — a DEPLOY-side progress signal."""
    return _BUILDS_OK_1046
_SKIP_UNCHANGED_BUILD = (
    os.environ.get("ENVGEN_SKIP_UNCHANGED_BUILD", "1") or "1").strip().lower() in (
    "1", "true", "yes", "on")


def _compose(compose_file: Path, *args: str, cwd: Path, timeout: int = 300) -> subprocess.CompletedProcess:
    # Pin the CLASSIC builder (DOCKER_BUILDKIT=0), matching every other compose-build
    # path (tools/docker_tools._run_compose, tools/_runtime_env, runhub/compose.py).
    # BuildKit's progress writer ELIDES per-step log lines when stdout/stderr is a
    # non-TTY pipe (capture_output=True), so a frontend `[vite:esbuild] Transform
    # failed with 1 error` was captured WITHOUT its file:line code-frame — every lane
    # saw a useless truncated head and re-ran the build blindly until the run wedged
    # on docker_up (smoke-notes 2026-06-19). The classic builder streams full step
    # logs, so the real esbuild error reaches the repair agent.
    import os as _os
    # #961: resolve the container CLI rather than hardcoding `docker` — see container_runtime.
    try:
        from .container_runtime import runtime_bin as _rb
        _bin = _rb()
    except Exception:
        _bin = "docker"
    # #964: announce the spawn BEFORE it blocks. These calls own the longest silent
    # windows in a run (build up to _DOCKER_BUILD_TIMEOUT, up to _DOCKER_UP_TIMEOUT)
    # and used to emit nothing at all — no start line, no argv, no elapsed — so an
    # in-progress cold build was indistinguishable from a wedged process from the
    # outside (netflix r155). Naming the verb and the cap up front makes the wait
    # self-explaining; the completion line gives rc + how long it actually took.
    _verb = " ".join(args) or "(no args)"
    _LOG.info("compose spawn: %s %s (timeout=%ss, cwd=%s)", _bin, _verb, timeout, cwd)
    _t0 = time.monotonic()
    # #1202hn: serialize the container-LIFECYCLE verbs against RunHub, which drives the SAME
    # compose project from its own subprocess with no coordination. r105: this function's
    # `up -d --remove-orphans` landed inside RunHub's in-flight `up` and removed a container
    # it had just created, so RunHub recorded `aborted` (`No such container`) while the stack
    # was in fact healthy -- seven seconds later the run read live seed counts off it. That
    # false `aborted` is what `deliverability_no_successful_run` reports, and no lane can
    # touch it. `build` is deliberately NOT serialized (see compose_mutex).
    from contextlib import nullcontext as _nullctx1202hn
    from .compose_mutex import compose_mutex_1202hn, is_lifecycle_op_1202hn
    _guard1202hn = (compose_mutex_1202hn(cwd, _verb, timeout_s=float(timeout))
                    if is_lifecycle_op_1202hn(args) else _nullctx1202hn())
    try:
        with _guard1202hn:
            cp = subprocess.run(
                [_bin, "compose", "-f", str(compose_file), *args],
                cwd=str(cwd), capture_output=True, text=True, timeout=timeout,
                env={**_os.environ, "DOCKER_BUILDKIT": "0", "COMPOSE_DOCKER_CLI_BUILD": "0"},
            )
    except subprocess.TimeoutExpired:
        _LOG.warning("compose spawn: %s %s TIMED OUT after %.0fs (cap %ss)",
                     _bin, _verb, time.monotonic() - _t0, timeout)
        raise
    _LOG.info("compose spawn: %s %s -> rc=%s in %.0fs",
              _bin, _verb, cp.returncode, time.monotonic() - _t0)
    # #1202kz: remember what we just did to this project, so container_runtime can tell an
    # anomaly ("we started it and it is gone") from the expected ("we tore it down").
    if cp.returncode == 0:
        try:
            from .compose_mutex import record_lifecycle_1202kz
            record_lifecycle_1202kz(compose_file, args[0] if args else "")
        except Exception:
            pass
    # #972: a FAILING spawn must say WHY. #964 announced `rc=1 in 0s` and stopped there,
    # which is enough to see that something broke and useless for diagnosing it — netflix
    # r158 produced two instant `docker build -> rc=1 in 0s` and left no other trace, so
    # the cause could not be recovered from the log at all. The transcript IS captured
    # (capture_output=True); it was simply never emitted. `_build_with_retry` folds a tail
    # into its return value, but only the caller that ultimately FAILS surfaces it, so a
    # failure that later self-heals vanishes silently. Bounded so a noisy build cannot
    # flood the log.
    if cp.returncode != 0:
        # #1129: #972 got the transcript EMITTED; it still does not carry the error.
        # Two independent losses, both in the two lines this replaces:
        #
        #   1. stdout was appended ONLY when stderr was blank. It never is: compose v2
        #      writes its progress ("Service frontend  Building") and the classic builder
        #      writes "The command '/bin/sh -c npm run build' returned a non-zero code: 1"
        #      to STDERR, while the compile error itself -- the Vite/rollup/tsc diagnostic
        #      naming the file and the symbol -- goes to STDOUT. So the one stream that
        #      held the answer was discarded in full, every time.
        #   2. what survived was then sliced to the LAST 600 chars, which for a build is
        #      the epilogue banner. Same truncate-before-extract shape as #1119, and
        #      `_salient_error` was written for exactly this case: its own docstring cites
        #      a frontend "'LoginPage' has already been declared" sitting at the TOP of a
        #      long transcript. It scans every line for error markers and falls back to
        #      the tail when none match, so it is never empty.
        #
        # Measured over the two runs on the current code (24 build-failure reports, all
        # from netflix-local-r1 and smoke-notes): 24 of 24 carried no error line at all --
        # only "returned a non-zero code: 1". The cost is not merely a thin log. In
        # netflix-local-r1 the frontend build failed at 13:29 (builds recovered at 13:36,
        # and the stack cycled hard afterwards -- 80 compose `up`, 102 `down`), and every
        # one of the visual judge's three remaining attempts found nothing serving on
        # :8080: "capture unavailable -- 0 of 13 screen(s) photographed" at 13:44, 14:10
        # and 15:03. Its verdict stayed frozen at the 13:21 score for the last 1h42m of the
        # run. Whether those probes lost a race with a down window or the frontend was
        # genuinely broken is exactly what the deleted transcript would have said.
        _streams = [t for t in ((cp.stdout or ""), (cp.stderr or "")) if t.strip()]
        _full = "\n".join(_streams).strip()
        try:
            from .framework_validation import _salient_error as _se_1129
            _tail = _se_1129(_full, cap=900) or _full[-600:]
        except Exception:
            # best-effort: an extractor that raises must not silence the report it exists
            # to enrich.
            _tail = _full[-600:]
        if _build_context_race_1202iw(_full):
            _tail = (_tail or "") + _RACE_NOTE_1202IW
        _LOG.warning("compose spawn: %s %s FAILED rc=%s — transcript tail:\n%s",
                     _bin, _verb, cp.returncode, _tail or "(the command produced no output)")
        # #1202cn: say when the HOST is the problem, because no lane can fix it.
        #
        # r37 ran 168 minutes and spent $371.74 over 4910 calls without ever reaching a
        # single visual judgment. Every `docker up` failed the same way, forty times:
        # "could not find an available, non-overlapping IPv4 address pool among the
        # defaults" -- Docker's pools run out near 31 networks and sixteen finished runs
        # still held theirs. Nothing said so. The failure arrived as a plain `docker_up`
        # failure, the orchestrator kept escalating stalls and nudging silent lanes, and
        # the lanes kept being asked to fix an application that was never the problem.
        #
        # tools/docker_tools.py already recognises two of these shapes for the tools an
        # AGENT calls; this is the path the FRAMEWORK calls, and it recognised none.
        #
        # Announce only -- deliberately not an abort. Aborting on a transient (a port
        # freed a second later, a daemon restarting) would be worse than a wasted retry,
        # and this repo has been burned acting on static inference before. What it buys
        # is that minute five says what minute 168 said.
        try:
            _low = (_full or "").lower()
            _host = next((m for k, m in _HOST_LEVEL_1202CN.items() if k in _low), None)
            # #1202hr: no known wording matched — so go and MEASURE the one host condition
            # that reliably surfaces as something else entirely.
            if not _host:
                _host = low_docker_disk_1202hr()
            if _host:
                _LOG.error(
                    "#1202cn this is a HOST failure, not the app's: %s. No lane can fix "
                    "it and remediation will not converge — the operator has to clear it "
                    "before this run can validate anything.", _host)
        except Exception:
            pass
    return cp


def low_docker_disk_1202hr(usage=None, root=None, floor_gb: float = 10.0):
    """#1202hr — is the filesystem docker stores images on out of room? MEASURED, not matched.

    tiktok-web-r106: the root filesystem holding /var/lib/docker was at 100% with 5.0G left
    (1035 dangling images, 176GB reclaimable). What the run reported was
    `Error processing tar file(exit status 1): unexpected EOF`, then `/health` never becoming
    healthy ("server disconnected without sending a response after 31 attempts"), then
    `ERR_CONNECTION_REFUSED` on every page — and the orchestrator filed a backend P0 "to
    restore healthcheck/startup". A host fault laundered into a lane defect, which this
    repo has paid for before: a lane once spent 45 minutes on one and then fabricated a fix.

    `_HOST_LEVEL_1202CN` exists to stop exactly that and could not fire: it matches the
    daemon's WORDING, and disk exhaustion never said "no space left on device". A condition
    that can be measured must not be inferred from text.

    The path matters as much as the check. The launcher's own preflight reads the filesystem
    the REPO sits on and printed `free=102G` while / had 5.0G, so it passed a doomed run;
    this asks docker where it actually writes.

    Returns None when there is room, when docker cannot be asked, or when the read fails —
    "could not tell" is not a verdict in either direction (#883), and this annotates a
    failure that has already happened, so silence costs nothing.
    """
    import shutil as _sh1202hr
    try:
        _root = (root or _docker_root_dir_1202hr)()
        if not _root:
            return None
        du = (usage or _sh1202hr.disk_usage)(_root)
        free_gb = float(getattr(du, "free", 0)) / (1024.0 ** 3)
    except Exception:
        return None
    if free_gb >= float(floor_gb):
        return None
    return ("docker's storage filesystem (%s) has only %.1fG free — a compose build writes "
            "hundreds of MB of layers plus the tar context, and r106 failed at 5.0G with "
            "`unexpected EOF` rather than any disk error. Reclaim space before retrying: "
            "`docker image prune -f` (dangling layers only, touches no running container; it "
            "recovered 176GB there), then `docker builder prune -f`"
            % (_root, free_gb))


def _docker_root_dir_1202hr():
    """Where the daemon stores images. Asked, not assumed — a host may relocate it."""
    try:
        from .container_runtime import runtime_bin as _rb
        _bin = _rb()
    except Exception:
        _bin = "docker"
    try:
        cp = subprocess.run([_bin, "info", "--format", "{{.DockerRootDir}}"],
                            capture_output=True, text=True, timeout=15)
        out = (cp.stdout or "").strip()
        if cp.returncode == 0 and out:
            return out
    except Exception:
        pass
    return "/var/lib/docker"


# #1202cn: compose failures the HOST owns. Keyed on the daemon's own wording, lowercased.
# Each names the remedy, because this message is read by whoever has to clear it.
_HOST_LEVEL_1202CN = {
    "non-overlapping ipv4 address pool": (
        "docker has run out of network address pools (the defaults run out near 31 "
        "networks) — stop the finished runs' stacks (`docker compose down`, without `-v`, "
        "keeps the volumes) and `docker network prune -f`"),
    "cannot connect to the docker daemon": (
        "the docker daemon is not reachable — start it, or fix access to docker.sock"),
    "no space left on device": (
        "the disk is full — reclaim space before retrying"),
    "port is already allocated": (
        "a host port this stack needs is held by another container — stop whatever holds "
        "it, or move this run to different ports"),
}


def _compose_capture(compose_file: Path, *args: str, cwd: Path, timeout: int):
    """#566l: `_compose` that converts a TimeoutExpired into a synthetic FAILED result
    (returncode 124) instead of raising, so a hung build/up is handled as a normal failure
    (fail-fast + retry) rather than propagating. Returns ``(CompletedProcess, timed_out)``."""
    try:
        return _compose(compose_file, *args, cwd=cwd, timeout=timeout), False
    except subprocess.TimeoutExpired as e:
        _out = e.stdout if isinstance(e.stdout, str) else (
            e.stdout.decode("utf-8", "ignore") if isinstance(e.stdout, (bytes, bytearray)) else "")
        _err = e.stderr if isinstance(e.stderr, str) else (
            e.stderr.decode("utf-8", "ignore") if isinstance(e.stderr, (bytes, bytearray)) else "")
        return subprocess.CompletedProcess(e.cmd, 124, _out or "", _err or ""), True


def _app_source_fingerprint(compose_file: Path) -> Optional[str]:
    """#566l-c: content hash of everything that feeds the docker BUILD — the app/ source
    (backend + frontend) plus the compose file — so an unchanged source can skip the rebuild.
    Excludes build OUTPUTS + deps (node_modules/dist/__pycache__/…). Returns None on ANY read
    error → the caller treats None as 'changed' and rebuilds (fail-safe: never skip on doubt)."""
    import hashlib
    root = compose_file.parent.parent / "app"
    if not root.is_dir():
        return None
    skip = {"node_modules", "dist", "build", "__pycache__", ".git", ".vite",
            ".next", "coverage", ".pytest_cache", ".turbo", ".cache"}
    h = hashlib.sha256()
    try:
        h.update(b"compose\0")
        h.update(compose_file.read_bytes())
        for p in sorted(root.rglob("*")):
            if not p.is_file():
                continue
            if any(part in skip for part in p.parts):
                continue
            h.update(str(p.relative_to(root)).encode("utf-8", "ignore"))
            h.update(b"\0")
            h.update(p.read_bytes())
        return h.hexdigest()
    except Exception:
        return None


def _read_build_fingerprint(cwd: Path) -> Optional[str]:
    try:
        fp = cwd / ".last_build_fingerprint"
        return fp.read_text(encoding="utf-8").strip() if fp.is_file() else None
    except Exception:
        return None


def _write_build_fingerprint(cwd: Path, val: Optional[str]) -> None:
    try:
        (cwd / ".last_build_fingerprint").write_text(val or "", encoding="utf-8")
    except Exception:
        pass


# #1202iw: THE BUILD CONTEXT CHANGED WHILE DOCKER WAS TARRING IT. NOT APP CODE.
#
# `docker build` streams the context directory into the daemon as a tar. The lanes write into
# that same directory continuously, so a file that grows between `stat` and `read` makes the
# tar entry short and the whole stream dies:
#
#     Can't add file .../app/frontend/vite.config.js to tar: archive/tar: missed writing N bytes
#     Can't close tar writer: archive/tar: missed writing N bytes
#     Error response from daemon: Error processing tar file(exit status 1): unexpected EOF
#
# 26 of the 423 failed builds in this corpus (6.1%) are this, across tiktok and netflix. The
# retry clears it every time -- but nothing SAID so, and in r110 the verifier read the failure
# and filed `Docker frontend build fails while packaging frontend assets` as a P0. That P0 was
# still open at the delivery cut and is named in the #743 blocker line that kept the run from
# releasing. A lane cannot fix a race in the framework's own packaging step; it can only
# rewrite app code that was never wrong, which is the failure mode the iron law about
# framework-owned code exists to prevent.
_BUILD_CONTEXT_RACE_1202IW = re.compile(
    r"archive/tar: missed writing|Can't close tar writer|"
    r"Error processing tar file\(exit status \d+\): unexpected EOF",
    re.I,
)

_RACE_NOTE_1202IW = (
    " [#1202iw] This is the FRAMEWORK's build-context packaging racing the lanes' own writes "
    "-- docker tars app/ while an agent is still writing into it, so a file changes size "
    "mid-stream and the tar aborts. It is NOT a defect in the application code and NO source "
    "change can fix it; the retry below re-tars a settled directory and succeeds. Do not open "
    "a bug for it and do not rewrite the file docker named."
)


def _build_context_race_1202iw(transcript: Any) -> bool:
    """True when a build transcript carries the context-tar race signature."""
    return bool(_BUILD_CONTEXT_RACE_1202IW.search(str(transcript or "")))


def _build_with_retry(compose_file: Path, cwd: Path) -> Tuple[bool, str]:
    """#566l-a/b: `docker compose build` with a bounded timeout + RETRY. A retry resumes from
    the classic layer cache (completed layers = offline), so a transient registry blip recovers;
    a persistent hang fails in bounded time with a clear diagnostic instead of eating the cap.
    Returns ``(ok, detail)``."""
    last = "docker build did not run"
    _raced_1202iw = False
    for attempt in range(_BUILD_RETRIES + 1):
        cp, timed_out = _compose_capture(
            compose_file, "build", cwd=cwd, timeout=_DOCKER_BUILD_TIMEOUT)
        if cp.returncode == 0:
            _note_build_ok_1046()
            if _raced_1202iw:
                # Say it OUT LOUD on the way past. A lane that saw the failed attempt has no
                # other way to learn the retry settled it, and silence here is what let r110's
                # verifier carry a framework race into a P0 that blocked the delivery cut.
                _LOG.info("compose spawn: docker build recovered on attempt %s — the earlier "
                          "failure was the #1202iw build-context tar race, not app code.",
                          attempt + 1)
            return True, ""
        tail = (((cp.stdout or "") + "\n" + (cp.stderr or "")).strip())[-3000:]
        _raced_1202iw = _raced_1202iw or _build_context_race_1202iw(tail)
        if timed_out:
            last = (f"docker build exceeded {_DOCKER_BUILD_TIMEOUT}s "
                    f"(attempt {attempt + 1}/{_BUILD_RETRIES + 1}) — most likely a hung "
                    f"npm/uv package install on a flaky registry/proxy (the app build fetches "
                    f"packages from the network). Raise ENVGEN_DOCKER_BUILD_TIMEOUT if this is a "
                    f"genuinely slow cold build. Build transcript tail:\n" + tail)
        else:
            last = (f"docker build FAILED (attempt {attempt + 1}/{_BUILD_RETRIES + 1})."
                    + (_RACE_NOTE_1202IW if _build_context_race_1202iw(tail) else "")
                    + f" Transcript tail:\n" + tail)
    return False, last


def _declared_host_port_from_compose(compose_file: Path, service: str) -> Optional[int]:
    """The published HOST port from the compose ``services.<svc>.ports`` mapping
    (``"HOST:CONTAINER"`` — scaffolder.py writes ``"{api_port}:{backend_port}"``).
    Deterministic + engine-agnostic: the framework KNOWS this port at scaffold time,
    so a live-query miss must never wedge api_smoke. Best-effort → None."""
    try:
        import yaml  # engine dep
        data = yaml.safe_load(Path(compose_file).read_text(encoding="utf-8")) or {}
        svc = ((data.get("services") or {}).get(service) or {})
        for entry in (svc.get("ports") or []):
            s = str(entry.get("published") if isinstance(entry, dict) else entry)
            m = re.search(r"(?:^|:)(\d+):\d+(?:/\w+)?$", s) or re.match(r"^(\d+)$", s)
            if m:
                return int(m.group(1))
    except Exception:
        return None
    return None


def _service_host_port(compose_file: Path, cwd: Path, service: str) -> Optional[int]:
    """Resolve the published host port of a compose service.

    ``docker compose ps -q <service>`` works on Docker Compose v2, but
    podman-compose's ``ps`` has NO service positional (argparse: "unrecognized
    arguments: <service>", exit 2, EMPTY stdout). On a podman-backed gen host that
    returned "" → None → api_smoke wedged on "could not resolve backend published
    port" and business_chain never executed (it early-returns before the chain
    stage). Fall back to a container-name lookup (`ps --filter name=<service>`,
    which podman DOES support), and finally to the compose file's DECLARED port
    (deterministic; a live-query hiccup must never wedge a functioning app). On
    Docker the first path resolves, so the fallbacks never run (unchanged)."""
    try:
        cid = _compose(compose_file, "ps", "-q", service, cwd=cwd, timeout=30).stdout.strip()
        cid = cid.splitlines()[0].strip() if cid else ""
        if not cid:
            # #1136: the name-filter fallback used to take the FIRST container matching
            # `name=<service>` ANYWHERE on the host, with no check that it is ours, and then
            # report ITS published port as this app's address. `compose ps -q` returns empty
            # whenever this run's stack is down, so the fallback runs often — and on a host
            # with other sandboxes it resolves a stranger.
            #
            # It did. Replaying `gather_squad_inputs` against netflix-local-r2's own artifact
            # returns api_base=http://localhost:3011 and ui_base=http://localhost:8096 —
            # while that run's compose declares 3000:8081 and 8080:3000. :3011 is the
            # rydr/Uber sandbox (`/openapi.json` → {"info":{"title":"uber"}}) and :8096 is
            # another project's frontend. So the FRAMEWORK, not a hallucinating agent, is what
            # pointed r2's test-user squad at someone else's product; it filed all six of its
            # API steps as this app's 404s (api_passed=0, verdict PARTIAL) while this run's own
            # chains were getting 201/200 on the same paths. In all three runs on the current
            # code the app's real port is the LEAST-probed one.
            #
            # #962 fixed exactly this shape for `container_id()` — match the
            # `com.docker.compose.project.config_files` label, and return nothing rather than
            # guess ("a probe that answers about another run's container reports confidently
            # about the wrong app"). That guard never reached this second, older lookup. Reuse
            # the guarded resolver instead of keeping a second copy: #665's lesson is that the
            # copy drifts from the original, and this is that drift, three tickets later.
            #
            # Returning "" here is not a loss: the deterministic `_declared_host_port_from_
            # compose` fallback below reads the run's OWN compose file, which is the right
            # answer and cannot belong to anyone else.
            try:
                from .container_runtime import container_id as _cid1136
                cid = _cid1136(compose_file, service) or ""
            except Exception:
                cid = ""
        if cid:
            ports = subprocess.run([_rt936(), "port", cid], capture_output=True, text=True, timeout=30).stdout
            # 0.0.0.0:P / 127.0.0.1:P / [::]:P / :::P (unbracketed IPv6)
            m = re.search(r"(?:\d+\.\d+\.\d+\.\d+|\[?::\]?):(\d+)", ports)
            if m:
                return int(m.group(1))
    except Exception:
        pass
    # deterministic fallback: the compose file's declared host port
    return _declared_host_port_from_compose(compose_file, service)


def _backend_host_port(compose_file: Path, cwd: Path) -> Optional[int]:
    """Resolve the published host port of the ``backend`` service."""
    return _service_host_port(compose_file, cwd, "backend")


# ── FIX #157 (gmrun5): a 5xx probe must report the backend ROOT CAUSE ──────────
# gmrun5 wedged 50min → STUCK on `GET /api/transit/{id}/departures → 500`: the
# remediation carried NOTHING beyond "→ 500", so the backend lane guessed
# ("parameter type"), guessed wrong, reported done, and never re-engaged — while
# the real cause (custom_routes.py:202 comparing a TEXT column to an integer →
# `operator does not exist: text = integer`) sat in the container logs the whole
# time. Third instance of the "gate knows more than it says" class (run-4's
# blank-no-rootcause → #154 exact call sites). Pull the log tail on a 5xx and
# hand the lane the salient last-traceback line, file:line first.

# FIX #161 (gmrun7): the innermost ``/app/`` frame is usually the framework's DB session
# wrapper (``database.py:80 in execute → super().execute(...)``) — the actual fix site is
# the HANDLER one frame out (``main.py:519 in _projected_..._departures`` / a lane
# ``custom_routes.py`` handler). Real run-7 traceback frames were main.py:229 (auth guard),
# main.py:519 (the projected handler), database.py:80 (execute) → the bare-innermost rule
# picked database.py, pointing the lane at framework infra it must not edit. De-prioritize
# the pure-infra backend files so the salient frame names the handler that built the query.
_INFRA_BACKEND_FILES = frozenset({
    "database.py", "seed_data.py", "seed_dataset.py", "models.py"})


def extract_salient_traceback(logs_text: str, limit: int = 320) -> str:
    """The salient line of the LAST Python traceback in a (docker) log tail:
    ``<file>:<line> in <func> — <exception message>``. The frame is the innermost ``/app/``
    frame that is NOT pure framework infra (``database.py``/``models.py``/``seed_*.py`` —
    the DB/ORM wrappers a bug never lives in), so it names the actual HANDLER; falls back to
    the innermost ``/app/`` frame, then the last frame. Strips ``service-1 |`` compose
    prefixes. '' when no traceback."""
    try:
        if not logs_text:
            return ""
        text = re.sub(r"(?m)^[\w.-]+\s*\|\s?", "", logs_text)
        marker = "Traceback (most recent call last):"
        idx = text.rfind(marker)
        if idx == -1:
            return ""
        block = text[idx:]
        frames = list(re.finditer(
            r'File "(?P<path>[^"]+)", line (?P<line>\d+), in (?P<fn>\S+)', block))
        if not frames:
            return ""
        app_frames = [m for m in frames if m.group("path").startswith("/app")]
        handler_frames = [m for m in app_frames
                          if Path(m.group("path")).name not in _INFRA_BACKEND_FILES]
        frame = (handler_frames or app_frames or frames)[-1]
        # the exception line: first non-indented `Some.Error: message` line after
        # the LAST frame of the block (postgres LINE/HINT continuations excluded).
        exc = ""
        tail = block[frames[-1].end():]
        for ln in tail.splitlines():
            if not ln or ln[0] in " \t":
                continue
            if re.match(r"^[\w.]+(Error|Exception|Warning)?\s*:", ln) and ": " in ln:
                exc = ln.strip()
                break
        fname = Path(frame.group("path")).name
        head = f"{fname}:{frame.group('line')} in {frame.group('fn')}"
        return (f"{head} — {exc}" if exc else head)[:limit]
    except Exception:
        return ""


def compose_unreachable_detail(unreachable: List[str], salient: str) -> str:
    """The ``business_endpoints_reachable`` failure detail. With a backend
    traceback, budget the endpoint list down so the file:line root cause lands
    INSIDE the first 300 chars (the urgent-wake message truncates there —
    gmrun5's lane acted on exactly that prefix); without one, the plain join."""
    joined = "; ".join(unreachable)
    if not salient:
        return joined[:800]
    return f"{joined[:220]} | backend traceback: {salient}"[:800]


_CHAIN_5XX_RE = re.compile(r"→\s*5\d\d\b")


def _chain_broken_has_5xx(broken) -> bool:
    """#300 — True when any broken business_chain step returned a 5xx (server
    error). Only then is a backend traceback worth fetching: a 4xx (404 parent
    not found, 400 validation) is self-describing, but a 5xx hides the real
    cause behind FastAPI's opaque 'Internal Server Error'."""
    for s in (broken or []):
        t = str(s)
        if _CHAIN_5XX_RE.search(t) or "Internal Server Error" in t:
            return True
    return False


def _business_chain_detail(broken, salient: str) -> str:
    """#300 — the ``business_chain`` failure detail. r81 M2 STUCK (95min): a chain
    step's POST /replies → 500 showed the lane only 'Internal Server Error' while
    business_endpoints_reachable surfaced the file:line traceback for its 500s and
    those got fixed. Attach the salient backend traceback to a chain 5xx too, so
    the lane sees the real root cause (mirrors compose_unreachable_detail).

    #1202qy -- joined by NEWLINE, not "; ". Every reader downstream is line-based, and the one
    that matters is `_salient_error`, whose whole promise (#182) is "return the marker-matching
    lines, never the misleading prefix". Collapse the list into one line and that promise cannot
    be kept: there is a single line, it matches, and the 200-char clip shows whatever happens to
    sit at position 0.

    tiktok-r129 20:24:35 is the instance. Four chains were failing on
    `POST /api/videos/{id}/comments -> 404`, with the diagnosis already computed beside it
    ("PARENT EXISTS: `GET /api/videos/35` answers 200 right now"). What the orchestrator logged,
    and what the lane was handed, was:

        RELEASE HELD: ... FAILS a fresh api_smoke
        (['business_chain:[build currency #1202ex] These verdicts may not be about the'])

    -- #1202ex's advisory, which sits at index 0 of `broken` by design so a human reading the
    whole list sees it first. One line each and the extractor reaches the 404s again; the
    advisory keeps its place in the list for whoever reads all of it.
    """
    joined = "\n".join(broken or [])
    if not salient:
        return joined[:800]
    return f"{joined[:520]} | backend traceback: {salient}"[:800]


def _backend_logs_tail(compose_file: Path, cwd: Path, tail: int = 200) -> str:
    """Last ``tail`` lines of the backend service's logs; '' on any fault."""
    try:
        r = _compose(compose_file, "logs", "--no-color", "--tail", str(tail),
                     "backend", cwd=cwd, timeout=30)
        return (r.stdout or "") + "\n" + (r.stderr or "")
    except Exception:
        return ""


def _db_readiness_probe_ok(base: str) -> bool:
    """#555 — TRUE DB-readiness (not just HTTP liveness). ``GET /`` answers the moment
    FastAPI is up, but Postgres can still be coming up (compose mid-restart/reseed) — so a
    request that TOUCHES the DB 5xx's on an otherwise-'live' backend (netflix r105: POST
    /auth/login → 500, an uncaught psycopg OperationalError racing the DB). The framework-
    owned ``/auth/login`` opens a DB connection to verify credentials, so a throwaway login
    is a genuine DB-touching probe present in EVERY generated app with the identity spine: it
    returns a non-5xx (401 invalid credentials) once Postgres answers and a 5xx/503 while it
    is still down.

    GENERALIZABLE + byte-identical when there is no DB endpoint: a 404 (no such route, e.g.
    a DB-less app) is <500 → treated as ready (the gate no-ops), so ONLY a real DB-down 5xx
    holds the wait. A connection error (status None) means the backend/DB isn't answering yet
    → not ready. Best-effort — the caller's try/except keeps this from ever raising."""
    r = _http("POST", base + "/auth/login",
              body={"email": "__db_readiness_probe__@example.invalid",
                    "password": "__db_readiness_probe__"},
              timeout=4)
    st = r.get("status")
    if st is None:
        return False
    return st < 500


def wait_backend_ready(project_dir: Any, timeout_s: int = 90, gap_s: float = 3.0) -> bool:
    """Bounded wait until the compose BACKEND answers HTTP (<500) AND Postgres is ready.

    The FINAL delivery gate evaluates LIVE state (sql_tables introspection, business-chain
    runs) and the compose stack restarts between milestones — evaluating mid-restart saw
    sql_tables=4-of-11 + failing chains on a HEALTHY app and KILLED otherwise-delivered runs
    (outlook run-28 → rc=1; run-31 → Status: FAILED, both at orchestrator's post-loop gate).
    Callers wait for readiness, then re-evaluate ONCE before raising — recorded-result checks
    are unaffected; only the live-probed ones get a fair read. Best-effort, never raises.

    #555: HTTP liveness (``GET /`` <500) is necessary but NOT sufficient — FastAPI answers
    while Postgres is still coming up, so the gate must ALSO clear a DB-touching probe
    (``_db_readiness_probe_ok``) before returning ready. The DB probe no-ops (404 → ready)
    for an app without the identity spine, so this stays byte-identical where there is no DB
    endpoint to probe."""
    import time as _time
    try:
        compose = Path(project_dir) / "docker" / "docker-compose.yml"
        cwd = compose.parent
        deadline = _time.time() + max(1, timeout_s)
        while _time.time() < deadline:
            port = _backend_host_port(compose, cwd) if compose.exists() else None
            if port:
                base = f"http://localhost:{port}"
                r = _http("GET", f"{base}/", timeout=4)
                if (r.get("status") is not None and (r.get("status") or 500) < 500
                        and _db_readiness_probe_ok(base)):
                    return True
            _time.sleep(gap_s)
        return False
    except Exception:
        return False


def _safe_url(url: str) -> str:
    """Percent-encode characters urllib refuses — a verifier-authored query like
    ``/api/messages/search?q=Test Message`` reached urlopen with a raw SPACE →
    ``InvalidURL: URL can't contain control characters`` → the step (and the whole
    business_chain) failed forever on a working endpoint (outlook run-29 M3, live).
    ``quote`` with the URL-structural chars in ``safe`` leaves valid URLs (and
    already-encoded %XX sequences) byte-identical; only spaces/non-ASCII change."""
    from urllib.parse import quote
    return quote(url, safe=":/?&=%+,@;$!*'()[]~._-#")


def _form_retry_warranted(body: Optional[dict], status: Optional[int],
                          body_text: str) -> bool:
    """FIX #281 (tiktok r66, live): does this 4xx bear the JSON-vs-FORM signature?

    ``_http`` always sends JSON, but an endpoint may legitimately declare FORM fields —
    the framework's OWN scaffolded ``oauth_routes.py`` does exactly that for
    ``POST /oauth/authorize`` (``email: str = Form(...)``), which is the correct OAuth2
    shape. FastAPI then reports every form field as missing FROM THE BODY, so the step
    400/422s no matter what the verifier authors: the chain-step schema cannot express
    encoding, so the lane is dispatched to fix a defect it has no power to fix. In r66
    that wedged business_chain through all 6 validation attempts → no successful run →
    DELIVERY-GATE NO-CONVERGENCE ABORT at 76min, on an app whose endpoint was FINE
    (re-sent form-encoded by hand: 401 + the real consent page).

    True only when the response names as MISSING FROM THE BODY a field we demonstrably
    DID send — a field we never sent is a genuine validation error and must keep its
    teeth, and a ``loc: ["query", ...]`` miss cannot be cured by re-encoding the body."""
    if not isinstance(body, Mapping) or not body:
        return False
    if not status or not (400 <= status < 500):
        return False
    try:
        payload = json.loads(body_text or "{}")
    except Exception:
        return False
    if not isinstance(payload, Mapping):
        return False
    errs = payload.get("errors")
    if not isinstance(errs, list):
        errs = payload.get("detail")
    if not isinstance(errs, list):
        return False
    sent = {str(k) for k in body}
    for e in errs:
        if not isinstance(e, Mapping):
            continue
        loc = e.get("loc")
        if not isinstance(loc, (list, tuple)) or len(loc) < 2:
            continue
        if str(loc[0]).lower() != "body":
            continue
        if str(e.get("type") or "").lower() != "missing":
            continue
        if str(loc[1]) in sent:
            return True
    return False


def _http(method: str, url: str, *, token: Optional[str] = None,
          body: Optional[dict] = None, timeout: int = 10,
          form: bool = False,
          headers: Optional[Mapping[str, str]] = None) -> Dict[str, Any]:
    """One HTTP call → {status, body_text, error}. Never raises.

    ``form=True`` (FIX #281) urlencodes the body instead of JSON, for endpoints that
    declare FORM fields (OAuth2 authorize/token being the standard case). Default is
    unchanged JSON for every existing caller.

    ``headers`` (#566x) adds request headers the CALLER needs to express a contract
    the URL alone cannot — the control plane's ``X-Tenant-Id`` scope selector being
    the case that motivated it. Omitted → byte-identical to the previous behaviour."""
    if form and body is not None:
        from urllib.parse import urlencode
        data = urlencode({k: ("" if v is None else v) for k, v in body.items()}).encode()
    else:
        data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(_safe_url(url), data=data, method=method.upper())
    req.add_header("Content-Type",
                   "application/x-www-form-urlencoded" if form else "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    for _hk, _hv in (headers or {}).items():
        if _hk and _hv is not None:
            req.add_header(str(_hk), str(_hv))
    # FIX #98 (instagram run-16, live): 2048 bytes TRUNCATED any list response past 2KB
    # mid-JSON — once #74/#84 made seeds dense, explore/feed bodies blew the cap, so
    # json.loads failed SILENTLY in both the chain's save-dig and the auto-capture/
    # harvest → last_id never set → literal ${post_id} → 422 wedge, while the verifier's
    # wiring (save: posts.0.id) was perfect. Read the full body (512KB safety bound —
    # a 50-row page is ~20-30KB); display truncation stays at note-construction time.
    # #1003: keep the response HEADERS. A 405 is REQUIRED by HTTP to carry `Allow:` naming
    # the methods the server does accept, and the HTTPError branch below is exactly where a
    # 405 lands — `e.headers` has it. #1000 fixed the sibling probe path in runhub; THIS is
    # the path that feeds `business_endpoints_reachable`, so r162's detail was built without
    # ever seeing the one header that explains it.
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return {"status": r.status, "body_text": r.read(524288).decode("utf-8", "replace"),
                    "error": None, "headers": dict(getattr(r, "headers", {}) or {})}
    except urllib.error.HTTPError as e:
        return {"status": e.code, "body_text": (e.read(524288).decode("utf-8", "replace") if e.fp else ""),
                "error": None, "headers": dict(getattr(e, "headers", {}) or {})}
    except Exception as e:
        return {"status": None, "body_text": "", "error": f"{type(e).__name__}: {e}", "headers": {}}


def _expected_shape(method: str, path: str) -> Optional[str]:
    """The response-contract shape an endpoint MUST return, derived deterministically
    from method+path (mirrors route_projector's single-vs-collection split):
      - ``"item"`` (single resource → ``{"item": {...}}``): any write
        (POST/PUT/PATCH/DELETE), a GET ending in ``/me``, or a GET ending in a path
        param (``/{id}``).
      - ``"items"`` (collection → ``{"items": [...]}``): any other GET.
    Returns ``None`` when the shape is genuinely ambiguous → skip the assertion."""
    m = method.upper()
    if m in ("POST", "PUT", "PATCH", "DELETE"):
        return "item"
    if m != "GET":
        return None
    last = next((s for s in reversed(path.split("/")) if s), "")
    if last == "me" or (last.startswith("{") and last.endswith("}")) or last.startswith(":"):
        return "item"
    return "items"


def _shape_violation(method: str, path: str, status: Optional[int],
                     body_text: str, ep_status: Any = "implemented") -> Optional[str]:
    """Return a violation message if a 2xx response's shape contradicts the contract
    for its path-type, else None. Conservative — only a clear single↔collection
    mismatch is flagged; a custom/other shape (no item/items key) is left alone."""
    # #1167: THE SAME LOOP'S OTHER GATE ALREADY KNOWS ABOUT STATUS, THIS ONE DID NOT.
    #
    # `_unimplemented_route` is called one line above with `ep.get("status")` and returns
    # None for anything not claiming `implemented` — its own message even offers
    # "implement the route or DEPRECATE the registration" as the escape. `_shape_violation`
    # was never given the status, so a deprecated registration still had its response shape
    # judged. netflix-local-r6: an agent parked `GET /__noop__` at status=deprecated, and
    # the verifier reported "run_validation/api_smoke failed on GET /__noop__ contract
    # shape" — a blocker on an endpoint the contract had already retired. Both delivered
    # artifacts still carry that registration, so this is not a one-run accident.
    if str(ep_status or "").lower() not in ("implemented", ""):
        return None

    expected = _expected_shape(method, path)
    if not expected or not status or not (200 <= status < 300):
        return None
    try:
        payload = json.loads(body_text or "{}")
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    if expected == "item" and "items" in payload and "item" not in payload:
        return f"{method} {path} → returns a list (items) but the contract is a single item"
    if expected == "items" and "item" in payload and "items" not in payload:
        return f"{method} {path} → returns a single item but the contract is a list (items)"
    return None


def _path_with_params(path: str, sample: str = "1") -> str:
    """Substitute path params ({id}/:id/${id}) with a sample value for smoke."""
    path = re.sub(r"\$\{[^}/]+\}", sample, path)
    path = re.sub(r"\{[^}/]+\}", sample, path)
    path = re.sub(r":[A-Za-z_]\w*", sample, path)
    return path


# #1051: a 404 whose BODY proves the route ran. The generated backend maps a foreign-key
# violation onto 404 with its own marker (main.py: "(rating / my_list / continue_watching)
# FK-VIOLATE -> 404 'referenced ...'"), so "referenced resource not found" means the route
# matched, executed, and rejected the PAYLOAD. FastAPI's genuine unrouted 404 is the literal
# {"detail":"Not Found"}.
_ROUTE_RAN_404_MARKERS_1051 = (
    "referenced resource not found",
    "referenced resource does not exist",
    "does not exist",
    "referenced",
)


def _route_ran_despite_404_1051(body_text: Any) -> bool:
    """True when a 404 body shows the ROUTE executed and rejected the request payload."""
    t = str(body_text or "").lower()
    if not t:
        return False
    return any(m in t for m in _ROUTE_RAN_404_MARKERS_1051)


def _unimplemented_route(method: str, path: str, ep_status: Any,
                         status_code: Optional[int],
                         body_text: Any = None) -> Optional[str]:
    """Return a violation message when an endpoint REGISTERED as
    ``status=implemented`` answers 404/405 — the route isn't actually wired, a
    contract lie the bare <500 rule counted as a pass (GATE-C1: the single
    trigger that lit ``functionally_validated`` and degraded the coverage/seed/
    visual/ui_flow delivery gates to warnings).

    Calibrated on generated/instagram round47 (768 contract-test records of the
    released app):
      * a 404 on a path WITH params stays soft — the probe substitutes dummy
        ids ("1"), so the parent resource may legitimately not exist (GET
        /api/users/{username}/posts 404s because user "1" is absent; the
        exemption is contains-a-param, NOT ends-with-param — that endpoint ends
        in /posts and would otherwise be a false FAIL).
      * a 404 on a param-less path = the route is not registered → FAIL.
      * a 405 = the path matched but the METHOD isn't wired → FAIL, params or
        not (never appears on a working app).
    Endpoints not yet claiming implemented (defined/implementing/revising —
    later-milestone or in-revision work) keep the soft <500 rule."""
    if status_code not in (404, 405):
        return None
    if str(ep_status or "").lower() != "implemented":
        return None
    if status_code == 404 and _path_with_params(path) != path:
        return None
    # #1051: ...and a param-LESS 404 whose body is the backend's FK-violation marker is also
    # not an unregistered route. r179: `POST /api/my-list -> 404` with
    # {"detail":"referenced resource not found"} was reported as "route not registered" while
    # the route existed twice in the delivered source (main.py + custom_routes.py) and the
    # verifier had just passed business_chain 64/64 across 16 chains. r178 then died on
    # exactly this misdiagnosis: "Real blocker: business_endpoints_implemented". The endpoint
    # was fine; the CHAIN sent a title_id/profile_id that does not exist. Those are different
    # defects with different owners, and conflating them routes the backend lane at an
    # endpoint it already implemented.
    if status_code == 404 and _route_ran_despite_404_1051(body_text):
        return None
    why = ("route not registered" if status_code == 404
           else "path matched but the method is not wired")
    return (f"{method} {path} → {status_code} but registered status=implemented "
            f"({why}) — implement the route or deprecate the registration")


def _frontend_navigable(project_dir: Any) -> "tuple[bool, str]":
    """The frontend gate's predicate: the shipped UI must have at least one page
    component AND at least one <Route> in the app shell — else it renders a blank
    page no matter how healthy the backend is."""
    fe_src = Path(project_dir) / "app" / "frontend" / "src"
    # GENERALITY (round 34): with no framework templates the lane chooses its
    # own layout (components/, views/, features/...) — counting only
    # src/pages/*.jsx failed a working app that kept page components in
    # components/. A "page" here is ANY .jsx component file under src/
    # besides the entry files.
    n_pages = len([f for f in fe_src.rglob("*.jsx")
                   if f.name not in ("App.jsx", "main.jsx")]) if fe_src.is_dir() else 0
    app_jsx = fe_src / "App.jsx"
    n_routes = 0
    if app_jsx.exists():
        try:
            n_routes = len(re.findall(r"<Route\s", app_jsx.read_text(encoding="utf-8")))
        except Exception:
            n_routes = 0
    ok = n_pages >= 1 and n_routes >= 1
    detail = f"{n_pages} page component(s), {n_routes} route(s)" + (
        "" if ok else " — the frontend is a blank shell; pages/routes must exist before release")
    return ok, detail


def _owner_fk_names_1202nk() -> frozenset:
    """The owner-column vocabulary the projector fills from the caller (#1202jv's single source)."""
    try:
        from .route_projector import _OWNER_FK_NAMES
        return frozenset(str(n).lower() for n in _OWNER_FK_NAMES)
    except Exception as _e:
        from .message_format import warn_once_1201
        warn_once_1201("probe_body_owner_names_1202nk",
                       "cannot load the owner-FK vocabulary; create probes will send owner "
                       "columns and the ownership guard will refuse them", _e)
        return frozenset()


def _is_time_field_1202nk(field: Any, typ: str) -> bool:
    name = str(field or "").lower()
    if any(w in typ for w in ("int", "float", "decimal", "double", "number", "bool")):
        return False            # `watch_time: int` is a duration, not a timestamp
    return (any(w in typ for w in ("timestamp", "datetime", "date", "time"))
            or name.endswith("_at") or name.endswith("_date") or name.endswith("_time"))


def _probe_body(ep: Any) -> dict:
    """Build a create-probe request body from the endpoint's REGISTERED request
    schema — domain-agnostic. Sends exactly the fields the contract declares, with
    type-appropriate placeholders, so the persistence probe works for ANY app (a
    task app's ``{title, description}``, a docs app's ``{title, body}``), not only
    social/instagram-shaped create endpoints. Falls back to common generic text
    fields when no request schema is registered (still NOT app-specific)."""
    req = (ep.get("schema") or {}).get("request") if isinstance(ep, dict) else None
    body: dict = {}
    if isinstance(req, dict):
        _owner_names = _owner_fk_names_1202nk()
        for field, typ in req.items():
            t = str(typ).lower().strip().rstrip("?").strip()
            # #1202nk: two placeholders the framework's own handlers reject. An OWNER column
            # is filled from the caller by the handler, and a literal `1` there is another
            # user's id — the #566s guard answers 403 "profile_id does not belong to the
            # caller" (33 of the 95 failed creates across 221 test-user reports). And a
            # timestamp-named or -typed field got "persist-probe" — tiktok-r125's
            # `created_at: "string?"` answered 400 "invalid input syntax for type timestamp"
            # on every milestone's journey. A create that fails on the probe's own body is
            # "write not verified", which quietly skips the persistence check it feeds.
            if str(field).lower() in _owner_names:
                continue
            if _is_time_field_1202nk(field, t):
                body[field] = "2026-01-01" if t == "date" else "2026-01-01T00:00:00Z"
                continue
            if t.endswith("[]") or t.startswith("list") or "array" in t:
                body[field] = []
            elif t.startswith("{") or "dict" in t or "object" in t:
                body[field] = {}
            elif "bool" in t:
                body[field] = True
            elif "float" in t or "decimal" in t or "double" in t:
                body[field] = 1.0
            elif "int" in t or t in ("number", "integer"):
                body[field] = 1
            else:
                body[field] = "persist-probe"
    if not body:
        # no registered request schema → generic best-effort, domain-agnostic
        body = {"name": "persist-probe", "title": "persist-probe",
                "description": "persist-probe", "text": "persist-probe",
                "content": "persist-probe"}
    return body


def _id_in_rows(new_id, rows) -> bool:
    """FIX #122 (runs 35+41, live): TYPE-TOLERANT id containment for the
    write-persist readback. The POST envelope carries an int id but a lane GET
    handler may stringify every value ("id":"3") — type-strict equality reported
    'write not persisted' on a correctly-persisting app and wedged the run.
    Compare as strings (the platform treats "8"/8 as the same id everywhere
    else); a None id never matches."""
    if new_id is None:
        return False
    try:
        want = str(new_id)
        return any(isinstance(r, dict) and r.get("id") is not None
                   and str(r.get("id")) == want for r in (rows or []))
    except Exception:
        return False


def run_smoke_validation(
    project_dir: Any,
    business_endpoints: List[Mapping[str, Any]],
    *,
    up_timeout: int = _DOCKER_UP_TIMEOUT,
    health_timeout: int = 90,
    teardown: bool = True,
) -> Dict[str, Any]:
    """Run the deterministic api_smoke. Returns a structured report:

        {"passed": bool, "summary": str, "checks": [{name, status, detail}],
         "backend_port": int|None}

    ``business_endpoints`` is a list of ``{method, path}`` (business only — the
    caller filters via ``lifecycle.business_endpoints``)."""
    project_dir = Path(project_dir).resolve()  # absolute → -f path can't double against cwd
    compose_file = project_dir / "docker" / "docker-compose.yml"
    cwd = project_dir / "docker"
    checks: List[Dict[str, Any]] = []
    endpoint_results: List[Dict[str, Any]] = []
    chain_results: List[Dict[str, Any]] = []

    def _add(name: str, ok: bool, detail: str = "") -> None:
        checks.append({"name": name, "status": "pass" if ok else "fail", "detail": detail})

    if not compose_file.exists():
        return {"passed": False, "summary": f"no compose file at {compose_file}",
                "checks": [{"name": "compose_present", "status": "fail", "detail": str(compose_file)}],
                "backend_port": None, "endpoints": []}

    # FRONTEND GATE — a release must ship a NAVIGABLE UI, not a blank shell. The
    # backend has 6 checks below; the frontend previously had ZERO, so an app whose
    # frontend lane authored nothing (0 pages, 0 routes) sailed through api_smoke and
    # released a blank page (instagram 1.0.0, 2026-06-09 — "打不开"). Static + cheap.
    _fe_ok, _fe_detail = _frontend_navigable(project_dir)
    _add("frontend_navigable", _fe_ok, _fe_detail)

    # VISIBILITY (informational): how much of the UI is framework FALLBACK vs lane-authored.
    # The HARD enforcement of "a page the references DEPICT must ship REAL, not the fallback"
    # lives in the reference-aware page_build_gate (pages_release_decision: referenced-unbuilt
    # never escapes), so this check stays informational to avoid double-gating a page that
    # legitimately has no reference to match (its fallback is acceptable).
    try:
        from .frontend_page_projector import _PAGE_MARKER
        _pages_dir = project_dir / "app" / "frontend" / "src" / "pages"
        _total = _fallback = 0
        _fb_names = []
        for _pf in sorted(_pages_dir.glob("*.jsx")) if _pages_dir.is_dir() else []:
            _total += 1
            try:
                if _PAGE_MARKER in _pf.read_text(encoding="utf-8", errors="ignore"):
                    _fallback += 1
                    _fb_names.append(_pf.stem)
            except Exception:
                pass
        _add("frontend_fallback_pages", True,
             f"{_fallback}/{_total} pages are framework fallback ({', '.join(_fb_names[:8])})")
    except Exception:
        pass

    backend_port: Optional[int] = None
    # FIX #36: serialize docker validations. Concurrent boots of the SAME compose
    # project (orchestrator framework-validation + verifier `run_validation`
    # api_smoke) share container names + host ports, so they tear each other down
    # → BOTH report docker_up FAIL ("not yet passing"), and a perfectly
    # deliverable app never validates in-run (confirmed: two concurrent
    # run_smoke_validation calls both fail docker_up). A cross-thread/process file
    # lock makes validations run strictly one-at-a-time.
    # #1202nx: this validation's fresh boot `down -v`s the stack. A test-user squad, browser walk or
    # visual capture that is using the stack right now holds a lease; wait for it BEFORE taking the
    # smoke lock (holding the lock while waiting would stall every other validation and gate).
    try:
        from .compose_mutex import wait_for_stack_leases_1202nx
        wait_for_stack_leases_1202nx(project_dir, "api_smoke validation (fresh boot)", logger=_LOG)
    except Exception:
        pass
    import fcntl as _fcntl
    import time as _time
    _lock_fh = None
    _lock_acquired = False
    try:
        cwd.mkdir(parents=True, exist_ok=True)
        _lock_fh = open(cwd / ".smoke_validation.lock", "w")
        _wait_start = _time.time()
        while True:
            try:
                _fcntl.flock(_lock_fh.fileno(), _fcntl.LOCK_EX | _fcntl.LOCK_NB)
                _lock_acquired = True
                break
            except OSError:
                if _time.time() - _wait_start > 600:
                    break  # gave up waiting (do NOT proceed unlocked — see guard below)
                _time.sleep(2)
    except Exception:
        _lock_fh = None
    # FIX #36-bis: if we could NOT acquire the lock within the wait window, another
    # validation has held it that whole time and is presumably mid `down -v`/`up`.
    # Proceeding here would run `down -v && up` CONCURRENTLY against the SAME compose
    # project → both tear each other's containers down → both report docker_up FAIL
    # (the exact race FIX #36's lock exists to prevent). Trading a hang for a race is
    # worse. Defer instead: surface a non-fatal lock_timeout so the framework retries
    # this validation once the lock frees, rather than corrupting a deliverable app.
    if not _lock_acquired:
        _add("docker_up", False,
             "smoke-validation lock not acquired within 600s — another validation is "
             "holding it; deferring to avoid a concurrent docker down/up race (will retry).")
        return _finalize(checks, None, endpoint_results)
    try:
        # 1. Clean boot (no stale postgres volume — see DockerUpTool fresh=True).
        # FIX #113: re-stage design assets by construction before the image build —
        # a lane checkout window can transiently drop tracked public/assets/ files.
        try:
            from .frontend_scaffold import ensure_assets_staged_for_build
            ensure_assets_staged_for_build(compose_file)
        except Exception:
            pass
        # FIX #125 (run-43 M3, live): #119's param-vs-projection repair is wired into
        # tools/docker_tools._run_compose (#121) + heal — but the FRAMEWORK VALIDATION
        # build goes through THIS module's own _compose, so the repair never fired here
        # and the validation image kept baking the lane's `username: int` on a
        # string-keyed route → GET /api/users/{username} 422/500 →
        # business_endpoints_reachable wedged (repair fixes it standalone: fixed=2).
        # Apply it to app/backend before the clean-boot build (same build-input floor
        # as the #113 asset staging above).
        try:
            from .backend_scaffold import repair_custom_routes_param_types_vs_projection
            _be = compose_file.parent.parent / "app" / "backend"
            if _be.is_dir():
                repair_custom_routes_param_types_vs_projection(_be)
        except Exception:
            pass
        # FIX #450 (run-37 M4): the deterministic validation build goes through THIS
        # module's own _compose, so #450's Dockerfile-restore (wired into
        # tools/docker_tools._run_compose) never fired here — and this is the exact
        # path that recorded run-37's docker_up=fail ('no Dockerfile') → 0.069 blank.
        # A lane merge can transiently drop the framework Dockerfile; restore it from
        # git before the clean-boot build. Same build-input floor as #113/#125 above.
        try:
            from .frontend_scaffold import ensure_build_infra_staged_for_build
            ensure_build_infra_staged_for_build(compose_file)
        except Exception:
            pass
        # #99 EFFICIENCY (r97-r99 delivery-tail sink): localize the seed's EXTERNAL image
        # URLs to /assets/ RIGHT HERE — this clean boot is the deterministic AUTHORITY for
        # the stored re-seed fingerprint (the loader hashes the seed CONTENT and re-seeds
        # when it changes). The frontend-api heal ALSO localizes the seed, but LATER and
        # DECOUPLED from this boot, so api_smoke seeded the EXTERNAL-URL seed, that later
        # rewrite flipped the fingerprint, and the visual gate's reuse boot (`up -d`, same
        # postgres volume, no `down -v`) then RE-SEEDED mid-capture → every data-driven page
        # rendered transiently data-starved (~0.05) → DELIVERY DEFERRED churn + ~8-min
        # recovery, EVERY run. Localizing here — after ensure_assets_staged_for_build above
        # stages the /assets targets, so matches resolve and NEVER 404 — makes THIS boot
        # store the localized fingerprint, so the visual gate's reuse boot finds it unchanged
        # and never re-seeds. Idempotent (rewrites only http(s):// image URLs; a no-op →
        # byte-identical seed when there is nothing to localize); never raises. Same
        # build-input floor as the #113/#125/#450 repairs above.
        try:
            from .frontend_scaffold import localize_seed_external_images
            _be_seed = compose_file.parent.parent / "app" / "backend"
            _fe_dir = compose_file.parent.parent / "app" / "frontend"
            if _be_seed.is_dir():
                localize_seed_external_images(_be_seed, _fe_dir)
        except Exception:
            pass
        _compose(compose_file, "down", "-v", "--remove-orphans", cwd=cwd, timeout=120)
        # #566l: build SEPARATELY from up so a hung/flaky network install fails fast + retries
        # (classic layer cache = offline-capable for completed layers), and SKIP the rebuild
        # entirely when the app source is unchanged since the last SUCCESSFUL build. Root cause of
        # the r122 run_validation 20-min hang: `up --build` re-ran a network package install every
        # validation and a flaky-registry window burned the full 1200s docker-up cap.
        _fp = _app_source_fingerprint(compose_file)
        _need_build = ((not _SKIP_UNCHANGED_BUILD) or _fp is None
                       or _fp != _read_build_fingerprint(cwd))
        if _need_build:
            _bok, _bdetail = _build_with_retry(compose_file, cwd)
            if not _bok:
                _add("docker_up", False, _bdetail)
                return _finalize(checks, backend_port, endpoint_results)
            _write_build_fingerprint(cwd, _fp)
        up, _ = _compose_capture(compose_file, "up", "-d", "--remove-orphans",
                                 cwd=cwd, timeout=_UP_ONLY_TIMEOUT)
        if up.returncode != 0 and not _need_build:
            # #566l safety net: we SKIPPED the build (source unchanged) but `up` failed — the
            # cached image may be missing/stale/pruned. Never ship stale: rebuild + retry up once
            # before giving up (so skip-when-unchanged can only ever save time, never mis-validate).
            _bok, _bdetail = _build_with_retry(compose_file, cwd)
            if _bok:
                _write_build_fingerprint(cwd, _fp)
                up, _ = _compose_capture(compose_file, "up", "-d", "--remove-orphans",
                                         cwd=cwd, timeout=_UP_ONLY_TIMEOUT)
        if up.returncode != 0:
            # S1 (PROPOSAL #3): `docker compose up`'s OWN stderr is often just a
            # benign warning (e.g. "attribute `version` is obsolete") while the REAL
            # failure is a container that crashed during init — e.g. postgres exit 3
            # on a malformed DDL (youtube run #16: the truncated up-stderr surfaced
            # ONLY the version warning and HID the exit-3 crash for many rounds).
            # Also capture the per-container logs (mirrors backend_health at the
            # /health-timeout branch) so the failure detail shows the ROOT, not the
            # warning. Service-agnostic: `logs` with no service = every container.
            # CLASS A (#36): on a BUILD failure (e.g. apt exit 100) the root cause is in
            # the build transcript, NOT the brief "failed to solve … exit code N" summary,
            # and `compose logs` is empty (no container booted). A 400-char tail of ONE
            # stream hid the apt error in run #34 → agents re-ran validation blindly ("the
            # output got truncated … I need the full stack trace"). Capture a generous
            # tail of BOTH streams so the lane sees the actual error.
            _up_detail = (((up.stdout or "") + "\n" + (up.stderr or "")).strip())[-3000:]
            try:
                _clogs = _compose(compose_file, "logs", "--tail", "40", cwd=cwd, timeout=30)
                _ctail = (_clogs.stdout or _clogs.stderr or "")[-1500:]
            except Exception:
                _ctail = ""
            _detail = _up_detail + (
                "\n--- container logs (tail) ---\n" + _ctail if _ctail else "")
            # #1202mh: this detail is what the lanes read AND what the
            # remediation dispatcher classifies. #1202de already stops the
            # framework dispatching on a host fault; without this the lanes
            # still see undifferentiated stderr and open the task themselves.
            try:
                from .visual_fidelity import operator_only_notice_1202mh
                _hf = operator_only_notice_1202mh(_detail)
            except Exception:
                _hf = ""
            if _hf:
                _detail = _hf + "\n\n--- raw ---\n" + _detail
            _add("docker_up", False, _detail)
            return _finalize(checks, backend_port, endpoint_results)
        _add("docker_up", True)

        backend_port = _backend_host_port(compose_file, cwd)
        if not backend_port:
            _add("backend_port", False, "could not resolve backend published port")
            return _finalize(checks, backend_port, endpoint_results)

        base = f"http://localhost:{backend_port}"

        # 2. /health (backend actually serves — catches boot crashes).
        healthy = False
        deadline = time.monotonic() + health_timeout
        while time.monotonic() < deadline:
            h = _http("GET", f"{base}/health", timeout=5)
            if h["status"] == 200:
                healthy = True
                break
            time.sleep(3)
        if not healthy:
            logs = _compose(compose_file, "logs", "--tail", "30", "backend", cwd=cwd, timeout=30)
            _add("backend_health", False, "/health not 200 within timeout. logs:\n" + (logs.stdout or logs.stderr)[-1200:])
            return _finalize(checks, backend_port, endpoint_results)
        _add("backend_health", True)
        # #1202qe: the freshly seeded state, before any check writes to it; restored in
        # _finalize so the next capture sees the seed, not this validation's test accounts.
        try:
            from .verification_isolation import isolated_verification_1202qe
            _scope = isolated_verification_1202qe(compose_file.parent.parent, "validation", _LOG)
            _scope.__enter__()
            _VALIDATION_SCOPE_1202QE.append(_scope)
        except Exception as _e1202qe:
            from .message_format import warn_once_1201
            warn_once_1201("validation_db_snapshot_1202qe", "#1202qe validation data snapshot",
                           _e1202qe)

        # #1202dj: THE one moment the database is provably up. `live_row_counts_1039` works
        # — proven against a live stack — but it is called from gate evaluation, and the
        # stack is cycled (`down -v`, `up`) around each validation, so by then the container
        # is usually gone: 2728 of 2728 corpus attempts reported "DID NOT RUN". The audit
        # then falls back to the `status == "defined"` filter, which examines 0 tables in 145
        # of 147 runs, and `is_clean` cannot tell that from "found nothing wrong" (#1023d).
        # Record what is true here so the seed gate finally has a number to read.
        try:
            from .seed_audit import live_row_counts_1039, record_live_counts_1202dj
            _counts1202dj = live_row_counts_1039(project_dir)
            if _counts1202dj:
                record_live_counts_1202dj(project_dir, _counts1202dj)
                _LOG.info("#1202dj live seed row counts captured at backend_health: %s",
                          dict(list(_counts1202dj.items())[:12]))
        except Exception as _e1202dj:
            # #1201: a silent `pass` here would leave the seed gate blind for the whole run
            # with nothing saying so — which is the exact failure #1202dj exists to end.
            from .message_format import warn_once_1201
            warn_once_1201("live_row_counts_1039_at_backend_health",
                           "#1202dj live seed row-count capture", _e1202dj)

        # 3. Register via the embedded AS → token. FIX #33: send a COMPLETE
        #    common registration payload. username-based auth is the dominant web
        #    convention (social apps, etc.), and Pydantic ignores extra fields
        #    while accepting the ones the app's model requires — so a single
        #    superset payload satisfies both email-only and username-requiring
        #    register models. The old {email,password,name}-only body made the
        #    gate 422 ("missing username") on any app whose register needs a
        #    username, blocking delivery of an otherwise-working app.
        def _tok(txt: str) -> Optional[str]:
            try:
                d = json.loads(txt)
            except Exception:
                return None
            if not isinstance(d, dict):
                return None
            return d.get("access_token") or d.get("token") or d.get("accessToken")

        _cred = {
            "username": "smoke_user", "email": "smoke@virtueai.com",
            "password": "smoke-pw-12345", "name": "Smoke", "full_name": "Smoke User",
        }
        reg = _http("POST", f"{base}/auth/register", body=_cred)
        token = _tok(reg["body_text"]) if reg["status"] in (200, 201) else None
        if not token:
            # register may not mint a token, or the user already exists → login.
            # Send username + email both so username- or email-login both resolve.
            login = _http("POST", f"{base}/auth/login",
                          body={"username": "smoke_user", "email": "smoke@virtueai.com",
                                "password": "smoke-pw-12345"})
            token = _tok(login["body_text"])
        _add("auth_register_login", bool(token),
             "" if token else f"register={reg['status']} + login; no access_token ({reg['body_text'][:200]})")
        if not token:
            return _finalize(checks, backend_port, endpoint_results)

        # 4. Every business endpoint reachable (status < 500 = no crash) AND —
        #    GATE-C1 — actually implemented when its registration claims so:
        #    a 404/405 from a status=implemented endpoint fails the smoke (see
        #    _unimplemented_route for the round47-calibrated exemptions).
        #    Collect a per-endpoint result so the caller can emit one
        #    contract-test record per endpoint (the delivery-gate evidence) —
        #    ``reachable`` stays the transport fact (<500); ``passed`` is the
        #    verdict the probe/contract-test records consume.
        unreachable: List[str] = []
        unimplemented: List[str] = []
        shape_violations: List[str] = []
        for ep in business_endpoints or []:
            method = str(ep.get("method") or "GET").upper()
            path = str(ep.get("path") or "")
            if not path:
                continue
            url = base + _path_with_params(path)
            body = {} if method in ("POST", "PUT", "PATCH") else None
            res = _http(method, url, token=token, body=body)
            reachable = res["status"] is not None and res["status"] < 500
            _ur = _unimplemented_route(method, path, ep.get("status"), res["status"],
                                       res.get("body_text"))
            endpoint_results.append({
                "id": ep.get("id"),
                "method": method,
                "path": path,
                "status_code": res["status"],
                "reachable": reachable,
                "passed": reachable and not _ur,
                "error": res["error"],
                "trace": f"{method} {url} -> {res['status'] or res['error']}",
            })
            if not reachable:
                # #1003: a 405 says WHY in its own headers. `Allow:` names the methods the
                # running app bound for this path — the fact that makes the difference
                # between "reproduce this" and "look at the route declaration". r162 spent 17
                # tasks on `POST /api/continue-watching → 405` because this line emitted the
                # number alone. Appended only for 405 and capped hard, since
                # compose_unreachable_detail budgets the first 300 chars for the traceback.
                _extra1003 = ""
                if res["status"] == 405:
                    for _k, _v in (res.get("headers") or {}).items():
                        if str(_k).lower() == "allow":
                            _extra1003 = f" (app accepts: {str(_v)[:48]})"
                            break
                unreachable.append(
                    f"{method} {path} → {res['status'] or res['error']}{_extra1003}")
            if _ur:
                unimplemented.append(_ur)
            # gate C — behavioral COMPLETENESS: a 2xx response MUST match the contract
            # shape for its path-type (catches the real instagram bug where GET
            # /api/users/me returned {"items":[all users]} — reachable but semantically
            # wrong). Conservative: only a clear single↔collection mismatch is flagged.
            _sv = _shape_violation(method, path, res["status"], res["body_text"],
                                   ep_status=ep.get("status"))
            if _sv:
                shape_violations.append(_sv)
        # FIX #157: on a 5xx (backend crash-in-handler, not a mere 404), pull the
        # backend log tail and attach the salient traceback line — the remediation
        # task then carries the ROOT CAUSE (file:line + exception), not just "→ 500"
        # (gmrun5: the bare 500 sent the lane down a wrong guess → 50min wedge).
        _salient = ""
        if unreachable and any(
                (r.get("status_code") or 0) >= 500 for r in endpoint_results):
            _salient = extract_salient_traceback(_backend_logs_tail(compose_file, cwd))
        _add("business_endpoints_reachable", not unreachable,
             compose_unreachable_detail(unreachable, _salient) if unreachable
             else f"{len(business_endpoints or [])} endpoint(s) reachable")
        _add("business_endpoints_implemented", not unimplemented,
             # #1034: was a [:800] cut on the JOINED string — this detail is what a lane reads
             # to know WHICH endpoints to implement, so a silent cut costs a repair round.
             join_capped(unimplemented, len(unimplemented), cap=12) if unimplemented
             else f"{len(business_endpoints or [])} registered-implemented endpoint(s) serve their route")
        _add("business_endpoints_correct_shape", not shape_violations,
             join_capped(shape_violations, len(shape_violations), cap=12)
             if shape_violations
             else f"{len(business_endpoints or [])} endpoint(s) match the item/items contract")

        # gate C (persistence): a parameterless POST collection endpoint must REALLY
        # persist — POST it, then GET the same path and require the new id to appear.
        # "201 but nothing stored" (in-memory handler, dropped txn) passed every
        # earlier gate. Conservative: only asserted for the first POST /api/<col>
        # whose POST returned 2xx with an {item:{id}} and whose GET returns a list.
        # §2 gate-hardening: the FIRST verifiable POST still drives the BLOCKING gate exactly
        # as before (no new hard blocks). Additionally, probe the OTHER parameterless POSTs and
        # surface non-blocking WARNINGS — a 2xx create whose collection GET is EMPTY or doesn't
        # contain the new id (the "201 but nothing stored" / 200-but-empty class), or a skip
        # that used to pass silently — so they're visible in the report instead of invisible.
        post_eps = [e for e in (business_endpoints or [])
                    if str(e.get("method", "")).upper() == "POST" and "{" not in str(e.get("path", ""))]
        persist_detail = "no parameterless POST endpoint to probe"
        persist_ok = True
        persist_warnings: list = []
        _first_scored = False
        for post_ep in post_eps[:8]:  # cap to bound probe time
            ppath = str(post_ep["path"])
            pres = _http("POST", base + ppath, token=token, body=_probe_body(post_ep))
            if not (pres["status"] and 200 <= pres["status"] < 300):
                persist_warnings.append(f"POST {ppath} → {pres['status'] or pres['error']} — write not verified")
                continue
            try:
                new_id = (json.loads(pres["body_text"]) or {}).get("item", {}).get("id")
            except Exception:
                new_id = None
            back = _http("GET", base + ppath, token=token)
            try:
                payload = json.loads(back["body_text"] or "{}")
                rows = payload.get("items") if isinstance(payload, dict) else None
            except Exception:
                rows = None
            if not isinstance(rows, list):
                persist_warnings.append(f"POST {ppath} ok but GET readback is not an items[] list — persistence not verifiable")
                continue
            if new_id is not None:
                contains = _id_in_rows(new_id, rows)   # FIX #122: type-tolerant
                if not _first_scored:
                    # FIRST verifiable POST = the blocking gate (byte-identical to prior behavior).
                    persist_ok = contains
                    persist_detail = (
                        f"POST {ppath} → id={new_id}; GET readback "
                        + ("contains it" if contains else
                           f"does NOT contain it ({len(rows)} row(s)) — write not persisted"))
                    _first_scored = True
                elif not contains:
                    persist_warnings.append(
                        f"POST {ppath} → id={new_id} NOT in readback ({len(rows)} row(s)) — possible non-persist")
            else:
                if len(rows) == 0:
                    persist_warnings.append(
                        f"POST {ppath} returned 2xx but the collection GET is EMPTY — possible non-persisting write")
                elif not _first_scored:
                    persist_detail = f"POST {ppath} 2xx ({len(rows)} row(s)); no item.id to match — skipped"
        if persist_warnings:
            persist_detail += " | warnings: " + "; ".join(persist_warnings)
        _add("business_writes_persist", persist_ok, persist_detail)

        # 5. Auth enforced: a business endpoint without a token → 401.
        #
        # #1202ih: IT MUST BE AN ENDPOINT THE CONTRACT SAYS NEEDS AUTH.
        #
        # This took the FIRST GET in the list and demanded 401 from it, whatever the
        # contract said. On tiktok the first GET is `/api/videos`, which the backend lane
        # declared PUBLIC (`schema.auth_required=false`) and which the projector therefore
        # built with no guard — so the framework demanded a denial from a route it had
        # itself constructed to answer 200. No lane can satisfy both halves.
        #
        # r107 resume2, live: this wedged the run for four post-cap validation cycles and
        # then killed it. The debugger lane — awake since #1202dr — diagnosed it exactly:
        # "run_validation auth_enforced_401 uses stale metadata for public GET
        # /api/videos ... schema.auth_required=false but metadata.auth_required=true ...
        # Registered public_video_metadata_drift_guard chain and diagnostic contract test
        # passed, but run_validation still fails auth_enforced_401." The lane did
        # everything right and could not clear a check that reads a copy it cannot reach.
        #
        # Pick through `_stated_auth_1202hi`, the projector's own single reader, so the
        # endpoint probed for a denial is the same one the handler was built to deny.
        # When NO GET requires auth, there is nothing here to prove — an app whose reads
        # are all public is a legitimate contract (the logged-out surface #320 exists to
        # keep open), and asserting a denial anyway invents a failure.
        _gets_1202ih = [e for e in (business_endpoints or [])
                        if str(e.get("method", "GET")).upper() == "GET"]
        get_ep = pick_auth_probe_endpoint_1202ih(_gets_1202ih)
        if get_ep:
            url = base + _path_with_params(str(get_ep.get("path")))
            noauth = _http("GET", url)
            _add("auth_enforced_401", noauth["status"] == 401,
                 "" if noauth["status"] == 401 else f"GET {get_ep.get('path')} no-token → {noauth['status']} (expected 401)")
        elif _gets_1202ih:
            _LOG.info("#1202ih auth_enforced_401 skipped: none of the %d GET endpoint(s) "
                      "states auth_required=true, so there is no declared denial to "
                      "verify. Probing a contract-public read for a 401 is the wedge this "
                      "replaced.", len(_gets_1202ih))

        # 5.5 VERIFIER CHAIN TEST (user decision 2026-06-11): real API-chain
        # coverage belongs to the VERIFIER's validation, not post-release
        # reporting — register → login → authed me → create → read-back →
        # cross-user interactions, driven by the registered contract. Any
        # step that is BROKEN (5xx / auth failure / wrong data) fails the
        # gate; "missing" (404/405 — later-milestone endpoints) stays soft.
        try:
            from .chain_executor import run_chains
            _chain = run_chains(base, project_dir, list(business_endpoints or []))
            # Surface the PER-CHAIN results so the run_validation tool can sync each
            # chain's verdict back through the LIVE registryhub (record_chain_result)
            # to the MAIN registry the delivery gate reads. run_chains' own status
            # write-back goes to project_dir's hub file — which, when validation runs
            # inside a lane WORKTREE, is NOT the registry the gate audits (run v20:
            # chains pass live but the gate sees stale 'registered' → deadlock).
            chain_results = _chain.get("chains") or []
            if _chain["broken"]:
                # #300: on a chain 5xx, attach the backend traceback (file:line
                # root cause) — else the lane fixes blind (r81 M2 STUCK 95min on
                # POST /replies → 500 shown only as 'Internal Server Error').
                _chain_salient = ""
                if _chain_broken_has_5xx(_chain["broken"]):
                    try:
                        _chain_salient = extract_salient_traceback(
                            _backend_logs_tail(compose_file, cwd))
                    except Exception:
                        _chain_salient = ""
                _add("business_chain", False,
                     _business_chain_detail(_chain["broken"], _chain_salient))
            elif _chain.get("environment_1202od"):
                # #1202od: the steps never reached the app. Not a pass (nothing was verified)
                # and not the lanes' failure — say which it is, so the retry is the remedy.
                _env1202od = _chain["environment_1202od"]
                _add("business_chain", False,
                     "NOT VERIFIED — the app was unreachable while the chains ran, so these "
                     "steps got no answer at all (%d step(s), e.g. %s). This is the stack, "
                     "not the code: no lane edit can change it. Re-run the validation once "
                     "the stack is up." % (len(_env1202od), str(_env1202od[0])[:160]))
            else:
                _add("business_chain", True,
                     f"{_chain['total_steps']} step(s) across "
                     f"{len(_chain['chains'])} verifier-authored chain(s) pass")
        except Exception as _chain_exc:
            _add("business_chain", False, f"chain runner crashed: {_chain_exc}")

        # 5.6 DEAD-CONTROL RULE (user decision 2026-06-11): page-type-agnostic
        # — a page that renders interactive markup (<form>, submit buttons)
        # must BIND it somewhere in the file (onSubmit/onClick/fetch/api use).
        # The 1.4.0 signup page was a pixel-perfect <form> with zero handlers;
        # every HTTP probe passed while no human could use it. Conservative
        # rules to avoid false positives: only flag files that have a <form>
        # or a submit-typed button AND contain NO handler/API token at all.
        try:
            _src_dir = Path(project_dir) / "app" / "frontend" / "src"
            _dead: list = []
            # F6 (2026-07-21): use the SAME handler-token set as the delivery-time audit
            # (frontend_audit._HANDLER_TOKENS) so a page wired via the default `api` client
            # (`api.get(...)` / `await api`) is not flagged dead here while frontend_audit —
            # which DOES recognize those tokens — clears it. The two gates were giving opposite
            # verdicts on the exact React shape the prompts tell pages to use.
            try:
                from .frontend_audit import _HANDLER_TOKENS as _HANDLER_TOK
            except Exception:
                _HANDLER_TOK = ("onSubmit", "onClick", "fetch(", "apiGet", "apiPost",
                                "apiPut", "apiDelete", "axios", "api.", "await api")
            if _src_dir.is_dir():
                for _pf in sorted(_src_dir.rglob("*.jsx")):
                    try:
                        _txt = _pf.read_text(encoding="utf-8", errors="ignore")
                    except Exception:
                        continue
                    _interactive = ("<form" in _txt) or ('type="submit"' in _txt)
                    _bound = any(tok in _txt for tok in _HANDLER_TOK)
                    if _interactive and not _bound:
                        _dead.append(_pf.name)
            _add("frontend_dead_controls", not _dead,
                 ("interactive markup with NO bound handler/API call — a user "
                  "clicking these gets nothing: " + ", ".join(_dead))[:800]
                 if _dead else "all interactive pages bind their controls")
        except Exception as _dc_exc:
            _add("frontend_dead_controls", True, f"scan skipped: {_dc_exc}")

        # 6. Frontend HTTP reachable: the UI container must actually SERVE. docker_up
        #    passes even when the frontend container crashes right after start (the
        #    nginx env-var crash shipped exactly that way), and frontend_navigable is
        #    a static file check — this closes the runtime gap.
        fe_port = _service_host_port(compose_file, cwd, "frontend")
        if fe_port:
            fe = _http("GET", f"http://localhost:{fe_port}/", timeout=20)
            ok = fe["status"] is not None and 200 <= fe["status"] < 400
            _add("frontend_reachable", ok,
                 f"GET :{fe_port}/ → {fe['status'] or fe['error']}"
                 + ("" if ok else " — the frontend container is not serving (crashed after start?)"))
        else:
            _add("frontend_reachable", False,
                 "could not resolve the frontend service's published port "
                 "(container not running?)")

        return _finalize(checks, backend_port, endpoint_results, chain_results)
    except Exception as exc:
        _add("runner_error", False, f"{type(exc).__name__}: {exc}")
        return _finalize(checks, backend_port, endpoint_results, chain_results)
    finally:
        if teardown:
            try:
                from .compose_mutex import wait_for_stack_leases_1202nx   # #1202nx
                # capped below the 600s other validations wait for the lock this one holds
                wait_for_stack_leases_1202nx(project_dir, "api_smoke validation (teardown)",
                                             timeout_s=min(300.0, float(os.environ.get(
                                                 "ENVGEN_STACK_LEASE_WAIT_SEC") or 300)),
                                             logger=_LOG)
                _compose(compose_file, "down", "-v", "--remove-orphans", cwd=cwd, timeout=120)
            except Exception:
                pass
        # FIX #36: release the validation lock so the next validator can boot.
        if _lock_fh is not None:
            try:
                _fcntl.flock(_lock_fh.fileno(), _fcntl.LOCK_UN)
            except Exception:
                pass
            try:
                _lock_fh.close()
            except Exception:
                pass


_VALIDATION_SCOPE_1202QE: List[Any] = []


def _finalize(checks: List[Dict[str, Any]], backend_port: Optional[int],
              endpoint_results: Optional[List[Dict[str, Any]]] = None,
              chain_results: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    while _VALIDATION_SCOPE_1202QE:          # #1202qe: every return path after the snapshot
        try:
            _VALIDATION_SCOPE_1202QE.pop().__exit__(None, None, None)
        except Exception as _e1202qe:
            from .message_format import warn_once_1201
            warn_once_1201("validation_db_restore_1202qe", "#1202qe validation data restore",
                           _e1202qe)
    passed = bool(checks) and all(c["status"] == "pass" for c in checks)
    fails = [c["name"] for c in checks if c["status"] != "pass"]
    summary = "all api_smoke checks passed" if passed else f"FAILED: {', '.join(fails)}"
    return {"passed": passed, "summary": summary, "checks": checks,
            "backend_port": backend_port, "endpoints": endpoint_results or [],
            "chains": chain_results or []}


__all__ = ["run_smoke_validation"]
