r"""#1202zk: the disk preflight rounded in the permissive direction, and its advice was stale.

Two defects in one three-line check.

★ THE FLOOR ADMITTED LESS THAN IT SAID. It read `df --output=avail -BG /` and tested `>= 60`,
and **`df -BG` rounds UP**: measured on 2026-09-29, root had **59.625 GiB** free
(64,022,118,400 bytes) and `df -BG` printed **60G**, so the check PASSED. The floor was really
59.001 GiB. Rounding toward ADMITTING is the wrong direction for a floor whose whole job is to
keep out the run that dies at minute 40 with a full disk — the failure it exists to prevent.
Found because a reporter built alongside it disagreed with it; two measurements of one fact
disagreeing is the most productive shape in this project.

★ AND THE ADVICE POINTED AT AN EMPTY DRAWER. The refusal had said `先 docker builder prune -af`
for weeks. On the same day: build cache **0B**, images **39.06GB**, volumes **20.82GB**. A hint
that was true once sends its reader to the one place with nothing in it.

★ THE TWO RECLAIM ROUTES ARE NOT EQUALLY SAFE, and the message says so. Dangling IMAGES are
untagged, referenced by no container and rebuildable. Dangling VOLUMES are DATA:
`docker volume ls -f dangling=true` means "referenced by no container", which INCLUDES an
environment that is merely STOPPED and whose data matters — on this machine that set covers
other work lines' environments (windows_web, macos_web, the messaging apps). 432 volumes
qualified. A blanket `volume prune` is never the safe answer, and saying "20.8G reclaimable"
without saying that is how someone deletes another project's data.
"""
import importlib.util
import os
import sys

_AGENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_ROOT = os.path.dirname(_AGENT)
_SCRIPT = os.path.join(_ROOT, "scripts", "disk_headroom.py")
_LAUNCH = os.path.join(_ROOT, "scripts", "tiktok_designinput.sh")

_GiB = 1024 ** 3


def _mod():
    spec = importlib.util.spec_from_file_location("disk_headroom_1202zk", _SCRIPT)
    m = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = m
    spec.loader.exec_module(m)
    return m


class _Usage:
    def __init__(self, free_gib):
        self.free = int(free_gib * _GiB)
        self.total = 1800 * _GiB
        self.used = self.total - self.free


def _wire(monkeypatch, m, free_gib, df=None):
    monkeypatch.setattr(m.shutil, "disk_usage", lambda _p: _Usage(free_gib))
    monkeypatch.setattr(m, "_docker_df", lambda: (df if df is not None else {
        "Images": ("51.05GB", "39.06GB"),
        "Local Volumes": ("25.36GB", "20.82GB"),
        "Build Cache": ("0B", "0B")}))


# ── the rounding direction ────────────────────────────────────────────────────────

def test_the_exact_value_that_df_rounded_up_is_now_refused(monkeypatch):
    """★ The measured case: 59.625 GiB free, a 60G floor. `df -BG` said 60G and the old check
    passed; exact bytes refuse."""
    m = _mod(); _wire(monkeypatch, m, 59.625)
    code, msg = m.report(60)
    assert code == 1, msg
    assert "59.6" in msg and "REFUSED" in msg


def test_a_hair_above_the_floor_passes(monkeypatch):
    m = _mod(); _wire(monkeypatch, m, 60.01)
    assert m.report(60)[0] == 0


def test_exactly_the_floor_passes(monkeypatch):
    """`>=`, not `>` — a floor of 60 means 60 is enough."""
    m = _mod(); _wire(monkeypatch, m, 60.0)
    assert m.report(60)[0] == 0


def test_the_report_states_the_exact_figure_not_a_rounded_one(monkeypatch):
    """A message that prints `60G` while refusing at 59.6 reads as a contradiction and the
    reader stops trusting it."""
    m = _mod(); _wire(monkeypatch, m, 59.625)
    assert "59.63G" in m.report(60)[1] or "59.62G" in m.report(60)[1]


# ── the advice ────────────────────────────────────────────────────────────────────

def test_images_are_offered_first_and_marked_safe(monkeypatch):
    m = _mod(); _wire(monkeypatch, m, 10)
    msg = m.report(60)[1]
    assert "docker image prune" in msg
    assert "SAFE" in msg
    assert msg.index("docker image prune") < msg.index("docker volume prune")


def test_volumes_are_marked_not_safe_and_say_why(monkeypatch):
    """★ The sentence that keeps someone from deleting another project's data."""
    m = _mod(); _wire(monkeypatch, m, 10)
    msg = m.report(60)[1]
    assert "NOT SAFE" in msg
    assert "STOPPED" in msg, msg


def test_an_empty_build_cache_is_named_as_empty(monkeypatch):
    """The stale advice pointed here. When there is nothing in it, say so rather than
    repeating the hint."""
    m = _mod(); _wire(monkeypatch, m, 10)
    msg = m.report(60)[1]
    assert "reclaims nothing" in msg
    assert "docker builder prune -af    #" not in msg, "an empty cache must not be offered"


def test_a_full_build_cache_is_offered(monkeypatch):
    m = _mod(); _wire(monkeypatch, m, 10, df={
        "Images": ("1GB", "0B"), "Local Volumes": ("1GB", "0B"),
        "Build Cache": ("45GB", "45.0GB")})
    msg = m.report(60)[1]
    assert "docker builder prune -af" in msg and "45.0G" in msg


def test_nothing_reclaimable_offers_nothing(monkeypatch):
    m = _mod(); _wire(monkeypatch, m, 10, df={
        "Images": ("1GB", "0B"), "Local Volumes": ("1GB", "0B"),
        "Build Cache": ("0B", "0B")})
    msg = m.report(60)[1]
    assert "docker image prune" not in msg and "docker volume prune" not in msg


def test_the_size_parser_handles_every_unit(monkeypatch):
    m = _mod()
    assert abs(m._gb("39.06GB") - 39.06) < 1e-6
    assert abs(m._gb("512MB") - 0.512) < 1e-6
    assert abs(m._gb("2TB") - 2000.0) < 1e-6
    assert m._gb("0B") == 0.0
    assert m._gb("nonsense") == 0.0


# ── degradation ───────────────────────────────────────────────────────────────────

def test_an_unreadable_docker_still_gives_the_disk_verdict(monkeypatch):
    """★ The disk figure is the part that decides; losing the advice must not lose the
    verdict, and it must not be silent about the loss either."""
    m = _mod(); _wire(monkeypatch, m, 10, df={})
    code, msg = m.report(60)
    assert code == 1
    assert "could not be read" in msg


def test_a_docker_that_raises_is_not_a_crash(monkeypatch):
    m = _mod()
    monkeypatch.setattr(m.shutil, "disk_usage", lambda _p: _Usage(10))
    def _boom(*a, **k):
        raise OSError("docker daemon is gone")
    monkeypatch.setattr(m.subprocess, "run", _boom)
    assert m.report(60)[0] == 1


# ── the caller ────────────────────────────────────────────────────────────────────

def test_the_launcher_delegates_and_keeps_no_second_measurement():
    """★ #1032: two measurements of one fact drift into two answers. The df arithmetic is
    gone, not merely supplemented."""
    src = open(_LAUNCH, encoding="utf-8").read()
    assert "disk_headroom.py" in src, "the launcher does not call the reporter"
    # EXECUTABLE lines only. The first version of this forbade the STRING, and the comment
    # that explains why the old `df -BG` check was wrong tripped it — a textual test that
    # cannot tell a comment from code forbids the documentation along with the defect.
    code_lines = [ln for ln in src.splitlines()
                  if ln.strip() and not ln.lstrip().startswith("#")]
    for ln in code_lines:
        assert "--output=avail -BG" not in ln, (
            "the launcher still computes its own rounded figure: %s" % ln.strip())
        assert "AVAIL_G" not in ln, (
            "the old variable survives in executable code: %s" % ln.strip())


def test_the_launcher_passes_the_floor_and_refuses_on_failure():
    src = open(_LAUNCH, encoding="utf-8").read()
    i = src.index("disk_headroom.py")
    nxt = src.find("\n# ---", i)
    window = src[i:nxt if nxt != -1 else len(src)]
    assert "60" in window, window
    assert "REFUSED" in window and "exit 1" in window, window
