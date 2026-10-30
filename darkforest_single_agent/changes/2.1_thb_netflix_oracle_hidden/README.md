# 2.1_thb_netflix_oracle_hidden: single Claude Code agent builds env-gen's Netflix app, oracle hidden

Started 2026-10-29. Successor to `../2_thb_netflix_selfval/`. In 2_ the agent could read the validator's source and
call it 20 times per iteration. It read the source before writing any code, passed all 14 checks on its first call,
and the score never moved again. That measured the ceiling of a fully transparent, shallow oracle.

**Question.** With the measurement oracle hidden, as env-gen's own north-star plan requires ("an independent oracle
the LLM agents never see and cannot game"), what does one agent reach in 5 submissions, and does what it is shown
(dev) track what it is not shown (hidden)?

## What the agent sees

The agent sees what env-gen's worker lanes see, minus anything they author themselves:
- The task text, the materials and the deliverable contract. The contract is frozen from DESCRIPTION.txt, unlike
  env-gen, where the team registers its own contract.
- After each submission, the **dev report**: env-gen's api_smoke verdicts, their details and the business-chain
  steps. In env-gen too, gate outcomes and their explanations are replayed to the lanes
  (`remediation_dispatcher.py:3775-3800, 4069-4082`).
- One sentence saying that further checks it cannot see evaluate every submission.

What it does not see:
- the evaluator's source (in env-gen the lane file tools are confined to the workspace; 2_ mounted it, 2.1 does not);
- a validate tool;
- docker;
- any hidden result.

## Loop

An iteration is one submission:
1. The agent works and tests with what the sandbox offers: builds, its own tests, a local database, a headless
   browser.
2. It submits by ending its turn.
3. The harness snapshots the workspace and runs the dev evaluation once. The report opens the next iteration.
4. The harness starts the hidden evaluation in the background.

There are 5 iterations, so the agent sees dev feedback 4 times. The 5th submission is evaluated too.

## Hidden evaluation (`scripts/hidden_eval.py`; results under `evals/hidden/`, never mounted in the sandbox)

| Part | What | Source |
|---|---|---|
| H1 `hidden/api_suite.py` | 49 black-box API checks in six families: auth, catalog fidelity to the dataset, profiles, per-profile and cross-account privacy, writes and input validation. It uses its own accounts and data, unlike the dev chain. Conventions the task leaves open are tolerated through env-gen's north-star `_conventions.py`, including how a profile is selected, which is detected | Written from DESCRIPTION.txt + docs/spec.md |
| H1b `hidden/ui_walk.py` | 23-step Playwright walk as a user: Sign In → profile → hero and rails → 7 nav items to the spec's routes → poster → detail → + My List → another profile → search → Play → back → account menu → Sign out; broken images; console errors | The spec's screens and controls, found by role, label and text |
| H2 `hidden/static_audit.py` | env-gen's static honesty / privacy / gate-gaming detectors (parked probe route, static data twin, masked API failure, fabricated fallback, …), unmodified, plus a scan for code that recognises the dev evaluator | Frozen env-gen; calibration records which detectors can fire on this layout |
| H3 `hidden/visual.py` | env-gen's own visual-fidelity judge: its prompt (`_JUDGE_INSTRUCTIONS` + `_rubric_block`) and parser (`_parse_verdict`). The judge is `claude -p` (Opus 5.5, subscription) in the baseline sandbox, with only the Read tool and the two images. 20 reference states captured at 1920×1107, 3 judgments each; env-gen's bar is 0.55. A parse failure is retried, then recorded as missing, not as 0 | Frozen env-gen |
| H4 | A person: `scripts/stack.py view <iter>` (127.0.0.1 only) and the comparison sheets | — |

**Calibration** (`scripts/calibrate.py`, `evals/calibration/report.json`):
- One planted defect per check family on a copy of 2_'s iteration 5, from the classes env-gen recorded in real runs.
- Failures on the clean snapshot were adjudicated by hand before freezing. Every one so far was a defect in the
  check (a wrong rating value, a selector, a profile-name collision with the app's auto-created profile), fixed in
  the check.
- There is no hand-written known-good reference app, so the clean arm is an agent output. A check that the clean arm
  passes can still be wrong.

## Files

| Path | Content |
|---|---|
| `config.json` | Iterations, timeouts, hidden-eval settings (port offset, judge model / effort / repeats) |
| `contract/netflix.json` | Copy of 2_'s frozen contract (identical) |
| `prompts/` | `iter1.txt`, `next_iter.txt`, `loop.txt` |
| `scripts/run_hidden_job.py`, `scripts/launch.sh` | The job and its background launcher |
| `scripts/dev_validator.py` | Dev evaluation, using 2_'s `validator.py` staging, policy and metrics, imported unmodified |
| `scripts/stack.py` | Boot a snapshot on shifted localhost ports, for the hidden evaluation and for people |
| `scripts/hidden_eval.py`, `scripts/hidden/` | Hidden evaluation H1–H3 |
| `scripts/calibrate.py` | Planted-defect calibration |
| `runs/netflix__r<run>/` | `status.json`, `job.log`, prompts, CLI results, `workspace/`, `snapshots/iter<k>/` |
| `evals/dev/`, `evals/hidden/` | Dev reports (shown) and hidden results (never shown), per iteration; `evals/hidden/selfval-it<k>/` re-scores 2_ |

## How to run

```bash
cd /home/user/project/shabi_forest/changes/2.1_thb_netflix_oracle_hidden
scripts/launch.sh 0                                   # run 0, resumable
tail -f runs/netflix__r0/job.log
# look at an iteration:
sg docker -c "../../.envs/venvs/thb-validator/bin/python -I -B scripts/stack.py view 1"          # 2.1 iteration 1
sg docker -c "../../.envs/venvs/thb-validator/bin/python -I -B scripts/stack.py view 1 --exp selfval"   # 2_ iteration 1
```
