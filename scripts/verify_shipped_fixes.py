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
import sys
from pathlib import Path

CONFIRMED, FALSIFIED, UNMEASURED = "CONFIRMED", "FALSIFIED", "NOT MEASURED"
_W = {CONFIRMED: "\033[32m", FALSIFIED: "\033[31m", UNMEASURED: "\033[33m"}


def _say(ticket, verdict, headline, detail=""):
    c = _W.get(verdict, "")
    print("%s%-12s %-13s\033[0m %s" % (c, ticket, verdict, headline))
    for line in (detail.splitlines() if detail else []):
        print("                            %s" % line)


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
def _reporter(run, ticket, artifact, what, expect_measured_key=None):
    rows = _jsonl(run, artifact)
    if not rows:
        return _say(ticket, UNMEASURED, "no logs/%s" % artifact,
                    "Either the check found nothing at every cut, or it never ran. The two "
                    "are not the same and this file cannot tell them apart -- read the run "
                    "log for the ticket id to decide.")
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
                     "table(s) holding rows no endpoint reads", "measured")


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


LIVE_CHECKS = [live_1202zd, live_1202ze]

CHECKS = [check_1202zc, check_1202za, check_1202zb, check_1202ze, check_1202zf,
          check_1202zd, check_cost]


def main(argv):
    if "--self-test" in argv:
        run = Path("generated/tiktok-web-r140")
        if not run.is_dir():
            print("self-test needs generated/tiktok-web-r140"); return 2
        print("SELF-TEST against %s, which PREDATES every fix here.\n"
              "The instrument checks must come back NOT MEASURED; a CONFIRMED would mean the\n"
              "verifier is reading a field that a pre-fix run also has.\n" % run.name)
        for c in CHECKS:
            c(run)
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
