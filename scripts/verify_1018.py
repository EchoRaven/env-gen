#!/usr/bin/env python3
"""Check a run against the 2026-10-17/18 tickets' PRE-REGISTERED predictions (n5…nh).

    python scripts/verify_1018.py generated/<run> --log gm_<run>.log

Every line prints CONFIRMED / FALSIFIED / N-A with the number it read, so a result cannot be
re-interpreted afterwards. Each criterion names WHAT it predicts, WHICH artifact/field it
reads, and WHAT counts as falsification.

VALIDATED ON A KNOWN ANSWER — the point of writing it before it is needed. Against
`generated/tiktok-web-r190` + its log, a run that predates every one of these patches, the
criteria that apply must come back FALSIFIED. A checker that reports CONFIRMED on a pre-patch
run is measuring nothing.
"""
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


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 2
    run = Path(argv[1])
    logtext = ""
    if "--log" in argv:
        p = Path(argv[argv.index("--log") + 1])
        if p.is_file():
            logtext = p.read_text(encoding="utf-8", errors="replace")

    reports = sorted((run / "test_user_reports").glob("*.json")) \
        if (run / "test_user_reports").is_dir() else []
    vreports = [p for p in reports if p.name != "failure_ledger.json"]

    # --- #1203n6 — the test-user validation must not die on an import -------------------
    # READS: test_user_reports/<ver>.json -> summary.verdict / summary.error
    # FALSIFIED: any report whose verdict is ERROR naming a relative-import failure.
    errs = []
    for p in vreports:
        s = (_json(p, {}) or {}).get("summary") or {}
        if str(s.get("verdict")) == "ERROR":
            errs.append("%s: %s" % (p.name, str(s.get("error"))[:60]))
    say("n6", "FALSIFIED" if errs else ("CONFIRMED" if vreports else "N-A"),
        "%d of %d test-user report(s) ERRORed: %s"
        % (len(errs), len(vreports), errs[:2] or "none"))

    # --- #1203n8 — an aborted validation must NAME its cause ----------------------------
    # READS: the run log's delivery-time TEST-USER line.
    # FALSIFIED: "no cause recorded" appears, or the old false clause comes back.
    bad8 = []
    if "no cause recorded" in logtext:
        bad8.append("no cause recorded")
    if "no journey, MCP or UI evidence was produced" in logtext:
        bad8.append("the retracted clause")
    say("n8", "FALSIFIED" if bad8 else ("CONFIRMED" if logtext else "N-A"),
        "delivery line says: %s" % (bad8 or "nothing of the kind"))

    # --- #1203n9 — the facts an abort collected must survive into the summary -----------
    # READS: test_user_reports/<ver>.json -> api.steps vs summary.api_steps
    # FALSIFIED: a report carries api.steps as a list and no summary.api_steps.
    lost = []
    for p in vreports:
        d = _json(p, {}) or {}
        s, api = d.get("summary") or {}, d.get("api") or {}
        if isinstance(api.get("steps"), list) and "api_steps" not in s:
            lost.append("%s (%d steps)" % (p.name, len(api["steps"])))
    say("n9", "FALSIFIED" if lost else ("CONFIRMED" if vreports else "N-A"),
        "%d report(s) threw away a walked journey: %s" % (len(lost), lost[:3] or "none"))

    # --- #1203nc — the lane must receive its lint details -------------------------------
    # READS: the run log.  FALSIFIED: any "Found N issues: (details unavailable)".
    hid = re.findall(r"Found (\d+) issues: \(details unavailable\)", logtext)
    say("nc", "FALSIFIED" if hid else ("CONFIRMED" if logtext else "N-A"),
        "%d message(s) withheld %d lint issue(s)" % (len(hid), sum(int(x) for x in hid)))

    # --- #1203nd — no chain may judge a database older than its models ------------------
    # READS: the run log's #1202fj drift line.
    # FALSIFIED: it fires at all (the boot migration should have closed the gap first).
    drift = re.findall(r"(\d+) modelled column\(s\) do not exist in it", logtext)
    say("nd", "FALSIFIED" if drift else ("CONFIRMED" if logtext else "N-A"),
        "#1202fj fired %d time(s), worst %s column(s) missing"
        % (len(drift), max((int(x) for x in drift), default=0)))

    # --- #1203ne — a declared `json` column must be JSONB in the DDL --------------------
    # READS: shared/hubs/registryhub_tables.json  vs  app/database/init/01_init.sql
    # FALSIFIED: a column the registration types `json` renders as TEXT.
    tabs = _json(run / "shared" / "hubs" / "registryhub_tables.json", {}) or {}
    sqlp = run / "app" / "database" / "init" / "01_init.sql"
    sql = sqlp.read_text(encoding="utf-8", errors="replace") if sqlp.is_file() else ""
    wrong = []
    for t, v in tabs.items():
        if t == "_meta" or not isinstance(v, dict):
            continue
        for c in ((v.get("schema") or {}).get("columns") or []):
            if not isinstance(c, dict) or "json" not in str(c.get("type") or "").lower():
                continue
            m = re.search(r'^\s+"%s"\s+(\S+)' % re.escape(str(c.get("name"))), sql, re.M)
            if m and "JSON" not in m.group(1).upper():
                wrong.append("%s.%s -> %s" % (t, c.get("name"), m.group(1)))
    # #1203d3's lesson, applied to this criterion: a CONFIRMED that examined nothing is
    # indistinguishable on the wire from one that examined everything. r190 declares no json
    # column at all, so it must read N-A there, not CONFIRMED.
    _declared_json = sum(
        1 for t, v in tabs.items() if t != "_meta" and isinstance(v, dict)
        for c in ((v.get("schema") or {}).get("columns") or [])
        if isinstance(c, dict) and "json" in str(c.get("type") or "").lower())
    if not (sql and _declared_json):
        say("ne", "N-A", "this run declares %d json column(s)%s"
            % (_declared_json, "" if sql else " and has no init DDL on disk"))
    else:
        say("ne", "FALSIFIED" if wrong else "CONFIRMED",
            "%d of %d declared-json column(s) rendered non-json: %s"
            % (len(wrong), _declared_json, wrong[:3] or "none"))

    # --- #1203nf — a by-name param that resolves elsewhere must say so ------------------
    # READS: registryhub_endpoints + registryhub_tables (the binding) vs the log (#1203nf).
    # FALSIFIED: such a binding exists and the log never announces it.
    eps = _json(run / "shared" / "hubs" / "registryhub_endpoints.json", {}) or {}
    bind = []
    for eid, ep in eps.items():
        if eid == "_meta" or not isinstance(ep, dict):
            continue
        path = str(ep.get("path") or "")
        for m in re.finditer(r"\{(\w+)\}", path):
            param = m.group(1)
            if param.lower().endswith("id") or param.lower() == "id":
                continue
            segs = [s for s in path.split("/") if s]
            try:
                i = segs.index("{%s}" % param)
            except ValueError:
                continue
            prev = segs[i - 1] if i > 0 else ""
            tbl = prev if prev in tabs else prev.rstrip("s")
            rec = tabs.get(tbl)
            if not isinstance(rec, dict):
                continue
            cols = {str(c.get("name")) for c in ((rec.get("schema") or {}).get("columns") or [])
                    if isinstance(c, dict)}
            if cols and param not in cols:
                bind.append("%s {%s} on %s" % (path, param, tbl))
    said = logtext.count("#1203nf")
    if not bind:
        say("nf", "N-A", "no by-name param resolves to another column in this run")
    else:
        say("nf", "CONFIRMED" if said else "FALSIFIED",
            "%d such binding(s) (%s), %d announcement(s)" % (len(bind), bind[0], said))

    # --- #1203nh — the measured LOGO component must reach the design doc ----------------
    # READS: design/component_specs/<screen>.json vs design/design_system.json + design/crops
    # FALSIFIED: a screen whose spec measures a logo region carries none in the document.
    LOGO = re.compile(r"(?i)(^|[_-])(logo|wordmark|brand)($|[_-])")
    cs = run / "design" / "component_specs"
    dsj = _json(run / "design" / "design_system.json", {}) or {}
    byname = {str(s.get("name")): s for s in (dsj.get("screens") or []) if isinstance(s, dict)}
    missing, cropped = [], 0
    for f in sorted(cs.glob("*.json")) if cs.is_dir() else []:
        spec = _json(f, {}) or {}
        want = [c for c in (spec.get("components") or [])
                if isinstance(c, dict) and LOGO.search(str(c.get("name") or ""))
                and isinstance(c.get("region"), list) and len(c["region"]) == 4]
        if not want:
            continue
        scr = byname.get(f.stem) or {}
        got = [c for c in (scr.get("components") or [])
               if isinstance(c, dict) and LOGO.search(str(c.get("id") or ""))]
        if got:
            cropped += sum(1 for c in got if c.get("crop"))
        else:
            missing.append("%s(%s)" % (f.stem, want[0].get("name")))
    if not cs.is_dir():
        say("nh", "N-A", "no component_specs in this run")
    else:
        say("nh", "FALSIFIED" if missing else "CONFIRMED",
            "%d screen(s) lost their measured logo: %s; %d restored logo(s) carry a crop"
            % (len(missing), missing[:3] or "none", cropped))

    # --- #1203n5 — a nested negative probe must bind to its registered template ---------
    # READS: the run log's RegistryHub chain rejection.
    # FALSIFIED: a rejected item is a nested action path (/<res>/<bogus>/<action>), which a
    # non-final collapse can bind.
    # The middle segment must look like a BOGUS id -- #363 only collapses a purely-negative
    # probe, so a real control-plane path like `/api/v1/tenants/default` is not this ticket's
    # population. The first version of this criterion counted those too and reported 3 where
    # the answer is 1; narrowed before it could mislead a future run.
    _BOGUS = re.compile(r"(\{\}|absent|missing|not[-_]?real|no[-_]?such|nonexistent|"
                        r"does[-_]?not[-_]?exist|unknown[-_]|fake[-_]|_\{\})", re.I)
    nested = set()
    for line in logtext.split("\n"):
        if "NOT registered in RegistryHub" not in line:
            continue
        for m in re.finditer(r"/api/(\w+)/([A-Za-z0-9_\-{}]+)/(\w+)", line):
            mid = m.group(2)
            if mid.startswith("{") or not _BOGUS.search(mid):
                continue
            nested.add(m.group(0))
    say("n5", "FALSIFIED" if nested else ("CONFIRMED" if logtext else "N-A"),
        "%d nested-action negative probe(s) still refused: %s"
        % (len(nested), sorted(nested)[:3] or "none"))

    w = max(len(t) for t, _, _ in OUT)
    for t, v, d in OUT:
        print(f"  {t:<{w}}  {v:<10} {d}")
    bad = sum(1 for _, v, _ in OUT if v == "FALSIFIED")
    print("\n%d falsified, %d confirmed, %d not applicable" % (
        bad, sum(1 for _, v, _ in OUT if v == "CONFIRMED"),
        sum(1 for _, v, _ in OUT if v == "N-A")))
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
