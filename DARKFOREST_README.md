# DarkForest experiments on this branch

On 2026-10-30, xingsixue123 added [`darkforest_single_agent/`](darkforest_single_agent/README.md) to this branch.
It holds two runs of a single Claude Code agent (Opus 5.5) building env-gen's Netflix app over 5 iterations:

- one where the agent could run api_smoke itself (oracle visible);
- one where it saw only the per-submission report and was scored by a hidden evaluation (oracle hidden).

For each run it includes:
- the code and prompts;
- the agent transcripts;
- every iteration's submission;
- the dev reports;
- the hidden evaluation and its calibration.

**Start at [`darkforest_single_agent/README.md`](darkforest_single_agent/README.md)**, which is a map of
everything. The write-up is [`darkforest_single_agent/REPORT.md`](darkforest_single_agent/REPORT.md).

These commits change nothing else in the repository.
