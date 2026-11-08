#!/usr/bin/env bash
# Hidden-evaluate job_selfval snapshots (tags selfval-it<k> in job_oracle_hidden/evals/hidden/, as 2.1 did for 2_),
# for a fixed sample of iterations, each as soon as its snapshot exists. Skips tags that already have a summary.
# usage: scripts/hidden_selfval.sh [iters...]   (default 1 4 8 12 16 20)
HERE=$(cd "$(dirname "$0")/.." && pwd); H="$HERE/job_oracle_hidden"; ITERS=${*:-1 4 8 12 16 20}
N=$(python3 -c "import json;print(json.load(open('$HERE/job_selfval/config.json'))['iters'])")
for k in $ITERS; do
  [ "$k" -gt "$N" ] && { echo "it$k skipped: job_selfval runs $N iterations"; continue; }  # 2.3: never wait for it
  S="$HERE/job_selfval/runs/netflix__r0/snapshots/iter$k/workspace"
  until [ -d "$S" ] && python3 -c "import json,sys;sys.exit(json.load(open('$HERE/job_selfval/runs/netflix__r0/status.json'))['iters_done']<$k)"; do sleep 300; done
  [ -f "$H/evals/hidden/selfval-it$k/summary.json" ] && { echo "it$k already done"; continue; }
  echo "$(date -Is) hidden eval selfval-it$k"
  (cd "$H" && env -i PATH=/usr/local/bin:/usr/bin:/bin HOME="$HOME" LANG=C.UTF-8 PYTHONDONTWRITEBYTECODE=1 \
     PLAYWRIGHT_BROWSERS_PATH=/home/user/project/shabi_forest/.envs/cache/ms-playwright \
     /home/user/project/shabi_forest/.envs/venvs/thb-validator/bin/python -I -B scripts/hidden_eval.py "$S" "selfval-it$k" \
     >> "$H/logs/hidden_selfval-it$k.log" 2>&1)
  echo "$(date -Is) done selfval-it$k rc=$?"
done
