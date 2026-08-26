"""#1119: extract the cause, THEN truncate — not the other way round.

`#748` rightly captured compose's stderr when a run failed to boot, then kept a blind
PREFIX of it: `compose_stderr=stderr[:500]` for the record and `stderr[:400]` for the
log line. docker compose emits its deprecation warning FIRST, then network/volume/
container progress, and only then the error.

Captured live from a real failure: 861 bytes of stderr with `OCI runtime` at offset
690, `seccomp` at 790 and `errno 524` at 842 — the entire cause past the 500-byte cap.
All 17 compose-up failures of that run therefore reported their cause as "the attribute
`version` is obsolete", a deprecation warning that is not an error at all.

The corpus cannot show the improvement: 0 of its 407 stored `compose_stderr` records
contain `OCI runtime`, because this truncation is what discarded it before anything
could read it. That absence is the evidence, not a counter-example.

#1119b: `OCI runtime create failed: ... error loading seccomp filter into kernel`
matched none of `_ERR_MARKERS` — `error:` wants the colon, and this says `create
failed` — so even reading the whole text the extractor fell through to the tail.
"""
import pytest

from env_generator.llm_generator.multi_agent.runtime.hubs.runhub.service import (
    _salient_stderr_1119,
)
from env_generator.llm_generator.multi_agent.runtime.framework_validation import (
    _ERR_MARKERS,
)

# the real shape, offsets preserved: warning first, cause last
REAL = (
    'time="2026-08-26T12:46:13-05:00" level=warning '
    'msg="/data/common/haibotong/forgingground-gen/generated/smoke-notes/docker/'
    'docker-compose.yml: the attribute `version` is obsolete, it will be ignored, '
    'please remove it to avoid potential confusion"\n'
    " Network docker_default  Creating\n"
    " Network docker_default  Created\n"
    ' Volume "docker_app_auth_keys"  Creating\n'
    ' Volume "docker_app_auth_keys"  Created\n'
    " Container docker-database-1  Creating\n"
    " Container docker-database-1  Created\n"
    " Container docker-backend-1  Creating\n"
    " Container docker-backend-1  Created\n"
    "Error response from daemon: OCI runtime create failed: container_linux.go:380: "
    "starting container process caused: error loading seccomp filter into kernel: "
    "loading seccomp filter: errno 524: unknown\n"
)


def _has_cause(text):
    low = (text or "").lower()
    return "seccomp" in low or "oci runtime" in low or "errno 524" in low


def test_the_fixture_reproduces_the_defect():
    """Guard the guard: if compose ever stops front-loading noise, say so here."""
    assert len(REAL) > 500, "fixture must exceed the storage cap"
    assert not _has_cause(REAL[:500]), "fixture no longer hides the cause behind the cap"
    assert "obsolete" in REAL[:400], "fixture no longer starts with the deprecation warning"


def test_the_extracted_cause_is_the_causal_line():
    got = _salient_stderr_1119(REAL)
    assert _has_cause(got), "the cause is still missing from what gets stored: %r" % got[:120]
    assert "OCI runtime create failed" in got
    # and it is the LINE, not a window of progress noise around it
    assert "Creating" not in got, "the excerpt is still padded with progress noise: %r" % got
    assert "obsolete" not in got, "the deprecation warning is still being reported as a cause"


def test_it_fits_the_cap_that_gets_stored():
    got = _salient_stderr_1119(REAL)
    assert _has_cause(got[:500]), "the cause fell outside the 500 chars actually stored"
    assert _has_cause(got[:400]), "the cause fell outside the 400 chars actually logged"


def test_the_oci_marker_is_registered():
    assert "oci runtime" in _ERR_MARKERS, (
        "#1119b's marker is gone; the extractor falls back to the tail for every "
        "container-runtime failure"
    )


def test_a_healthcheck_exec_failure_is_also_caught():
    """The same host fault surfaces as `OCI runtime exec failed` from a HEALTHCHECK."""
    text = (
        " Container app-db-1  Waiting\n"
        " Container app-db-1  Error\n"
        "OCI runtime exec failed: exec failed: container_linux.go:380: starting "
        "container process caused: error loading seccomp filter into kernel: errno 524\n"
    )
    assert _has_cause(_salient_stderr_1119(text))


def test_empty_stderr_stays_empty():
    """The caller substitutes its own guidance message for an empty cause."""
    assert _salient_stderr_1119("") == ""
    assert _salient_stderr_1119(None) == ""


def test_a_pre_existing_error_shape_still_wins():
    """#1119b only ADDS a marker; it must not displace the errors already matched."""
    text = (
        " Container app-ui-1  Creating\n"
        "npm ERR! code ELIFECYCLE\n"
        "npm ERR! Failed at the build script\n"
    )
    got = _salient_stderr_1119(text)
    assert "npm ERR!" in got


def test_extraction_never_loses_the_text_on_a_fault(monkeypatch):
    """Any failure inside the extractor must degrade to the pre-#1119 behaviour."""
    from env_generator.llm_generator.multi_agent.runtime import (
        framework_validation as FV,
    )

    def _boom(*a, **k):
        raise RuntimeError("nope")

    monkeypatch.setattr(FV, "_salient_error", _boom)
    got = _salient_stderr_1119(REAL)
    assert got == REAL, "a broken extractor swallowed the stderr entirely"
