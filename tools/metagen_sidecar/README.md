# metagen → OpenAI sidecar

Bridges the forgingground engine (conda/venv, OpenAI API) to the MetaGen SDK
(`metagen`, which is **Buck-PAR-only** — native fbthrift/folly extensions, not
pip-installable). The sidecar is a Buck `python_binary` that imports `metagen`, creates a
platform via `thrift_platform_factory`, and serves OpenAI-style
`POST /v1/chat/completions` on localhost. The engine points `--api-base` at it.

```
engine (conda) --provider openai --api-base http://127.0.0.1:8900/v1 --model <metagen-id>
      │  OpenAI /v1/chat/completions (HTTP, localhost)
      ▼
metagen_sidecar (Buck PAR) ── metagen thrift_platform_factory.dialog_completion() ─▶ GPT-5.6 / Fable / Gemini
```

## Setup
1. Copy `metagen_sidecar.py` + `TARGETS` into your fbcode checkout, e.g.
   `fbcode/scripts/<you>/metagen_sidecar/`.
2. **Confirm the real metagen API first** (the class names below are resolved defensively;
   this prints ground truth so we can fix any mismatch):
   ```
   buck2 run //scripts/<you>/metagen_sidecar:metagen_sidecar -- --introspect
   ```
   Paste that output back if anything looks off (esp. the Dialog*/attachment/tool-call
   class names and the `dialog_completion` signature).
3. **Run the sidecar** (devserver auth; runs as your unix user):
   ```
   MG_KEY='mg-api-...' buck2 run //scripts/<you>/metagen_sidecar:metagen_sidecar -- --port 8900
   ```
   Leave it running. `ENVGEN_METAGEN_FACTORY=prod` switches to `thrift_platform_factory.create`
   (needs CAT tokens for a real identity — see the extra dep in TARGETS).

## Point the engine at it
In the conda env where the generator runs:
```
export OPENAI_API_KEY=dummy            # sidecar ignores it; it uses MG_KEY
python -m env_generator.llm_generator.main \
  --provider openai --api-base http://127.0.0.1:8900/v1 \
  --model gpt-5-6-sol-genai-responses \
  --name netflix-web-r1 --design-input design_inputs/netflix
```

## Quick smoke test (no engine)
```
curl -s http://127.0.0.1:8900/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"gpt-5-6-sol-genai-responses","messages":[{"role":"user","content":"Reply with exactly: pong"}]}'
```

## Notes
- Only the Python stdlib is used for HTTP, so the Buck target needs **no dep beyond metagen**.
- Tool calling: the engine's OpenAI tool schema is forwarded to metagen's `tools` string
  (works for 3P models GPT/Claude/Gemini). `tool_choice` → metagen `tool_config`.
- Vision: `image_url` data-URIs → `DialogAttachmentContent`.
- `-responses` models (e.g. `gpt-5-6-sol-genai-responses`): if `dialog_completion` rejects
  them or ignores `tools`, use `claude-5-fable-vertex-genai` / `gemini-3-1-pro-preview-genai`,
  which are standard dialog models — or we add a Responses-API path in the sidecar.
