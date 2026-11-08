# What this export of 2.3 leaves out

| reason | items | size |
|---|---|---|
| staged copy of the snapshot the dev evaluator ran | 83 | 4395 MB |
| the agent's caches (pip, playwright, ...) | 4 | 3780 MB |
| staged copy of the snapshot the hidden evaluation ran | 29 | 1842 MB |
| copy of the snapshot the dev evaluator ran | 39 | 1552 MB |
| Python packages the agent installed with pip --user | 3 | 1502 MB |
| workspace copy byte-identical to an env-gen design asset (listed in ASSET_COPIES.tsv) | 11220 | 1396 MB |
| the agent's npm cache | 4 | 685 MB |
| build output (vite build) | 20 | 429 MB |
| the run's final workspace, identical to its last snapshot (checked before export) | 4 | 201 MB |
| staged copies used to serve snapshots on localhost | 2 | 116 MB |
| the judge's copies of the reference and the screenshot (both kept elsewhere) | 56 | 90 MB |
| Codex's internal sqlite state (the session transcripts are kept in .codex/sessions) | 104 | 70 MB |
| Codex installation id | 6 | 0 MB |
| process id | 7 | 0 MB |
| lock file | 10 | 0 MB |
| Codex temp files | 6 | 0 MB |
| Codex's captured shell environments | 6 | 0 MB |
| lock files | 6 | 0 MB |

In every kept text file, Claude account emails, names and ids are replaced with placeholders such as `<emailAddress>`, the second account's owner's name with `acct2`, and the local user name in paths with `user`.
