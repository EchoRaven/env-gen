r"""#826: a ticket allocator, because three collisions in one session is a namespace problem.

`#817` and `#820` were re-derived after a context break — the previous session had already shipped
both, `#820` down to the same number. `#822` and `#823` were simply taken. Each was found only
after the code and the write-up existed under the wrong number, and the rule *"check the log
first"* was written down after the first collision and failed twice more. **A check that lives in
a habit is not a check** — this session's own lesson about rules versus locations (#786/#793/#802).

★ **The first two versions of this script were wrong in the way this repo catalogues most often.**
Scanning all source for `#NNN` matched a CSS hex colour (`.empty { color: #999; }`) and a prose
example (`"Your invoice #4021 is ready"`), and reported the next free ticket as **4022**.
Tightening the regex chased the symptom: `#999` and a ticket number are the *same token*, and no
pattern separates them.

What does separate them is **where a number is CLAIMED** rather than referenced — two places, both
structured:

    EXPERIMENTS headings   `## 150. #820 — an unsatisfiable nav-link expectation`
    commit subjects        `#824/#825: renumber the new audits off a collision`

A number appearing only in a code comment is a *reference*; it does not claim the namespace.
"""
import os
import pathlib
import subprocess

import pytest


_TOOL = pathlib.Path(__file__).resolve().parents[2] / "tools" / "ticket.sh"


def _highest_existing_ticket() -> int:
    """The largest ticket number this repo already carries.

    #1000: the ceiling used to be the literal 1000, chosen when tickets sat in the 800s. The
    guard's PURPOSE — documented below as "v1 answered 4022" — is to catch a parser blowout,
    not to assert the project has fewer than a thousand fixes. It reached a thousand, the
    absolute bound went stale, and a correct allocation of 1001 turned two tests red.

    A relative bound keeps the intent and never expires: 4022 fails it forever, 1001 passes
    it the day #1000 lands.
    """
    import re as _re
    nums = []
    for _p in (pathlib.Path(__file__).resolve().parent).glob("*_[0-9]*.py"):
        # BOTH conventions: 463 files carry the number as a SUFFIX
        # (test_foo_1053.py) and 106 as a PREFIX (test_1064_foo.py). Matching only
        # the suffix made this scanner blind to a sixth of the numbered corpus, so
        # a run of prefix-named tickets could sit above the reported "highest" and
        # a correct allocation read as implausible.
        _m = (_re.search(r"_(\d{3,5})\.py$", _p.name)
              or _re.match(r"test_(\d{3,5})_", _p.name))
        if _m:
            nums.append(int(_m.group(1)))
    if not nums:
        return 0
    # A trailing number is not always a ticket. `test_kickoff_roadmap_validator_
    # adversarial_5000.py` counts CASES, and taking it as the highest ticket put the
    # bound at 5000 — so a correct allocation of 1060 read as "implausible" and this
    # guard failed on a filename rather than on a parser blowout, which is the only
    # thing it exists to catch.
    #
    # The ticket sequence is dense; an outlier is not. Take the highest number that
    # has a neighbour within 50 below it, which no gap in a real sequence exceeds and
    # no isolated round number can fake.
    nums.sort()
    top = nums[0]
    for _a, _b in zip(nums, nums[1:]):
        if _b - _a <= 50:
            top = _b
    return top
_ROOT = _TOOL.parent.parent


# #834: every no-arg call RESERVES, so a suite that exercises the allocator was appending live
# numbers to the repo's `.tickets` and pushing the next real allocation past them. A test with a
# side effect on a repo artifact makes that artifact untrustworthy — worse than having no test.
# The script honours TICKET_LEDGER for exactly this.
@pytest.fixture()
def ledger(tmp_path):
    return str(tmp_path / "tickets")


def _run(*args, ledger=None):
    env = dict(os.environ)
    env["TICKET_LEDGER"] = ledger or "/dev/null"
    return subprocess.run(["bash", str(_TOOL), *args],
                          capture_output=True, text=True, cwd=str(_ROOT), env=env)


def test_the_script_parses():
    assert subprocess.run(["bash", "-n", str(_TOOL)]).returncode == 0


def test_it_reports_a_plausible_next_number():
    """Non-vacuity with a ceiling: v1 answered 4022, which is the failure this guards."""
    out = _run().stdout.strip()
    assert out.isdigit(), out
    # #1000: bound RELATIVE to what the repo already carries, not to a literal ceiling. The
    # old `< 1000` was chosen when tickets sat in the 800s; the project reached 1000 and the
    # bound went stale, failing a correct allocation of 1001. The purpose stated above —
    # catching the v1 answer of 4022 — survives intact and now never expires.
    _top = _highest_existing_ticket()
    assert _top > 0, "no numbered tests found; this guard would be vacuous"
    assert _top < int(out) <= _top + 10, f"implausible next ticket: {out} (highest={_top})"


def _a_ticket_this_repo_actually_carries():
    """A number the repo demonstrably uses, discovered rather than remembered.

    #1202em: this test hardcoded ["817", "820", "822", "823"] -- "the four numbers that
    actually collided this session" -- and that session ended. Which numbers are claimed
    moves as files are added, renamed and removed: on the run that exposed this, 817 was
    reported FREE inside the suite and TAKEN a minute later, while 820 had gone the other
    way. A snapshot of someone else's session is not a fixture; it is a slow leak that
    spends a 12-minute suite run to tell you the repo changed.
    """
    import re
    for f in sorted((_ROOT / "agent" / "tests").glob("test_*_[0-9][0-9][0-9].py")):
        m = re.search(r"_(\d{3})\.py$", f.name)
        if m:
            return m.group(1)
    return None


def test_a_number_the_repo_carries_is_reported_taken():
    """The behaviour under test -- 'an id already in use must be refused' -- asserted
    against a number this checkout really uses."""
    n = _a_ticket_this_repo_actually_carries()
    if not n:
        pytest.skip("no numbered ticket tests in this checkout")
    r = _run(n)
    assert r.returncode == 1, f"#{n} is used by agent/tests but was not refused: {r.stdout}"
    assert "TAKEN" in r.stdout


@pytest.mark.parametrize("n,what", [("999", "a CSS hex colour"),
                                    ("4021", "a prose invoice number")])
def test_the_lookalikes_are_free(n, what):
    """★ Both were reported TAKEN by earlier versions. They are not tickets; they are text that
    looks like one, and only the claim-site scan tells them apart."""
    r = _run(n)
    assert r.returncode == 0, f"{what} still reads as a ticket: {r.stdout}"
    assert "FREE" in r.stdout


def test_allocation_reserves_so_two_callers_cannot_collide(ledger):
    """★ The contract CHANGED under this test and the test was pinning the old one.

    #829 extended the allocator after three further collisions: it now scans test filenames and
    the working tree, and — the part that matters here — **allocation APPENDS to `.tickets`**, so
    a number is taken the moment it is handed out. The original assertion (*"the number it hands
    out is one it will not then call taken"*) encoded the pure-read semantics and became false by
    design. That is #782's shape in a test I wrote one turn earlier.

    The property worth guarding is the one reservation exists for: two callers seconds apart must
    not get the same number. That is what produced three of the four collisions."""
    a = _run(ledger=ledger).stdout.strip()
    b = _run(ledger=ledger).stdout.strip()
    assert a.isdigit() and b.isdigit()
    assert a != b, f"two consecutive allocations returned {a} — reservation is not working"
    assert int(b) > int(a)


def test_an_allocated_number_reads_as_taken(ledger):
    """The other half of the same contract: having handed a number out, the allocator must not
    then tell a second caller it is free."""
    n = _run(ledger=ledger).stdout.strip()
    assert _run(n, ledger=ledger).returncode == 1


def test_it_says_where_a_taken_number_was_claimed():
    """'Taken' without a location sends the reader looking — #798's rule."""
    out = _run("820").stdout
    assert "claimed in" in out
    assert "EXPERIMENTS" in out or "#820" in out


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
