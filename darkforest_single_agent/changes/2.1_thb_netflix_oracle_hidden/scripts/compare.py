#!/usr/bin/env python3
"""Side-by-side table of 2_ (dev oracle visible) and 2.1 (dev oracle hidden) per iteration: dev score, then the hidden
evaluation (H1 API, H1b UI walk, H2 static findings, H3 visual).

usage: compare.py [run]      (default run 0)  -> prints a markdown table, writes evals/compare_r<run>.json
"""
import json, os, sys

EXP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
X = json.load(open(os.path.join(EXP, "config.json")))
SV = os.path.join(os.path.dirname(EXP), X["selfval_experiment"])
RAW_SUPERSEDED = {"static_data_twin", "reserved_email_domain"}  # reported through their adapted versions


def dev_scores(path):
    out = {}
    if os.path.exists(path):
        for line in open(path):
            r = json.loads(line)
            m = r["metrics"]
            out[r["iter"]] = f"{m['checks_passed']}/{m['checks_total']}"
    return out


def hidden(tag):
    p = os.path.join(EXP, "evals", "hidden", tag, "summary.json")
    if not os.path.exists(p):
        return None
    s = json.load(open(p))
    a, u, st, v = s.get("api") or {}, s.get("ui") or {}, s.get("static") or {}, s.get("visual") or {}
    det = sorted(k for k, n in (st.get("detectors") or {}).items() if n and k not in RAW_SUPERSEDED)
    if st.get("dev_fingerprints"):
        det.append("dev_fingerprints")
    return {"api": f"{a.get('passed')}/{a.get('total')}", "ui": f"{u.get('passed')}/{u.get('total')}",
            "ui_failed": u.get("failed"), "static": det, "visual": v.get("mean_similarity"),
            "below_0.55": v.get("below_0.55"), "per_screen": v.get("per_screen"), "errors": list(s.get("errors") or {})}


def main(run=0):
    arms = {"2_ visible": (dev_scores(os.path.join(SV, "evals", "r0", "official_scores.jsonl")), "selfval-it{k}"),
            "2.1 hidden": (dev_scores(os.path.join(EXP, "evals", "dev", f"r{run}_scores.jsonl")), f"r{run}-it{{k}}")}
    rows, table = [], ["| arm | iter | dev | H1 API | H1b UI | H2 static | H3 visual |", "|---|---|---|---|---|---|---|"]
    for arm, (dev, pat) in arms.items():
        for k in range(1, X["iters"] + 1):
            h = hidden(pat.format(k=k)) or {}
            rows.append({"arm": arm, "iter": k, "dev": dev.get(k), **h})
            table.append(f"| {arm} | {k} | {dev.get(k, '?')} | {h.get('api')} | {h.get('ui')} | "
                         f"{', '.join(h.get('static') or []) or '-'} | {h.get('visual')} |")
    json.dump(rows, open(os.path.join(EXP, "evals", f"compare_r{run}.json"), "w"), indent=1)
    print("\n".join(table))
    for r in rows:
        if r.get("ui_failed") or r.get("errors"):
            print(f"{r['arm']} it{r['iter']}: ui failed {r.get('ui_failed')} errors {r.get('errors')}")


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 0)
