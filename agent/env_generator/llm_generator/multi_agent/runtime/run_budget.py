"""RunBudget — run_budget.json caps + usage persistence (PROPOSAL #8, Tier-1b).

Extracted VERBATIM from Orchestrator (behavior-preserving move). ``run_budget.json``
is the live budget kill-switch: the UI may raise the caps mid-run and the delivery-wait
loop re-reads them each tick, writing usage back so the live monitor can show progress.
Pure file IO over ``output_dir``; holds NO orchestrator state — the cleanest Tier-1
extraction (reviewed_version:8: "fully clean, greenlight as-is").

NOTE on location: the proposal said an ``orchestrator/`` package, but that name collides
with ``orchestrator.py`` (a dir and a module cannot coexist). The established home for
extracted orchestrator logic is ``runtime/`` (backend_scaffold, validation_runner, …),
so Tier-1 collaborators live here.
"""

import json
import os
import time
from pathlib import Path
from typing import Any, Dict


class RunBudget:
    """Owns run_budget.json. Constructed with the run's output_dir + a logger."""

    def __init__(self, output_dir, logger):
        self._output_dir = Path(output_dir)
        self._logger = logger

    def path(self) -> Path:
        return self._output_dir / "run_budget.json"

    def load_caps(self, env_defaults: Dict[str, Any]) -> Dict[str, Any]:
        """Caps from run_budget.json if present (UI can raise them live), else env."""
        try:
            data = json.loads(self.path().read_text(encoding="utf-8"))
            caps = data.get("caps") or {}
            return {
                "max_wall_sec": float(caps.get("max_wall_sec", env_defaults["max_wall_sec"])),
                "max_ticks": int(caps.get("max_ticks", env_defaults["max_ticks"])),
                "unlimited": bool(caps.get("unlimited", env_defaults.get("unlimited", False))),
            }
        except Exception:
            return dict(env_defaults)

    def write(self, caps: Dict[str, Any], started_at: float,
              elapsed: float, ticks: int, status: str) -> None:
        """Persist caps + usage so the live monitor can show budget progress."""
        try:
            payload = {
                "caps": {"max_wall_sec": float(caps["max_wall_sec"]), "max_ticks": int(caps["max_ticks"]),
                         "unlimited": bool(caps.get("unlimited", False))},
                "usage": {
                    "started_at": started_at,
                    "elapsed_sec": round(float(elapsed), 1),
                    "ticks": int(ticks),
                    "status": status,
                    "updated_at": time.time(),
                },
            }
            # #1163: carry the SPEND beside the wall-clock and tick caps. The framework
            # had a budget abort and no budget: what a run cost only existed afterwards,
            # by grepping `prompt_tokens=` out of a log. It rides here because this file
            # is what the live monitor already reads, so the number is visible DURING a
            # run rather than in a post-mortem. Best-effort: accounting must never be the
            # reason a run record fails to write.
            try:
                from utils.llm import llm_usage, tool_result_bytes
                payload["llm"] = llm_usage()
                # #1171: the top contributors only — the whole map is long and the
                # question ("which tool put that much in the context") is answered by
                # the head of it.
                _tb = tool_result_bytes()
                if _tb:
                    payload["tool_result_bytes"] = dict(list(_tb.items())[:12])
            except Exception:
                pass
            path = self.path()
            tmp = path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            os.replace(tmp, path)
        except Exception as e:
            self._logger.debug("run_budget write failed: %s", e)
