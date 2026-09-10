"""#1202ju: the MCP surface is projected once, at kickoff, and never again.

`project_mcp`'s docstring says the tool surface "cannot drift from the endpoints" because it
is a deterministic projection of the RegistryHub business contract. A deterministic projection
is only deterministic if it is re-run when its input moves, and this one ran exactly once —
`_generate_mcp()` is awaited immediately after kickoff registers the contract, so every
endpoint a lane registers during implementation arrives afterwards and never gets a tool.

Measured: tiktok-r111's `mcp_server/app/main.py` was written 19:15 and its endpoints hub last
moved 02:23 the next morning — seven hours of contract growth, 20 tools against 31 business
endpoints by mcp_scaffold's own filter. 16 of the 17 recent runs carrying an MCP probe report
the surface INCOMPLETE, and the probe is right.

Same shape as #1202ic (param types) and #1202jt (auth guard), one artefact over.
"""
import sys
import pathlib

_AGENT = pathlib.Path(__file__).resolve().parents[1]
if str(_AGENT) not in sys.path:
    sys.path.insert(0, str(_AGENT))

import ast                                                             # noqa: E402
import inspect                                                         # noqa: E402

from env_generator.llm_generator.multi_agent.runtime import scaffolder as SC  # noqa: E402
from env_generator.llm_generator.multi_agent.runtime import mcp_scaffold as MS  # noqa: E402


class _Hubs:
    def __init__(self, eps):
        self.registryhub = type("R", (), {"get_endpoints": lambda _s: eps})()


class _Orch:
    def __init__(self, out, eps):
        self.output_dir = str(out)
        self.hubs = _Hubs(eps)
        self._logger = type("L", (), {"warning": lambda *a, **k: None,
                                      "info": lambda *a, **k: None,
                                      "debug": lambda *a, **k: None})()


def _eps(*paths):
    return {f"e{i}": {"method": "GET", "path": p, "status": "implemented"}
            for i, p in enumerate(paths)}


def _scaffolder(out, eps):
    s = SC.Scaffolder.__new__(SC.Scaffolder)
    s._orch = _Orch(out, eps)
    return s


def _write_server(out, eps):
    d = pathlib.Path(out) / "mcp_server" / "app"
    d.mkdir(parents=True, exist_ok=True)
    (d / "main.py").write_text(MS.render_mcp_server(eps, "app"), encoding="utf-8")
    return d / "main.py"


def test_an_unmoved_contract_does_not_touch_the_tree(tmp_path):
    """★ RENDER-THEN-COMPARE: `write_mcp_server` writes three files unconditionally, so a
    per-cycle call would churn mtimes — the stale-looking-mtime trap of #934/#1202jn."""
    eps = _eps("/api/videos", "/api/users")
    f = _write_server(tmp_path, eps)
    before = f.stat().st_mtime_ns
    assert _scaffolder(tmp_path, eps).refresh_mcp_1202ju() is False
    assert f.stat().st_mtime_ns == before, "an unchanged contract must not rewrite the file"


def test_a_grown_contract_is_re_projected(tmp_path):
    """★ r111's shape: endpoints registered after kickoff never reached the surface."""
    _write_server(tmp_path, _eps("/api/videos"))
    grown = _eps("/api/videos", "/api/explore", "/api/live")
    assert _scaffolder(tmp_path, grown).refresh_mcp_1202ju() is True
    now = (tmp_path / "mcp_server" / "app" / "main.py").read_text()
    assert "/api/explore" in now and "/api/live" in now


def test_it_never_creates_a_server_kickoff_has_not_made(tmp_path):
    """Kickoff's pass owns the first projection; this one only keeps it current.

    Pins the OUTCOME, not one guard: deleting the `is_file()` early return leaves this green,
    because the read then raises and the function's own `except` returns False anyway. Said
    plainly rather than claiming a counter-proof that does not fire — the explicit check is
    readability, and the except is what actually holds the line.
    """
    assert _scaffolder(tmp_path, _eps("/api/videos")).refresh_mcp_1202ju() is False
    assert not (tmp_path / "mcp_server").exists()


def test_no_business_endpoints_is_not_a_reason_to_write(tmp_path):
    _write_server(tmp_path, _eps("/api/videos"))
    assert _scaffolder(tmp_path, {}).refresh_mcp_1202ju() is False


def test_the_async_entry_and_the_cycle_entry_share_one_body():
    """One fact, one emitter: `generate_mcp` must delegate, not hold a second copy."""
    body = inspect.getsource(SC.Scaffolder.generate_mcp)
    assert "self.project_mcp()" in body
    assert "write_mcp_server" not in body, (
        "the async entry keeps no projection logic of its own")


def test_the_refresh_is_hooked_once_not_at_each_caller():
    """★ #706 hooked one of three release sites; #934 one of four branches. One wrapper."""
    from env_generator.llm_generator.multi_agent import orchestrator as ORCH
    tree = ast.parse(inspect.getsource(ORCH))
    calls = [n for n in ast.walk(tree)
             if isinstance(n, ast.Call)
             and getattr(n.func, "attr", None) == "refresh_mcp_1202ju"]
    assert len(calls) == 1, f"expected one hook, found {len(calls)}"
    wrapper = inspect.getsource(ORCH.Orchestrator._project_missing_routes)
    assert "refresh_mcp_1202ju" in wrapper, (
        "it belongs in the per-cycle re-projection wrapper both cycle sites already call")
