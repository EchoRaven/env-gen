"""Answer, from a finished run's artifacts, whether the fixes shipped on 2026-09-29 worked.

Written because the provider account hit zero credits with six behaviour changes and two
instruments landed and NONE of them verified live (r141 died at 82.7 s on
`429 insufficient_quota`). The checkpoints existed only as prose in my memory, which means
the first thing that happens when credits return is me re-deriving which file to open. That
is friction at exactly the bottleneck, so it is a command now.

Every check prints one of three verdicts and never blurs them:

    CONFIRMED   the artifact says what the fix predicted
    FALSIFIED   the artifact says the opposite -- the prediction was wrong, go read why
    NOT MEASURED  the artifact is absent or empty, so this run says NOTHING either way

The third is the one that matters. A check that cannot distinguish "looked and found
nothing" from "never looked" reports a silence as a pass, which is the defect #1202z5 fixed
one module over and the reason this script refuses to collapse them.

    python scripts/verify_shipped_fixes.py generated/tiktok-web-r142
    python scripts/verify_shipped_fixes.py --self-test

`--self-test` runs against tiktok-web-r140, which PREDATES every fix here: a run from before
the change must come back NOT MEASURED on the instrument checks. A verifier that reports
CONFIRMED for a run that could not possibly carry the fix is reading the wrong field.
"""
import json
import re
import sys
from pathlib import Path

CONFIRMED, FALSIFIED, UNMEASURED = "CONFIRMED", "FALSIFIED", "NOT MEASURED"
_W = {CONFIRMED: "\033[32m", FALSIFIED: "\033[31m", UNMEASURED: "\033[33m"}


def _say(ticket, verdict, headline, detail=""):
    c = _W.get(verdict, "")
    print("%s%-12s %-13s\033[0m %s" % (c, ticket, verdict, headline))
    for line in (detail.splitlines() if detail else []):
        print("                            %s" % line)
    return verdict            # so `--self-test` can ENFORCE what its banner claims


def _budget(run: Path) -> dict:
    p = run / "run_budget.json"
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _jsonl(run: Path, name: str) -> list:
    p = run / "logs" / name
    out = []
    try:
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                out.append(json.loads(line))
    except Exception:
        return []
    return out


# ── #1202zc: does the offered tool set stop rotating? ────────────────────────────
def check_1202zc(run):
    m = (_budget(run).get("stage_tool_sets_1202zc") or {})
    if not m:
        return _say("#1202zc", UNMEASURED,
                    "no `stage_tool_sets_1202zc` in run_budget.json",
                    "The instrument ships with the fix, so a run without it predates both.")
    rows = [(k, v) for k, v in m.items() if str(k).startswith("orchestrator")]
    if not rows:
        return _say("#1202zc", UNMEASURED, "the ledger has no orchestrator label",
                    "Labels present: " + ", ".join(sorted(m)[:6]))
    worst = max(rows, key=lambda kv: int(kv[1].get("distinct_sets") or 0))
    k, v = worst
    calls = int(v.get("calls") or 0)
    dist = int(v.get("distinct_sets") or 0)
    capped = bool(v.get("capped"))
    ratio = (dist / calls) if calls else 0.0
    detail = "\n".join(
        "%-28s calls=%-5d distinct_sets=%-4d union=%-3d capped=%s"
        % (a, int(b.get("calls") or 0), int(b.get("distinct_sets") or 0),
           int(b.get("union_size") or 0), bool(b.get("capped")))
        for a, b in sorted(rows, key=lambda kv: -int(kv[1].get("calls") or 0))[:6])
    if capped:
        return _say("#1202zc", FALSIFIED,
                    "the 32-tool cap BOUND on %s — the union is wider than the corpus "
                    "predicted (largest measured per-stage usage was 25)" % k, detail)
    if dist <= 2:
        return _say("#1202zc", CONFIRMED,
                    "the menu converged: %s saw %d distinct sets over %d calls"
                    % (k, dist, calls), detail)
    if ratio > 0.5:
        return _say("#1202zc", FALSIFIED,
                    "%s still rotates: %d distinct sets over %d calls (%.0f%%)"
                    % (k, dist, calls, 100 * ratio), detail)
    return _say("#1202zc", CONFIRMED,
                "%s converged partially: %d distinct sets over %d calls" % (k, dist, calls),
                detail)


# ── #1202za: which tool repeats itself? ──────────────────────────────────────────
def check_1202za(run):
    d = (_budget(run).get("dedup_saved_1191") or {})
    split = d.get("by_tool_1202za") or {}
    if not split:
        return _say("#1202za", UNMEASURED, "no `by_tool_1202za` split in run_budget.json")
    rows = [(k, v) for k, v in split.items() if not str(k).startswith("_")]
    if not rows:
        return _say("#1202za", UNMEASURED, "the split is present but empty")
    top, tv = max(rows, key=lambda kv: int(kv[1].get("bytes") or 0))
    total = sum(int(v.get("bytes") or 0) for _, v in rows) or 1
    share = 100.0 * int(tv.get("bytes") or 0) / total
    detail = "\n".join("%-30s calls=%-4d bytes=%d"
                       % (a, int(b.get("calls") or 0), int(b.get("bytes") or 0))
                       for a, b in sorted(rows, key=lambda kv: -int(kv[1].get("bytes") or 0))[:6])
    headline = ("one tool dominates: %s is %.0f%% of the dedup saving over %d calls — that is "
                "a poll of state that is not moving" % (top, share, int(tv.get("calls") or 0))
                if share >= 60 else
                "the saving is spread over %d tools; no single poll dominates" % len(rows))
    return _say("#1202za", CONFIRMED, headline, detail)


# ── #1202zb / #1202ze / #1202zf: did the new reporters fire? ─────────────────────
_RUNLOG_CACHE_1203R8 = {}


def _runlog_1203r8(run) -> str:
    """The run's own log text, concatenated, or "" when none is on disk.

    #1203r8: this file used to tell the reader "read the run log for the ticket id to
    decide", and then not read it -- while holding the run directory the log lives in. The
    log needs no new flag; it is `<run>/logs/*.log`."""
    key = str(run)
    if key not in _RUNLOG_CACHE_1203R8:
        parts = []
        try:
            for f in sorted((Path(run) / "logs").glob("*.log")):
                try:
                    parts.append(f.read_text(encoding="utf-8", errors="ignore"))
                except Exception:
                    pass
        except Exception:
            pass
        _RUNLOG_CACHE_1203R8[key] = "\n".join(parts)
    return _RUNLOG_CACHE_1203R8[key]


def _reporter(run, ticket, artifact, what, expect_measured_key=None,
              unmeasured_says=None):
    rows = _jsonl(run, artifact)
    if not rows:
        # #1203r8: AN ABSENT ARTIFACT IS TWO DIFFERENT ANSWERS, AND THE CODE SAYS WHICH.
        #
        # These reporters write only when they have findings, and when they CANNOT measure
        # they announce it through `warn_once_1201`. So "no artifact" means either "measured,
        # found nothing" or "never measured" -- and the second one leaves a sentence in the
        # log. This used to print "this file cannot tell them apart -- read the run log",
        # which was true only because the file declined to read a log it already had.
        #
        # Measured over 107 runs for #1202zb: the artifact exists in ZERO of them, which next
        # to siblings firing in 15-38 runs each reads like a reporter that shipped disabled.
        # It did not. The announcement `unreachable-twin-table check could not run (no live
        # row counts from this validation cycle)` appears in exactly 3 runs, and
        # `warn_once_1201` speaks once per process -- so 3 runs could not measure and SAID
        # so, and the other 104 measured and genuinely found nothing.
        #
        # Absence of the announcement is reported as CONFIRMED for an INSTRUMENT ticket,
        # because running and finding nothing is what a working reporter looks like. It is
        # never inferred from silence alone: without a log on disk the old ambiguity stands
        # and the verdict stays UNMEASURED (#1202z5 -- a check that cannot tell "looked and
        # found nothing" from "never looked" reports a silence as a pass).
        _log = _runlog_1203r8(run) if unmeasured_says else ""
        if unmeasured_says and _log:
            _n = _log.count(unmeasured_says)
            if _n:
                return _say(ticket, UNMEASURED,
                            "no logs/%s, and the probe ANNOUNCED it could not measure "
                            "(%d line(s))" % (artifact, _n),
                            "so this run says nothing about %s -- the probe never got a "
                            "reading, which is a different answer from finding none" % what)
            return _say(ticket, CONFIRMED,
                        "no logs/%s, and NO 'could not measure' announcement in %d log "
                        "line(s)" % (artifact, _log.count("\n") + 1),
                        "the probe ran and found no %s. Absence of the artifact is a "
                        "finding of zero here, not a silence: these reporters write only "
                        "when they have findings and announce it when they cannot measure."
                        % what)
        return _say(ticket, UNMEASURED, "no logs/%s" % artifact,
                    "Either the check found nothing at every cut, or it never ran. The two "
                    "are not the same and this file cannot tell them apart -- no run log on "
                    "disk to decide from (#1203r8 reads it when there is one).")
    if expect_measured_key:
        blind = [r for r in rows if r.get(expect_measured_key) is False]
        if blind and len(blind) == len(rows):
            return _say(ticket, UNMEASURED,
                        "%d record(s), every one with %s=false"
                        % (len(rows), expect_measured_key),
                        "why: " + str(rows[-1].get("why") or "(not recorded)"))
    last = rows[-1]
    n = last.get("count")
    detail = json.dumps(last, ensure_ascii=False)[:300]
    return _say(ticket, CONFIRMED,
                "%d record(s); latest reports %s %s" % (len(rows), n, what), detail)


def check_1202zb(run):
    return _reporter(run, "#1202zb", "unreachable_twin_table_1202zb.jsonl",
                     "table(s) holding rows no endpoint reads", "measured",
                     # the exact sentence heal_pipeline emits when it has no row counts --
                     # matched on the EMITTED text, never on the ticket id, because a lane
                     # grepping for the id puts the id in the log (12 such lines for the
                     # sibling marker `SEED SHORTFALL`, every one a search, not a sighting).
                     unmeasured_says="unreachable-twin-table check could not run")


def check_1202ze(run):
    return _reporter(run, "#1202ze", "gate_passed_while_smoke_failed_1202ze.jsonl",
                     "gate pass(es) carrying a false smoke signal")


def check_1202zf(run):
    rows = _jsonl(run, "unstaged_seed_media_1202xn.jsonl")
    if not rows:
        return _say("#1202zf", UNMEASURED, "no logs/unstaged_seed_media_1202xn.jsonl")
    # the ledger is written at SCAFFOLD time too, and #1202zf's own finding is the one that
    # survives to delivery -- so the question is whether the delivered tree still lacks them.
    fe = run / "app" / "frontend" / "public"
    refs = set()
    for r in rows:
        for m in (r.get("rows") or r.get("media") or []):
            u = str(m).split(" (")[0]
            if u.startswith("/assets/"):
                refs.add(u)
    still = sorted(u for u in refs if not (fe / u.lstrip("/")).is_file())
    if not still:
        return _say("#1202zf", CONFIRMED,
                    "%d media ref(s) were reported during the run and ALL are on disk now — "
                    "the scaffold-time reports were transient, as #1202zf predicted"
                    % len(refs))
    return _say("#1202zf", FALSIFIED,
                "%d of %d reported media ref(s) are STILL missing from the delivered tree"
                % (len(still), len(refs)),
                "\n".join("  - " + u for u in still[:8]))


# ── #1202zd: does the projected store return the app's columns? ──────────────────
def check_1202zd(run):
    p = run / "app" / "backend" / "oauth_store.py"
    try:
        src = p.read_text(encoding="utf-8")
    except Exception:
        return _say("#1202zd", UNMEASURED, "no app/backend/oauth_store.py in this run")
    if "RETURNING id, email, name, tenant_id" in src:
        return _say("#1202zd", FALSIFIED,
                    "the store still carries the FIXED four-column RETURNING",
                    "`user.username` cannot come back; the run predates #1202zd or the "
                    "template did not reach this tree.")
    if "_json_safe_row_1202zd" not in src:
        return _say("#1202zd", FALSIFIED,
                    "RETURNING is no longer the fixed four, but the row coercion is absent",
                    "A `timestamp` column will reach `json.dumps` and register will 500.")
    return _say("#1202zd", CONFIRMED,
                "the store derives RETURNING from the live table and coerces the row",
                "Next: curl POST /auth/register on the running stack — expect 200 and a "
                "`user.username`, then re-count `save FAILED` in the chain records.")


# ── the cost picture the tool-menu fix is supposed to move ───────────────────────
def check_cost(run):
    b = _budget(run)
    llm = b.get("llm") or {}
    unc = int(llm.get("uncached") or 0)
    cached = int(llm.get("cached") or 0)
    usd = float(llm.get("usd") or 0.0)
    if not (unc or cached):
        return _say("cost", UNMEASURED, "run_budget.json carries no llm token counts")
    share = 100.0 * unc / max(1, unc + cached)
    return _say("cost", CONFIRMED,
                "$%.2f | uncached %s of %s prompt tokens (%.0f%%)"
                % (usd, f"{unc:,}", f"{unc + cached:,}", share),
                "r140's baseline before #1202zc: compare this share, not the dollar total — "
                "a longer run costs more at the same efficiency.")


# ── --live: what a RUNNING stack and the gate ledgers can verify with no credits ──
#
# Four of the six fixes shipped 2026-09-29 never needed the model, only artifacts. Written as a
# mode because the technique is worth more than the one-off: ask of each fix which part needs
# the MODEL and which part only needs what is already on disk or already up.
def live_1202zd(run):
    """Execute the SHIPPED RETURNING + coercion against the run's live database, then roll back.

    The coercion is compiled out of the template with `ast` rather than retyped — testing a copy
    proves nothing about what ships.
    """
    import ast as _ast
    import json as _json
    try:
        import psycopg
        from psycopg.rows import dict_row
    except Exception as exc:
        return _say("#1202zd live", UNMEASURED, "psycopg unavailable: %s" % exc)
    port = _compose_db_port(run)
    if not port:
        return _say("#1202zd live", UNMEASURED,
                    "no database port in docker/docker-compose.yml — read the port from"
                    " compose, never from `docker ps`")
    tmpl = (Path(__file__).resolve().parent.parent / "agent" / "env_generator" /
            "llm_generator" / "multi_agent" / "runtime" / "oauth_as_templates" /
            "oauth_store.py.tmpl")
    try:
        src = tmpl.read_text(encoding="utf-8")
        fn = [n for n in _ast.walk(_ast.parse(src))
              if isinstance(n, _ast.FunctionDef) and n.name == "_json_safe_row_1202zd"]
        if not fn:
            return _say("#1202zd live", FALSIFIED,
                        "the row coercion is gone from the shipped template")
        mod = _ast.Module(body=[fn[0]], type_ignores=[]); _ast.fix_missing_locations(mod)
        ns = {}
        exec(compile(mod, "<tmpl>", "exec"), ns)          # noqa: S102
        coerce = ns["_json_safe_row_1202zd"]
    except Exception as exc:
        return _say("#1202zd live", UNMEASURED, "could not compile the coercion: %s" % exc)
    dsn = ("host=127.0.0.1 port=%s user=sandbox password=sandbox dbname=app "
           "connect_timeout=8" % port)
    try:
        conn = psycopg.connect(dsn, row_factory=dict_row)
    except Exception as exc:
        return _say("#1202zd live", UNMEASURED,
                    "the stack is not up on :%s (%s)" % (port, type(exc).__name__))
    try:
        cur = conn.cursor()
        cur.execute("SELECT column_name FROM information_schema.columns "
                    "WHERE table_name='users'")
        existing = {r["column_name"] for r in cur.fetchall()}
        if not existing:
            return _say("#1202zd live", UNMEASURED, "no users table in the live database")
        secret = ("password", "secret", "token", "api_key")
        ret = [c for c in ("id", "email", "name", "tenant_id") if c in existing]
        ret += sorted(c for c in existing if c not in ret
                      and not any(w in str(c).lower() for w in secret))
        cols = {"email": "probe_1202zd@localhost.invalid", "name": "probe",
                "password_hash": "x", "tenant_id": "default"}
        if "username" in existing:
            cols["username"] = "probe_1202zd"
        cols = {k: v for k, v in cols.items() if k in existing}
        sql = 'INSERT INTO users ({}) VALUES ({}) RETURNING {}'.format(
            ", ".join('"%s"' % c for c in cols), ", ".join(["%s"] * len(cols)),
            ", ".join('"%s"' % c for c in ret))
        cur.execute(sql, tuple(cols.values()))
        row = cur.fetchone()
        raw_fails = False
        try:
            _json.dumps(row)
        except TypeError:
            raw_fails = True
        _json.dumps(coerce(row))                          # must not raise
        detail = ("RETURNING %d columns; username=%r; raw json.dumps %s; after the shipped "
                  "coercion it serialises"
                  % (len(ret), row.get("username"),
                     "RAISES (the 500 this prevents)" if raw_fails else "happens to work"))
        if "username" in existing and not row.get("username"):
            return _say("#1202zd live", FALSIFIED,
                        "the table has `username` and the insert did not return it", detail)
        return _say("#1202zd live", CONFIRMED,
                    "the shipped path runs against the real schema", detail)
    except Exception as exc:
        return _say("#1202zd live", FALSIFIED,
                    "the shipped path FAILED against the real schema: %s: %s"
                    % (type(exc).__name__, exc))
    finally:
        try:
            conn.rollback(); conn.close()                 # the live app stays untouched
        except Exception:
            pass


def _compose_db_port(run):
    """The db host port, from compose. #feedback: never `docker ps | grep`."""
    import re as _re
    p = Path(run) / "docker" / "docker-compose.yml"
    try:
        text = p.read_text(encoding="utf-8")
    except Exception:
        return None
    best = None
    for m in _re.finditer(r'"?(\d{4,5}):(\d{4,5})"?', text):
        host, cont = m.group(1), m.group(2)
        if cont == "5432" or host == cont:
            best = best or host
    return best


def live_1202ze(_run):
    """Replay every REAL gate record on disk through the shipped reporter.

    The reporter is a pure function of the gate dict, so it never needed the gate to RUN — it
    needed gate OUTPUT, and thousands of those are already in `logs/delivery_gate.jsonl`.
    """
    import json as _json
    import tempfile as _tf
    # BOTH levels: the orchestrator imports `multi_agent.*` (from llm_generator/) and
    # `utils.*` (from agent/). Missing the second is an ImportError, which this check
    # correctly reported as NOT MEASURED rather than as a pass.
    _agent = Path(__file__).resolve().parent.parent / "agent"
    for _p in (str(_agent / "env_generator" / "llm_generator"), str(_agent)):
        if _p not in sys.path:
            sys.path.insert(0, _p)
    try:
        import multi_agent.orchestrator as O
    except Exception as exc:
        return _say("#1202ze live", UNMEASURED, "cannot import the reporter: %s" % exc)

    class _WH:
        def __init__(self):
            self.tasks, self.created = [], []
        def list_tasks(self):
            return self.tasks
        def create_task(self, **kw):
            self.created.append(kw)
            rec = {"id": "t%d" % len(self.created), "status": "pending", **kw}
            self.tasks.append(rec)
            return rec

    class _Orch:
        def __init__(self, wh, out):
            class _H:
                workhub = wh
            self.hubs, self.output_dir = _H(), str(out)

    gen = Path(__file__).resolve().parent.parent / "generated"
    total = ok = fired = tasks = runs = 0
    with _tf.TemporaryDirectory() as td:
        for ledger in sorted(gen.glob("*/logs/delivery_gate.jsonl")):
            wh = _WH(); out = Path(td) / ledger.parts[-3]
            orch = _Orch(wh, out)
            for line in ledger.read_text(encoding="utf-8", errors="ignore").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    gate = _json.loads(line)
                except Exception:
                    continue
                total += 1
                if gate.get("ok"):
                    ok += 1
                O._gate_cleared_while_smoke_failed_1202ze(orch, gate)
            art = out / "logs" / "gate_passed_while_smoke_failed_1202ze.jsonl"
            if art.exists():
                fired += len([l for l in art.read_text(encoding="utf-8").splitlines()
                              if l.strip()])
                runs += 1
            tasks += len(wh.created)
    if not total:
        return _say("#1202ze live", UNMEASURED, "no gate ledgers under generated/")
    return _say("#1202ze live", CONFIRMED,
                "%d real gate records replayed; %d with ok=true; the reporter fired on %d"
                % (total, ok, fired),
                "tasks filed: %d across %d run(s) — one per run is the storm control (#794) "
                "holding on inputs I did not construct" % (tasks, runs))



def live_1202zb(run):
    """Run the twin detector against the DELIVERED stack's own row counts.

    #1202zb abstains without live counts, on purpose: `recent_live_counts_1202dj` refuses
    anything past its TTL because the stack is torn down and rebuilt around each validation,
    and a stale count would describe a different database. That honesty means a finished run
    directory can never confirm it -- the counts have expired by the time anyone asks. So this
    check goes to the source the detector would have used: the container that is still up.

    On tiktok-web-r140 this reports `videos` (35 rows, unread) against `feed` (8 rows, served
    via `/api/feed`) -- the exact pair the ticket was written for, and the reason 35 of the
    delivered app's rows have no interface that reaches them.
    """
    import json as _json
    import subprocess as _sp
    _agent = Path(__file__).resolve().parent.parent / "agent"
    for _p in (str(_agent / "env_generator" / "llm_generator"), str(_agent)):
        if _p not in sys.path:
            sys.path.insert(0, _p)
    try:
        import multi_agent.runtime.heal_pipeline as HP
        # The detector re-imports the counts reader from `seed_audit` INSIDE its body, so the
        # name it resolves is that module's, not `heal_pipeline`'s. Patching only the latter
        # left it abstaining, and the check said so instead of passing -- which is the whole
        # reason it reports NOT MEASURED as a third outcome.
        import multi_agent.runtime.seed_audit as SA
    except Exception as exc:
        return _say("#1202zb live", UNMEASURED, "cannot import the detector: %s" % exc)
    eps_p = Path(run) / "shared" / "hubs" / "registryhub_endpoints.json"
    if not eps_p.is_file():
        return _say("#1202zb live", UNMEASURED, "no endpoint registry in %s" % run)
    name = Path(run).name + "-database-1"
    try:
        # read-only: one SELECT against pg's own statistics view, no schema touched
        raw = _sp.check_output(
            ["docker", "exec", name, "sh", "-c",
             'psql -U sandbox -d app -tAc '
             '"select relname||chr(61)||n_live_tup from pg_stat_user_tables"'],
            stderr=_sp.DEVNULL, timeout=60).decode("utf-8", "replace")
    except Exception as exc:
        return _say("#1202zb live", UNMEASURED,
                    "the delivered stack is not reachable (%s): %s"
                    % (name, type(exc).__name__))
    counts = {}
    for ln in raw.splitlines():
        if "=" in ln:
            k, v = ln.split("=", 1)
            try:
                counts[k.strip()] = int(v)
            except ValueError:
                pass
    if not counts:
        return _say("#1202zb live", UNMEASURED, "the database returned no row counts")
    SA.recent_live_counts_1202dj = lambda _r: counts
    HP.recent_live_counts_1202dj = lambda _r: counts

    class _RH:
        def get_endpoints(self):
            return _json.loads(eps_p.read_text(encoding="utf-8"))

        def get_tables(self):
            return {}

    out = HP._unreachable_twin_tables_1202zb(str(run), _RH())
    if not out.get("measured"):
        return _say("#1202zb live", UNMEASURED,
                    "the detector abstained: %s" % out.get("why"))
    fs = out.get("findings") or []
    if not fs:
        return _say("#1202zb live", UNMEASURED,
                    "measured against %d live tables and found no unreachable twin -- "
                    "that is a fact about THIS stack, not about the detector" % len(counts))
    return _say("#1202zb live", CONFIRMED,
                "on real row counts from the running stack: "
                + "; ".join("%s(%s rows, unread) vs %s(%s rows, served via %s)"
                            % (f.get("unread"), f.get("unread_rows"), f.get("served"),
                               f.get("served_rows"), f.get("via")) for f in fs[:3]))

# ── the 2026-09-30 batch ─────────────────────────────────────────────────────────

def check_1202zt(run):
    """Does the DELIVERED middleware refuse to call a missing route an auth failure?"""
    p = run / "app" / "backend" / "main.py"
    try:
        src = p.read_text(encoding="utf-8")
    except Exception:
        return _say("#1202zt", UNMEASURED, "no app/backend/main.py in this run")
    if "_fw_route_exists_1202zt" not in src:
        return _say("#1202zt", FALSIFIED,
                    "the projected guard has no route-existence check",
                    "An unknown /api/ path still answers 401. The run predates #1202zt or the "
                    "skeleton did not render this main.py.")
    if "return await call_next(request)" not in src:
        return _say("#1202zt", FALSIFIED,
                    "the check is present but nothing falls through to FastAPI's 404")
    return _say("#1202zt", CONFIRMED,
                "the guard checks for a matching route before refusing",
                "Next: curl an invented /api/ path on the running stack — expect 404, and 401 "
                "on a real protected one.")


def check_1202zn(run):
    """Is a contract-public feed read projected WITHOUT an actor?

    #1202zn releases the shape demotion for a feed-named table the materials never described.
    The observable is the delivered handler: a released read takes no `get_current_user`, and the
    path reaches `_FW_PUBLIC_API_1202KH` because the skeleton emits that list from the same auth
    decision. r140 shows the pre-fix state — the list is EMPTY while `GET /api/feed` is declared
    `auth_required=false`.
    """
    import json as _json
    import re as _re
    p = run / "app" / "backend" / "main.py"
    eps = run / "shared" / "hubs" / "registryhub_endpoints.json"
    try:
        src = p.read_text(encoding="utf-8")
        recs = _json.loads(eps.read_text(encoding="utf-8"))
    except Exception:
        return _say("#1202zn", UNMEASURED, "no main.py or endpoint registry in this run")
    feeds = []
    for k, v in recs.items():
        if str(k).startswith("_") or not isinstance(v, dict):
            continue
        path = str(v.get("path") or "")
        md, sch = v.get("metadata") or {}, v.get("schema") or {}
        if md.get("auth_required", sch.get("auth_required")) is not False:
            continue
        if str(v.get("method") or "").upper() != "GET":
            continue
        if "feed" in path or "explore" in path or "timeline" in path:
            feeds.append(path)
    if not feeds:
        return _say("#1202zn", UNMEASURED,
                    "this run declares no public GET on a feed-shaped path — nothing to release")
    m = _re.search(r"_FW_PUBLIC_API_1202KH = \[(.*?)\]", src, _re.S)
    listed = m.group(1) if m else ""
    missing = [f for f in feeds if f not in listed]
    if missing:
        return _say("#1202zn", FALSIFIED,
                    "%d contract-public feed read(s) are absent from the guard's public list: %s"
                    % (len(missing), ", ".join(missing[:4])),
                    "That is r140's exact pre-fix state — the shape demoted it at skeleton time, "
                    "so the path was never public to the middleware.")
    return _say("#1202zn", CONFIRMED,
                "every contract-public feed read is in the guard's public list (%d)" % len(feeds),
                "Next: curl it tokenless on the running stack — expect 200, not 401.")


def check_1202zq(run):
    """When a gate field was capped, did the ledger keep the VERDICT rather than the dump?"""
    rows = _jsonl(run, "delivery_gate.jsonl")
    if not rows:
        return _say("#1202zq", UNMEASURED, "no logs/delivery_gate.jsonl")
    capped = [r.get("deliverability") for r in rows
              if isinstance(r.get("deliverability"), dict)
              and "_truncated_948" in r["deliverability"]]
    if not capped:
        return _say("#1202zq", UNMEASURED,
                    "%d gate records and none of them capped `deliverability` — the cap never "
                    "bound, so this run says nothing either way" % len(rows))
    kept = [c for c in capped if isinstance(c.get("_kept_1202zq"), dict)]
    if not kept:
        return _say("#1202zq", FALSIFIED,
                    "%d capped record(s) still carry a byte `head` and no `_kept_1202zq`"
                    % len(capped),
                    "The run predates #1202zq: the verdict is in the part that was cut.")
    with_verdict = [k for k in kept if "verdict" in (k.get("_kept_1202zq") or {})]
    return _say("#1202zq",
                CONFIRMED if with_verdict else FALSIFIED,
                "%d of %d capped record(s) kept the deliverability verdict"
                % (len(with_verdict), len(capped)),
                "`_dropped_1202zq` names what went, so the cap can be audited.")


def check_1202zr(run):
    """If a Contract note named a WRITE, did it refuse to call it a public read?"""
    rows = _jsonl(run, "delivery_gate.jsonl")
    if not rows:
        return _say("#1202zr", UNMEASURED, "no logs/delivery_gate.jsonl")
    notes = []
    for r in rows:
        bp = r.get("blocker_prose")
        if not isinstance(bp, dict):
            continue
        for v in (bp.get("deliverability_ui_flow_failed") or []):
            if "Contract note" in str(v):
                notes.append(str(v))
    if not notes:
        return _say("#1202zr", UNMEASURED,
                    "no Contract note in this run's gate ledger — the branch never ran")
    writes = [n for n in notes
              if any(("-> %s " % m) in n for m in ("POST", "PUT", "PATCH", "DELETE"))]
    if not writes:
        return _say("#1202zr", UNMEASURED,
                    "%d Contract note(s), none naming a write — nothing to qualify" % len(notes))
    good = [n for n in writes if "name a WRITE" in n]
    return _say("#1202zr",
                CONFIRMED if len(good) == len(writes) else FALSIFIED,
                "%d of %d note(s) naming a write carry the write caveat"
                % (len(good), len(writes)),
                "A note that tells a lane to publish a POST is the defect #1202zr removed.")


LIVE_CHECKS = [live_1202zd, live_1202ze, live_1202zb]

# ── 2026-10-01 session: #1203a3 .. #1203a9 ──────────────────────────────────────
#
# Each of these reads the DELIVERED artifacts, so the next run answers them in one command
# instead of the investigation they each took. UNMEASURED is the honest verdict when the
# precondition is absent, and every headline says which it was.

def _hub(run: Path, name: str) -> dict:
    try:
        return json.loads((run / "shared" / "hubs" / name).read_text(encoding="utf-8"))
    except Exception:
        return {}


def _pages_src(run: Path) -> dict:
    """`{component: source}` for the delivered page files."""
    out = {}
    base = run / "app" / "frontend" / "src"
    for sub in ("pages", "components"):
        d = base / sub
        if not d.is_dir():
            continue
        for f in sorted(d.glob("*.jsx")) + sorted(d.glob("*.tsx")):
            try:
                out[f.stem] = f.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
    return out


def check_1203a3(run):
    """Does the MCP surface still advertise the fixed auth endpoints as business tools?"""
    reg = _hub(run, "registryhub_mcp_registry.json")
    tools = [k.split(":")[-1] for k in reg if str(k).startswith("mcp:tool:")]
    if not tools:
        return _say("#1203a3", UNMEASURED, "no MCP tools in registryhub_mcp_registry.json")
    bad = [t for t in tools
           if re.search(r"(^|_)(auth|oauth)(_|$)|_(signup|signin|logout|login|register)$", t)]
    return _say("#1203a3", FALSIFIED if bad else CONFIRMED,
                "%d MCP tool(s) on the fixed auth surface, of %d" % (len(bad), len(tools)),
                ("Still advertised: %s" % ", ".join(sorted(bad)[:6])) if bad else
                "The agent-facing surface is business endpoints only.")


def check_1203a5(run):
    """Was a page that delegates through `React.lazy` called a placeholder stub?"""
    rows = _jsonl(run, "delivery_gate.jsonl")
    if not rows:
        return _say("#1203a5", UNMEASURED, "no logs/delivery_gate.jsonl")
    src = _pages_src(run)
    lazy = {c for c, t in src.items()
            if re.search(r"lazy\s*\(\s*\(\s*\)\s*=>\s*import\s*\(", t)}
    if not lazy:
        return _say("#1203a5", UNMEASURED,
                    "no delivered page uses `lazy(() => import(...))` — the shape this fix is "
                    "about never occurred")
    flagged = set()
    for r in rows:
        for pr in (r.get("blocker_prose") or {}).get("deliverability_ui_page_unwired") or []:
            for c in lazy:
                if c in str(pr) and "placeholder stub" in str(pr):
                    flagged.add(c)
    return _say("#1203a5", FALSIFIED if flagged else CONFIRMED,
                "%d lazy-delegating page(s); %d called a placeholder stub"
                % (len(lazy), len(flagged)),
                ("Flagged: %s. EITHER this run predates #1203a5 (r142 itself does — it is the "
                 "run the fix was derived from, and its 149 gate records are what proved it) OR "
                 "the override regressed. Tell them apart by the run's date against the "
                 "#1203a5 commit, the way #1202zq's check does."
                 % ", ".join(sorted(flagged))) if flagged else
                "Composition through a dynamic import is credited.")


def check_1203a6(run):
    """Does an auth-flow verdict carry its own grounds, and name a dead backend separately?"""
    reports = sorted((run / "test_user_reports").glob("*.json")) \
        if (run / "test_user_reports").is_dir() else []
    flows = []
    for f in reports:
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        uf = d.get("ui_flows") or {}
        flows.extend(uf.get("flows") or [] if isinstance(uf, dict) else [])
    if not flows:
        return _say("#1203a6", UNMEASURED, "no ui_flows in test_user_reports/")
    grounded = [f for f in flows if "url" in f and "auth_requests" in f]
    wired_but_down = [f for f in flows if "the form IS wired" in str(f.get("note") or "")]
    if not grounded:
        return _say("#1203a6", FALSIFIED,
                    "%d flow record(s) and none carries `url`/`auth_requests`" % len(flows),
                    "The run predates #1203a6: its 'not wired' verdicts cannot be audited.")
    return _say("#1203a6", CONFIRMED,
                "%d of %d flow record(s) carry their grounds; %d named an unreachable backend "
                "instead of a dead form" % (len(grounded), len(flows), len(wired_but_down)))


def check_1203a7(run):
    """When an inert page was flagged, did the note say WHICH of the three things was true?"""
    rows = _jsonl(run, "delivery_gate.jsonl")
    # DEDUPED BY SENTENCE. The gate re-evaluates every tick, so a run that flags two pages
    # 24 times each yields 48 prose entries; reporting that as "48 flagged pages" is the
    # category-for-instance confusion this project has a ticket about (#1202sr).
    proses = set()
    for r in rows:
        for pr in (r.get("blocker_prose") or {}).get("deliverability_ui_page_unwired") or []:
            proses.add(str(pr))
    if not proses:
        return _say("#1203a7", UNMEASURED, "no ui_page_unwired prose in this run")
    split = {p for p in proses
             if "RENDERS UI but never calls" in p or "is a REDIRECT" in p}
    stub = {p for p in proses if "placeholder stub" in p}
    if not split and stub:
        return _say("#1203a7", UNMEASURED,
                    "%d distinct flagged page(s), all carrying the blanket stub sentence — "
                    "either they are genuinely JSX-less (then it is correct) or this run "
                    "predates #1203a7" % len(stub))
    return _say("#1203a7", CONFIRMED if split else UNMEASURED,
                "%d of %d distinct flagged page(s) got a cause-specific note"
                % (len(split), len(proses)))


def check_1203a8(run):
    """Could the gate SEE a lazy-delegating page's endpoints, or did it go silent on them?

    ★ Like #1203a9's first version, an earlier draft re-ran today's resolver and so could only
    confirm. The artifact signal is the gate's own prose: before the fix, a page that delegates
    only through `lazy(() => import(...))` resolved to [] and `page_apis_understated` could not
    name it; after, it either names it or the page declares everything its subtree calls.
    """
    src = _pages_src(run)
    lazy = {c for c, t in src.items()
            if re.search(r"lazy\s*\(\s*\(\s*\)\s*=>\s*import\s*\(", t)
            and not re.search(r"import\s+[A-Z]\w*\s+from\s+['\"]\.", t)}
    if not lazy:
        return _say("#1203a8", UNMEASURED,
                    "no delivered page delegates ONLY through a dynamic import")
    rows = _jsonl(run, "delivery_gate.jsonl")
    if not rows:
        return _say("#1203a8", UNMEASURED, "no logs/delivery_gate.jsonl")
    named = set()
    for r in rows:
        for pr in (r.get("blocker_prose") or {}).get(
                "deliverability_page_apis_understated") or []:
            for c in lazy:
                if c in str(pr):
                    named.add(c)
    pages = _hub(run, "registryhub_ui_pages.json")
    declared = {}
    for k, v in pages.items():
        if k == "_meta" or not isinstance(v, dict):
            continue
        comp = str(v.get("component") or "")
        if comp in lazy:
            declared[comp] = list(v.get("apis_used")
                                  or (v.get("metadata") or {}).get("apis_used") or [])
    silent = sorted(c for c in lazy if c not in named)
    if not silent:
        return _say("#1203a8", CONFIRMED,
                    "%d lazy-only page(s), every one of them named by "
                    "`page_apis_understated`" % len(lazy))
    return _say("#1203a8", UNMEASURED,
                "%d lazy-only page(s); the gate never named %d of them"
                % (len(lazy), len(silent)),
                "Silent on: %s (declared: %s). That is EITHER the resolver blind (pre-#1203a8) "
                "OR those pages already declare everything their subtree calls — this artifact "
                "cannot separate the two, so it is not a verdict."
                % (", ".join(silent[:5]),
                   "; ".join("%s=%d" % (c, len(declared.get(c, []))) for c in silent[:5])))


def check_1203a9(run):
    """Does the DELIVERED feed handler query the data table rather than a column-identical copy?

    ★ The first version of this check re-ran today's `_resource_model` against the run's models,
    so it answered "is the current code right?" and CONFIRMED on r140 — a run that predates the
    fix. `--self-test` caught it. A verification of a DELIVERED artifact has to read the
    artifact: the projected handler names the model class it queries.
    """
    be = run / "app" / "backend"
    try:
        main = (be / "main.py").read_text(encoding="utf-8", errors="replace")
        models_src = (be / "models.py").read_text(encoding="utf-8", errors="replace")
    except Exception:
        return _say("#1203a9", UNMEASURED, "no delivered app/backend/main.py")
    # table -> ORM class, from the delivered models module
    cls_of = {}
    for m in re.finditer(r"class\s+(\w+)\s*\([^)]*\)\s*:\s*(?:#[^\n]*)?\n(?:\s+[^\n]*\n)*?"
                         r"\s+__tablename__\s*=\s*['\"](\w+)['\"]", models_src):
        cls_of[m.group(2)] = m.group(1)
    feeds = [t for t in cls_of if re.search(r"(^|_)(feed|feeds|explore|timeline|reels|discover"
                                            r"|stream|streams)(_|$)", t.lower())]
    if not feeds:
        return _say("#1203a9", UNMEASURED, "the delivered schema has no feed-shaped table")
    hits = []
    for t in feeds:
        k = main.find('"/api/%s"' % t)
        if k < 0:
            k = main.find("'/api/%s'" % t)
        if k < 0:
            continue
        seg = main[k:k + 1600]
        queried = set(re.findall(r"\bdb\.query\(\s*(\w+)", seg))
        if cls_of[t] in queried:
            hits.append("%s -> db.query(%s)" % (t, cls_of[t]))
    if not hits:
        return _say("#1203a9", UNMEASURED,
                    "no projected GET on a feed-shaped path in the delivered main.py "
                    "(%d feed-shaped table(s) exist)" % len(feeds))
    # Is that table a column-identical copy of another one in the SAME delivered schema?
    def _cols_of(cls):
        m = re.search(r"class\s+%s\s*\([^)]*\)\s*:(.*?)(?=\nclass\s|\Z)" % re.escape(cls),
                      models_src, re.S)
        if not m:
            return ()
        return tuple(sorted(set(re.findall(r"^\s+(\w+)\s*=\s*Column\(", m.group(1), re.M))))
    bad = []
    for h in hits:
        t = h.split(" -> ")[0]
        own = _cols_of(cls_of[t])
        if len(own) < 6:
            continue
        for other, ocls in cls_of.items():
            if other == t:
                continue
            if re.search(r"(^|_)(feed|feeds|explore|timeline|reels|discover|stream|streams)(_|$)",
                         other.lower()):
                continue
            if _cols_of(ocls) == own:
                bad.append("%s (column-identical to %s)" % (h, other))
                break
    if not bad:
        return _say("#1203a9", CONFIRMED,
                    "%d feed-shaped route(s) projected, none of them onto a column-identical "
                    "copy of a data table" % len(hits))
    return _say("#1203a9", FALSIFIED,
                "%d delivered feed route(s) query a column-identical copy" % len(bad),
                "\n".join("  - %s" % b for b in bad)
                + "\nThe run predates #1203a9, or the override regressed.")


# ── 2026-10-14 session: #1203ja .. #1203jk ──────────────────────────────────────
#
# Thirteen changes landed with ZERO live verification (the $1000 authorisation was spent
# before any of them existed), and the predictions for them were prose in memory. That is
# the friction this file's own header names: "the first thing that happens when credits
# return is me re-deriving which file to open".
#
# ★ EVERY CHECK BELOW IS GATED ON `_has_1014_1203ja`, and that is what makes the
# `--self-test` meaningful for them. The marker is `summary.ui_walk_ran_1203je`, a field
# that did not exist before 2026-10-14, so a run that predates the batch answers NOT
# MEASURED instead of confirming on an artifact it happens to share.

def _reports_1203ja(run: Path) -> list:
    """Every per-version test-user report, newest version last. [] when there are none."""
    d = run / "test_user_reports"
    out = []
    try:
        for f in sorted(d.glob("*.json")):
            if not re.match(r"^\d+\.\d+\.\d+$", f.stem):
                continue
            try:
                out.append((f.stem, json.loads(f.read_text(encoding="utf-8"))))
            except Exception:
                continue
    except Exception:
        return []
    return sorted(out, key=lambda kv: tuple(int(x) for x in kv[0].split(".")))


def _has_1014_1203ja(run: Path) -> bool:
    """Did this run execute the 2026-10-14 code at all?

    Keyed on a field that batch ADDED (`ui_walk_ran_1203je`). Without this gate the checks
    below would confirm on pre-fix runs that happen to carry the same artifacts, which is
    exactly what `--self-test` exists to catch.
    """
    for _v, rep in _reports_1203ja(run):
        if isinstance(rep.get("summary"), dict) and \
                "ui_walk_ran_1203je" in rep["summary"]:
            return True
    return False


def _releases_1203ja(run: Path) -> list:
    h = _hub(run, "codehub_releases.json")
    tags = [k for k in h if not str(k).startswith("_")]
    try:
        return sorted(tags, key=lambda v: tuple(int(x) for x in v.split(".")))
    except Exception:
        return sorted(tags)


def check_1203ja(run):
    """#1203ja: the release the user actually boots is no longer the one nobody walked."""
    if not _has_1014_1203ja(run):
        return _say("#1203ja", UNMEASURED, "this run predates the 2026-10-14 batch")
    tags = _releases_1203ja(run)
    if not tags:
        return _say("#1203ja", UNMEASURED, "no release was cut, so there is no final tag")
    have = {v for v, _ in _reports_1203ja(run)}
    if tags[-1] in have:
        return _say("#1203ja", CONFIRMED,
                    "the final tag v%s has a test-user report (%d release(s) cut)"
                    % (tags[-1], len(tags)))
    return _say("#1203ja", FALSIFIED,
                "the final tag v%s has NO test-user report" % tags[-1],
                "reports present: %s — look for '#1203ja final-release test-user walk did "
                "not dispatch' in the run log" % ", ".join(sorted(have)))


def check_1203jc(run):
    """#1203jc/#1203je: an unwalked journey or UI is no longer recorded as PASS."""
    if not _has_1014_1203ja(run):
        return _say("#1203jc", UNMEASURED, "this run predates the 2026-10-14 batch")
    bad, nw = [], 0
    for v, rep in _reports_1203ja(run):
        s = rep.get("summary") or {}
        steps = int(s.get("api_steps") or 0)
        ui_ran = bool(s.get("ui_walk_ran_1203je", True))
        if s.get("verdict") == "PASS" and (steps == 0 or not ui_ran):
            bad.append("v%s (api_steps=%d, ui_ran=%s)" % (v, steps, ui_ran))
        if s.get("verdict") == "NOT_WALKED":
            nw += 1
    if bad:
        return _say("#1203jc", FALSIFIED,
                    "%d report(s) say PASS with nothing walked" % len(bad),
                    "; ".join(bad))
    return _say("#1203jc", CONFIRMED,
                "no PASS without evidence (%d NOT_WALKED verdict(s) recorded)" % nw)


def check_1203je(run):
    """#1203je: the frontend is waited for, so a dead container is not a page verdict."""
    if not _has_1014_1203ja(run):
        return _say("#1203je", UNMEASURED, "this run predates the 2026-10-14 batch")
    refused, skipped = [], 0
    for v, rep in _reports_1203ja(run):
        uf = rep.get("ui_flows") or {}
        if not uf.get("ran", True):
            skipped += 1
            continue
        for fl in (uf.get("flows") or []):
            if "ERR_CONNECTION_REFUSED" in str(fl.get("note") or ""):
                refused.append("v%s %s" % (v, fl.get("flow")))
    if refused:
        return _say("#1203je", FALSIFIED,
                    "%d flow(s) still record ERR_CONNECTION_REFUSED" % len(refused),
                    ", ".join(refused[:6]))
    return _say("#1203je", CONFIRMED,
                "no flow blames the app for an unreachable frontend "
                "(%d walk(s) skipped on readiness)" % skipped)


def check_1203jd(run):
    """#1203jd: FIX #155's pre-cut smoke now guards the final cut too.

    A hold here is the guard WORKING, but whether the tree was really broken is a judgement
    only a reader can make — so a triggered hold is reported, never scored.
    """
    if not _has_1014_1203ja(run):
        return _say("#1203jd", UNMEASURED, "this run predates the 2026-10-14 batch")
    holds = [h for h in _jsonl(run, "delivery_hold.jsonl")
             if "fresh_smoke_final_1203jd" in json.dumps(h)]
    if not holds:
        return _say("#1203jd", CONFIRMED,
                    "the final-cut fresh smoke held nothing (the common case)")
    return _say("#1203jd", UNMEASURED,
                "the final cut was HELD %d time(s) — read these before trusting them"
                % len(holds),
                "\n".join(str(h.get("detail") or h)[:200] for h in holds[:3])
                + "\nIf the tree was fine this is a FALSE hold: set "
                  "ENVGEN_FRESH_SMOKE_GATE=0 and re-run.")


def check_1203jg(run):
    """#1203jg: the top blocker now says which pages failed and why."""
    if not _has_1014_1203ja(run):
        return _say("#1203jg", UNMEASURED, "this run predates the 2026-10-14 batch")
    recs = _jsonl(run, "delivery_gate.jsonl")
    last = None
    for r in recs:
        if "failed_checks" in r:
            last = r
    if not last:
        return _say("#1203jg", UNMEASURED, "no gate record carries failed_checks")
    if "validation_ui_evidence_failed" not in (last.get("failed_checks") or []):
        return _say("#1203jg", UNMEASURED,
                    "the final gate did not fail on validation_ui_evidence_failed")
    prose = (last.get("blocker_prose") or {}).get("validation_ui_evidence_failed")
    if not prose:
        return _say("#1203jg", FALSIFIED,
                    "the top blocker fired and still carries NO prose")
    txt = " ".join(prose) if isinstance(prose, list) else str(prose)
    if "no summary recorded" in txt and ":" in txt:
        return _say("#1203jg", UNMEASURED,
                    "prose present but every page says 'no summary recorded'",
                    txt[:240] + "  (the lookup matched nothing — check the record shape)")
    return _say("#1203jg", CONFIRMED, "the top blocker names its pages AND their reasons",
                txt[:240])


def check_1203jf(run):
    """#1203jf: the count of ui failures whose ONLY stated cause is an anonymous 401."""
    if not _has_1014_1203ja(run):
        return _say("#1203jf", UNMEASURED, "this run predates the 2026-10-14 batch")
    h = _hub(run, "codehub_checks.json")
    n = tot = 0
    for k, v in h.items():
        if not isinstance(v, dict) or not str(v.get("name") or "").startswith("validation:ui_"):
            continue
        if str(v.get("status")) != "failure":
            continue
        tot += 1
        blob = json.dumps(v.get("evidence") or {}).lower()
        if re.search(r"/(api/)?auth/me", blob) and ("401" in blob or "403" in blob):
            n += 1
    if not tot:
        return _say("#1203jf", UNMEASURED, "this run recorded no failing ui_* checks")
    return _say("#1203jf", CONFIRMED if n == 0 else UNMEASURED,
                "%d of %d failing ui_* records blame an anonymous /auth/me 401" % (n, tot),
                "" if n == 0 else
                "prose alone moves agents weakly (#1203i9) — if this has not dropped, the "
                "deterministic detector in #1203jf's comment is the next step.")


def check_1203jh(run):
    """#1203jh/#1203jhb: the stop reason names what shipped, inside the 400-char cap."""
    if not _has_1014_1203ja(run):
        return _say("#1203jh", UNMEASURED, "this run predates the 2026-10-14 batch")
    reason = str(((_budget(run).get("usage") or {}).get("terminal_reason")) or "")
    if "exited without a delivery" not in reason and "no abort and no cap" not in reason:
        return _say("#1203jh", UNMEASURED,
                    "this run did not end on the generic stop reason")
    tags = _releases_1203ja(run)
    if not tags:
        return _say("#1203jh", CONFIRMED if "SHIPPED:" not in reason else FALSIFIED,
                    "nothing shipped and the reason %s claim one"
                    % ("does not" if "SHIPPED:" not in reason else "DOES"))
    if "SHIPPED:" in reason and tags[-1] in reason:
        return _say("#1203jh", CONFIRMED,
                    "the stop reason names the tags it shipped, uncut (%d chars)"
                    % len(reason))
    return _say("#1203jh", FALSIFIED,
                "%d release(s) shipped and the reason does not say so intact" % len(tags),
                "reason (%d chars): %s" % (len(reason), reason[-160:]))


def check_1203jk(run):
    """#1203jk: the final tag's report carries EVIDENCE, not just existence."""
    if not _has_1014_1203ja(run):
        return _say("#1203jk", UNMEASURED, "this run predates the 2026-10-14 batch")
    tags = _releases_1203ja(run)
    reps = dict(_reports_1203ja(run))
    if not tags or tags[-1] not in reps:
        return _say("#1203jk", UNMEASURED,
                    "no final-tag report to judge (see #1203ja above)")
    rep = reps[tags[-1]]
    s = rep.get("summary") or {}
    uf = rep.get("ui_flows") or {}
    steps = int(s.get("api_steps") or 0)
    walked_ui = bool(uf.get("ran", True)) and bool(uf.get("flows"))
    if steps > 0 or walked_ui:
        return _say("#1203jk", CONFIRMED,
                    "the final tag's report measured something (api_steps=%d, ui=%s)"
                    % (steps, walked_ui))
    return _say("#1203jk", FALSIFIED,
                "the final tag's report measured NOTHING and was still kept",
                "api_steps=0 and the UI walk did not run — #1203jk should have re-walked it")


CHECKS = [check_1203ja, check_1203jc, check_1203je, check_1203jd,
          check_1203jg, check_1203jf, check_1203jh, check_1203jk,
          check_1203a3, check_1203a5, check_1203a6, check_1203a7,
          check_1203a8, check_1203a9,
          check_1202zt, check_1202zn, check_1202zq, check_1202zr,
          check_1202zc, check_1202za, check_1202zb, check_1202ze, check_1202zf,
          check_1202zd, check_cost]


def main(argv):
    if "--self-test" in argv:
        run = Path("generated/tiktok-web-r140")
        if not run.is_dir():
            print("self-test needs generated/tiktok-web-r140"); return 2
        print("SELF-TEST against %s, which PREDATES every fix here.\n"
              "The instrument checks must come back NOT MEASURED; a CONFIRMED would mean the\n"
              "verifier is reading a field that a pre-fix run also has.\n" % run.name)
        # That sentence was printed and nothing enforced it, which is the shape this whole
        # script exists to catch one level down. `check_cost` is exempt BY NAME and for a
        # stated reason: it measures what the run spent, not whether a fix reached it, so it
        # confirms on any run with a budget file. Every other check here answers "did this
        # delivered tree get the change?", and r140 is from before all of them -- so a
        # CONFIRMED means the check is reading something a pre-fix run also has, and the fix
        # it claims to verify is unverified.
        _exempt = {"check_cost"}
        _wrong = []
        for c in CHECKS:
            v = c(run)
            if v == CONFIRMED and getattr(c, "__name__", "") not in _exempt:
                _wrong.append(getattr(c, "__name__", str(c)))
        if _wrong:
            print("\n\033[31mSELF-TEST FAILED\033[0m: %s CONFIRMED on a run that predates "
                  "the fix, so the check does not discriminate: %s"
                  % (len(_wrong), ", ".join(_wrong)))
            return 1
        print("\nself-test ok: no fix check confirms on a pre-fix run "
              "(%d checks, %d exempt)." % (len(CHECKS), len(_exempt)))
        return 0
    live = "--live" in argv
    argv = [a for a in argv if a != "--live"]
    if len(argv) < 2:
        print(__doc__); return 2
    run = Path(argv[1])
    if not run.is_dir():
        print("no such run directory: %s" % run); return 2
    print("run: %s\n" % run)
    for c in (CHECKS + LIVE_CHECKS if live else CHECKS):
        try:
            c(run)
        except Exception as exc:                       # a broken check must not hide the rest
            _say(getattr(c, "__name__", "?"), UNMEASURED,
                 "the check itself raised: %s: %s" % (type(exc).__name__, exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
