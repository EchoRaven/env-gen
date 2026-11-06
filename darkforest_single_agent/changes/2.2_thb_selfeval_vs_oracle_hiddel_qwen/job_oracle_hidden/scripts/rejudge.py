#!/usr/bin/env python3
"""Re-run only the H3 visual judgment of hidden-eval tags from their existing captures (no docker), as hidden_eval.py
does in its last step, and update summary.json the same way. 2.2 addition: judge calls go to Claude on the shared
acct2 subscription, and when it hits a session limit the CLI answers with a limit message that judge() records as a
missing verdict. This tool re-judges such tags after the limit resets.

usage (thb-validator venv, no docker needed):
  rejudge.py --scan          list tags whose judge outputs contain a usage-limit message
  rejudge.py <tag> [...]     re-judge those tags; exit 3 if a limit message appears again (caller waits, retries)
"""
import glob, json, os, sys

EXP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [os.path.join(EXP, "scripts"), os.path.join(EXP, "scripts", "hidden")]
import visual  # noqa: E402

H = os.path.join(EXP, "evals", "hidden")
LIMIT = ("hit your session limit", "hit your usage limit", "usage limit reached", "rate limit")


def limited(tag):
    n = 0
    for f in glob.glob(os.path.join(H, tag, "visual", "judge", "*", "raw.txt")):
        t = open(f, errors="replace").read(400).lower()
        n += any(s in t for s in LIMIT)
    return n


def rejudge(tag):
    out = os.path.join(H, tag)
    r = visual.judge(os.path.join(out, "visual"))
    sp = os.path.join(out, "summary.json")
    s = json.load(open(sp))
    s["visual"] = {"mean_similarity": r["mean_similarity"], "n_scored": r["n_scored"], "n_screens": r["n_screens"],
                   "below_0.55": r["below_0.55"],
                   "per_screen": {k: v["similarity_mean"] for k, v in r["screens"].items()}}
    s.setdefault("errors", {}).pop("visual_judge", None)
    s["rejudged"] = s.get("rejudged", 0) + 1
    json.dump(s, open(sp, "w"), indent=1)
    return r["mean_similarity"], r["n_scored"], limited(tag)


if __name__ == "__main__":
    if sys.argv[1:] == ["--scan"]:
        for t in sorted(os.listdir(H)):
            if os.path.isdir(os.path.join(H, t)) and limited(t):
                print(t, limited(t))
        sys.exit(0)
    rc = 0
    for tag in sys.argv[1:]:
        m, n, lim = rejudge(tag)
        print(f"{tag}: mean {m} scored {n} limit-messages {lim}", flush=True)
        if lim:
            rc = 3
            break
    sys.exit(rc)
