# Cutover 13 Baseline (Review Quality Hard Gates)

## Test counts
- regressions: 7 OK
- discover: 509 OK

## Today's gap
`CodeHub.submit_review(state="approve", inline_comments=[], comments=[])` is
currently accepted. Two such "LGTM" reviews satisfy the Cutover-7 2-reviewer
rule and let the PR merge. This is review-as-compliance-theater.

## After Cutover 13
- `submit_review` rejects `state=="approve"` without >=1 inline_comment cited on a real diff line
- `submit_review` rejects `state=="approve"` without >=1 considered_alternatives entry
- merge-gate `_is_pr_approved` defends in depth: silently downgrades substantively-empty approvals
- review_worker prompt + orchestrator prompt teach the new contract
