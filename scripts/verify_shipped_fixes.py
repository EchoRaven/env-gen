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
    if len(argv) < 2:
        print(__doc__); return 2
    run = Path(argv[1])
    if not run.is_dir():
        print("no such run directory: %s" % run); return 2
    print("run: %s\n" % run)
    for c in CHECKS:
        try:
            c(run)
        except Exception as exc:                       # a broken check must not hide the rest
            _say(getattr(c, "__name__", "?"), UNMEASURED,
                 "the check itself raised: %s: %s" % (type(exc).__name__, exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
