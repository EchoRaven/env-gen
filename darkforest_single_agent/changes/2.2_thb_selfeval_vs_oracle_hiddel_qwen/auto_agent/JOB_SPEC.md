# JOB SPEC: Qwen3.8-27B + Codex Netflix Experiment (2.2)

You are an autonomous Claude Code agent running on acct2's account. Your job is to **replicate experiments 2 and 2.1** (Netflix app building benchmark) but with **Qwen3.8-27B (local vLLM) + Codex CLI** replacing the single Claude Code worker. Everything else (benchmark, sandbox, evaluation, contract) stays identical.

**Current checkout handoff (2026-11-05):** `job_selfval/` and `job_oracle_hidden/` have already been copied and adapted, both `config.json` files specify 20 iterations, and `common/codex_worker.py` contains a bwrap Codex worker. Inspect, revise, or replace this code as needed; **do not run the copy commands in Phase 2.1 or 3.1 again**. Read `PROGRESS.md` first. The **Codex worker must run inside a verified filesystem sandbox**. A working directory alone does not confine filesystem access.

**You own vLLM setup and lifecycle.** Choose its configuration, start/stop/restart your own server as needed, and change the Codex integration to match. Preserve the model's native 262,144-token maximum and check Codex's effective context/compaction. `changes/0.02_qwen_test/ANALYSIS_zh.md` and `scripts/serve_vllm.sh` are prior measurements and a legacy server script, not a mandated or optimal configuration. Existing `smoke/` results are examples of working integration; decide what additional testing the jobs need. Do not stop unrelated GPU jobs or services.

**You have a 5-hour session window. If you run out of quota, you will be resumed automatically. Track your progress so you can pick up where you left off.**

Work in `/home/user/project/shabi_forest/changes/2.2_thb_selfeval_vs_oracle_hiddel_qwen/`.

---

## PHASE 0: Orientation and Progress Tracking

Create and maintain a file `PROGRESS.md` in the experiment directory. Update it after every major step so you can resume if interrupted. Structure:

```markdown
# Progress
- [ ] Phase 1: vLLM server setup
- [ ] Phase 2: Job 1 (oracle observable) — copy, modify, run 20 iters
- [ ] Phase 3: Job 2 (oracle hidden) — copy, modify, run 20 iters
- [ ] Phase 4: Evaluation and report
## Current state
<what you're doing right now>
## Issues encountered
<any blockers or fixes>
```

**On resume:** Read `PROGRESS.md` first. Skip completed phases. Continue from where you left off.

---

## PHASE 1: Set Up Local vLLM Server with Qwen3.8-27B

### 1.1 Environment

Source the project environment first:
```bash
source /home/user/project/shabi_forest/.envs/env.sh
source /home/user/project/shabi_forest/changes/0.02_qwen_test/scripts/env.sh
```

The vLLM venv is at `/home/user/project/shabi_forest/.envs/venvs/vllm/`. The model weights are cached in `/home/user/project/shabi_forest/.envs/cache/hf/`.

### 1.2 Start the Server

One **legacy measured example**, which you may replace, is:

```bash
source /home/user/project/shabi_forest/changes/0.02_qwen_test/scripts/env.sh
vllm serve RedHatAI/Qwen3.8-27B-INT4 \
  --host 127.0.0.1 --port 8000 \
  --served-model-name local \
  --gpu-memory-utilization 0.92 \
  --max-model-len 262144 \
  --max-num-seqs 8 \
  --max-num-batched-tokens 8192 \
  --kv-cache-dtype fp8 \
  --reasoning-parser qwen3 \
  --enable-auto-tool-choice --tool-call-parser qwen3_xml \
  --enable-prompt-tokens-details
```

You may use or revise `scripts/serve_vllm.sh`, or start your own server. Check health before worker calls:
```bash
curl -sf http://127.0.0.1:8000/health
```

The server log goes to `vllm_server.log` in the experiment directory.

**Important:** The Codex CLI needs an OpenAI-compatible endpoint. The legacy setup serves at `http://127.0.0.1:8000/v1`; adjust `common/codex_worker.py` and `common/codex.json` if you change the server. Verify long-context and compaction behavior in actual agent sessions; API-only context tests do not establish that behavior.

### 1.3 Codex CLI Configuration

Codex CLI is at `/home/user/.nvm/versions/node/v22.22.1/bin/codex`. It connects to an OpenAI-compatible API.

**Reference:** The working example in `changes/0.2.2_math_group_evo_deepseek/compose/` uses Codex CLI 0.163.0 with an external API (deepseek via api.inco.ai) through an LLM gateway. Study these files:
- `compose/scripts/sessions.py` — how to run `codex exec`, parse output, handle limits
- `compose/scripts/sandbox.py` — container setup with Codex
- `compose/scripts/llm_gateway.py` — the gateway pattern (you may not need this for local vLLM)
- `compose/config.json` — Codex agent settings

The existing worker configures Codex with:
```
OPENAI_BASE_URL=http://127.0.0.1:8000/v1
OPENAI_API_KEY=dummy
```

**Test the combination before running the full experiment.** Try a simple `codex exec` call with a basic prompt and verify it works with local Qwen. Debug context length matching — sometimes Codex compacts early. Relevant test: `compose/tests/test_codex_window.py` and `compose/tests/test_codex_compact.py` in the 0.2.2 directory.

**Your goal:** Choose and validate a Codex CLI + local vLLM Qwen combination for the two 20-iteration jobs. Prior INT4/FP8-KV tests establish a working legacy option, including a Codex turn with roughly 200K input tokens; they do not establish the best setup for the jobs.

---

## PHASE 2: Job 1 — Oracle Observable (selfval)

### 2.1 Copy and Set Up

```bash
cp -a /home/user/project/shabi_forest/changes/2_thb_netflix_selfval \
      /home/user/project/shabi_forest/changes/2.2_thb_selfeval_vs_oracle_hiddel_qwen/job_selfval
```

### 2.2 Modify for Codex + Qwen

**What to change in `job_selfval/`:**

1. **`config.json`**: Change `iters` from 5 to 20. Remove or adapt claude-specific settings. Add codex/qwen settings.

2. **`scripts/run_selfval_job.py`**: This is the main file to modify. Currently it:
   - Imports `sandbox.py` from `0_baxbench_nl2_tests` to build a bwrap command
   - Calls `claude -p <prompt> --model claude-opus-5-5 ...` inside the sandbox
   - Has a `Broker` thread that serves `validate` requests
   - Runs official validation after each iteration

   You need to replace the Claude Code invocation with Codex CLI:
   - Replace `sandbox_argv()` to use Codex instead of Claude
   - The Codex CLI command pattern (from 0.2.2's sessions.py):
     ```
     codex exec [resume <sid> | fork <sid>] --json --skip-git-repo-check \
       --dangerously-bypass-approvals-and-sandbox --dangerously-bypass-hook-trust \
       -c 'model_reasoning_effort="medium"' <prompt>
     ```
   - Set environment: `OPENAI_BASE_URL=http://127.0.0.1:8000/v1`, `OPENAI_API_KEY=dummy`
   - The sandbox (bwrap) may or may not be needed for Codex. Codex has its own sandbox bypass. The key constraint from the specs: **the worker agent shall not modify and work outside of the sandbox**. You can either:
     - Keep bwrap but replace the claude binary with codex, or
     - Use Codex's own containment with `--dangerously-bypass-approvals-and-sandbox` but ensure the working directory is confined
   - Parse Codex output differently: use `parse_stream()` from `0.2.2/compose/scripts/sessions.py` instead of JSON output parsing

3. **`scripts/launch.sh`**: Update to source the vllm environment and check the vLLM server is running before starting.

4. **Keep unchanged:**
   - `contract/netflix.json` — the frozen contract
   - `prompts/` — the task prompts (iter1.txt, loop.txt, next_iter.txt)
   - `sandbox_tools/` — the validate command
   - `scripts/validator.py` — the validation logic
   - The benchmark at `benchmarks/env-gen` — **NEVER modify anything in benchmarks/**

### 2.3 Run 20 Iterations

```bash
cd /home/user/project/shabi_forest/changes/2.2_thb_selfeval_vs_oracle_hiddel_qwen/job_selfval
scripts/launch.sh 0
tail -f logs/job_r0.log
```

Monitor for:
- Codex connecting to vLLM successfully
- Worker staying within its sandbox
- Validation running correctly after each iteration
- Disk space (snapshots accumulate)

**If there are runtime blockers:** Fix them and resume. The job is resumable (it checks `status.json` for `iters_done`).

**Disk management:** Each snapshot can be large. After confirming an iteration's score, you can remove intermediate build artifacts from older snapshots (node_modules, __pycache__, .git objects) but keep the source code. Check disk with `df -h /` periodically.

### 2.4 Verify Job 1

After all 20 iterations complete:
- Check `evals/r0/official_scores.jsonl` for per-iteration scores
- Check `runs/netflix__r0/status.json` for completion

---

## PHASE 3: Job 2 — Oracle Hidden

### 3.1 Copy and Set Up

```bash
cp -a /home/user/project/shabi_forest/changes/2.1_thb_netflix_oracle_hidden \
      /home/user/project/shabi_forest/changes/2.2_thb_selfeval_vs_oracle_hiddel_qwen/job_oracle_hidden
```

### 3.2 Modify for Codex + Qwen

Same approach as Phase 2, but:

1. **`scripts/run_hidden_job.py`** instead of `run_selfval_job.py`:
   - No `Broker` thread (no validate calls in oracle hidden)
   - Has `dev_eval()` and `hidden_eval()` functions — keep these unchanged
   - Replace only the Claude Code invocation with Codex

2. **`config.json`**: `iters` → 20. The hidden eval settings stay the same.

3. **No `sandbox_tools/`** in this dir (no validate command for oracle hidden).

4. **The sandbox is simpler** — no validate_io mount, no /thb mount.

### 3.3 Run 20 Iterations

Same as Phase 2 but for the hidden job. Make sure Job 1 is fully complete first.

### 3.4 Verify Job 2

- Check `evals/dev/r0_scores.jsonl` for dev scores
- Check `evals/hidden/` for hidden evaluation results
- Check `runs/netflix__r0/status.json`

---

## PHASE 4: Evaluation and Report

### 4.1 In-Person Evaluation

For high-scoring iterations (pick the best few from each job):

1. **Boot the app** using the view/stack scripts:
   ```bash
   # For job_selfval (uses view.py):
   cd job_selfval
   sg docker -c "../../.envs/venvs/thb-validator/bin/python -I -B scripts/view.py <iter>"
   
   # For job_oracle_hidden (uses stack.py):
   cd job_oracle_hidden
   sg docker -c "../../.envs/venvs/thb-validator/bin/python -I -B scripts/stack.py view <iter>"
   ```

2. **Take screenshots** of the running app. Compare with reference screenshots in `benchmarks/env-gen/design_inputs/netflix/references/`.

3. **Evaluate visually:** Does it look like Netflix? Are the pages navigable? Do the features work?

### 4.2 Score Summary

Collect from both jobs:
- Per-iteration automated scores (from official_scores.jsonl / dev r0_scores.jsonl)
- Hidden eval scores (from evals/hidden/ for job 2)
- Your visual assessment of the best iterations

### 4.3 Compose Final Report

Create `REPORT.md` in the experiment directory with:

```markdown
# 2.2: Qwen3.8-27B + Codex vs Claude Code — Netflix Benchmark

## Setup
- Model: Qwen3.8-27B-INT4 via local vLLM
- Agent: Codex CLI
- Context: 262k tokens
- Iterations: 20 per job

## Results

### Job 1: Oracle Observable (selfval)
| Iter | Passed | Checks OK | Chain OK | Endpoints 2xx | Notes |
|------|--------|-----------|----------|---------------|-------|
| 1    | ...    | ...       | ...      | ...           | ...   |
...

### Job 2: Oracle Hidden
#### Dev Scores
(same table format)

#### Hidden Scores
(if available)

## Visual Evaluation
(screenshots and observations for the best iterations)

## Comparison with Claude Code (experiments 2 and 2.1)
(how does qwen+codex compare to claude opus 5.5?)

## Issues and Observations
(what went wrong, what worked, codex+qwen quirks)
```

---

## CONSTRAINTS AND RULES

1. **NEVER modify anything in `benchmarks/`**. This is a frozen third-party benchmark (CLAUDE.md Rule 1).
2. **Keep environments inside the project.** Use `.envs/` for everything (CLAUDE.md Rule 2).
3. **The worker agent must not modify or work outside its sandbox.** Confine it to its workspace.
4. **Watch disk space.** Run `df -h /` periodically. If below 50 GB free, clean only artifacts owned by this 2.2 experiment; leave other experiments and shared caches intact.
5. **The vLLM server uses the GPU.** Check existing GPU jobs before starting or stopping a server. Stop only services/processes that belong to this 2.2 experiment.
6. **Choose the vLLM configuration yourself.** Keep setup effort proportionate to the experiment; record the chosen configuration and evidence in `PROGRESS.md`.
7. **If Codex+Qwen fails repeatedly on a specific iteration, log the error and move on.** The experiment data is what matters.

## RESOURCES

| Path | What |
|------|------|
| `changes/0.02_qwen_test/` | vLLM Qwen setup tested on this machine |
| `changes/0.2.2_math_group_evo_deepseek/compose/` | Working Codex + external API example |
| `changes/2_thb_netflix_selfval/` | Original oracle observable experiment (Claude Code) |
| `changes/2.1_thb_netflix_oracle_hidden/` | Original oracle hidden experiment (Claude Code) |
| `changes/0_baxbench_nl2_tests/scripts/` | Base experiment scripts (sandbox.py, run_job.py, common.py) |
| `.envs/venvs/vllm/` | vLLM Python environment |
| `.envs/venvs/thb-validator/` | Validator Python environment |
| `.envs/cache/hf/` | Hugging Face model cache |
| `benchmarks/env-gen/` | Frozen env-gen benchmark (READ ONLY) |
