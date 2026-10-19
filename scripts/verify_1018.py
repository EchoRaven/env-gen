#!/usr/bin/env python3
"""Check a run against the 2026-10-17/18 tickets' PRE-REGISTERED predictions (n5…nt).

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

    # --- #1203nr — the seed audit must stop blaming service-name resolution ------------
    # READS: the run log.
    # FALSIFIED: the stale cause "tried services database/db/postgres" appears. 104 of 104
    #   compose files name the service `database`, so that sentence never described the real
    #   situation (a declared service with no container, i.e. the stack is down).
    # CONTROL (pre-patch): 38 runs carry it, r190 17 times, netflix-r37 241.
    _nr_old = logtext.count("tried services database/db/postgres")
    _nr_new = logtext.count("IS declared in") + logtext.count("declares NO database service")
    say("nr", "FALSIFIED" if _nr_old else ("CONFIRMED" if _nr_new else "N-A"),
        "%d stale cause line(s), %d line(s) naming the real one" % (_nr_old, _nr_new))

    # --- #1203ns / #1203nt — the staged dataset must carry the aligned keys ------------
    # READS: app/backend/seed_dataset.json + app/backend/models.py. `align_dataset_field_names`
    #   runs BEFORE the file is written (backend_skeleton 3407 vs 3462), so the delivered
    #   artifact is the aligned one and both tickets are checkable without a database.
    # FALSIFIED (ns): the model declares a content column the dataset does not fill while
    #   carrying a synonym of it — the shape that shipped 295 blank comments in 4 runs.
    # FALSIFIED (nt): a table declares BOTH twins of a media group, one holds a reference and
    #   the other is absent — the shape where the frontend picks which column is empty.
    # CONTROL (pre-patch): ns r139/r140/r145/r160; nt r189 (users + videos) and r191 (users).
    _be = run / "app" / "backend"
    _ds = _json(_be / "seed_dataset.json", {}) or {}
    _cols_by = {}
    try:
        _msrc = (_be / "models.py").read_text(encoding="utf-8", errors="ignore")
        for _m in re.finditer(r"class\s+\w+\(Base\):(.*?)(?=\nclass |\Z)", _msrc, re.S):
            _blk = _m.group(1)
            _tn = re.search(r'__tablename__\s*=\s*[\'"]([^\'"]+)', _blk)
            if _tn:
                _cols_by[_tn.group(1)] = set(
                    re.findall(r"^\s{4}(\w+)\s*=\s*Column", _blk, re.M))
    except Exception:
        _cols_by = {}

    _CONTENT = ("body", "text", "content", "message")
    _TWINS = (("avatar", "avatar_url"), ("thumbnail", "thumbnail_url"),
              ("cover", "cover_url"), ("image", "image_url"),
              ("poster", "poster_url"), ("video", "video_url"))

    _ns_bad, _ns_ok, _nt_bad, _nt_ok = [], 0, [], 0
    for _t, _rows in (_ds or {}).items():
        _cols = _cols_by.get(_t)
        if not _cols or not (isinstance(_rows, list) and _rows
                             and isinstance(_rows[0], dict)):
            continue
        _keys = set().union(*[set(r) for r in _rows[:50] if isinstance(r, dict)])
        # ns: a declared content column, a synonym present, the column itself not filled
        _tgt = [c for c in _CONTENT if c in _cols]
        if _tgt and (set(_CONTENT) & _keys):
            if _tgt[0] in _keys:
                _ns_ok += 1
            elif not (set(_tgt) & _keys):
                _ns_bad.append("%s.%s (dataset has %s)"
                               % (_t, _tgt[0], sorted(set(_CONTENT) & _keys)))
        # nt: both twins declared, one holds a reference, the other absent
        for _a, _b in _TWINS:
            if _a not in _cols or _b not in _cols:
                continue
            for _r in _rows[:50]:
                if not isinstance(_r, dict):
                    continue
                _have = [c for c in (_a, _b)
                         if isinstance(_r.get(c), str) and _r.get(c)
                         and (_r[c].startswith("/") or _r[c].startswith("http")
                              or _r[c].startswith("data:"))]
                if not _have:
                    continue
                if len(_have) == 2:
                    _nt_ok += 1
                else:
                    _nt_bad.append("%s.%s set, %s absent"
                                   % (_t, _have[0], _b if _have[0] == _a else _a))
                break
    say("ns", "FALSIFIED" if _ns_bad else ("CONFIRMED" if _ns_ok else "N-A"),
        "%d table(s) carry a content synonym the column never got: %s"
        % (len(_ns_bad), _ns_bad[:2] or "none"))
    say("nt", "FALSIFIED" if _nt_bad else ("CONFIRMED" if _nt_ok else "N-A"),
        "%d one-sided media twin(s): %s" % (len(_nt_bad), _nt_bad[:2] or "none"))

    # --- #1203oc — no page may render a literal table of the app's own rows ------------
    # READS: app/frontend/src + app/backend/models.py, through the shipped detector itself
    #   (`fabricated_record_arrays_1203oc`), so this criterion cannot drift from the code.
    # FALSIFIED: any site. A component that fetches from services/api and ALSO renders a
    #   hand-written array whose fields are columns of a table this app serves is showing the
    #   viewer rows nobody has — the #175 bar, which #175 itself only enforces against a
    #   quoted literal in the same expression.
    # CONTROL (pre-patch): r190 3 sites (MessagesDmEmptyPage / ProfileOwnPage /
    #   SettingsMoreMenuPage on `seededVideos`), r155 6, r131 3, r157 2; r191 and r185 clean.
    # N-A is REAL here and not a pass: with no parsable models.py the schema vocabulary is
    #   missing and the detector announces UNCHECKED (3 of 104 corpus runs).
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agent"))
        from env_generator.llm_generator.multi_agent.runtime.frontend_audit import (
            fabricated_record_arrays_1203oc as _fab_oc)
        _oc_app = run / "app"
        if not (_oc_app / "backend" / "models.py").is_file():
            say("oc", "N-A", "no models.py in this run, so the schema vocabulary is absent")
        else:
            _oc = _fab_oc(_oc_app) or []
            say("oc", "FALSIFIED" if _oc else "CONFIRMED",
                "%d fabricated-record site(s): %s"
                % (len(_oc), [r.split(" — ")[0] for r in _oc[:2]] or "none"))
    except Exception as _e_oc:
        say("oc", "N-A", "the #1203oc detector could not be imported (%s)" % _e_oc)

    # --- #1203od — the gate must see the PAGE behind a route guard --------------------
    # READS: app/frontend/src/App.jsx, through the shipped reader, so this cannot drift from
    #   the code it checks.
    # FALSIFIED: the file declares `<Route` and the reader gets no component out of it (the
    #   check would then examine nothing and report clean), OR a routed page's NAME matches
    #   the junk vocabulary -- a placeholder route that reached a release.
    # CONTROL (pre-patch): netflix-local-r35 routes 30 pages and the old regex saw 5 (r41
    #   5/28, r8 5/26); tiktok-web-r191 is identical under both; googlemaps-r15 declares no
    #   router at all and is N-A rather than clean.
    # The detail line carries the blind-spot size on THIS run, which is the number the fix
    #   exists for even when no junk name is present.
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agent"))
        from env_generator.llm_generator.multi_agent.runtime.frontend_audit import (
            routed_page_components_1203od as _rpc_od)
        _od_app = run / "app" / "frontend" / "src" / "App.jsx"
        if not _od_app.is_file():
            say("od", "N-A", "no App.jsx in this run")
        else:
            _od_src = _od_app.read_text(encoding="utf-8", errors="ignore")
            _od_names, _od_state = _rpc_od(_od_src)
            _od_naive = set(re.findall(r"element=\{\s*<(\w+)", _od_src))
            _od_junk = [n for n in _od_names if re.search(
                r"noop|dummy|placeholder|todo|fixme|untitled|testpage|foobar|temppage",
                n, re.I)]
            if _od_state == "unparsed":
                say("od", "FALSIFIED", "App.jsx declares <Route> and no page name parsed")
            elif _od_state == "no-routes":
                say("od", "N-A", "this app declares no router")
            else:
                say("od", "FALSIFIED" if _od_junk else "CONFIRMED",
                    "%d routed page(s), %d of them hidden from the old regex; junk: %s"
                    % (len(_od_names), len(set(_od_names) - _od_naive),
                       _od_junk or "none"))
    except Exception as _e_od:
        say("od", "N-A", "the #1203od reader could not be imported (%s)" % _e_od)

    # --- #1203of — no text character doing an icon's job where the icon is available ----
    # READS: app/frontend/src, through the shipped detector.
    # FALSIFIED: any site. The project imports a real icon set and still draws an icon with a
    #   character whose concept that set offers -- in 37 of the 63 measured sites the app
    #   ALREADY IMPORTS that very icon. This is the axis the user names as the weakest thing
    #   shipped (iconography mean 0.577 over 251 PASSING screens, min 0.22).
    # CONTROL (pre-patch): r190 3 (its `profile-fix.css` draws the tabs as ▦/⚑/♡), r183 2
    #   (`♪` beside an imported `Music2`), r115 13, netflix-local-r8 10; r191 and r185 clean.
    # N-A when the project imports NO icon set -- that half belongs to #1203kd, and an empty
    #   result here is a statement about ownership, not about cleanliness.
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agent"))
        from env_generator.llm_generator.multi_agent.runtime.frontend_audit import (
            _ICON_LIB_1203KD as _lib_of,
            glyph_icons_with_a_real_icon_available_1203of as _glyph_of)
        _of_src = run / "app" / "frontend" / "src"
        if not _of_src.is_dir():
            say("of", "N-A", "no frontend source in this run")
        else:
            _of_has_lib = False
            for _f in _of_src.rglob("*"):
                if _f.suffix not in (".jsx", ".tsx", ".js", ".ts", ".css"):
                    continue
                if "node_modules" in _f.parts:
                    continue
                try:
                    if _lib_of.search(_f.read_text(encoding="utf-8", errors="replace")):
                        _of_has_lib = True
                        break
                except Exception:
                    continue
            if not _of_has_lib:
                say("of", "N-A", "this project imports no icon set (#1203kd's half)")
            else:
                _of = _glyph_of(_of_src) or []
                say("of", "FALSIFIED" if _of else "CONFIRMED",
                    "%d glyph-icon site(s): %s"
                    % (len(_of), [r.split(" \u2014 ")[0] for r in _of[:2]] or "none"))
    except Exception as _e_of:
        say("of", "N-A", "the #1203of detector could not be imported (%s)" % _e_of)

    # --- #1203og — a build failure must name the file that cannot parse -----------------
    # READS: the run's compose_build_failure logs (how many failed on a syntax error) AND
    #   `logs/unparsable_frontend_1203og.jsonl` (whether the pre-build scan named one).
    # ★ THE FIRST VERSION OF THIS CRITERION COULD NEVER HAVE CONFIRMED: it looked for the
    #   `#1203og` marker inside `compose_build_failure*.log`, which `_compose` writes from the
    #   docker transcript alone. The #947 ratchet caught the same thing one layer down -- the
    #   finding reached a logger and a detail string, not a file -- and the recorder it asked
    #   for is what this now reads.
    # FALSIFIED: a build-failure log reports a syntax error and does NOT carry the #1203og
    #   note. That is the state r191 shipped in: 10 of 10 of its failures are the same stray
    #   `}` in SettingsMoreMenuPage.jsx:19, and every transcript hands over a tail instead of
    #   the line.
    # CONFIRMED: either there are no syntax-error build failures at all, or each one names it.
    # CONTROL (pre-patch): r191 FALSIFIED (10 logs, no note), r190 FALSIFIED (4 syntax of 10,
    #   the other 6 being #1203mr's duplicate-declaration class), r189 CONFIRMED (4 failures,
    #   none a syntax error), r188 N-A (no build failure at all).
    # ★ A FALSIFIED AFTER THE PATCH IS STILL INFORMATION, not necessarily a regression: the
    #   bracket scan sees one syntax-error family (a closer with no opener). A syntax error of
    #   another kind leaves the note absent, and reading WHICH kind is the point -- that is the
    #   next family to decide about, with the same false-positive measurement in hand.
    try:
        _og_logs = sorted((run / "logs").glob("compose_build_failure*")) \
            if (run / "logs").is_dir() else []
        _og_syn, _og_named = 0, 0
        for _lf in _og_logs:
            try:
                _tx = _lf.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            # NOT `already been declared`: a duplicate export is #1203mr's class and no
            # bracket scan can see it, so counting it here would report FALSIFIED for a
            # cause this criterion does not own. (It did, on r190, before this line.)
            if not re.search(r"Transform failed|Unexpected \"", _tx):
                continue
            if "already been declared" in _tx:
                continue
            _og_syn += 1
        _og_led = run / "logs" / "unparsable_frontend_1203og.jsonl"
        _og_named = 0
        if _og_led.is_file():
            for _ln in _og_led.read_text(encoding="utf-8", errors="ignore").splitlines():
                try:
                    # `_json` in this file is a FILE READER, not the module (caught before
                    # it ran: `_json.loads` would have called it with a string path).
                    _og_named += int((json.loads(_ln) or {}).get("count") or 0)
                except Exception:
                    continue
        if not _og_logs:
            say("og", "N-A", "no compose build failure in this run")
        elif not _og_syn:
            say("og", "CONFIRMED", "%d build failure(s), none a syntax error" % len(_og_logs))
        else:
            say("og", "FALSIFIED" if not _og_named else "CONFIRMED",
                "%d syntax-error build failure(s), %d unparsable file(s) named in "
                "logs/unparsable_frontend_1203og.jsonl" % (_og_syn, _og_named))
    except Exception as _e_og:
        say("og", "N-A", "the #1203og criterion could not read this run (%s)" % _e_og)

    # --- #1203oi — an EMPTY-state task must not name a screen that drew nothing ----------
    # READS: the run's workhub tasks (which screens the EMPTY-state task names) + the delivered
    #   captures through `blank_captures_1203ny`.
    # FALSIFIED: the task names a screen whose capture has near-zero ink AND the task body
    #   carries no carve-out for it -- the lane was sent after seed rows or filters for a page
    #   that did not render.
    # CONFIRMED: either no overlap, or every overlapping screen is named in the carve-out.
    # CONTROL (pre-patch): r163 4 of 4 named screens blank (and r163 is the ALL-blank case the
    #   new title exists for), r180 3, r169 1, gmrun3 2; r191 no overlap.
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agent"))
        from env_generator.llm_generator.multi_agent.runtime.visual_fidelity import (
            blank_captures_1203ny as _blank_oi)
        _oi_tasks = _json(run / "shared" / "hubs" / "workhub_tasks.json", {}) or {}
        _oi_named, _oi_carved = set(), set()
        for _t in _oi_tasks.values():
            if not isinstance(_t, dict) or "render an EMPTY" not in str(_t.get("title") or ""):
                continue
            _desc = str(_t.get("description") or "")
            _m = re.search(r"EMPTY-state: ([^.]{0,300})", _desc)
            if _m:
                _oi_named |= {s.strip() for s in _m.group(1).split(",") if s.strip()}
            _m2 = re.search(r"near-zero ink against its own reference: ([^.]{0,300})", _desc)
            if _m2:
                _oi_carved |= {s.strip() for s in _m2.group(1).split(",") if s.strip()}
        if not _oi_named:
            say("oi", "N-A", "this run filed no EMPTY-state task")
        else:
            _oi_blank = {str(r).split(":", 1)[0].strip() for r in (_blank_oi(run) or [])}
            _oi_bad = sorted((_oi_named & _oi_blank) - _oi_carved)
            say("oi", "FALSIFIED" if _oi_bad else "CONFIRMED",
                "%d of %d named screen(s) drew nothing and are not carved out: %s"
                % (len(_oi_bad), len(_oi_named), _oi_bad[:3] or "none"))
    except Exception as _e_oi:
        say("oi", "N-A", "the #1203oi criterion could not read this run (%s)" % _e_oi)

    # --- #1203oj — a P0 must reach the lane that owns the file it names ------------------
    # READS: shared/hubs/registryhub_consumers.json (the registration) and
    #   shared/hubs/workhub_tasks.json (where the breaking-change P0s went).
    # FALSIFIED: a breaking-change task is assigned to a lane its own `affected_files`
    #   contradict and carries no #1203oj note -- the backend being told to edit
    #   app/frontend/src/services/api.js.
    # CONFIRMED: no such task, or every one of them carries the note.
    # INFO in the detail: how many consumer RECORDS still contradict themselves. The patch
    #   deliberately leaves those alone (they are also the link that made the consumer
    #   reachable), so a non-zero count there is expected, not a failure.
    # CONTROL (pre-patch): r120 78 tasks, netflix-r43 53, netflix-r44 37, netflix-r30 31,
    #   r191 17, r181 16; r190 0 of its 2 (its contradictions are not breaking-change tasks).
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agent"))
        from env_generator.llm_generator.multi_agent.runtime.registryhub import (
            _breaking_task_owner_1203oj as _own_oj,
            _consumer_file_lane_1203oj as _lane_oj)
        _oj_tasks = _json(run / "shared" / "hubs" / "workhub_tasks.json", {}) or {}
        _oj_bad, _oj_ok = 0, 0
        for _t in _oj_tasks.values():
            if not isinstance(_t, dict) or "status" not in _t:
                continue
            _md = _t.get("metadata") or {}
            if not isinstance(_md, dict):
                continue
            if _md.get("source") != "registryhub_breaking_change":
                continue
            _asg, _note = _own_oj(_t.get("assignee"), _md.get("affected_files") or [])
            if not _note:
                continue
            if "#1203oj" in str(_t.get("description") or ""):
                _oj_ok += 1
            else:
                _oj_bad += 1
        _oj_recs = _json(run / "shared" / "hubs" / "registryhub_consumers.json", {}) or {}
        _oj_contra = sum(
            1 for _c in _oj_recs.values()
            if isinstance(_c, dict) and _c.get("agent") and _c.get("file_path")
            and _lane_oj(_c.get("file_path")) not in ("", str(_c.get("agent"))))
        if not _oj_bad and not _oj_ok:
            say("oj", "N-A", "no breaking-change task whose files name another lane "
                             "(%d self-contradicting consumer record(s))" % _oj_contra)
        else:
            say("oj", "FALSIFIED" if _oj_bad else "CONFIRMED",
                "%d misrouted P0(s) with no note, %d corrected; %d self-contradicting "
                "consumer record(s)" % (_oj_bad, _oj_ok, _oj_contra))
    except Exception as _e_oj:
        say("oj", "N-A", "the #1203oj criterion could not read this run (%s)" % _e_oj)

    # --- #1203ok — the freeze may hold only a chain that PASSED --------------------------
    # READS: shared/hubs/registryhub_verification_chains.json + the run log.
    # FALSIFIED: the log refuses a chain as frozen while the stored record shows the chain RAN
    #   and did not pass -- #1202nz's wedge in another word (`environment_blocked`).
    # CONFIRMED: refusals happened and none of them holds a chain with a recorded non-pass.
    # ★ A never-ran chain (`registered`/`coverage`) being frozen is NOT a falsification: it
    #   becomes `failing` on the next gate cycle, after which #1202nz's path applies, and the
    #   framework's own coverage-completion does not go through that method at all. My first
    #   version of this criterion counted those too, which would have reported a defect the
    #   suite had already refused.
    # CONTROL (pre-patch): r190 refuses 27 times across 16 chain names and all the checked
    #   ones are `passing`, so r190 CONFIRMS even before the patch -- the criterion is about
    #   the WRONG refusal, which the corpus has not yet produced. The detail prints the
    #   never-ran count, which is what makes the refusal reachable: r144 17, r108 16, r191 3.
    try:
        _ok_f = run / "shared" / "hubs" / "registryhub_verification_chains.json"
        _ok_chains = _json(_ok_f, {}) or {}
        _ok_status = {}
        for _k, _v in _ok_chains.items():
            if _k == "_meta" or not isinstance(_v, dict):
                continue
            _ok_status[str(_k)] = str(_v.get("status") or "")
        _ok_ran = {}
        for _k, _v in _ok_chains.items():
            if _k == "_meta" or not isinstance(_v, dict):
                continue
            _ok_ran[str(_k)] = bool(_v.get("last_result") or _v.get("results")
                                    or _v.get("history"))
        _ok_never = sum(1 for _k, _s in _ok_status.items()
                        if _s in ("registered", "coverage") and not _ok_ran.get(_k))
        _ok_blocked = sum(1 for _s in _ok_status.values() if _s == "environment_blocked")
        _ok_refused = re.findall(r"chain `([\w.\-]+)` is frozen", logtext)
        _ok_bad = sorted({n for n in _ok_refused
                          if _ok_ran.get(n) and _ok_status.get(n, "passing") != "passing"})
        if not _ok_refused:
            say("ok", "N-A", "no frozen-chain refusal in this log (%d never-ran, %d "
                             "environment_blocked chain(s) stored)"
                             % (_ok_never, _ok_blocked))
        else:
            say("ok", "FALSIFIED" if _ok_bad else "CONFIRMED",
                "%d refusal(s); %d hold a chain with a recorded non-pass: %s; stored: "
                "%d never-ran, %d environment_blocked"
                % (len(_ok_refused), len(_ok_bad), _ok_bad[:3] or "none", _ok_never,
                   _ok_blocked))
    except Exception as _e_ok:
        say("ok", "N-A", "the #1203ok criterion could not read this run (%s)" % _e_ok)

    # --- #1203ol — no event may be addressed to a file -----------------------------------
    # READS: shared/hubs/eventhub_inboxes.json (the inbox keys) and registryhub_endpoints.json
    #   (the `provider` field that caused it).
    # FALSIFIED: an inbox is keyed by something path-shaped. No agent answers to that name, so
    #   everything in it is undeliverable -- r171 holds 108 events there, 15 of them urgent.
    # CONFIRMED: no path-keyed inbox. The detail also prints path-shaped `provider` values,
    #   which the patch does NOT rewrite: it drops the recipient at publish time, so a
    #   registration may still carry one and nothing is lost by it.
    # CONTROL (pre-patch): tiktok-web-r171 FALSIFIED (1 inbox, 108 events); every other run
    #   CONFIRMED.
    try:
        _ol_inb = _json(run / "shared" / "hubs" / "eventhub_inboxes.json", {}) or {}
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agent"))
        from env_generator.llm_generator.multi_agent.runtime.eventhub import (
            _looks_like_a_path_1203ol as _path_ol)
        _ol_bad = {}
        for _k, _box in _ol_inb.items():
            if _k == "_meta" or str(_k).startswith(("version", "last_")):
                continue
            if not isinstance(_box, dict) or not _path_ol(_k):
                continue
            _ol_bad[str(_k)] = len(_box.get("items") or {})
        _ol_eps = _json(run / "shared" / "hubs" / "registryhub_endpoints.json", {}) or {}
        _ol_prov = sum(1 for _k, _e in _ol_eps.items()
                       if _k != "_meta" and isinstance(_e, dict)
                       and _path_ol(_e.get("provider")))
        if not _ol_inb:
            say("ol", "N-A", "this run has no event inboxes")
        else:
            say("ol", "FALSIFIED" if _ol_bad else "CONFIRMED",
                "%d path-keyed inbox(es) holding %d event(s): %s; %d endpoint(s) registered "
                "with a path as provider"
                % (len(_ol_bad), sum(_ol_bad.values()),
                   sorted(_ol_bad)[:2] or "none", _ol_prov))
    except Exception as _e_ol:
        say("ol", "N-A", "the #1203ol criterion could not read this run (%s)" % _e_ol)

    # --- #1203om — the guard's own 4xx must carry CORS headers ---------------------------
    # READS: the delivered app/backend/main.py, by AST.
    # FALSIFIED: a 4xx-returning `@app.middleware("http")` guard is registered AFTER
    #   CORSMiddleware (so it is the OUTER layer and its response skips CORS) and its 4xx
    #   branch does not set `Access-Control-Allow-Origin` itself. A browser then reports a CORS
    #   failure instead of a 401 -- r181's verifier said so about 49 times and the run died on
    #   validation_ui_evidence_failed + deliverability_ui_flow_failed.
    # CONFIRMED: either CORS is the outer layer, or the guard sets the header itself.
    # CONTROL (pre-patch): 101 of 101 delivered backends FALSIFY, r190 and r191 among them.
    # ★ AST, not a string scan: a `split("\n\n\n")` window over the guard body answered 64.
    try:
        _om_f = run / "app" / "backend" / "main.py"
        if not _om_f.is_file():
            say("om", "N-A", "no delivered backend main.py in this run")
        else:
            import ast as _ast_om
            _om_tree = _ast_om.parse(_om_f.read_text(encoding="utf-8", errors="ignore"))
            _om_cors, _om_guards = None, []
            for _n in _ast_om.walk(_om_tree):
                if isinstance(_n, _ast_om.Call):
                    _fn = getattr(_n.func, "attr", getattr(_n.func, "id", ""))
                    if _fn == "add_middleware" and _n.args:
                        _nm = getattr(_n.args[0], "id", getattr(_n.args[0], "attr", ""))
                        if _nm == "CORSMiddleware":
                            _om_cors = (_n.lineno if _om_cors is None
                                        else min(_om_cors, _n.lineno))
                if isinstance(_n, (_ast_om.FunctionDef, _ast_om.AsyncFunctionDef)):
                    if not any(isinstance(_d, _ast_om.Call)
                               and getattr(_d.func, "attr", "") == "middleware"
                               and _d.args and isinstance(_d.args[0], _ast_om.Constant)
                               and _d.args[0].value == "http"
                               for _d in _n.decorator_list):
                        continue
                    _dump = _ast_om.dump(_n)
                    _four = any(
                        _kw.arg == "status_code" and isinstance(_kw.value, _ast_om.Constant)
                        and isinstance(_kw.value.value, int) and 400 <= _kw.value.value < 500
                        for _r in _ast_om.walk(_n)
                        if isinstance(_r, _ast_om.Return) and isinstance(_r.value, _ast_om.Call)
                        for _kw in _r.value.keywords)
                    _om_guards.append((_n.lineno, _four,
                                       "Access-Control-Allow-Origin" in _dump))
            _om_bad = [g for g in _om_guards
                       if g[1] and _om_cors is not None and g[0] > _om_cors and not g[2]]
            if _om_cors is None or not _om_guards:
                say("om", "N-A", "this backend has no CORS middleware or no http guard")
            else:
                say("om", "FALSIFIED" if _om_bad else "CONFIRMED",
                    "%d of %d http guard(s) answer 4xx outside CORS without setting the "
                    "header themselves" % (len(_om_bad), len(_om_guards)))
    except Exception as _e_om:
        say("om", "N-A", "the #1203om criterion could not read this run (%s)" % _e_om)

    # --- #1203oo — an MCP tool must not call a path parameter a body field ---------------
    # READS: shared/hubs/registryhub_endpoints.json, rendered through the framework's own
    #   `_body_fields_note_1202xt` -- the function that writes the line, so the criterion
    #   cannot disagree with what ships.
    # FALSIFIED: some POST/PUT/PATCH endpoint whose contract restates one of its own path
    #   parameters in `request` has that name under "Body fields". `render_tool` already makes
    #   it a required ARGUMENT of the tool and interpolates it into the URL, so the sentence is
    #   wrong about where the value goes -- #1202xy's finding, third case.
    # CONFIRMED: every restated path parameter appears under "Path" instead.
    # CONTROL (pre-patch): 93 endpoints in 37 runs FALSIFY, r184/r187/r189/r190 among them;
    #   for 30 of them in 13 runs the old note named nothing else at all.
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agent"))
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]
                               / "agent" / "env_generator" / "llm_generator"))
        from multi_agent.runtime.mcp_scaffold import (  # noqa: E402
            _body_fields_note_1202xt as _oo_note, _path_params as _oo_pp)
        _oo_src = run / "shared" / "hubs" / "registryhub_endpoints.json"
        _oo_d = _json(_oo_src, None)
        _oo_eps = None
        if isinstance(_oo_d, list):
            _oo_eps = _oo_d
        elif isinstance(_oo_d, dict):
            _oo_eps = _oo_d.get("endpoints")
            if isinstance(_oo_eps, dict):
                _oo_eps = list(_oo_eps.values())
            if _oo_eps is None:
                _oo_eps = list(_oo_d.values())
        _oo_writes, _oo_clash, _oo_bad = 0, 0, []
        for _ep in _oo_eps or []:
            if not isinstance(_ep, dict):
                continue
            if str(_ep.get("method", "")).upper() not in ("POST", "PUT", "PATCH"):
                continue
            _rq = (_ep.get("schema") or {}).get("request") if isinstance(
                _ep.get("schema"), dict) else None
            if not isinstance(_rq, dict) or not _rq:
                continue
            _oo_writes += 1
            _pp = set(_oo_pp(str(_ep.get("path") or "")))
            _cl = {n for n in _rq if str(n) in _pp}
            if not _cl:
                continue
            _oo_clash += 1
            _note = _oo_note(_ep)
            _body = re.search(r"(?:^|\. )Body fields: (.*?)(?=(?:\. (?:Path|Headers): )|$)",
                              _note)
            _named = ({x.split(" (")[0].strip() for x in _body.group(1).split(", ")}
                      if _body else set())
            if _named & _cl:
                _oo_bad.append("%s %s" % (_ep.get("method"), _ep.get("path")))
        if _oo_eps is None:
            say("oo", "N-A", "this run has no registryhub_endpoints.json")
        elif not _oo_clash:
            say("oo", "N-A", "none of this run's %d schema'd writes restate a path parameter"
                % _oo_writes)
        else:
            say("oo", "FALSIFIED" if _oo_bad else "CONFIRMED",
                "%d of %d restating write(s) still name the path value as a body field%s"
                % (len(_oo_bad), _oo_clash,
                   (" -- e.g. " + ", ".join(sorted(_oo_bad)[:2])) if _oo_bad else ""))
    except Exception as _e_oo:
        say("oo", "N-A", "the #1203oo criterion could not read this run (%s)" % _e_oo)

    # --- #1203op — a task must not send a lane to a file that is not there ---------------
    # READS: shared/hubs/workhub_tasks.json, and the run's OWN git history
    #   (`git log --all --name-only`) to decide what "not there" means.
    # FALSIFIED: a breaking-change or auth-relaxed task names an `app/...` path that NEVER
    #   existed at any point in this run, and the task carries no #1203op note saying so.
    # CONFIRMED: no such task, or every one of them carries the note.
    # ★ WHY GIT AND NOT THE TREE: a task that asked the lane to DELETE a file names a path
    #   that is correctly absent from the final tree, and at filing time it existed, so the
    #   runtime check never fired. Scanning the tree answers 138 tasks in 19 runs and that
    #   number is not this behaviour; "never in the history" is what can be attributed.
    # CONTROL (pre-patch): netflix-local-r44 FALSIFIES 37, tiktok-web-r191 17,
    #   tiktok-web-r184 4, netflix-local-r5 2, netflix-local-r6 2; r190 has none -> N-A.
    try:
        import subprocess as _sp_op
        _op_tasks = _json(run / "shared" / "hubs" / "workhub_tasks.json", None)
        if not isinstance(_op_tasks, dict):
            say("op", "N-A", "this run has no workhub_tasks.json")
        elif not (run / ".git").is_dir():
            say("op", "N-A", "this run directory carries no git history to check against")
        else:
            _op_h = _sp_op.run(["git", "-C", str(run), "log", "--all", "--name-only",
                                "--format="], capture_output=True, text=True, timeout=300)
            _op_ever = {l.strip() for l in _op_h.stdout.splitlines() if l.strip()}
            if _op_h.returncode != 0 or not _op_ever:
                say("op", "N-A", "git could not list this run's history")
            else:
                _op_pat = re.compile(
                    r"\b(app/(?:backend|frontend)/[A-Za-z0-9_./\-]+\.[A-Za-z]{2,4})\b")
                _op_n, _op_bad = 0, []
                for _k, _t in _op_tasks.items():
                    if _k == "_meta" or not isinstance(_t, dict):
                        continue
                    _ti = str(_t.get("title") or "")
                    if not (_ti.startswith("Fix breaking change in")
                            or "is public again - undo the auth workaround" in _ti):
                        continue
                    _desc = str(_t.get("description") or "")
                    _ps = set(_op_pat.findall(_ti + " " + _desc))
                    _ps |= {str(x) for x in (_t.get("affected_files") or [])
                            if isinstance(x, str)}
                    _gh = [x for x in _ps if x.startswith("app/") and x not in _op_ever]
                    if not _gh:
                        continue
                    _op_n += 1
                    if "#1203op" not in _desc:
                        _op_bad.append("%s -> %s" % (_ti[:40], sorted(_gh)[0]))
                if not _op_n:
                    say("op", "N-A", "no task in this run names a path that never existed")
                else:
                    say("op", "FALSIFIED" if _op_bad else "CONFIRMED",
                        "%d of %d task(s) naming a never-existing file say nothing about it%s"
                        % (len(_op_bad), _op_n,
                           (" -- e.g. " + _op_bad[0]) if _op_bad else ""))
    except Exception as _e_op:
        say("op", "N-A", "the #1203op criterion could not read this run (%s)" % _e_op)

    # --- #1203oq — one task must not carry two opposite orders --------------------------
    # READS: shared/hubs/workhub_tasks.json, through the framework's OWN
    #   `is_transport_failure_1202od`, the predicate #1202vq classifies with.
    # FALSIFIED: a `business_endpoints_reachable` task whose EVERY evidence fragment raised at
    #   the socket still carries "Add them to app/backend/custom_routes.py" (so it says both
    #   "do NOT edit a handler for these" and "add them"), or is still assigned to a lane that
    #   cannot re-run a validation.
    # CONFIRMED: no such task, or each one carries the re-run instruction and went to the
    #   verifier. A MIXED task (some answered, some did not) is correct either way and is not
    #   counted -- there the "wire them" prose is still true of the ones that answered.
    # CONTROL (pre-patch): tiktok-web-r166 1 and tiktok-web-r190 1 FALSIFY. tiktok-web-r107
    #   has the same shape and is N-A on purpose: it predates #1202vq's notice, so the
    #   framework had concluded nothing for the prose to contradict.
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agent"))
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]
                               / "agent" / "env_generator" / "llm_generator"))
        from multi_agent.runtime.chain_executor import (  # noqa: E402
            is_transport_failure_1202od as _oq_gone)
        _oq_pre = "The `business_endpoints_reachable` validation check FAILED: "
        _oq_add = "Add them to app/backend/custom_routes.py"
        _oq_not = "THE APP DID NOT ANSWER"
        _oq_t = _json(run / "shared" / "hubs" / "workhub_tasks.json", None)
        if not isinstance(_oq_t, dict):
            say("oq", "N-A", "this run has no workhub_tasks.json")
        else:
            _oq_n, _oq_bad = 0, []
            for _k, _t in _oq_t.items():
                if _k == "_meta" or not isinstance(_t, dict):
                    continue
                _d = str(_t.get("description") or "")
                if not _d.startswith(_oq_pre) or _oq_not not in _d:
                    continue
                _fr = [x.strip() for x
                       in _d[len(_oq_pre):].split("\n")[0].split(" || ")[-1].split(";")
                       if x.strip()]
                if not _fr:
                    continue
                if any(not _oq_gone({"status": None, "error": x}) for x in _fr):
                    continue          # mixed: both instructions are true of their own half
                _oq_n += 1
                if _oq_add in _d or str(_t.get("assignee") or "") != "verifier":
                    _oq_bad.append("%s -> %s"
                                   % (str(_t.get("title") or "")[:38], _t.get("assignee")))
            if not _oq_n:
                say("oq", "N-A", "no task in this run reports every endpoint unanswered")
            else:
                say("oq", "FALSIFIED" if _oq_bad else "CONFIRMED",
                    "%d of %d all-unanswered task(s) still say to wire the routes or went to a "
                    "lane with no validation tool%s"
                    % (len(_oq_bad), _oq_n,
                       (" -- e.g. " + _oq_bad[0]) if _oq_bad else ""))
    except Exception as _e_oq:
        say("oq", "N-A", "the #1203oq criterion could not read this run (%s)" % _e_oq)

    # --- #1203or — a lane must not get away with "that tool is not on my surface" ---------
    # READS: the run's hubs, through the framework's OWN
    #   `contradicted_capability_claims_1203or`, with the "offered" set taken from the tools
    #   each agent SUCCESSFULLY CALLED in its paired run log (a strict subset of what it was
    #   offered, so this under-counts rather than over-counts).
    # FALSIFIED: such a claim exists and `logs/contradicted_capability_claims_1203or.jsonl`
    #   does not record it -- i.e. the run contained the contradiction and nothing said so.
    # CONFIRMED: no such claim, or every one of them is in that ledger.
    # ★ THE LOG IS NOT IN THE TREE. A modern run's log sits beside the repo as `gm_<run>.log`
    #   (37 of 38 r140+ trees have no `generation_*.log` at all), so this pairs by the log's
    #   own `Output directory:` line -- the same pairing this script already does for --log.
    # CONTROL (pre-patch): instagram-r175 FALSIFIES 4, r185 3, r182 3, r176 3, r191 1.
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agent"))
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]
                               / "agent" / "env_generator" / "llm_generator"))
        from multi_agent.runtime.delivery_gate import (  # noqa: E402
            contradicted_capability_claims_1203or as _cc1203or)
        import subprocess as _sp_or
        _or_logs = []
        for _f in sorted((Path(__file__).resolve().parents[1]).glob("*.log")):
            try:
                with _f.open(encoding="utf-8", errors="replace") as _fh:
                    _head = [next(_fh, "") for _ in range(40)]
            except Exception:
                continue
            for _l in _head:
                _m = re.search(r"Output directory:\s*(\S+)", _l)
                if _m:
                    if Path(_m.group(1).rstrip("/")).name == run.name:
                        _or_logs.append(str(_f))
                    break
        _or_logs += [str(x) for x in (run / "logs").glob("generation_*.log")]
        if not _or_logs:
            say("or", "N-A", "no run log pairs to this tree, so nothing can be judged")
        else:
            # the tick is a real character, not an escape: inside an r-string `\u2705`
            # reaches grep literally and matches nothing, which reads as "no tool was ever
            # called successfully" -- an N-A that looks like a fact.
            _or_ok = "\u2705"
            _out = _sp_or.run(["grep", "-ohE",
                               r"\[[a-z_0-9]+\] " + _or_ok + r" [a-z_0-9]+"]
                              + _or_logs, capture_output=True, text=True, timeout=900).stdout
            _did = {}
            for _l in _out.splitlines():
                _m = re.match(r"\[([a-z_0-9]+)\] " + _or_ok + r" ([a-z_0-9]+)", _l.strip())
                if _m:
                    _did.setdefault(_m.group(1), set()).add(_m.group(2))
            if not _did:
                say("or", "N-A", "the paired log records no successful tool call")
            else:
                _rows = _cc1203or(run / "shared" / "hubs", _did)
                _led = run / "logs" / "contradicted_capability_claims_1203or.jsonl"
                _have = _led.read_text(encoding="utf-8") if _led.is_file() else ""
                _unsaid = [r for r in _rows
                           if str(r.get("id") or "") not in _have]
                if not _rows:
                    say("or", "N-A", "no contradicted capability claim in this run")
                else:
                    say("or", "FALSIFIED" if _unsaid else "CONFIRMED",
                        "%d of %d contradicted capability claim(s) reach no ledger%s"
                        % (len(_unsaid), len(_rows),
                           (" -- e.g. %s says %s" % (_rows[0].get("agent"),
                                                     ",".join(_rows[0].get("tools") or [])))
                           if _unsaid else ""))
    except Exception as _e_or:
        say("or", "N-A", "the #1203or criterion could not read this run (%s)" % _e_or)

    # --- #1203os — a finding must not wear #1201's "this mechanism is OFF" template -------
    # READS: the run log (--log), which is where #1201/#1203os lines land.
    # FALSIFIED: a `#1201 ... did NOT run this process` line whose subject is one of the three
    #   moved sites -- a ui_page registered with no `apis_used`, a ui_page claimed IMPLEMENTED
    #   with no surface, or a stack-lease wait. None of those is a mechanism that declined.
    # CONFIRMED: those subjects appear under `#1203os` (or not at all) and every remaining
    #   `#1201` line is a mechanism that really did not run.
    # CONTROL (pre-patch): 599 of the corpus's 602 `#1201` lines are these three, across 66
    #   logs -- r191 and r190 among them. 3 lines in 3 logs are the real population.
    try:
        _os_subjects = ("registered with no `apis_used`",
                        "was claimed IMPLEMENTED with no route and no component",
                        "for the stack lease held by")
        if not logtext:
            say("os", "N-A", "no run log given, and these lines live only in the log")
        else:
            _os_bad, _os_ok, _os_real = 0, 0, 0
            for _l in logtext.splitlines():
                if "#1203os " in _l and any(x in _l for x in _os_subjects):
                    _os_ok += 1
                    continue
                if "#1201 " not in _l:
                    continue
                if any(x in _l for x in _os_subjects):
                    _os_bad += 1
                elif "did NOT run this process" in _l:
                    _os_real += 1
            if not (_os_bad or _os_ok):
                say("os", "N-A", "this log carries none of the three moved subjects "
                                 "(%d real #1201 line(s))" % _os_real)
            else:
                say("os", "FALSIFIED" if _os_bad else "CONFIRMED",
                    "%d finding(s) still wear the #1201 template, %d announce correctly, "
                    "%d genuine mechanism-off line(s)" % (_os_bad, _os_ok, _os_real))
    except Exception as _e_os:
        say("os", "N-A", "the #1203os criterion could not read this run (%s)" % _e_os)

    # --- #1203ot — a success line must not repeat itself byte for byte ------------------
    # READS: the run log (--log).
    # FALSIFIED: the `#1202vz resolved ...` line appears more times than it has DISTINCT
    #   bodies plus a small allowance -- i.e. the localiser's every pass is still printing the
    #   same sentence. #1202ad's rule, on the biggest offender left after #1203i3.
    # CONFIRMED: each distinct resolution is said at most a handful of times (one per state).
    # CONTROL (pre-patch): r183 1220 lines / 1 distinct body, r190 797/1, r185 607/1,
    #   r191 427/1.
    try:
        if not logtext:
            say("ot", "N-A", "no run log given, and this line lives only in the log")
        else:
            _ot_lines = [l for l in logtext.splitlines() if "#1202vz resolved" in l]
            _ot_bodies = {l.split("#1202vz", 1)[1].strip() for l in _ot_lines}
            if not _ot_lines:
                say("ot", "N-A", "this run never resolved a declared FK by natural key")
            else:
                # one line per distinct state is the fix's own shape; allow 3x headroom for
                # counts that legitimately move between passes.
                _ot_cap = max(3 * len(_ot_bodies), 3)
                say("ot", "FALSIFIED" if len(_ot_lines) > _ot_cap else "CONFIRMED",
                    "%d line(s) for %d distinct resolution(s)"
                    % (len(_ot_lines), len(_ot_bodies)))
    except Exception as _e_ot:
        say("ot", "N-A", "the #1203ot criterion could not read this run (%s)" % _e_ot)

    # --- #1203ou — a KEPT-PAGE decision must not repeat itself every pass ----------------
    # READS: the run log (--log).
    # FALSIFIED: `#1197 KEEPING the lane's auth page` appears more times than it has DISTINCT
    #   raw bodies plus headroom -- the scaffolder re-announcing the same decision per tick.
    # CONFIRMED: one line per distinct decision (page + the two line counts).
    # ★ DISTINCT RAW lines, not normalised: normalising the numbers merges "15 lines" with
    #   "14 lines", and the lane editing its own page between passes is exactly the change
    #   that must still be reported.
    # CONTROL (pre-patch): r190 212 lines / 5 distinct (the top one 92x), r183 208/17,
    #   r185 110/14, r191 88/9.
    try:
        if not logtext:
            say("ou", "N-A", "no run log given, and this line lives only in the log")
        else:
            _ou = [l for l in logtext.splitlines() if "#1197 KEEPING" in l]
            _ou_b = {l.split("#1197", 1)[1].strip() for l in _ou}
            if not _ou:
                say("ou", "N-A", "this run kept no lane auth page")
            else:
                _ou_cap = max(3 * len(_ou_b), 3)
                say("ou", "FALSIFIED" if len(_ou) > _ou_cap else "CONFIRMED",
                    "%d line(s) for %d distinct kept-page decision(s)"
                    % (len(_ou), len(_ou_b)))
    except Exception as _e_ou:
        say("ou", "N-A", "the #1203ou criterion could not read this run (%s)" % _e_ou)

    # --- #1203ov — "the walk observed nothing" must not read as "the login failed" --------
    # READS: the run log (--log).
    # FALSIFIED: a browser-gate line reports `auth_ok=False` with EVERY other signal empty
    #   and says nothing about the step count -- the signature of a walk that recorded
    #   nothing being reported as a failed authentication.
    # CONFIRMED: no such line, or each one carries the no-steps wording / the
    #   `auth_walk_recorded_no_steps` signal.
    # CONTROL (pre-patch): 14 such lines in 13 of the 101 logs that have any `auth_ok=False`;
    #   4 are modern (r183 1, r185 1, r191 2), and r191's was its terminal
    #   `browser_ui_unusable — "attempt 8; signals: auth_ok=False"`.
    try:
        if not logtext:
            say("ov", "N-A", "no run log given, and these lines live only in the log")
        else:
            _ov_sig = re.compile(r"auth_ok=False blank=\[\] console_errors=\[\] "
                                 r"hollow=False login_wall=\[\] visual_mismatches=\[\]")
            _ov_bad, _ov_ok = 0, 0
            for _l in logtext.splitlines():
                if "auth_ok=False" not in _l:
                    continue
                if "no login steps recorded" in _l or "auth_walk_recorded_no_steps" in _l:
                    _ov_ok += 1
                elif _ov_sig.search(_l):
                    _ov_bad += 1
            if not (_ov_bad or _ov_ok):
                say("ov", "N-A", "this log has no all-empty auth_ok=False line")
            else:
                say("ov", "FALSIFIED" if _ov_bad else "CONFIRMED",
                    "%d line(s) report a silent walk as a failed login, %d name it correctly"
                    % (_ov_bad, _ov_ok))
    except Exception as _e_ov:
        say("ov", "N-A", "the #1203ov criterion could not read this run (%s)" % _e_ov)

    # --- #1203ox — the startup tool-surface line must not assert offerability ------------
    # READS: the run log (--log).
    # FALSIFIED: a `tool-surface: profile ...` line says the tools it names are
    #   "(offerable via ranking)". For most profiles that is not true: `rank_tool_names`
    #   caps at `max(limit, len(always_include))` and fills `always_include` first, so the
    #   ranked slots are `max(0, limit - |always_include[stage] & granted|)` -- 0 for the
    #   orchestrator in 5 of its 6 stages, and for backend / frontend / verifier / debugger
    #   / knowledge / realism_judge / the three test users in essentially every stage.
    # CONFIRMED: every such line states the CONDITION instead (free ranker slot or the
    #   stage's allowlist) and carries the ticket id.
    # CONTROL (pre-patch): 2806 lines in 211 of 211 logs, 14 per log (one per profile), every
    #   one of them asserting offerability; r189/r190/r191 are 14 each.
    try:
        if not logtext:
            say("ox", "N-A", "no run log given, and this line lives only in the log")
        else:
            _ox_bad = _ox_ok = 0
            for _l in logtext.splitlines():
                if "tool-surface: profile" not in _l:
                    continue
                _low = _l.lower()
                if ("#1203ox" in _l and "only" in _low and "slot" in _low
                        and "allowlist" in _low):
                    _ox_ok += 1
                elif "offerable via ranking" in _low:
                    _ox_bad += 1
            if not (_ox_bad or _ox_ok):
                say("ox", "N-A", "this log has no tool-surface profile line")
            else:
                # #883: a log carrying BOTH wordings is not clean -- the old sentence is
                # still being emitted somewhere, so this fails closed.
                say("ox", "FALSIFIED" if _ox_bad else "CONFIRMED",
                    "%d line(s) assert the tools are offerable, %d state the condition"
                    % (_ox_bad, _ox_ok))
    except Exception as _e_ox:
        say("ox", "N-A", "the #1203ox criterion could not read this run (%s)" % _e_ox)

    # --- #1203oy — the release note must carry the visual verdict ------------------------
    # READS: shared/hubs/codehub_releases.json
    # FALSIFIED: a release record whose `notes` do NOT mention the visual verdict while the
    #   same record carries one (`visual_passed` present) -- the note is the only visual
    #   fact that reaches `live_monitor_server.build_releases`, whose per-release payload is
    #   tag/branch/sha/notes/createdAt/snapshots and no `visual_*` key.
    # CONFIRMED: every release that has a verdict says so in its note.
    # CONTROL (pre-patch): 78 of 95 releases carry the framework's constant "the delivery
    #   gate is fully clear" and 22 of those were cut with `visual_passed=False` (r167, r168,
    #   r169, r173 x2, r177 x2, r184, r190, r191); none of the 95 notes mentions a verdict.
    try:
        # `_json` is this script's own reader (path, default) -- NOT the stdlib module.
        _oy_d = _json(run / "shared" / "hubs" / "codehub_releases.json", None)
        if _oy_d is None:
            say("oy", "N-A", "this run cut no release")
        else:
            _oy_bad, _oy_ok, _oy_novrd = [], 0, 0
            for _k, _v in (_oy_d or {}).items():
                if _k == "_meta" or not isinstance(_v, dict):
                    continue
                if "visual_passed" not in _v:
                    _oy_novrd += 1
                    continue
                _n = str(_v.get("notes") or "")
                if "#1203oy" in _n or "visual verdict" in _n.lower():
                    _oy_ok += 1
                else:
                    _oy_bad.append("%s(visual_passed=%r)" % (_k, _v.get("visual_passed")))
            if not (_oy_bad or _oy_ok):
                say("oy", "N-A", "none of this run's %d release(s) carries a visual verdict"
                    % _oy_novrd)
            else:
                say("oy", "FALSIFIED" if _oy_bad else "CONFIRMED",
                    "%d release note(s) omit the verdict in the same record, %d carry it%s"
                    % (len(_oy_bad), _oy_ok,
                       (" -- " + ", ".join(sorted(_oy_bad)[:3])) if _oy_bad else ""))
    except Exception as _e_oy:
        say("oy", "N-A", "the #1203oy criterion could not read this run (%s)" % _e_oy)

    # --- #1203p2 — the `apis_used` no-op must be observable, not only returned ----------
    # READS: the run log (--log).
    # This one is a QUESTION, not a guard: #1203b0's note rides in `ToolResult.data`, which
    # reaches the model and nothing else -- tool results are not logged, so the note's text
    # appears 0 times in all 211 pre-patch logs BY CONSTRUCTION. #1203p2 adds one line per
    # (page, repeat) so the next run can say whether that no-op is what keeps
    # `deliverability_page_apis_understated` coming back: 59 returns across the gate ledgers,
    # and the check's own task bodies are specific (only 2 of its 139 tasks lack a concrete
    # identifier), so vagueness is already ruled out.
    # CONFIRMED: the line is present -- the no-op happens, and its count per page is the
    #   attribution this ticket was written to get.
    # N-A (not a failure): no line, which means lanes passed `apis_used` on every
    #   re-registration in this run and the returns have another cause.
    # FALSIFIED: `page_apis_understated` failed in this run AND a re-registration happened
    #   with no line at all -- that would mean the recorder itself did not run.
    # CONTROL (pre-patch): r190 is FALSIFIED by construction -- `page_apis_understated`
    #   is in that log, pages were re-registered, and the recorder did not exist yet, so
    #   it said nothing. Every pre-patch log reads the same way.
    try:
        if not logtext:
            say("p2", "N-A", "no run log given, and this line lives only in the log")
        else:
            _p2_lines = [l for l in logtext.splitlines() if "#1203p2" in l]
            _p2_pages = {l.split("register_ui_page(", 1)[1].split(")", 1)[0]
                         for l in _p2_lines if "register_ui_page(" in l}
            _p2_blocked = "page_apis_understated" in logtext
            if _p2_lines:
                say("p2", "CONFIRMED",
                    "%d omission(s) recorded over %d page(s)%s"
                    % (len(_p2_lines), len(_p2_pages),
                       " -- and `page_apis_understated` is in this run, so these are the "
                       "calls that changed nothing" if _p2_blocked else ""))
            elif _p2_blocked and "registryhub_register_ui_page" in logtext:
                say("p2", "FALSIFIED",
                    "`page_apis_understated` is in this run and pages were re-registered, "
                    "yet the #1203p2 recorder said nothing")
            else:
                say("p2", "N-A",
                    "no re-registration omitted `apis_used` in this run (the no-op #1203b0 "
                    "reports did not happen), so the returns have another cause")
    except Exception as _e_p2:
        say("p2", "N-A", "the #1203p2 criterion could not read this run (%s)" % _e_p2)

    # --- #1203p4 — a breaking change that reached no consumer must say so --------------
    # READS: shared/hubs/eventhub_events.json for the CONDITION, and the run log for the
    #   announcement. Both halves, because the condition is visible in an artifact and the
    #   answer is not: with `recipient_agents` empty the urgent event goes to nobody AND the
    #   per-consumer fix-task loop never runs, so the whole breaking change passed silently.
    # FALSIFIED: this run has `breaking_change_detected` events with an empty `recipients`
    #   and the log never says it (the pre-patch state of every run).
    # CONFIRMED: the condition held and the log names it.
    # N-A: no such event in this run, so there was nothing to announce.
    # CONTROL (pre-patch): 1,887 of 20,970 urgent events across 102 runs have empty
    #   recipients and EVERY one is this event type -- 47% of the corpus's 4,043
    #   `breaking_change_detected` events. r186 is 37 such events and 0 lines; r181 30, r185
    #   28, r184 25. Not a spelling mismatch: normalising the `/api` and `/api/v1` prefixes on
    #   both sides recovers 1 of the 1,887.
    try:
        _p4_ev = _json(run / "shared" / "hubs" / "eventhub_events.json", None)
        _p4_silent = 0
        for _k, _v in (_p4_ev or {}).items():
            if _k == "_meta" or not isinstance(_v, dict):
                continue
            if str(_v.get("event_type") or "") != "breaking_change_detected":
                continue
            if not _v.get("recipients"):
                _p4_silent += 1
        _p4_said = len([l for l in (logtext or "").splitlines() if "#1203p4" in l])
        if _p4_ev is None:
            say("p4", "N-A", "this run has no eventhub_events.json")
        elif not _p4_silent:
            say("p4", "N-A", "every breaking-change event in this run had a consumer to tell")
        elif not logtext:
            say("p4", "N-A", "%d breaking change(s) reached no consumer, but no run log was "
                "given to check whether it was said" % _p4_silent)
        else:
            say("p4", "FALSIFIED" if not _p4_said else "CONFIRMED",
                "%d breaking change(s) reached no consumer; %d announcement(s) in the log"
                % (_p4_silent, _p4_said))
    except Exception as _e_p4:
        say("p4", "N-A", "the #1203p4 criterion could not read this run (%s)" % _e_p4)

    # --- #1203p6 — the UI skills the task never named -----------------------------------
    # READS: shared/hubs/workhub_tasks.json (did the pointer land in a task body?) and
    #   shared/hubs/eventhub_events.json (did consultation move?). Both, because the pointer
    #   and its effect are different questions and this criterion exists to decide whether a
    #   GATE is warranted -- #1202w6 wants a live run before a new wall, and
    #   `preconditions.py` records what the last skill gate cost ("release-readiness gate
    #   blocked deliver_project forever").
    # CONFIRMED: a task body names the skills AND `skill_consulted` for them is above the
    #   corpus baseline of 4 per run-family -- the pointer is the lever, no wall needed.
    # FALSIFIED: a visual-remediation task was dispatched and no body names them -- the
    #   pointer did not reach the lane at all.
    # N-A (an ANSWER, not a failure): bodies name them and consultation did NOT move -- the
    #   pointer is not the lever, and a gate can be argued for with that in hand.
    # CONTROL (pre-patch): 0 of 25,903 corpus task bodies name any of the three, and each is
    #   consulted 4 times across 104 runs (vs `verification-before-completion` 9,725 and
    #   `release-readiness` 9,064, the latter the only one of the two that a precondition
    #   gates).
    _P6_SKILLS = ("frontend-design", "ui-ux-review", "ui-bootstrap")
    try:
        _p6_tasks = _json(run / "shared" / "hubs" / "workhub_tasks.json", None) or {}
        _p6_named = 0
        _p6_visual = 0
        for _k, _t in _p6_tasks.items():
            if _k == "_meta" or not isinstance(_t, dict):
                continue
            _b = " ".join(str(_t.get(f) or "") for f in ("title", "description", "how"))
            if "below the bar" in _b or "visual" in _b.lower():
                _p6_visual += 1
            if any(s in _b for s in _P6_SKILLS):
                _p6_named += 1
        _p6_ev = _json(run / "shared" / "hubs" / "eventhub_events.json", None) or {}
        _p6_used = 0
        for _k, _v in _p6_ev.items():
            if _k == "_meta" or not isinstance(_v, dict):
                continue
            if str(_v.get("event_type") or "") != "skill_consulted":
                continue
            _pl = _v.get("payload") or {}
            if str(_pl.get("skill") or _pl.get("name") or "") in _P6_SKILLS:
                _p6_used += 1
        if not _p6_tasks:
            say("p6", "N-A", "this run has no workhub_tasks.json")
        elif _p6_named and _p6_used > 4:
            say("p6", "CONFIRMED",
                "%d task body(ies) name a UI skill and they were consulted %d time(s) "
                "(corpus baseline: 4 per skill over 104 runs)" % (_p6_named, _p6_used))
        elif _p6_named:
            say("p6", "N-A",
                "%d task body(ies) name a UI skill and consultation did not move (%d) -- the "
                "pointer is not the lever; a gate can be argued for from here" % (_p6_named, _p6_used))
        elif _p6_visual:
            say("p6", "FALSIFIED",
                "%d visual/remediation task(s) and not one names a UI skill" % _p6_visual)
        else:
            say("p6", "N-A", "no visual remediation task in this run, so nothing to point at")
    except Exception as _e_p6:
        say("p6", "N-A", "the #1203p6 criterion could not read this run (%s)" % _e_p6)

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
