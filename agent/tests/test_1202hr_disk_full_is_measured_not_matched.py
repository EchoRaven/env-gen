"""#1202hr — the host's disk was full and the framework filed a P0 against the backend lane.

tiktok-web-r106, live. The root filesystem holding `/var/lib/docker` was at 100% with 5.0G
left (1035 dangling images, 176GB reclaimable). Every symptom the run reported was downstream
of that:

    Error response from daemon: Error processing tar file(exit status 1): unexpected EOF
    RunHub run_5313a06c5a aborted on backend /health (server disconnected without sending
      a response after 31 attempts)
    Error: Page.goto: net::ERR_CONNECTION_REFUSED at http://localhost:8081/

and the orchestrator's response was "I created backend P0 task_01e0e3d7c2 to restore
healthcheck/startup" — a host fault laundered into a lane defect. This has happened before
and is recorded as its own defect class; the lane spent 45 minutes on it and then fabricated
a fix.

`_HOST_LEVEL_1202CN` exists to prevent exactly this, and it did not fire, because it matches
the daemon's WORDING and disk exhaustion surfaced as "unexpected EOF" and "server
disconnected" — never the string "no space left on device" it looks for.

A condition that can be MEASURED should not be guessed at from text. When a compose operation
fails and no known wording matched, this reads the free space on the filesystem docker
actually stores images on — which is not necessarily the one the run directory is on. The
launcher's own preflight illustrates the trap: it printed `free=102G` for /data while / had
5.0G, so the guard passed and the run was doomed before it started.
"""
import sys
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(_ROOT), str(_ROOT / "env_generator" / "llm_generator")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from multi_agent.runtime.validation_runner import (_HOST_LEVEL_1202CN,
                                                   low_docker_disk_1202hr)


class _Usage:
    def __init__(self, free_gb):
        self.free = int(free_gb * (1024 ** 3))
        self.total = 1800 * (1024 ** 3)
        self.used = self.total - self.free


class MeasuredNotMatched(unittest.TestCase):
    def test_an_exhausted_docker_filesystem_is_reported(self):
        msg = low_docker_disk_1202hr(usage=lambda p: _Usage(5.0), root=lambda: "/var/lib/docker")
        self.assertTrue(msg, "5.0G free — the exact state that broke r106 — read as fine")
        self.assertIn("/var/lib/docker", msg)

    def test_the_message_names_a_remedy_the_operator_can_run(self):
        msg = low_docker_disk_1202hr(usage=lambda p: _Usage(2.0), root=lambda: "/var/lib/docker")
        self.assertIn("prune", msg, msg)

    def test_ample_space_says_nothing(self):
        """It must not add noise to the vast majority of failures, which are the app's."""
        self.assertIsNone(
            low_docker_disk_1202hr(usage=lambda p: _Usage(172.0), root=lambda: "/var/lib/docker"))

    def test_it_measures_dockers_filesystem_not_the_run_directory(self):
        """The launcher's preflight measured the repo's mount and printed `free=102G` while
        the mount docker writes to had 5.0G. Reading the wrong path is how the guard passed."""
        seen = []

        def usage(p):
            seen.append(str(p))
            return _Usage(5.0)

        low_docker_disk_1202hr(usage=usage, root=lambda: "/var/lib/docker")
        self.assertEqual(seen, ["/var/lib/docker"])

    def test_an_unreadable_docker_root_is_not_a_disk_verdict(self):
        """#883: "could not tell" must not render as "the disk is fine" OR as "it is full"."""
        def boom(_p):
            raise OSError("nope")
        self.assertIsNone(low_docker_disk_1202hr(usage=boom, root=lambda: "/var/lib/docker"))

    def test_the_wording_table_still_carries_its_own_cases(self):
        """The measured check ADDS to the substring table; it does not replace it — a daemon
        that does say "no space left on device" is still recognised immediately."""
        self.assertIn("no space left on device", _HOST_LEVEL_1202CN)


if __name__ == "__main__":
    unittest.main()
