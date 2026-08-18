"""#936 — which container CLI is on this host, and the one call shape no shim can rescue.

Ten argv lists across five modules begin with the literal ``"docker"``, and this host runs podman
5.8.3 with no docker package. It works anyway, via a hand-installed PATH shim the repo ships and
`tools/podman_setup.sh` tells you to add yourself:

    tools/podman_shim/docker   `docker compose …` -> `podman-compose …`;  `docker …` -> `podman …`

★ Nothing verifies that shim is present. Measured both ways:

    without it   subprocess.run(["docker","info"])            -> FileNotFoundError
    with it      docker ps --format '{{.Names}}'              -> rc=0, all three containers
    with it      docker compose -f … ps -q frontend           -> rc=2, EMPTY stdout

The last line is the one that matters, and it is why this module exists. podman-compose's ``ps``
has **no service positional** — argparse answers "unrecognized arguments: frontend" and exits 2.
That is not an exception, so it cannot be caught; the caller just gets ``""``. The shim rescues
every other shape and cannot rescue this one.

Both stale-build probes depend on exactly that call. #738 was written because r148 released
v1.0.0 with the SPA crashing on every route, and its state file ``served_build.json`` exists in
**0 of the corpus's runs**: the guard that writes it (``if _bundle738 and _fe738``) never sees a
bundle listing, because the container id was always empty.

Two functions, deliberately: the binary, and the lookup the shim cannot fix.
"""
from __future__ import annotations

import logging
import shutil
import subprocess
from typing import Any, Dict

#: one-shot flags — a line that fires every round stops being read (#845)
_SAID: Dict[str, bool] = {}


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
        cid = out.splitlines()[0].strip() if out else ""
    except Exception:
        return ""
    if cid and not _SAID.get("fallback"):
        # ★ Say it ONCE. The compose lookup returning "" while the name filter finds the container
        # is the signature of a podman-compose CLI, and it is the state in which #715 and #738
        # produced nothing for the entire history of this corpus. Silence here is what made that
        # take a full session to notice; a line makes the next reader's first question cheap.
        _SAID["fallback"] = True
        logging.getLogger(__name__).info(
            "#936 `%s compose ps -q %s` returned nothing but the container IS running (%s) — this "
            "is podman-compose, whose `ps` has no service positional. Using the name filter. Every "
            "probe keyed on that lookup (#715/#738 served-build staleness) got an empty id before "
            "this fallback existed.", rt, service, cid[:12])
    return cid
