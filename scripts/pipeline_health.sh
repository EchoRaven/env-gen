#!/usr/bin/env bash
# Two numbers that say whether the pipeline is getting better, computed from artifacts
# rather than memory.
#
# Written because I told the user for several turns that r97/r108 were "the pipeline's
# first and second deliveries ever". They were not: netflix-r30 cut a gate-fully-clear
# release on 09-01 and nine runs have delivered across two envs. I had been answering
# from impression instead of from `codehub_releases.json`, and there was no command to
# answer it with.
#
#   bash scripts/pipeline_health.sh [days]     # default 9
set -uo pipefail
REPO="${REPO:-/data/common/haibotong/forgingground-gen}"
PY="${PY:-/home/haibotong/miniconda3/envs/dt/bin/python}"
DAYS="${1:-9}"

cd "$REPO" || exit 1
"$PY" - "$DAYS" <<'PYEOF'
import json, pathlib, sys, time, collections

days = int(sys.argv[1]); cut = time.time() - days * 86400
rows = []
for p in sorted(pathlib.Path("generated").glob("*/run_budget.json")):
    try:
        d = json.loads(p.read_text())
    except Exception:
        continue
    usd = (d.get("llm") or {}).get("usd") or 0
    if usd <= 0:
        continue                      # a run that never called the model says nothing
    started = (d.get("usage") or {}).get("started_at") or 0
    if started < cut:
        continue
    # DELIVERED = a release row exists. `_meta` is the document's own revision counter,
    # not a release — reading it as one reported 11/11 delivered on a corpus with 1.
    rel, clear = [], False
    try:
        raw = json.loads((p.parent / "shared/hubs/codehub_releases.json").read_text())
        for k, v in raw.items():
            if k == "_meta" or not isinstance(v, dict):
                continue
            rel.append(k)
            if "fully clear" in str(v.get("notes") or ""):
                clear = True
    except Exception:
        pass
    env = p.parent.name.split("-r")[0]
    rows.append({"t": started, "run": p.parent.name, "env": env, "usd": usd,
                 "delivered": bool(rel), "clear": clear})

rows.sort(key=lambda r: r["t"])
deliv = [r for r in rows if r["delivered"]]
spend = sum(r["usd"] for r in rows)

print(f"=== pipeline health · last {days} days · {len(rows)} paid runs ===\n")
print(f"  delivered            {len(deliv)}/{len(rows)}  ({100*len(deliv)/max(len(rows),1):.0f}%)")
print(f"  of those, gate-clear {sum(1 for r in deliv if r['clear'])}")
print(f"  total spend          ${spend:.0f}")
if deliv:
    print(f"  cost per delivery    ${spend/len(deliv):.0f} amortised over ALL runs")
    print(f"  cheapest delivery    ${min(r['usd'] for r in deliv):.2f} ({min(deliv, key=lambda r: r['usd'])['run']})")

print("\n  per env:")
by = collections.defaultdict(lambda: [0, 0, 0.0])
for r in rows:
    b = by[r["env"]]; b[0] += 1; b[1] += r["delivered"]; b[2] += r["usd"]
for env, (n, d, s) in sorted(by.items(), key=lambda kv: -kv[1][0]):
    print(f"    {env:22} {d}/{n} delivered   ${s:.0f}")

print("\n  deliveries oldest → newest (the trend that matters):")
for r in deliv:
    when = time.strftime('%m-%d %H:%M', time.localtime(r["t"]))
    print(f"    {when}  {r['run']:26} ${r['usd']:7.2f}  {'gate-clear' if r['clear'] else 'escape'}")
PYEOF

echo
echo "=== defect discovery · new #1202 ids per day ==="
git log --format="%ad|%B" --date=format:'%m-%d' 2>/dev/null | "$PY" -c "
import sys,re,collections
d=collections.defaultdict(set); cur=None
for line in sys.stdin:
    m=re.match(r'^(\d\d-\d\d)\|',line)
    if m: cur=m.group(1)
    if cur:
        for t in re.findall(r'#1202([a-z]{1,3})\b', line): d[cur].add(t)
ks=sorted(d)[-int('$DAYS'):]
for k in ks: print(f'  {k}  {len(d[k]):3}  {chr(9608)*min(len(d[k]),50)}')
if len(ks)>=4:
    h=len(ks)//2; a=sum(len(d[k]) for k in ks[:h]); b=sum(len(d[k]) for k in ks[h:])
    verdict='DECELERATING' if b < a*0.7 else 'NOT decelerating'
    print(f'\n  first half {a} · second half {b}  ->  {verdict}')
    print('  (a rate that is not falling means \"no framework defects left\" has no date)')
"
