"""#936 — which container CLI is on this host, and the one call shape no shim can rescue.

Seven argv lists across FOUR modules began with the literal ``"docker"`` (measured by AST on
2026-08-18; an earlier count of "ten across five" in this docstring was mine and was wrong — it
included ``memory_bank.py:997``, a KEYWORD list ``["docker","compose","port","url",…]`` that is
not an argv at all, and the same false positive #936b's locator produced). #961 converted all
seven. This host runs podman 5.8.3 with no docker package, and it worked anyway only via a
hand-installed PATH shim the repo ships and `tools/podman_setup.sh` tells you to add yourself:

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



def _exited_container_reason_1202av(rt: str, service: str, want: str, timeout: int) -> str:
    """Why is this run's `service` container gone? Ask the EXITED ones. (#1202av)

    `docker compose up -d` without `--wait` returns rc=0 as soon as the start is issued, so
    a container that starts and immediately dies still reports success. r32 shows both halves
    and never joins them: 66 `up -d --remove-orphans -> rc=0` between 20:10 and 00:15, and
    across the very same window 179 errors saying this run has no running container. The log
    holds no exit, no restart, no unhealthy line anywhere — because nothing ever looked at a
    stopped container. Four and a half hours of "NOT RUNNING" with the reason one command away.

    Best-effort and read-only: any failure returns "" and the caller says exactly what it said
    before. Never raises.
    """
    try:
        # Ask the daemon for OUR container by label rather than paging through every
        # container that happens to share the service name. The first version capped the
        # name scan at 12 and real data killed it immediately: this machine has 20
        # containers matching `name=backend` and the one being asked about was 18th, so
        # the diagnostic answered "" precisely in the many-runs case it was written for.
        ids = []
        try:
            lf = subprocess.run(
                [rt, "ps", "-a",
                 "--filter", "label=com.docker.compose.project.config_files=%s" % want,
                 "--filter", "name=%s" % service, "--format", "{{.ID}}"],
                capture_output=True, text=True, timeout=timeout)
            ids = [x for x in lf.stdout.split() if x]
        except Exception:
            ids = []
        if not ids:
            # A multi-file compose joins config_files with commas, which an exact label
            # match cannot express — fall back to the name scan, uncapped, and let the
            # label comparison below do the filtering.
            ps = subprocess.run(
                [rt, "ps", "-a", "--filter", "name=%s" % service, "--format", "{{.ID}}"],
                capture_output=True, text=True, timeout=timeout)
            ids = [x for x in ps.stdout.split() if x]
        for cid in ids:
            try:
                out = subprocess.run(
                    [rt, "inspect", cid, "--format",
                     "{{index .Config.Labels \"com.docker.compose.project.config_files\"}}"
                     "|{{.State.Status}}|{{.State.ExitCode}}"],
                    capture_output=True, text=True, timeout=timeout).stdout.strip()
                lbl, _, rest = out.partition("|")
                status, _, code = rest.partition("|")
            except Exception:
                continue
            if not lbl or not (lbl == want or want in lbl.split(",")):
                continue
            if status == "running":
                continue
            tail = ""
            try:
                lg = subprocess.run([rt, "logs", "--tail", "3", cid],
                                    capture_output=True, text=True, timeout=timeout)
                _raw1202av = " ".join(((lg.stdout or "") + (lg.stderr or "")).split())
                # #1034: declare the cut rather than presenting a slice as the whole tail.
                tail = _raw1202av[:220] + ("…" if len(_raw1202av) > 220 else "")
            except Exception:
                pass
            return ("this run's container %s is %s with exit code %s%s"
                    % (cid[:12], status or "gone", code or "?",
                       (" — last output: " + tail) if tail else ""))
    except Exception:
        pass
    return ""

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


def compose_provider(*, timeout: int = 20) -> Dict[str, Any]:
    """Which compose implementation is behind ``<runtime> compose``, and what it cannot do.

    #936c: a preflight that only asks "is the daemon up?" cannot see the state that actually
    costs anything here. Under `tools/podman_shim`, ``docker compose version`` answers
    ``podman-compose version 1.5.0`` — and podman-compose's own help is explicit:

        usage: podman-compose ps [-h] [-q] [-f FORMAT]        <- no service positional

    So ``compose ps -q <service>`` exits 2 with EMPTY stdout, which is not an exception. Every
    probe keyed on that lookup (#715, #738) has produced nothing for the whole corpus, silently.
    Reported at startup so a reader does not have to find it the way I did.

    Returns ``{"provider", "service_ps", "message"}``; never raises.
    """
    rt = runtime_bin()
    try:
        r = subprocess.run([rt, "compose", "version"],
                           capture_output=True, text=True, timeout=timeout)
        text = ((r.stdout or "") + " " + (r.stderr or "")).strip()
    except Exception as exc:
        # #1202et: the message too. This decides the compose provider and then says
        # "assuming v2"; a reader who only learns "TimeoutExpired" cannot tell a slow host
        # from a missing binary from a permission error, and the assumption rides on it.
        return {"provider": "unknown", "service_ps": True,
                "message": (f"{rt} compose version failed "
                            f"({type(exc).__name__}: {exc}) — assuming v2")}
    low = text.lower()
    if "podman-compose" in low:
        return {"provider": text.splitlines()[0].strip()[:60] if text else "podman-compose",
                "service_ps": False,
                "message": ("podman-compose has NO service positional on `ps`, so "
                            "`compose ps -q <service>` returns EMPTY (exit 2, not an exception). "
                            "Use container_runtime.container_id(), which falls back to a name "
                            "filter — #715/#738 produced nothing for the entire corpus without "
                            "it.")}
    return {"provider": text.splitlines()[0].strip()[:60] if text else f"{rt} compose",
            "service_ps": True, "message": "compose v2: `ps -q <service>` supported"}


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
        ids = [ln.strip() for ln in out.splitlines() if ln.strip()] if out else []
    except Exception:
        return ""
    if len(ids) > 1:
        # #962 — AMBIGUOUS. Every run's compose project is named `docker` (the project name comes
        # from the compose file's parent directory, which is always `docker/`), so containers are
        # named `docker_backend_1` with NO run identity. Two stacks up at once — a leftover from a
        # previous run is enough, measured 2026-08-18 — and this filter matches both. Taking
        # `[0]` silently answers about SOMEONE ELSE'S container, which is exactly how a stale-build
        # or served-build probe reports confidently about the wrong app.
        #
        # Disambiguate on the compose project's config_files label, which carries the absolute
        # path of the file the caller asked about. If that cannot single one out, return "" —
        # "unknown" is recoverable, a confident wrong container is not.
        want = str(compose_file)
        matched = []
        for cid in ids:
            try:
                lbl = subprocess.run(
                    [rt, "inspect", cid, "--format",
                     "{{index .Config.Labels \"com.docker.compose.project.config_files\"}}"],
                    capture_output=True, text=True, timeout=timeout).stdout.strip()
            except Exception:
                continue
            if lbl and (lbl == want or want in lbl.split(",")):
                matched.append(cid)
        log = logging.getLogger(__name__)
        if len(matched) == 1:
            log.warning(
                "#962 `%s ps --filter name=%s` matched %d containers (compose project name is "
                "`docker` for EVERY run, so names collide across runs); disambiguated to %s by "
                "config_files label %s.", rt, service, len(ids), matched[0][:12], want)
            return matched[0]
        # #1130: ZERO candidates and TWO-OR-MORE are opposite problems with opposite
        # remedies, and #962 gave them one message written for the second. "matched N
        # containers and the label could not single one out ... Stop the stale stack, or
        # give the run its own compose project name" tells a reader to DISAMBIGUATE. When
        # `matched` is empty there is nothing to disambiguate: every running container with
        # that name belongs to some OTHER run, and this run's own container is simply not
        # up. Stopping a stale stack changes nothing; starting this one is the whole fix.
        #
        # Measured across both runs built by the current code: 97 of 97 of these were the
        # zero case (netflix-local-r1 66, smoke-notes 31) — the ambiguous case the wording
        # was written for has not occurred once. It is not cosmetic: this returns "" and
        # `seed_audit` then reports `#1039 live seed row-count DID NOT RUN (no database
        # container resolved)`, so the seed audit was blind for entire runs while the log
        # blamed a name collision.
        if not matched:
            # #1202au: say it when the STATE changes, not on every probe. The message is
            # correct — verified against r32, whose `database` container genuinely was not
            # running for the 4h24m this fired — but it fired 179 times saying exactly that,
            # one unchanging fact per probe. Same rule as #1202n/#1202p/#1202v/#1202ab/
            # #1202ac. A move back to a previously-seen state still reports, so a stack that
            # goes down, comes up and goes down again is not silently swallowed.
            from .message_format import state_changed_1202ad
            if not state_changed_1202ad(
                    "container_zero_match:%s:%s" % (want, service), len(ids)):
                return ""
            _why1202av = _exited_container_reason_1202av(rt, service, want, timeout)
            if _why1202av:
                log.error(
                    "#1202av why this run's `%s` container is not running: %s. `up -d` without "
                    "--wait returns rc=0 once the start is ISSUED, so a container that dies "
                    "immediately still looks like a successful bring-up — r32 logged 66 such "
                    "successes across the same window as 179 of the line below, and never once "
                    "looked at the stopped container.", service, _why1202av)
            log.error(
                "#962/#1130 `%s ps --filter name=%s` found %d running container(s) with that "
                "name and NONE of them belongs to this run (no config_files label matches %s). "
                "This run's `%s` container is NOT RUNNING — the other %d belong to other runs "
                "and are irrelevant. Returning NO id rather than guessing. Start this run's "
                "stack (compose up) before probing it; stopping the other stacks would not "
                "help.", rt, service, len(ids), want, service, len(ids))
            return ""
        log.error(
            "#962 `%s ps --filter name=%s` matched %d containers and the config_files label could "
            "not single one out (%d candidates for %s). Returning NO id rather than guessing — a "
            "probe that answers about another run's container reports confidently about the wrong "
            "app. Stop the stale stack, or give the run its own compose project name.",
            rt, service, len(ids), len(matched), want)
        return ""
    cid = ids[0] if ids else ""
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
