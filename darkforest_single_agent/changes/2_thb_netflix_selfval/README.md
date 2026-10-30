# 2_thb_netflix_selfval: single Claude Code agent builds env-gen's Netflix app, with self-validation

Started 2026-10-28. The goal is the single-agent ceiling on a harder build-from-spec task than BaxBench. Arm E of
`../1_baxbench_evalfb/` (evaluator feedback) reached 9/9 by iteration 3, so BaxBench is too shallow for that.

**Question.** One Claude Code session builds the env-gen ("thb") Netflix clone from its spec over 5 iterations. It
can run env-gen's own deterministic validation as often as it wants (within a cap) and gets the harness's report
after each submission. How far does it get, and how fast?

**Interpretation.**
- The agent sees every automated check, and it may read the validator's source. The automated score is therefore
  the ceiling on *visible* checks and invites gaming them (env-gen's own history: runs with a fake probe route rose
  from 0/83 to 25/65).
- The held-out judge is a person using the running app against the reference screenshots and the spec
  (`scripts/view.py`).
- It is not comparable to env-gen pipeline results, because only part of their gates run here (see below).

## Design

| Item | Setting |
|---|---|
| Benchmark | `benchmarks/env-gen` (frozen, commit `1c0a5dba`), task `design_inputs/netflix` |
| Agent | Settings come from `../0_baxbench_nl2_tests/config.json`: Claude Code 2.1.304, `claude-opus-5-5`, `--effort medium`, bypassPermissions, no web tools. One session per run via `--resume`. Subscription only; nothing calls a paid API |
| Iterations | 5, at most 4 h each. Iteration 1 gets `prompts/iter1.txt` (the task text verbatim, materials, deliverable, validation). Iterations 2–5 get the harness report on the previous submission plus `prompts/loop.txt` |
| Loop (`prompts/loop.txt`) | (1) Continue from the current state and the last report, and make a better version. (2) Check it with every validation available. (3) When confident, submit by ending the turn |
| Self-validation | The `validate` command in the sandbox, at most 20 calls per iteration. The request goes to a broker thread outside the sandbox (`scripts/run_selfval_job.py`), which snapshots `/workspace` and runs `scripts/validator.py` |
| Official score | After each submission the harness validates `snapshots/iter<k>` itself (`evals/r<run>/official-it<k>/`, `official_scores.jsonl`). The agent sees this report at the start of the next iteration |
| Validator | env-gen's `run_smoke_validation` (api_smoke), imported unmodified from the frozen repo. It covers clean compose boot, health, register/login, password check, 401 without a token, every contract endpoint implemented with the right shape, writes persist, the contract-projected CRUD business chain, and frontend reachable, navigable, fallback pages and dead controls. Also reported: endpoints answering 2xx, chain steps ok, and the files the framework "repaired" in the validated copy |
| Not run | Anything that calls an LLM (visual-fidelity judge, test-user agents); the delivery gate and deliverability audits (they read env-gen's internal pipeline hubs); MCP probes |
| Contract | `contract/netflix.json`, frozen from `DESCRIPTION.txt` by `contract/make_contract.py`: 17 endpoints, all required; `/api/*` needs a token; request bodies only for `POST /api/profiles` and `POST /api/my-list`, taken from the data model. The agent cannot change it. Tables are not passed to the validator, so it adds no synthetic "missing write path" chain (`continue_watching` has a GET and no write in the task text) |

## Sandbox (extends the baseline's)

The baseline bwrap sandbox (`../0_baxbench_nl2_tests/scripts/sandbox.py`, unmodified) runs with the workspace at
`/workspace`, plus:

- **Read-only mounts:**
  - Node 22 at `/opt/node`, an existing install that is only mounted;
  - `sandbox_tools/` at `/opt/thbval`;
  - the contract at `/opt/thbval-contract.json`;
  - the task materials at `/workspace/design`;
  - the frozen env-gen repo at `/thb`. This is an explicit exception to CLAUDE.md Rule 2 that the user approved: the agent may read env-gen's validation workflow.
- **Read-write mount:** `validate_io/` at `/validate_io`.
- **No docker in the sandbox.** Docker builds and runs the agent's compose file as root outside the sandbox, so `validator.py` refuses a compose file that reaches the host:
  - bind mounts, build contexts, env files, secrets or configs outside the project;
  - privileged containers, `cap_add`, devices or `security_opt`;
  - host or container network, pid or ipc namespaces.
- **Network:** shared with the host, for npm and PyPI. WebFetch and WebSearch are disabled.

## Files

| Path | Content |
|---|---|
| `config.json` | Iterations, timeouts, validate-call cap, Node path |
| `contract/` | `make_contract.py` and the frozen `netflix.json` |
| `prompts/` | `iter1.txt`, `next_iter.txt`, `loop.txt` |
| `sandbox_tools/validate` | The in-sandbox command (request file in `/validate_io`, wait for the response) |
| `scripts/validator.py` | Stage a snapshot, check the compose policy, run env-gen api_smoke, write `report.json` / `report.txt` |
| `scripts/run_selfval_job.py` | The job: agent loop, broker thread, official validation |
| `scripts/launch.sh` | Start or resume a run in the background (nohup, setsid) |
| `scripts/view.py` | Boot one iteration's app for a person (ports shifted by 10000 + 100·iter) |
| `probe/toy/` | A minimal app used to test the validator plumbing (not part of the experiment) |
| `runs/netflix__r<run>/` | `status.json`, `job.log`, prompts, CLI results, `workspace/`, `snapshots/iter<k>/`, `validate_io/` |
| `evals/r<run>/` | `it<k>-call<NN>-<id>/` (agent calls), `official-it<k>/`, `agent_calls.jsonl`, `official_scores.jsonl` |

## How to run

```bash
cd /home/user/project/shabi_forest/changes/2_thb_netflix_selfval
scripts/launch.sh 0                       # run 0, resumable
tail -f logs/job_r0.log
# view an iteration (after it is submitted):
sg docker -c "../../.envs/venvs/thb-validator/bin/python -I -B scripts/view.py 1"
sg docker -c "../../.envs/venvs/thb-validator/bin/python -I -B scripts/view.py 1 --down"
```

Validator environment: `.envs/venvs/thb-validator`, which has env-gen's `pyproject.toml` dependencies. No API keys
are set; the validator runs under `env -i`.
