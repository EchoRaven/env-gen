#!/usr/bin/env python3
"""Census every mutation spec's anchor against the current tree. #1203pe.

A mutation only tests something while its `find` anchor still appears EXACTLY ONCE in the
target file. A later patch that rewrites that region silently turns the property into "no
mutation is verifying this" -- and the suite stays green, because the test still passes for
whatever reason it passes now.

This is the FREE half of the discipline: it reads text and runs no tests, so it can cover
every spec ever written rather than the handful a session happens to remember. The other half
(`mutate.py`) is expensive and is run on the specs this census flags, plus the day's new ones.

Exit codes: 0 when nothing is unexplained (or always, without --strict); 1 on an unexplained
loss; 2 when the spec directory itself cannot be read -- which is NOT the same as "clean"
(#883), and the message says which it is.
"""

from __future__ import annotations

import json
import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_SPECS = os.path.join(_HERE, "mutations")
_ROOT = os.path.dirname(_HERE)

# A loss is EXPLAINED only by one of these, written into the mutation's `label`. Keeping the
# vocabulary closed is the point: "the code changed" is not an explanation, it is the thing
# being reported.
_EXPLAINED = ("[SUPERSEDED", "[NOT RUNNABLE", "[BAD-ANCHOR")

# A `[SUPERSEDED ...]` label usually says WHERE the property is carried now, by naming another
# spec. That sentence is the whole explanation, and it is worth exactly as much as the file it
# names: 7 of the first 9 explanations in this directory pointed at `glyph_now.json`, which the
# collection step had not copied, so the claim was unverifiable. #1201's shape -- a frozen list
# read only in a failure message is not an assertion.
_CARRIER_RE = re.compile(r"([A-Za-z0-9_]+\.json)")


def _test_paths(spec_test, agent_dir):
    """Every test file a spec names, resolved -- or [] when one of them is gone.

    `mutate.py` accepts a pytest node id (`path.py::test_name`) and several space-separated
    paths, so a naive `os.path.isfile(spec["test"])` reports a live spec as dead. MEASURED when
    this was written: of 248 specs, 7 looked unresolvable and only 3 were -- the other 4 were
    this checker refusing a `::node-id` suffix and a two-path `test` field.
    """
    out = []
    for token in str(spec_test or "").split():
        rel = token.split("::", 1)[0]
        out.append(os.path.join(agent_dir, rel))
    return out


def _label(mutation, index):
    for key in ("label", "name", "id"):
        value = mutation.get(key)
        if value:
            return str(value)
    return "M%d" % index


def census(spec_dir=_SPECS, root=_ROOT):
    """Returns (rows, problems). A row per mutation whose anchor is not unique.

    `problems` holds what the census could not READ -- a spec that will not parse, or a target
    file that is gone. Those are reported separately from anchor losses, because "I could not
    look" and "I looked and found nothing wrong" are different answers.
    """
    rows, problems, retired_specs = [], [], []
    if not os.path.isdir(spec_dir):
        return rows, [("<spec dir>", "missing: %s" % spec_dir)], []
    for name in sorted(os.listdir(spec_dir)):
        if not name.endswith(".json"):
            continue
        path = os.path.join(spec_dir, name)
        try:
            with open(path, encoding="utf-8") as handle:
                spec = json.load(handle)
        except Exception as exc:
            problems.append((name, "unreadable: %s" % exc))
            continue
        # A spec whose TEST is gone can never run again, whatever its anchors say. That is a
        # "cannot look", not a lost anchor, so it belongs in `problems` (#883) -- UNLESS the
        # spec says it is retired and why. The three retired here are completed CONTROLS: each
        # mutated against an OLD version of a test to show the old assertion was satisfiable
        # without the property, and the comparison test was a throwaway. They are kept as the
        # record of what the old form could not see, not deleted.
        agent_dir = os.path.join(root, "agent")
        retired = str(spec.get("retired") or "").strip()
        for candidate in _test_paths(spec.get("test"), agent_dir):
            if os.path.isfile(candidate):
                continue
            if retired:
                retired_specs.append((name, retired))
            else:
                problems.append((name, "test gone: %s" % os.path.relpath(candidate, root)))
        if retired:
            continue           # it will never run; censusing its anchors says nothing
        target = os.path.join(root, str(spec.get("file") or ""))
        if not os.path.isfile(target):
            problems.append((name, "target gone: %s" % spec.get("file")))
            continue
        try:
            with open(target, encoding="utf-8", errors="ignore") as handle:
                source = handle.read()
        except Exception as exc:
            problems.append((name, "target unreadable: %s" % exc))
            continue
        for index, mutation in enumerate(spec.get("mutations") or [], 1):
            find = mutation.get("find")
            if not isinstance(find, str) or not find:
                problems.append((name, "mutation %d has no `find`" % index))
                continue
            count = source.count(find)
            if count != 1:
                label = _label(mutation, index)
                explained = any(token in label for token in _EXPLAINED)
                if explained:
                    for carrier in _CARRIER_RE.findall(label):
                        if carrier == name:
                            continue
                        if not os.path.isfile(os.path.join(spec_dir, carrier)):
                            # The explanation names a carrier that is not here, so nothing can
                            # check that the property really is carried. That is not explained.
                            explained = False
                            label += "  [CARRIER MISSING: %s]" % carrier
                rows.append((name, index, count, explained, label))
    return rows, problems, retired_specs


def main(argv):
    strict = "--strict" in argv
    rows, problems, retired_specs = census()
    total_specs = len([n for n in (os.listdir(_SPECS) if os.path.isdir(_SPECS) else [])
                       if n.endswith(".json")])
    unexplained = [r for r in rows if not r[3]]
    print("mutation census: %d spec(s) in %s" % (total_specs, os.path.relpath(_SPECS, _ROOT)))
    if retired_specs:
        print("retired (completed controls, kept as record): %d" % len(retired_specs))
    if problems:
        print("COULD NOT LOOK at %d thing(s) -- this is not a clean result:" % len(problems))
        for name, why in problems:
            print("   %-28s %s" % (name, why))
    print("anchors no longer unique: %d (explained %d, UNEXPLAINED %d)"
          % (len(rows), len(rows) - len(unexplained), len(unexplained)))
    for name, index, count, _ok, label in rows:
        mark = " " if _ok else "!"
        print("  %s %-26s #%-3d count=%d  %s" % (mark, name, index, count, label[:84]))
    if problems and strict:
        return 2
    if unexplained and strict:
        print("\nAn unexplained loss means a property that WAS verified no longer is. Either "
              "re-aim the mutation at today's shape, or label it [SUPERSEDED ...] and say "
              "where the property is carried now.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
