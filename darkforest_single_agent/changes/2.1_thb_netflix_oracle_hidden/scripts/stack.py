#!/usr/bin/env python3
"""Boot or stop one snapshot's compose stack on 127.0.0.1 only, with every published host port shifted by an offset.

  stack.py view <iter> [run] [--exp selfval]   start an iteration for a person (ports +view_port_base+100*iter)
  stack.py view <iter> [run] --down            stop it

The hidden evaluator calls up() / down() directly. Run under `sg docker` with the thb-validator venv. Staging and
the compose policy are 2_'s (validator.stage / compose_policy), so a stack boots exactly what was validated.
"""
import json, os, subprocess, sys, time, urllib.request

EXP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
X = json.load(open(os.path.join(EXP, "config.json")))
sys.path.insert(0, os.path.join(os.path.dirname(EXP), X["selfval_experiment"], "scripts"))
import validator as V  # noqa: E402

FILES = ["-f", "docker-compose.yml", "-f", "stack-override.yml"]


def _wait(url, timeout):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            if urllib.request.urlopen(url, timeout=5).status < 500:
                return True
        except Exception:
            pass
        time.sleep(3)
    return False


def up(src, stage_dir, project, offset, timeout=600):
    """Stage src, refuse a compose file that reaches the host, start it. Returns {service: url} or raises."""
    V.stage(src, os.path.join(stage_dir, "project"))
    proj_dir = os.path.join(stage_dir, "project")
    bad = V.compose_policy(proj_dir)
    if bad:
        raise RuntimeError("compose policy: " + "; ".join(bad))
    dock = os.path.join(proj_dir, "docker")
    cfg = json.loads(subprocess.run(["docker", "compose", "config", "--format", "json"], cwd=dock,
                                    capture_output=True, text=True, check=True).stdout)
    lines, urls = ["services:"], {}
    for name, s in (cfg.get("services") or {}).items():
        ports = [p for p in s.get("ports") or [] if p.get("published")]
        if ports:
            lines += [f"  {name}:", "    ports: !override"]
            for p in ports:
                host = int(p["published"]) + offset
                if host > 65535:
                    raise RuntimeError(f"published port {p['published']} + offset {offset} > 65535")
                lines.append(f'      - "127.0.0.1:{host}:{p["target"]}"')
                urls.setdefault(name, f"http://127.0.0.1:{host}")
    open(os.path.join(dock, "stack-override.yml"), "w").write("\n".join(lines) + "\n")
    subprocess.run(["docker", "compose", "-p", project, *FILES, "down", "-v"], cwd=dock, capture_output=True)
    r = subprocess.run(["docker", "compose", "-p", project, *FILES, "up", "-d", "--build"], cwd=dock,
                       capture_output=True, text=True, timeout=timeout)
    if r.returncode:
        raise RuntimeError("compose up failed: " + (r.stderr or r.stdout)[-1500:])
    if "backend" in urls and not _wait(urls["backend"] + "/health", 300):
        raise RuntimeError("backend /health never answered")
    if "frontend" in urls and not _wait(urls["frontend"] + "/", 120):
        raise RuntimeError("frontend / never answered")
    return urls


def down(stage_dir, project):
    dock = os.path.join(stage_dir, "project", "docker")
    if os.path.isdir(dock):
        subprocess.run(["docker", "compose", "-p", project, *FILES, "down", "-v"], cwd=dock, capture_output=True)


def snapshot_dir(exp, run, k):
    if exp == "selfval":
        return os.path.join(os.path.dirname(EXP), X["selfval_experiment"], "runs", f"netflix__r{run}", "snapshots",
                            f"iter{k}", "workspace")
    return os.path.join(EXP, "runs", f"netflix__r{run}", "snapshots", f"iter{k}", "workspace")


def main(argv):
    args = [a for a in argv if not a.startswith("--")]
    exp = argv[argv.index("--exp") + 1] if "--exp" in argv else "hidden"
    args = [a for a in args if a != exp]
    if args[:1] != ["view"]:
        print(__doc__)
        return 1
    k, run = int(args[1]), int(args[2]) if len(args) > 2 else 0
    stage_dir = os.path.join(EXP, "views", f"{exp}-r{run}-it{k}")
    project = f"thbview21-{exp}-r{run}-it{k}"
    if "--down" in argv:
        down(stage_dir, project)
        return 0
    urls = up(snapshot_dir(exp, run, k), stage_dir, project, X["view_port_base"] + 100 * k + (50 if exp == "selfval" else 0))
    print(f"{exp} run {run} iteration {k} is up:\n  " + "\n  ".join(f"{n}: {u}" for n, u in urls.items()))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
