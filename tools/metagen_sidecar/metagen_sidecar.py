#!/usr/bin/env python3
"""metagen -> OpenAI-compatible sidecar.

Bridges the two dependency worlds: the forgingground engine runs in a conda/venv and
speaks the OpenAI API; the MetaGen SDK (`metagen`) is Buck-PAR-only (native fbthrift/folly
extensions, not pip-installable). This is a Buck python_binary that imports `metagen`,
creates a platform via `thrift_platform_factory`, and serves OpenAI-style
`POST /v1/chat/completions` on localhost. The engine then runs:

    --provider openai --api-base http://127.0.0.1:<port>/v1 --model <metagen-virtual-id>

Only the stdlib is used for HTTP so the Buck target needs no dep beyond metagen.

Usage (inside the PAR):
    metagen_sidecar --introspect                 # dump the REAL metagen API (run this FIRST)
    MG_KEY='mg-api-...' metagen_sidecar --port 8900

Env:
    MG_KEY / METAGEN_API_KEY   the mg-api-... key (required to serve)
    ENVGEN_METAGEN_FACTORY     'devserver' (default) or 'prod' (thrift_platform_factory.create)
"""
from __future__ import annotations
import argparse
import json
import os
import re
import sys
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

_VERSION = "v18-imgstrip"

# CONTEXT BLOAT FIX (2026-07-22): agents call view_image() to look at references while building;
# each result carries a ~300KB base64 screenshot that the engine's observation-masking never trims
# (it only handles str content, not multimodal image parts), so the 20 Netflix references pile up to
# ~6.3M chars and are re-sent EVERY call (r5: content_chars=6.46M, 90-97s/call). The image
# INFORMATION is already fully captured as TEXT in reference_spec.json / design_system.json /
# component_specs, and any agent can re-view on demand — so stripping STALE images from history
# loses no information (the opposite of truncating text/debug). Keep images only in the most recent
# MG_IMAGE_KEEP_LAST messages; TEXT (incl. debug tool output) is NEVER touched here.
_IMAGE_KEEP_LAST = int(os.environ.get("MG_IMAGE_KEEP_LAST", "4") or 4)
# NB: no \s in the base64 class — data-URIs are contiguous, and \s would greedily consume the
# newline + any alphanumeric TEXT following the image (which must be preserved).
_DATA_URI_RE = re.compile(r"data:image/[A-Za-z0-9.+\-]+;base64,[A-Za-z0-9+/=]+")
_IMG_PLACEHOLDER = "[image viewed earlier — omitted to bound context; re-view with view_image if needed]"


def _strip_data_uris(text: str) -> str:
    """Replace inline base64 image data-URIs with a short placeholder; leaves all other text intact."""
    return _DATA_URI_RE.sub(_IMG_PLACEHOLDER, text)

# Prompt/KV-cache reuse: one sidecar process serves ONE generation run, and all of that run's
# calls share a large stable prefix (system prompt + contract + reference materials + tool defs).
# A single stable seed routes them to the SAME shard so its persistent KV cache serves that prefix
# instead of re-processing ~140k chars every call (r5: 90-97s/call on 140k-355k-char contexts).
# Applied ONLY when MG_STICKY_ROUTING is enabled (metagen warns sticky routing can perform worse /
# cause SEVs, and it only helps if the model has persistent KV cache enabled). Override via MG_STICKY_SEED.
_STICKY_SEED = os.environ.get("MG_STICKY_SEED") or os.urandom(8).hex()


# ── metagen SDK resolution (real names confirmed via --introspect) ───────────
def _imp(modnames, symbol):
    """Return symbol from the first module in `modnames` that has it, else None."""
    for mod in modnames:
        try:
            m = __import__(mod, fromlist=[symbol])
            if hasattr(m, symbol):
                return getattr(m, symbol)
        except Exception:
            continue
    return None


def load_sdk():
    """Resolve the metagen symbols we need into a namespace. Tries `metagen.types` and
    `metagen` (the SDK's base_module) for each. Optional classes resolve to None."""
    import types as _t
    ns = _t.SimpleNamespace()
    TYPE_MODS = ["metagen.types", "metagen"]
    ns.MetaGenKey = _imp(["metagen", "metagen.auth", "metagen.types"], "MetaGenKey")
    ns.thrift_platform_factory = _imp(
        ["metagen.platform_factories", "metagen"], "thrift_platform_factory")
    ns.Dialog = _imp(TYPE_MODS, "Dialog")
    ns.DialogMessage = _imp(TYPE_MODS, "DialogMessage")
    ns.DialogSource = _imp(TYPE_MODS, "DialogSource")
    ns.DialogTextContent = _imp(TYPE_MODS, "DialogTextContent")
    ns.DialogAttachmentContent = _imp(TYPE_MODS, "DialogAttachmentContent")
    ns.MessageAttachmentType = _imp(TYPE_MODS, "MessageAttachmentType")
    # confirmed real names (via --introspect):
    ns.ToolCallReq = _imp(TYPE_MODS, "DialogToolCallRequestContentV2")
    ns.ToolCallResp = _imp(TYPE_MODS, "DialogToolCallResponseContent")
    ns.Usage = _imp(TYPE_MODS, "Usage")
    ns.FinishReason = _imp(TYPE_MODS, "FinishReason")
    return ns


def introspect():
    """Print the REAL metagen API so we can confirm class names + dialog_completion signature."""
    import importlib
    import inspect
    print("== import metagen ==")
    metagen = importlib.import_module("metagen")
    print("metagen file:", getattr(metagen, "__file__", "?"))
    try:
        import pkgutil
        print("submodules:", sorted(m.name for m in pkgutil.iter_modules(metagen.__path__)))
    except Exception as e:
        print("submodules err:", e)
    for mod in ("metagen", "metagen.types", "metagen.platform_factories"):
        try:
            m = importlib.import_module(mod)
            names = [n for n in dir(m) if not n.startswith("_")]
            print(f"\n== {mod} ({len(names)}) ==")
            print([n for n in names if any(k in n for k in
                  ("Dialog", "Attachment", "Message", "Tool", "MetaGenKey",
                   "Platform", "factory", "Source", "Usage", "Finish", "Reason"))] or names[:40])
        except Exception as e:
            print(f"\n== {mod} == ERR {e}")
    # dialog_completion signature
    tpf = _imp(["metagen.platform_factories", "metagen"], "thrift_platform_factory")
    print("\nthrift_platform_factory:", tpf)
    if tpf is not None:
        print("factory methods:", [n for n in dir(tpf) if not n.startswith("_")])
    MGP = _imp(["metagen", "metagen.platform"], "MetaGenPlatform")
    if MGP is not None:
        try:
            print("dialog_completion sig:", inspect.signature(MGP.dialog_completion))
        except Exception as e:
            print("sig err:", e)
        print("MetaGenPlatform methods:", [n for n in dir(MGP)
              if "dialog" in n.lower() or "completion" in n.lower()])

    print("\n== class fields (exact constructor args the sidecar needs) ==")

    def _describe(name):
        cls = _imp(["metagen.types", "metagen"], name)
        if cls is None:
            print(f"{name}: MISSING")
            return
        bits = []
        try:
            bits.append("init" + str(inspect.signature(cls.__init__)))
        except Exception:
            pass
        for attr in ("_fields", "__annotations__", "thrift_spec"):
            v = getattr(cls, attr, None)
            if v:
                try:
                    bits.append(f"{attr}={list(v.keys()) if isinstance(v, dict) else list(v)}")
                except Exception:
                    pass
        print(f"{name}: {' | '.join(bits) if bits else dir(cls)[:25]}")

    for n in ("Dialog", "DialogMessage", "DialogTextContent", "DialogAttachmentContent",
              "DialogToolCallRequestContentV2", "DialogToolCallResponseContent",
              "DialogResponseOutputFunctionToolCallContent", "DialogCompletionResponse",
              "DialogCompletion", "Usage"):
        _describe(n)
    for enum_name in ("DialogSource", "MessageAttachmentType", "FinishReason"):
        e = _imp(["metagen.types", "metagen"], enum_name)
        members = [m for m in dir(e) if not m.startswith("_") and m.isupper()] if e else []
        print(f"{enum_name} members: {members}")
    print("\n(confirm the class names above match load_sdk(); adjust _imp lists if not.)")


# ── platform ─────────────────────────────────────────────────────────────────
def make_platform(sdk):
    key = os.environ.get("MG_KEY") or os.environ.get("METAGEN_API_KEY")
    if not key:
        raise SystemExit("Set MG_KEY (or METAGEN_API_KEY) to your mg-api-... key")
    if sdk.thrift_platform_factory is None or sdk.MetaGenKey is None:
        raise SystemExit("Could not resolve thrift_platform_factory / MetaGenKey — run --introspect")
    cred = sdk.MetaGenKey(key=key)
    factory = os.environ.get("ENVGEN_METAGEN_FACTORY", "devserver").lower()
    fn = (sdk.thrift_platform_factory.create if factory == "prod"
          else sdk.thrift_platform_factory.create_for_current_unix_user_for_devserver_only)
    # auto_rate_limit lets the SDK back off/retry on 429s (a full run bursts many concurrent
    # calls; GPT-5.6-sol's self-service quota is tight). Fall back if the factory lacks the kwarg.
    try:
        return fn(metagen_auth_credential=cred, auto_rate_limit=True)
    except TypeError:
        return fn(metagen_auth_credential=cred)


# ── OpenAI request -> metagen Dialog ─────────────────────────────────────────
def _split_data_uri(url):
    m = re.match(r"data:([^;]+);base64,(.*)", url or "", re.DOTALL)
    return (m.group(1), m.group(2)) if m else (None, None)


def _source(sdk, role):
    DS = sdk.DialogSource
    name = {"system": "SYSTEM", "user": "USER", "assistant": "ASSISTANT",
            "developer": "DEVELOPER", "tool": "IPYTHON", "function": "IPYTHON"}.get(role, "USER")
    return getattr(DS, name, getattr(DS, "USER"))


_SUPPORTED_IMG = {"image/jpeg", "image/png", "image/gif", "image/webp"}


def _sniff_mime(raw):
    """Detect the true image type from magic bytes (the engine sometimes mislabels jpeg as png,
    which Claude rejects). Returns a supported mime or None."""
    if raw[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if raw[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if raw[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
        return "image/webp"
    return None


def _fit_image(b64, mime, limit=4_500_000):
    """Claude Vertex accepts only jpeg/png/gif/webp and caps images at 5 MB. Pass through a
    supported image under the cap; otherwise transcode/shrink to JPEG via PIL (handles oversized
    rasters AND unsupported types like bmp/tiff). If we can't (e.g. SVG, or PIL absent in the PAR)
    return (None, None) so the caller DROPS it rather than 500-ing the whole request."""
    import base64
    try:
        raw = base64.b64decode(b64)
    except Exception:
        return None, None
    real = _sniff_mime(raw)
    if real:
        mime = real  # trust the actual bytes over the engine's declared media type
    m = (mime or "").lower()
    if m in _SUPPORTED_IMG and len(raw) <= limit:
        return b64, mime
    if "svg" in m:  # rasterize SVG so the model can SEE it (the app still ships the real .svg)
        try:
            import cairosvg
            raw = cairosvg.svg2png(bytestring=raw, output_width=1024)
        except Exception:
            return None, None  # no SVG rasterizer in the PAR → drop (logo/icons still appear in screenshots)
    try:
        import io
        from PIL import Image
        im = Image.open(io.BytesIO(raw)).convert("RGB")
        for side in (1568, 1280, 1024, 768):
            w, h = im.size
            r = side / max(w, h) if max(w, h) > side else 1.0
            im2 = im.resize((round(w * r), round(h * r))) if r < 1.0 else im
            buf = io.BytesIO()
            im2.save(buf, "JPEG", quality=80)
            if buf.tell() <= limit:
                return base64.b64encode(buf.getvalue()).decode(), "image/jpeg"
        return None, None
    except Exception:
        return None, None  # PIL unavailable in the PAR → drop the oversized image (safe)


def _attachment(sdk, url):
    mime, b64 = _split_data_uri(url)
    if not b64 or sdk.DialogAttachmentContent is None or sdk.MessageAttachmentType is None:
        return None
    b64, mime = _fit_image(b64, mime)
    if not b64:
        return None  # oversized + couldn't shrink → drop (caller substitutes a text note)
    atype = getattr(sdk.MessageAttachmentType, "BASE64", None) or \
        getattr(sdk.MessageAttachmentType, "BASE64_IMAGE", None)
    for kw in ({"data": b64, "type": atype, "mime": mime or "image/png"},
               {"data": b64, "type": atype, "mime_type": mime or "image/png"}):
        try:
            return sdk.DialogAttachmentContent(**kw)
        except Exception:
            continue
    return None


def _valid_tool_id(tid, i):
    """Anthropic requires tool ids to match ^[a-zA-Z0-9_-]+$ and be non-empty."""
    tid = tid or ""
    if tid and re.fullmatch(r"[a-zA-Z0-9_-]+", tid):
        return tid
    return f"call_{i}"


def _tool_call_content(sdk, name, args_str, tool_id):
    # DialogToolCallRequestContentV2 carries the call as Anthropic tool_use JSON in tool_call_text.
    # It MUST include a non-empty id (^[a-zA-Z0-9_-]+$) so the later tool_result can reference it.
    C = sdk.ToolCallReq
    if C is None:
        return None
    try:
        inp = json.loads(args_str) if isinstance(args_str, str) else (args_str or {})
    except Exception:
        inp = {}
    txt = json.dumps({"type": "tool_use", "id": tool_id, "name": name, "input": inp})
    for kw in ({"tool_call_text": txt}, {"tool_call_text": txt, "metadata": None}):
        try:
            return C(**kw)
        except Exception:
            continue
    return None


def _contents(sdk, msg, strip_images: bool = False):
    out = []
    c = msg.get("content")
    if isinstance(c, str):
        if c:
            out.append(sdk.DialogTextContent(text=_strip_data_uris(c) if strip_images else c))
    elif isinstance(c, list):
        for part in c:
            if not isinstance(part, dict):
                out.append(sdk.DialogTextContent(text=str(part)))
            elif part.get("type") == "text":
                out.append(sdk.DialogTextContent(text=part.get("text", "")))
            elif part.get("type") == "image_url":
                if strip_images:  # stale image: drop the base64, keep a text breadcrumb
                    out.append(sdk.DialogTextContent(text=_IMG_PLACEHOLDER))
                    continue
                att = _attachment(sdk, (part.get("image_url") or {}).get("url", ""))
                out.append(att if att is not None else
                           sdk.DialogTextContent(text="[image omitted]"))
    # Render PRIOR tool calls as plain text — providers (Claude Vertex) strictly validate
    # structured tool_use/tool_result id linkage on replayed history, which metagen's Dialog
    # doesn't let us control. Text keeps the model's context without the fragile correlation.
    for tc in (msg.get("tool_calls") or []):
        fn = tc.get("function") or {}
        args = fn.get("arguments")
        args = args if isinstance(args, str) else json.dumps(args or {})
        out.append(sdk.DialogTextContent(text=f"[called tool `{fn.get('name', '')}` with arguments {args}]"))
    if not out:
        out.append(sdk.DialogTextContent(text=""))
    return out


def _tool_response(sdk, msg):
    body = msg.get("content")
    body = body if isinstance(body, str) else json.dumps(body) if body is not None else ""
    # tool_name must carry the tool_use id (Anthropic tool_result.tool_use_id) so it links to the
    # assistant's tool_use — prefer tool_call_id over the function name.
    name = _valid_tool_id(msg.get("tool_call_id") or msg.get("name"), 0)
    # DialogToolCallResponseContent requires text + tool_name + tool_data (all required).
    C = sdk.ToolCallResp
    if C is not None:
        try:
            return [C(text=body, tool_name=name, tool_data=body)]
        except Exception:
            pass
    return [sdk.DialogTextContent(text=f"[tool result {name}] {body}")]


def build_dialog(sdk, messages):
    # #999: report the size that actually LEAVES here, not the one the client measured.
    #
    # The client logs `content_chars` BEFORE sending, so a vision lane shows figures like
    # 13.5 MB (r162's peak) while this function strips every base64 image outside the last
    # MG_IMAGE_KEEP_LAST messages. The logged number is therefore systematically wrong for
    # exactly the lanes where size matters, and reading it cost a 15-minute investigation
    # into a runaway context that was never running away.
    #
    # Same shape as #973 and #987: a number printed without the one fact needed to read it.
    # Logged only when stripping actually changed something, so ordinary text-only calls
    # stay silent.
    _pre = 0
    for _m in messages:
        _c = (_m or {}).get("content") if isinstance(_m, dict) else None
        if isinstance(_c, str):
            _pre += len(_c)
    dmsgs = []
    n = len(messages)
    # Keep base64 images only in the most recent MG_IMAGE_KEEP_LAST messages; strip stale ones
    # (see _IMAGE_KEEP_LAST note). TEXT is never stripped — only image data-URIs.
    keep_img_from = max(0, n - _IMAGE_KEEP_LAST)
    for i, m in enumerate(messages):
        strip = i < keep_img_from
        role = m.get("role", "user")
        if role == "tool":
            # Render the tool result as a plain USER text message (see _contents note) — avoids
            # structured tool_result.tool_use_id validation we can't satisfy through Dialog.
            body = m.get("content")
            body = body if isinstance(body, str) else json.dumps(body) if body is not None else ""
            if strip and "data:image" in body:  # a view_image-style result that carried a base64 blob
                body = _strip_data_uris(body)
            name = m.get("name") or m.get("tool_call_id") or "tool"
            dmsgs.append(sdk.DialogMessage(source=_source(sdk, "user"),
                         contents=[sdk.DialogTextContent(text=f"[tool result — {name}]\n{body}")]))
        else:
            dmsgs.append(sdk.DialogMessage(source=_source(sdk, role),
                         contents=_contents(sdk, m, strip_images=strip)))
    try:
        _post = sum(len(getattr(c, "text", "") or "")
                    for m in dmsgs for c in (getattr(m, "contents", None) or []))
        if _pre and _post and _pre - _post > 100_000:
            print(f"[sidecar] image-strip: {_pre:,} -> {_post:,} chars "
                  f"(images kept in last {_IMAGE_KEEP_LAST} messages)", flush=True)
    except Exception:
        pass
    return sdk.Dialog(messages=dmsgs)


def _tools_string_for_model(tools, model):
    """metagen forwards the `tools` string verbatim to the provider, so it must be in the
    PROVIDER's schema (confirmed by Claude rejecting OpenAI's {type:function}). The engine
    emits OpenAI format; translate per model family. Returns a JSON string."""
    m = (model or "").lower()
    fns = [t.get("function") or {} for t in tools if isinstance(t, dict)]
    # Anthropic / Claude (incl. Fable): [{name, description, input_schema}]
    if any(k in m for k in ("claude", "fable", "anthropic", "sonnet", "opus", "haiku")):
        return json.dumps([{"type": "custom", "name": f.get("name"),
                            "description": f.get("description", ""),
                            "input_schema": f.get("parameters") or {"type": "object", "properties": {}}}
                           for f in fns])
    # Gemini: [{functionDeclarations:[{name, description, parameters}]}]
    if "gemini" in m:
        return json.dumps([{"functionDeclarations": [
            {"name": f.get("name"), "description": f.get("description", ""),
             "parameters": f.get("parameters") or {"type": "object", "properties": {}}}
            for f in fns]}])
    # OpenAI Responses API (gpt-*-genai-responses): FLAT tool schema (name at top level).
    if "responses" in m:
        return json.dumps([{"type": "function", "name": f.get("name"),
                            "description": f.get("description", ""),
                            "parameters": f.get("parameters") or {"type": "object", "properties": {}}}
                           for f in fns])
    # OpenAI / Azure / GPT Chat Completions (default): nested {type:function, function:{...}}.
    return json.dumps(tools)


# ── metagen response -> OpenAI ───────────────────────────────────────────────
def _norm_finish(finish, has_tools):
    if has_tools:
        return "tool_calls"
    s = str(finish or "").upper()
    return "length" if ("MAX_OUTPUT" in s or "LENGTH" in s) else "stop"


def _parse_tool_call_text(raw):
    """DialogToolCallRequestContentV2.tool_call_text holds the model's raw tool call. Extract
    (name, arguments_json_string). Handles our own {name,arguments} round-trip and provider
    shapes (Anthropic tool_use {name,input}, OpenAI {name,arguments})."""
    try:
        o = json.loads(raw)
    except Exception:
        return "", "{}", ""
    if not isinstance(o, dict):
        return "", "{}", ""
    tid = o.get("id") or o.get("call_id") or ""
    fn = o.get("function")
    if isinstance(fn, dict):
        # OpenAI chat-completions shape wrapped in tool_call_text (GPT): {"function":{name,arguments}}
        name = fn.get("name") or ""
        args = fn.get("arguments")
    else:
        # Anthropic tool_use {name,input} / flat {name,arguments}
        name = o.get("name") or o.get("tool_name") or ""
        args = o.get("arguments")
        if args is None:
            args = o.get("input") or o.get("parameters") or o.get("args")
    if args is None:
        args = {}
    return name, (args if isinstance(args, str) else json.dumps(args)), tid


def _debug_contents(resp):
    """Dump the raw content objects (type + public attrs) of the response — so we can see the
    real tool_call_text / field shapes. Enabled per-request via {"debug": true}."""
    out = []
    for ch in (getattr(resp, "choices", None) or [])[:1]:
        for msg in (getattr(getattr(ch, "dialog", None), "messages", None) or []):
            for c in (getattr(msg, "contents", None) or []):
                d = {"__type__": type(c).__name__}
                for a in dir(c):
                    if a.startswith("_"):
                        continue
                    try:
                        v = getattr(c, a)
                    except Exception:
                        continue
                    if not callable(v):
                        d[a] = repr(v)[:400]
                out.append(d)
    return out


def parse_response(resp):
    text, tool_calls = [], []
    choices = getattr(resp, "choices", None) or []
    finish = None
    if choices:
        ch = choices[0]
        finish = getattr(ch, "finish_reason", None)
        dialog = getattr(ch, "dialog", None)
        for msg in (getattr(dialog, "messages", None) or []):
            for c in (getattr(msg, "contents", None) or []):
                cname = type(c).__name__
                if "FunctionToolCall" in cname:  # responses-API: name + arguments (JSON string)
                    nm = getattr(c, "name", "") or ""
                    ps = getattr(c, "arguments", None)
                    ps = ps if isinstance(ps, str) else json.dumps(ps or {})
                    tid = getattr(c, "call_id", None) or getattr(c, "id", None)
                    tool_calls.append({"id": _valid_tool_id(tid, len(tool_calls)), "type": "function",
                                       "function": {"name": nm, "arguments": ps}})
                    continue
                if "ToolCall" in cname:  # DialogToolCallRequestContentV2: everything in tool_call_text
                    nm, ps, tid = _parse_tool_call_text(getattr(c, "tool_call_text", "") or "")
                    tool_calls.append({"id": _valid_tool_id(tid, len(tool_calls)), "type": "function",
                                       "function": {"name": nm, "arguments": ps}})
                    continue
                t = getattr(c, "text", None)
                if isinstance(t, str) and "Reasoning" not in cname:
                    text.append(t)
    u = getattr(resp, "usage", None)
    usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    if u is not None:
        pt = getattr(u, "prompt_tokens", None) or 0
        ct = getattr(u, "completion_tokens", None) or 0
        tt = getattr(u, "total_tokens", None)
        usage = {"prompt_tokens": pt, "completion_tokens": ct,
                 "total_tokens": tt if tt is not None else pt + ct}
    return "".join(text), (tool_calls or None), _norm_finish(finish, bool(tool_calls)), usage


def _drops_sampling(model):
    """Reasoning-class models (Claude 5 Fable, GPT-5, o-series) deprecate temperature/top_p."""
    if os.environ.get("MG_NO_SAMPLING") == "1":
        return True
    m = (model or "").lower()
    return any(k in m for k in ("claude-5", "fable", "gpt-5", "o1", "o3", "o4", "reasoning"))


def complete(sdk, platform, body):
    dialog = build_dialog(sdk, body.get("messages") or [])
    model = body.get("model")
    params = {"model": model, "dialog": dialog}
    no_sampling = _drops_sampling(model)
    if body.get("temperature") is not None and not no_sampling:
        params["temperature"] = body["temperature"]
    # max_tokens is REQUIRED by some 3P models (e.g. Claude Vertex) — always send it.
    params["max_tokens"] = (body.get("max_tokens") or body.get("max_completion_tokens")
                            or int(os.environ.get("MG_DEFAULT_MAX_TOKENS", "4096")))
    if body.get("top_p") is not None and not no_sampling:
        params["top_p"] = body["top_p"]
    tools = body.get("tools")
    if tools:
        # provider-specific schema string — dialog_completion has NO tool_config kwarg.
        params["tools"] = _tools_string_for_model(tools, model)
    if body.get("reasoning_effort"):
        params["reasoning_effort"] = body["reasoning_effort"]
    # Route all of a run's calls to one shard for persistent-KV-cache reuse of the common prefix.
    # Opt-in (MG_STICKY_ROUTING=1) — see the _STICKY_SEED note above for the metagen caveats.
    if os.environ.get("MG_STICKY_ROUTING", "").strip().lower() in ("1", "true", "yes", "on"):
        params["sticky_routing_seed"] = _STICKY_SEED
    try:
        resp = platform.dialog_completion(**params)
    except Exception as e:  # safety net: strip sampling params if the model rejects them
        msg = str(e).lower()
        if (any(p in msg for p in ("temperature", "top_p", "sampling"))
                and any(w in msg for w in ("deprecat", "not supported", "unsupported", "invalid"))):
            params.pop("temperature", None)
            params.pop("top_p", None)
            resp = platform.dialog_completion(**params)
        else:
            raise
    content, tool_calls, finish, usage = parse_response(resp)
    msg = {"role": "assistant", "content": content or ""}
    if tool_calls:
        msg["tool_calls"] = tool_calls
    out = {"id": "chatcmpl-metagen", "object": "chat.completion",
           "model": body.get("model"),
           "choices": [{"index": 0, "message": msg, "finish_reason": finish}],
           "usage": usage}
    if body.get("debug"):
        out["_debug"] = _debug_contents(resp)
    return out


# ── HTTP ─────────────────────────────────────────────────────────────────────
class Handler(BaseHTTPRequestHandler):
    sdk = None
    platform = None

    def _send(self, code, obj):
        data = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *a):
        pass  # quiet

    def do_GET(self):
        if self.path.rstrip("/") in ("/health", "/v1/health"):
            return self._send(200, {"status": "ok", "version": _VERSION})
        if self.path.rstrip("/").endswith("/models"):
            return self._send(200, {"object": "list", "data": [
                {"id": os.environ.get("MG_MODEL", "gpt-5-6-sol-genai-responses"),
                 "object": "model", "owned_by": "metagen"}]})
        self._send(404, {"error": {"message": f"not found: {self.path}"}})

    def do_POST(self):
        if not self.path.rstrip("/").endswith("/chat/completions"):
            return self._send(404, {"error": {"message": f"not found: {self.path}"}})
        try:
            n = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(n) or b"{}")
        except Exception as e:
            return self._send(400, {"error": {"message": f"bad request: {e}"}})
        try:
            self._send(200, complete(self.sdk, self.platform, body))
        except Exception as e:
            traceback.print_exc()
            self._send(500, {"error": {"message": f"{type(e).__name__}: {e}",
                                       "type": "metagen_error"}})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8900)
    ap.add_argument("--introspect", action="store_true")
    args = ap.parse_args()
    if args.introspect:
        introspect()
        return
    sdk = load_sdk()
    Handler.sdk = sdk
    Handler.platform = make_platform(sdk)
    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"metagen sidecar {_VERSION} on http://{args.host}:{args.port}/v1  (Ctrl-C to stop)", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
