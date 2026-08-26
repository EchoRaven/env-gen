"""#1118: the ticket allocator could not see 156 of the repo's own regression tests.

`tools/ticket.sh` gathers claimed numbers from several sources; one of them scans
`agent/tests` for ticket numbers in filenames. That scan matched only
`test_<name>_<NNNN>.py`. The repo uses both orders — 463 files put the number last,
156 put it first (`test_1117_the_reason_it_was_stored.py`) — so a third of its own
numbered tests were invisible.

That is harmless while a ticket is also named in a commit subject, which is the source
that normally carries it. It stops being harmless in exactly the window the filename
scan exists for: a ticket whose test file exists but whose commit has not landed yet is
claimed by nothing else. With `test_1117_*.py` on disk and uncommitted, the tool
answered 1117 — a number already in use.

#1118b (same file, found while testing the above): bash reads a leading-zero literal as
OCTAL, so a claim like 0902 aborted the arithmetic, left `next` unbound, and made the
script print NOTHING on stdout while exiting 0. No claim in this repo has a leading zero
today — 0 across filenames, commit subjects and the ledger — so it was unreachable; it
is one token, and the failure it prevents is silent.
"""
import pathlib
import shutil
import subprocess

import pytest

TOOL = pathlib.Path(__file__).resolve().parents[2] / "tools" / "ticket.sh"


@pytest.fixture
def repo(tmp_path):
    """A minimal layout the tool can anchor to: it cd's to `dirname $0`/..

    Its own ledger lives here too, so an allocation reserves nothing in the real repo.
    """
    (tmp_path / "tools").mkdir()
    (tmp_path / "agent" / "tests").mkdir(parents=True)
    shutil.copy(TOOL, tmp_path / "tools" / "ticket.sh")
    return tmp_path


def _ask(repo, *args):
    p = subprocess.run(["bash", str(repo / "tools" / "ticket.sh"), *args],
                       capture_output=True, text=True, timeout=60)
    assert p.returncode in (0, 1), p.stderr
    return p.stdout.strip()


def test_a_number_first_filename_is_claimed(repo):
    """The fix. `test_902_something.py` used to read as an unused number."""
    (repo / "agent" / "tests" / "test_902_something.py").touch()
    assert "TAKEN" in _ask(repo, "902"), (
        "a ticket whose test file already exists was offered as free"
    )


def test_a_number_last_filename_is_still_claimed(repo):
    """The original behaviour must survive the fix."""
    (repo / "agent" / "tests" / "test_something_901.py").touch()
    assert "TAKEN" in _ask(repo, "901")


def test_both_orders_at_once(repo):
    t = repo / "agent" / "tests"
    (t / "test_something_901.py").touch()
    (t / "test_902_something.py").touch()
    assert "TAKEN" in _ask(repo, "901")
    assert "TAKEN" in _ask(repo, "902")


def test_an_unused_number_is_still_free(repo):
    """#1118 must not make everything look claimed."""
    (repo / "agent" / "tests" / "test_902_something.py").touch()
    assert "FREE" in _ask(repo, "903")


def test_the_next_number_clears_a_number_first_ticket(repo):
    """The allocation path, not just the query path."""
    (repo / "agent" / "tests" / "test_902_something.py").touch()
    out = _ask(repo)
    assert out.isdigit(), "allocator produced no number: %r" % out
    assert int(out) > 902, (
        "the allocator offered %s with #902 already on disk" % out
    )


def test_a_leading_zero_claim_does_not_silence_the_allocator(repo):
    """#1118b: `0902` used to abort the arithmetic and print nothing, exit 0."""
    (repo / "agent" / "tests" / "test_0902_something.py").touch()
    out = _ask(repo)
    assert out.isdigit(), (
        "a leading-zero claim produced an EMPTY ticket number — a caller doing "
        "n=$(tools/ticket.sh) would have taken that as success: %r" % out
    )
    assert int(out) > 902


@pytest.mark.parametrize("name", [
    "test_notes.py",                 # no number at all
    "test_1117.py",                  # number but no descriptive half
    "README.md",
])
def test_unnumbered_files_claim_nothing(repo, name):
    (repo / "agent" / "tests" / name).touch()
    assert "FREE" in _ask(repo, "903")
