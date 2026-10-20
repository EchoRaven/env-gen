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
import io
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

# These two do not excuse a MISSED on their own: they say the property is guarded by a
# DIFFERENT spec, which is only an answer if that spec exists. #1203pe's own lesson is that
# an unverified carrier claim is itself the defect -- it reads as coverage and is not. So a
# label carrying one of these is accepted only when every `mu_*.json` / `mut_*.json` name it
# mentions is a file on disk.
DEFERRING = ("CARRIED", "SPLIT")
_SPEC_NAME = re.compile(r"\b((?:mu|mut)[A-Za-z0-9_]*\.json)\b")


def _deferral_is_real(label, spec_dir):
    """(ok, detail) for a label that defers the property to another spec."""
    named = sorted(set(_SPEC_NAME.findall(label or "")))
    if not named:
        return False, "defers the property but names no spec to defer it to"
    missing = [n for n in named if not os.path.exists(os.path.join(spec_dir, n))]
    if missing:
        return False, "defers to a spec that does not exist: %s" % ", ".join(missing)
    return True, ""
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


def _snapshot(target):
    """The target's bytes before `mutate.py` touches it, or None."""
    try:
        with io.open(target, "rb") as fh:
            return fh.read()
    except Exception:
        return None


def _restore_from_snapshot(target, before):
    """Put `before` back if the file changed. Returns the path when it did, else "".

    RESTORE TO THE SNAPSHOT, NEVER TO HEAD. The first version of this ran
    `git checkout -- <target>`, reasoning that a dirty target meant `mutate.py` had been
    killed and left a mutant. A dirty target means no such thing: it is just as likely to be
    the author's own uncommitted patch. On 2026-10-20 that is exactly what happened -- it
    discarded an uncommitted `#1203qu` change in heal_pipeline.py, silently, and the loss
    looked identical to the mutant it was written to clean up. Comparing against the bytes
    this tool itself read a moment earlier cannot make that mistake.

    Never raises: this runs in a `finally` and must not mask the verdict it protects."""
    if not target or before is None:
        return ""
    try:
        with io.open(target, "rb") as fh:
            if fh.read() == before:
                return ""
        with io.open(target, "wb") as fh:
            fh.write(before)
        return target
    except Exception:
        return ""


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
        # A spec whose test file is gone can never run, and `mutate.py` then prints no
        # verdict lines at all -- which this tool used to report as "did mutate.py change
        # its output?", sending the reader after the wrong thing. Three specs are in that
        # state (2026-10-20): one-off controls judged against a `_tmp_old_*.py` copy of the
        # pre-fix test, deleted after the run. `mutation_census.py --strict` does not catch
        # them because it verifies ANCHORS, not test paths. Split on `::` first: pytest
        # accepts a nodeid there and `os.path.exists` on one is trivially False.
        _tfile = (d.get("test") or "").split("::", 1)[0]
        if not _tfile or not os.path.exists(os.path.join("agent", _tfile)):
            broken.append((p, "test file does not exist: %s" % (_tfile or "<empty>")))
            continue
        _before = _snapshot(d.get("file") or "")
        try:
            out = subprocess.run([PY, "scripts/mutate.py", p],
                                 capture_output=True, text=True, timeout=900).stdout
        except Exception as exc:
            broken.append((p, "run failed: %s" % exc))
            out = ""
        finally:
            # RESTORE, ALWAYS. `mutate.py` edits the target in place and restores it on its
            # own way out -- but only if it gets there. A timeout here, or the harness killing
            # the parent, leaves the mutant ON DISK: 2026-10-20 ended one session with
            # `DERIVED_VERDICTS_1203NA` missing "NOT_WALKED" and another with
            # `auth_steps_1203ov = None`, both live defects sitting in the tree behind a single
            # `M` in git status. This tool must never be the thing that leaves one.
            _restored = _restore_from_snapshot(d.get("file") or "", _before)
            if _restored:
                broken.append((p, "the target differed from its pre-run bytes and was put "
                                  "back: %s" % _restored))
        if not out:
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
            if any(t in label for t in DEFERRING):
                ok, why = _deferral_is_real(label, os.path.dirname(p) or ".")
                if ok:
                    explained += 1
                else:
                    unexplained.append((os.path.basename(p), verdict,
                                        "%s  <<< %s" % (label[:110], why)))
            elif _annotated(label):
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
