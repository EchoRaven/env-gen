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
import pathlib
import subprocess

import pytest


_TOOL = pathlib.Path(__file__).resolve().parents[2] / "tools" / "ticket.sh"
_ROOT = _TOOL.parent.parent


def _run(*args):
    return subprocess.run(["bash", str(_TOOL), *args],
                          capture_output=True, text=True, cwd=str(_ROOT))


def test_the_script_parses():
    assert subprocess.run(["bash", "-n", str(_TOOL)]).returncode == 0


def test_it_reports_a_plausible_next_number():
    """Non-vacuity with a ceiling: v1 answered 4022, which is the failure this guards."""
    out = _run().stdout.strip()
    assert out.isdigit(), out
    assert 800 < int(out) < 1000, f"implausible next ticket: {out}"


@pytest.mark.parametrize("n", ["817", "820", "822", "823"])
def test_the_real_collisions_are_reported_taken(n):
    """The four numbers that actually collided this session."""
    r = _run(n)
    assert r.returncode == 1, r.stdout
    assert "TAKEN" in r.stdout


@pytest.mark.parametrize("n,what", [("999", "a CSS hex colour"),
                                    ("4021", "a prose invoice number")])
def test_the_lookalikes_are_free(n, what):
    """★ Both were reported TAKEN by earlier versions. They are not tickets; they are text that
    looks like one, and only the claim-site scan tells them apart."""
    r = _run(n)
    assert r.returncode == 0, f"{what} still reads as a ticket: {r.stdout}"
    assert "FREE" in r.stdout


def test_the_next_number_is_itself_free():
    """The allocator must not hand out something it would then call taken."""
    nxt = _run().stdout.strip()
    assert _run(nxt).returncode == 0


def test_it_says_where_a_taken_number_was_claimed():
    """'Taken' without a location sends the reader looking — #798's rule."""
    out = _run("820").stdout
    assert "claimed in" in out
    assert "EXPERIMENTS" in out or "#820" in out


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
