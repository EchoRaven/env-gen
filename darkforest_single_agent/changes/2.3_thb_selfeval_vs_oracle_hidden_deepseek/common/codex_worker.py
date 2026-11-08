"""The 2.3 worker: Codex CLI 0.163.0 driving deepseek-v4.1-flash through the experiment's LLM gateway, inside a bwrap
sandbox. Experiment 2.3 is 2.2 with the model replaced (Qwen3.8-27B on local vLLM -> DeepSeek through
../scripts/llm_gateway.py on 127.0.0.1:39823, which holds the API key); everything else in this file is 2.2's.

This replaces the Claude Code worker of experiments 2 and 2.1 and nothing else. The sandbox mirrors the baseline's
(../0_baxbench_nl2_tests/scripts/sandbox.py): empty root with an allow-list of read-only system mounts, a private /tmp,
the job's own home at /home/agent, the workspace at /workspace as the only writable project path, and the host
network (npm, PyPI, and the model gateway on 127.0.0.1:39823). Differences, all because the agent is no longer Claude:
- no ~/.claude mount at all (the worker sees none of the user's Claude files, credentials included);
- Codex is mounted read-only at /opt/codex; its home is <rd>/home/.codex (config, model catalog, sessions).
The job adds its own mounts (Node, design materials, validate tool ...) through `extra`.

Codex config (same reasoning as ../0.2.2_math_group_evo_deepseek/compose/scripts/sandbox.py): Codex does not know the
model, so without a catalog entry it caps the window at 272,000 and compacts at ~20% of the configured window. As in
2.2, the window is the model's native maximum: the catalog entry declares 1,048,576 (DeepSeek's; 2.2 declared Qwen's
262,144), of which Codex uses 95%, and auto-compaction is set to 967,000 tokens (as in 0.2.2) so a compaction request
(history + summary output) still fits the model's context.
"""
import glob, json, os, signal, subprocess, time, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
C = json.load(open(os.path.join(HERE, "codex.json")))
SF = "/home/user/project/shabi_forest"
ENVS = f"{SF}/.envs"
SANDBOX_BIN = f"{ENVS}/sandbox-bin"

OFF_FEATURES = ["memories", "goals", "apps", "plugins", "remote_plugin", "plugin_sharing", "recommended_plugins",
                "tool_suggest", "skill_mcp_dependency_install", "skill_search", "workspace_dependencies", "browser_use",
                "browser_use_external", "in_app_browser", "computer_use", "image_generation", "realtime_conversation",
                "guardian_approval", "daemon_auto_start", "api_key_model_discovery", "api_key_cyber_access_programs"]
RULES = 'prefix_rule(pattern = ["rm"], decision = "allow")\nprefix_rule(pattern = ["git"], decision = "allow")\n'


def config_toml():
    L = [f'model = "{C["model"]}"', 'model_provider = "deepseek"', f'model_reasoning_effort = "{C["effort"]}"',
         f'model_context_window = {C["context_window"]}', f'model_auto_compact_token_limit = {C["auto_compact_tokens"]}',
         'model_catalog_json = "/home/agent/.codex/model_catalog.json"',
         'web_search = "disabled"', 'check_for_update_on_startup = false', "background_terminal_max_timeout = 7200000",
         "", "[analytics]", "enabled = false", "", "[agents]", "enabled = false", "", "[features]"]
    L += [f"{x} = false" for x in OFF_FEATURES]
    L += ["", "[skills]", "include_instructions = false", "", "[skills.bundled]", "enabled = false", "",
          "[model_providers.deepseek]", 'name = "deepseek"', f'base_url = "{C["base_url"]}"',
          'env_key = "OPENAI_API_KEY"', 'wire_api = "responses"', "stream_idle_timeout_ms = 3600000",
          "stream_max_retries = 20", "request_max_retries = 20", ""]
    return "\n".join(L)


def catalog_json():
    m = json.load(open(os.path.join(HERE, "model_catalog_base.json")))
    m.update(slug=C["model"], display_name=C["model"], context_window=C["context_window"],
             max_context_window=C["context_window"], default_reasoning_level=C["effort"],
             supported_reasoning_levels=[{"effort": e, "description": e} for e in ("low", "medium", "high")],
             input_modalities=["text"])
    return json.dumps({"models": [m]})


def prepare_home(rd):
    cd = os.path.join(rd, "home", ".codex")
    for d in ("sessions", "rules"):
        os.makedirs(os.path.join(cd, d), exist_ok=True)
    open(os.path.join(cd, "config.toml"), "w").write(config_toml())
    open(os.path.join(cd, "rules", "default.rules"), "w").write(RULES)
    open(os.path.join(cd, "model_catalog.json"), "w").write(catalog_json())
    os.makedirs(os.path.join(rd, "workspace"), exist_ok=True)
    os.makedirs(os.path.join(rd, "cli"), exist_ok=True)


def argv(rd, codex_args, extra=(), path_prefix=(), env_extra=None):
    """`env -i ... bwrap ... codex <codex_args>`; extra: further bwrap mount args (inserted before --chdir)."""
    prepare_home(rd)
    path = ":".join(list(path_prefix) + ["/opt/codex/codex-path", SANDBOX_BIN, "/usr/local/bin", "/usr/bin", "/bin"])
    env = {"HOME": "/home/agent", "USER": "agent", "LOGNAME": "agent", "PATH": path, "SHELL": "/bin/bash",
           "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", "TERM": "dumb", "TMPDIR": "/tmp",
           "XDG_CACHE_HOME": "/home/agent/.cache", "PIP_CACHE_DIR": "/home/agent/.cache/pip",
           "NPM_CONFIG_CACHE": "/home/agent/.npm", "NPM_CONFIG_UPDATE_NOTIFIER": "false",
           "CODEX_HOME": "/home/agent/.codex", "OPENAI_API_KEY": "dummy", "NO_PROXY": "127.0.0.1,localhost",
           "no_proxy": "127.0.0.1,localhost"}
    env.update(env_extra or {})
    a = ["env", "-i"] + [f"{k}={v}" for k, v in env.items()] + [
        "bwrap", "--die-with-parent", "--new-session", "--unshare-pid", "--unshare-ipc", "--unshare-uts",
        "--hostname", "sandbox",
        "--ro-bind", "/usr", "/usr", "--symlink", "usr/bin", "/bin", "--symlink", "usr/lib", "/lib",
        "--symlink", "usr/lib64", "/lib64", "--symlink", "usr/sbin", "/sbin",
        "--ro-bind", "/etc", "/etc", "--ro-bind", "/run/systemd/resolve", "/run/systemd/resolve",
        "--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp", "--tmpfs", "/var/tmp",
        "--ro-bind", C["codex_dir"], "/opt/codex",
        "--ro-bind", f"{ENVS}/python", f"{ENVS}/python", "--ro-bind", f"{ENVS}/bin", f"{ENVS}/bin",
        "--ro-bind", SANDBOX_BIN, SANDBOX_BIN,
        "--bind", os.path.join(rd, "home"), "/home/agent",
        "--bind", os.path.join(rd, "workspace"), "/workspace"]
    return a + list(extra) + ["--chdir", "/workspace", "/opt/codex/bin/codex"] + list(codex_args)


def session_file(rd, sid):
    if not sid:
        return None
    g = glob.glob(os.path.join(rd, "home", ".codex", "sessions", "*", "*", "*", f"rollout-*-{sid}.jsonl"))
    return g[0] if g else None


def first_thread_id(path):
    try:
        with open(path, errors="replace") as f:
            for _, line in zip(range(50), f):
                if '"thread.started"' in line:
                    return json.loads(line).get("thread_id")
    except (OSError, ValueError):
        pass
    return None


def parse_stream(path):
    """From ../0.2.2_math_group_evo_deepseek/compose/scripts/sessions.py: a run succeeded iff its last turn completed."""
    with open(path, "rb") as f:
        f.seek(0, 2)
        n = f.tell()
        f.seek(max(0, n - 8_000_000))
        raw = f.read().decode(errors="replace")
    res = {"session_id": first_thread_id(path)}
    done, msg, err, items, usage, cmds = False, None, None, 0, None, 0
    for line in raw.splitlines():
        if not line.startswith("{"):
            continue
        try:
            j = json.loads(line)
        except ValueError:
            continue
        ty = j.get("type") if isinstance(j, dict) else None
        if ty == "turn.started":
            done = False
        elif ty == "turn.completed":
            done, usage = True, j.get("usage")
        elif ty == "turn.failed":
            done, err = False, str((j.get("error") or {}).get("message"))
        elif ty == "error":
            err = str(j.get("message"))
        elif ty == "item.completed":
            it = j.get("item") or {}
            items += 1
            cmds += it.get("type") == "command_execution"
            if it.get("type") == "agent_message" and it.get("text"):
                msg = it["text"]
    res.update(num_turns=items, commands=cmds, usage=usage, is_error=not done)
    res["result"] = msg if done else (err or "the run ended without completing its turn")
    return res


def gateway_ok():
    """2.3: the model gateway (../scripts/llm_gateway.py) answers /health; it replaces 2.2's vLLM health check."""
    try:
        return urllib.request.urlopen(C["health_url"], timeout=10).status == 200
    except Exception:
        return False


def wait_gateway(log):
    t0 = time.time()
    while not gateway_ok():
        if time.time() - t0 < 30:
            log("model gateway not healthy; waiting (systemd restarts it; ../scripts/gateway.sh starts it)")
        time.sleep(30)


def flags():
    return ["--json", "--skip-git-repo-check", "--dangerously-bypass-approvals-and-sandbox",
            "--dangerously-bypass-hook-trust", "-c", f'model_reasoning_effort="{C["effort"]}"']


def run(rd, codex_args, timeout, tag, log, **kw):
    """Run one `codex exec` in the sandbox; silence watchdog; returns parse_stream's result plus _rc/_timed_out/...
    The raw event stream is deleted after parsing (the session transcript in <rd>/home/.codex/sessions has it all)."""
    a = argv(rd, codex_args, **kw)
    out_p, err_p = os.path.join(rd, "cli", f"{tag}.jsonl"), os.path.join(rd, "cli", f"{tag}.stderr")
    t0 = time.time()
    timed_out = silent = False
    last_size, last_change = 0, time.time()
    with open(out_p, "w") as fo, open(err_p, "w") as fe:
        p = subprocess.Popen(a, stdin=subprocess.DEVNULL, stdout=fo, stderr=fe, start_new_session=True)
        while True:
            try:
                rc = p.wait(timeout=10)
                break
            except subprocess.TimeoutExpired:
                pass
            size = os.path.getsize(out_p)
            if size != last_size:
                last_size, last_change = size, time.time()
            silent = time.time() - last_change > C["silence_s"]
            timed_out = time.time() - t0 > timeout
            if silent or timed_out:
                log(f"{tag}: {'timeout' if timed_out else 'no output for %ds (watchdog)' % C['silence_s']}; stopping")
                os.killpg(p.pid, signal.SIGINT)
                try:
                    rc = p.wait(timeout=60)
                except subprocess.TimeoutExpired:
                    os.killpg(p.pid, signal.SIGKILL)
                    rc = p.wait()
                break
    res = parse_stream(out_p)
    if silent:
        res.update(is_error=True, result="watchdog: the session produced no output for too long")
    res.update(_rc=rc, _timed_out=timed_out, _silent=silent, _wall_s=round(time.time() - t0, 1),
               _stderr=open(err_p, errors="replace").read()[-3000:])
    json.dump(res, open(os.path.join(rd, "cli", f"{tag}.json"), "w"), indent=1)
    os.remove(out_p)
    return res


def drive(rd, st, save, prompt, first_prompt, timeout, tag, log, **kw):
    """Run one iteration's prompt in the job's Codex session (st['codex_sid']) until the agent ends its turn, the
    iteration's time runs out, or it keeps failing. A session that cannot be resumed (e.g. a context overflow) is
    replaced by a fresh one that gets the original task text plus this iteration's message. Returns (res, attempts)
    or (None, attempts) after max_attempts_per_iter failures. `save()` persists st."""
    prepare_home(rd)
    t0, failed_resumes, res = time.time(), 0, None
    note = None
    for attempt in range(C["max_attempts_per_iter"]):
        wait_gateway(log)
        left = timeout - (time.time() - t0)
        if left < 60:
            res = res or {"is_error": True, "result": "no time left"}
            res["_timed_out"] = True
            return res, attempt
        sid = st.get("codex_sid")
        if sid and session_file(rd, sid) and failed_resumes < C["fresh_session_after_failed_resumes"]:
            text = note or prompt
            args = ["exec", "resume", sid] + flags() + [text]
            mode = f"resume {sid}"
        else:
            if sid:
                log(f"{tag}: session {sid} failed {failed_resumes}x on resume; starting a fresh session")
                st.setdefault("abandoned_sids", []).append(sid)
            text = ("[Harness note: your previous working session could not be continued, so this is a fresh session. "
                    "All your earlier work is still in /workspace. Your original task statement follows, then the "
                    "message of the current iteration.]\n\n" + first_prompt + "\n\n---\n\n" + prompt) \
                if (sid or st.get("abandoned_sids")) and prompt != first_prompt else prompt
            args = ["exec"] + flags() + [text]
            mode = "new session"
            failed_resumes = 0
        open(os.path.join(rd, f"prompt_{tag}_a{attempt}.txt"), "w").write(text)
        log(f"{tag} attempt {attempt} ({mode})")
        res = run(rd, args, left, f"{tag}_a{attempt}", log, **kw)
        rsid = res.get("session_id")
        if mode == "new session" and rsid and session_file(rd, rsid):
            st["codex_sid"] = rsid
            st.setdefault("sids", []).append(rsid)
            save()
        if res.get("_timed_out"):
            return res, attempt + 1
        if not res.get("is_error") and res.get("_rc") == 0:
            return res, attempt + 1
        log(f"{tag} attempt {attempt} error (rc={res.get('_rc')}): {str(res.get('result'))[:300]!r} "
            f"stderr: {res.get('_stderr', '')[-300:]!r}")
        if mode.startswith("resume"):
            failed_resumes += 1
        note = ("Your previous turn was interrupted by an error in the harness or the model server. Continue the "
                "current iteration from where you are; when ready, submit by ending your turn with a short summary.")
        time.sleep(60)
    return None, C["max_attempts_per_iter"]


_DOCKER_DIRECT = None


def docker_argv(cmd):
    """argv to run shell `cmd` with docker access: plain bash when the docker socket is already usable (as inside the
    proctor's outer sandbox, where `sg` cannot call setgroups), else `sg docker -c` as in experiments 2 and 2.1."""
    global _DOCKER_DIRECT
    if _DOCKER_DIRECT is None:
        try:
            _DOCKER_DIRECT = subprocess.run(["docker", "version", "--format", "{{.Server.Version}}"], timeout=60,
                                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0
        except Exception:
            _DOCKER_DIRECT = False
    return ["bash", "-c", cmd] if _DOCKER_DIRECT else ["sg", "docker", "-c", cmd]


def make_writable(path):
    """u+w on every directory under path (2.2: Qwen copies the read-only design assets with their modes, so a
    staged copy of its workspace cannot be removed by validator.stage()'s rmtree on a re-stage)."""
    if os.path.isdir(path):
        for d, dirs, _ in os.walk(path):
            os.chmod(d, os.stat(d).st_mode | 0o700)
