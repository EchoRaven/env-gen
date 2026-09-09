#!/usr/bin/env python
"""
LLM Generator - Main Entry Point

Multi-Agent Environment Generator with:
- Parallel code generation (Database, Backend, Frontend agents)
- Real-time progress events
- Checkpoint system for resume
- Dynamic port allocation
"""

import argparse
import asyncio
import logging
import os
import sys
import json
import shutil
from datetime import datetime
from enum import Enum
from pathlib import Path

# Freeze forensics: the run intermittently FREEZES (all agents go silent at once —
# no pending LLM call, no warnings; an event-loop/lock block somewhere). py-spy
# can't attach (yama ptrace_scope=1, no sudo), so register a signal-triggered
# all-thread stack dump instead: `kill -USR1 <pid>` writes every thread's stack to
# stderr (the run log) — the external watcher sends it before killing a frozen run.
import faulthandler
import signal as _signal
from typing import Optional
_ASYNC_LOOP = [None]  # set by _main_with_loop_capture; read by the USR2 dumper
try:
    faulthandler.register(_signal.SIGUSR1, all_threads=True)

    # SIGUSR2 → dump every asyncio task + coroutine stack. faulthandler (USR1)
    # only shows THREADS — the kickoff-phase freeze (loop alive, every
    # coroutine starved) needs the WEDGED AWAITS.
    def _dump_asyncio_tasks(signum, frame):
        import asyncio as _aio, sys as _sys, traceback as _tb
        loop = _ASYNC_LOOP[0]
        if loop is None:
            print("[USR2] loop not captured yet", file=_sys.stderr, flush=True)
            return
        try:
            tasks = _aio.all_tasks(loop=loop)
        except Exception as exc:
            print(f"[USR2] all_tasks failed: {exc}", file=_sys.stderr, flush=True)
            return
        print(f"[USR2] {len(tasks)} asyncio task(s):", file=_sys.stderr, flush=True)
        for t in tasks:
            try:
                print(f"--- task {t.get_name()} done={t.done()}", file=_sys.stderr, flush=True)
                for fr in t.get_stack(limit=8):
                    _tb.print_stack(fr, limit=1, file=_sys.stderr)
            except Exception:
                pass

    _signal.signal(_signal.SIGUSR2, _dump_asyncio_tasks)
except Exception:
    pass

# Fix #55 (run-40, 2026-07-02): the main process DIED SILENTLY mid-run — no
# exception in the log, no shutdown record, no OOM trace; the USR1/USR2 dumps
# above are MANUAL (someone must signal a live pid) so they can't explain a
# process that is already gone. Automatic crash forensics, all best-effort:
#   * faulthandler.enable(file=...) — a native/hard fault (segfault in a grpc /
#     PIL / event-loop C dep) writes every thread's stack to the crash file as
#     the process dies (stderr under nohup can be lost with the terminal);
#   * sys.excepthook + threading.excepthook — an uncaught Python exception is
#     appended to the SAME file before the interpreter exits;
#   * an atexit marker — "clean interpreter exit" present ⇒ orderly exit;
#     absent + no traceback ⇒ SIGKILL (OOM-killer / external kill), which
#     narrows run-40's class in one read.
# ENVGEN_CRASH_LOG names the file (default envgen_crash.log in the cwd);
# ENVGEN_CRASH_LOG=0/off disables (tests that import this module set a tmp path).
def _forensics_note(msg):  # no-op until armed below; rebound when the file opens
    pass


try:
    _crash_target = os.environ.get("ENVGEN_CRASH_LOG", "envgen_crash.log")
    if _crash_target not in ("0", "off", "false"):
        _crash_file = open(_crash_target, "a", buffering=1)  # kept open: faulthandler writes on the dying fd
        faulthandler.enable(file=_crash_file, all_threads=True)

        def _forensics_note(msg):  # noqa: F811 — armed rebind of the module no-op
            try:
                _crash_file.write(f"[{datetime.utcnow().isoformat()}] {msg} pid={os.getpid()}\n")
                _crash_file.flush()
            except Exception:
                pass

        _forensics_note(f"crash-forensics armed argv={' '.join(sys.argv[:6])}")

        def _crash_note(prefix, etype, evalue, etb):
            import traceback as _tb
            try:
                _crash_file.write(f"[{datetime.utcnow().isoformat()}] {prefix} pid={os.getpid()}\n")
                _tb.print_exception(etype, evalue, etb, file=_crash_file)
                _crash_file.flush()
            except Exception:
                pass

        _prev_excepthook = sys.excepthook

        def _forensic_excepthook(etype, evalue, etb):
            _crash_note("UNCAUGHT EXCEPTION", etype, evalue, etb)
            _prev_excepthook(etype, evalue, etb)

        sys.excepthook = _forensic_excepthook

        import threading as _threading
        _prev_thread_hook = _threading.excepthook

        def _forensic_thread_hook(args):
            _crash_note(f"UNCAUGHT THREAD EXCEPTION ({getattr(args.thread, 'name', '?')})",
                        args.exc_type, args.exc_value, args.exc_traceback)
            # CHAIN the prior hook (review w6x6art4t): without it the default
            # "Exception in thread ..." traceback VANISHES from stderr/run log.
            try:
                _prev_thread_hook(args)
            except Exception:
                pass

        _threading.excepthook = _forensic_thread_hook

        import atexit as _atexit
        _atexit.register(lambda: _forensics_note("clean interpreter exit"))
except Exception:
    pass

# ===== Global JSON Patch to Handle Non-Serializable Objects =====
# This ensures all json.dumps calls in the entire application handle
# Message objects and other non-serializable types gracefully.
# IMPORTANT: Only applies to data serialization, NOT to API requests.

_original_json_dumps = json.dumps
_in_api_call = False  # Flag to detect nested calls

def _safe_json_dumps(obj, **kwargs):
    """Patched json.dumps that handles non-serializable objects."""
    global _in_api_call
    
    # If already using default handler (likely API call), don't interfere
    if 'default' in kwargs and kwargs['default'] is not None:
        return _original_json_dumps(obj, **kwargs)
    
    def default_handler(o):
        # Check the type name to avoid importing the class
        type_name = type(o).__name__
        
        # Skip Message and LLMResponse objects - let them serialize normally
        # These are used in API calls and should keep their structure
        if type_name in ('Message', 'LLMResponse'):
            if hasattr(o, 'to_dict'):
                return o.to_dict()
        
        # For other objects with to_dict, use it
        if hasattr(o, 'to_dict'):
            return o.to_dict()
        
        # Handle objects with __dict__ but avoid complex nested structures
        if hasattr(o, '__dict__'):
            # Only serialize simple objects, not complex nested ones
            d = {}
            for k, v in o.__dict__.items():
                if not k.startswith('_'):
                    if isinstance(v, (str, int, float, bool, type(None), list, dict)):
                        d[k] = v
                    else:
                        d[k] = str(v)
            return d
        
        if isinstance(o, datetime):
            return o.isoformat()
        if isinstance(o, Enum):
            return o.value
        
        # Fallback to string representation
        return str(o)
    
    kwargs['default'] = default_handler
    return _original_json_dumps(obj, **kwargs)

# Apply the monkey patch globally
json.dumps = _safe_json_dumps

# ===== End Global JSON Patch =====

# Add paths for imports
_agents_dir = Path(__file__).parent.parent.parent.absolute()
if str(_agents_dir) not in sys.path:
    sys.path.insert(0, str(_agents_dir))

_llm_generator_dir = Path(__file__).parent.absolute()
if str(_llm_generator_dir) not in sys.path:
    sys.path.insert(0, str(_llm_generator_dir))

from utils.config import LLMConfig, LLMProvider
from utils.model_limits import resolve_max_output_tokens
from multi_agent import Orchestrator


def setup_logging(verbose: bool = False, log_file: Optional[Path] = None):
    """Setup logging configuration.
    
    Args:
        verbose: Enable debug logging
        log_file: Optional path to log file. If provided, logs will be saved to file.
    """
    level = logging.DEBUG if verbose else logging.INFO
    
    fmt = "%(asctime)s [%(levelname).1s] %(name)s: %(message)s"
    date_fmt = "%H:%M:%S"
    
    handlers = [logging.StreamHandler()]
    
    # Add file handler if log_file specified
    if log_file:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_file, encoding='utf-8')
        file_handler.setFormatter(logging.Formatter(fmt, date_fmt))
        handlers.append(file_handler)
    
    logging.basicConfig(
        level=level,
        format=fmt,
        datefmt=date_fmt,
        handlers=handlers,
    )
    
    # Suppress noisy loggers
    for name in ["openai", "httpx", "httpcore", "urllib3", "asyncio", "aiohttp", "playwright"]:
        logging.getLogger(name).setLevel(logging.WARNING)


def reset_output_dir(output_dir: Path) -> None:
    """
    Remove prior generation artifacts for a fresh non-resume run.

    This prevents old specs, app files, checkpoints, and persisted memory from
    contaminating a new generation when reusing the same project name.
    """
    output_dir = Path(output_dir)
    if not output_dir.exists():
        return

    resolved = output_dir.resolve()
    if resolved == Path("/") or len(resolved.parts) < 4:
        raise RuntimeError(f"Refusing to reset suspicious output directory: {resolved}")

    for child in output_dir.iterdir():
        if child.is_dir() and not child.is_symlink():
            shutil.rmtree(child)
        else:
            child.unlink()


def parse_milestones(raw: Optional[str] = None):
    """Parse the --milestones argument into an ordered list of dicts.

    Accepts a path to a JSON file OR an inline JSON string. Returns an ordered
    list of dicts ``{"name": str, "version": str, "description_slice": str}``.
    Returns None when ``raw`` is empty/absent so the orchestrator synthesizes a
    single milestone (one-milestone behavior identical to today).
    """
    if not raw:
        return None

    text = raw
    candidate = Path(raw)
    try:
        if candidate.exists() and candidate.is_file():
            text = candidate.read_text(encoding="utf-8")
    except OSError:
        # Treat as inline JSON if the path probe fails.
        text = raw

    data = json.loads(text)
    if isinstance(data, dict):
        data = [data]
    if not isinstance(data, list):
        raise ValueError(
            "--milestones must parse to a list of milestone dicts (or a single dict)."
        )

    milestones = []
    for i, entry in enumerate(data, start=1):
        if not isinstance(entry, dict):
            raise ValueError(f"--milestones entry #{i} is not an object: {entry!r}")
        milestones.append({
            "name": str(entry.get("name") or f"M{i}"),
            "version": str(entry.get("version") or "1.0.0"),
            "description_slice": str(entry.get("description_slice") or ""),
        })
    return milestones or None


async def main():
    parser = argparse.ArgumentParser(
        description="Multi-Agent Environment Generator"
    )
    
    parser.add_argument("--name", required=True, help="Project name")
    parser.add_argument("--description", default="", help="Project description")
    parser.add_argument("--output", default="./generated", help="Output directory")
    parser.add_argument("--model", default="gpt-4", help="LLM model")
    parser.add_argument("--provider", default="openai",
                       choices=["openai", "openrouter", "google", "anthropic", "azure", "metagen", "local"])
    parser.add_argument("--api-base", dest="api_base", default=None,
                       help="Override the API base URL (e.g. an OpenAI-compatible "
                            "gateway or self-hosted endpoint). Defaults per provider.")
    parser.add_argument("--max-tokens", dest="max_tokens", type=int, default=None,
                       help="Max output tokens per response. Defaults to the "
                            "model's documented cap (resolved from --model).")
    parser.add_argument("--api-version", dest="api_version", default=None,
                       help="Azure OpenAI API version (e.g. 2024-10-21). For "
                            "--provider azure; --model is the deployment name, "
                            "--api-base the Azure endpoint.")
    parser.add_argument("--verbose", action="store_true", help="Verbose output")
    parser.add_argument("--resume", action="store_true", help="Resume from checkpoint")
    # #1202bw: restore points. `--resume` continues from the run's LATEST state, which
    # for a wedged run is the wedge itself; these let an operator rewind first.
    parser.add_argument("--list-snapshots", action="store_true",
                       help="List this run's restore points and exit")
    parser.add_argument("--restore-snapshot", dest="restore_snapshot", default=None,
                       help="Rewind the run directory to the named snapshot and exit "
                            "(the current state is copied to snapshots/.pre-restore-*). "
                            "Pass the literal 'best' to let #1202hx pick the highest-quality "
                            "restore point -- the newest is routinely not it. "
                            "Follow with --resume to continue from it.")
    parser.add_argument("--reference-images", nargs="*", default=[], 
                       help="Reference screenshot paths for design (e.g., screenshot/expedia.png)")
    parser.add_argument("--reference-dir", default=None,
                       help="Directory containing reference screenshots")
    parser.add_argument("--design-input", dest="design_input", default=None,
                       help="Design-Prep input dir with optional references/ docs/ assets/ "
                            "subfolders (real screenshots + docs + real icon/logo/image assets)")
    parser.add_argument("--log", action="store_true",
                       help="Save logs to file (output_dir/logs/generation.log)")
    parser.add_argument("--fresh", dest="fresh", action="store_true", default=None,
                       help="Clear any previous output for this project before generation")
    parser.add_argument("--no-fresh", dest="fresh", action="store_false",
                       help="Reuse the existing output directory for a non-resume run")
    parser.add_argument("--milestones", dest="milestones", default=None,
                       help="Ordered milestone slices: a path to a JSON file OR "
                            "inline JSON. Each entry is "
                            '{"name": str, "version": str, "description_slice": str}. '
                            "If absent, a single milestone is synthesized (behavior "
                            "identical to a one-milestone run).")

    args = parser.parse_args()
    
    output_dir = Path(args.output) / args.name
    # #1202bw: both act on an EXISTING run dir and exit, so they must be handled before
    # the --fresh reset below — which would otherwise delete the very snapshots asked for.
    if args.list_snapshots or args.restore_snapshot:
        from env_generator.llm_generator.multi_agent.runtime.run_snapshot import (
            list_snapshots, restore_snapshot, best_snapshot_1202hx)
        if args.list_snapshots:
            snaps = list_snapshots(output_dir)
            if not snaps:
                print(f'No snapshots under {output_dir}/snapshots')
            # #1202hx: name the one worth restarting from. The listing was ordered by
            # time, and the newest is not the best -- r106's last interval held 1 of 9
            # screens at a 0.34 median.
            _best_1202hx = best_snapshot_1202hx(snaps)
            for s in snaps:
                # #1202di: size never answered "is this worth restoring". A snapshot taken
                # while the app could not boot has judged nothing, and restoring it resumes
                # a run that has never scored a screen — all four of netflix-r43's were like
                # that. `None` prints as "?" because not-measured is not zero.
                _j = s.get("judgments")
                _health = "judged ?" if _j is None else f"judged {_j}"
                if _j == 0:
                    _health += " ⚠ NOTHING SCORED"
                if s.get("plateau"):
                    _health += f", plateau {s['plateau']}"
                if s.get("usd") is not None:
                    _health += f", ${s['usd']:.0f}"
                if s.get("ticks") is not None:
                    _health += f", tick {s['ticks']}"
                # #1202hx: the quality that decides whether restoring is ahead or behind.
                if s.get("budget_left_s") is not None:
                    _health += f", budget {s['budget_left_s']/60:.0f}min left"
                if s.get("screens_total"):
                    _health += (f", screens {s['screens_pass']}/{s['screens_total']}"
                                f" med {s.get('visual_med') or 0:.2f}")
                _fw = s.get("fwval_failed")
                if _fw:
                    _health += f", blocked on {','.join(_fw[:3])}"
                elif _fw == []:
                    _health += ", no blocking checks"
                print(f"{s['name']:<34} {s.get('kind',''):<10} "
                      f"{s.get('files',0):>5} files  {s.get('bytes',0)/1e6:>7.1f} MB  "
                      f"{_health}"
                      f"{'   <-- BEST STATE TO RESUME FROM' if s['name'] == _best_1202hx else ''}")
            if _best_1202hx:
                print(f"\n#1202hx best restore point: {_best_1202hx}\n"
                      f"  --restore-snapshot best   then re-run with --resume"
                      f"   (literal 'best' resolves to {_best_1202hx}; #1202it)")
        else:
            # #1202it: `--restore-snapshot best` resolves to #1202hx's ranking instead of
            # making the operator read a listing and copy a timestamp back in. The ranking
            # already existed and was only ever PRINTED -- so the one step that decides
            # whether a resume starts ahead or behind was the one step left manual, and the
            # newest snapshot (the obvious guess) is routinely the worst: r106's last
            # interval held 1 of 9 screens at a 0.34 median.
            _want = args.restore_snapshot
            if str(_want).strip().lower() == "best":
                _want = best_snapshot_1202hx(list_snapshots(output_dir))
                if not _want:
                    print("No snapshot to restore: nothing under "
                          f"{output_dir}/snapshots has a readable ledger.")
                    return 1
                print(f"#1202hx picked {_want} as the best restore point.")
            res = restore_snapshot(output_dir, _want)
            if res['ok']:
                print(f"Restored {len(res['restored'])} files from "
                      f"{_want}; previous state saved to {res['backup']}")
                # #1202ey: say what a restore does NOT rewind. `app/` and `worktrees/` are
                # git and are deliberately left alone -- rewinding them would discard real
                # work, and the history is append-only so nothing is lost by not touching
                # it. But an operator restoring to escape a wedge reasonably reads
                # "Restored N files" as "the run went back", and then finds the wedged code
                # still there. Saying it costs one line; the same silence has already cost
                # this project several investigations that began from the wrong premise.
                print('Coordination state only: app/ and worktrees/ are git and are NOT '
                      'rewound, so the code stays as the abandoned attempt left it.')
                print('Continue with: --resume')
            else:
                print(f"Restore FAILED: {res['error']}")
                return 1
        return 0
    if args.fresh is None:
        args.fresh = not args.resume
    if args.resume and args.fresh:
        raise RuntimeError("Cannot use --resume and --fresh together.")
    if args.fresh:
        reset_output_dir(output_dir)

    # Setup log file path if --log is specified
    log_file = output_dir / "logs" / f"generation_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log" if args.log else None
    
    setup_logging(args.verbose, log_file)
    logger = logging.getLogger("main")
    
    if log_file:
        logger.info(f"Logging to file: {log_file}")
    
    # Get provider and API key
    provider_map = {
        "openai": (LLMProvider.OPENAI, "OPENAI_API_KEY"),
        "openrouter": (LLMProvider.OPENROUTER, "OPENROUTER_API_KEY"),
        "google": (LLMProvider.GOOGLE, "GOOGLE_API_KEY"),
        "anthropic": (LLMProvider.ANTHROPIC, "ANTHROPIC_API_KEY"),
        "azure": (LLMProvider.AZURE, "AZURE_OPENAI_API_KEY"),
        "metagen": (LLMProvider.METAGEN, "METAGEN_API_KEY"),
        "local": (LLMProvider.LOCAL, None),
    }
    
    provider_enum, api_key_env = provider_map.get(args.provider, (LLMProvider.OPENAI, "OPENAI_API_KEY"))
    
    api_key = None
    if api_key_env:
        api_key = os.environ.get(api_key_env) or os.environ.get("GEMINI_API_KEY")
        if not api_key:
            print(f"Error: {api_key_env} environment variable not set")
            sys.exit(1)
    
    # Max output tokens: explicit --max-tokens wins, else the model's
    # documented cap (resolved by family prefix, safe 8192 fallback).
    max_tokens = args.max_tokens or resolve_max_output_tokens(args.model)
    
    extra_params = {}
    if args.api_version:
        extra_params["api_version"] = args.api_version

    llm_config = LLMConfig(
        provider=provider_enum,
        model_name=args.model,
        api_key=api_key,
        api_base=args.api_base,
        temperature=0.7,
        max_tokens=max_tokens,
        # 240s ≈ 5× the worst observed call latency (52.8s on gemini-3.1-pro with
        # 62K-token prompts). The old 1800s meant one wedged HTTP call froze the
        # whole run for 30 minutes; 240s turns a hang into a quick retry.
        timeout=240,
        extra_params=extra_params,
    )
    
    # output_dir already defined above for logging
    output_dir.mkdir(parents=True, exist_ok=True)
    
    logger.info(f"Starting multi-agent generation: {args.name}")
    logger.info(f"Output directory: {output_dir}")
    logger.info(f"Model: {args.model} ({args.provider})")
    
    # Collect reference MATERIALS — images plus documents (HTML pages, PDFs,
    # markdown/plain-text feature docs, MCP tool docs). The orchestrator
    # classifies them and compiles a reference spec at run start.
    reference_images = list(args.reference_images)
    if args.reference_dir:
        ref_dir = Path(args.reference_dir)
        if ref_dir.exists():
            for ext in ("*.png", "*.jpg", "*.jpeg", "*.webp",
                        "*.html", "*.htm", "*.pdf", "*.md", "*.markdown",
                        "*.txt", "*.rst"):
                reference_images.extend([str(p) for p in ref_dir.glob(ext)])

    # Design-Prep: --design-input's references/ + docs/ also feed the existing reference
    # pipeline (so back-compat consumers keep working); the assets/ folder is consumed by
    # the Design-Prep phase itself (Task 5) via the design_input dir passed to the orchestrator.
    if args.design_input:
        from env_generator.llm_generator.multi_agent.runtime.design_prep import resolve_design_input
        resolved = resolve_design_input(args.design_input, None, [])
        for p in resolved["references"] + resolved["docs"]:
            if p not in reference_images:
                reference_images.append(p)


    if reference_images:
        logger.info(f"Reference images: {len(reference_images)} files")
        for img in reference_images:
            logger.info(f"  - {img}")
    
    orchestrator = Orchestrator(
        llm_config=llm_config,
        output_dir=output_dir,
        name=args.name,
        verbose=args.verbose,
        reference_images=reference_images,
        design_input=args.design_input,
    )
    
    requirements = []
    if args.description:
        requirements.append(args.description)

    milestones = parse_milestones(args.milestones)
    if milestones:
        logger.info(f"Milestones: {len(milestones)} slices "
                    f"({', '.join(m['version'] for m in milestones)})")

    result = await orchestrator.run(
        goal=args.description or f"Build a {args.name} web application",
        requirements=requirements,
        resume=args.resume,
        milestones=milestones,
    )
    
    # #1202as: hand back the per-lane worktree checkouts. `git worktree add` had no
    # counterpart anywhere in the pipeline, so 24 byte-identical copies of a 186MB app/
    # survived every run (tiktok-web-r74: 4.4GB of its 4.7GB). Across the corpus that is
    # 93GB of 138GB, and it is why /data reached 99%. Nothing is lost: `remove` runs
    # without --force so a dirty lane keeps its files, and branches are left alone so
    # every commit stays reachable for forensics.
    try:
        from multi_agent.runtime.worktree_reclaim import reclaim_run_worktrees_1202as
        _wt = reclaim_run_worktrees_1202as(output_dir)
        if _wt.get("bytes_reclaimed"):
            print(f"  Disk: reclaimed {_wt['bytes_reclaimed'] / 1073741824:.1f} GB from "
                  f"{len(_wt['removed'])} lane worktrees"
                  + (f" ({len(_wt['kept'])} kept — uncommitted work)" if _wt.get("kept") else ""))
    except Exception:
        pass

    print("\n" + "=" * 60)
    print("GENERATION COMPLETE")
    print("=" * 60)
    print(f"  Status: {'SUCCESS' if result.success else 'FAILED'}")
    print(f"  Phases: {', '.join(result.phases_completed)}")
    print(f"  Issues: {result.issues_found} found, {result.issues_fixed} fixed")
    # #1163: what did this run COST. Printed here because the number was previously
    # recoverable only by grepping `prompt_tokens=` out of the log afterwards, which is
    # how the 2.4x spread between two DELIVERING runs (r13 6362 calls, r14 2626) stayed
    # invisible. The cache line is deliberate: 91-92% of input tokens are hits, so
    # protecting that rate matters more than shaving rounds.
    try:
        from utils.llm import llm_usage
        _u = llm_usage()
        if _u.get("calls"):
            _hit = (100 * _u["cached"] // _u["prompt"]) if _u.get("prompt") else 0
            print(f"  LLM: {_u['calls']:,} calls | in {_u['uncached']:,} uncached "
                  f"+ {_u['cached']:,} cached ({_hit}% hit) | out {_u['completion']:,}")
            print("  Cost: $%.2f" % _u["usd"] if _u.get("priced") else
                  "  Cost: not priced (set ENVGEN_PRICE_IN_PER_M / _CACHED_PER_M / _OUT_PER_M)")
    except Exception:
        pass
    print(f"  Duration: {result.duration:.1f}s")
    print(f"  Output: {result.project_path}")
    
    # Show ports used
    status = orchestrator.get_status()
    print(f"\n  Ports allocated:")
    print(f"    API: {status['ports']['api']}")
    print(f"    UI: {status['ports']['ui']}")
    print("=" * 60)
    
    if result.success:
        print("\nNext Steps:")
        print(f"  1. cd {result.project_path}")
        print(f"  2. docker-compose -f docker/docker-compose.yml up --build")
        print(f"  3. Open http://localhost:{status['ports']['ui']}")
    
    return 0 if result.success else 1


if __name__ == "__main__":
    async def _main_with_loop_capture():
        # expose the running loop to the SIGUSR2 asyncio-task dumper
        try:
            _ASYNC_LOOP[0] = asyncio.get_running_loop()
        except Exception:
            pass
        # The watchdog (finally) must force-exit with the code main() ACTUALLY
        # returned: a successful generation (release cut, delivery gate passed)
        # whose post-delivery asyncio cleanup hangs on leftover resident-lane tasks
        # should still exit 0 — not be reported a failure (run #11: M1 cut v1.0.0,
        # gate passed, main() returned 0, yet the watchdog forced exit 7).
        _rc_holder = [7]
        try:
            rc = await main()
            print(f"[main-exit] main() returned {rc!r}", file=sys.stderr, flush=True)
            _rc_holder[0] = rc if isinstance(rc, int) else 0
            return rc
        except BaseException as exc:
            # EVIDENCE (2026-06-11 freeze post-mortem): a silent main() exit at
            # M2 kickoff left only un-cancellable leftovers and asyncio.run's
            # shutdown hung forever in _cancel_all_tasks. Every exit path now
            # leaves a trace.
            import traceback as _tb
            print(f"[main-exit] main() raised {type(exc).__name__}: {exc}",
                  file=sys.stderr, flush=True)
            _tb.print_exc(file=sys.stderr)
            raise
        finally:
            # ABSOLUTE shutdown bound: asyncio.run's cleanup (cancel+gather of
            # leftover tasks) has hung indefinitely (USR2 dump: 4 leftover
            # tasks never finish after cancel). A daemon timer guarantees the
            # process exits ≤120s after main() ends, no matter what.
            import threading as _th, os as _os
            def _force_exit():
                print(f"[main-exit] shutdown watchdog fired — forcing exit "
                      f"(rc={_rc_holder[0]})", file=sys.stderr, flush=True)
                # os._exit skips atexit — without this note a SUCCESSFUL run
                # that exits via the watchdog reads as SIGKILL/OOM in the
                # crash log (review w6x6art4t: the #55 decode would mislead).
                _forensics_note(f"shutdown-watchdog exit rc={_rc_holder[0]} "
                                "(result durable; asyncio cleanup hung)")
                _os._exit(_rc_holder[0])
            # On success the result (release/commit) is already durable, so a hung
            # cleanup needn't wait the full safety bound — exit promptly; keep the
            # long bound for the unknown/failure case.
            _t = _th.Timer(20.0 if _rc_holder[0] == 0 else 120.0, _force_exit)
            _t.daemon = True
            _t.start()

    sys.exit(asyncio.run(_main_with_loop_capture()))
