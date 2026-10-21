"""#1203qx: does the design system ever say WHICH icon an element uses?

    python scripts/icon_specificity.py generated/<run>      # one run, with verdicts
    python scripts/icon_specificity.py --corpus             # the whole corpus baseline

WHY THIS EXISTS. iconography is the weakest delivered dimension, and the reason is NOT the
remediation loop: held to the same screens (378 judged 5+ times), icons gain +0.132 from
round 1 to round 5, which is the same as color (+0.127) and typography (+0.133). Icons are
simply the LOWEST STARTING dimension -- 0.349 at round 1 against color's 0.609 -- and five
rounds of ordinary progress cannot close a 0.26 gap. It is a cold-start problem.

MEASURED, over all 104 `design/design_system.json` in `generated/` (2026-10-20):

    level                      icon-related fields
    document (104 docs)        `iconography` = {style, stroke_px, notes}   104/104, SIX empty
    screen   (1477 screens)    nothing                                     0
    component(10146 comps)     `components[]/colors/icon`                  122, every value a hex colour

    `assets` lists a staged, semantically named inventory -- icons/bookmark_24.svg,
    icons/call_24.svg -- median 28 paths per run (min 2, max 128), in 104 of 104 runs. The
    delivered files are real: 4245 SVGs carrying genuine Material Symbols path data.

So the framework puts 28 named icons on the table, states their stroke width and their
colour, and never says which element uses which. The model guesses -- and 96% of the 1521
recorded icon deviations are exactly a wrong pairing ("reference uses a red traffic/car
icon; implementation uses a red exclamation icon"). The one thing never specified is the one
thing that goes wrong.

THREE LEVELS, NOT ONE. Checking only the top level reports "iconography: present, 104/104"
and reads as covered. `layout_metrics` taught this already: it is a per-SCREEN field, and a
top-level-only scan called it absent. This tool prints all three levels every time.

EVERY COUNT SITS NEXT TO ONE THAT CANNOT BE ZERO (#1026b, and the five times a scan of mine
returned a zero it had manufactured itself): screens and components are printed beside the
icon-field counts, so "0 icon fields" can be told apart from "0 screens parsed".
"""
import collections
import glob
import json
import os
import re
import sys

ICONISH = re.compile(r"icon|glyph|symbol", re.I)
HEX = re.compile(r"^#[0-9a-fA-F]{3,8}$")
SVG_PATH = re.compile(r"[\w/\-\.]+\.svg")


def _docs(target):
    if target == "--corpus":
        return sorted(glob.glob("generated/*/design/design_system.json"))
    p = os.path.join(target, "design", "design_system.json")
    return [p] if os.path.exists(p) else []


def _walk(obj, path, out):
    """Every icon-ish key, with the JSON path it sits on."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if ICONISH.search(str(k)):
                out.append(("/".join(path + [str(k)]), k, v))
            _walk(v, path + [str(k)], out)
    elif isinstance(obj, list):
        for v in obj:
            _walk(v, path + ["[]"], out)


def measure(docs):
    """Counts per level. `identity` is the number that matters: a field naming an icon."""
    r = collections.Counter()
    vals = collections.Counter()
    for p in docs:
        try:
            d = json.load(open(p, encoding="utf-8"))
        except Exception as exc:
            r["unreadable"] += 1
            print("   !! unreadable: %s (%s)" % (p, exc))
            continue
        r["docs"] += 1
        # NOT `d["iconography"]`. The document's root keys are design_system / assets /
        # screens; `iconography` lives one level down under `design_system`. The first
        # version of this tool read the root and printed "iconography present 0/104" --
        # a zero it manufactured itself, in the very line written to prevent one. Find it
        # wherever it is, and say where.
        top = None
        _found = []
        _walk(d, [], _found)
        for jpath, key, val in _found:
            if str(key).lower() == "iconography" and "screens" not in jpath:
                top = val
                r["doc_iconography_at_" + (jpath.rsplit("/", 1)[0] or "root")] += 1
                break
        if isinstance(top, dict):
            r["doc_iconography"] += 1
            if not top:
                r["doc_iconography_empty"] += 1
        screens = d.get("screens") if isinstance(d, dict) else None
        for s in (screens or []):
            if not isinstance(s, dict):
                continue
            r["screens"] += 1
            found = []
            _walk(s, [], found)
            for jpath, key, val in found:
                # A colour is not an identity. `colors/icon: "#2f2f2f"` says how to paint the
                # icon, which is useless to a model that does not know which icon it is.
                if isinstance(val, str) and HEX.match(val.strip()):
                    r["screen_colour_fields"] += 1
                    continue
                if "components" in jpath or "elements" in jpath:
                    r["component_fields"] += 1
                else:
                    r["screen_fields"] += 1
                # Print EVERY non-colour field, whatever its type. A count of 9 with
                # nothing listed is the shape that hides what the 9 actually are -- they
                # turn out to be sizes and booleans (glyph_px, icon_only, icon_label_gap_px),
                # not identities, and the tool has to show that rather than assert it.
                vals["%s = %s" % (key, json.dumps(val)[:30])] += 1
            # components under this screen, for the denominator
            for k in ("components", "component_specs", "elements"):
                v = s.get(k)
                if isinstance(v, list):
                    r["components"] += sum(1 for c in v if isinstance(c, dict))
        inv = SVG_PATH.findall(json.dumps(d.get("assets") if isinstance(d, dict) else None))
        icons = [x for x in inv if "icon" in x.lower()]
        r["inventory_paths"] += len(icons)
        if icons:
            r["docs_with_inventory"] += 1
    return r, vals


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 2
    target = argv[1]
    docs = _docs(target)
    if not docs:
        # An empty file list and a clean result look identical. Say which this is.
        print("no design_system.json under %r -- nothing was measured, which is NOT the same "
              "as nothing being wrong" % target)
        return 2
    r, vals = measure(docs)
    print("design_system.json read: %d" % r["docs"])
    print("  document level : iconography present %d/%d, of which EMPTY {}: %d"
          % (r["doc_iconography"], r["docs"], r["doc_iconography_empty"]))
    print("  screen level   : %d screens parsed -> %d icon field(s)"
          % (r["screens"], r["screen_fields"]))
    print("  component level: %d components parsed -> %d icon field(s), plus %d colour-only"
          % (r["components"], r["component_fields"], r["screen_colour_fields"]))
    print("  inventory      : %d icons/*.svg path(s) across %d doc(s)"
          % (r["inventory_paths"], r["docs_with_inventory"]))
    print()
    for k, n in sorted(r.items()):
        if k.startswith("doc_iconography_at_"):
            print("  (iconography found at JSON path %r in %d doc(s))"
                  % (k[len("doc_iconography_at_"):], n))
    if vals:
        print("NON-COLOUR icon field(s) -- are any of these an IDENTITY?")
        for k, n in vals.most_common(20):
            print("   %-48s %d" % (k, n))
    else:
        print("IDENTITY FIELDS: none. The design system names no icon for any element, while")
        print("staging %d named icon file(s). E1 of the pre-registration holds."
              % r["inventory_paths"])
    # E2: inventory present at all? A missing inventory is a DIFFERENT cause.
    if r["docs"] and not r["inventory_paths"]:
        print("\nE2 FALSIFIED: no staged icon inventory either. The cold start is then 'no")
        print("icons to choose from', which is the opposite diagnosis -- do not file E1.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
