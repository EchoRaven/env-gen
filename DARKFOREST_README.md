# DarkForest experiments on this branch

xingsixue123 added [`darkforest_single_agent/`](darkforest_single_agent/README.md) to this branch. It holds
single-agent solves of env-gen's Netflix task, each run once with the oracle visible and once with it hidden:

- **Claude** (2026-10-30). One Claude Code agent (Opus 5.5), 5 iterations per setting.
- **Qwen** (2026-11-06). Codex CLI driving a local Qwen3.8-27B, 20 iterations per setting. It uses the same task,
  validator and hidden evaluation as the Claude runs.
- **DeepSeek** (2026-11-08). Codex CLI driving deepseek-v4.1-flash through an API, 20 iterations per setting. Only
  the model changed from the Qwen runs.

For each run the directory has:
- the code and prompts;
- the agent transcripts;
- every iteration's submission;
- the api_smoke reports the agent received;
- a hidden evaluation it never saw (API suite, UI walk, static audit, visual judge), with its calibration.

**Start at [`darkforest_single_agent/README.md`](darkforest_single_agent/README.md)**, which maps everything and
gives the headline numbers. These commits change nothing else in the repository.
