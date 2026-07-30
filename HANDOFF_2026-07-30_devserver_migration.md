# HANDOFF — moving the pipeline to a devserver (2026-07-30)

Self-contained for a fresh session, on a NEW machine. Repo:
`forgingground-gen` (the git repo is the `forgingground-gen/` dir itself).
Branch `feat/pipeline-opt-6` @ `8b7b21f`, being merged to `main`.

---

## 1. Why we are moving

Three capabilities we need are all behind **Facebook corp network connectivity**,
and the GPU box this work was done on has no VPN interface and no proxy. Probed
2026-07-30, all from the same key:

| endpoint | status | gives us |
|---|---|---|
| `api.llama.com/experimental/compat/openai/v1/chat/completions` | ✅ public, **currently used** | works, but see the defects below |
| `api.llama.com/experimental/passthrough/anthropic/v1/messages` | ❌ 403 "connect to the corporate VPN" | real `cache_control` + `cache_read_input_tokens`, and Claude's true `prompt_tokens` |
| `api.llama.com/experimental/passthrough/openai/v1/responses` | ❌ 403 same | GPT-5.5/5.6 tool-calling (broken on the compat layer) |
| `genai-api.facebook.com/dialog-completions/` | ❌ 401, needs internal identity | the Dialog API + its documented cache metrics |

`.../compat/openai/v1/models` and `.../responses` are **404** — the model list
cannot be enumerated, model names have to be probed one at a time.

**So the single reason to be on a devserver: those three 403/401s become 200s.**

---

## 2. What is known about caching (do not re-derive)

**Nothing about caching has been verified, and one plausible-sounding claim was
disproved.**

A claim came back that `prompt_tokens: 6` on Claude is *proof* caching works —
the reasoning being that Anthropic reports only non-cached input tokens, so
6 fresh + ~cached + completion = `total_tokens`. That arithmetic is self-
consistent on a repeated prefix, and it is **wrong**:

    novel prefix (fresh uuid, nothing cacheable)  -> prompt_tokens = 6, total 8049
    novel prefix #2                                -> prompt_tokens = 6, total 8044
    repeat of #2                                   -> prompt_tokens = 6, total 8044

A brand-new prefix has nothing cached, so a "non-cached count" would read ~8000.
It reads 6 either way — it is a constant, not a cache signal. Corroborating: on
the SAME gateway `prompt_tokens` is correct for gemini (8002) and for
`gpt-5-2-genai` (7213). The broken value is Claude-specific mapping, not caching.

Also measured: `cache_control` in every placement is silently accepted and inert
on the compat layer; `prompt_cache_key` is accepted with no observable effect; a
latency A/B with the salt at the START (so the cacheable prefix is genuinely
broken — putting it at the END shares the prefix and proves nothing) gives
**1.01x**, i.e. no observable benefit.

**The one experiment that would settle it**, once on corp network:

```bash
source /tmp/envgen_opus47.sh
curl -s -X POST "https://api.llama.com/experimental/passthrough/anthropic/v1/messages" \
  -H "Authorization: Bearer $ENVGEN_LLM_KEY" -H "anthropic-version: 2023-06-01" \
  -H "Content-Type: application/json" -d '{
    "model":"claude-4-7-opus-vertex-genai","max_tokens":16,
    "system":[{"type":"text","text":"<~3000 tokens of stable text>",
               "cache_control":{"type":"ephemeral"}}],
    "messages":[{"role":"user","content":"ok"}]}' | python3 -m json.tool | grep -i cache
```

Run it **twice**. First call should show `cache_creation_input_tokens > 0`,
second `cache_read_input_tokens > 0`. That is the only unambiguous evidence.

---

## 3. Model map (probed 2026-07-30, key `mg-api-71b41b05af9a`)

| model | entitled | tool-calling on compat | `prompt_tokens` |
|---|---|---|---|
| `claude-4-7-opus-vertex-genai` | ✅ | ✅ | ❌ constant 6 |
| **`gpt-5-2-genai`** | ✅ | ✅ | ✅ accurate |
| `gpt-5-1-genai` | ✅ | untested | ✅ |
| `gpt-5-5-genai-responses` | ✅ | ❌ gateway bug | ✅ |
| `gpt-5-6-sol-genai-responses` | ✅ | ❌ same bug, plus 429 quota | — |
| `gpt-4o-genai`, `gpt-5-mini-genai`, `gpt-4-1-genai`, `gpt-5-6-sol-genai-background-mode` | ⚠ exist, NO entitlement | — | — |
| `gpt-5-5-genai`, `gpt-5-6-genai`, `gpt-5-3/4-genai`, `*-sol-genai`, `*-background-mode` | ✗ do not exist | — | — |

**The `-responses` tool-calling bug is the GATEWAY, not the model** — worth
reporting to the metagen team with this repro:

- nested tools (`{"type":"function","function":{...}}`) → `400 Missing required parameter: 'tools[0].name'`
- flat tools (`{"type":"function","name":...}`) → `500 Out of bounds dict access: invalid index "function"` in
  `llama_experimental/openai_compat/core/LlamaApiExperimentalOpenAICha...`
- **hybrid (both keys present) → still `400 tools[0].name`**, which proves the
  gateway REWRITES tools from `tools[0]["function"]` and drops the flat field.
  There is no client-side escape.

On a devserver, use `passthrough/openai/v1/responses` for those models instead.

---

## 4. What was done, and what is NOT verified

35 commits this session, `#330`-`#365`, from a trajectory review of r91/r92/r93
(six parallel read-only agents; every P0 re-verified in source before acting).
Full evidence: `REVIEW_2026-07-29_round2_findings.md`.

Each fix is TDD (red→green) with its own test file, and every commit was checked
against a **byte-identical failure set vs the `c9224a0` baseline** — zero
regressions across all 35. Baseline is 18 pre-existing failures (NOT the "~8" an
earlier handoff claimed — I re-ran it).

> ⚠ **None of this has been validated by a live generation run.** Unit evidence
> only. Two fixes change run-termination conditions and want watching first:
> `#353` (the visual gate now BLOCKS on unjudged declared screens) and `#358`
> (the idle backstop can now actually fire, including for background lanes).

> ⚠ **`agent/tests/` is gitignored**, so the ~88 test files backing these fixes
> are NOT in the repo. To re-verify on the devserver they must be copied across
> out-of-band.

**Known flaky tests, do not chase:** `test_verdict_cache_by_pixels.py` and
`test_theme_variant_capture.py` (~23-27s each) are order/timing dependent and
rotate 0-2 spurious failures per full-suite run. Proven non-deterministic: the
same single test returned pass/FAIL/pass across three consecutive identical
invocations, and the file fails differently on the untouched baseline worktree.

---

## 5. Ops (exact)

- **Python**: `/home/haibotong/miniconda3/envs/dt/bin/python`. Run pytest FROM `agent/`.
  - `cd <repo>/agent && <python> -m pytest tests/<file> -q -p no:cacheprovider -p no:randomly`
- **Zero-regress check** (the discipline every commit followed): run the full
  suite, sort the `FAILED` lines, and `comm -13` against a baseline captured from
  a clean worktree at the merge-base. Anything in the left-only set is yours.
- **Launch a run** (needs ≥60G disk; `docker builder prune -af` if low):
  - `cd <repo> && setsid bash -c 'source /tmp/envgen_opus47.sh && ./run_tiktok_designinput.sh 95 > gm_tiktok_r95.log 2>&1' < /dev/null &`
  - **`setsid` is REQUIRED** — a plain `nohup` child dies on session rotation.
  - PID: `pgrep -f "main.*tiktok-web-r95"`. Log in the REPO ROOT.
- **Key**: all `/tmp/envgen_*.sh` share ONE key. The bearer is the
  `LLM|<id>|<secret>` app token; `mg-api-71b41b05af9a` is only the BILLING
  identity it resolves to. Budget was raised to $22k on 2026-07-29 and was live.
  - Probe before a long run:
    `source /tmp/envgen_opus47.sh && curl -s -m 30 -X POST "$ENVGEN_API_BASE/chat/completions" -H "Authorization: Bearer $ENVGEN_LLM_KEY" -H "Content-Type: application/json" -d "{\"model\":\"$ENVGEN_MODEL\",\"messages\":[{\"role\":\"user\",\"content\":\"ok\"}],\"max_tokens\":5}"`
  - `Spend exceeded` in the reply = the cap re-tripped; a run will become a
    zombie retrying ~11k times without ever reaching the abort ladder.
- **Monitoring a live run**: a timed ~20-min wakeup is the PRIMARY heartbeat,
  re-armed every turn (survives session rotation). Token-lean per wake: `ps -p
  <pid>` plus a grep for the terminal/milestone markers; deep-dive only on a real
  wedge. Cold start "persists" for 10-15 min is NORMAL, not a deadlock.
- **Push**: `GIT_SSH_COMMAND='ssh -i ~/.ssh/id_ed25519 -o IdentitiesOnly=yes' git push vaibackup HEAD:<branch>`
  - `origin` (`Virtue-AI/forgingground-gen`) is **not reachable** with either key
    on the old box — "Repository not found" for `id_ed25519` AND
    `id_ed25519_virtueai`. `vaibackup` works and has `main`.
  - No Claude co-author trailer in commit messages.

---

## 6. Next steps, in order

1. **Confirm the corp-network endpoints answer.** Run the two `passthrough/*`
   probes in §1. If they 200, the move has paid for itself immediately.
2. **Settle caching** with the §2 experiment. This is the largest open cost
   question and it is one command.
3. **Run r95 to validate `#330`-`#365` end-to-end.** Use
   `claude-4-7-opus-vertex-genai` for this — same model as r91-r94, so a
   regression is attributable. Do NOT change the model and the framework in the
   same run; that conflates "did the fixes work" with "does this model behave
   differently".
   - Watch: `#353` blocking correctly rather than wedging; `#358` firing only on
     genuine idling; `grep -c "#225 registered design-screen"` should now be
     NON-zero (it was 0 in r91-r94), and the delivered `App.jsx` should carry
     ~11 routes rather than 3.
4. **Separately**, if the OpenAI cost question matters, run one r96 on
   `gpt-5-2-genai` — its `prompt_tokens` is accurate, so per-run spend becomes
   measurable for the first time (Claude's constant 6 makes historical runs
   incomparable).
5. **Report the gateway tool-schema bug** (§3 repro) so the `-responses` family
   becomes usable on the compat layer too.

---

## 7. Still open (evidence gathered, not acted on)

From `REVIEW_2026-07-29_round2_findings.md`, verified but deliberately not fixed:

- **Resident-lane wake suppression.** r91's orchestrator made 550 `finish()`
  calls, 74% no-ops. `#358` bounds the damage but the wakes themselves are
  tick-driven and unsuppressed. The existing `allow_resident_wakeup` policy is
  per-MESSAGE and does not cover ticks. Needs a content-hash of the decision
  inputs — a real change to the coordinator loop, which I would not make without
  a live run to validate against.
- **Generality**: the framework is tiktok-shaped (62 of 83 run dirs). Computed/
  aggregate routes get a hardcoded empty stub then a HARD delivery block whose
  remediation is unactionable; the `{item}/{items}` envelope is a hard gate on a
  two-word vocabulary; auth is assumed universally. A non-social env will hit
  these.
- **Test-suite hygiene**: 347 silent `except: pass` handlers in the package are
  the mechanism by which heal layers accrete — a pass that silently no-ops looks
  identical to one that worked.
- **`origin` access**: nobody can push to `Virtue-AI/forgingground-gen` from the
  old box. Worth resolving so `vaibackup` is not the only home.
