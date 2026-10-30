#!/usr/bin/env python3
"""Run the hidden evaluation (H1 API, H1b UI walk, H2 static, H3 visual) on one snapshot. Its results never reach
the agent.

usage (under `sg docker`, thb-validator venv, PLAYWRIGHT_BROWSERS_PATH set, no CLAUDECODE vars):
  hidden_eval.py <snapshot_workspace> <tag> [--parts api,ui,static,visual] [--repeats N] [--screens a,b]

Writes evals/hidden/<tag>/{api.json, ui/, static.json, visual/, summary.json}. --screens re-captures and re-judges only
the named visual screens and keeps the others' earlier verdicts. Steps:
1. Boot the snapshot (scripts/stack.py) on 127.0.0.1 with ports +port_offset, under evals/.hidden.lock, so only one
   hidden stack runs at a time.
2. H1, H1b and the H3 captures run against that stack, which is then torn down.
3. H2 reads the source.
4. The H3 judgments run with the lock released, since they need no docker.
A part that fails is recorded as an error in the summary, never as a score.
"""
import fcntl, json, os, sys, traceback

EXP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
X = json.load(open(os.path.join(EXP, "config.json")))
sys.path[:0] = [os.path.join(EXP, "scripts"), os.path.join(EXP, "scripts", "hidden")]
import stack  # noqa: E402
import api_suite, static_audit, ui_walk, visual  # noqa: E402

LOCK = os.path.join(EXP, "evals", ".hidden.lock")


def main(ws, tag, parts, repeats=None, screens=None):
    out = os.path.join(EXP, "evals", "hidden", tag)
    os.makedirs(out, exist_ok=True)
    if repeats:
        X["hidden"]["judge_repeats"] = visual.X["hidden"]["judge_repeats"] = repeats
    sp = os.path.join(out, "summary.json")
    summary = json.load(open(sp)) if os.path.exists(sp) else {}  # a partial re-run keeps the other parts' results
    summary.update({"snapshot": ws, "tag": tag, "parts": sorted(set(summary.get("parts", [])) | parts)})
    owned = {"api": ["api"], "ui": ["ui"], "static": ["static"], "visual": ["visual_capture", "visual_judge"]}
    summary["errors"] = {k: v for k, v in summary.get("errors", {}).items()
                         if k != "stack" and not any(k in owned[p] for p in parts)}
    with open(LOCK, "w") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        stage, project = os.path.join(out, "stack"), "thbhid21"
        try:
            urls = stack.up(ws, stage, project, X["hidden"]["port_offset"])
            be, fe = urls.get("backend"), urls.get("frontend")
            conv = None
            if "api" in parts:
                try:
                    r = api_suite.Suite(be, fe).run()
                    json.dump(r, open(os.path.join(out, "api.json"), "w"), indent=1)
                    conv = r.get("convention")
                    summary["api"] = {"passed": r["passed"], "total": r["total"], "by_category": r["by_category"],
                                      "convention": conv, "note": r["note"]}
                except Exception:
                    summary["errors"]["api"] = traceback.format_exc()[-1500:]
            if "ui" in parts:
                try:
                    r = ui_walk.Walk(be, fe, os.path.join(out, "ui")).run()
                    summary["ui"] = {"passed": r["passed"], "total": r["total"],
                                     "failed": [c["name"] for c in r["checks"] if not c["ok"]]}
                except Exception:
                    summary["errors"]["ui"] = traceback.format_exc()[-1500:]
            if "visual" in parts:
                try:
                    cap = visual.capture(be, fe, os.path.join(out, "visual"), conv, screens)
                    summary["visual_captured"] = sum(not c.get("capture_missing") for c in cap.values())
                except Exception:
                    summary["errors"]["visual_capture"] = traceback.format_exc()[-1500:]
        except Exception:
            summary["errors"]["stack"] = traceback.format_exc()[-1500:]
        finally:
            stack.down(stage, project)
    if "static" in parts:
        try:
            static_audit.main(ws, os.path.join(out, "static.json"))
            st = json.load(open(os.path.join(out, "static.json")))
            summary["static"] = {"detectors": {k: len(v) for k, v in st.get("detectors", {}).items()},
                                 "dev_fingerprints": len(st.get("dev_fingerprints", []))}
        except Exception:
            summary["errors"]["static"] = traceback.format_exc()[-1500:]
    if "visual" in parts and os.path.exists(os.path.join(out, "visual", "captures.json")):
        try:
            r = visual.judge(os.path.join(out, "visual"), screens)
            summary["visual"] = {"mean_similarity": r["mean_similarity"], "n_scored": r["n_scored"],
                                 "n_screens": r["n_screens"], "below_0.55": r["below_0.55"],
                                 "per_screen": {k: v["similarity_mean"] for k, v in r["screens"].items()}}
        except Exception:
            summary["errors"]["visual_judge"] = traceback.format_exc()[-1500:]
    json.dump(summary, open(os.path.join(out, "summary.json"), "w"), indent=1)
    print(json.dumps({k: v for k, v in summary.items() if k != "errors"}, indent=1))
    if summary["errors"]:
        print("ERRORS:", {k: v[-300:] for k, v in summary["errors"].items()})
    return summary


if __name__ == "__main__":
    a = sys.argv[1:]
    parts = set(a[a.index("--parts") + 1].split(",")) if "--parts" in a else {"api", "ui", "static", "visual"}
    reps = int(a[a.index("--repeats") + 1]) if "--repeats" in a else None
    scr = set(a[a.index("--screens") + 1].split(",")) if "--screens" in a else None
    main(a[0], a[1], parts, reps, scr)
