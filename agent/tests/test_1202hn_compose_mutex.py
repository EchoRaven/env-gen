"""#1202hn — two components brought the SAME compose project up at the same time.

tiktok-web-r105, live, in one nine-second window:

    17:04:05  orchestrator calls run_start        -> RunHub begins its own `compose up`
    17:04:12  validation_runner: docker up -d --remove-orphans
    17:04:14  RunHub: compose up FAILED (rc=1)
              " Container tiktok-web-r105-frontend-1  Created
                ...
                Error response from daemon: No such container: c1080f8b..."
    17:04:14  validation_runner: docker up -d --remove-orphans -> rc=0 in 2s

One `up` carried `--remove-orphans` and removed a container the other had just created. The
stack itself was fine — seven seconds later the run captured live seed counts from it
(`videos: 28, comments: 295, users: 9`) — but RunHub recorded its run as `aborted`, which is
what `deliverability_no_successful_run` reads. A delivery blocker produced entirely by two
framework components racing, with nothing a lane could do about it.

Neither path had any mutual exclusion: `validation_runner._compose` and
`hubs/runhub/compose.py::_default_runner` each spawn their own subprocess.

Scope is deliberate. Only the container-LIFECYCLE verbs are serialized (`up`, `down`, `stop`,
`start`, `restart`, `rm`): those are what create and destroy containers, and they finish in
seconds (the r105 pair took 2s and 0s). `build` is NOT serialized — it took 28s in that same
window and can take 900s, and holding a lock across it would trade this race for RunHub
timeouts. `ps` / `logs` / `config` observe and cannot race.
"""
import sys
import threading
import time
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(_ROOT), str(_ROOT / "env_generator" / "llm_generator")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from multi_agent.runtime.compose_mutex import (compose_mutex_1202hn,
                                               is_lifecycle_op_1202hn)


class WhichOpsAreSerialized(unittest.TestCase):
    def test_lifecycle_verbs_are(self):
        for op in ("up", "down", "stop", "start", "restart", "rm"):
            self.assertTrue(is_lifecycle_op_1202hn([op, "-d"]), op)

    def test_build_and_observers_are_not(self):
        """A 900s build under the lock would starve RunHub; `ps`/`logs` cannot race."""
        for op in ("build", "ps", "logs", "config", "images"):
            self.assertFalse(is_lifecycle_op_1202hn([op, "-q"]), op)

    def test_the_verb_is_found_past_global_flags(self):
        self.assertTrue(is_lifecycle_op_1202hn(
            ["docker", "compose", "-f", "docker-compose.yml", "up", "-d"]))
        self.assertFalse(is_lifecycle_op_1202hn(
            ["docker", "compose", "-f", "docker-compose.yml", "build"]))


class MutualExclusion(unittest.TestCase):
    def test_two_holders_of_one_project_do_not_overlap(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            overlaps, inside, lock = [], [], threading.Lock()

            def work():
                with compose_mutex_1202hn(d, "up"):
                    with lock:
                        inside.append(1)
                        if len(inside) > 1:
                            overlaps.append(1)
                    time.sleep(0.15)
                    with lock:
                        inside.pop()

            ts = [threading.Thread(target=work) for _ in range(4)]
            for t in ts:
                t.start()
            for t in ts:
                t.join(timeout=20)
            self.assertEqual(overlaps, [], "two compose lifecycle ops ran concurrently")

    def test_different_projects_are_independent(self):
        """Serializing across UNRELATED runs would make every generation wait on every other
        one on this machine, which has 119 containers up from other work."""
        import tempfile
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            started = threading.Event()
            done = threading.Event()

            def hold():
                with compose_mutex_1202hn(a, "up"):
                    started.set()
                    done.wait(timeout=5)

            t = threading.Thread(target=hold)
            t.start()
            self.assertTrue(started.wait(timeout=5))
            t0 = time.time()
            with compose_mutex_1202hn(b, "down"):
                pass
            self.assertLess(time.time() - t0, 2.0, "an unrelated project had to wait")
            done.set()
            t.join(timeout=5)

    def test_a_timeout_proceeds_loudly_rather_than_wedging(self):
        """#1201: a lock that can hang a run is worse than the race it prevents. The wait is
        bounded and the fallback is audible, never a silent pass-through."""
        import tempfile
        from multi_agent.runtime import compose_mutex as cm
        with tempfile.TemporaryDirectory() as d:
            said = []
            orig = cm.warn_once_1201
            cm.warn_once_1201 = lambda *a, **k: said.append(a)
            started, done = threading.Event(), threading.Event()

            def hold():
                with compose_mutex_1202hn(d, "up"):
                    started.set()
                    done.wait(timeout=10)

            t = threading.Thread(target=hold)
            t.start()
            try:
                self.assertTrue(started.wait(timeout=5))
                with compose_mutex_1202hn(d, "down", timeout_s=0.2):
                    pass
                self.assertTrue(said, "the bounded wait expired silently")
            finally:
                cm.warn_once_1201 = orig
                done.set()
                t.join(timeout=5)


if __name__ == "__main__":
    unittest.main()


class BothSpawnSitesTakeIt(unittest.TestCase):
    """A lock only one of the two racers takes is not a lock. Each site is driven for its own
    argv style — `("up", "-d")` from validation_runner, a full docker argv from RunHub."""

    def _record(self, module):
        from contextlib import nullcontext
        from multi_agent.runtime import compose_mutex as cm
        seen = []
        orig = cm.compose_mutex_1202hn

        def spy(cwd, op="", timeout_s=300.0):
            seen.append(str(op))
            return nullcontext(True)

        cm.compose_mutex_1202hn = spy
        return seen, (lambda: setattr(cm, "compose_mutex_1202hn", orig))

    def test_validation_runner(self):
        import subprocess
        import tempfile
        from multi_agent.runtime import validation_runner as vr
        seen, restore = self._record(vr)
        real = subprocess.run
        subprocess.run = lambda *a, **k: subprocess.CompletedProcess(a[0] if a else [], 0, "", "")
        try:
            with tempfile.TemporaryDirectory() as d:
                vr._compose(Path(d) / "docker-compose.yml", "up", "-d",
                            cwd=Path(d), timeout=5)
                self.assertTrue(seen, "the `up` spawn did not take the lock")
                seen.clear()
                vr._compose(Path(d) / "docker-compose.yml", "build", cwd=Path(d), timeout=5)
                self.assertEqual(seen, [], "`build` must not hold the lock for up to 900s")
        finally:
            subprocess.run = real
            restore()

    def test_runhub_default_runner(self):
        import subprocess
        import tempfile
        from multi_agent.runtime.hubs.runhub import compose as rc
        seen, restore = self._record(rc)
        real = subprocess.run
        subprocess.run = lambda *a, **k: subprocess.CompletedProcess(a[0] if a else [], 0, "", "")
        try:
            with tempfile.TemporaryDirectory() as d:
                rc._default_runner(["docker", "compose", "-f", "x.yml", "up", "-d",
                                    "--remove-orphans"], cwd=d, timeout=5)
                self.assertTrue(seen, "RunHub's spawn did not take the lock")
                seen.clear()
                rc._default_runner(["docker", "compose", "-f", "x.yml", "build"],
                                   cwd=d, timeout=5)
                self.assertEqual(seen, [])
        finally:
            subprocess.run = real
            restore()
