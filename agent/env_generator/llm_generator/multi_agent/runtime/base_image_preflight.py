"""Base-image preflight primitives — generalizable infra hardening (task #32).

Two dev-box outages (r22/r23, 2026-08-03) burned hours because docker_up rebuilds
each service FROM base images that had been pruned, and the pulls failed
unrecoverably (mirror mTLS cert unfollowable by rootless podman; ghcr DNS-blocked).
The validation loop kept RETRYING those unrecoverable failures up to its cap and
then ran a remediation backlog — grinding to the 2h wall-clock watchdog with no
delivery and no verdict.

These are the PURE primitives the fix is built on (no I/O, no product literals, so
they generalize to every app + env):

  * ``base_images_required(...)``  — the base images an app's build actually needs,
    parsed from its generated Dockerfiles + compose (NOT a hardcoded list), so it
    tracks whatever bases the templates emit.
  * ``unrecoverable_base_pull_error(...)`` — True when a docker_up failure is a base
    image that cannot be fetched here (egress/mirror/cert), i.e. retrying is futile
    and the run should fail FAST with a clear cause instead of looping to the cap.

The subprocess-driven seeding + the fail-fast wiring live elsewhere; keeping the
decision logic pure makes it unit-testable without a container runtime.
"""
from __future__ import annotations

import re
from typing import Iterable, List, Sequence

# A build-container FROM line: `FROM <ref> [AS <stage>]` (case-insensitive), with an
# optional `--platform=...` flag. Stage aliases (the `AS name` part, and bare
# `FROM <earlier-stage>`) are NOT base images — they resolve within the build.
_FROM_RE = re.compile(
    r"^\s*FROM\s+(?:--platform=\S+\s+)?(?P<ref>\S+)(?:\s+AS\s+(?P<stage>\S+))?\s*$",
    re.IGNORECASE,
)
# A compose `image: <ref>` entry (a pulled image; services with only `build:` are
# covered by their Dockerfile FROM lines instead).
_COMPOSE_IMAGE_RE = re.compile(r"^\s*image:\s*[\"']?(?P<ref>[^\"'\s#]+)[\"']?\s*$")

# Substrings that mark a pull/build failure as UNRECOVERABLE in this environment —
# no amount of retrying fixes an unreachable registry or an unusable client cert.
# Sourced verbatim from the r22/r23 docker_up logs; matched case-insensitively.
_UNRECOVERABLE_MARKERS = (
    "creating build container: unable to copy",   # buildah cannot fetch the FROM base
    "manifest unknown",                            # mirror reached, tag absent (e.g. ghcr not mirrored)
    "no such host",                                # registry DNS blocked (ghcr.io / docker.io direct)
    "pinging container registry",                  # registry unreachable during the connectivity ping
    "mirrors also failed",                         # every configured mirror failed
    "certs.d",                                     # client cert path unreadable (the symlink ENOENT)
    "x509: certificate",                           # TLS/cert rejection talking to the mirror
    "client.cert: no such file",                   # the exact rootless-podman-cant-follow-symlink error
)


def _strip_stage_refs(refs: Iterable[str]) -> List[str]:
    """Drop refs that name an earlier build stage rather than a real image."""
    seen: List[str] = []
    stages = set()
    out: List[str] = []
    for ref, stage in refs:
        if stage:
            stages.add(stage)
    for ref, _stage in refs:
        if ref in stages:
            continue  # `FROM builder` — resolves to a prior stage, not a base pull
        if ref not in seen:
            seen.append(ref)
            out.append(ref)
    return out


def base_images_from_dockerfile(text: str) -> List[str]:
    """Base image refs a Dockerfile pulls, in order, de-duplicated.

    Multi-stage aware: ``FROM x AS builder`` then ``FROM builder`` yields only ``x``.
    """
    pairs = []
    for line in (text or "").splitlines():
        m = _FROM_RE.match(line)
        if not m:
            continue
        pairs.append((m.group("ref"), m.group("stage")))
    return _strip_stage_refs(pairs)


def base_images_from_compose(text: str) -> List[str]:
    """Pulled image refs declared via ``image:`` in a compose file, de-duplicated."""
    out: List[str] = []
    for line in (text or "").splitlines():
        m = _COMPOSE_IMAGE_RE.match(line)
        if not m:
            continue
        ref = m.group("ref")
        if ref and ref not in out:
            out.append(ref)
    return out


def base_images_required(
    dockerfile_texts: Sequence[str] = (), compose_texts: Sequence[str] = ()
) -> List[str]:
    """Union of every base image an app's build needs (Dockerfile FROM + compose image:).

    Order-stable and de-duplicated. Empty inputs → empty list (caller decides policy).
    """
    out: List[str] = []
    for t in dockerfile_texts:
        for ref in base_images_from_dockerfile(t):
            if ref not in out:
                out.append(ref)
    for t in compose_texts:
        for ref in base_images_from_compose(t):
            if ref not in out:
                out.append(ref)
    return out


def unrecoverable_base_pull_error(text: str) -> bool:
    """True if a docker_up failure is an unfetchable base image (retrying is futile).

    Deliberately conservative: returns True only on the known egress/mirror/cert
    signatures, so a transient or app-code build error still gets the normal retries.
    """
    if not text:
        return False
    low = text.lower()
    return any(marker in low for marker in _UNRECOVERABLE_MARKERS)


# ── #441: generic anti-spin fail-fast — detect a remediation loop stuck on the SAME
#    failure so it aborts instead of retrying to the wall-clock (r23: docker_up failed
#    IDENTICALLY 2×, spun ~1.5h; r28: the same remediation replayed to queue-full=130).
#    Pure + generic across failure TYPES (build / api_smoke / business_chain / gate),
#    so it generalizes to every app+env. The subprocess wiring (feed each attempt's
#    log, abort when is_spinning) lives in the orchestrator; keeping the decision pure
#    makes it unit-testable without a live run. ─────────────────────────────────────
_SIG_NORMALIZERS = (
    (re.compile(r"\d{4}-\d{2}-\d{2}[ t]\d{2}:\d{2}:\d{2}\S*"), "<ts>"),  # timestamps
    (re.compile(r"/[^\s'\":]+"), "<path>"),                              # abs paths
    (re.compile(r"0x[0-9a-f]+"), "<hex>"),                               # hex addrs
    (re.compile(r"\b[0-9a-f]{7,}\b"), "<hash>"),                         # sha/uuids
    (re.compile(r"\d+"), "<n>"),                                         # any number
    (re.compile(r"\s+"), " "),                                           # collapse ws
)


def failure_signature(text: str, keep_lines: int = 4) -> str:
    """A STABLE, normalized signature of a failure log: its last few non-empty lines
    with volatile tokens (timestamps, paths, hashes, numbers) masked, so the SAME
    underlying failure yields the SAME signature across retries (differing only in a
    timestamp / temp path / pid). '' for empty input. Lower-cased. Generic."""
    if not text:
        return ""
    lines = [ln.strip() for ln in str(text).strip().splitlines() if ln.strip()]
    if not lines:
        return ""
    sig = " | ".join(lines[-max(1, keep_lines):]).lower()
    for rx, rep in _SIG_NORMALIZERS:
        sig = rx.sub(rep, sig)
    return sig.strip()


def is_spinning(signatures: Sequence[str], threshold: int = 3) -> bool:
    """True when the last ``threshold`` failure signatures are IDENTICAL (and non-
    empty) — the remediation loop is making no progress on the same error, so more
    retries are futile and it should fail-fast. Conservative: needs ``threshold``
    samples and exact-match; a loop that varies its error each attempt (genuine
    progress) never trips it. Generic across failure types + apps."""
    if threshold < 1 or len(signatures) < threshold:
        return False
    last = list(signatures)[-threshold:]
    return bool(last[0]) and len(set(last)) == 1
