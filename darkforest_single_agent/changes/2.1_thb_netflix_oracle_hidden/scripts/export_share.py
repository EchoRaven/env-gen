#!/usr/bin/env python3
"""Copy experiments 2_ and 2.1 (and the baseline sandbox they import) into a directory for sharing, without
duplicates, caches or account data.

usage: export_share.py <dest_dir> [--jpeg]

Kept: all code, prompts, configs and logs; every iteration's submitted workspace; the agent transcripts; the dev
evaluator's reports; the hidden evaluation (results, judge replies, screenshots); the calibration report.
Omitted, with the reason recorded in <dest>/OMITTED.md:
- copies: staged copies of a snapshot made by an evaluator, the run's final workspace (identical to iteration 5),
  the judge's copies of the two images it compared, calibration mutants (calibrate.py re-plants them);
- design assets copied into a workspace that are byte-identical to env-gen's design_inputs/netflix/assets;
- build output and caches: node_modules, dist, __pycache__, the agent's ~/.cache and ~/.npm;
- account data: the job's ~/.claude.json and everything in the Claude config overlay except the transcripts.
In every text file kept, the account's email, names and ids are replaced with placeholders, and the local user name in
paths with `user`.
--jpeg stores full-page screenshots as JPEG (quality 90) instead of PNG.
"""
import collections, fnmatch, json, os, re, sys

CH = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SF = os.path.dirname(CH)
DESIGN = f"{SF}/benchmarks/env-gen/design_inputs/netflix/assets"
EXPS = ["2_thb_netflix_selfval", "2.1_thb_netflix_oracle_hidden"]
BASE = ("0_baxbench_nl2_tests", ["config.json", "scripts/sandbox.py", "scripts/common.py"])
OMIT = [  # (glob on the path relative to changes/, reason)
    ("*/node_modules", "build dependencies (npm install)"),
    ("*/dist", "build output (vite build)"),
    ("*/__pycache__", "bytecode"),
    ("*/runs/*/home", "the agent's home: pip/npm/playwright caches and the per-job ~/.claude.json (account data)"),
    ("*/runs/*/workspace", "the run's final workspace, identical to snapshots/iter5/workspace"),
    ("2_thb_netflix_selfval/views", "staged copies used to serve snapshots on localhost"),
    ("2_thb_netflix_selfval/evals/r0/*/project", "staged copy of the snapshot the dev evaluator ran"),
    ("2_thb_netflix_selfval/evals/r0/*/src", "copy of the snapshot the dev evaluator ran"),
    ("2.1_thb_netflix_oracle_hidden/evals/dev/*/project", "staged copy of the snapshot the dev evaluator ran"),
    ("2.1_thb_netflix_oracle_hidden/evals/hidden/*/stack", "staged copy of the snapshot the hidden evaluation ran"),
    ("2.1_thb_netflix_oracle_hidden/evals/hidden/*/visual/judge/*/workspace",
     "the judge's copies of the reference and the screenshot (both kept elsewhere)"),
    ("2.1_thb_netflix_oracle_hidden/evals/calibration/*/workspace", "calibration mutants; calibrate.py re-plants them"),
    ("2.1_thb_netflix_oracle_hidden/share", "this export"),
    ("*.pid", "process id"),
    ("*/.hidden.lock", "lock file"),
]
OVERLAY_KEEP = "projects"  # in runs/*/claude_overlay keep only the transcripts


def secrets():
    vals = {}
    for p in [os.path.expanduser("~/.claude.json")] + [f"{CH}/{e}/runs/netflix__r0/home/.claude.json" for e in EXPS]:
        try:
            d = json.load(open(p))
        except Exception:
            continue
        a = d.get("oauthAccount") or {}
        for k in ("emailAddress", "fullName", "displayName", "organizationName", "accountUuid", "organizationUuid"):
            if isinstance(a.get(k), str) and len(a[k]) >= 4:
                vals[a[k]] = f"<{k}>"
        for k in ("userID", "machineID"):
            if isinstance(d.get(k), str) and len(d[k]) >= 8:
                vals[d[k]] = f"<{k}>"
    if vals:
        email = next((v for v, t in vals.items() if t == "<emailAddress>"), None)
        if email:
            vals[email.split("@")[0] + "@"] = "<emailAddress-local>@"
    user = os.path.basename(os.path.expanduser("~"))
    vals.update({f"/home/{user}/": "/home/user/", f"-home-{user}-": "-home-user-",  # the local account name in paths
                 f" {user} ": " user "})  # and as a file owner in `ls -l` output
    return dict(sorted(vals.items(), key=lambda kv: -len(kv[0])))


def glob(rel, g):
    """Glob on whole path segments: `*` never crosses a `/`; a leading `*/` matches any depth; a pattern without `/`
    matches the basename. A match on a directory covers everything under it."""
    if "/" not in g:
        return fnmatch.fnmatch(os.path.basename(rel), g)
    rx = re.escape(g).replace(r"\*", "[^/]*")
    if g.startswith("*/"):
        rx = "(?:.*/)?" + rx[len("[^/]*/"):]
    return re.fullmatch(rx + "(?:/.*)?", rel) is not None


def omitted(rel):
    for g, why in OMIT:
        if glob(rel, g):
            return why
    parts = rel.split("/")
    if "claude_overlay" in parts:
        i = parts.index("claude_overlay")
        if len(parts) > i + 1 and parts[i + 1] != OVERLAY_KEEP:
            return "Claude config overlay (settings, caches, account backups); only the transcripts are kept"
    if "/app/frontend/public/assets/" in rel + "/" and os.path.isfile(os.path.join(CH, rel)):
        sub = rel.split("/app/frontend/public/assets/", 1)[1]
        ref = os.path.join(DESIGN, sub)
        if os.path.isfile(ref) and filecmp(os.path.join(CH, rel), ref):
            return "design asset byte-identical to env-gen design_inputs/netflix/assets"
    return None


def filecmp(a, b):
    import filecmp as fc
    return fc.cmp(a, b, shallow=False)


def main(dest, jpeg=False):
    sec = secrets()
    hits, om, kept = collections.Counter(), collections.defaultdict(lambda: [0, 0]), [0, 0]
    os.makedirs(dest, exist_ok=True)
    roots = [f"{BASE[0]}/{f}" for f in BASE[1]] + EXPS
    for root in roots:
        src_root = os.path.join(CH, root)
        walk = [(os.path.dirname(src_root), [], [os.path.basename(src_root)])] if os.path.isfile(src_root) else os.walk(src_root)
        for d, dirs, files in walk:
            reld = os.path.relpath(d, CH)
            for x in list(dirs):
                why = omitted(f"{reld}/{x}")
                if why:
                    dirs.remove(x)
                    p = os.path.join(d, x)
                    n = sum(os.path.getsize(os.path.join(a, f)) for a, _, fs in os.walk(p) for f in fs
                            if os.path.isfile(os.path.join(a, f)) and not os.path.islink(os.path.join(a, f)))
                    om[why][0] += 1
                    om[why][1] += n
            for f in files:
                rel = f"{reld}/{f}" if reld != "." else f
                src = os.path.join(CH, rel)
                if os.path.islink(src):
                    continue
                why = omitted(rel)
                if why:
                    om[why][0] += 1
                    om[why][1] += os.path.getsize(src)
                    continue
                out = os.path.join(dest, "changes", rel)
                os.makedirs(os.path.dirname(out), exist_ok=True)
                if jpeg and f.endswith(".png") and os.path.getsize(src) > 300_000:
                    from PIL import Image
                    out = out[:-4] + ".jpg"
                    Image.open(src).convert("RGB").save(out, quality=90)
                else:
                    data = open(src, "rb").read()
                    if b"\0" not in data[:8192]:
                        for v, ph in sec.items():
                            c = data.count(v.encode())
                            if c:
                                hits[ph] += c
                                data = data.replace(v.encode(), ph.encode())
                    open(out, "wb").write(data)
                kept[0] += 1
                kept[1] += os.path.getsize(out)
    with open(os.path.join(dest, "OMITTED.md"), "w") as fh:
        fh.write("# What this export leaves out\n\n| reason | items | size |\n|---|---|---|\n")
        for why, (n, b) in sorted(om.items(), key=lambda kv: -kv[1][1]):
            fh.write(f"| {why} | {n} | {b / 2**20:.0f} MB |\n")
        fh.write("\nAccount email, names and ids are replaced with placeholders such as `<emailAddress>` in every kept "
                 "text file, and the local user name in paths with `user` (`/home/user/...`).\n")
    print(f"kept {kept[0]} files, {kept[1] / 2**20:.0f} MB; omitted {sum(n for n, _ in om.values())} items, "
          f"{sum(b for _, b in om.values()) / 2**20:.0f} MB")
    print("redactions:", dict(hits))
    return kept, om, hits


if __name__ == "__main__":
    main(sys.argv[1], "--jpeg" in sys.argv)
