"""Reference MATERIALS — beyond screenshots.

Users specify the target app with whatever they have: UI screenshots, HTML
pages, PDF documents, markdown/plain-text feature write-ups, MCP tool docs,
or free-form text typed into the run request. This module makes all of them
first-class references:

  1. ``classify_references`` splits a mixed list into images vs documents.
  2. ``extract_text`` reads a document (md/txt/html/pdf) to plain text.
  3. ``compile_reference_spec`` runs ONCE at run start with the RUN'S OWN
     selected model: it reads every material and emits a machine-usable spec —
     required screens, required endpoints, required MCP tools, entities, and
     acceptance criteria.
  4. ``gates_from_spec`` turns the spec into deliverability gates in the
     existing ``user_gates`` format (endpoint_exists / mcp_tool_exists), so the
     compiled requirements are ENFORCED at delivery, not just suggested.

The spec is also written to ``design/reference_spec.json`` (and the documents
copied under ``design/references/``) so every lane can read the same compiled
ground truth during kickoff and implementation.
"""

from __future__ import annotations

import logging
from typing import Optional  # noqa: E402  (used above the file's own typing import)

import base64
import json
import os as _os
import os
import re

# Milestone COUNT is user-controlled, not capped. The ENVGEN_MILESTONES
# hyperparameter (unset by default) lets the caller steer how many milestones the
# planner produces — no artificial ceiling:
#   ENVGEN_MILESTONES="5"    → FORCE exactly 5 milestones (hard constraint).
#   ENVGEN_MILESTONES="3-5"  → RECOMMEND ~3-5 (soft guidance; planner may deviate).
#   unset / ""               → FREE: the planner chooses K itself, no cap.
# (Was a hard data[:6] truncation that silently dropped a complex task's later
# phases even though the planner instructions say "choose K yourself".)
def _milestone_target() -> "Tuple[str, Optional[int], Optional[int]]":
    """Parse ENVGEN_MILESTONES → (mode, lo, hi). mode ∈ {force, recommend, free}."""
    raw = (os.environ.get("ENVGEN_MILESTONES") or "").strip()
    if not raw:
        return ("free", None, None)
    m = re.fullmatch(r"(\d+)\s*-\s*(\d+)", raw)
    if m:
        lo, hi = int(m.group(1)), int(m.group(2))
        if lo > hi:
            lo, hi = hi, lo
        return ("recommend", max(1, lo), max(1, hi))
    if raw.isdigit() and int(raw) >= 1:
        n = int(raw)
        return ("force", n, n)
    return ("free", None, None)  # unparseable → free


def _milestone_count_guidance() -> str:
    """Prompt fragment steering the planner's milestone COUNT per the hyperparameter."""
    mode, lo, hi = _milestone_target()
    if mode == "force":
        return (f"\n\n## MILESTONE COUNT — HARD CONSTRAINT\nProduce EXACTLY {lo} "
                f"milestone(s) — no more, no fewer. Partition the build to fit {lo} "
                f"coherent phases.")
    if mode == "recommend":
        span = f"{lo}" if lo == hi else f"{lo}-{hi}"
        return (f"\n\n## MILESTONE COUNT — RECOMMENDATION\nAim for about {span} "
                f"milestone(s). Deviate only if the task clearly needs to.")
    return ""  # free: planner decides, no guidance, no cap
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple

_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
_DOC_EXTS = {".md", ".markdown", ".txt", ".html", ".htm", ".pdf", ".rst"}

# Per-document and total budgets for the compile prompt (chars of extracted
# text). Generous but bounded — a 300-page PDF must not blow up the call.
_DOC_CHAR_BUDGET = 24_000
_TOTAL_CHAR_BUDGET = 96_000
_MAX_IMAGES_IN_COMPILE = 6
# Per-screen component DECOMPOSITION (material-prep) caps. The spec-compile cap
# (6) is a single-multimodal-call budget; decomposition is INDEPENDENT one-call-
# per-screen, so it must cover EVERY reference screen (a run with 9 pages whose
# spec stopped at 6 left 3 screens with no measured-color build spec → those
# pages can't be built to the reference). Bound how many run AT ONCE so a large
# reference set (running concurrently with the spec compile) never rate-limits.
_MAX_DECOMPOSE_IMAGES = 24
_DECOMPOSE_CONCURRENCY = 6


def _spread_sample_648(seq, k):
    """#648 — spend the compile's image budget ACROSS the reference set, not on its head.

    This was `reference_images[:6]`, and the list arrives in `Path.glob` order, which on every
    kept run equals alphabetical order (verified: the real first six match the sorted first six
    in 45 of 45). Every run ships **20** references, so the cap binds every time and always cuts
    at the same place — the same six screens reach the design-system compile in all 45 runs:
    account_menu, browse_by_languages, browse_home, browse_home_rows, card_hover_preview,
    card_preview. The other fourteen — login, player, title_detail, games, genre_category,
    movies, shows, my_list, new_and_popular, landing — have never informed the global tokens in
    any run.

    An alphabetical cut is not a neutral one. Classified against the corpus:

        all references            532 page / 328 overlay      -> overlay 36%
        the six the compile saw   111 page / 147 overlay      -> overlay 54%

    i.e. more than half the global design-token budget was spent on modals and hover cards. A
    strided sample inverts it to 180 page / 90 overlay — 33% overlay, matching the corpus — and
    reaches `player` and `games`, two of the screens the visual gate keeps failing.

    Striding rather than classifying because the classification (`load_screen_classifications`)
    reads design_system.json, which is this compile's OUTPUT: it does not exist yet here.
    Deterministic, order-preserving, and free of any product vocabulary.
    """
    seq = list(seq)
    if k <= 0:
        return []
    if len(seq) <= k:
        return seq
    step = len(seq) / k
    return [seq[min(int(i * step), len(seq) - 1)] for i in range(k)]


def classify_references(paths: List[Any]) -> Dict[str, List[str]]:
    """Split a mixed reference list into {"images": [...], "docs": [...]}.
    Unknown extensions and missing files are dropped (reported by caller)."""
    images: List[str] = []
    docs: List[str] = []
    for raw in paths or []:
        p = Path(raw)
        if not p.is_file():
            continue
        ext = p.suffix.lower()
        if ext in _IMAGE_EXTS:
            images.append(str(p))
        elif ext in _DOC_EXTS:
            docs.append(str(p))
    return {"images": images, "docs": docs}


def _strip_html(html: str) -> str:
    html = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", html)
    html = re.sub(r"(?s)<!--.*?-->", " ", html)
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"&nbsp;?", " ", text)
    return re.sub(r"[ \t]{2,}", " ", text)


def extract_text(path: Any, max_chars: int = _DOC_CHAR_BUDGET) -> str:
    """Plain text of a reference document. Best-effort — an unreadable file
    returns a one-line error marker rather than raising."""
    p = Path(path)
    ext = p.suffix.lower()
    try:
        if ext == ".pdf":
            from pypdf import PdfReader  # lazy: optional dep
            reader = PdfReader(str(p))
            parts: List[str] = []
            total = 0
            for page in reader.pages:
                t = page.extract_text() or ""
                parts.append(t)
                total += len(t)
                if total >= max_chars:
                    break
            text = "\n".join(parts)
        elif ext in (".html", ".htm"):
            text = _strip_html(p.read_text(encoding="utf-8", errors="ignore"))
        else:
            text = p.read_text(encoding="utf-8", errors="ignore")
    except Exception as exc:
        return f"[unreadable reference {p.name}: {exc}]"
    text = text.strip()
    return text[:max_chars] + ("\n…[truncated]" if len(text) > max_chars else "")


def stage_reference_docs(docs: List[str], output_dir: Any) -> List[str]:
    """Copy reference documents into ``<output_dir>/design/references/`` so the
    lanes can read them with their normal file tools (the originals live
    outside the workspace). Returns the staged relative paths."""
    staged: List[str] = []
    if not docs:
        return staged
    dest_dir = Path(output_dir) / "design" / "references"
    dest_dir.mkdir(parents=True, exist_ok=True)
    for d in docs:
        src = Path(d)
        try:
            dest = dest_dir / src.name
            dest.write_bytes(src.read_bytes())
            staged.append(str(Path("design") / "references" / src.name))
        except Exception:
            continue
    return staged


# ---------------------------------------------------------------------------
# Spec compilation (one call with the run's selected model)
# ---------------------------------------------------------------------------
_COMPILE_INSTRUCTIONS = """You are compiling the REFERENCE SPECIFICATION for an app-generation pipeline.
You are given the user's reference materials for the target product: UI
screenshots (images), and/or documents (feature write-ups, HTML page text, PDF
docs, MCP tool documentation), and the raw requirements text.

Extract a precise, buildable specification. Only include what the materials
actually support — do not invent. Respond with ONLY a JSON object:
{
  "screens":   [{"name": "<snake_case>", "route_hint": "/<path>", "must_have": ["<visible component/feature>", ...]}, ...],
  "endpoints": [{"method": "GET|POST|PUT|PATCH|DELETE", "path": "/api/...", "purpose": "<one line>"}, ...],
  "entities":  [{"name": "<table_snake_case>", "fields": ["<column>", ...]}, ...],
  "mcp_tools": [{"name": "<tool_name>", "purpose": "<one line>", "endpoint": "<METHOD /api/... — the endpoint (from your endpoints list) this tool wraps>"}, ...],
  "acceptance": ["<machine-checkable acceptance criterion>", ...]
}
Rules: endpoint paths start with /api/ (auth endpoints with /auth/); screens
must be real screens depicted or described; mcp_tools ONLY if the materials
document MCP tools; keep every list deduplicated."""


def _parse_spec(text: str) -> Dict[str, Any]:
    m = re.search(r"\{.*\}", text or "", re.DOTALL)
    if not m:
        return {}
    try:
        data = json.loads(m.group(0))
    except Exception:
        return {}
    if not isinstance(data, Mapping):
        return {}
    spec: Dict[str, Any] = {}
    for key in ("screens", "endpoints", "entities", "mcp_tools", "acceptance"):
        items = data.get(key)
        spec[key] = [i for i in items if isinstance(i, (Mapping, str))] if isinstance(items, list) else []
    return spec


_SPEC_LIST_KEYS = ("screens", "endpoints", "entities", "mcp_tools", "acceptance")


# #818: measured over all 150 corpus reference_specs. The other four briefing sections sit far
# under their caps (screens 206, endpoints 395, entities 100, mcp_tools 0 — medians); `acceptance`
# is the only one that overflows, and it overflows in 150 of 150 runs: median 2,156, max 3,202
# against a 1,500 cut. 4000 clears the observed maximum with ~25% margin.
# #965: re-measured at 154 specs — netflix-web-r155 came in at 4,079 chars / 36 criteria, 27% over
# the previous corpus max, so the #818 budget went from 25% headroom to binding and dropped a
# criterion. Same rule, new maximum: 5100 clears 4,079 with ~25% margin. This constant is a
# TREADMILL by construction — each richer app resets the maximum — so the paired corpus test is
# the tripwire that forces the re-measurement rather than letting the drop go quiet.
_ACCEPTANCE_BUDGET_818 = 5100


def _acceptance_line_818(acceptance) -> str:
    """The acceptance criteria, cut on an ITEM boundary and never silently.

    These are the machine-checkable criteria the run is judged against, and a mid-sentence cut at
    1,500 chars removed the tail of them from every briefing in the corpus — 150 of 150. Same
    shape as #817 one artefact over: a cap that was never sized against the thing it caps.
    """
    items = [str(x) for x in (acceptance or [])]
    out = " | ".join(items)
    if len(out) <= _ACCEPTANCE_BUDGET_818:
        return out
    kept: List[str] = []
    n = 0
    for it in items:
        if n + len(it) + 3 > _ACCEPTANCE_BUDGET_818:
            break
        kept.append(it)
        n += len(it) + 3
    dropped = len(items) - len(kept)
    logging.getLogger(__name__).warning(
        "reference briefing: %d of %d acceptance criteria dropped (%d chars over the %d "
        "budget) — the briefing states only the first %d, so a lane reading it cannot see the "
        "rest.", dropped, len(items), len(out), _ACCEPTANCE_BUDGET_818, len(kept))
    return " | ".join(kept) + f" | … and {dropped} more acceptance criterion(s) — see " \
                              f"design/reference_spec.json"


def _spec_nonempty(spec: Mapping[str, Any]) -> bool:
    """A spec is usable when it carries at least one buildable signal (the
    callers' own emptiness test — acceptance criteria alone don't count)."""
    return bool(spec) and any(
        spec.get(k) for k in ("screens", "endpoints", "entities", "mcp_tools"))


def _merge_specs(specs: List[Mapping[str, Any]]) -> Dict[str, Any]:
    """Union the per-image/per-doc partial specs into one, deduping each list by
    a stable identity (name / path+method / verbatim string). Used by the
    per-image fallback so N small compiles reassemble into one spec."""
    merged: Dict[str, Any] = {k: [] for k in _SPEC_LIST_KEYS}
    seen: Dict[str, set] = {k: set() for k in _SPEC_LIST_KEYS}
    for sp in specs:
        if not isinstance(sp, Mapping):
            continue
        for k in _SPEC_LIST_KEYS:
            for item in (sp.get(k) or []):
                if isinstance(item, Mapping):
                    key = (str(item.get("name") or item.get("path") or "")
                           + "|" + str(item.get("method") or "")).strip().lower()
                else:
                    key = str(item).strip().lower()
                if not key or key in seen[k]:
                    continue
                seen[k].add(key)
                merged[k].append(item)
    return merged


async def _compile_call(llm: Any, parts: List[Dict[str, Any]]) -> Dict[str, Any]:
    """One multimodal chat → parsed partial spec ({} on any failure)."""
    from utils.llm import Message
    try:
        client = getattr(llm, "_client", llm)
        resp = await client.chat([Message.user_multimodal(parts)],
                                 temperature=0.0, max_tokens=8000)
        return _parse_spec(getattr(resp, "content", "") or "")
    except Exception:
        return {}


async def compile_reference_spec(
    llm: Any,
    reference_images: List[str],
    reference_docs: List[str],
    raw_requirements: str = "",
) -> Dict[str, Any]:
    """Compile the structured reference spec from the run's reference materials.

    Fast path: ONE combined multimodal call (all docs + images) — what
    gpt-class models handle in a single shot. Fallback (2026-06-13): if the
    combined call yields nothing usable — observed with gemini-3.x, which
    reliably returns ``MALFORMED_FUNCTION_CALL`` on a large 6-image multimodal
    request, so the reference design guidance was silently lost — recompile
    PER-IMAGE (plus one text-only call for docs/requirements) and merge. The
    smaller calls succeed where the combined one malforms. Returns {} only when
    there is nothing to compile or every call fails (callers treat the spec as
    optional enrichment, never a blocker)."""
    if not reference_images and not reference_docs and not raw_requirements:
        return {}

    # Shared text context (instructions + raw requirements + documents) — reused
    # verbatim by both the combined call and every per-image fallback call.
    text_parts: List[Dict[str, Any]] = [{"type": "text", "text": _COMPILE_INSTRUCTIONS}]
    if raw_requirements:
        text_parts.append({"type": "text",
                           "text": "\n## RAW REQUIREMENTS\n" + str(raw_requirements)[:16_000]})
    total = 0
    for d in reference_docs or []:
        text = extract_text(d)
        total += len(text)
        if total > _TOTAL_CHAR_BUDGET:
            text_parts.append({"type": "text",
                               "text": f"\n[further documents omitted for budget: {Path(d).name} …]"})
            break
        text_parts.append({"type": "text",
                           "text": f"\n## DOCUMENT: {Path(d).name}\n{text}"})

    # Per-image part pairs (label + image), built once.
    image_parts: List[List[Dict[str, Any]]] = []
    for img in _spread_sample_648(reference_images or [], _MAX_IMAGES_IN_COMPILE):
        try:
            b64 = base64.b64encode(Path(img).read_bytes()).decode()
        except Exception:
            continue
        image_parts.append([
            {"type": "text", "text": f"\n## SCREENSHOT: {Path(img).stem}"},
            {"type": "image_url",
             "image_url": {"url": f"data:image/png;base64,{b64}", "detail": "high"}},
        ])

    # FAST PATH: one combined call.
    combined = await _compile_call(
        llm, text_parts + [p for pair in image_parts for p in pair])
    if _spec_nonempty(combined):
        return combined

    # FALLBACK: per-image (+ one text-only call for docs/requirements), then
    # merge. Run them CONCURRENTLY — the calls are independent, and Gemini's
    # per-call latency is ~50s (it is a thinking model), so a sequential fallback
    # over 6 screenshots costs minutes and can miss the window where the spec
    # feeds kickoff. gather() collapses that to ~one call's latency.
    if not image_parts:
        return combined  # nothing to chunk — the combined call already covered it
    import asyncio
    jobs = [_compile_call(llm, text_parts)]  # docs/requirements only
    jobs += [_compile_call(llm, text_parts + pair) for pair in image_parts]
    results = await asyncio.gather(*jobs, return_exceptions=True)
    partials = [r for r in results if isinstance(r, dict)]
    merged = _merge_specs(partials)
    return merged if _spec_nonempty(merged) else {}


# ---------------------------------------------------------------------------
# Gates from the spec (existing user_gates machinery — enforced at delivery)
# ---------------------------------------------------------------------------
def gates_from_spec(spec: Mapping[str, Any], max_gates: int = 80) -> List[Dict[str, Any]]:
    """Deliverability gates derived from the compiled spec, in the
    ``user_gates`` format. endpoint_exists per required endpoint and
    mcp_tool_exists per documented MCP tool — the compiled requirements become
    enforced contract, not advisory text."""
    gates: List[Dict[str, Any]] = []
    seen: set = set()
    for ep in spec.get("endpoints") or []:
        if not isinstance(ep, Mapping):
            continue
        method = str(ep.get("method") or "").strip().upper()
        path = str(ep.get("path") or "").strip()
        if method not in ("GET", "POST", "PUT", "PATCH", "DELETE") or not path.startswith("/"):
            continue
        key = f"{method} {path}"
        if key in seen:
            continue
        seen.add(key)
        gates.append({
            "type": "endpoint_exists",
            "name": f"ref_spec: {key}",
            "params": {"method": method, "path": path},
            "source": "reference_spec",
        })
    for tool in spec.get("mcp_tools") or []:
        if not isinstance(tool, Mapping):
            continue
        name = str(tool.get("name") or "").strip()
        if not name or f"mcp {name}" in seen:
            continue
        seen.add(f"mcp {name}")
        gates.append({
            "type": "mcp_tool_exists",
            "name": f"ref_spec: mcp tool {name}",
            "params": {"name": name},
            "source": "reference_spec",
        })
    return gates[:max_gates]


def merge_user_gates(workspace: Any, new_gates: List[Dict[str, Any]]) -> int:
    """Append generated gates into ``<workspace>/.user_gates.json`` (the store
    ``deliver_project_call`` evaluates), de-duplicated by gate name. Gates from
    earlier compiles (source == reference_spec) are replaced wholesale so a
    re-compile never accretes stale gates. Returns the number now present from
    this source."""
    path = Path(workspace) / ".user_gates.json"
    try:
        existing = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
        if not isinstance(existing, list):
            existing = []
    except Exception:
        existing = []
    kept = [g for g in existing if not (isinstance(g, Mapping) and g.get("source") == "reference_spec")]
    names = {g.get("name") for g in kept if isinstance(g, Mapping)}
    added = [g for g in new_gates if g.get("name") not in names]
    path.write_text(json.dumps(kept + added, indent=2) + "\n", encoding="utf-8")
    return len(added)


def spec_summary_for_requirements(spec: Mapping[str, Any]) -> str:
    """Compact text block appended to the requirements the kickoff sees, so the
    lanes design against the compiled spec from the first turn."""
    if not spec or not any(spec.get(k) for k in ("screens", "endpoints", "entities", "mcp_tools")):
        return ""
    lines = ["\n\n## REFERENCE SPEC (compiled from the user's reference materials — binding)"]
    if spec.get("screens"):
        lines.append("Screens: " + "; ".join(
            f"{s.get('name')}({s.get('route_hint', '?')})" for s in spec["screens"]
            if isinstance(s, Mapping))[:1500])
    if spec.get("endpoints"):
        lines.append("Required endpoints: " + "; ".join(
            f"{e.get('method')} {e.get('path')}" for e in spec["endpoints"]
            if isinstance(e, Mapping))[:2000])
    if spec.get("entities"):
        lines.append("Entities: " + "; ".join(
            f"{e.get('name')}[{', '.join(map(str, (e.get('fields') or [])[:10]))}]"
            for e in spec["entities"] if isinstance(e, Mapping))[:2000])
    if spec.get("mcp_tools"):
        lines.append("Required MCP tools: " + "; ".join(
            str(t.get("name")) for t in spec["mcp_tools"] if isinstance(t, Mapping))[:800])
    if spec.get("acceptance"):
        lines.append("Acceptance: " + _acceptance_line_818(spec["acceptance"]))
    lines.append("Full spec: design/reference_spec.json; documents: design/references/.")
    return "\n".join(lines)


_AGENT_NOTES = """# Agent Notes — conventions for this workspace (machine-authored, read first)

## Contract & response shapes (FIXED — code to them exactly)
- single resource -> {"item": {...all columns...}}; list -> {"items": [...], "total": N};
  created (POST) -> {"item": {...new row with id...}}; deleted -> {"item": {"id": ..., "deleted": true}};
  error -> {"detail": "..."} with the HTTP status.
- Every /api/ route requires `Authorization: Bearer <token>`; missing/invalid -> 401.
  POST /auth/register | /auth/login -> {"access_token": ...}.
- The backend app (models/handlers/auth/Dockerfile) is REGENERATED from the registered
  contract (registryhub_register_endpoint / registryhub_register_table). Spend effort on the
  contract, not on hand-written app scaffolding.

## Ground truth files
- design/reference_spec.json — compiled spec from the user's reference materials
  (screens / endpoints / entities / mcp_tools / acceptance). BINDING: spec endpoints
  and MCP tools are deliverability gates.
- design/references/ — the user's reference documents, verbatim.
- design/component_specs/<screen>.json — PRE-COMPUTED per-component build spec for each
  reference screen (the framework decomposed every reference BEFORE you woke): named
  components, each with its region + role + state + MEASURED background/accent hex. Build
  each component to THESE colors — they are sampled from the reference, not guessed. If a
  screen has no spec here, run decompose_reference yourself.
- Reference images: list_reference_images / view_image.

## Working discipline
- LARGE tool-call payloads are unreliable: write big JSON to a file with several
  small write/edit calls, then pass the file path (e.g. decision_file=...).
- You must COMPLETE your assigned tasks. Blocked or task looks wrong -> send_message
  the task creator; only the creator/orchestrator cancels.
- Never poll in a loop; act, then finish().
"""


def write_agent_notes(output_dir: Any) -> str:
    """Persist the workspace conventions doc agents read at wake-up."""
    dest = Path(output_dir) / "design" / "agent_notes.md"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(_AGENT_NOTES, encoding="utf-8")
    return str(dest)


# ---------------------------------------------------------------------------
# Pre-generation MATERIAL-PREP: per-component build specs (decompose each
# reference BEFORE any lane wakes) — USER directive 2026-06-29 / PIPELINE.md §2-4.
# ---------------------------------------------------------------------------
def _component_specs_enabled() -> bool:
    """Material-prep decomposition is on by default; disable with
    ENVGEN_COMPONENT_SPECS in {0,false,no,off}. (Default-on is env-agnostic — it
    only does work when the run actually supplies reference images.)"""
    return (os.environ.get("ENVGEN_COMPONENT_SPECS") or "1").strip().lower() not in (
        "0", "false", "no", "off")


async def precompute_component_specs(
    images: List[str],
    *,
    output_dir: Any,
    llm: Any,
    logger: Any,
    max_images: int = _MAX_DECOMPOSE_IMAGES,
) -> List[str]:
    """Pre-generation MATERIAL-PREP (USER 2026-06-29 — "材料准备阶段在生成前"): BEFORE any
    lane wakes, decompose EACH reference screenshot into its named UI components with MEASURED
    per-component colors (background + accent hues, sampled not guessed) and persist them to
    ``design/component_specs/<stem>.json``. The frontend lane consumes these as its build spec
    (PIPELINE.md §2-4 "generate-to-spec, per component"), so it builds to truth from its first
    turn instead of re-discovering the decomposition on demand (the on-demand ``decompose_reference``
    tool stays available as a fallback / for screens added later).

    Env-agnostic: runs for whatever references the run supplies, no app-specific assumptions.
    Best-effort and concurrent — one vision call per image via ``decompose_reference``; an image
    that fails or yields no components is skipped. Returns the staged relative paths (``[]`` when
    disabled / no images / every image failed). Never raises into the caller.
    """
    if not _component_specs_enabled():
        return []
    imgs = [i for i in (images or []) if i][:max_images]
    if not imgs:
        return []
    import asyncio

    from .material_prep import decompose_reference

    # Bound concurrency: every reference screen is decomposed, but only
    # _DECOMPOSE_CONCURRENCY vision calls run at once (this fans out alongside the
    # reference-spec compile, so an unbounded gather over a big reference set
    # could rate-limit the provider).
    _sem = asyncio.Semaphore(_DECOMPOSE_CONCURRENCY)

    async def _decompose_bounded(_img):
        async with _sem:
            return await decompose_reference(_img, llm)

    results = await asyncio.gather(
        *[_decompose_bounded(img) for img in imgs], return_exceptions=True)
    specs_dir = Path(output_dir) / "design" / "component_specs"
    written: List[str] = []
    for img, res in zip(imgs, results):
        if isinstance(res, BaseException) or not isinstance(res, Mapping):
            logger.info("component decompose failed for %s: %s", Path(img).name, res)
            continue
        if res.get("error") or not res.get("components"):
            logger.info("component decompose produced nothing for %s: %s",
                        Path(img).name, res.get("error") or "no components")
            continue
        stem = Path(img).stem
        rel = Path("design") / "component_specs" / f"{stem}.json"
        try:
            specs_dir.mkdir(parents=True, exist_ok=True)
            payload = {"reference": Path(img).name,
                       "count": res.get("count"),
                       "components": res.get("components")}
            (Path(output_dir) / rel).write_text(
                json.dumps(payload, indent=2) + "\n", encoding="utf-8")
            written.append(str(rel))
        except Exception:
            continue
    if written:
        logger.warning(
            "MATERIAL-PREP: %d/%d reference screen(s) decomposed into per-component "
            "build specs (MEASURED colors) → %s", len(written), len(imgs), ", ".join(written))
    return written


# ---------------------------------------------------------------------------
# Milestone planning (when the user supplies no --milestones)
# ---------------------------------------------------------------------------
_PLAN_INSTRUCTIONS = """You are planning the MILESTONE ROADMAP for an app-generation pipeline.
Given the requirements and the compiled reference spec (screens / endpoints /
entities), partition the build into K incremental milestones. Choose K
yourself: a small app (<=8 endpoints, <=3 screens) is ONE milestone; larger
apps split so each milestone adds roughly 4-10 NEW endpoints and a coherent
feature set. K never exceeds 6.

PLATFORM CONSTRAINTS (always hold, any strategy):
- The FULL data model (all tables) ships in milestone 1 — the backend is
  generated from the contract, so the schema foundation cannot trickle in.
- If the app is auth-gated (most are), the auth surface must be usable by the
  end of milestone 1 — users must be able to get in before anything else
  matters. An un-gated app (public docs site) may skip this.
- Each later milestone builds ON TOP of delivered ones: its description must
  say so and list ONLY the NEW pages and NEW endpoints it adds.
- Every endpoint and screen from the spec appears in exactly one milestone.
- Each description_slice is self-contained: PAGES section, DATA MODEL section
  (full model, repeated verbatim in every slice), NEW API ENDPOINTS section
  (method + path lines).
- Within a milestone the natural build order is: data model -> components ->
  pages that compose them — say so in the slice when it helps.

DECOMPOSITION STRATEGIES (few-shot). To avoid biasing you toward any app
category, all four examples split the SAME abstract app — one with entities
A and B (B belongs to A), list/detail/create screens for each, a cross-user
action X on B, and a summary view. They demonstrate that one app admits many
valid roadmaps — pick (or invent) the split that fits THIS app's spec:
1. INCREMENTAL FEATURE: M1 = A end-to-end (list/detail/create) as a thin but
   usable product; M2 = B nested under A; M3 = action X + the summary view.
2. PAGE-BY-PAGE: M1 = entry page + A list page; M2 = A detail + create
   pages; M3 = B pages; M4 = summary view page.
3. JOURNEY THIN-SLICE: M1 = the single primary journey (create A -> add B ->
   perform X) with minimal screens; M2 = the browsing/secondary journeys;
   M3 = everything aggregate or convenience.
4. CORE-CRUD THEN INTERACTIONS: M1 = CRUD for A and B (no cross-user
   behavior); M2 = action X and its notifications; M3 = the summary view
   and derived counters.

Respond with ONLY a JSON array (each milestone MAY include an "acceptance" list of
2-4 machine-checkable criteria that define DONE for THAT milestone's slice):
[{"name": "M1-<slug>", "version": "1.0.0", "description_slice": "<text>",
  "acceptance": ["<criterion the test-user can verify, e.g. 'a created item appears in its list'>", ...]},
 {"name": "M2-<slug>", "version": "1.1.0", "description_slice": "<text>", "acceptance": [...]}, ...]
Versions increment the minor part per milestone (1.0.0, 1.1.0, 1.2.0, ...)."""


async def plan_milestones(llm: Any, raw_requirements: str,
                          spec: Mapping[str, Any]) -> Optional[List[Dict[str, str]]]:
    """One call with the run's model → the milestone roadmap. None on any
    failure (caller falls back to a single milestone)."""
    from utils.llm import Message
    spec_text = ""
    if spec:
        spec_text = "\n## COMPILED REFERENCE SPEC\n" + json.dumps(
            {k: spec.get(k) for k in ("screens", "endpoints", "entities")},
            ensure_ascii=False)[:24_000]
    prompt = (_PLAN_INSTRUCTIONS
              + _milestone_count_guidance()
              + "\n\n## REQUIREMENTS\n" + str(raw_requirements or "")
              + spec_text)
    try:
        client = getattr(llm, "_client", llm)
        resp = await client.chat([Message.user_multimodal(
            [{"type": "text", "text": prompt}])], temperature=0.0, max_tokens=16000)
        text = getattr(resp, "content", "") or ""
        m = re.search(r"\[.*\]", text, re.DOTALL)
        if not m:
            return None
        data = json.loads(m.group(0))
        if not isinstance(data, list) or not data:
            return None
        # Truncate ONLY when the count is FORCED (enforce exactly N); recommend/free
        # leave the planner's K untouched — no artificial ceiling.
        _mode, _lo, _hi = _milestone_target()
        if _mode == "force":
            data = data[:_hi]
        out: List[Dict[str, str]] = []
        for i, entry in enumerate(data):
            if not isinstance(entry, Mapping):
                return None
            name = str(entry.get("name") or f"M{i+1}").strip()
            version = str(entry.get("version") or f"1.{i}.0").strip()
            slice_ = str(entry.get("description_slice") or "").strip()
            if not slice_:
                return None
            # §4: carry optional per-milestone acceptance criteria (best-effort; the
            # test-user squad scopes its goals to THIS milestone's acceptance when present).
            _acc = entry.get("acceptance")
            acc = [str(a) for a in _acc] if isinstance(_acc, list) else []
            out.append({"name": name, "version": version,
                        "description_slice": slice_, "acceptance": acc})
        return out
    except Exception:
        return None


@dataclass
class ReferenceCompileResult:
    """Outcome of :func:`compile_reference_materials`. ``requirements`` is the
    (possibly spec-extended) requirements text to use downstream. The remaining
    fields are the state the orchestrator records ONLY when this run actually
    produced them — ``classified`` gates the images/docs writes (so a classify
    failure leaves the orchestrator's prior values untouched), and ``spec`` is
    None unless a usable reference spec compiled.
    """
    requirements: str
    classified: bool = False
    images: Optional[List[str]] = None
    docs: Optional[List[str]] = None
    spec: Optional[Dict[str, Any]] = None
    spec_summary: Optional[str] = None


# #871: ceiling on the reference compile INCLUDING its re-rolls. `utils.llm` caps one completion
# at 240s (FIX #187) and the retry layer is capped at 3 attempts (#890's correction), so one
# call is ~12 MINUTES worst case -- bounded, and large enough to eat a run. This gathers two. Same
# calibration as #870's planning ceiling: above one watchdog, below two. Env-overridable.
# #898: DERIVED from the live per-call watchdog, not hardcoded. r153 measured 6550
# completions with max 588.9s -- 2.45x the 240s I had calibrated against, because 240 is
# `_llm_hard_timeout(None, ...)` (the UNSET default) while config.py sets timeout=1800, so
# the live cap is min(1800, 600) = 600s. The old 300s sat at HALF the real watchdog and
# would have cut that 588.9s call in two.
# ★ imported INSIDE the function: three tests exec this module's source into a synthetic
# package and hand-stub each module-level relative import, so a new one there fails at
# collection with `No module named '<pkg>.stage_contract'` (#853/#889 hit this too).
# Calling it per use also means the ceiling tracks a config change without a restart.
def _ref_compile_timeout_s_871() -> float:
    from .stage_contract import llm_ceiling_898
    return llm_ceiling_898("ENVGEN_REF_COMPILE_TIMEOUT_S")


async def compile_reference_materials(
    raw_req: str,
    *,
    output_dir: Any,
    llm: Any,
    logger: Any,
    reference_images: Optional[List[Any]] = None,
) -> ReferenceCompileResult:
    """Classify reference materials, stage documents into the workspace,
    compile the REFERENCE SPEC with the run's selected model, persist it,
    derive deliverability gates from it, and return the requirements text
    extended with the spec summary. Best-effort: on any failure the run
    proceeds with the original requirements (``classified=False`` ⇒ the
    caller leaves its reference-image/-doc state as-is).
    """
    images: Optional[List[str]] = None
    docs: Optional[List[str]] = None
    try:
        split = classify_references(reference_images or [])
        images = split["images"]
        docs = split["docs"]
        if not images and not docs:
            return ReferenceCompileResult(raw_req, classified=True,
                                          images=images, docs=docs)
        try:
            write_agent_notes(output_dir)
        except Exception:
            pass
        # stage BOTH docs and reference images into design/references/ so the
        # env is self-contained (the Env Forge UI can serve/show the screenshots).
        staged = stage_reference_docs(docs + images, output_dir)
        if staged:
            logger.info("Reference documents staged: %s", staged)
        # Material-prep (pre-gen) runs CONCURRENTLY with the spec compile: both are
        # one-time vision passes over the same reference images and are independent, so
        # there is no reason to pay their latency back-to-back. The component decompose
        # writes design/component_specs/* regardless of whether the spec compile yields
        # anything usable (the two artifacts serve different lanes).
        import asyncio as _asyncio
        # #871: bound the pair. Same shape as #870, one phase earlier.
        #
        # Both are vision LLM calls. `utils.llm._llm_hard_timeout` caps each COMPLETION at 240s,
        # but its retry layer re-rolls after every cancel with no cap on the count ("a cancelled
        # slow call is retried, not lost"), so each branch is 240s x N — and `gather` waits for
        # the slower one. This runs BEFORE milestone planning, so a stall here costs design prep,
        # the roadmap, kickoff and every lane, exactly as #870's did one step later.
        #
        # The fallback already exists and is three lines below: an unusable spec logs
        # "continuing without" and the run proceeds. That is what makes a ceiling safe here —
        # timing out lands on a path the code already takes, not on a new one.
        #
        # Calibrated against the 240s watchdog like #870: one full attempt per branch (they run
        # concurrently, so the pair does not need double), and the second re-roll truncated.
        try:
            spec, _ = await _asyncio.wait_for(
                _asyncio.gather(
                    compile_reference_spec(llm, images, docs, raw_req),
                    precompute_component_specs(images, output_dir=output_dir,
                                               llm=llm, logger=logger),
                ),
                timeout=_ref_compile_timeout_s_871(),
            )
        except _asyncio.TimeoutError:
            logger.error(
                "Reference compile TIMED OUT after %.0fs (#871) — continuing without a spec. "
                "Unbounded, its retry loop ran ahead of milestone planning and cost the run.",
                _ref_compile_timeout_s_871())
            spec = None
        if not spec or not any(spec.get(k) for k in
                               ("screens", "endpoints", "entities", "mcp_tools")):
            logger.info("Reference spec compile produced nothing usable — continuing without.")
            return ReferenceCompileResult(raw_req, classified=True,
                                          images=images, docs=docs)
        spec_path = Path(output_dir) / "design" / "reference_spec.json"
        spec_path.parent.mkdir(parents=True, exist_ok=True)
        spec_path.write_text(json.dumps(spec, indent=2) + "\n", encoding="utf-8")
        gates = gates_from_spec(spec)
        n = merge_user_gates(output_dir, gates) if gates else 0
        summary = spec_summary_for_requirements(spec)
        logger.warning(
            "REFERENCE SPEC compiled: %d screens, %d endpoints, %d entities, "
            "%d mcp tools → %d deliverability gates registered; spec at %s",
            len(spec.get("screens") or []), len(spec.get("endpoints") or []),
            len(spec.get("entities") or []), len(spec.get("mcp_tools") or []),
            n, spec_path)
        return ReferenceCompileResult(raw_req + summary, classified=True,
                                      images=images, docs=docs,
                                      spec=spec, spec_summary=summary)
    except Exception as exc:
        logger.error("reference material compile failed (non-fatal): %s", exc)
        return ReferenceCompileResult(raw_req, classified=(images is not None),
                                      images=images, docs=docs)
