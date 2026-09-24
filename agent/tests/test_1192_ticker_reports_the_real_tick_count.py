"""#1192 — the budget ticker overwrote the real tick count with a literal zero.

#1175 added a 30-second ticker so `run_budget.json` would stop going stale (it had been
16 minutes behind, understating spend 3.4x). It writes the ledger from its own task, and it
passed `0` for the tick count — so every 30 seconds it overwrote whatever the coordination
loop had just recorded.

Measured across the ledgers: r19, r20, r21, r22, r23 and r24 ALL report `ticks=0`, including
runs that ran for over two hours. The only true values I ever saw in this session — r17's 27
and r20's 31/200 — were reads that happened to land between a loop write and the next
overwrite.

`max_ticks` still ENFORCES correctly: the loop compares its own local, not the ledger. What
was destroyed is the ability to SEE how close a run is to that ceiling — which is the number
the ceiling gets set from. That is my own defect, introduced with #1175.
"""
import inspect
import re

from env_generator.llm_generator.multi_agent import orchestrator as orc

_SRC = inspect.getsource(orc)


def _ticker_body():
    i = _SRC.index("async def _budget_ticker_1175(")
    return _SRC[i:_SRC.index("self._budget_ticker_1175 = asyncio.create_task", i)]


def test_the_ticker_no_longer_writes_a_literal_zero():
    body = _ticker_body()
    assert '_tick_count_1192' in body, "the ticker must report the live count"
    # The write's positional args: caps, start, elapsed, TICKS, status.
    call = body[body.index("self._budget.write("):]
    call = call[:call.index('"running")') + len('"running")')]
    assert re.search(r',\s*0,\s*"running"\)', call) is None, (
        "a literal 0 in the ticks position is the defect")


def test_the_loop_publishes_the_count_for_it():
    """The ticker is a separate task and cannot see the loop's local."""
    # Landmark, not a byte count: #1196 added comment lines between the publish and the
    # write and this window went red while the wiring it guards was untouched. #943, 13th.
    i = _SRC.index("self._tick_count_1192 = tick_count")
    between = _SRC[i:_SRC.index("self._write_run_budget(", i)]
    assert "\n\n" not in between, "publish must sit in the same block as the ledger write"


def test_the_ceiling_is_still_enforced_from_the_loops_own_local():
    """The fix must not make enforcement depend on the ledger — a written number can be
    stale, and the abort has to be exact."""
    assert 'tick_count >= caps["max_ticks"]' in _SRC


def test_no_budget_write_hardcodes_a_zero_tick_count():
    """★ The first pass fixed only the periodic ticker and left the FINAL write, which runs
    last and overwrites everything. r24's resume proved it: the abort said "aborted after 11
    coordination ticks" and the ledger it wrote said ticks=0.

    Every write is checked, with one exception stated explicitly: the "starting" write at
    boot, where zero is the true count.
    """
    import re as _re
    for m in _re.finditer(r"(?:_write_run_budget|_budget\.write)\(", _SRC):
        # Landmark, not a byte count: cut at the NEXT write (or the end). #943's ratchet,
        # twelfth sighting in this session -- the first draft of this very test had a 700.
        _nxt = _re.search(r"(?:_write_run_budget|_budget\.write)\(", _SRC[m.end():])
        call = _SRC[m.start():m.end() + _nxt.start()] if _nxt else _SRC[m.start():]
        status = _re.search(r'"(starting|running|finished|delivered|budget_exceeded|stuck_abort)"', call)
        if not status:
            continue
        seg = call[:status.start()]
        # A hardcoded 0 is CORRECT where the elapsed time is also hardcoded 0 -- the
        # "starting" write at boot and the loop's own first write, both before any tick has
        # happened. It is a defect only where elapsed is a real expression: that means time
        # has passed, ticks have been counted, and the ledger is being told otherwise.
        if _re.search(r"0\.0,\s*0,\s*$", seg.rstrip()) or _re.search(r",\s*0\.0,\s*0,\s*$", seg.rstrip()):
            continue
        assert _re.search(r",\s*0,\s*$", seg.rstrip()) is None, (
            "a literal 0 tick count with a live elapsed, before status=%s" % status.group(1))


def test_the_default_is_safe_when_the_loop_has_not_started():
    """Before the first tick the attribute does not exist; the ticker must still write."""
    body = _ticker_body()
    assert 'getattr(self, "_tick_count_1192", 0)' in body
