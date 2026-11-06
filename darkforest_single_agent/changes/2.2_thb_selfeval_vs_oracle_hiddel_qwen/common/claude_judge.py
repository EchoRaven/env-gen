"""bwrap sandbox for the hidden visual judge (`claude -p`) in 2.2.

Experiment 2.1's judge ran in the baseline sandbox (../0_baxbench_nl2_tests/scripts/sandbox.py), which binds the
user's real ~/.claude, credentials included. In 2.2 the proctor runs on acct2's account inside a filesystem sandbox
where ~/.claude is read-only and must not be used. So the judge gets an empty per-judgment HOME and authenticates
with the acct2 OAuth token through CLAUDE_CODE_OAUTH_TOKEN. Same CLI binary, model, prompt, tools (Read only), and
workspace (only the two images) as 2.1; only the account and home differ.
"""
import os

SF = "/home/user/project/shabi_forest"
ENVS = f"{SF}/.envs"
CLAUDE_BIN = "/home/user/.local/share/claude/versions/2.1.304"
TOKEN_FILE = f"{ENVS}/secrets/claude_oauth_token_acct2"


def command(jrd, claude_args):
    """argv for `env -i ... bwrap ... claude <claude_args>`, workspace <jrd>/workspace, home <jrd>/home."""
    home, ws = os.path.join(jrd, "home"), os.path.join(jrd, "workspace")
    os.makedirs(os.path.join(home, ".claude"), exist_ok=True)
    os.makedirs(ws, exist_ok=True)
    token = open(TOKEN_FILE).read().strip()
    env = {"HOME": "/home/agent", "USER": "agent", "LOGNAME": "agent", "PATH": "/usr/local/bin:/usr/bin:/bin",
           "SHELL": "/bin/bash", "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", "TERM": "dumb", "TMPDIR": "/tmp",
           "CLAUDE_CONFIG_DIR": "/home/agent/.claude", "CLAUDE_CODE_OAUTH_TOKEN": token, "DISABLE_AUTOUPDATER": "1",
           "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1", "CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1"}
    return ["env", "-i"] + [f"{k}={v}" for k, v in env.items()] + [
        "bwrap", "--die-with-parent", "--new-session", "--unshare-pid", "--unshare-ipc", "--unshare-uts",
        "--hostname", "sandbox",
        "--ro-bind", "/usr", "/usr", "--symlink", "usr/bin", "/bin", "--symlink", "usr/lib", "/lib",
        "--symlink", "usr/lib64", "/lib64", "--symlink", "usr/sbin", "/sbin",
        "--ro-bind", "/etc", "/etc", "--ro-bind", "/run/systemd/resolve", "/run/systemd/resolve",
        "--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp", "--tmpfs", "/var/tmp",
        "--ro-bind", CLAUDE_BIN, "/opt/claude/claude",
        "--bind", home, "/home/agent", "--bind", ws, "/workspace", "--chdir", "/workspace",
        "/opt/claude/claude"] + list(claude_args)
