"""#1202lm — `docker compose ps` during a recycle looks exactly like a dead app.

GROUND TRUTH (tiktok-web-r120 resume2, delivery window). `run_smoke_validation` opens every
cycle with `down -v` + build + `up`, and it ran that cycle every ~90 seconds:

    19:14:07 down -v · 19:14:10 build · 19:14:21 up   (22s of "stopped")
    19:15:40 down -v · 19:15:42 build · 19:15:5x up
    ...

The framework's own line at the delivery cut:

    #743 1 P0 BUG task(s) are still open at the delivery cut: UI validation blocked:
    frontend/backend services stopped during browser smoke, leaving only database
    running. Corpus: 90 of 129 runs end this way

"Only database running" is not a crash signature — it is the NORMAL MIDDLE of a healthy
recycle, because postgres is the dependency and comes back first. A point-in-time `ps`
cannot tell the two apart, and its reader is an LLM that files P0s against the lane.

The fact that separates them already existed, in the compose lock; it just had one reader
(#1202dl's own acquisition). This gives it to the two tools that hand the snapshot to an
agent — and the second one matters more, because its advice ("Run docker_up first") is the
concurrent-compose race #36's lock exists to prevent.
"""
import fcntl
import inspect
from pathlib import Path

import pytest

from env_generator.llm_generator.tools import docker_tools as dt


def _lockfile(tmp_path):
    d = tmp_path / "docker"
    d.mkdir(parents=True, exist_ok=True)
    (d / "docker-compose.yml").write_text("services: {}\n", encoding="utf-8")
    return d / "docker-compose.yml"


def test_a_held_lock_reads_as_a_recycle(tmp_path):
    cf = _lockfile(tmp_path)
    lock = cf.parent / ".smoke_validation.lock"
    lock.write_text("", encoding="utf-8")
    with open(lock, "w") as holder:
        fcntl.flock(holder.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        assert dt.compose_recycle_in_flight_1202lm(cf) is True
    assert dt.compose_recycle_in_flight_1202lm(cf) is False


def test_no_lock_file_is_not_a_recycle(tmp_path):
    assert dt.compose_recycle_in_flight_1202lm(_lockfile(tmp_path)) is False


def test_the_probe_does_not_keep_the_lock(tmp_path):
    """★ It reports; it must never serialise. A probe that held would BE the outage."""
    cf = _lockfile(tmp_path)
    lock = cf.parent / ".smoke_validation.lock"
    lock.write_text("", encoding="utf-8")
    assert dt.compose_recycle_in_flight_1202lm(cf) is False
    with open(lock, "w") as rival:          # a real validation must still get in
        fcntl.flock(rival.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(rival.fileno(), fcntl.LOCK_UN)


def test_the_probe_does_not_truncate_the_holders_marker(tmp_path):
    """Opened append-only: `open(..., "w")` would empty a file another process owns."""
    cf = _lockfile(tmp_path)
    lock = cf.parent / ".smoke_validation.lock"
    lock.write_text("holder-pid-12345", encoding="utf-8")
    dt.compose_recycle_in_flight_1202lm(cf)
    assert lock.read_text(encoding="utf-8") == "holder-pid-12345"
    assert '"a"' in inspect.getsource(dt.compose_recycle_in_flight_1202lm)


def test_unknowable_is_not_in_flight():
    """Claiming a recycle that is not happening would excuse a genuinely dead stack."""
    assert dt.compose_recycle_in_flight_1202lm(None) is False
    assert dt.compose_recycle_in_flight_1202lm("/nonexistent/path/docker-compose.yml") is False


def test_docker_status_hands_the_fact_to_its_reader():
    src = inspect.getsource(dt.DockerStatusTool.execute)
    assert "compose_recycle_in_flight_1202lm" in src, (
        "docker_status still returns a bare snapshot — the reader cannot tell a recycle "
        "from a crash")
    assert "_RECYCLE_NOTE_1202LM" in src, "the note never reaches the agent-visible text"
    assert "stopped_services" in src


def test_the_note_forbids_filing_a_bug_from_a_recycle():
    note = dt._RECYCLE_NOTE_1202LM
    assert "Do not" in note and "file a bug" in note
    assert "only database running" in note, (
        "the note must name the exact signature the corpus reports, or the reader will not "
        "connect it to what it is looking at")
    assert "re-check" in note.lower(), "a refusal with no next step is just a block"


def test_the_exec_path_does_not_advise_racing_the_recycle():
    """★ The harm here is the REMEDY, not the diagnosis: docker_up during a `down -v`/`up`
    is the concurrent-compose race #36's lock exists to prevent."""
    src = inspect.getsource(dt)
    i = src.index("No container for service")
    j = src.index("Run docker_up first.", i)
    guarded = src[:i]
    assert "compose_recycle_in_flight_1202lm(compose_file)" in guarded.rsplit(
        "def ", 1)[-1] or "compose_recycle_in_flight_1202lm" in src[max(0, i - 1200):i], (
        "the recycle-aware arm must precede the docker_up advice")
    assert "Do NOT run docker_up" in src[i:j], (
        "the recycle arm must say explicitly not to race it")


def test_both_emitters_are_covered():
    """#934's lesson: a guard on one of several producing branches is not a guard."""
    src = inspect.getsource(dt)
    assert src.count("compose_recycle_in_flight_1202lm(") >= 3, (
        "the fact must reach EVERY agent-visible emitter of 'the services are not up', "
        "not just the first one found")
