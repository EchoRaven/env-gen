"""2.3 smoke: a real long Codex session through the gateway at the production settings (window 1,048,576, compaction at
967,000). Turns 1-4: four ~230k-token prompts (Codex accepts at most 1,048,576 characters per input), a code word in the
first (2.2's probe_codex_long.py, scaled to DeepSeek's window). Next turn (resume): the agent cats 14 workspace files of ~9k tokens each, which pushes the session past 967k, so
Codex must compact during the turn and continue. Last turn (resume): a question after the compaction.
usage: python3 -I smoke/probe_long_compact.py"""
import json, os, subprocess, sys, time, urllib.request
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "common"))
import codex_worker as W
RD = os.path.join(HERE, "long_compact")
MARKER = "AMBER-7319-MAPLE"
log = lambda m: print(m, flush=True)


def records(n, start=0):
    return "".join(f"Record {i:06d}: the archive includes copper lanterns, silver bridges, blue orchards, and a "
                   f"reference number {i * 7919 % 1000003:06d}.\n" for i in range(start, start + n))


def count(text):
    body = {"model": W.C["model"], "input": text, "max_output_tokens": 16, "reasoning": {"effort": "low"}}
    req = urllib.request.Request(W.C["base_url"] + "/responses", data=json.dumps(body).encode(),
                                 headers={"Authorization": "Bearer dummy", "Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(req, timeout=600))["usage"]["input_tokens"]


per = count(records(2000)) / 2000
CH = 230_000                      # tokens per filler turn: Codex accepts at most 1,048,576 characters per input
n = int(CH / per)
log(f"tokens/record {per:.2f}; {n} records (~{int(n * per)} tokens, {len(records(n))} chars) per filler turn")
W.prepare_home(RD)
os.makedirs(os.path.join(RD, "workspace"), exist_ok=True)
for b in range(1, 15):  # ~9k tokens each, under Codex's 10k-token tool output limit
    body = records(int(9000 / per), 10_000_000 + b * 100_000)
    if b == 14:
        body += "KEY: VIOLET-2208-CEDAR\n"
    open(os.path.join(RD, "workspace", f"blk_{b:02d}.txt"), "w").write(body)


def turn(tag, text, sid):
    """One `codex exec [resume sid] -` with the prompt on stdin (an argv string is limited to 128 KiB)."""
    pp = os.path.join(RD, "cli", f"{tag}_prompt.txt")
    open(pp, "w").write(text)
    ev = os.path.join(RD, "cli", f"{tag}.jsonl")
    t0 = time.time()
    with open(pp) as src, open(ev, "w") as out, open(os.path.join(RD, "cli", f"{tag}.stderr"), "w") as err:
        rc = subprocess.run(W.argv(RD, ["exec"] + (["resume", sid] if sid else []) + W.flags() + ["-"]), stdin=src,
                            stdout=out, stderr=err, timeout=1800).returncode
    r = W.parse_stream(ev)
    log(f"{tag}: rc={rc} wall={time.time() - t0:.0f}s error={r['is_error']} result={str(r['result'])[:80]!r} "
        f"usage={r['usage']}")
    if r["is_error"]:
        log(open(os.path.join(RD, "cli", f"{tag}.stderr")).read()[-600:])
    return r


sid = None
for i in range(4):
    head = ("This is a long-context test in several parts. Read each part; do not call tools; reply only 'OK part "
            f"{i + 1}'.\n")
    body = records(n // 2, i * n) + (f"SECRET CODE: {MARKER}\n" if i == 0 else "") + records(n - n // 2, i * n + n // 2)
    r = turn(f"fill{i + 1}", head + body, sid)
    sid = sid or r["session_id"]
st = {"codex_sid": sid}
r2, _ = W.drive(RD, st, lambda: None, "Run `cat /workspace/blk_01.txt`, then `cat /workspace/blk_02.txt`, and so on up "
                "to `cat /workspace/blk_14.txt`: fourteen separate commands, one at a time, each printing the whole "
                "file. Then reply with the KEY line printed by the last file.", "", 1800, "t2", log)
log(f"turn cat: error={r2 and r2['is_error']} result={str(r2 and r2['result'])[:120]!r} usage={r2 and r2['usage']}")
r3, _ = W.drive(RD, st, lambda: None, "Without running commands: which KEY did the last file print, and what was the "
                "SECRET CODE in the first part of this conversation? Say 'unknown' for anything you no longer have.",
                "", 900, "t3", log)
log(f"turn question: error={r3 and r3['is_error']} result={str(r3 and r3['result'])[:200]!r}")
f = W.session_file(RD, st["codex_sid"])
lines = [json.loads(l) for l in open(f)]
comp = sum(1 for j in lines if j.get("type") == "compacted")
tc = [j["payload"]["info"]["last_token_usage"]["input_tokens"] for j in lines
      if j.get("type") == "event_msg" and (j.get("payload") or {}).get("type") == "token_count"
      and (j["payload"].get("info") or {}).get("last_token_usage")]
log(f"session {st['codex_sid']}: compacted items {comp}; max request input {max(tc) if tc else None}; "
    f"last request input {tc[-1] if tc else None}; abandoned {st.get('abandoned_sids')}")
