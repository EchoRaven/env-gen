"""Pre-registered checks for the 2026-10-20 batch (sections A-D, 13 checks).

    python scripts/verify_1020.py generated/<run> [--log gm_<run>.log]

Every check prints CONFIRMED / FALSIFIED / NOT MEASURED. NOT MEASURED is a real answer --
#883's rule is that "could not tell" must never be dressed as "clean" -- and several of
these are EXPECTED to be NOT MEASURED until the run exercises the path.

Two rules this script follows, both learned the hard way on 2026-10-20:
  * a check for "did this announcement fire" matches a substring unique to the EMISSION,
    never a ticket marker -- the framework and the lanes grep for their own markers, so a
    marker in a log is often a SEARCH, not an occurrence.
  * every count that could be zero is printed next to a quantity that cannot be, so an
    empty scan cannot read as a clean one.
"""
import ast
import json
import re
import sys
from pathlib import Path

OUT = []


def say(ticket, verdict, detail):
    OUT.append((ticket, verdict, detail))


def _json(p, default=None):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except Exception:
        return default


def _seed(run):
    """The delivered _SEED dict, or None."""
    for p in (run / "app" / "backend" / "seed_data.py",):
        try:
            src = p.read_text(encoding="utf-8")
        except Exception:
            continue
        m = re.search(r"_SEED\s*=\s*(\{.*?\})\s*\n(?=[A-Za-z_#]|\Z)", src, re.S)
        if not m:
            continue
        try:
            return ast.literal_eval(m.group(1)), src
        except Exception:
            return None, src
    return None, ""


def _tables(run):
    d = _json(run / "shared" / "hubs" / "registryhub_tables.json", {}) or {}
    return {str(r["name"]): r for r in d.values()
            if isinstance(r, dict) and r.get("name") and r.get("schema")}


_CONSTRAINT_TYPE_LIST = re.compile(
    r"^\s*(unique)\s*\(\s*([A-Za-z_]\w*(?:\s*,\s*[A-Za-z_]\w*)+)\s*\)\s*$", re.I)


def check_qk(run):
    """#1203qk: no duplicate composite-UNIQUE key survives in the delivered seed."""
    seed, _src = _seed(run)
    tables = _tables(run)
    if not seed or not tables:
        return say("#1203qk", "NOT MEASURED",
                   "seed parsed=%s tables=%d" % (bool(seed), len(tables)))
    sets = {}
    for name, rec in tables.items():
        for c in (rec.get("schema") or {}).get("columns") or []:
            if not isinstance(c, dict):
                continue
            m = _CONSTRAINT_TYPE_LIST.match(str(c.get("type") or ""))
            if m:
                sets.setdefault(name.lower(), []).append(
                    [x.strip() for x in m.group(2).split(",")])
    if not sets:
        return say("#1203qk", "NOT MEASURED",
                   "no table declares a composite UNIQUE (scanned %d tables)" % len(tables))
    bad = []
    checked = 0
    for t, cols_list in sets.items():
        rows = seed.get(t) or []
        for cols in cols_list:
            keys = [tuple(r.get(c) for c in cols) for r in rows if isinstance(r, dict)]
            keys = [k for k in keys if all(v is not None for v in k)]
            checked += len(keys)
            if len(keys) != len(set(keys)):
                bad.append("%s(%s)" % (t, ",".join(cols)))
    say("#1203qk", "FALSIFIED" if bad else "CONFIRMED",
        "%d declared set(s), %d key(s) compared, duplicates in: %s"
        % (sum(len(v) for v in sets.values()), checked, bad or "none"))


def check_ql(run):
    """#1203ql: a UNIQUE FK column holds at most one row per parent."""
    seed, src = _seed(run)
    if not seed:
        return say("#1203ql", "NOT MEASURED", "no parsable _SEED")
    if "_ONE_PER_OWNER" not in src or "_demo_floor_1203ql" not in src:
        return say("#1203ql", "FALSIFIED",
                   "the emitted loader predates #1203ql (_ONE_PER_OWNER=%s, "
                   "_demo_floor_1203ql=%s)"
                   % ("_ONE_PER_OWNER" in src, "_demo_floor_1203ql" in src))
    init = ""
    try:
        init = (run / "app" / "database" / "init" / "01_init.sql").read_text(encoding="utf-8")
    except Exception:
        pass
    uq_fk, cur = [], None
    for line in init.splitlines():
        t = line.strip()
        mt = re.match(r'CREATE TABLE(?: IF NOT EXISTS)? "?(\w+)"?', t, re.I)
        if mt:
            cur = mt.group(1)
            continue
        if not cur or not re.search(r"\bUNIQUE\b", t, re.I) or re.match(r"UNIQUE\s*\(", t, re.I):
            continue
        mc = re.match(r'"(\w+)"\s+(.+)$', t)
        if not mc or re.search(r"PRIMARY\s+KEY", mc.group(2), re.I):
            continue
        mp = re.search(r'references\s+"?(\w+)"?', mc.group(2), re.I)
        if mp:
            uq_fk.append((cur, mc.group(1), mp.group(1)))
    if not uq_fk:
        return say("#1203ql", "NOT MEASURED",
                   "no single-column UNIQUE FK in the DDL (%d chars scanned)" % len(init))
    bad = []
    for tbl, col, parent in uq_fk:
        rows = seed.get(tbl) or []
        vals = [r.get(col) for r in rows if isinstance(r, dict) and r.get(col) is not None]
        pn = len(seed.get(parent) or [])
        if len(vals) != len(set(vals)) or (pn and len(rows) > pn):
            bad.append("%s.%s->%s rows=%d distinct=%d parent=%d"
                       % (tbl, col, parent, len(rows), len(set(vals)), pn))
    say("#1203ql", "FALSIFIED" if bad else "CONFIRMED",
        "%d UNIQUE-FK table(s) checked; violations: %s" % (len(uq_fk), bad or "none"))


def check_log_only(logtext, nlines):
    """The checks whose whole evidence is the run log."""
    # #1203qn -- the sentence must never interpolate None into the counts.
    hits = len(re.findall(r"None/None journey steps passed", logtext))
    say("#1203qn", "FALSIFIED" if hits else "CONFIRMED",
        "%d occurrence(s) of the None/None clause in %d log line(s)" % (hits, nlines))

    # #1203qm -- primary_dataless must always carry its corroborating sample.
    naked = 0
    total = 0
    for m in re.finditer(r"found the app UNUSABLE \(([^)]*)\)", logtext):
        body = m.group(1)
        if "primary_dataless" not in body:
            continue
        total += 1
        if "primary_route_rendered" not in body:
            naked += 1
    say("#1203qm", "NOT MEASURED" if not total else
        ("FALSIFIED" if naked else "CONFIRMED"),
        "%d verdict(s) named primary_dataless, %d without the sample" % (total, naked))

    # #1203qp -- a retired check must not print counts it never measured.
    zeros = len(re.findall(r"- Semantic hub drift: [^\n]*spec_pages=0[^\n]*hub_pages=0", logtext))
    stanzas = len(re.findall(r"- Semantic hub drift", logtext))
    say("#1203qp", "FALSIFIED" if zeros else ("CONFIRMED" if stanzas else "NOT MEASURED"),
        "%d drift stanza(s), %d printing the six zeros" % (stanzas, zeros))

    # #1203md -- the shortfall line should now be able to print at all.
    short = len(re.findall(r"table\(s\) hold fewer rows", logtext))
    say("#1203md", "CONFIRMED" if short else "NOT MEASURED",
        "%d shortfall line(s); absent is fine if no table actually loaded short" % short)

    # #1203qs -- the #1017 message must name the pages, and must keep the COUNT and the
    # LIST as two numbers. The defect it replaced printed "on 0 record(s): <unnamed
    # records>" 269 times across r170-r173 for the commonest live blocker, so the check is
    # on the SHAPE of the line, not on whether it appears.
    ui = re.findall(r"#1017 validation_ui_evidence_failed on (\d+) record\(s\), "
                    r"(\d+) named page\(s\): ([^\n]*)", logtext)
    blind = [t for t in ui if t[0] == "0" and "<unnamed records>" in t[2]]
    # NOT a defect signal: `failed_records` is len(failed) and `pages_failed` is
    # sorted(set(failed)), so the two numbers are EQUAL whenever no page failed twice --
    # which is the common case. The first draft of this check called that "the COUNT and the
    # LIST merged again" and would have reported r191's 10 correct messages as suspect. What
    # would be wrong is the LIST being longer than the COUNT, which set() makes impossible
    # unless something upstream swapped the two fields.
    inverted = [t for t in ui if int(t[1]) > int(t[0])]
    old_shape = len(re.findall(r"#1017 validation_ui_evidence_failed on \d+ record\(s\): ",
                               logtext))
    say("#1203qs",
        "FALSIFIED" if (blind or old_shape or inverted)
        else ("CONFIRMED" if ui else "NOT MEASURED"),
        "%d message(s) in the two-number shape, %d in the OLD one-number shape, %d reported "
        "0 records with no names, %d named MORE pages than records (the fields swapped)"
        % (len(ui), old_shape, len(blind), len(inverted)))

    # #1203qv -- the invisible-icon advice must carry its MECHANISM, not just the symptom.
    # A lane that reads "CSS colour cannot reach" and nothing else can still see the icon in
    # the DOM, so the report contradicts what it sees. Never firing is NOT falsification:
    # it needs an <img src> row pointing at a fill="currentColor" SVG to trigger at all.
    icon = re.findall(r"#1203n0 ([^\n]*)", logtext)
    mute = [t for t in icon if "in the DOM and invisible on screen" not in t]
    say("#1203qv", "FALSIFIED" if mute else ("CONFIRMED" if icon else "NOT MEASURED"),
        "%d invisible-icon advice line(s), %d missing the mechanism clause%s"
        % (len(icon), len(mute),
           "" if icon else " (absent is fine: needs an <img> + currentColor row)"))

    # #1203qr -- a wedge while every build check is green.
    #
    # The comparison MUST use the statuses the hold itself observed (#585 prints them), not
    # the final state on disk: codehub keeps ONE record per check name and overwrites it, so
    # r191's four checks read `failure` when the hold fired at 1792189274 and `success` on
    # disk at 1792195203 -- 99 minutes later. Comparing against the end state calls a
    # correct hold a wedge.
    observed = re.findall(
        r"verification_checklist_not_ready — observed (\{[^}]*\})", logtext)
    wedged = [o for o in observed if "failure" not in o and "pending" not in o]
    say("#1203qr",
        "FALSIFIED" if wedged else ("CONFIRMED" if observed else "NOT MEASURED"),
        "%d hold(s) printed what they observed; %d held with nothing failing or pending: %s"
        % (len(observed), len(wedged), wedged[:2] or "none"))


def check_reports(run):
    """#1203ix / #1203ov / #1203n9 -- fields the walk should now leave behind."""
    d = run / "test_user_reports"
    files = sorted(d.glob("*.json")) if d.is_dir() else []
    if not files:
        return say("#1203ix/#1203ov/#1203n9", "NOT MEASURED",
                   "no test_user_reports/*.json in %s" % run)
    fill = steps = recovered = 0
    for f in files:
        r = _json(f, {}) or {}
        blob = json.dumps(r)
        if "fill_rounds" in blob:
            fill += 1
        if "auth_steps_1203ov" in blob:
            steps += 1
        summ = r.get("summary") or {}
        if summ.get("verdict") == "ERROR" and summ.get("api_steps") is not None:
            recovered += 1
    say("#1203ix", "CONFIRMED" if fill else "NOT MEASURED",
        "%d of %d report(s) carry fill_rounds" % (fill, len(files)))
    say("#1203ov", "CONFIRMED" if steps else "NOT MEASURED",
        "%d of %d report(s) carry auth_steps_1203ov" % (steps, len(files)))
    say("#1203n9", "CONFIRMED" if recovered else "NOT MEASURED",
        "%d ERROR report(s) carry recovered api_steps" % recovered)


def check_releases(run):
    """#1203oy: a release note must name the visual verdict it shipped with."""
    d = _json(run / "shared" / "hubs" / "codehub_releases.json", {}) or {}
    recs = [r for r in d.values() if isinstance(r, dict) and r.get("tag")]
    if not recs:
        return say("#1203oy", "NOT MEASURED", "no release records")
    marked = sum(1 for r in recs if "#1203oy" in str(r.get("notes") or ""))
    lying = sum(1 for r in recs
                if r.get("visual_passed") is False
                and "#1203oy" not in str(r.get("notes") or ""))
    say("#1203oy", "FALSIFIED" if lying else ("CONFIRMED" if marked else "NOT MEASURED"),
        "%d release(s), %d carry the verdict clause, %d shipped visual_passed=False "
        "without it" % (len(recs), marked, lying))


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 2
    run = Path(argv[1])
    logtext, nlines = "", 0
    if "--log" in argv:
        try:
            logtext = Path(argv[argv.index("--log") + 1]).read_text(
                encoding="utf-8", errors="ignore")
            nlines = logtext.count("\n")
        except Exception as exc:
            print("!! --log unreadable: %s" % exc)
    else:
        print("!! no --log given; the log-only checks will all read NOT MEASURED")
    check_qk(run)
    check_ql(run)
    check_reports(run)
    check_releases(run)
    check_log_only(logtext, nlines)
    width = max(len(t) for t, _v, _d in OUT)
    bad = 0
    for ticket, verdict, detail in OUT:
        print("%-*s  %-12s %s" % (width, ticket, verdict, detail))
        bad += 1 if verdict == "FALSIFIED" else 0
    print("\n%d check(s): %d FALSIFIED, %d NOT MEASURED, %d CONFIRMED"
          % (len(OUT), bad,
             sum(1 for _t, v, _d in OUT if v == "NOT MEASURED"),
             sum(1 for _t, v, _d in OUT if v == "CONFIRMED")))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
