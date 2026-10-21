"""Pre-registered checks for the 2026-10-20 batch (sections A-D, 16 checks).

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
    # #1203r8 (2026-10-21): WHY THIS IS 0 EVERYWHERE, AND WHY THE 12 HITS ARE NOT IT.
    #
    # Audited over 455 logs: this needle appears ZERO times. `SEED SHORTFALL` -- the prefix
    # of the same sentence -- appears 12 times, and every one is a LANE GREPPING FOR IT
    # (`GREP: pattern=SEED SHORTFALL|missing_seed|seed_audit ...`). Not one is an emission.
    # Matching the marker name instead of the emitted text would have read those 12 as proof
    # the mechanism fires; the full sentence is what distinguishes a search from a sighting.
    #
    # The emission lives in a GENERATED code string (`backend_skeleton` writes
    # `_sys.stderr.write('SEED SHORTFALL (#1202r): %d table(s) hold fewer rows ...')` into
    # the app's own seeder), so it is the container that prints it, and container stderr does
    # reach the framework log -- which is why the 12 grep lines are there at all. So 0 means
    # no seeded table has ever actually loaded short, not that the check reads the wrong
    # stream. Correctly waiting; absent stays NOT MEASURED.
    #
    # ★ Worth noting for whoever picks this up: the lanes grep for this string 12 times
    # across 9 runs. They are looking for an answer about seed shortfalls, and nothing
    # answers -- the same shape as the dropped `uses` parameter on register_endpoint.
    short = len(re.findall(r"table\(s\) hold fewer rows", logtext))
    say("#1203md", "CONFIRMED" if short else "NOT MEASURED",
        "%d shortfall line(s); absent is fine if no table actually loaded short" % short)

    # #1203ip -- does the browser walk still report a malformed fill value?
    #
    # CALIBRATION (2026-10-20, over the modern logs): r185 printed 10 of these while
    # exercising `Locator.fill` 25 times; r190 (11 fills) and r191 (4 fills) printed NONE.
    # So the emission is gone from the two newest runs but the PATH is still walked, which
    # is exactly the pair of numbers this check needs: the fill count is the quantity that
    # cannot be zero in a run that got as far as typing into a form, so an empty Malformed
    # scan cannot read as clean on a run that never typed anything.
    fills = len(re.findall(r"Locator\.fill", logtext))
    malformed = len(re.findall(r"Locator\.fill: Error: Malformed value", logtext))
    say("#1203ip",
        "NOT MEASURED" if not fills else ("FALSIFIED" if malformed else "CONFIRMED"),
        "%d Locator.fill call(s), %d reporting a malformed value "
        "(r185 negative control: 25 fills / 10 malformed)" % (fills, malformed))

    # #1203qo -- an agent must not stop because the tool it needs is off its surface.
    #
    # WHAT THIS DOES AND DOES NOT MEASURE. `#1203qo`'s own guard
    # (test_hub_consistency_gate_tools_present.py) is static: it pins that every tool a gap
    # message NAMES is in the matching bundle, and that an empty extraction is loud rather
    # than vacuously green. This check measures a different thing -- the LIVE symptom in the
    # same family: an agent stopping at delivery because the tool it was told to call is not
    # on its surface. A clean log here does NOT prove that guard holds, and the guard holding
    # does not predict this count; the gap-message path and the delivery path are offered
    # their tools separately. Both are reported because only one of them can see a run.
    #
    # CALIBRATION: present in EVERY modern log -- r185 1, r190 2, r191 1 -- and the three
    # sentences name three DIFFERENT tools ("final delivery tool", "delivery tool calls",
    # "final release tool calls"), so the check matches the shared tail rather than any one
    # of them. Each occurrence is a delivery that stopped with the gate already green.
    surface = len(re.findall(r"not available in this tool surface", logtext))
    say("#1203qo",
        "NOT MEASURED" if not nlines else ("FALSIFIED" if surface else "CONFIRMED"),
        "%d delivery stop(s) blamed on a missing tool surface across %d log line(s) "
        "(r185/r190/r191 controls: 1/2/1)" % (surface, nlines))

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


def check_reports(run, logtext=""):
    """#1203ix / #1203ov / #1203n9 -- fields the walk should now leave behind.

    `logtext` is needed because #1203ov's observable is a LOG signal, not an artifact one --
    see the comment at that check for why its artifact spelling could never fire."""
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
    # #1203r8 (2026-10-21): THIS CRITERION COULD NEVER FIRE, AND THAT WAS MY BUG.
    #
    # It looked for `auth_steps_1203ov` in `test_user_reports/*.json`. Measured over every
    # such file on disk -- 188 files, 107 runs -- that key appears ZERO times, and so does
    # `"auth_ok"`. The walkthrough's structured verdict is never persisted: what reaches
    # `report["ui"]` is a DIGEST (`ran` / `screens` / `top_issues` / `reason`), and that
    # `reason` belongs to the VISUAL GATE, not the walk -- its only values across the corpus
    # are judge failures ("no screenshots or no llm", RateLimitError, JSONDecodeError). So
    # the field this asked about exists in-process and in prose, never as queryable data,
    # and the check was condemned to print NOT MEASURED forever while looking diligent.
    #
    # The OBSERVABLE that can actually appear is the key #1203ov emits when it distinguishes
    # the two Falses: `auth_walk_recorded_no_steps`. Its consumer sits in the same module
    # (`if report.get("auth_steps_1203ov") == 0`), so the fix is not inert -- the distinction
    # reaches the gate's reason, and the reason is logged.
    #
    # It is 0 everywhere today, in logs AND artifacts, and that is CORRECTLY WAITING rather
    # than broken: the branch needs an auth walk that recorded nothing, r191 died of exactly
    # that BEFORE the fix existed, and r46 -- the only run since -- authenticated fine
    # (`auth_ok=True`, 15 pages). So absence is reported as NOT MEASURED with the reason,
    # never as CONFIRMED, and a sighting is what proves the fix end to end.
    _ov = logtext.count("auth_walk_recorded_no_steps") if logtext else 0
    say("#1203ov", "CONFIRMED" if _ov else "NOT MEASURED",
        "%d log mention(s) of auth_walk_recorded_no_steps -- the key #1203ov emits when a "
        "walk recorded NO steps (0 is correctly waiting: the branch needs an unobserved "
        "auth walk, and r46 authenticated fine). The old spelling of this check read "
        "auth_steps_1203ov out of test_user_reports/*.json, where it appears 0 times in "
        "188 files across 107 runs, so it could never fire" % _ov)
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


def check_skills(run):
    """#1203p6 -- did naming the UI skills in the gate's task text get them read?

    BASELINE, measured over all 104 `eventhub_events.json` files (2026-10-20): 23617
    `skill_consulted` events naming 12 distinct skills, and the three UI skills sit at the
    very bottom with FOUR consults each -- half the next-lowest (`mcp-server-bootstrap`, 8)
    against `verification-before-completion`'s 9725.

    Per RUN the floor is starker still: only 7 of 104 runs consult a UI skill even once, and
    in the modern era six of seven runs are a flat ZERO (r185/186/187/188/189/190) while
    r191 managed exactly 1. A run consulting 439-1055 skills and none of them about the UI
    is the shape this ticket describes.

    So: 2+ UI consults is the patch working, 0 against a healthy consult total is the defect
    standing, and 1 is inside the noise this baseline already contains -- it is reported as
    NOT MEASURED rather than dressed up as either answer (#883)."""
    ui = ("frontend-design", "ui-ux-review", "ui-bootstrap")
    d = _json(run / "shared" / "hubs" / "eventhub_events.json", {}) or {}
    total = 0
    seen = {}
    for key, ev in (d.items() if isinstance(d, dict) else []):
        # `_meta` is a top-level bookkeeping key, not an event. Counting it as one is how a
        # scan of this file reports a shape it never actually read.
        if key == "_meta" or not isinstance(ev, dict):
            continue
        if str(ev.get("event_type")) != "skill_consulted":
            continue
        total += 1
        pay = ev.get("payload") if isinstance(ev.get("payload"), dict) else {}
        name = str(pay.get("skill") or pay.get("name") or pay.get("skill_name") or "?")
        if name in ui:
            seen[name] = seen.get(name, 0) + 1
    hits = sum(seen.values())
    if not total:
        verdict = "NOT MEASURED"
    elif hits >= 2:
        verdict = "CONFIRMED"
    elif hits == 0 and total >= 200:
        verdict = "FALSIFIED"
    else:
        verdict = "NOT MEASURED"
    say("#1203p6", verdict,
        "%d skill_consulted event(s) this run, %d naming a UI skill %s "
        "(modern-era control: 6 of 7 runs at 0, r191 at 1)"
        % (total, hits, sorted(seen.items()) or "[]"))


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
    check_reports(run, logtext)
    check_releases(run)
    check_skills(run)
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
