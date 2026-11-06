"""One live long-prompt Codex/bwrap/vLLM integration probe."""
import json
import os
import subprocess
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "common"))
import codex_worker as worker

RD = os.path.join(ROOT, "smoke", "live_qwen_long_probe")
TARGET = 195_000
MARKER = "AMBER-7319-MAPLE"


def tokenize_count(prompt):
    req = urllib.request.Request(
        "http://127.0.0.1:8000/tokenize",
        data=json.dumps({"model": "local", "prompt": prompt}).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=60) as response:
        return json.load(response)["count"]


def make_prompt(n):
    lines = [
        "This is a long-context retrieval test. Read the whole input. "
        "At the end, reply with the secret code printed near the middle. Do not call tools.\n"
    ]
    for i in range(n):
        lines.append(
            f"Record {i:06d}: the archive includes copper lanterns, silver bridges, "
            f"blue orchards, and a reference number {i * 7919 % 1000003:06d}.\n"
        )
        if i == n // 2:
            lines.append(f"SECRET CODE: {MARKER}\n")
    lines.append("What is the exact SECRET CODE? Reply with the code only.\n")
    return "".join(lines)


worker.prepare_home(RD)
sample = make_prompt(1000)
sample_tokens = tokenize_count(sample)
n = round(1000 * TARGET / sample_tokens)
prompt = make_prompt(n)
count = tokenize_count(prompt)
if count > 210_000:
    n = round(n * 205_000 / count)
    prompt = make_prompt(n)
    count = tokenize_count(prompt)
if not 180_000 <= count <= 210_000:
    raise RuntimeError(f"unexpected prompt size: {count}")

prompt_path = os.path.join(RD, "cli", "long_prompt.txt")
events_path = os.path.join(RD, "cli", "long.jsonl")
stderr_path = os.path.join(RD, "cli", "long.stderr")
with open(prompt_path, "w") as f:
    f.write(prompt)
print(f"prompt_tokens={count} prompt_bytes={len(prompt.encode())}", flush=True)

args = worker.argv(RD, ["exec"] + worker.flags() + ["-"])
start = time.monotonic()
with open(prompt_path) as source, open(events_path, "w") as events, open(stderr_path, "w") as errors:
    completed = subprocess.run(args, stdin=source, stdout=events, stderr=errors, timeout=600)
result = worker.parse_stream(events_path)
result.update(_rc=completed.returncode, _wall_s=round(time.monotonic() - start, 1),
              _prompt_tokens=count, _prompt_bytes=len(prompt.encode()))
with open(os.path.join(RD, "cli", "long.json"), "w") as f:
    json.dump(result, f, indent=2)
print(json.dumps({k: result.get(k) for k in (
    "session_id", "is_error", "result", "_rc", "_wall_s", "_prompt_tokens", "usage")},
    ensure_ascii=False), flush=True)
