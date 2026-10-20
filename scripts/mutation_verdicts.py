"""Which mutations are currently NOT CAUGHT and do not say why.

    python scripts/mutation_verdicts.py scripts/mutations/*.json
    python scripts/mutation_verdicts.py --touched            # specs whose target file is dirty vs HEAD~1

`mutation_census.py --strict` verifies that every anchor still appears EXACTLY ONCE, which
catches the failure where a later patch rewrites the line a spec anchors on and the spec
quietly stops testing anything. It does NOT record verdicts. So a mutation can sit MISSED,
with no annotation and no alarm, for as long as nobody re-runs it by hand -- which is how
five of them survived to 2026-10-20, found only by re-running 65 specs during a session
close.

A MISSED is not automatically a defect. Three of them are legitimate and say so in the
label, in the vocabulary the census already uses:

    SUPERSEDED        another spec now owns this property
    EXPECTED-MISSED   a deliberately null mutation, or one whose owner is another file
    NOT RUNNABLE      the branch cannot be driven (and the comment says why)
    BAD-ANCHOR        kept as a record of an anchor that never matched

What this reports is the REST: a mutation that is not caught and offers no reason. Each one
is either a real coverage hole or an annotation somebody forgot to write.
"""
import glob
import json
import os
import re
import subprocess
import sys

# ENUMERATED FROM THE SPECS, not guessed. The first draft of this list omitted CARRIED and
# promptly reported `mut_kf.json`'s carried mutation as unexplained -- the same over-narrow
# vocabulary mistake this file exists to catch, made by this file. Counts when derived
# (2026-10-20, over scripts/mutations/*.json): EXPECTED-MISSED 20 specs, SUPERSEDED 16,
# NOT RUNNABLE 3, "null mutation" 3, BAD-ANCHOR 2, CARRIED 2.
ANNOTATIONS = ("SUPERSEDED", "EXPECTED-MISSED", "NOT RUNNABLE", "BAD-ANCHOR",
               "CARRIED", "null mutation")
# The verdict lines mutate.py prints, in its own spelling.
VERDICT = re.compile(r"^  (CAUGHT|MISSED|NOT APPLIED|BROKEN)\s+(.*)$")
PY = sys.executable


def _annotated(label):
    return any(tok in (label or "") for tok in ANNOTATIONS)


def _touched_specs():
    """Specs whose target file differs from the previous commit."""
    try:
        out = subprocess.run(["git", "diff", "--name-only", "HEAD~1..HEAD"],
                             capture_output=True, text=True, timeout=60).stdout
    except Exception:
        return []
    changed = {os.path.basename(p) for p in out.split()}
    keep = []
    for p in sorted(glob.glob("scripts/mutations/*.json")):
        try:
            d = json.load(open(p, encoding="utf-8"))
        except Exception:
            continue
        if os.path.basename(d.get("file") or "") in changed:
            keep.append(p)
    return keep


def main(argv):
    specs = _touched_specs() if "--touched" in argv else [a for a in argv[1:]
                                                          if a.endswith(".json")]
    if not specs:
        print(__doc__)
        return 2
    print("running %d spec(s)\n" % len(specs))
    unexplained, explained, caught, broken = [], 0, 0, []
    for p in specs:
        try:
            d = json.load(open(p, encoding="utf-8"))
        except Exception as exc:
            broken.append((p, "spec unreadable: %s" % exc))
            continue
        labels = [(m.get("label") or "") for m in (d.get("mutations") or [])]
        try:
            out = subprocess.run([PY, "scripts/mutate.py", p],
                                 capture_output=True, text=True, timeout=900).stdout
        except Exception as exc:
            broken.append((p, "run failed: %s" % exc))
            continue
        if "baseline: red" in out:
            broken.append((p, "RED BASELINE -- the spec's own test file does not pass clean"))
            continue
        seen = 0
        for line in out.splitlines():
            m = VERDICT.match(line)
            if not m:
                continue
            verdict, shown = m.group(1), m.group(2).strip()
            seen += 1
            if verdict == "CAUGHT":
                caught += 1
                continue
            label = next((l for l in labels if l.startswith(shown[:40])), shown)
            if _annotated(label):
                explained += 1
            else:
                unexplained.append((os.path.basename(p), verdict, label[:150]))
        if not seen:
            broken.append((p, "no verdict lines -- did mutate.py change its output?"))
    print("CAUGHT: %d    not-caught WITH a reason: %d    not-caught with NONE: %d"
          % (caught, explained, len(unexplained)))
    if broken:
        print("\nspecs that could not be judged (%d):" % len(broken))
        for p, why in broken:
            print("   %-34s %s" % (os.path.basename(p), why))
    if unexplained:
        print("\nNOT CAUGHT AND NO REASON GIVEN (%d) -- each is a coverage hole or a"
              " missing annotation:" % len(unexplained))
        for spec, verdict, label in unexplained:
            print("   %-24s %-12s %s" % (spec, verdict, label))
    return 1 if (unexplained or broken) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
