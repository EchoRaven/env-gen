#!/usr/bin/env python3
"""Collect 2.2's scores into markdown tables (stdout) and results/summary.json, from the raw result files only.

usage: python3 -I scripts/collect.py            print the tables
       python3 -I scripts/collect.py --report   also write them into REPORT.md between the TABLES markers
"""
import contextlib, io, json, os, sys

EXP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SV, HJ = os.path.join(EXP, "job_selfval"), os.path.join(EXP, "job_oracle_hidden")
RAW_SUPERSEDED = {"static_data_twin", "reserved_email_domain"}  # as 2.1's compare.py


def jl(p):
    return [json.loads(l) for l in open(p)] if os.path.exists(p) else []


def hidden(tag):
    p = os.path.join(HJ, "evals", "hidden", tag, "summary.json")
    if not os.path.exists(p):
        return None
    s = json.load(open(p))
    a, u, st, v = s.get("api") or {}, s.get("ui") or {}, s.get("static") or {}, s.get("visual") or {}
    det = sorted(k for k, n in (st.get("detectors") or {}).items() if n and k not in RAW_SUPERSEDED)
    return {"api": f"{a['passed']}/{a['total']}" if a else None, "ui": f"{u['passed']}/{u['total']}" if u else None,
            "ui_failed": u.get("failed"), "static": det, "dev_fingerprints": st.get("dev_fingerprints"),
            "visual": v.get("mean_similarity"), "visual_scored": v.get("n_scored"), "errors": sorted(s.get("errors") or {}),
            "rejudged": s.get("rejudged", 0)}


def m(x):
    return x.get("metrics") or {}


def iters(job):
    st = json.load(open(os.path.join(job, "runs", "netflix__r0", "status.json")))
    return {i["iter"]: i for i in st["iters"]}


def main():
    out = {"selfval": [], "hidden": []}
    sv_it = iters(SV)
    calls = {}
    for c in jl(os.path.join(SV, "evals", "r0", "agent_calls.jsonl")):
        calls[c["iter"]] = calls.get(c["iter"], 0) + 1
    print("### Job 1 (selfval, oracle observable): official validation per iteration\n")
    print("| Iter | Passed | Checks OK | Chain OK | Endpoints 2xx | validate calls | wall (min) | Hidden API | Hidden UI | Visual | Notes |")
    print("|---|---|---|---|---|---|---|---|---|---|---|")
    for r in jl(os.path.join(SV, "evals", "r0", "official_scores.jsonl")):
        k, mm = r["iter"], m(r)
        h = hidden(f"selfval-it{k}") or {}
        it = sv_it.get(k, {})
        note = "; ".join(filter(None, [f"hidden errors: {','.join(h['errors'])}" if h.get("errors") else "",
                                       f"static: {','.join(h['static'])}" if h.get("static") else ""]))
        row = {"iter": k, "passed": r["passed"], "checks": f"{mm.get('checks_passed')}/{mm.get('checks_total')}",
               "chain": f"{mm.get('chain_steps_ok')}/{mm.get('chain_steps_total')}",
               "endpoints": f"{mm.get('endpoints_2xx')}/{mm.get('endpoints_total')}", "validate_calls": calls.get(k, 0),
               "wall_min": round((it.get("wall_s") or 0) / 60, 1), "hidden": h or None}
        out["selfval"].append(row)
        print(f"| {k} | {r['passed']} | {row['checks']} | {row['chain']} | {row['endpoints']} | {row['validate_calls']} | "
              f"{row['wall_min']} | {h.get('api', '')} | {h.get('ui', '')} | {h.get('visual', '') if h else ''} | {note} |")
    hj_it = iters(HJ)
    dev = {}
    for r in jl(os.path.join(HJ, "evals", "dev", "r0_scores.jsonl")):
        dev[r["iter"]] = r  # a resumed job may re-append an iteration; the last row is the same report
    print("\n### Job 2 (oracle hidden): dev evaluation (shown to the agent) and hidden evaluation per iteration\n")
    print("| Iter | Dev passed | Checks OK | Chain OK | Endpoints 2xx | wall (min) | Hidden API | Hidden UI | Visual (screens) | Notes |")
    print("|---|---|---|---|---|---|---|---|---|---|")
    for k in sorted(dev):
        r, mm = dev[k], m(dev[k])
        h = hidden(f"r0-it{k}") or {}
        it = hj_it.get(k, {})
        notes = []
        rs = os.path.join(HJ, "evals", "dev_rescore", f"r0-it{k}", "report.json")
        if os.path.exists(rs):
            rr = json.load(open(rs))
            notes.append(f"infra clash; post-hoc rescore: passed={rr.get('passed')} "
                         f"{(rr.get('_wrapper') or {}).get('metrics', {}).get('checks_passed')}/14")
        if h.get("errors"):
            notes.append("hidden errors: " + ",".join(h["errors"]))
        if h.get("static"):
            notes.append("static: " + ",".join(h["static"]))
        if h.get("rejudged"):
            notes.append("visual re-judged")
        row = {"iter": k, "passed": r["passed"], "checks": f"{mm.get('checks_passed')}/{mm.get('checks_total')}",
               "chain": f"{mm.get('chain_steps_ok')}/{mm.get('chain_steps_total')}",
               "endpoints": f"{mm.get('endpoints_2xx')}/{mm.get('endpoints_total')}",
               "wall_min": round((it.get("wall_s") or 0) / 60, 1), "hidden": h or None, "notes": notes}
        out["hidden"].append(row)
        vis = f"{h.get('visual')} ({h.get('visual_scored')})" if h and h.get("visual") is not None else "—"
        print(f"| {k} | {r['passed']} | {row['checks']} | {row['chain']} | {row['endpoints']} | {row['wall_min']} | "
              f"{h.get('api') or '—'} | {h.get('ui') or '—'} | {vis} | {'; '.join(notes)} |")
    tot = lambda its: (round(sum((i.get("wall_s") or 0) for i in its.values()) / 3600, 2),  # noqa: E731
                       sum(((i.get("usage") or {}).get("output_tokens") or 0) for i in its.values()))
    out["totals"] = {"selfval_hours_tokens_out": tot(sv_it), "hidden_hours_tokens_out": tot(hj_it)}
    print(f"\nTotals (agent wall hours, final cumulative output tokens are in status.json): selfval {tot(sv_it)[0]} h, "
          f"hidden {tot(hj_it)[0]} h")
    os.makedirs(os.path.join(EXP, "results"), exist_ok=True)
    json.dump(out, open(os.path.join(EXP, "results", "summary.json"), "w"), indent=1)


if __name__ == "__main__":
    if "--report" in sys.argv:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            main()
        rp = os.path.join(EXP, "REPORT.md")
        r = open(rp).read()
        a, b = r.index("<!-- TABLES -->") + len("<!-- TABLES -->"), r.index("<!-- /TABLES -->")
        open(rp, "w").write(r[:a] + "\n<!-- generated by scripts/collect.py --report; do not edit by hand -->\n\n"
                            + buf.getvalue().replace("### ", "#### ") + "\n" + r[b:])
        print("REPORT.md tables updated")
    else:
        main()
