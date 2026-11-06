#!/usr/bin/env python3
"""The DEV evaluator (its report is shown to the agent): env-gen's api_smoke on one snapshot.

usage (under `sg docker`, thb-validator venv):  dev_validator.py <src_dir> <out_dir>

Same checks as ../2_thb_netflix_selfval/scripts/validator.py, whose staging, compose policy and metrics are imported
unmodified. The difference is the agent-facing text. It carries env-gen's own check verdicts and details and the
business-chain steps, and it does NOT show the "endpoints answering 2xx" count: in 2_ that count rewarded 2xx on
the probe's empty bodies, and the agent changed two endpoints' semantics to raise it. The metric is still written
to report.json for analysis.
"""
import json, os, sys, time

EXP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
X = json.load(open(os.path.join(EXP, "config.json")))
sys.path.insert(0, os.path.join(os.path.dirname(EXP), X["selfval_experiment"], "scripts"))
import validator as V  # noqa: E402  (2_'s module: stage, compose_policy, metrics; also puts env-gen on sys.path)

os.environ["COMPOSE_PROJECT_NAME"] = "thbval21"
DETAIL_CAP = 1500


def text_report(rep):
    m = rep["_wrapper"]["metrics"]
    L = [f"env-gen api_smoke: {'PASSED' if rep.get('passed') else 'FAILED'} - {m['checks_passed']}/{m['checks_total']} "
         f"checks passed. Business-chain steps ok: {m['chain_steps_ok']}/{m['chain_steps_total']}.",
         f"Summary: {rep.get('summary', '')}", "", "Checks:"]
    for c in rep.get("checks", []):
        d = str(c.get("detail") or "").strip()
        L.append(f"- [{c.get('status')}] {c.get('name')}" + (f": {d[:DETAIL_CAP]}" if d else ""))
    for ch in rep.get("chains") or []:
        L += ["", f"Business chain {ch.get('name')}:"]
        for s in ch.get("steps") or []:
            note = str(s.get("note") or "")[:400]
            L.append(f"- [{'ok' if s.get('ok') else s.get('kind') or 'fail'}] {s.get('method')} {s.get('path')} -> "
                     f"{s.get('status')} (expect {s.get('expect')})" + (f": {note}" if note and not s.get("ok") else ""))
    changed = rep["_wrapper"]["framework_modified_files"]
    if changed:
        L += ["", "Files env-gen repaired in the evaluated copy before building (your workspace is unchanged):"]
        L += [f"- {p}" for p in changed[:50]]
    return "\n".join(L) + "\n"


def main(src, out):
    os.makedirs(out, exist_ok=True)
    project = os.path.join(out, "project")
    t0 = time.time()
    V.stage(src, project)
    before = V.tree_hashes(project)
    try:
        from env_generator.llm_generator.multi_agent.runtime.lifecycle import business_endpoints
        from env_generator.llm_generator.multi_agent.runtime.validation_runner import run_smoke_validation
        bad = (V.compose_policy(project) if os.path.isfile(os.path.join(project, "docker", "docker-compose.yml"))
               else ["/workspace/docker/docker-compose.yml not found: the app must be started by it"])
        if bad:
            rep = {"passed": False, "summary": "not run: the compose file is missing or breaks the policy",
                   "checks": [{"name": "compose_policy", "status": "fail", "detail": "; ".join(bad)}]}
        else:
            rep = run_smoke_validation(project, business_endpoints(V.CONTRACT["endpoints"]), teardown=True)
    except Exception as e:
        rep = {"passed": False, "summary": f"validator error: {type(e).__name__}: {e}",
               "checks": [{"name": "validator_error", "status": "fail", "detail": repr(e)[:DETAIL_CAP]}]}
    after = V.tree_hashes(project)
    changed = sorted(p for p in set(before) | set(after)
                     if before.get(p) != after.get(p) and not p.startswith(("shared/", "logs/", "docker/.")))
    rep["_wrapper"] = {"framework_modified_files": changed, "wall_s": round(time.time() - t0, 1), "metrics": V.metrics(rep)}
    json.dump(rep, open(os.path.join(out, "report.json"), "w"), indent=1, default=str)
    open(os.path.join(out, "report.txt"), "w").write(text_report(rep))
    print(open(os.path.join(out, "report.txt")).read())


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
