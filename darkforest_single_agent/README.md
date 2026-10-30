# darkforest_single_agent: what was pushed, and where everything is

This directory was added to `feat/netflix-generality-366-367` by xingsixue123 on 2026-10-30, on top of `1c0a5db`
(the commit the experiments were run against).

It holds two runs of **one Claude Code agent** (Opus 5.5, effort medium) building env-gen's Netflix app from
`design_inputs/netflix` over 5 iterations:

| Experiment | Directory | What the agent could see |
|---|---|---|
| **2_ oracle visible** | [`changes/2_thb_netflix_selfval/`](changes/2_thb_netflix_selfval/) | It could run env-gen's api_smoke itself, through a `validate` command, and read its source |
| **2.1 oracle hidden** | [`changes/2.1_thb_netflix_oracle_hidden/`](changes/2.1_thb_netflix_oracle_hidden/) | One submission per iteration. The api_smoke report came after each submission. It was told about further checks it could not see. A hidden evaluation then scored every submission of both experiments |

Nothing outside this directory was changed, apart from a short pointer file at the repository root,
`DARKFOREST_README.md`.

## Start here

| To see | Open |
|---|---|
| Design, hidden evaluation, results, and the comparison with env-gen's r134 | [`REPORT.md`](REPORT.md) |
| What was left out and why (copies, caches, account data) | [`OMITTED.md`](OMITTED.md) |
| Each experiment's design, settings and how to run it | [2_ README](changes/2_thb_netflix_selfval/README.md), [2.1 README](changes/2.1_thb_netflix_oracle_hidden/README.md) |
| Every score of every submission in one file | [`evals/compare_r0.json`](changes/2.1_thb_netflix_oracle_hidden/evals/compare_r0.json) |

**Headline.**
- Both agents passed api_smoke by iteration 1 (2_) or 2 (2.1).
- Both passed every hidden functional check (49 API, 23 UI walk) in every iteration.
- Both plateaued in visual similarity at about 0.73–0.74 from iteration 1–2 on.
- Hiding the oracle did not raise the ceiling: the 2.1 agent stopped improving once api_smoke passed.

## Records of each run

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

## Inside one hidden-evaluation folder (`evals/hidden/<tag>/`)

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

There is one JSON event per line. Screenshots the agent took are embedded as base64, which is why the files are
large. To list the tool calls:

```python
import json
for line in open(path):
    e = json.loads(line)
    if e.get("type") == "assistant":
        for c in e["message"]["content"]:
            if c.get("type") == "tool_use":
                print(c["name"], json.dumps(c["input"])[:120])
```

## Redaction and paths

- The Claude account's email, names and ids are replaced with placeholders such as `<emailAddress>`.
- The local user name is replaced with `user`, so paths read `/home/user/...`.
- Scripts assume the project root `/home/user/project/shabi_forest`, with env-gen at `benchmarks/env-gen`
  (commit `1c0a5dba`).
