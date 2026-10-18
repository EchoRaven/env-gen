#!/usr/bin/env python3
"""Check a run against the 2026-10-17/18 tickets' PRE-REGISTERED predictions (n5…nq).

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
    log_note = "no --log given"
    if "--log" in argv:
        p = Path(argv[argv.index("--log") + 1])
        if not p.is_file():
            log_note = "%s does not exist" % p.name
        else:
            raw = p.read_text(encoding="utf-8", errors="replace")
            # A LOG FROM ANOTHER RUN MUST NOT PRODUCE CONFIDENT NUMBERS. Measured the hard
            # way: a glob handed `gm_tiktok_r160.log` to googlemaps-r16 and five log-based
            # criteria came back CONFIRMED -- five answers about a run the log never watched.
            # `main.py` writes "Output directory: <path>" as its second line, so the pairing
            # is checkable rather than assumed.
            want = run.resolve().name
            m = re.search(r"Output directory:\s*(\S+)", raw[:4000])
            got = Path(m.group(1)).name if m else None
            if got is None:
                log_note = "%s names no output directory in its header" % p.name
            elif got != want:
                log_note = "%s is the log of %r, not %r -- IGNORED" % (p.name, got, want)
            else:
                logtext, log_note = raw, "%s (%d bytes)" % (p.name, len(raw))
    say("log", "INFO", log_note)

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

    # --- #1203ni — the measured components must survive the analyst's rewrite -----------
    # READS: design/component_specs/<screen>.json (components with a region) vs the same
    #        screen's components in design/design_system.json.
    # FALSIFIED: the document carries fewer than 80% of the measured components.
    # N-A: no component_specs on disk.
    spec_n = doc_n = 0
    worst = []
    for f in sorted(cs.glob("*.json")) if cs.is_dir() else []:
        spec = _json(f, {}) or {}
        want = [c for c in (spec.get("components") or [])
                if isinstance(c, dict)
                and isinstance(c.get("region"), list) and len(c["region"]) == 4]
        if not want:
            continue
        have = (byname.get(f.stem) or {}).get("components") or []
        spec_n += len(want)
        doc_n += len(have)
        if len(have) < len(want):
            worst.append("%s %d/%d" % (f.stem, len(have), len(want)))
    if not cs.is_dir() or not spec_n:
        say("ni", "N-A", "no measured components to compare")
    else:
        keep = doc_n / spec_n
        worst.sort(key=lambda x: int(x.rsplit(" ", 1)[1].split("/")[0]))
        say("ni", "CONFIRMED" if keep >= 0.8 else "FALSIFIED",
            "the document keeps %d of %d measured component(s) (%d%%); thinnest: %s"
            % (doc_n, spec_n, round(100 * keep), worst[:3] or "none"))

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

    # --- #1203nm — the DDL-behind-models ledger must not name a DOTTED column ----------
    # READS: logs/ddl_behind_models_1202xk.jsonl -> tables[] (the part after "<table>: ")
    # FALSIFIED: any row names a column containing a `.`. The DDL creates
    #   `"metadata.visibility" TEXT` and the old `\w+` column regex could not see a quoted
    #   dotted identifier, so it reported a column the DDL CREATES as one it never creates.
    # CONTROL (pre-patch): r190 47 such rows, r166 103, r180 25 -- all FALSIFIED.
    _nm_f = run / "logs" / "ddl_behind_models_1202xk.jsonl"
    _nm_rows, _nm_dotted = 0, []
    if _nm_f.is_file():
        for _ln in _nm_f.read_text(encoding="utf-8", errors="ignore").splitlines():
            try:
                _d = json.loads(_ln)
            except Exception:
                continue
            _nm_rows += 1
            # COUNT LINES, NOT TABLE ENTRIES. The first version counted entries against a
            # denominator of lines and printed "103 of 52", a ratio above 1 that reads as a
            # bug in the checker rather than a verdict about the run.
            _hit = [str(_t)[:60] for _t in (_d.get("tables") or [])
                    if ":" in str(_t) and "." in str(_t).split(":", 1)[1]]
            if _hit:
                _nm_dotted.append(_hit[0])
    say("nm", "FALSIFIED" if _nm_dotted else ("CONFIRMED" if _nm_rows else "N-A"),
        "%d of %d ledger line(s) name a dotted column: %s"
        % (len(_nm_dotted), _nm_rows, _nm_dotted[:2] or "none"))

    # --- #1203nn — the gate must stop claiming no run ever had a task suite -------------
    # READS: logs/delivery_gate.jsonl -> validation_runtime.matrix_skipped_reason
    # FALSIFIED: any evaluation's reason contains "ever had one" (2 of 106 corpus trees DO
    #   carry tasks/tasks.yaml), or the surviving population fact is missing from it.
    # CONTROL (pre-patch): r190 467 occurrences, r183 376, r120 309 -- all FALSIFIED.
    _nn_f = run / "logs" / "delivery_gate.jsonl"
    _nn_seen, _nn_bad, _nn_ok = 0, 0, 0
    if _nn_f.is_file():
        for _ln in _nn_f.read_text(encoding="utf-8", errors="ignore").splitlines():
            if "matrix_skipped_reason" not in _ln:
                continue
            _nn_seen += 1
            if "ever had one" in _ln:
                _nn_bad += 1
            elif "recorded gate evaluations" in _ln:
                _nn_ok += 1
    say("nn", "FALSIFIED" if _nn_bad else ("CONFIRMED" if _nn_ok else "N-A"),
        "%d of %d gate record(s) still claim no run EVER had one; %d carry the "
        "population fact" % (_nn_bad, _nn_seen, _nn_ok))

    # --- #1203no — a total/cursor contradiction must not name which number lied ---------
    # READS: logs/list_total_unreachable_1202w0.jsonl -> endpoints[]
    # FALSIFIED: a row still says "so more rows exist than `total` admits" -- a direction
    #   that holds for the offset shape and not for an opaque cursor, whose page 2 #1202w0's
    #   own probe found EMPTY (r132).
    # CONTROL (pre-patch): r171 84 rows, r183 65, instagram-r176 55 -- all FALSIFIED.
    _no_f = run / "logs" / "list_total_unreachable_1202w0.jsonl"
    _no_rows, _no_bad, _no_ok = 0, 0, 0
    if _no_f.is_file():
        for _ln in _no_f.read_text(encoding="utf-8", errors="ignore").splitlines():
            try:
                _d = json.loads(_ln)
            except Exception:
                continue
            for _e in (_d.get("endpoints") or []):
                _no_rows += 1
                if "so more rows exist than" in str(_e):
                    _no_bad += 1
                elif "cannot both be right" in str(_e) or "already carries" in str(_e):
                    _no_ok += 1
    say("no", "FALSIFIED" if _no_bad else ("CONFIRMED" if _no_ok else "N-A"),
        "%d of %d row(s) still assert a direction; %d state the contradiction"
        % (_no_bad, _no_rows, _no_ok))

    # --- #1203np — unstaged seeded media must reach a TASK, not just a log --------------
    # READS: logs/unstaged_seed_media_1202xn.jsonl + shared/hubs/workhub_tasks.json
    # FALSIFIED: the ledger has rows and no workhub task was filed for them. The detector
    #   has run since r124 and reached a logging.warning and an artifact only.
    # CONTROL (pre-patch): 15 runs carry ledger rows (r190 83, r181 63, r166 54) and NONE
    #   of them has the task -- all FALSIFIED.
    _np_f = run / "logs" / "unstaged_seed_media_1202xn.jsonl"
    _np_rows = (len([l for l in _np_f.read_text(encoding="utf-8", errors="ignore").splitlines()
                     if l.strip()]) if _np_f.is_file() else 0)
    _np_tasks = _json(run / "shared" / "hubs" / "workhub_tasks.json", {}) or {}
    _np_hit = [v for k, v in _np_tasks.items()
               if k != "_meta" and isinstance(v, dict)
               and "seeded media reference" in str(v.get("title") or "")]
    say("np", "FALSIFIED" if (_np_rows and not _np_hit) else
        ("CONFIRMED" if _np_hit else "N-A"),
        "%d ledger row(s), %d task(s) filed%s"
        % (_np_rows, len(_np_hit),
           " — assignee/priority: %s/%s" % (_np_hit[0].get("assignee"),
                                            _np_hit[0].get("priority"))
           if _np_hit else ""))

    # --- #1203nq — a missing asset the frontend REMAPS must say so ----------------------
    # READS: logs/missing_static_assets_1203g9.jsonl -> assets[], and the delivered
    #   frontend's own remap tables via remapped_seed_media_1203m3.
    # FALSIFIED: a ledger row whose path IS a key in a resolving remap table does not carry
    #   "ALREADY REMAPS". 38% of the corpus's rows are in that class, and the consumer told
    #   the lane to "add the file" for work it had already done.
    # CONTROL (pre-patch): r182 6 of its rows are remapped and none says so -- FALSIFIED.
    _nq_f = run / "logs" / "missing_static_assets_1203g9.jsonl"
    _nq_rows, _nq_bad, _nq_ok = [], 0, 0
    if _nq_f.is_file():
        for _ln in _nq_f.read_text(encoding="utf-8", errors="ignore").splitlines():
            try:
                _d = json.loads(_ln)
            except Exception:
                continue
            _nq_rows += [str(a) for a in (_d.get("assets") or [])]
    if _nq_rows:
        try:
            sys.path.insert(0, str(Path(__file__).resolve().parents[1]
                                   / "agent" / "env_generator" / "llm_generator"))
            from multi_agent.runtime.frontend_scaffold import (
                remapped_seed_media_1203m3 as _rsm)
            _paths = sorted({r.split(" (referenced by ")[0] for r in _nq_rows})
            _mapped = set((_rsm(run, _paths) or {}))
        except Exception as _e:
            _mapped = None
            say("nq-dep", "INFO", "could not import the remap reader: %r" % (_e,))
        if _mapped is not None:
            for r in _nq_rows:
                if r.split(" (referenced by ")[0] not in _mapped:
                    continue
                if "ALREADY REMAPS" in r:
                    _nq_ok += 1
                else:
                    _nq_bad += 1
            say("nq", "FALSIFIED" if _nq_bad else ("CONFIRMED" if _nq_ok else "N-A"),
                "%d remapped row(s) unannotated, %d annotated, out of %d row(s)"
                % (_nq_bad, _nq_ok, len(_nq_rows)))
    else:
        say("nq", "N-A", "no #1203g9 ledger rows in this run")

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
