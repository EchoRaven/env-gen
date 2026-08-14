# COMMANDS — Next Session (r131)

**Copy-paste ready.** Goal + rationale: `GOAL_next_session.md`. Context: `HANDOFF_2026-08-11_netflix_ownerscoping.md`.

Everything below assumes `REPO=/home/haibotong/forgingground-gen`.
Replace `r131` with the actual run number if you advance past it (`r132`, …).

> ⚠️ **NEVER run `pkill -f <pattern>`** — the pattern matches your own command line and kills your
> own shell. Kill by **PID / pgid** only. (Teardown in §8 does this correctly.)

---

## 1. PUSH (user runs this — agent github egress is 403)

```bash
cd /home/haibotong/forgingground-gen && git push origin feat/netflix-generality-366-367
```

Verify afterwards (should print `ahead 0` and `0`):

```bash
cd /home/haibotong/forgingground-gen && git status -sb | head -1 && git log --oneline origin/feat/netflix-generality-366-367..HEAD | wc -l
```

There are **11** commits to push (`#566m` → `#566w`).

---

## 2. PRE-FLIGHT (run before every launch)

```bash
cd /home/haibotong/forgingground-gen
echo "=== branch ==="; git status -sb | head -1
echo "=== unpushed ==="; git log --oneline origin/feat/netflix-generality-366-367..HEAD | wc -l
echo "=== tree ==="; git status --porcelain -- agent/ | head
echo "=== running gens (want none) ==="; ps -eo pid,etime,cmd | grep "[.]venv/bin/python -m env_generator" | grep -v grep
echo "=== containers (want 0) ==="; podman ps -a --format '{{.Names}}' 2>/dev/null | wc -l
echo "=== providers (want vertex:404 relay:400) ==="; \
  echo "vertex:$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 http://127.0.0.1:8790/ 2>/dev/null)" \
  "relay:$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 http://127.0.0.1:19080/ 2>/dev/null)"
echo "=== base images (want 5) ==="; podman images --format '{{.Repository}}:{{.Tag}}' 2>/dev/null | grep -cE 'node:20-alpine|nginx:alpine|postgres:16|python:3.11-slim-bookworm|uv:python3.11-bookworm-slim'
echo "=== highest run dir ==="; ls -d agent/generated/netflix-web-r* 2>/dev/null | sed 's/.*-r//' | sort -n | tail -1
```

**Real liveness check for the vertex proxy** (`/health` lies — this makes a REAL call;
`launch_netflix.sh` does the same and aborts rc=4 if it fails):

```bash
curl -s --max-time 20 http://127.0.0.1:8790/v1/messages -H 'content-type: application/json' \
  -d '{"model":"claude-opus-4-7","max_tokens":8,"messages":[{"role":"user","content":"ping"}]}' | head -c 300; echo
```

Heal base images manually if the count is < 5:

```bash
cd /home/haibotong/forgingground-gen && (unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY; ./tools/ensure_base_images.sh)
```

---

## 3. LAUNCH r131

```bash
cd /home/haibotong/forgingground-gen
ENVGEN_SINGLE_MILESTONE=0 FW_DEBUG=1 ENVGEN_VISUAL_MIN=0.65 \
  nohup ./launch_netflix.sh netflix-web-r131 > gm_netflix-web-r131.launch.log 2>&1 &
sleep 25 && grep -iE "started pgid|ensure-bases.*OK|proxy pong OK|ABORT" gm_netflix-web-r131.launch.log
```

Get the gen PID:

```bash
cd /home/haibotong/forgingground-gen
GEN_PID=$(ps -eo pid,cmd | grep "[.]venv/bin/python -m env_generator" | grep netflix-web-r131 | grep -v grep | awk '{print $1}')
echo "GEN_PID=$GEN_PID"
```

**Confirm multi-milestone actually took** (must print `ENVGEN_SINGLE_MILESTONE=0`; if it prints
`=1` the run is single-milestone and CANNOT produce ≥2 tags — kill and relaunch):

```bash
tr '\0' '\n' < /proc/$GEN_PID/environ | grep ENVGEN_SINGLE_MILESTONE
```

Gen log: `gm_netflix-web-r131.log` · Generated app: `agent/generated/netflix-web-r131/`

---

## 4. KEEPER + MONITOR (start immediately after launch)

```bash
cd /home/haibotong/forgingground-gen
nohup bash -c 'while pgrep -f "env_generator.llm_generator.main.*netflix-web-r131" >/dev/null 2>&1; do
  unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY
  /home/haibotong/forgingground-gen/tools/ensure_base_images.sh >/dev/null 2>&1; sleep 240; done' \
  > r131_base_keeper.log 2>&1 &
echo "KEEPER_PID=$!"
nohup ./r112_monitor.sh netflix-web-r131 > netflix-web-r131_monitor.nohup.log 2>&1 &
echo "MONITOR_PID=$!"
```

**Write the PIDs down** — you need them for teardown (§8).

Monitor outputs:
- `netflix-web-r131_monitor.status` — a signal line every ~30 min
- `netflix-web-r131_monitor.TERMINAL` — the final VERDICT when the gen exits

---

## 5. STATUS ONE-LINERS (while it runs)

Quick pulse:

```bash
cd /home/haibotong/forgingground-gen
echo "gen: $(ps -o etime= -p ${GEN_PID:-0} 2>/dev/null | tr -d ' ' || echo DOWN) | tags: $(python3 -c "import json;d=json.load(open('agent/generated/netflix-web-r131/shared/hubs/codehub_releases.json'));print([k for k in d if k!='_meta'])" 2>/dev/null || echo '(no hub yet)')"
grep 'delivery gate has' gm_netflix-web-r131.log | tail -1
tail -3 netflix-web-r131_monitor.status
```

Last 40 log lines:

```bash
tail -40 /home/haibotong/forgingground-gen/gm_netflix-web-r131.log
```

Release tags only:

```bash
python3 -c "import json;d=json.load(open('/home/haibotong/forgingground-gen/agent/generated/netflix-web-r131/shared/hubs/codehub_releases.json'));print([k for k in d if k!='_meta'])"
```

Terminal verdict (exists only after the gen exits):

```bash
cat /home/haibotong/forgingground-gen/netflix-web-r131_monitor.TERMINAL
```

---

## 6. VALIDATION GREPS (the fix-by-fix checks)

**Always timestamp-check any hit before believing it** — a stale line from an earlier cycle looks
identical to a live failure. Use the pass/fail summary below to establish the cutoff.

```bash
cd /home/haibotong/forgingground-gen
L=gm_netflix-web-r131.log
echo "#566s IDOR leaks in projected create (want 0): $(grep -cE 'POST.*→ 2[0-9][0-9] \(expected \[40' $L)"
echo "#566t rating value-null       (want 0): $(grep -icE 'value.*null|null value in column .value.' $L)"
echo "#566t rating → 400            (want 0): $(grep -cE 'rating.*→ 400' $L)"
echo "#566u rating → 409            (want 0): $(grep -cE 'rating.*→ 409' $L)"
echo "#566v denial-probe surprises  (want 0): $(grep -cE 'DENIAL-PROBE got success|expected \[403' $L)"
echo "     rating → 422 (backlog)          : $(grep -cE 'rating.*→ 422' $L)"
echo "     my-list → 404 (backlog)         : $(grep -cE 'my-list.*→ 404' $L)"
echo "     UndefinedColumn                 : $(grep -c 'UndefinedColumn' $L)"
```

**#566w — per-step chain failures. The single most useful diagnostic.** Format is
`business_chain:<METHOD> <path> → <code> (expected [<codes>]; <detail>)`:

```bash
grep -oE 'business_chain:[A-Z]+ [^ ]+ → [0-9]+ \(expected \[[^]]*\]' \
  /home/haibotong/forgingground-gen/gm_netflix-web-r131.log | sort | uniq -c | sort -rn | head -20
```

This is exactly how the r130 oscillation was visible — the same endpoint failing in **both**
directions across cycles:

```
     23 business_chain:GET /api/my-list?profile_id=24 → 403 (expected [200]      <- false denial
      3 business_chain:GET /api/my-list?profile_id=27 → 200 (expected [403, 404] <- cross-user leak
```

Two opposite failures on one endpoint = the lane is oscillating, not converging. **#566w should
make this shape disappear for `my-list` / `continue-watching`** (those reads are now projected).
If it reappears, verify §7.0 first — the fix may not have reached the app.

Chain pass/fail summary lines (use these as the staleness cutoff):

```bash
grep -nE 'business_chain [0-9]+[/ ][^ ]* (chains|steps|PASS|FAIL)|chains/[0-9]+ steps (PASS|FAIL)|business_chain [0-9]+/[0-9]+ (PASS|FAIL)|[0-9]+ steps/[0-9]+ chains green' \
  /home/haibotong/forgingground-gen/gm_netflix-web-r131.log | tail -20
```

Gate trajectory (which blockers, in order — the most informative single view):

```bash
grep -oE 'gate has [^|]*' /home/haibotong/forgingground-gen/gm_netflix-web-r131.log | tail -20
```

Chain regression / flapping warnings (Objective 3):

```bash
grep -nE 'was green then regressed|Author them NOW' /home/haibotong/forgingground-gen/gm_netflix-web-r131.log | tail -10
```

Milestone advance signals:

```bash
grep -inE 'advancing to milestone|_await_prior_milestone|GENERATION COMPLETE|Status: (SUCCESS|FAIL)|main\(\) returned' /home/haibotong/forgingground-gen/gm_netflix-web-r131.log | tail -20
```

Fail-fast signals (7-cycle STUCK-ABORT / 75-min no-deliver timeout):

```bash
grep -inE 'STUCK|abort|forcing exit|no-deliver|timeout' /home/haibotong/forgingground-gen/gm_netflix-web-r131.log | tail -20
```

---

## 7. OBJECTIVE-2 DIAGNOSIS (owner-scoping)

### 7.0 ★ FIRST CHECK — confirm #566w took effect (run as soon as `main.py` exists, ~20 min in)

```bash
cd /home/haibotong/forgingground-gen/agent
RUN=r131 PYTHONPATH=. ../.venv/bin/python - <<'PY'
import os
run = os.environ.get("RUN", "r131")
src = open("generated/netflix-web-%s/app/backend/main.py" % run).read()
print("run=%s  #566w present: %s" % (
    run, "YES" if "def _fw_resource_seg(" in src else "NO  <== fix did NOT reach this app"))
ns = {}
for name in ("_NESTED_CHILD_RESOURCES", "_OWNER_SCOPED_RESOURCES"):
    exec([l for l in src.splitlines() if l.startswith(name + " = set(")][0], ns)
st = src.index("def _custom_route_overrides_projected")
exec(src[st:src.index("\ntry:", st)], ns)
f = ns["_custom_route_overrides_projected"]
for m, path in [("GET", "/api/my-list"), ("GET", "/api/my-list/{id}"),
                ("GET", "/api/continue-watching"), ("GET", "/api/titles"),
                ("GET", "/api/search"), ("POST", "/api/my-list")]:
    r = f(m, path)
    print("  %-5s %-26s lane_overrides=%-5s -> %s"
          % (m, path, r, "PROJECTED serves" if r is False else "lane serves"))
PY
```

**Expect for r131:** `my-list`, `my-list/{id}`, `continue-watching`, `titles` → `PROJECTED serves`;
`/api/search` → `lane serves`. If a kebab-case resource still says `lane serves`, #566w did not
cover it — that is the next bug, and it lives in the same policy function.

**Contrast against the pre-fix app:** re-run with `RUN=r130`. Verified output:

```
run=r130  #566w present: NO  <== fix did NOT reach this app
  GET   /api/my-list               lane_overrides=True  -> lane serves
  GET   /api/my-list/{id}          lane_overrides=True  -> lane serves
  GET   /api/continue-watching     lane_overrides=True  -> lane serves
  GET   /api/titles                lane_overrides=False -> PROJECTED serves
  GET   /api/search                lane_overrides=True  -> lane serves
  POST  /api/my-list               lane_overrides=False -> PROJECTED serves
```

That first line — `my-list` lane-served — is the exact condition that wedged r130.

### 7.1 The lane's custom handlers (only these can still shadow a projected handler)

```bash
# r130 — the run that oscillated
grep -n "_resolve_profile" -A 40 /home/haibotong/forgingground-gen/agent/generated/netflix-web-r130/app/backend/custom_routes.py | head -80
```

```bash
# r131 — same file, once the backend lane has written it
grep -n "_resolve_profile" -A 40 /home/haibotong/forgingground-gen/agent/generated/netflix-web-r131/app/backend/custom_routes.py | head -80
```

Every custom handler the lane authored (the shadowing surface):

```bash
grep -nE '^@(router|app)\.(get|post|put|patch|delete)|^(async )?def ' \
  /home/haibotong/forgingground-gen/agent/generated/netflix-web-r131/app/backend/custom_routes.py | head -60
```

Framework runtime helpers as actually rendered into the app:

```bash
grep -nE '_fw_owner_val|_fw_owns|_fw_fill_required_defaults|_fw_upsert_on_conflict|_fw_uid|_fw_resource_seg' \
  /home/haibotong/forgingground-gen/agent/generated/netflix-web-r131/app/backend/main.py | head -40
```

### 7.2 Framework source you would be editing

```bash
# runtime helpers + the route-override POLICY (both live in template strings)
grep -n "_fw_owner_val\|_fw_owns\|_fw_resource_seg\|_custom_route_overrides_projected\|_MAIN_HEADER\|_CUSTOM_ROUTES_INCLUDE" \
  /home/haibotong/forgingground-gen/agent/env_generator/llm_generator/multi_agent/runtime/backend_skeleton.py | head -30
```

```bash
# projected handler emitter
grep -n "_owner_fk\|_generate_handler\|_generate_upsert_handler" \
  /home/haibotong/forgingground-gen/agent/env_generator/llm_generator/multi_agent/runtime/route_projector.py | head -20
```

```bash
# delivery gate blockers
grep -n "business_chain_failing\|verification_checklist_not_ready\|deliverability_" \
  /home/haibotong/forgingground-gen/agent/env_generator/llm_generator/multi_agent/runtime/delivery_gate.py | head -20
```

---

## 8. TEARDOWN (after the run finishes or wedges)

```bash
cd /home/haibotong/forgingground-gen
# use the PIDs printed in §3 and §4
kill -TERM $KEEPER_PID $MONITOR_PID 2>/dev/null
kill -TERM $GEN_PID 2>/dev/null; sleep 2; kill -KILL $GEN_PID 2>/dev/null
podman rm -f -a 2>&1 | tail -1
```

If you lost the PIDs, find them **without pkill**:

```bash
ps -eo pid,etime,cmd | grep -E "env_generator|r112_monitor|ensure_base_images" | grep -v grep
```

…then `kill -TERM <pid> …` with the PIDs you read off that list.

Verify clean:

```bash
ps -eo pid,cmd | grep "[.]venv/bin/python -m env_generator" | grep -v grep; podman ps -a --format '{{.Names}}' | wc -l
```

---

## 9. TESTS

Full suite — **expect 1272 passed + 73 pre-existing `oauth_contract` network failures**
(no network in the sandbox; they are UNRELATED). Any *new* failure is yours:

```bash
cd /home/haibotong/forgingground-gen/agent && PYTHONPATH=. ../.venv/bin/python -m pytest -q 2>&1 | tail -20
```

Just the owner-scoping / route-policy fix tests (**expect 29 passed**):

```bash
cd /home/haibotong/forgingground-gen/agent && PYTHONPATH=. ../.venv/bin/python -m pytest -q \
  tests/test_owner_fk_idor_566s.py \
  tests/test_fill_required_defaults_566t.py \
  tests/test_upsert_on_conflict_566u.py \
  tests/test_read_isolation_reverify_566v.py \
  tests/test_kebab_resource_projected_guard_566w.py \
  tests/test_projected_wins_standard_get_528.py 2>&1 | tail -20
```

**The mandatory render+compile assertion** for ANY `route_projector.py` / `backend_skeleton.py`
change — those files hold triple-quoted TEMPLATE strings, so a typo is a SyntaxError in *every
generated app*, not in this repo:

```python
# in your new agent/tests/test_*_566x.py
import os, py_compile, tempfile
from env_generator.llm_generator.multi_agent.runtime.backend_skeleton import render_skeleton_main

src = render_skeleton_main(endpoints, tables)          # sample endpoints/tables
p = os.path.join(tempfile.mkdtemp(), "main.py")
open(p, "w").write(src)
py_compile.compile(p, doraise=True)                     # raises on a bad emit
```

**Second contract to respect:** `tests/test_projected_wins_standard_get_528.py` slices
`_custom_route_overrides_projected` out of the template and execs it **standalone**. Anything that
function references must be defined *inside* it (that is why `_fw_resource_seg` is nested).

---

## 10. COMMIT (after a framework change)

```bash
cd /home/haibotong/forgingground-gen
git add -A agent/env_generator && git status --short -- agent/ && git diff --cached --stat
```

Commit with a heredoc — **avoid backticks in the message** (the shell interprets them and emits
confusing `command not found` noise; the commit still lands):

```bash
git commit -F - <<'MSG'
#566x <area>: <one-line generalizable summary>

<what was wrong, why it was wrong, and the live evidence>

<what the fix does, and proof the scope is narrow>

Test: agent/tests/test_..._566x.py (N cases) + render_skeleton_main py_compile assertion.
Suite: NNNN passed, 73 pre-existing oauth_contract network failures.
MSG
git log --oneline -1; git status -sb | head -1
```

Then ask the user to push (§1).

---

## 11. QUICK REFERENCE

| thing | value |
|---|---|
| repo | `/home/haibotong/forgingground-gen` |
| branch | `feat/netflix-generality-366-367` (ahead **11** at session start) |
| last commit | `4ab3000` (#566w) |
| next run | **r131** |
| gen log | `gm_netflix-web-r131.log` |
| launch log | `gm_netflix-web-r131.launch.log` |
| monitor status | `netflix-web-r131_monitor.status` |
| monitor verdict | `netflix-web-r131_monitor.TERMINAL` |
| generated app | `agent/generated/netflix-web-r131/app/backend/` |
| release hub (tags) | `agent/generated/netflix-web-r131/shared/hubs/codehub_releases.json` |
| lane custom handlers | `.../app/backend/custom_routes.py` |
| projected handlers + policy | `.../app/backend/main.py` |
| emitter | `agent/env_generator/llm_generator/multi_agent/runtime/route_projector.py` |
| runtime helpers + route policy | `agent/env_generator/llm_generator/multi_agent/runtime/backend_skeleton.py` |
| chain executor | `agent/env_generator/llm_generator/multi_agent/runtime/chain_executor.py` |
| delivery gate | `agent/env_generator/llm_generator/multi_agent/runtime/delivery_gate.py` |
| vertex proxy | `:8790` (404 on `/` = up) |
| relay proxy | `:19080` (400 on `/` = up) |
| test baseline | **1272 passed**, 73 pre-existing network failures |
| success signal | `*** MULTI-MILESTONE VALIDATED ***` (≥2 tags + rc=0) |
| run duration | ~2–3h favorable; slow draws longer |
