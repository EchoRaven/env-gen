r"""#847: the allocator's high-water mark had no upper sanity bound.

`tools/ticket.sh` allocates `max(claimed) + 1`, and `max` is maximally sensitive to one bad claim.
#826's own header records this happening — a prose example `"Your invoice #4021 is ready"` made it
report 4022 — and the fix was to NARROW THE SOURCES. That closes the shapes already seen. It does
not close prose inside the two sources that remain, both of which are scanned as whole lines:

    ## 172. #848 — a task body rendering "Your invoice #4021 is ready"
    $ tools/ticket.sh  ->  4022          <- reproduced against the real document

And the damage is PERMANENT: allocating appends to `.tickets`, and `.tickets` is itself a scanned
source (#829's reservation fix). One bad read poisons every later allocation. Silently — the tool
prints a bare number, so 4022 is indistinguishable from 848 at the call site.

The bound is measured rather than guessed, which is this session's standing correction for caps:
767 claims over 1..847, largest legitimate gap **38** (427 -> 465), nothing above 50. The poison
jump is 3174. 100 sits an order of magnitude from both.

★ Why warn-and-skip and not refuse. A refusal wedges allocation on a false positive, and #789
settled that trade: the fail-open was correct there, only its silence was the defect. So this
speaks, names the outlier, and prints where it was claimed — and it speaks on **stderr**, because
the caller is `n=$(tools/ticket.sh)` and an allocator that prints prose into its own output is a
worse bug than the one being fixed.

Every case drives the real script through `TICKET_LEDGER`, so the suite never touches the repo's
`.tickets` (#834 — a test with a side effect on a repo artifact makes the artifact untrustworthy).
"""
import pathlib
import re
import subprocess

import pytest


_ROOT = pathlib.Path(__file__).resolve().parents[2]
_SH = _ROOT / "tools/ticket.sh"


def _run(tmp_path, ledger_lines, arg=None):
    led = tmp_path / "tickets"
    led.write_text("".join(f"#{n} reserved x\n" for n in ledger_lines), encoding="utf-8")
    cmd = ["bash", str(_SH)] + ([str(arg)] if arg is not None else [])
    p = subprocess.run(cmd, cwd=_ROOT, capture_output=True, text=True,
                       env={"PATH": "/usr/bin:/bin", "HOME": str(tmp_path),
                            "TICKET_LEDGER": str(led)})
    return p


def test_the_script_is_where_we_think_it_is():
    """Non-vacuity: every case below shells out, and a moved script would make them all pass on a
    non-zero exit that nobody asserted against."""
    assert _SH.exists(), _SH


def test_a_clean_allocation_still_returns_a_bare_number(tmp_path):
    """Non-regression, and the shape the caller depends on."""
    p = _run(tmp_path, [846])
    assert p.returncode == 0, p.stderr
    assert p.stdout.strip().isdigit(), repr(p.stdout)
    # #1000: relative to what the REPO carries. `_run` seeds a synthetic ledger in tmp_path
    # but invokes the allocator with cwd=_ROOT, so the answer is correctly driven by the real
    # ticket set — 1001 today. The old `< 1000` was a literal ceiling chosen when tickets sat
    # in the 800s; it went stale the day #1000 landed and failed a correct allocation. The
    # guard's purpose (the sibling test records v1 answering 4022) survives and never expires.
    # A trailing number is not always a ticket: `test_kickoff_roadmap_validator_
    # adversarial_5000.py` counts CASES, and max() over the filenames put the bound at
    # 5000 — so a correct allocation read as implausible and this guard failed on a
    # filename rather than on the parser blowout it exists to catch. The ticket
    # sequence is dense and an outlier is not: take the highest number with a
    # neighbour within 50 below it.
    _nums = []
    for _p in pathlib.Path(__file__).resolve().parent.glob("*_[0-9]*.py"):
        # BOTH conventions — see the note in test_ticket_allocator_826: 463 files
        # carry the number as a suffix, 106 as a prefix.
        _m = (re.search(r"_(\d{3,5})\.py$", _p.name)
              or re.match(r"test_(\d{3,5})_", _p.name))
        if _m:
            _nums.append(int(_m.group(1)))
    _nums.sort()
    _top = _nums[0] if _nums else 0
    for _a, _b in zip(_nums, _nums[1:]):
        if _b - _a <= 50:
            _top = _b
    assert _top > 0, "no numbered tests found; this guard would be vacuous"
    assert _top < int(p.stdout) <= _top + 10, f"{p.stdout} (highest={_top})"


def test_a_quoted_number_does_not_become_the_high_water_mark(tmp_path):
    """The defect. 4021 is in a scanned source; the next ticket must not be 4022."""
    clean = int(_run(tmp_path, [846]).stdout)
    poisoned = _run(tmp_path, [846, 4021])
    assert poisoned.returncode == 0, poisoned.stderr
    assert int(poisoned.stdout) == clean, poisoned.stdout


def test_the_outlier_is_named_on_stderr_not_stdout(tmp_path):
    """`n=$(tools/ticket.sh)` must still capture only the number."""
    p = _run(tmp_path, [846, 4021])
    assert p.stdout.strip().isdigit(), repr(p.stdout)
    assert "4021" in p.stderr and "IGNORING" in p.stderr, p.stderr


def test_the_warning_says_where_it_came_from(tmp_path):
    """An operator cannot act on 'ignored a number'. The override needs a location, and a real
    ticket that legitimately jumped needs to be distinguishable from a quoted figure."""
    err = _run(tmp_path, [846, 4021]).stderr
    assert "Claimed at:" in err
    assert "_GAP_847" in err, "the override must be named or the guard is a dead end"


def test_a_nearby_number_is_still_accepted(tmp_path):
    """★ Non-vacuity for the guard itself: this is a GAP test, not 'always ignore the maximum'.
    A claim inside the threshold must win, or the allocator would hand out a taken number the
    moment the namespace grew normally."""
    near = int(_run(tmp_path, [846]).stdout) + 40      # inside _GAP_847, above every real claim
    p = _run(tmp_path, [846, near])
    assert int(p.stdout) == near + 1, (p.stdout, p.stderr)
    # The assertion is that THIS claim is not ignored. A bare "IGNORING" not in
    # stderr also fails on an unrelated outlier the repo really carries —
    # `test_kickoff_roadmap_validator_adversarial_5000.py`, whose trailing number
    # counts CASES — which ticket.sh correctly drops ("#5000, 3900 higher, and the
    # largest real gap in this namespace is 38"). That is the guard working, not a
    # defect in the allocation under test. `near` also appears in the notice as the
    # REFERENCE POINT ("claims above #1100"), so only the list after "Claimed at:"
    # answers whether THIS claim was dropped.
    _ignored = p.stderr.split("Claimed at:", 1)[-1] if "Claimed at:" in p.stderr else ""
    assert str(near) not in _ignored, p.stderr


def test_two_stacked_outliers_are_both_dropped(tmp_path):
    """A poisoned ledger accumulates, so one drop is not enough.

    ★ This case passed against the FIRST cut and still missed the real defect — see below. The
    outliers here are 4979 apart, and the descending walk handled that fine."""
    clean = int(_run(tmp_path, [846]).stdout)
    p = _run(tmp_path, [846, 4021, 9000])
    assert int(p.stdout) == clean, p.stdout
    assert "9000" in p.stderr and "4021" in p.stderr


def test_adjacent_outliers_are_both_unreachable(tmp_path):
    """#847b, the case that broke the first cut — and it is the GENERAL one, not a corner.

    The original guard descended from `max` while each step was more than the threshold above the
    claim below it. Two outliers **1 apart** stop that descent immediately. And adjacency is what
    poisoning always produces: the ledger reserves N, the next allocation reserves N+1, so from
    the second bad allocation onward the outliers are adjacent forever. The descending guard was
    therefore guaranteed to fail against exactly the scenario it was written for.

    Ascending from the bottom of a dense namespace has no such hole."""
    clean = int(_run(tmp_path, [846]).stdout)
    p = _run(tmp_path, [846, 4021, 4022])
    assert int(p.stdout) == clean, (p.stdout, p.stderr)
    assert "4021" in p.stderr


def test_a_long_adjacent_poison_run_is_still_unreachable(tmp_path):
    """The degenerate end of the same shape: a ledger poisoned and then used for a while."""
    clean = int(_run(tmp_path, [846]).stdout)
    p = _run(tmp_path, [846] + list(range(4021, 4041)))
    assert int(p.stdout) == clean, p.stdout


def test_a_heading_inside_a_code_fence_is_not_a_claim():
    """#847c, asserted against the SHIPPED document rather than a fixture.

    EXPERIMENTS item 172 documents the poison by showing it, and the shown line begins with `## `.
    So the write-up about the bug reintroduced the bug — `#4021` became a live claim and #826's
    `test_the_lookalikes_are_free[4021]` went red. Any document explaining this tool has the shape.

    Reading the real file is the point: a fixture would prove the awk works, not that the repo is
    currently clean, and it is the repo the allocator runs against."""
    doc = _ROOT / "EXPERIMENTS_PENDING_2026-08-13.md"
    src = doc.read_text(encoding="utf-8")
    assert '\n## 172. #848 ' in src, "non-vacuity: the fenced lookalike must still be in the doc"
    p = subprocess.run(["bash", str(_SH), "4021"], cwd=_ROOT, capture_output=True, text=True)
    assert p.returncode == 0, p.stdout


def test_no_heading_declares_a_lookalike():
    """The other half of #847c: a fence protects a quotation, but a real heading is a declaration
    site and a lookalike in one is a defect in the DOCUMENT. Item 172's prose heading originally
    read `... could hand out #4022` and had to be reworded."""
    import re
    docs = sorted(_ROOT.glob("EXPERIMENTS_PENDING_*.md"))
    assert docs, "non-vacuity"
    bad = []
    for d in docs:
        fenced = False
        for ln, line in enumerate(d.read_text(encoding="utf-8").splitlines(), 1):
            if line.startswith("```"):
                fenced = not fenced
            elif not fenced and re.match(r"^## [0-9]", line):
                bad += [f"{d.name}:{ln} {line}" for n in re.findall(r"#([0-9]{4})", line)
                        if int(n) > 2000]
    assert not bad, "heading declares a number that is not a ticket:\n" + "\n".join(bad)


def test_the_check_branch_is_untouched(tmp_path):
    """Blast radius. Asking whether a number is free is conservative by nature — answering TAKEN
    for a quoted number is harmless, and narrowing it here would be scope the defect never had."""
    assert _run(tmp_path, [846, 4021], arg=4021).returncode == 1
    assert _run(tmp_path, [846], arg=4021).returncode == 0


def test_an_empty_ledger_does_not_divide_by_a_missing_neighbour(tmp_path):
    """The walk indexes `_all[i-1]`; the degenerate namespace is where that reads off the end."""
    p = _run(tmp_path, [])
    assert p.returncode == 0, p.stderr
    assert p.stdout.strip().isdigit(), repr(p.stdout)


def test_the_measured_gap_is_recorded_beside_the_threshold():
    """The threshold is only defensible with the measurement next to it; a bare `100` is the kind
    of number that four correct caps sat beside in #816/#817."""
    src = _SH.read_text(encoding="utf-8")
    i = src.index("_GAP_847=")
    assert "largest\n# legitimate gap of 38" in src or "gap of 38" in src, "measurement missing"
    assert "3174" in src[:i], "the poison magnitude is what makes 100 defensible"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
