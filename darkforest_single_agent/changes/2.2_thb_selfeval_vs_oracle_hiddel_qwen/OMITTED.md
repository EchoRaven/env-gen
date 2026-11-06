# What this export of 2.2 leaves out

| reason | items | size |
|---|---|---|
| staged copy of the snapshot the dev evaluator ran | 74 | 4717 MB |
| staged copy of the snapshot the hidden evaluation ran | 29 | 2494 MB |
| the judge's copies of the reference and the screenshot (both kept elsewhere) | 1277 | 1935 MB |
| workspace copy byte-identical to an env-gen design asset (listed in ASSET_COPIES.tsv) | 12444 | 1640 MB |
| copy of the snapshot the dev evaluator ran | 33 | 1229 MB |
| the agent's caches (pip, playwright, ...) | 2 | 1023 MB |
| build output (vite build) | 20 | 799 MB |
| the run's final workspace, the same as snapshots/iter20/workspace apart from a .venv | 2 | 516 MB |
| the agent's npm cache | 2 | 371 MB |
| Python packages the agent installed with pip --user | 20 | 328 MB |
| staged copies used to serve snapshots on localhost | 2 | 164 MB |
| Codex's internal sqlite state (the session transcripts are kept in .codex/sessions) | 102 | 58 MB |
| the second account's Claude config: credentials metadata, settings, sessions | 1 | 7 MB |
| the builder agent's Claude/Codex home (account data) | 1 | 1 MB |
| the builder agent's home on the second account (account data) | 1 | 1 MB |
| bytecode | 3 | 0 MB |
| temp files and caches (vLLM, torch inductor) | 1 | 0 MB |
| the builder agent's own session logs (it built 2.2; not part of the experiment) | 1 | 0 MB |
| temp files | 1 | 0 MB |
| Codex's captured shell environments | 6 | 0 MB |
| Claude account config | 8 | 0 MB |
| the builder agent's first session output before an auth fix (account data) | 1 | 0 MB |
| Codex installation id | 6 | 0 MB |
| process id | 5 | 0 MB |
| lock file | 6 | 0 MB |
| Codex temp files | 6 | 0 MB |
| lock files | 6 | 0 MB |

In every kept text file, Claude account emails, names and ids are replaced with placeholders such as `<emailAddress>`, the second account's owner's name with `acct2`, and the local user name in paths with `user`.
