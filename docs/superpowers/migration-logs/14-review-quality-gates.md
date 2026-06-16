# Cutover 13: Review Quality Hard Gates

**Branch:** `haibotong-cutover-13-review-quality`
**Date:** 2026-05-24

## What

Stopped "LGTM theater" reviews. `CodeHub.submit_review(state="approve", ...)`
now requires at least one inline_comment (cited on a real diff line) AND at
least one non-empty `considered_alternatives` entry. The merge-time gate
(`_is_pr_approved`) defends in depth: even if a review row is written to the
store bypassing `submit_review` validation, it doesn't count toward approval
unless substantive. Updated the `codehub_review_pr` LLM tool (the real
tool-name in this codebase — see "Discrepancies" below), the `review_worker`
prompt, and orchestrator prompt to teach the new contract.

## Commits

- `2fc5e497` Cutover 13: record pre-flight baseline (regressions 7 OK, discover 509 OK)
- `2aea9d07` CodeHub: submit_review rejects approve without inline_comments + considered_alternatives
- `cf138b4d` CodeHub merge gate: _is_pr_approved filters out non-substantive approve reviews
- `a9dda4aa` codehub_review_pr tool: add considered_alternatives parameter + update description
- `f01ce9a6` review_worker prompt: REVIEW QUALITY CONTRACT — inline_comments + considered_alternatives required
- `c6ee092a` Orchestrator prompt: REVIEW QUALITY — mandatory reviewer must submit substantive approve
- `d8f4d670` Add end-to-end test: rubber-stamp approves blocked; substantive approves merge-ready

## Test deltas
- Regressions: 7 OK -> 7 OK
- Discover: 509 OK -> 534 OK (+25 new tests)

## New surfaces
- `CodeHub.submit_review(considered_alternatives=...)` — new kwarg, validated when `state=="approve"`
- `CodeHub._is_review_substantive(review)` — staticmethod helper used by `_is_pr_approved`
- `codehub_review_pr` LLM tool — new `considered_alternatives` parameter + updated description

## Prompts
- `review_worker_agent.j2`: REVIEW QUALITY CONTRACT block (no LGTM, cite a line, list an alternative)
- `orchestrator_agent.j2`: REVIEW QUALITY block (orchestrator is mandatory reviewer; same rule applies)

## Discrepancies vs. plan

- **Real tool name is `codehub_review_pr`, not `codehub_submit_review`.** The
  plan (Task 4) referred to the LLM tool as `codehub_submit_review`, but the
  registered tool in `agent/env_generator/llm_generator/tools/hub_tools.py`
  is named `codehub_review_pr`. Implementation, the new
  `considered_alternatives` parameter, and the updated description were
  applied to the real tool; commit message `a9dda4aa` and the migration log
  reflect the actual name.

- **Pre-existing test fixtures updated (7 tests).** As called out in Task 2
  Step 5, several pre-Cutover-13 tests submitted `state="approve"` with empty
  `inline_comments` and no `considered_alternatives`. Once the new gate
  landed they had to supply substantive fields to stay green. The fixtures
  were updated in-place (no test was weakened or skipped) — they now create
  substantive approvals matching the new contract. This is the expected cost
  of the gate.

## Known gaps (future cutovers)
- Inline_comment line numbers aren't verified against actual diff lines (no
  diff parsing yet); a malicious reviewer could cite a fake line. Diff-line
  verification is a larger sub-project.
- No "did the reviewer actually read the diff" semantic check; we can only
  verify shape (presence + non-empty strings).
- The substantive check is purely structural — a reviewer could write
  `considered_alternatives=["x"]` and pass. Quality of the alternative isn't
  graded.
