#!/usr/bin/env bash
# Re-judge (visual only, from captures) every hidden tag whose judge hit the Claude usage limit; back off 30 min when the
# limit is hit again; skip tags whose hidden_eval is still running; exit once job 2 is done and no tag is left.
HERE=$(cd "$(dirname "$0")/.." && pwd); H="$HERE/job_oracle_hidden"
PY=/home/user/project/shabi_forest/.envs/venvs/thb-validator/bin/python
run() { (cd "$H" && env -i PATH=/usr/local/bin:/usr/bin:/bin HOME="$HOME" LANG=C.UTF-8 PYTHONDONTWRITEBYTECODE=1 "$PY" -I -B scripts/rejudge.py "$@"); }
while :; do
  tags=$(run --scan | awk '{print $1}')
  todo=""
  for t in $tags; do pgrep -f "hidden_eval.py .* $t( |$)" >/dev/null || todo="$todo $t"; done
  if [ -z "$todo" ]; then
    st=$(python3 -c "import json;print(json.load(open('$H/runs/netflix__r0/status.json'))['state'])" 2>/dev/null)
    [ "$st" = done ] && ! pgrep -f 'hidden_eval.py' >/dev/null && { echo "$(date -Is) nothing left; exit"; break; }
    sleep 600; continue
  fi
  for t in $todo; do
    echo "$(date -Is) rejudge $t"; run "$t"; rc=$?
    [ $rc -eq 3 ] && { echo "$(date -Is) usage limit again; sleeping 30 min"; sleep 1800; break; }
  done
done
