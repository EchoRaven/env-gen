# vertex_anthropic_proxy

A ~130-line localhost proxy that lets the engine's **native Anthropic client** talk to the
internal **Vertex gateway** (`vertex.ai-gateway.fbinfra.net`) for `claude-opus-4-7` — with
**prompt caching working**.

## Why it exists

- The engine's `AnthropicClient` (`agent/utils/llm.py`, wrapping `anthropic.AsyncAnthropic`)
  POSTs to `{api_base}/v1/messages`.
- The Vertex gateway instead (a) authenticates with the **fb x509 cert (mTLS)**, not a bearer
  key, and (b) exposes `…:rawPredict` / `…:streamRawPredict`, not `/v1/messages`.
- We must NOT go through the OpenAI-compat wrapper: it silently drops `cache_control` for opus
  (proven inert). This proxy forwards the **Anthropic body verbatim**, so caching works.

Verified live on `claude-opus-4-7`:
- non-streaming: call 1 `cache_creation_input_tokens=34303`, call 2 `cache_read=34303`
- streaming: full SSE (`message_start`…`message_stop`) with `cache_read` in `message_start`

## Run

```bash
# from the repo root, in a venv that has httpx
python tools/vertex_anthropic_proxy/vertex_anthropic_proxy.py --port 8790
# health:
curl -s http://127.0.0.1:8790/health
```

Then point the engine at it (a dummy key satisfies the SDK; the proxy ignores it):

```bash
--provider anthropic \
--api-base http://127.0.0.1:8790 \
--model claude-opus-4-7
# env: ANTHROPIC_API_KEY=dummy   ENVGEN_ANTHROPIC_CACHE=1 (default on, #368)
```

## Config (env, defaults suit this host)

| var | default | meaning |
|---|---|---|
| `VERTEX_GATEWAY_BASE` | `https://vertex.ai-gateway.fbinfra.net/v1` | gateway base |
| `VERTEX_PROJECT` | `devai-mea-egeit` | Vertex project |
| `VERTEX_LOCATION` | `global` | **only `global` works** (us-east5/europe-west1 → 501) |
| `FB_X509` | `/var/facebook/credentials/haibotong/x509/haibotong.pem` | client cert+key (mTLS) |
| `FB_CA` | `/etc/pki/tls/certs/fb_certs.pem` | CA to verify the gateway's server cert |
| `VERTEX_PROXY_TIMEOUT` | `600` | upstream timeout (s) |

## Notes

- `httpx`'s `cert=`+`verify=cafile` combo fails to present the client cert on TLS1.3 here;
  the proxy builds the `ssl.SSLContext` explicitly (CA + `load_cert_chain`) — that works.
- Streaming requires keeping `stream:true` in the body for `:streamRawPredict` (otherwise the
  gateway returns a single JSON blob the SDK can't parse). `translate_body` handles this.
