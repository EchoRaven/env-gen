r"""#1203jb: the id allocator could not see any id containing a digit.

`scripts/next_ticket.sh` exists because picking an id by eye collided twice, and its
header's own lesson is that each collision came from "checking ONE representation instead
of the fact". It then matched `${PREFIX}[a-z]{1,3}`, so a third representation went
unseen: every id with a DIGIT in it. Widening the scan surfaced 96 id-shaped tokens in
the 1203 range alone — about a third of it — that `--all` and the "in use" count had
been reporting as nonexistent.

Nothing collided on its own, because the GENERATOR's sequence is letters-only
(`itertools.product(ascii_lowercase)`) and can never re-issue `j0`. The harm is the
answer a human gets: this script is what a session consults before claiming an id by
hand, and it said "j0 is free" about an id carrying 16 code references and 3 test files.
Same shape as #1118 on the other allocator (`tools/ticket.sh`), which could not see 156
of the repo's own test files.

★ The scan is widened; the ALLOCATION sequence is untouched. `[a-z][a-z0-9]{0,2}` must
still start with a letter — `${PREFIX}` followed by digits is just a longer number, and
claiming it would re-introduce #826's original bug of reading `#999` as a ticket.
"""
import pathlib
import shutil
import subprocess

import pytest

_SCRIPT = pathlib.Path(__file__).resolve().parents[2] / "scripts" / "next_ticket.sh"


@pytest.fixture
def repo(tmp_path):
    """A minimal tree the script can anchor to: it cd's to `dirname $0`/.."""
    (tmp_path / "scripts").mkdir()
    (tmp_path / "agent" / "tests").mkdir(parents=True)
    shutil.copy(_SCRIPT, tmp_path / "scripts" / "next_ticket.sh")
    return tmp_path


def _ask(repo, *args, prefix="1203"):
    p = subprocess.run(["bash", str(repo / "scripts" / "next_ticket.sh"), *args],
                       capture_output=True, text=True, timeout=120,
                       env={"PATH": "/usr/bin:/bin:/usr/local/bin",
                            "TICKET_PREFIX": prefix})
    assert p.returncode == 0, p.stderr
    return p.stdout


def _plant(repo, body, name="mod.py"):
    (repo / "agent" / name).write_text(body, encoding="utf-8")


def test_an_id_with_a_digit_is_reported_as_in_use(repo):
    """★ THE TICKET. `#1203j0` is claimed by a comment; `--all` must say so."""
    _plant(repo, "x = 1  # #1203j0: a real claim\n")
    ids = _ask(repo, "--all").split()
    assert "j0" in ids, "the allocator still cannot see an id containing a digit: %s" % ids


def test_it_never_offers_an_id_that_is_in_use(repo):
    """The property that matters, asked directly rather than through the id's spelling."""
    _plant(repo, "# #1203ja #1203jb #1203j0 #1203j1\n")
    ids = set(_ask(repo, "--all").split())
    nxt = [l for l in _ask(repo).splitlines() if l.startswith("next")][0]
    offered = nxt.split("#1203")[1].strip()
    assert offered not in ids, "offered %r, which is already in use" % offered


def test_a_number_is_not_a_claim(repo):
    """#826's original bug: `#999` and a ticket id are the same token. The suffix must
    start with a LETTER, so a longer number claims nothing."""
    _plant(repo, "# invoice #1203456 and colour #120399\n")
    ids = _ask(repo, "--all").split()
    assert not any(i and i[0].isdigit() for i in ids), \
        "a digit-leading token was claimed as an id: %s" % ids


def test_highest_is_an_id_the_generator_can_issue(repo):
    """Reporting `highest = j2` beside `next = ja` would be a lie about the ordering: the
    generator issues `ja` AFTER `j`, while ASCII puts `j0` before `ja`. So the headline
    ranks only the letters-only ids, and digit-bearing ones are listed apart."""
    _plant(repo, "# #1203j #1203j2\n")
    out = _ask(repo)
    hi = [l for l in out.splitlines() if l.startswith("in use")][0]
    assert "#1203j" in hi and "#1203j2" not in hi, \
        "the headline ranked a digit-bearing id: %s" % hi
    assert "also" in out, "the digit-bearing ids are not reported at all"


def test_the_digit_ids_are_listed_separately(repo):
    """They are in use and must be visible, just not ranked with the issuable ones."""
    _plant(repo, "# #1203aa #1203b7\n")
    out = _ask(repo)
    also = [l for l in out.splitlines() if l.strip().startswith(("also", "not issuable"))]
    assert also and "b7" in " ".join(also), "b7 is not surfaced: %r" % out


def test_a_digit_id_is_not_misread_as_its_letter_prefix(repo):
    """★ ONE token, TWO wrong answers — and the half of the script the other tests do not
    reach. `grep -ohE "1203[a-z]{1,3}"` run over the text `#1203j0` emits `1203j`: the
    narrow scan both loses `j0` AND claims `j`, an id nobody took. The second error is the
    one that reaches allocation, because `next` is computed from its own scan: with `j`
    believed taken the generator starts after it and `a`..`j` are silently burned.

    Asserted through the published behaviour rather than the regex, so it holds whichever
    half is narrowed: `j0` is the only claim in this tree, therefore nothing letters-only
    is claimed and allocation must begin at the start of the sequence.
    """
    _plant(repo, "y = 2  # #1203j0: the only claim in this tree\n")
    ids = _ask(repo, "--all").split()
    assert "j0" in ids, "the digit id is still invisible: %s" % ids
    assert "j" not in ids, "`j` was claimed by nobody — it is `j0` misread: %s" % ids
    nxt = [l for l in _ask(repo).splitlines() if l.startswith("next")][0]
    assert nxt.split("#1203")[1].strip() == "a", (
        "allocation skipped ahead as though a letter id were taken (%s) — the `next` scan "
        "is reading `j0` as `j`" % nxt)
