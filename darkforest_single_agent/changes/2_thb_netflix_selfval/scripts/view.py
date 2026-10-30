#!/usr/bin/env python3
"""Boot one iteration's submitted app so a person can use it in a browser.

usage (from the experiment dir):
  sg docker -c "../../.envs/venvs/thb-validator/bin/python -I -B scripts/view.py <iter> [run]"         # start
  sg docker -c "../../.envs/venvs/thb-validator/bin/python -I -B scripts/view.py <iter> [run] --down"  # stop

The snapshot is staged in views/r<run>-it<iter>/ (same staging and compose policy as the validator) and started as
compose project thbview-r<run>-it<iter>, with every published host port shifted by 10000 + 100*iter, so several
iterations can run side by side and never collide with a validation in progress. Open the printed URLs locally
(VS Code forwards the ports). Keep it on this machine: do not expose these pages publicly.
"""
import json, os, subprocess, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import validator  # noqa: E402  (stage, compose_policy)

EXP = validator.EXP


def main(argv):
    down = "--down" in argv
    args = [a for a in argv if a != "--down"]
    k, run = int(args[0]), int(args[1]) if len(args) > 1 else 0
    proj, view = f"thbview-r{run}-it{k}", os.path.join(EXP, "views", f"r{run}-it{k}")
    dock = os.path.join(view, "project", "docker")
    files = ["-f", "docker-compose.yml", "-f", "view-override.yml"]
    if down:
        subprocess.run(["docker", "compose", "-p", proj, *files, "down", "-v"], cwd=dock)
        return 0
    validator.stage(os.path.join(EXP, "runs", f"netflix__r{run}", "snapshots", f"iter{k}", "workspace"),
                    os.path.join(view, "project"))
    bad = validator.compose_policy(os.path.join(view, "project"))
    if bad:
        print("refused:", "; ".join(bad))
        return 1
    cfg = json.loads(subprocess.run(["docker", "compose", "config", "--format", "json"], cwd=dock,
                                    capture_output=True, text=True, check=True).stdout)
    off, lines, urls = 10000 + 100 * k, ["services:"], []
    for name, s in (cfg.get("services") or {}).items():
        ports = [p for p in s.get("ports") or [] if p.get("published")]
        if ports:
            lines += [f"  {name}:", "    ports: !override"]
            for p in ports:
                host = int(p["published"]) + off
                lines.append(f'      - "127.0.0.1:{host}:{p["target"]}"')  # this machine only; reach it by port forwarding
                urls.append(f"{name}: http://localhost:{host}")
    open(os.path.join(dock, "view-override.yml"), "w").write("\n".join(lines) + "\n")
    subprocess.run(["docker", "compose", "-p", proj, *files, "up", "-d", "--build"], cwd=dock, check=True)
    print(f"iteration {k} of run {run} is up ({proj}):\n  " + "\n  ".join(urls))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
