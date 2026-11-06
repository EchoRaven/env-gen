# Progress
- [x] Phase 1: vLLM server setup (auto-agent, 2026-11-05 02:10)
- [x] Phase 2: Job 1 (oracle observable) — 20 iters done 2026-11-05 14:37 (all passed; 15/15 endpoints from iter 15)
- [x] Phase 3: Job 2 (oracle hidden) — 20 iters done 2026-11-05 18:20. Visual re-judging of quota-hit tags still runs in
  `scripts/rejudge_loop.sh`
- [ ] Phase 4: Evaluation and report — tours of both jobs done; REPORT.md written (22:25). Pending: finish visual
  re-judging (rejudge_loop) and then `python3 -I scripts/collect.py --report`, plus updating the visual ranges in the prose

## Current state
Both jobs are done, both tours are done, and REPORT.md is written. Remaining: `scripts/rejudge_loop.sh` (pid in
`rejudge_loop.pid`, log `logs_rejudge.txt`) waits for the Claude quota to reset and re-judges r0-it3 (partial),
r0-it5..9, and r0-it18..20. When `job_oracle_hidden/scripts/rejudge.py --scan` prints nothing, run
`python3 -I scripts/collect.py --report`, then check the job 2 visual range quoted in REPORT.md's prose (≈0.52-0.53)
and the comparison table. If the loop died, restart it with `setsid nohup scripts/rejudge_loop.sh >> logs_rejudge.txt 2>&1 &`.
vLLM was stopped at 22:25 (both jobs done). To restart it:
`scripts/serve_vllm.sh`.

## Phase 1 decision (chosen configuration and evidence)
- Server: the legacy config, kept on purpose. `scripts/serve_vllm.sh` runs `scripts/vllm_exec.sh` as the user unit
  `shabi-forest-qwen-2-2.service` (Restart=on-failure): RedHatAI/Qwen3.8-27B-INT4, `--kv-cache-dtype fp8`,
  `--max-model-len 262144` (native), `--max-num-seqs 8`, `--max-num-batched-tokens 8192`, gpu-mem 0.92,
  qwen3 reasoning parser, qwen3_xml tool parser. Started 02:10; healthy.
- Codex: 0.163.0, settings in `common/codex.json`: model catalog entry declaring a 262,144-token window,
  `model_auto_compact_token_limit = 220000` (a compaction request still fits max_model_len), effort medium.
- Evidence: `smoke/live_qwen_long_probe` is a Codex turn with 199,889 input tokens and a correct answer and no early
  compaction. `smoke/rd` has a forced compaction (`"type":"compacted"` in the rollout) and then a resumed turn that
  remembered the earlier context. `smoke/live_qwen_tool_probe` covers tool use. A 02:11 sanity run in the bwrap
  sandbox could not see the project tree, could not write `/etc` (read-only), and wrote `/workspace`.
- Rejected: spending GPU time on other quantizations or speculative decoding. The jobs are bounded by agent quality,
  not throughput. One job runs at a time, so max-num-seqs 8 is ample.

## Issues encountered
- (02:12) `sg docker` fails inside the outer auto-agent sandbox (`setgroups: Operation not permitted`). The docker socket
  is usable directly (group mapped to nogroup). Fix: `common/codex_worker.py:docker_argv()` uses plain `bash -c` when
  `docker version` works, otherwise `sg docker -c`. Both job runners use it. The first launch (1 min old, no work)
  was stopped and its run dir wiped before relaunch. The validator was checked end-to-end on `job_selfval/probe/toy`
  (docker_up passes).
- (02:15) Job 2's hidden visual judge (`job_oracle_hidden/scripts/hidden/visual.py`) used the baseline sandbox, which
  binds the user's real `~/.claude` (wrong account, read-only here, and the user's files). The new
  `common/claude_judge.py` gives each judgment an empty HOME and the acct2 token via `CLAUDE_CODE_OAUTH_TOKEN`, with
  the same binary (2.1.304), model, prompt, Read-only tool, and two-image workspace. Tested: `auth status` reports
  oauth_token; the judge read a reference jpg; `/home/user/.claude` was invisible to it.
- (03:16) Job 1 iter 1 scored: passed 14/14 checks, 12/15 endpoints 2xx, chain 8/8 (62 min, 3 validate calls).
- (03:20) Ran a dry-run hidden eval of job 1's iter1 snapshot (tag `dryrun-selfval-it1` in
  `job_oracle_hidden/evals/hidden/`, `--repeats 1`; extra data, not part of job 2). It found two wrapper bugs, both
  fixed:
  1. Qwen publishes the backend on 48000, and +20000 overflows 65535. `stack.py` now wraps only an overflowing port
     into `[offset, 65535]` and checks that ports are unique. The frontend proxies to the backend inside docker, so
     the host port does not matter to it.
  2. Qwen copies the read-only design assets with `r-x` modes, so a re-stage `rmtree` fails. The new
     `codex_worker.make_writable()` runs before staging in `stack.up`, the dev-eval retry, and the selfval
     official/broker validator (validator.py itself is unchanged). The running job 1 process still has the old code,
     which affects only a validator infra retry. It picks up the fix if it is restarted.
  Result: no errors. API 47/49, UI 20/21, visual mean 0.552 (17/20 screens scored).
- Renamed compose projects so 2.2 never collides with 2/2.1: hidden `thbhid22`, `stack.py` view `thbview22-*`,
  `view.py` `thbview22-r*` (experiment 2's stopped `thbview-r0-it1/it5` containers exist). `validator.py` keeps
  `thbval` (unchanged file); do not run experiment 2's or 2.1's validators concurrently with 2.2.
- (05:21) Job 1 iters 1-3 all passed 14/14 (endpoints 12, 13, 13 of 15; chain 8/8). ~65 min/iter. The real job session
  has auto-compacted twice (`"type":"compacted"` in its rollout) and continued without error; last turn context
  ~180K tokens. So in-session compaction at the 220K limit is validated.
- (07:16, after a proctor-session quota restart; the job itself kept running) iters 4-6 passed 14/14, 13/15
  endpoints, chain 8/8. iter 6 took only 20 min (1 validate call). Session compactions: 4. Iter 7 is active.
- (11:10) iters 7-11 all passed 14/14, 13/15 endpoints, chain 8/8 (plateau since iter 2). Iter 12 running.
- (12:25) iter 12 passed (same scores). Started `scripts/hidden_selfval.sh` (pid in `hidden_selfval.pid`, log
  `logs_hidden_selfval.txt`): it hidden-evaluates job 1's snapshots at iters 1,4,8,12,16,20 (full 3 judge repeats;
  tags `selfval-it<k>`, which `job_oracle_hidden/scripts/compare.py` reads, as 2.1 did for 2_). It is a sample, not
  all 20, to limit Claude judge calls on the shared acct2 quota. Re-run it after a restart; it skips finished tags.
- (14:40) Job 1 at iter 17. iter 15 first hit 15/15 endpoints (it15 and it16 both 14/14, 15/15, 8/8). Hidden selfval
  results: it1 API 47/49, UI 20/21, visual 0.542; it4 46, 18/21, 0.519; it8 46, 18/21, 0.525; it12 46, 18/21, 0.507;
  it16 API 42, UI 4/5 ('walk did not crash' failed), visual capture error. A rerun (tag `selfval-it16-rerun`,
  api+ui) reproduced it (API 43). Cause: in iter 14 Qwen changed Login.jsx to a two-step sign-in (email ->
  Continue -> password, as in the reference), and the frozen 2.1 UI walk/capture wait for a password field on the first
  screen (`fail_03.png`). The instrument is left unchanged for comparability. Report it as an evaluator limitation,
  and check sign-in by hand in Phase 4. Job 2 may hit the same thing.
- (15:15) selfval-it20 hidden: API 43/49, UI walk crash (two-step login), no visual capture. Started selfval-it13
  (last pre-two-step-login snapshot) via `scripts/hidden_selfval.sh 13`.
- Phase 4 for job 1 done: `job_selfval/results/tour/it20/{NOTES.md,contact_sheet.jpg,*.png,tour.json}` by
  `common/tour.py` (generic real-UI tour) and `common/contact_sheet.py`. Key defect: the title-page Play button is covered
  and unclickable. The two-step sign-in works for a person. View stack torn down.
- (15:30) selfval-it13 hidden: API 46/49, UI 6/22, visual 0.298 (no errors). Real bug: iter 13's frontend throws
  `ReferenceError: seasons is not defined` (React crash; files changed vs it12: App, Card, GenreCategory, Landing,
  new TitleDetail), so /browse and every nav page is blank after sign-in. Job 1's own validator scored it 14/14
  (it does not render the UI). Later iterations fixed it (it20 renders). Note this for the report.
- (17:20, after another proctor quota pause) Job 2 at iter 15 (iters 2-14 took only 2-14 min each). Three problems found:
  1. **Visual judge hit the acct2 session limit**: judge raw.txt says "You've hit your session limit". r0-it3 is partial
     (39/54) and r0-it4..14 have no score. Fix: `job_oracle_hidden/scripts/rejudge.py` re-runs only the judge from the
     existing captures (no docker) and updates summary.json (`rejudged` counter). `scripts/rejudge_loop.sh` (pid
     `rejudge_loop.pid`, log `logs_rejudge.txt`) re-judges limit-hit tags, backs off 30 min on a new limit, and exits
     once job 2 is done. r0-it4 re-judged: 0.519 (18 screens). Check `rejudge.py --scan` before writing the report.
  2. **Container-name clash** (infra, mine): Qwen's compose hard-codes `container_name: netflix_*`, so the dev stack
     of iter 12 collided with the still-running r0-it11 hidden stack ("Conflict. The container name
     /netflix_database is already in use"). The agent got a false docker_up failure as iter 12's dev report. Fix:
     `dev_eval` now also holds `evals/.hidden.lock`, which hidden_eval holds only during its stack phase. Job 2 was
     restarted at 17:29 to load it (iter 15's turn was interrupted and resumed in the same session).
  3. Genuine, not infra: job 2 iter 1 dev+hidden: database container exited (3). Iter 2 dev: the app published host
     port 8000, which vLLM uses ("address already in use"), and the agent fixed it in iter 3. Job 1 hit the same 8000
     clash at iter 1 call 1, which is why Qwen's apps use 48000. Job 1 iter 13 call 2: 48000 was already in use
     (source not identified; probably teardown lag of the previous validator stack).
- (17:40) Post-hoc dev rescore of job 2 iter 12 (`job_oracle_hidden/evals/dev_rescore/r0-it12/`): 14/14, chain 8/8. The original
  failed report stays as what the agent saw.
- For Phase 4, run view.py/stack.py without `sg` (plain venv python) for the same reason.
- History: the first auto-agent attempt used a wrong-account HOME and hit quota. The supervisor now uses an isolated
  config with the acct2 token (managed by the auto-agent systemd service; do not resume old isolated-HOME sessions).
  The outer service runs in `auto_agent/sandbox_exec.sh` (see `auto_agent/SAFETY_RULES.md`).
