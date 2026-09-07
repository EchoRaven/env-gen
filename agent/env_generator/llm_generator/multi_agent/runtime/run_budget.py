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


# #1202eb: the whole of a terminal provider reason, with room for phrasings we have not
# seen. Measured, and the measurement is thin on purpose to say so: the corpus holds
# exactly ONE distinct terminal reason (OpenAI's `429 ... insufficient_quota`, 217 chars,
# 257 occurrences across gm-r15 and the generated/ logs). That is one provider's one
# sentence, not a distribution — so the cap is set at ~1.8x it rather than at a quantile
# nobody could compute. Raise it if a second provider's billing text ever gets clipped.
_REASON_CAP_1202EB = 400


# #1202ev: `usage.status` alone cannot tell a killed run from a live one. 40 of the
# 104 undelivered runs in the corpus carry `status="running"` with no terminal reason --
# every one of them a process someone killed, and on disk indistinguishable from a run
# still working. Recording WHICH process wrote the ledger makes the question answerable
# by anyone reading the file, during the run or years later.
#
# The pid alone is not enough: pids are reused, so a dead run whose number was recycled
# would read as alive. Pairing it with the process start time from /proc settles that --
# a recycled pid has a different start time.
_STARTTIME_FIELD_1202EV = 22   # `starttime`, per proc(5) -- 1-based field number


def _proc_started_1202ev(pid):
    """Boot-relative start time of `pid`, or None when it cannot be determined.

    None means "cannot tell", never "dead": on a platform without /proc, or for a
    process owned by someone else, the honest answer is that liveness is unknown and
    the caller must not claim the run was abandoned.
    """
    try:
        raw = Path("/proc/%d/stat" % int(pid)).read_text(encoding="utf-8")
        # `comm` is parenthesised and may itself contain spaces and parens, so the
        # fixed-width fields start after the LAST ')'. tail[0] is then field 3.
        tail = raw[raw.rindex(")") + 2:].split()
        return float(tail[_STARTTIME_FIELD_1202EV - 3])
    except Exception:
        return None


def process_liveness_1202ev(usage):
    """"alive" | "gone" | "unknown" for the process that wrote this `usage` block.

    Public because the ledger's readers -- the live monitor, and any post-mortem over
    the run corpus -- need the same answer the resume path needs, and re-deriving it
    per reader is how two readers come to disagree about whether a run is running.
    """
    try:
        pid = (usage or {}).get("pid")
        if not isinstance(pid, int) or pid <= 0:
            return "unknown"          # written before #1202ev, or by another platform
        started = (usage or {}).get("pid_started")
        now = _proc_started_1202ev(pid)
        if now is None:
            # No such process. That is only proof of death if we can read /proc at all;
            # otherwise every run on the box would read as gone.
            return "gone" if Path("/proc/self/stat").exists() else "unknown"
        if not isinstance(started, (int, float)):
            return "unknown"          # a pid we cannot pin to a start time proves nothing
        return "alive" if abs(float(started) - now) < 1.0 else "gone"
    except Exception:
        return "unknown"


class RunBudget:
    """Owns run_budget.json. Constructed with the run's output_dir + a logger."""

    def __init__(self, output_dir, logger):
        self._output_dir = Path(output_dir)
        self._logger = logger
        # #1202cg: what every EARLIER process in this output dir already spent. Computed
        # once, on this process's first write; see _carry_1202cg.
        self._carry_1202cg = None

    def path(self) -> Path:
        return self._output_dir / "run_budget.json"

    def _carry_1202cg_for(self, started_at: float, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Project spend ACROSS resumes.

        This payload is rebuilt from scratch on every write, so a ``--resume`` -- a new
        process over the same output dir -- starts the ledger at zero. r35 is the case:
        the fresh run died having spent $163 by tick 24, the resume's ledger then read
        $0.20, and nothing on disk said the project had cost $163 more than the number an
        operator was looking at. ``ENVGEN_MAX_SPEND_USD`` is likewise a FRESH allowance on
        a resume, not a remainder, which is correct (a new process, an operator setting a
        new cap) but only if the cumulative figure exists somewhere to be read.

        Folded exactly once per process: the carry is computed on the first write, from the
        file the PREVIOUS process left, and then held. Re-reading it on every write would
        add this run's own spend to itself several times a minute. A file whose
        ``usage.started_at`` matches ours was written by this process, so its cumulative is
        already correct and is carried unchanged.

        Best-effort: accounting must never be the reason a run record fails to write, which
        is the same rule the spend block above already follows.
        """
        if self._carry_1202cg is None:
            prior_total, prior_calls, runs, first = 0.0, 0, 0, started_at
            try:
                old = json.loads(self.path().read_text(encoding="utf-8"))
                prev_cum = old.get("cumulative_1202cg") or {}
                same_process = float((old.get("usage") or {}).get("started_at") or 0.0) == float(started_at)
                prior_total = float(prev_cum.get("usd_before_this_run") or 0.0)
                prior_calls = int(prev_cum.get("calls_before_this_run") or 0)
                runs = int(prev_cum.get("runs") or 0)
                first = float(prev_cum.get("first_started_at") or started_at)
                if not same_process:
                    # A previous process's totals become part of the carry.
                    prior_total += float((old.get("llm") or {}).get("usd") or 0.0)
                    prior_calls += int((old.get("llm") or {}).get("calls") or 0)
                    runs += 1
            except Exception:
                pass
            self._carry_1202cg = {
                "usd_before_this_run": round(prior_total, 4),
                "calls_before_this_run": prior_calls,
                "runs": max(1, runs + (0 if runs else 1)),
                "first_started_at": first,
            }
        out = dict(self._carry_1202cg)
        try:
            out["usd_total"] = round(out["usd_before_this_run"]
                                     + float((payload.get("llm") or {}).get("usd") or 0.0), 4)
            out["calls_total"] = (out["calls_before_this_run"]
                                  + int((payload.get("llm") or {}).get("calls") or 0))
        except Exception:
            pass
        return out

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

    def seal_abandoned_predecessor_1202ev(self) -> str:
        """Retire a `running` ledger left by a process that is gone. Returns what it did.

        A killed run leaves `status="running"` forever, because the code that would
        have written a terminal status is exactly the code the kill prevented from
        running. The next process over this output dir is the first thing in a position
        to notice, so it says so before it starts overwriting the evidence.

        Only a PROVEN death seals. A ledger whose writer cannot be identified (written
        before #1202ev, or on a platform with no /proc) stays untouched: mislabelling a
        live run as abandoned would invent the same kind of false certainty this fixes.

        The status and reason are patched in place. Rebuilding the payload would drop
        the predecessor's spend, which _carry_1202cg_for reads on this process's first
        write to keep cumulative cost honest across a resume.
        """
        try:
            path = self.path()
            if not path.is_file():
                return "no ledger"
            data = json.loads(path.read_text(encoding="utf-8"))
            usage = data.get("usage")
            if not isinstance(usage, dict) or str(usage.get("status")) != "running":
                return "not running"
            live = process_liveness_1202ev(usage)
            if live != "gone":
                # "alive" -> a concurrent run, or our own earlier write; "unknown" -> a
                # writer we cannot identify. Neither may be sealed. The pid is compared
                # only AFTER liveness: a bare `pid == os.getpid()` short-circuit would
                # call a ledger ours on the strength of a recycled number alone.
                if live == "alive" and usage.get("pid") == os.getpid():
                    return "ours"
                return live
            usage["status"] = "abandoned"
            usage["terminal_reason"] = (
                "process %s exited without recording an outcome; sealed by pid %d taking "
                "over this output dir" % (usage.get("pid"), os.getpid()))[:_REASON_CAP_1202EB]
            usage["sealed_at_1202ev"] = time.time()
            tmp = path.with_suffix(".json.1202ev")
            tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
            tmp.replace(path)
            if self._logger:
                self._logger.warning("#1202ev: predecessor pid %s left this run marked "
                                     "`running` and is gone -- sealed as `abandoned`",
                                     usage.get("pid"))
            return "sealed"
        except Exception:
            return "error"

    def write_process_wall_1202ez(self, seconds: float) -> None:
        """Stash the run's TOTAL process wall clock for the next write to carry.

        `usage.started_at` means "the origin the wall-clock cap is measured from" (#1196),
        which excludes design-prep and kickoff -- ~60 minutes of it in netflix-r26. Making
        the terminal write agree with that meaning (#1202ez) is right, but it would leave
        nowhere to read how long the run actually took. One field cannot answer both
        questions; that is the mistake #1196 named. So: two fields.

        Set just before the write that should carry it. Held rather than written directly
        so the value lands inside the same atomic payload as the status it belongs to.
        """
        try:
            self._process_wall_1202ez = float(seconds)
        except Exception:
            pass

    def write(self, caps: Dict[str, Any], started_at: float,
              elapsed: float, ticks: int, status: str, reason: str = "") -> None:
        """Persist caps + usage so the live monitor can show budget progress.

        #1202eb: `reason` carries WHY a run reached a non-`finished` status. The status
        word alone repeats the mistake #1202df/#1202ea fixed elsewhere — the framework
        knows the instance and reports only the category. Empty for a clean run, so the
        field appears exactly when there is something to read.
        """
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
                    # #1202ev: who wrote this. See process_liveness_1202ev.
                    "pid": os.getpid(),
                    "pid_started": _proc_started_1202ev(os.getpid()),
                },
            }
            _pw = getattr(self, "_process_wall_1202ez", None)
            if isinstance(_pw, (int, float)):
                # #1202ez: total wall clock INCLUDING design-prep and kickoff, beside the
                # capped window. Absent when nobody set it, so it never claims a
                # measurement that was not taken.
                payload["usage"]["process_wall_sec_1202ez"] = round(float(_pw), 1)
            if reason:
                payload["usage"]["terminal_reason"] = str(reason)[:_REASON_CAP_1202EB]
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
                # #1202cr: the per-phase split beside the total, so a finished run can be
                # asked WHERE its budget went — the question r40-vs-r41 turns on. Capped at
                # 24 labels (costliest first) to keep run_budget.json small; the total in
                # payload["llm"] stays authoritative and is never derived from this.
                try:
                    from utils.llm import llm_usage_by_label_1202cr
                    _bl = llm_usage_by_label_1202cr()
                    if _bl:
                        payload["llm_by_phase_1202cr"] = dict(list(_bl.items())[:24])
                except Exception:
                    pass
                # #1202cw: the census of framework writes onto lane files. `is_lane_owned`
                # measured ~22,000 alternating overwrites across 164 projects and nothing has
                # been able to SEE them since. "declared" is the count the projectors argue
                # for; "refused" should stay empty — a name appearing there is a projector
                # clobbering lane work without having said why.
                try:
                    from .path_routed_workspace import lane_clobbers_1202cw
                    _lc = lane_clobbers_1202cw()
                    if any(_lc.values()):
                        payload["lane_clobbers_1202cw"] = {
                            k: dict(sorted(v.items(), key=lambda kv: -kv[1])[:12])
                            for k, v in _lc.items() if v}
                except Exception:
                    pass
                # #1202cy: which stage used which tools. Capped at the 16 busiest
                # stages and 10 tools each — enough to see an EMPTY stage, which is the
                # question, without turning run_budget.json into a trace.
                try:
                    from utils.llm import stage_tools_1202cy
                    _st = stage_tools_1202cy()
                    if _st:
                        payload["stage_tools_1202cy"] = {
                            k: dict(list(v.items())[:10])
                            for k, v in list(_st.items())[:16]}
                except Exception:
                    pass
                _tb = tool_result_bytes()
                if _tb:
                    payload["tool_result_bytes"] = dict(list(_tb.items())[:12])
                    # #1191: how much the identical-snapshot dedup kept out of the context. Reported
                    # beside the tool attribution so the saving is a measurement, not an estimate.
                    try:
                        from utils.llm import dedup_saved_1191
                        payload["dedup_saved_1191"] = dedup_saved_1191()
                    except Exception:
                        pass
            except Exception:
                pass
            # #1202cg: fold the previous process's spend forward.
            payload["cumulative_1202cg"] = self._carry_1202cg_for(started_at, payload)
            path = self.path()
            tmp = path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            os.replace(tmp, path)
        except Exception as e:
            self._logger.debug("run_budget write failed: %s", e)
