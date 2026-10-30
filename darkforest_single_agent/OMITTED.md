# What this export leaves out

| reason | items | size |
|---|---|---|
| the judge's copies of the reference and the screenshot (both kept elsewhere) | 618 | 1061 MB |
| staged copy of the snapshot the hidden evaluation ran | 20 | 943 MB |
| staged copy of the snapshot the dev evaluator ran | 16 | 754 MB |
| the agent's home: pip/npm/playwright caches and the per-job ~/.claude.json (account data) | 2 | 445 MB |
| this export | 1 | 389 MB |
| design asset byte-identical to env-gen design_inputs/netflix/assets | 1700 | 212 MB |
| calibration mutants; calibrate.py re-plants them | 9 | 194 MB |
| copy of the snapshot the dev evaluator ran | 6 | 150 MB |
| the run's final workspace, identical to snapshots/iter5/workspace | 2 | 113 MB |
| build output (vite build) | 5 | 107 MB |
| staged copies used to serve snapshots on localhost | 1 | 94 MB |
| Claude config overlay (settings, caches, account backups); only the transcripts are kept | 36 | 8 MB |
| process id | 2 | 0 MB |
| lock file | 1 | 0 MB |

Account email, names and ids are replaced with placeholders such as `<emailAddress>` in every kept text file, and the local user name in paths with `user` (`/home/user/...`).
