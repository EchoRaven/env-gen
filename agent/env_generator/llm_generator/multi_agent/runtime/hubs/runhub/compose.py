"""RunHub docker compose lifecycle wrapper + HTTP healthcheck poller.

All subprocess/HTTP calls are gated behind injectable callables so unit tests
can stub them. Production callers pass `runner=subprocess.run` and
`getter=httpx.get` (or `urllib.request.urlopen`).
"""

from __future__ import annotations

import os
import subprocess
import time
from dataclasses import dataclass
from typing import Any, Callable, List, Optional


def _runtime_bin_961() -> str:
    """#961 — resolve the container CLI, never assume the literal ``docker``.

    Imported lazily and guarded: this module is deliberately dependency-light so unit tests can
    stub every subprocess, and a hard import would make an unrelated import error break the
    lifecycle. Falling back to ``"docker"`` keeps the pre-#961 behaviour exactly.
    """
    try:
        from ...container_runtime import runtime_bin
    except Exception:
        return "docker"
    try:
        return runtime_bin()
    except Exception:
        return "docker"


@dataclass
class ComposeResult:
    returncode: int
    stdout: str = ""
    stderr: str = ""


@dataclass
class HealthcheckResult:
    healthy: bool
    status_code: Optional[int] = None
    attempts: int = 0
    elapsed_s: float = 0.0
    last_error: str = ""


def _default_runner(args: List[str], cwd: Optional[str] = None, timeout: float = 120.0) -> ComposeResult:
    # R2 round-11 Fix A: force classic builder. RunHub.start_run uses this
    # runner to bring up generated apps for the deliverability gate;
    # `up -d --remove-orphans` triggers an implicit build when images are
    # missing, which on this host (Docker 20.10.8 + kernel 5.11) hits the
    # spike's BuildKit fork/exec failures. Pinning classic via env var is
    # content-neutral — does not change Dockerfile or compose semantics.
    cp = subprocess.run(
        args, cwd=cwd, capture_output=True, text=True, timeout=timeout,
        env={**os.environ, "DOCKER_BUILDKIT": "0", "COMPOSE_DOCKER_CLI_BUILD": "0"},
    )
    return ComposeResult(returncode=cp.returncode, stdout=cp.stdout, stderr=cp.stderr)


class ComposeLifecycle:
    def __init__(self, cwd: str, runner: Optional[Callable] = None,
                 compose_file: Optional[str] = None) -> None:
        self.cwd = cwd
        self._runner = runner or _default_runner
        self.compose_file = compose_file

    def _base_args(self) -> List[str]:
        # #961: the runtime, not the literal. This host has no `docker` binary — the whole
        # lifecycle works only because tools/podman_shim is hand-added to PATH, which nothing
        # guarantees (#936). runtime_bin() prefers docker when it exists, so a docker host is
        # unchanged; a podman host now works WITHOUT the shim.
        args = [_runtime_bin_961(), "compose"]
        if self.compose_file:
            args += ["-f", self.compose_file]
        return args

    def up(self, timeout: float = 180.0) -> ComposeResult:
        result = self._runner(self._base_args() + ["up", "-d", "--remove-orphans"],
                              cwd=self.cwd, timeout=timeout)
        return _coerce(result)

    def down(self, timeout: float = 60.0) -> ComposeResult:
        try:
            result = self._runner(self._base_args() + ["down", "--remove-orphans"],
                                  cwd=self.cwd, timeout=timeout)
            return _coerce(result)
        except Exception as e:  # never raise from down() — finally must always succeed
            return ComposeResult(returncode=-1, stderr=f"down failed: {e}")


def _coerce(r: Any) -> ComposeResult:
    if isinstance(r, ComposeResult):
        return r
    # subprocess.CompletedProcess shape
    return ComposeResult(returncode=int(getattr(r, "returncode", -1)),
                         stdout=str(getattr(r, "stdout", "")),
                         stderr=str(getattr(r, "stderr", "")))


class HealthcheckProbe:
    def __init__(self, url: str, poll_interval_s: float = 2.0,
                 timeout_s: float = 60.0, getter: Optional[Callable] = None,
                 request_timeout_s: float = 5.0,
                 clock: Callable[[], float] = time.time,
                 sleep: Callable[[float], None] = time.sleep) -> None:
        self.url = url
        self.poll_interval_s = poll_interval_s
        self.timeout_s = timeout_s
        self._getter = getter
        self._request_timeout_s = request_timeout_s
        self._clock = clock
        self._sleep = sleep

    def _http_get(self, url: str, timeout: float):
        if self._getter is not None:
            return self._getter(url, timeout)
        try:
            import httpx
        except ImportError:
            from urllib.request import urlopen
            return _UrllibResponse(urlopen(url, timeout=timeout))
        return httpx.get(url, timeout=timeout)

    def wait(self) -> HealthcheckResult:
        start = self._clock()
        attempts = 0
        last_status: Optional[int] = None
        last_error = ""
        while True:
            attempts += 1
            try:
                resp = self._http_get(self.url, self._request_timeout_s)
                code = getattr(resp, "status_code", None)
                last_status = code
                if isinstance(code, int) and 200 <= code < 400:
                    return HealthcheckResult(
                        healthy=True, status_code=code, attempts=attempts,
                        elapsed_s=self._clock() - start)
            except Exception as e:
                last_error = str(e)
            elapsed = self._clock() - start
            if elapsed >= self.timeout_s:
                return HealthcheckResult(
                    healthy=False, status_code=last_status, attempts=attempts,
                    elapsed_s=elapsed, last_error=last_error)
            self._sleep(self.poll_interval_s)


class _UrllibResponse:
    # #1000: keep the HEADERS, not just the number.
    #
    # A 405 is REQUIRED by HTTP to carry `Allow:` naming the methods the server does accept —
    # the single fact that answers "which methods did this app actually bind for this path".
    # r162 died on `POST /api/continue-watching returns 405`, static analysis of the worktree
    # came back clean on every line, and the header that would have settled it was discarded
    # here, in four lines, at the moment of capture.
    def __init__(self, raw):
        self.status_code = getattr(raw, "status", getattr(raw, "code", 0))
        try:
            self.headers = dict(getattr(raw, "headers", {}) or {})
        except Exception:
            self.headers = {}


__all__ = ["ComposeLifecycle", "ComposeResult", "HealthcheckProbe", "HealthcheckResult"]
