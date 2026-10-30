#!/usr/bin/env python3
"""Validate one snapshot of the agent's Netflix app with env-gen's own deterministic api_smoke.

usage (under `sg docker`, with the thb-validator venv):  validator.py <src_dir> <out_dir>

What it runs: `run_smoke_validation` from the frozen benchmarks/env-gen, unmodified. That is env-gen's api_smoke:
a clean `docker compose down -v && up --build`, backend /health, register/login and password checks, every
contract endpoint reachable and implemented and returning the right shape, 401 without a token, writes persist,
the business_chain (env-gen's own contract-projected default CRUD chain, synthesize_default_chain), and the
frontend checks (reachable, navigable, fallback pages, dead controls).

What it does not run: anything that calls an LLM (visual-fidelity judge, test-user agents), the delivery gate and
deliverability audits (they read the env-gen pipeline's internal hubs, which a single agent does not produce), and
MCP probes.

The contract is changes/2_thb_netflix_selfval/contract/netflix.json (frozen from DESCRIPTION.txt); it is written into
the copy as env-gen's registry file, so the agent cannot change it. The snapshot is validated in a copy under
<out_dir>/project. api_smoke heals some files before building (env-gen framework repairs); every file it changed is
listed in the report, so a pass that depended on a repair is visible.

Writes <out_dir>/report.json and <out_dir>/report.txt (the text the agent sees). LLM SDKs are importable but no API
key is set, and nothing here calls them.
"""
import hashlib, json, os, shutil, sys, time

THB = "/home/user/project/shabi_forest/benchmarks/env-gen"
EXP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONTRACT = json.load(open(os.path.join(EXP, "contract", "netflix.json")))
SKIP = {"node_modules", ".git", "__pycache__", ".pytest_cache", ".mypy_cache", ".venv", "venv", ".cache", "dist"}
DETAIL_CAP = 1500

sys.path[:0] = [f"{THB}/agent", f"{THB}/agent/env_generator/llm_generator"]
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
os.environ["COMPOSE_PROJECT_NAME"] = "thbval"  # serialized by the caller's lock; never shares a name with other work


def compose_policy(project):
    """The agent writes the compose file and docker runs it as root, outside the sandbox. Refuse anything that
    reaches the host: bind mounts or build contexts outside the project, host namespaces, privileges, devices."""
    import subprocess
    r = subprocess.run(["docker", "compose", "-f", "docker-compose.yml", "config", "--format", "json"],
                       cwd=os.path.join(project, "docker"), capture_output=True, text=True, timeout=120)
    if r.returncode:
        return [f"`docker compose config` failed: {r.stderr.strip()[:800]}"]
    cfg, root, bad = json.loads(r.stdout), os.path.realpath(project), []

    def inside(p):
        p = os.path.realpath(p)
        return p == root or p.startswith(root + os.sep)
    for name, s in (cfg.get("services") or {}).items():
        for key in ("privileged", "cap_add", "devices", "security_opt", "pid", "ipc", "userns_mode", "cgroup_parent"):
            if s.get(key):
                bad.append(f"service {name}: `{key}` is not allowed")
        if str(s.get("network_mode") or "").startswith(("host", "container:", "service:")):
            bad.append(f"service {name}: network_mode `{s['network_mode']}` is not allowed")
        for v in s.get("volumes") or []:
            if v.get("type") == "bind" and not inside(v.get("source", "")):
                bad.append(f"service {name}: bind mount of {v.get('source')} (outside the project) is not allowed")
        b = s.get("build") or {}
        for ctx in [b.get("context")] + list((b.get("additional_contexts") or {}).values()):
            if ctx and "://" not in ctx and not inside(ctx):
                bad.append(f"service {name}: build context {ctx} is outside the project")
        for f in s.get("env_file") or []:
            path = f.get("path") if isinstance(f, dict) else f
            if path and not inside(path):
                bad.append(f"service {name}: env_file {path} is outside the project")
    for kind in ("secrets", "configs"):
        for name, s in (cfg.get(kind) or {}).items():
            if s.get("file") and not inside(s["file"]):
                bad.append(f"{kind[:-1]} {name}: file {s['file']} is outside the project")
    return bad


def tree_hashes(root):
    out = {}
    for d, dirs, files in os.walk(root):
        dirs[:] = [x for x in dirs if x not in SKIP]
        for f in files:
            p = os.path.join(d, f)
            if os.path.isfile(p) and not os.path.islink(p):
                out[os.path.relpath(p, root)] = hashlib.sha256(open(p, "rb").read()).hexdigest()
    return out


def stage(src, project):
    if os.path.exists(project):
        shutil.rmtree(project)
    shutil.copytree(src, project, symlinks=True,
                    ignore=lambda d, names: {n for n in names if n in SKIP
                                             or os.path.isfile(os.path.join(d, n, "pyvenv.cfg"))})
    design = os.path.join(project, "design")  # the task materials, as the agent sees them at /workspace/design
    if os.path.isdir(design) and not os.listdir(design):
        os.rmdir(design)
    if not os.path.exists(design):
        shutil.copytree(f"{THB}/design_inputs/netflix", design, copy_function=shutil.copyfile)
        for d, dirs, files in os.walk(design):  # the frozen source is read-only; its copy must not be
            for n in dirs + files:
                os.chmod(os.path.join(d, n), 0o755 if n in dirs else 0o644)
        os.chmod(design, 0o755)
    hubs = os.path.join(project, "shared", "hubs")
    os.makedirs(hubs, exist_ok=True)
    json.dump(CONTRACT["endpoints"], open(os.path.join(hubs, "registryhub_endpoints.json"), "w"), indent=1)


def metrics(rep):
    """Stricter counts than api_smoke's own verdicts, which stay soft on purpose: a 404 on a path with an id is
    not a failure, and a chain step that hits a missing route is left to business_endpoints_implemented."""
    checks, eps = rep.get("checks", []), rep.get("endpoints") or []
    steps = [s for ch in rep.get("chains") or [] for s in ch.get("steps") or []]
    return {"checks_passed": sum(c.get("status") == "pass" for c in checks), "checks_total": len(checks),
            "endpoints_2xx": sum(200 <= (e.get("status_code") or 0) < 300 for e in eps), "endpoints_total": len(eps),
            "chain_steps_ok": sum(bool(s.get("ok")) for s in steps), "chain_steps_total": len(steps)}


def text_report(rep, changed, wall):
    m = rep["_wrapper"]["metrics"]
    L = [f"env-gen api_smoke: {'PASSED' if rep.get('passed') else 'FAILED'} - {m['checks_passed']}/{m['checks_total']} "
         f"checks passed ({wall:.0f}s).",
         f"Contract endpoints answering 2xx with a token: {m['endpoints_2xx']}/{m['endpoints_total']}. "
         f"Business-chain steps ok: {m['chain_steps_ok']}/{m['chain_steps_total']}.",
         f"Summary: {rep.get('summary', '')}", "", "Checks:"]
    for c in rep.get("checks", []):
        d = str(c.get("detail") or "").strip()
        if len(d) > DETAIL_CAP:
            d = d[:DETAIL_CAP] + " ...[truncated]"
        L.append(f"- [{c.get('status')}] {c.get('name')}" + (f": {d}" if d else ""))
    bad = [e for e in rep.get("endpoints") or [] if not 200 <= (e.get("status_code") or 0) < 300]
    if bad:
        L += ["", "Endpoints not answering 2xx:"] + [f"- {e.get('trace') or e.get('path')}"
                                                     + (f" ({e['error']})" if e.get("error") else "") for e in bad]
    for ch in rep.get("chains") or []:
        L += ["", f"Chain {ch.get('name')}:"]
        for s in ch.get("steps") or []:
            note = str(s.get("note") or "")[:400]
            L.append(f"- [{'ok' if s.get('ok') else s.get('kind') or 'fail'}] {s.get('method')} {s.get('path')} -> "
                     f"{s.get('status')} (expect {s.get('expect')})" + (f": {note}" if note and not s.get("ok") else ""))
    if changed:
        L += ["", "Files the env-gen framework repaired in the validated copy before building (your workspace is "
                  "unchanged; a check that passed may depend on these):"] + [f"- {p}" for p in changed[:50]]
    return "\n".join(L) + "\n"


def main(src, out):
    os.makedirs(out, exist_ok=True)
    project = os.path.join(out, "project")
    t0 = time.time()
    stage(src, project)
    before = tree_hashes(project)
    try:
        from env_generator.llm_generator.multi_agent.runtime.lifecycle import business_endpoints
        from env_generator.llm_generator.multi_agent.runtime.validation_runner import run_smoke_validation
        eps = business_endpoints(CONTRACT["endpoints"])
        bad = (compose_policy(project) if os.path.isfile(os.path.join(project, "docker", "docker-compose.yml"))
               else ["/workspace/docker/docker-compose.yml not found: the app must be started by it"])
        if bad:
            rep = {"passed": False, "summary": "not run: the compose file is missing or breaks the policy",
                   "checks": [{"name": "compose_policy", "status": "fail", "detail": "; ".join(bad)}]}
        else:
            rep = run_smoke_validation(project, eps, teardown=True)
    except Exception as e:  # a validator crash is reported, never shown as an app failure without saying so
        rep = {"passed": False, "summary": f"validator error: {type(e).__name__}: {e}",
               "checks": [{"name": "validator_error", "status": "fail", "detail": repr(e)[:DETAIL_CAP]}]}
    after = tree_hashes(project)
    changed = sorted(p for p in set(before) | set(after)  # minus the validator's own bookkeeping files
                     if before.get(p) != after.get(p) and not p.startswith(("shared/", "logs/", "docker/.")))
    wall = time.time() - t0
    rep["_wrapper"] = {"framework_modified_files": changed, "wall_s": round(wall, 1), "metrics": metrics(rep)}
    json.dump(rep, open(os.path.join(out, "report.json"), "w"), indent=1, default=str)
    open(os.path.join(out, "report.txt"), "w").write(text_report(rep, changed, wall))
    print(open(os.path.join(out, "report.txt")).read())


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
