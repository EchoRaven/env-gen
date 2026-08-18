"""#936 — which container CLI is actually on this host, and how to find a service's container.

Ten argv lists across five modules begin with the literal ``"docker"``. There is no ``docker``
binary on a podman-backed gen host — verified by execution, not inference:

    subprocess.run(["docker", "info"])  ->  FileNotFoundError: [Errno 2] ... 'docker'

Every one of those calls sits inside a ``try``, so each fails silently and the thing it implements
simply never happens. The clearest casualty is #738's stale-bundle probe, written because r148
released v1.0.0 with the SPA crashing on every route: its state file ``served_build.json`` exists
in **0 of the corpus's runs**, because the guard that writes it (``if _bundle738 and _fe738``)
never sees a bundle listing.

Two functions, deliberately: the binary, and the one lookup that differs between the runtimes.
"""
from __future__ import annotations

import shutil
import subprocess
from typing import Any


def runtime_bin() -> str:
    """``docker`` when the binary exists, else ``podman``.

    Resolved per call rather than cached: this is a PATH walk, called a handful of times per round,
    and a cached answer would outlive a host change inside a long-lived process. Docker is
    preferred so a docker host behaves exactly as before.
    """
    for _b in ("docker", "podman"):
        if shutil.which(_b):
            return _b
    return "docker"


def container_id(compose_file: Any, service: str, *, timeout: int = 20) -> str:
    """The running container id for a compose service, on either runtime. ``""`` if unknown.

    ``compose ps -q <service>`` is Compose-v2 only. podman-compose's ``ps`` has **no service
    positional** — argparse answers "unrecognized arguments: <service>" with exit 2 and EMPTY
    stdout, which is not an exception and so cannot be caught. ``podman compose`` merely delegates
    to podman-compose and inherits the gap.

    ``validation_runner._service_host_port`` hit this first and wrote the remedy down: fall back to
    a container-NAME filter, which podman does support. This is that remedy, extracted so the next
    caller does not have to rediscover it.
    """
    rt = runtime_bin()
    try:
        out = subprocess.run([rt, "compose", "-f", str(compose_file), "ps", "-q", service],
                             capture_output=True, text=True, timeout=timeout).stdout.strip()
        if out:
            return out.splitlines()[0].strip()
    except Exception:
        pass
    try:
        out = subprocess.run([rt, "ps", "-q", "--filter", f"name={service}"],
                             capture_output=True, text=True, timeout=timeout).stdout.strip()
        return out.splitlines()[0].strip() if out else ""
    except Exception:
        return ""
