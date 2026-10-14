"""#1203jp: the disk-reclaim keep set scanned agent/ but not scripts/.

`scripts/reclaim_generated.sh` protects "every run the SOURCE CITES as evidence" — delete a
cited run and the comment that cites it points at nothing. The first version scanned
`agent/env_generator agent/tests` only, and the single most load-bearing citation is NOT in
either: `scripts/verify_shipped_fixes.py --self-test` runs against `generated/tiktok-web-r140`
and exits 2 without it, so deleting r140 disarms the check that catches a fix verifier
confirming on a pre-fix run.

On the day this was found the preview was identical with and without `scripts` (100 kept /
129 removed either way) because agent/ happens to name r140 too. That is the point: the
protection held by luck, and a test that only re-ran the live tree would have been green.
So the fixture below builds a run cited ONLY from scripts/, which is the input the guard
exists for, and the negative control removes `scripts` from CITE_ROOTS to prove the root is
what saves it.
"""
import os
import re
import shutil
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
SCRIPT = os.path.join(REPO, "scripts", "reclaim_generated.sh")


def _default_cite_roots(src):
    """The DEFAULT value of CITE_ROOTS, not any mention of the word in prose.

    #943/#1203jp: anchored on the assignment so the comment block above it (which names
    scripts/verify_shipped_fixes.py several times) cannot satisfy this on its own.
    """
    m = re.search(r'^CITE_ROOTS=\$\{CITE_ROOTS:-"([^"]*)"\}', src, re.M)
    assert m, "no CITE_ROOTS default assignment in reclaim_generated.sh"
    return m.group(1).split()


def test_scripts_is_a_default_citation_root():
    src = open(SCRIPT, encoding="utf-8").read()
    roots = _default_cite_roots(src)
    assert "scripts" in roots, (
        "scripts/ is not scanned for run citations, so `verify_shipped_fixes.py --self-test`'s "
        "tiktok-web-r140 is protected only if some other root happens to name it: %r" % (roots,)
    )
    assert "agent/env_generator" in roots and "agent/tests" in roots, roots


def _fixture(tmp_path, cite_in):
    """A miniature repo: 3 runs, one of them cited from `cite_in`."""
    for d in ("scripts", "agent/env_generator", "agent/tests", "generated"):
        os.makedirs(os.path.join(str(tmp_path), d), exist_ok=True)
    for run in ("faketok-web-r1", "faketok-web-r2", "faketok-web-r999"):
        os.makedirs(os.path.join(str(tmp_path), "generated", run), exist_ok=True)
        open(os.path.join(str(tmp_path), "generated", run, "x.txt"), "w").write("x")
    open(os.path.join(str(tmp_path), cite_in, "citer.py"), "w").write(
        "# the evidence for this lives in generated/faketok-web-r999\n"
    )
    shutil.copy(SCRIPT, os.path.join(str(tmp_path), "scripts", "reclaim_generated.sh"))
    return os.path.join(str(tmp_path), "scripts", "reclaim_generated.sh")


def _preview(script, **env):
    e = dict(os.environ)
    e.update({"KEEP_N": "1"})
    e.update(env)
    p = subprocess.run(["bash", script], capture_output=True, text=True, env=e, timeout=120)
    assert p.returncode == 0, (p.returncode, p.stdout, p.stderr)
    return p.stdout


def test_a_run_cited_only_from_scripts_is_kept(tmp_path):
    script = _fixture(tmp_path, "scripts")
    out = _preview(script)
    assert "faketok-web-r999" not in out, (
        "a run cited only from scripts/ is on the delete list:\n%s" % out
    )
    # KEEP_N=1 keeps the newest alone, so the OTHER old run must still be removable --
    # otherwise this test would pass against a script that keeps everything.
    assert "faketok-web-r1" in out, "nothing was removable; the fixture proves nothing:\n%s" % out


def test_dropping_the_scripts_root_is_what_loses_it(tmp_path):
    """Negative control: the keep is caused by the root, not by something else in the script."""
    script = _fixture(tmp_path, "scripts")
    out = _preview(script, CITE_ROOTS="agent/env_generator agent/tests")
    assert "faketok-web-r999" in out, (
        "removing scripts/ from CITE_ROOTS did NOT expose the cited run, so "
        "test_a_run_cited_only_from_scripts_is_kept cannot be attributed to the root:\n%s" % out
    )


def test_a_run_cited_from_agent_is_still_kept(tmp_path):
    """The root that was already there must not have been dropped by the rewrite."""
    script = _fixture(tmp_path, "agent/env_generator")
    out = _preview(script)
    assert "faketok-web-r999" not in out, out


def test_the_preview_reports_how_many_runs_citation_saved(tmp_path):
    """A protection whose size is invisible is one nobody notices losing (#1203jp)."""
    script = _fixture(tmp_path, "scripts")
    out = _preview(script)
    m = re.search(r"^kept by citation: (\d+) run\(s\) named in (.+)$", out, re.M)
    assert m, "the preview does not say how many runs were kept by citation:\n%s" % out
    assert int(m.group(1)) == 1, (m.group(1), out)
    assert "scripts" in m.group(2).split(), m.group(2)
