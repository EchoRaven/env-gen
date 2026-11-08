# darkforest_single_agent: what was pushed, and where everything is

xingsixue123 added this directory to `feat/netflix-generality-366-367`, on top of `1c0a5db` (the env-gen commit every
run was scored against), in three pushes:
- **2026-10-30:** the **Claude** solves (experiments 2_ and 2.1);
- **2026-11-06:** the **Qwen** solves (experiment 2.2);
- **2026-11-08:** the **DeepSeek** solves (experiment 2.3).

Every run is **one agent** building env-gen's Netflix app from `design_inputs/netflix`, iteration after iteration. Each
model was run in two settings:
- **Oracle visible** ("selfval"). The agent can run env-gen's api_smoke itself, through a `validate` command, and read
  its source.
- **Oracle hidden.** There is one submission per iteration, and the api_smoke report arrives after each one. The agent
  is told that further checks exist that it cannot see. A hidden evaluation it never sees then scores the submissions
  of both settings.

| Solve | Agent | Oracle visible | Oracle hidden |
|---|---|---|---|
| **Claude** (2_, 2.1) | Claude Code 2.1.304, Opus 5.5, effort medium; 5 iterations | [`changes/2_thb_netflix_selfval/`](changes/2_thb_netflix_selfval/) | [`changes/2.1_thb_netflix_oracle_hidden/`](changes/2.1_thb_netflix_oracle_hidden/) |
| **Qwen** (2.2) | Codex CLI 0.163.0 driving Qwen3.8-27B-INT4 on local vLLM (one RTX 6000 Ada), effort medium; 20 iterations | [`changes/2.2_…_qwen/job_selfval/`](changes/2.2_thb_selfeval_vs_oracle_hiddel_qwen/job_selfval/) | [`changes/2.2_…_qwen/job_oracle_hidden/`](changes/2.2_thb_selfeval_vs_oracle_hiddel_qwen/job_oracle_hidden/) |
| **DeepSeek** (2.3) | Codex CLI 0.163.0 driving deepseek-v4.1-flash through an API (`:fast` tier), effort medium, 1M-token window; 20 iterations | [`changes/2.3_…_deepseek/job_selfval/`](changes/2.3_thb_selfeval_vs_oracle_hidden_deepseek/job_selfval/) | [`changes/2.3_…_deepseek/job_oracle_hidden/`](changes/2.3_thb_selfeval_vs_oracle_hidden_deepseek/job_oracle_hidden/) |

2.2 copies 2_ and 2.1 into `job_selfval/` and `job_oracle_hidden/` and replaces only the worker, which becomes Codex
and Qwen in a bwrap sandbox. Everything else is unchanged:
- the task prompts and the contract;
- the validator and the dev evaluator;
- the hidden evaluator, including its visual judge (Claude Opus 5.5, three judgments per screen).

2.3 copies 2.2 and changes only the model: deepseek-v4.1-flash through a local API gateway instead of Qwen on vLLM,
with the model's native 1M-token window. Everything listed above is byte-identical to 2.2 (md5-checked).

Nothing outside this directory was changed, apart from a short pointer file at the repository root,
`DARKFOREST_README.md`.

## Start here

| To see | Open |
|---|---|
| Claude solves: design, hidden evaluation, results, comparison with env-gen's r134 | [`REPORT.md`](REPORT.md) |
| Qwen solves: setup, results, issues, visual tour | [`2.2 REPORT.md`](changes/2.2_thb_selfeval_vs_oracle_hiddel_qwen/REPORT.md). Its tables were generated on 2026-11-05 at 22:25, before the last visual re-judging, so the current numbers are below |
| DeepSeek solves: setup, results, the two-step sign-in, visual tour, comparison with Qwen and Claude | [`2.3 REPORT.md`](changes/2.3_thb_selfeval_vs_oracle_hidden_deepseek/REPORT.md) |
| What was left out and why (copies, caches, account data) | [`OMITTED.md`](OMITTED.md) for 2_ and 2.1, [`2.2 OMITTED.md`](changes/2.2_thb_selfeval_vs_oracle_hiddel_qwen/OMITTED.md) for 2.2, [`2.3 OMITTED.md`](changes/2.3_thb_selfeval_vs_oracle_hidden_deepseek/OMITTED.md) for 2.3 |
| Each experiment's design, settings and how to run it | [2_ README](changes/2_thb_netflix_selfval/README.md), [2.1 README](changes/2.1_thb_netflix_oracle_hidden/README.md), [2.2 job_selfval README](changes/2.2_thb_selfeval_vs_oracle_hiddel_qwen/job_selfval/README.md), [2.2 job_oracle_hidden README](changes/2.2_thb_selfeval_vs_oracle_hiddel_qwen/job_oracle_hidden/README.md). 2.3's job READMEs are the same as 2.2's; its changes from 2.2 are listed in [`2.3 README_zh.md`](changes/2.3_thb_selfeval_vs_oracle_hidden_deepseek/README_zh.md) (Chinese) |
| Every score of every Claude submission in one file | [`evals/compare_r0.json`](changes/2.1_thb_netflix_oracle_hidden/evals/compare_r0.json) |

**Headline: Claude.**
- Both agents passed api_smoke by iteration 1 (2_) or 2 (2.1).
- Both passed every hidden functional check (49 API, 23 UI walk) in every iteration.
- Both plateaued in visual similarity at about 0.73–0.74 from iteration 1–2 on.
- Hiding the oracle did not raise the ceiling: the 2.1 agent stopped improving once api_smoke passed.

**Headline: Qwen** (same hidden evaluation, so the numbers are directly comparable with Claude's).

| | Oracle visible (job_selfval, 12.3 h) | Oracle hidden (job_oracle_hidden, 3.3 h) |
|---|---|---|
| api_smoke | 14/14 in all 20 iterations. Endpoints answering 2xx: 12/15, then 13/15, then 15/15 from iteration 15 | it1 did not boot (the database exited); it2 clashed with the vLLM port. 14/14 from iteration 3, with 11/15 endpoints |
| Hidden API (49) | 47 at it1, 46 at it4–13, 42–43 at it16 and it20 | 46 at it2–20 (rating, re-rating and one 4xx case fail) |
| Hidden UI walk | 20/21 at it1, 18/21 at it4–12. **it13 shipped a frontend crash**, a blank page after sign-in (6/22), which api_smoke passed. From it14 the login is a two-step form that the frozen walk cannot sign in through (4/5) | 22/23 at it2–20 |
| Visual (mean of scored screens) | 0.542 → 0.507 (it1–12); 0.298 at it13; none at it16 and it20 (capture could not sign in) | 0.519–0.538 at it2–20; **it8 and it9 not judged yet** |

- Job 1 was hidden-evaluated on 7 sampled iterations: 1, 4, 8, 12, 13, 16 and 20. Job 2 was evaluated on all 20.
- Seeing the oracle bought endpoint coverage and more hours of work, but no hidden gain. Job 1 also regressed in ways
  its oracle could not see.
- Qwen sits well below Claude on the same yardstick: API 46 vs 49, visual about 0.53 vs about 0.74.

**Headline: DeepSeek** (same hidden evaluation; agent time 0.6 h and 1.1 h).

| | Oracle visible (job_selfval) | Oracle hidden (job_oracle_hidden) |
|---|---|---|
| api_smoke | 14/14 in all 20 iterations. Endpoints answering 2xx: 11/15 at it1–9, 14/15 at it10–11, 15/15 from it12 | 13/14 at it1 (business chain 5/8), then 14/14. 11/15 endpoints throughout |
| Hidden API (49) | 49 at it1, 4 and 8; 47 at it12, 16 and 20 | 49 in all 20 iterations |
| Hidden UI walk | 4/5 everywhere. From iteration 1 the sign-in is two-step (email, Continue, then password), as in the reference `login.jpg`. The frozen walk waits for a password field on the first screen and cannot sign in | 4/5 everywhere, same reason |
| Visual | None: the capture cannot sign in either | None, same reason |

- Job 1 was hidden-evaluated on 6 sampled iterations: 1, 4, 8, 12, 16 and 20. Job 2 was evaluated on all 20.
- The evaluator was left unchanged so the numbers stay comparable. So 2.3 has no visual score.
  - Instead, both final apps were signed into and driven by hand: [job_selfval tour](changes/2.3_thb_selfeval_vs_oracle_hidden_deepseek/job_selfval/results/tour/it20/),
    [job_oracle_hidden tour](changes/2.3_thb_selfeval_vs_oracle_hidden_deepseek/job_oracle_hidden/results/tour/it20/), and side by side with the references in
    [`reference_vs_it20.jpg`](changes/2.3_thb_selfeval_vs_oracle_hidden_deepseek/results/compare/reference_vs_it20.jpg).
  - Indicative only: in the pre-launch smoke run the apps still had a one-step sign-in, and the same evaluator gave
    visual 0.59–0.62. That run had shorter limits and one judgment per screen.
- Seeing the oracle bought the last 4 endpoints by weakening input validation (it10, it12). For example, a profile
  without a name is created as "New Profile", and a My List add without a title adds the top-rated title. The hidden
  suite caught 2 of these changes (49 → 47).
  - So, as for Qwen and Claude, seeing the oracle brought no hidden gain.
- With the oracle hidden, DeepSeek matches Claude on the hidden API (49/49). Qwen was at 46.

## Records of the Claude runs

`R2 = changes/2_thb_netflix_selfval`, `R21 = changes/2.1_thb_netflix_oracle_hidden`; `k` = iteration 1–5.

| Record | 2_ oracle visible | 2.1 oracle hidden |
|---|---|---|
| Task prompt (iteration 1) | [`R2/prompts/iter1.txt`](changes/2_thb_netflix_selfval/prompts/iter1.txt) | [`R21/prompts/iter1.txt`](changes/2.1_thb_netflix_oracle_hidden/prompts/iter1.txt) |
| Prompt actually sent each iteration (with the report) | [`R2/runs/netflix__r0/prompt_iter<k>.txt`](changes/2_thb_netflix_selfval/runs/netflix__r0/) | [`R21/runs/netflix__r0/prompt_iter<k>.txt`](changes/2.1_thb_netflix_oracle_hidden/runs/netflix__r0/) |
| **Agent transcript** (every message, tool call and result; JSONL, about 35 MB, download raw) | [`a6c4d6ed….jsonl`](changes/2_thb_netflix_selfval/runs/netflix__r0/claude_overlay/projects/-workspace/a6c4d6ed-f825-4ef2-89d9-8d54246c96d9.jsonl) | [`bdf44f07….jsonl`](changes/2.1_thb_netflix_oracle_hidden/runs/netflix__r0/claude_overlay/projects/-workspace/bdf44f07-3267-40db-bdd6-e0c724b9a9ff.jsonl) |
| Agent's closing message, turns, tokens and list-price cost per iteration | `R2/runs/netflix__r0/iter<k>_a0.json` | `R21/runs/netflix__r0/iter<k>_a0.json` |
| Run log and timing | [`job.log`](changes/2_thb_netflix_selfval/runs/netflix__r0/job.log), [`status.json`](changes/2_thb_netflix_selfval/runs/netflix__r0/status.json) | [`job.log`](changes/2.1_thb_netflix_oracle_hidden/runs/netflix__r0/job.log), [`status.json`](changes/2.1_thb_netflix_oracle_hidden/runs/netflix__r0/status.json) |
| **Submission of iteration k** (app source, compose, SQL) | [`R2/runs/netflix__r0/snapshots/iter<k>/workspace/`](changes/2_thb_netflix_selfval/runs/netflix__r0/snapshots/) | [`R21/runs/netflix__r0/snapshots/iter<k>/workspace/`](changes/2.1_thb_netflix_oracle_hidden/runs/netflix__r0/snapshots/) |
| api_smoke report the agent received after iteration k | [`R2/evals/r0/official-it<k>/report.txt`](changes/2_thb_netflix_selfval/evals/r0/) | [`R21/evals/dev/r0-it<k>/report.txt`](changes/2.1_thb_netflix_oracle_hidden/evals/dev/) |
| api_smoke scores per iteration | [`official_scores.jsonl`](changes/2_thb_netflix_selfval/evals/r0/official_scores.jsonl) | [`r0_scores.jsonl`](changes/2.1_thb_netflix_oracle_hidden/evals/dev/r0_scores.jsonl) |
| The agent's own `validate` calls (6) | [`R2/evals/r0/it<k>-call<n>-*/report.txt`](changes/2_thb_netflix_selfval/evals/r0/), [`agent_calls.jsonl`](changes/2_thb_netflix_selfval/evals/r0/agent_calls.jsonl) | none (no validate command) |
| **Hidden evaluation of iteration k** | [`R21/evals/hidden/selfval-it<k>/`](changes/2.1_thb_netflix_oracle_hidden/evals/hidden/) | [`R21/evals/hidden/r0-it<k>/`](changes/2.1_thb_netflix_oracle_hidden/evals/hidden/) |
| Harness code | [`R2/scripts/`](changes/2_thb_netflix_selfval/scripts/) (`run_selfval_job.py`, `validator.py`), [`sandbox_tools/validate`](changes/2_thb_netflix_selfval/sandbox_tools/validate) | [`R21/scripts/`](changes/2.1_thb_netflix_oracle_hidden/scripts/) (`run_hidden_job.py`, `dev_validator.py`, `stack.py`) |

## Records of the Qwen runs (2.2)

`Q = changes/2.2_thb_selfeval_vs_oracle_hiddel_qwen`, `QS = Q/job_selfval`, `QH = Q/job_oracle_hidden`; `k` =
iteration 1–20.

| Record | Oracle visible (`QS`) | Oracle hidden (`QH`) |
|---|---|---|
| Setup, results, issues, tour notes | [`Q/REPORT.md`](changes/2.2_thb_selfeval_vs_oracle_hiddel_qwen/REPORT.md), [`Q/PROGRESS.md`](changes/2.2_thb_selfeval_vs_oracle_hiddel_qwen/PROGRESS.md) (build log with every issue fixed) | same |
| Task prompt (iteration 1) | [`QS/prompts/iter1.txt`](changes/2.2_thb_selfeval_vs_oracle_hiddel_qwen/job_selfval/prompts/iter1.txt) | [`QH/prompts/iter1.txt`](changes/2.2_thb_selfeval_vs_oracle_hiddel_qwen/job_oracle_hidden/prompts/iter1.txt) |
| Prompt actually sent each iteration | [`QS/runs/netflix__r0/prompt_iter<k>.txt`](changes/2.2_thb_selfeval_vs_oracle_hiddel_qwen/job_selfval/runs/netflix__r0/) | [`QH/runs/netflix__r0/prompt_iter<k>.txt`](changes/2.2_thb_selfeval_vs_oracle_hiddel_qwen/job_oracle_hidden/runs/netflix__r0/) |
| **Agent transcript** (Codex rollout, JSONL; 25 MB and 6.8 MB) | [`rollout-…T02-13-10….jsonl`](changes/2.2_thb_selfeval_vs_oracle_hiddel_qwen/job_selfval/runs/netflix__r0/home/.codex/sessions/2026/11/05/rollout-2026-11-05T02-13-10-01a1aa8d-ec2f-7713-b498-c51f1cb3cb3d.jsonl) | [`rollout-…T14-38-45….jsonl`](changes/2.2_thb_selfeval_vs_oracle_hiddel_qwen/job_oracle_hidden/runs/netflix__r0/home/.codex/sessions/2026/11/05/rollout-2026-11-05T14-38-45-01a1ad38-895c-7ee3-b9d3-85fb2471f421.jsonl) |
| Codex's output per iteration | `QS/runs/netflix__r0/cli/iter<k>_a0.json` | `QH/runs/netflix__r0/cli/iter<k>_a0.json` |
| Run log and timing | [`job.log`](changes/2.2_thb_selfeval_vs_oracle_hiddel_qwen/job_selfval/runs/netflix__r0/job.log), [`status.json`](changes/2.2_thb_selfeval_vs_oracle_hiddel_qwen/job_selfval/runs/netflix__r0/status.json) | [`job.log`](changes/2.2_thb_selfeval_vs_oracle_hiddel_qwen/job_oracle_hidden/runs/netflix__r0/job.log), [`status.json`](changes/2.2_thb_selfeval_vs_oracle_hiddel_qwen/job_oracle_hidden/runs/netflix__r0/status.json) |
| **Submission of iteration k** | [`QS/runs/netflix__r0/snapshots/iter<k>/workspace/`](changes/2.2_thb_selfeval_vs_oracle_hiddel_qwen/job_selfval/runs/netflix__r0/snapshots/) | [`QH/runs/netflix__r0/snapshots/iter<k>/workspace/`](changes/2.2_thb_selfeval_vs_oracle_hiddel_qwen/job_oracle_hidden/runs/netflix__r0/snapshots/) |
| api_smoke report the agent received after iteration k | [`QS/evals/r0/official-it<k>/report.txt`](changes/2.2_thb_selfeval_vs_oracle_hiddel_qwen/job_selfval/evals/r0/) | [`QH/evals/dev/r0-it<k>/report.txt`](changes/2.2_thb_selfeval_vs_oracle_hiddel_qwen/job_oracle_hidden/evals/dev/). `evals/dev_rescore/r0-it12` re-scores it12 after the fact, because the original run hit an infra clash |
| api_smoke scores per iteration | [`official_scores.jsonl`](changes/2.2_thb_selfeval_vs_oracle_hiddel_qwen/job_selfval/evals/r0/official_scores.jsonl) | [`r0_scores.jsonl`](changes/2.2_thb_selfeval_vs_oracle_hiddel_qwen/job_oracle_hidden/evals/dev/r0_scores.jsonl) |
| The agent's own `validate` calls (33) | [`QS/evals/r0/it<k>-call<n>-*/report.txt`](changes/2.2_thb_selfeval_vs_oracle_hiddel_qwen/job_selfval/evals/r0/), [`agent_calls.jsonl`](changes/2.2_thb_selfeval_vs_oracle_hiddel_qwen/job_selfval/evals/r0/agent_calls.jsonl) | none (no validate command) |
| **Hidden evaluation of iteration k** | [`QH/evals/hidden/selfval-it<k>/`](changes/2.2_thb_selfeval_vs_oracle_hiddel_qwen/job_oracle_hidden/evals/hidden/) for k = 1, 4, 8, 12, 13, 16, 20 (plus `dryrun-selfval-it1` and `selfval-it16-rerun`) | [`QH/evals/hidden/r0-it<k>/`](changes/2.2_thb_selfeval_vs_oracle_hiddel_qwen/job_oracle_hidden/evals/hidden/) |
| Iteration 20 driven through its UI (screens, contact sheet, notes) | [`QS/results/tour/it20/`](changes/2.2_thb_selfeval_vs_oracle_hiddel_qwen/job_selfval/results/tour/it20/) | [`QH/results/tour/it20/`](changes/2.2_thb_selfeval_vs_oracle_hiddel_qwen/job_oracle_hidden/results/tour/it20/) |
| Harness code | [`Q/common/`](changes/2.2_thb_selfeval_vs_oracle_hiddel_qwen/common/) (`codex_worker.py`: bwrap Codex worker; `claude_judge.py`: visual judge; `tour.py`), [`Q/scripts/`](changes/2.2_thb_selfeval_vs_oracle_hiddel_qwen/scripts/) (vLLM launch, `collect.py`, re-judge loop), `QS/scripts/` | same `Q/common/` and `Q/scripts/`, plus `QH/scripts/` (with `rejudge.py`) |

**Also in `Q/`.**
- **The vLLM server log** (`vllm_server.log`).
- **Context and compaction smoke tests** (`smoke/`).
- **`specs.md`**, the user's task description.
- **`auto_agent/`.** The harness was adapted and the jobs run by an autonomous Claude Code agent on a second account,
  driven by `auto_agent/JOB_SPEC.md` and `SAFETY_RULES.md`. That agent's own session logs and account homes are not
  included.
- **`ASSET_COPIES.tsv`.** It lists every workspace file left out because it was byte-identical to an env-gen design
  asset (Qwen copied the assets into `app/assets/` and `app/frontend/public/media/`). Copy them back from
  `design_inputs/netflix/assets/` to rebuild a workspace.

**Not finished in 2.2.**
- **Job 2, iterations 8 and 9.** The visual judge hit its quota, so the screens are captured but not judged.
  `QH/scripts/rejudge.py r0-it8 r0-it9` would finish them.
- **REPORT.md's tables** predate the re-judging of iterations 3, 5–7 and 18–20. `scripts/collect.py --report`
  regenerates them.

## Records of the DeepSeek runs (2.3)

`D = changes/2.3_thb_selfeval_vs_oracle_hidden_deepseek`, `DS = D/job_selfval`, `DH = D/job_oracle_hidden`; `k` =
iteration 1–20. The layout is 2.2's.

| Record | Oracle visible (`DS`) | Oracle hidden (`DH`) |
|---|---|---|
| Setup, results, issues, tour notes | [`D/REPORT.md`](changes/2.3_thb_selfeval_vs_oracle_hidden_deepseek/REPORT.md), [`D/README_zh.md`](changes/2.3_thb_selfeval_vs_oracle_hidden_deepseek/README_zh.md) (Chinese: every change from 2.2, the smoke record and the run log) | same |
| Task prompt (iteration 1) | [`DS/prompts/iter1.txt`](changes/2.3_thb_selfeval_vs_oracle_hidden_deepseek/job_selfval/prompts/iter1.txt) | [`DH/prompts/iter1.txt`](changes/2.3_thb_selfeval_vs_oracle_hidden_deepseek/job_oracle_hidden/prompts/iter1.txt) |
| Prompt actually sent each iteration | [`DS/runs/netflix__r0/prompt_iter<k>.txt`](changes/2.3_thb_selfeval_vs_oracle_hidden_deepseek/job_selfval/runs/netflix__r0/) | [`DH/runs/netflix__r0/prompt_iter<k>.txt`](changes/2.3_thb_selfeval_vs_oracle_hidden_deepseek/job_oracle_hidden/runs/netflix__r0/) |
| **Agent transcript** (Codex rollout, JSONL; 5.9 MB and 7.3 MB; one session per job, no compaction) | [`rollout-…T03-32-51….jsonl`](changes/2.3_thb_selfeval_vs_oracle_hidden_deepseek/job_selfval/runs/netflix__r0/home/.codex/sessions/2026/11/08/rollout-2026-11-08T03-32-51-01a1ba49-f40e-7a31-8fa1-578c13af04af.jsonl) | [`rollout-…T04-16-54….jsonl`](changes/2.3_thb_selfeval_vs_oracle_hidden_deepseek/job_oracle_hidden/runs/netflix__r0/home/.codex/sessions/2026/11/08/rollout-2026-11-08T04-16-54-01a1ba72-4816-7400-b355-424455a4cce6.jsonl) |
| Codex's output per iteration | `DS/runs/netflix__r0/cli/iter<k>_a0.json` | `DH/runs/netflix__r0/cli/iter<k>_a0.json` |
| Run log and timing | [`job.log`](changes/2.3_thb_selfeval_vs_oracle_hidden_deepseek/job_selfval/runs/netflix__r0/job.log), [`status.json`](changes/2.3_thb_selfeval_vs_oracle_hidden_deepseek/job_selfval/runs/netflix__r0/status.json) | [`job.log`](changes/2.3_thb_selfeval_vs_oracle_hidden_deepseek/job_oracle_hidden/runs/netflix__r0/job.log), [`status.json`](changes/2.3_thb_selfeval_vs_oracle_hidden_deepseek/job_oracle_hidden/runs/netflix__r0/status.json) |
| **Submission of iteration k** | [`DS/runs/netflix__r0/snapshots/iter<k>/workspace/`](changes/2.3_thb_selfeval_vs_oracle_hidden_deepseek/job_selfval/runs/netflix__r0/snapshots/) | [`DH/runs/netflix__r0/snapshots/iter<k>/workspace/`](changes/2.3_thb_selfeval_vs_oracle_hidden_deepseek/job_oracle_hidden/runs/netflix__r0/snapshots/) |
| api_smoke report the agent received after iteration k | [`DS/evals/r0/official-it<k>/report.txt`](changes/2.3_thb_selfeval_vs_oracle_hidden_deepseek/job_selfval/evals/r0/) | [`DH/evals/dev/r0-it<k>/report.txt`](changes/2.3_thb_selfeval_vs_oracle_hidden_deepseek/job_oracle_hidden/evals/dev/) |
| api_smoke scores per iteration | [`official_scores.jsonl`](changes/2.3_thb_selfeval_vs_oracle_hidden_deepseek/job_selfval/evals/r0/official_scores.jsonl) | [`r0_scores.jsonl`](changes/2.3_thb_selfeval_vs_oracle_hidden_deepseek/job_oracle_hidden/evals/dev/r0_scores.jsonl) |
| The agent's own `validate` calls (30) | [`DS/evals/r0/it<k>-call<n>-*/report.txt`](changes/2.3_thb_selfeval_vs_oracle_hidden_deepseek/job_selfval/evals/r0/), [`agent_calls.jsonl`](changes/2.3_thb_selfeval_vs_oracle_hidden_deepseek/job_selfval/evals/r0/agent_calls.jsonl) | none (no validate command) |
| **Hidden evaluation of iteration k** | [`DH/evals/hidden/selfval-it<k>/`](changes/2.3_thb_selfeval_vs_oracle_hidden_deepseek/job_oracle_hidden/evals/hidden/) for k = 1, 4, 8, 12, 16, 20 | [`DH/evals/hidden/r0-it<k>/`](changes/2.3_thb_selfeval_vs_oracle_hidden_deepseek/job_oracle_hidden/evals/hidden/) |
| Iteration 20 driven through its UI (screens, contact sheets, notes) | [`DS/results/tour/it20/`](changes/2.3_thb_selfeval_vs_oracle_hidden_deepseek/job_selfval/results/tour/it20/) | [`DH/results/tour/it20/`](changes/2.3_thb_selfeval_vs_oracle_hidden_deepseek/job_oracle_hidden/results/tour/it20/) |
| Harness code | [`D/common/`](changes/2.3_thb_selfeval_vs_oracle_hidden_deepseek/common/) (`codex_worker.py`, `claude_judge.py`, `tour.py`), [`D/scripts/`](changes/2.3_thb_selfeval_vs_oracle_hidden_deepseek/scripts/) (`llm_gateway.py`: the API gateway; `pipeline.py`: runs both jobs, the hidden evaluation and `collect.py`; `manual_check.py`: the hand-driven follow-up to the tour), `DS/scripts/` | same `D/common/` and `D/scripts/`, plus `DH/scripts/` |

**Also in `D/`.**
- **`logs/`.** The pipeline log, plus the hidden-evaluation and re-judge logs. `logs/gateway/gateway.jsonl` has one
  line per model request: status, retries, timing and token counts, but no content.
- **`smoke/`.** The pre-launch tests: a tool-call probe, a 942,714-token request with a real compaction and resume
  (`long_compact`), and `e2e`, which ran 2 iterations of each job and scored them with the hidden evaluation, visual
  judge included (job 1: iteration 1 only).
- **`results/`.** `tables.md` and `summary.json` (every score), and `compare/reference_vs_it20.jpg`.
- **`ASSET_COPIES.tsv`.** As in 2.2, it lists every workspace file left out because it is byte-identical to an
  env-gen design asset.

## Inside one hidden-evaluation folder (`evals/hidden/<tag>/`, in 2.1 and in 2.2's and 2.3's `job_oracle_hidden`)

| File | Content |
|---|---|
| `summary.json` | All scores for that submission: API, UI walk, static findings, visual mean and per-screen scores |
| `api.json` | The 49 API checks (category, name, pass or fail, a short detail such as the status code), plus the profile convention detected |
| `ui/ui_walk.json`, `ui/fail_NN.png` | The browser walk's checks, with a screenshot of each failed check |
| `static.json` | Findings of env-gen's 14 static detectors, the two adapted ones, and the dev-evaluator fingerprint scan |
| `visual/shots/*.png` | The 20 screenshots (1920×1107) the judge compared with `design_inputs/netflix` references |
| `visual/visual.json` | Per screen: the mean and SD of three judgments, and each judgment's rubric dimensions and listed deviations |
| `visual/judge/<screen>-<n>/raw.txt` | The judge's raw reply |

**Tags.**
- `r0-it1..5`: 2.1's submissions.
- `selfval-it1..5`: 2_'s submissions.
- `calib-clean` and `calib-<defect>`: the calibration (one planted defect each). Its report is
  [`evals/calibration/report.json`](changes/2.1_thb_netflix_oracle_hidden/evals/calibration/report.json).

**Code.**
- [`scripts/hidden/`](changes/2.1_thb_netflix_oracle_hidden/scripts/hidden/): `api_suite.py`, `ui_walk.py`,
  `static_audit.py` and `visual.py`.
- [`hidden_eval.py`](changes/2.1_thb_netflix_oracle_hidden/scripts/hidden_eval.py) runs them on one snapshot.
- [`calibrate.py`](changes/2.1_thb_netflix_oracle_hidden/scripts/calibrate.py) runs the calibration, and
  [`compare.py`](changes/2.1_thb_netflix_oracle_hidden/scripts/compare.py) builds the comparison table.

## Smaller items

- **`changes/0_baxbench_nl2_tests/`:** the bwrap sandbox (`scripts/sandbox.py`, `scripts/common.py`, `config.json`)
  that both experiments import.
- **`R2/runs/netflix__r0/validate_io/`:** the requests and responses of the agent's `validate` calls.
- **`R2/results/visual/`:** earlier screenshots of 2_'s iterations 1 and 5. `index.html` is a side-by-side page;
  open it locally.
- **`R2/probe/toy/`:** a minimal app used to test the validator plumbing. It is not part of the experiment.
- **`R21/logs/`:** the job log, the hidden-evaluation logs for each iteration, and the calibration and re-score
  logs. env-gen's `.gitignore` excludes `logs/` and `*.log`, so these files were added with `git add -f`.

## Reading a transcript

Each transcript has one JSON event per line.

- **Claude** (`claude_overlay/projects/-workspace/*.jsonl`). Screenshots the agent took are embedded as base64, which
  is why these files are large.
- **Codex** (`home/.codex/sessions/**/rollout-*.jsonl`). The events are `response_item` (`message`, `reasoning`,
  `function_call`, `function_call_output`) and `event_msg` (`task_started` and `task_complete` mark each iteration).
  An event of type `compacted` marks a context compaction.

To list the tool calls:

```python
import json
for line in open(path):
    e = json.loads(line)
    if e.get("type") == "assistant":                       # Claude
        for c in e["message"]["content"]:
            if c.get("type") == "tool_use":
                print(c["name"], json.dumps(c["input"])[:120])
    p = e.get("payload") or {}
    if e.get("type") == "response_item" and p.get("type") == "function_call":   # Codex
        print(p["name"], p["arguments"][:120])
```

## Redaction and paths

- The Claude accounts' emails, names and ids are replaced with placeholders such as `<emailAddress>`. In 2.2 and
  2.3, the second account's owner's name is `acct2`. The email of env-gen's tester, which appears in a reference screenshot
  and is quoted by the agent, is `<tester-email>`.
- Nothing pushed contains any of the local secret files: every file was compared, byte for byte, with each secret.
- The local user name is replaced with `user`, so paths read `/home/user/...`.
- Scripts assume the project root `/home/user/project/shabi_forest`, with env-gen at `benchmarks/env-gen`
  (commit `1c0a5dba`).
