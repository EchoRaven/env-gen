r"""#1202av: when this run has no running container, say WHY, not just that it has none.

`docker compose up -d` without `--wait` returns rc=0 as soon as the start is issued, so a
container that starts and dies immediately still reports a successful bring-up. r32 holds
both halves and never joins them:

    20:10 – 00:15   66x  compose spawn: docker up -d --remove-orphans -> rc=0
    20:05 – 00:29  179x  #962/#1130 ... This run's `database` container is NOT RUNNING

Nowhere in that log is an exit, a restart, or an unhealthy line — because nothing ever
looked at a stopped container. Four and a half hours of "NOT RUNNING" with the reason one
command away.
"""
import sys
import types
import unittest
from pathlib import Path
from unittest import mock

THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS_DIR.parent / "env_generator" / "llm_generator"))

from multi_agent.runtime import container_runtime as cr  # noqa: E402

_WANT = "/runs/r32/docker/docker-compose.yml"


def _cp(stdout=""):
    return types.SimpleNamespace(stdout=stdout, stderr="", returncode=0)


class WhyTheContainerIsGoneTests(unittest.TestCase):
    def test_an_exited_container_of_this_run_explains_itself(self):
        def _run(argv, **kw):
            if argv[1] == "ps":
                return _cp("abc123def456\n")
            if argv[1] == "inspect":
                return _cp("%s|exited|1" % _WANT)
            if argv[1] == "logs":
                return _cp("FATAL: data directory has wrong ownership")
            return _cp()

        with mock.patch.object(cr.subprocess, "run", _run):
            why = cr._exited_container_reason_1202av("docker", "database", _WANT, 30)

        self.assertIn("abc123def456"[:12], why)
        self.assertIn("exit code 1", why)
        self.assertIn("wrong ownership", why)

    def test_another_run_s_exited_container_is_not_ours(self):
        """The label check is the whole point: #962 exists because names collide."""
        def _run(argv, **kw):
            if argv[1] == "ps":
                return _cp("abc123def456\n")
            if argv[1] == "inspect":
                return _cp("/runs/r31/docker/docker-compose.yml|exited|1")
            return _cp()

        with mock.patch.object(cr.subprocess, "run", _run):
            self.assertEqual(
                cr._exited_container_reason_1202av("docker", "database", _WANT, 30), "")

    def test_a_running_container_is_not_a_reason(self):
        def _run(argv, **kw):
            if argv[1] == "ps":
                return _cp("abc123def456\n")
            if argv[1] == "inspect":
                return _cp("%s|running|0" % _WANT)
            return _cp()

        with mock.patch.object(cr.subprocess, "run", _run):
            self.assertEqual(
                cr._exited_container_reason_1202av("docker", "database", _WANT, 30), "")

    def test_it_never_raises(self):
        """Diagnostics must not become the failure they were added to explain."""
        def _boom(*a, **k):
            raise OSError("no docker here")

        with mock.patch.object(cr.subprocess, "run", _boom):
            self.assertEqual(
                cr._exited_container_reason_1202av("docker", "database", _WANT, 30), "")


    def test_it_finds_a_container_past_the_first_dozen(self):
        """The bug real data caught the moment the unit tests all passed.

        The first version scanned `ps -a --filter name=<service>` and looked at the first
        12 ids. This machine has 20 containers matching `name=backend`, and the one being
        asked about was 18th — so the diagnostic returned "" in exactly the many-runs case
        #962/#1130 exists for. It now asks the daemon for OUR container by label, and the
        name scan that remains as the multi-file-compose fallback is uncapped.
        """
        others = ["other%02d" % n for n in range(19)]

        def _run(argv, **kw):
            if argv[1] == "ps":
                if any(a.startswith("label=") for a in argv):
                    return _cp("")          # e.g. a comma-joined multi-file config_files
                return _cp("\n".join(others + ["theone"]) + "\n")
            if argv[1] == "inspect":
                cid = argv[2]
                if cid == "theone":
                    return _cp("%s|exited|3" % _WANT)
                return _cp("/runs/elsewhere/docker-compose.yml|exited|1")
            if argv[1] == "logs":
                return _cp("could not translate host name \"database\"")
            return _cp()

        with mock.patch.object(cr.subprocess, "run", _run):
            why = cr._exited_container_reason_1202av("docker", "backend", _WANT, 30)

        self.assertIn("exit code 3", why)
        self.assertIn("database", why)

    def test_the_label_filter_is_asked_first(self):
        """One question to the daemon beats paging every container that shares a name."""
        seen = []

        def _run(argv, **kw):
            seen.append(argv)
            if argv[1] == "ps":
                return _cp("abc123def456\n")
            if argv[1] == "inspect":
                return _cp("%s|exited|1" % _WANT)
            return _cp()

        with mock.patch.object(cr.subprocess, "run", _run):
            cr._exited_container_reason_1202av("docker", "backend", _WANT, 30)

        first_ps = next(a for a in seen if a[1] == "ps")
        self.assertTrue(
            any(a == "label=com.docker.compose.project.config_files=%s" % _WANT
                for a in first_ps),
            "the first question to the daemon does not narrow by label")


if __name__ == "__main__":
    unittest.main()
