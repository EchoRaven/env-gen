"""Body translation for the anthropic->Vertex proxy (tools/vertex_anthropic_proxy).

Pure-function checks on translate_body: model moves to the URL (dropped from body),
anthropic_version is stamped, the stream flag is kept ONLY for the streaming verb, and
everything caching/tool-calling depends on (system w/ cache_control, tools, messages) is
forwarded untouched. Live e2e (caching + SSE) was verified separately against the gateway.
"""
import importlib.util
import pathlib

_P = (pathlib.Path(__file__).resolve().parents[2]
      / "tools/vertex_anthropic_proxy/vertex_anthropic_proxy.py")


def _load():
    # Module builds a shared httpx client (with the fb cert) at import; fine on this host.
    spec = importlib.util.spec_from_file_location("vxproxy_iso", str(_P))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


vx = _load()


def _body():
    return {
        "model": "claude-opus-4-7",
        "max_tokens": 16,
        "system": [{"type": "text", "text": "big", "cache_control": {"type": "ephemeral"}}],
        "tools": [{"name": "t", "input_schema": {"type": "object"}}],
        "messages": [{"role": "user", "content": "hi"}],
    }


def test_model_moved_out_and_version_stamped():
    model, b = vx.translate_body(_body(), stream=False)
    assert model == "claude-opus-4-7"
    assert "model" not in b
    assert b["anthropic_version"] == vx.VERTEX_ANTHROPIC_VERSION


def test_cache_control_and_tools_preserved():
    _, b = vx.translate_body(_body(), stream=False)
    assert b["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert b["tools"][0]["name"] == "t"
    assert b["messages"] == [{"role": "user", "content": "hi"}]


def test_stream_flag_dropped_for_rawpredict():
    src = _body(); src["stream"] = True
    _, b = vx.translate_body(src, stream=False)
    assert "stream" not in b  # non-streaming verb must not carry it


def test_stream_flag_kept_for_streamrawpredict():
    _, b = vx.translate_body(_body(), stream=True)
    assert b["stream"] is True  # SSE only emitted when the body keeps stream=true


def test_missing_model_returns_none():
    src = _body(); src.pop("model")
    model, _ = vx.translate_body(src, stream=False)
    assert model is None


def test_upstream_url_verb_selection():
    assert vx._upstream_url("claude-opus-4-7", False).endswith(":rawPredict")
    assert vx._upstream_url("claude-opus-4-7", True).endswith(":streamRawPredict")
    assert "locations/global" in vx._upstream_url("claude-opus-4-7", False)


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
