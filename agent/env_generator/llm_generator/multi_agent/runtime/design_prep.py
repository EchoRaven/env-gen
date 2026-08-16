"""Design-Prep phase — a one-shot pre-generation step that turns user-provided references, docs,
and REAL assets into a rich, measured design document + a staged asset library the frontend/backend
lanes build from.

Runs once at run start, before the lanes; does not reappear. Two layers (hybrid architecture):

  1. Deterministic MEASURE — crop references, sample exact hex, extract the palette, ingest+stage
     real assets into a manifest. No LLM; "measure, don't guess".
  2. Single-shot ANALYST — one agent enriches the measured skeleton with per-component style/UX
     prose + component→asset mapping + asset annotations, and emits design_system.json/.md.

Everything is best-effort: any failure degrades to today's references-only behavior, never blocks
a run. Env-agnostic.
"""

from __future__ import annotations

import logging

_LOG_813 = logging.getLogger(__name__)

import json
from pathlib import Path
from typing import Dict, List, Optional

_IMG_EXTS = (".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp")
_DOC_EXTS = (".md", ".markdown", ".txt", ".rst", ".html", ".htm", ".pdf")


def _list_files(folder: Path, exts) -> List[str]:
    if not folder.is_dir():
        return []
    out: List[str] = []
    for p in sorted(folder.iterdir()):
        if p.is_file() and p.suffix.lower() in exts:
            out.append(str(p))
    return out


def resolve_design_input(design_input: Optional[str],
                         reference_dir: Optional[str],
                         reference_images: Optional[List[str]]) -> Dict:
    """Resolve the design inputs into {references, docs, assets_dir}.

    With ``design_input`` set (a dir), read its optional ``references/`` (images), ``docs/``
    (md/html/pdf/txt), and ``assets/`` (real asset files) subfolders. Absent → back-compat:
    ``reference_dir`` (glob images) + ``reference_images`` passthrough, docs=[], assets_dir=None.
    Best-effort — never raises."""
    references: List[str] = []
    docs: List[str] = []
    assets_dir: Optional[str] = None
    dataset_dir: Optional[str] = None

    try:
        if design_input:
            root = Path(design_input)
            references = _list_files(root / "references", _IMG_EXTS)
            docs = _list_files(root / "docs", _DOC_EXTS)
            adir = root / "assets"
            assets_dir = str(adir) if adir.is_dir() else None
            # F1: the FOURTH channel — a dataset/ folder of REAL structured data
            # (JSON/CSV) ingested recursively (a folder path, like assets/).
            ddir = root / "dataset"
            dataset_dir = str(ddir) if ddir.is_dir() else None
            return {"references": references, "docs": docs,
                    "assets_dir": assets_dir, "dataset_dir": dataset_dir}

        # back-compat: references-only
        references = list(reference_images or [])
        if reference_dir:
            references.extend(_list_files(Path(reference_dir), _IMG_EXTS))
    except Exception:
        pass
    return {"references": references, "docs": docs,
            "assets_dir": assets_dir, "dataset_dir": dataset_dir}


# ── deterministic skeleton design_system (measure, no LLM) ───────────────────
def _measure_palette(references: List[str]) -> Dict:
    """Measured palette across the references — bg (dominant across screens) + accent hues.
    Only MEASURED facts (bg/accents); surface/text/etc. are the analyst's to add. Best-effort."""
    from .material_prep import extract_palette
    from collections import Counter
    bgs: Counter = Counter()
    accents: Dict[str, str] = {}
    for ref in references or []:
        pal = extract_palette(ref)
        if not isinstance(pal, dict) or pal.get("error"):
            continue
        if pal.get("background"):
            bgs[pal["background"]] += 1
        for hue, hx in (pal.get("accents") or {}).items():
            accents.setdefault(hue, hx)
    out: Dict = {}
    if bgs:
        out["bg"] = bgs.most_common(1)[0][0]
    if accents:
        out["accents"] = accents
        out["accent"] = next(iter(accents.values()))
    return out


def _theme_from_palette(palette: Dict) -> Dict:
    """default theme from the measured bg luminance (dark if the background is dark)."""
    from .material_prep import _luminance
    default = "light"
    bg = palette.get("bg")
    if bg:
        lum = _luminance(bg)
        if lum is not None and lum < 128:
            default = "dark"
    return {"default": default, "themes": [default]}


def _load_component_specs(output_dir: Path) -> Dict[str, Dict]:
    """Load design/component_specs/<stem>.json (as reference_materials writes them), keyed by
    stem. Best-effort — a missing dir or unreadable file is skipped."""
    specs: Dict[str, Dict] = {}
    d = output_dir / "design" / "component_specs"
    if not d.is_dir():
        return specs
    for p in sorted(d.glob("*.json")):
        try:
            specs[p.stem] = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
    return specs


def _measure_component_geometry(im, region) -> Dict:
    """#220: deterministic per-component geometry (columns / rows / gaps) from
    the reference pixels. The analyst schema always promised a ``geometry``
    field but no LLM run fills it — measure it instead. Tiny regions (< 2% of
    the screen) carry no measurable structure and are skipped. Best-effort."""
    if im is None or not (isinstance(region, (list, tuple)) and len(region) == 4):
        return {}
    try:
        x0, y0, x1, y1 = (float(v) for v in region)
    except (TypeError, ValueError):
        return {}
    if (x1 - x0) * (y1 - y0) < 0.02:
        return {}
    try:
        from .material_prep import grid_columns, row_bands
        gc = grid_columns(im, (x0, y0, x1, y1))
        rb = row_bands(im, (x0, y0, x1, y1))
        geo = {
            "columns": gc.get("columns"),
            "pitch_px": gc.get("pitch_px"),
            "rows": rb.get("items"),
            "row_gap_px": rb.get("item_gap_px"),
        }
        return {k: v for k, v in geo.items() if v}
    except Exception:
        return {}


def _skeleton_components(spec: Optional[Dict], im=None) -> List[Dict]:
    from .material_prep import _slug
    comps: List[Dict] = []
    for c in ((spec or {}).get("components") or []):
        if not isinstance(c, dict):
            continue
        accents = c.get("accents") or {}
        accent = next(iter(accents.values()), None) if isinstance(accents, dict) else None
        colors: Dict = {}
        if c.get("background"):
            colors["bg"] = c["background"]
        if accent:
            colors["accent"] = accent
        comps.append({
            "id": _slug(str(c.get("name") or "component")),
            "region": c.get("region"),
            "colors": colors,          # MEASURED (never overwritten downstream)
            "geometry": _measure_component_geometry(im, c.get("region")),  # #220 MEASURED
            "assets": [],              # analyst maps real assets here
            "role": c.get("role") or "",
            "state": c.get("state") or "",
            "copy": "",                # #778 — filled by the screen pass below
            "crop": c.get("crop"),
            "build_notes": "",
        })
    return comps


def build_skeleton_design_system(resolved: Dict, output_dir,
                                 *, existing_specs: Optional[Dict] = None) -> Dict:
    """Deterministic skeleton of design_system.json — MEASURED facts only, no LLM.

    Measures the palette + theme from the references, ingests+stages the assets/ folder into
    ``<output_dir>/design/assets/`` (manifest), and carries the pre-measured per-component colors
    from ``design/component_specs/<stem>.json`` (or ``existing_specs`` keyed by screen stem) into
    ``screens[].components[]`` (leaving ``assets:[]`` for the analyst). Best-effort; never raises."""
    out = Path(output_dir)
    references = list(resolved.get("references") or [])

    assets: List[Dict] = []
    adir = resolved.get("assets_dir")
    if adir:
        try:
            from .material_prep import ingest_assets
            assets = ingest_assets(adir, out / "design" / "assets")
        except Exception:
            assets = []

    # F1: the dataset/ channel — real structured data rows, staged into
    # design/dataset/ (build-infra copies them to app/backend/dataset/).
    dataset: List[Dict] = []
    ddir = resolved.get("dataset_dir")
    if ddir:
        try:
            from .material_prep import ingest_dataset
            dataset = ingest_dataset(ddir, out / "design" / "dataset")
        except Exception:
            dataset = []

    palette = _measure_palette(references)
    theme = _theme_from_palette(palette)

    specs = existing_specs if existing_specs is not None else _load_component_specs(out)
    screens: List[Dict] = []
    for ref in references:
        stem = Path(ref).stem
        im = None
        try:
            from PIL import Image
            im = Image.open(ref).convert("RGB")
        except Exception:
            im = None
        layout_metrics: Dict = {}
        if im is not None:
            try:
                from .material_prep import content_bounds
                layout_metrics = content_bounds(im) or {}
            except Exception:
                layout_metrics = {}
        screens.append({
            "name": stem,
            "reference": Path(ref).name,
            "layout": "",
            "layout_metrics": layout_metrics,   # #220 MEASURED screen content bounds
            "components": _skeleton_components(specs.get(stem), im),
        })

    # #822: a screen the SPEC declares but no reference image covers is dropped here, silently.
    # The skeleton is built from the reference IMAGES, so `reference_spec.json` can require a
    # screen this pipeline will never see. Measured on r140+: `profiles` is declared in 11 of 11
    # runs, has no reference image in any of them, and therefore appears in NO design_system, NO
    # visual_gate capture and NO verdict — never photographed, never scored, never blocking. For
    # a streaming clone that is the who's-watching picker, the first screen after login.
    #
    # It also corrects #788, which recorded the spec's `screens` list as ENFORCED because "the
    # visual gate captures and scores every screen in it, so an unbuilt one takes a blocking
    # zero". True only for screens WITH a reference image; silent for the rest.
    #
    # Nothing is invented here — a screen cannot be visually scored against an image that does
    # not exist. What changes is that the gap is stated instead of inferred from an absence.
    try:
        _spec822 = json.loads((out / "design" / "reference_spec.json").read_text(
            encoding="utf-8")) if (out / "design" / "reference_spec.json").is_file() else {}
        _want822 = {str(x.get("name")) for x in (_spec822.get("screens") or [])
                    if isinstance(x, dict) and x.get("name")}
        _have822 = {str(x.get("name")) for x in screens if isinstance(x, dict)}
        _missing822 = sorted(_want822 - _have822)
        if _missing822:
            _LOG_813.warning(
                "design-prep: the reference SPEC declares %d screen(s) with no reference image, "
                "so they are absent from design_system.json and the visual gate will never "
                "capture, score or block on them: %s. The spec's `screens` list is enforced only "
                "for screens that HAVE an image.", len(_missing822), _missing822)
    except Exception:
        pass

    return {
        "design_system": {
            "palette": palette,
            "theme": theme,
            "type_scale": [],
            "radius_scale": {},
            "shadow_scale": [],
            "iconography": {},
        },
        "assets": assets,
        "dataset": dataset,
        "screens": screens,
    }


# ── single-shot analyst enrichment (the one agent pass) ──────────────────────
_ANALYST_PROMPT = (
    "You are a senior UI/UX designer writing the DESIGN SYSTEM for a faithful clone of a reference app.\n"
    "You are given: (1) a SKELETON design_system JSON whose colors are already MEASURED from the "
    "reference pixels — these are GROUND TRUTH, never change a measured hex; (2) the reference "
    "screenshots; (3) a manifest of REAL assets (icons/logos/images) the build will actually use, "
    "with their images; (4) any reference docs.\n\n"
    "Produce an ENRICHED design_system JSON with the SAME shape as the skeleton, filling in:\n"
    " - design_system: add surface/text/border palette keys (do NOT change measured bg/accent), "
    "type_scale (roles h1/h2/body/caption with size_px+weight estimated from the crops), "
    "radius_scale, shadow_scale, iconography {style,stroke_px}.\n"
    " - screens[].layout: one line describing the page layout.\n"
    " - screens[].components[]: for EACH component keep its measured colors, and add role, "
    "build_notes (concrete: what it looks like + how to build it), typography, and CRITICALLY "
    "\"assets\": the list of REAL asset ids (from the manifest) this component should render "
    "(a nav uses the logo + action icons; a post uses avatar/media assets; etc.). Map every asset "
    "that visibly belongs to a component.\n"
    " - assets[]: for each asset add \"description\" (what it depicts + style) and \"use\" (where it "
    "appears).\n\n"
    "\"measure, don't guess\": colors are measured facts. Output ONLY the JSON object, nothing else."
)


def _img_part(path: str) -> Optional[Dict]:
    import base64
    try:
        src = str(path)
        try:
            from tools.file_tools import _compressed_image_for_llm
            src = _compressed_image_for_llm(src) or src
        except Exception:
            pass
        with open(src, "rb") as f:
            b64 = base64.b64encode(f.read()).decode()
        return {"type": "image_url",
                "image_url": {"url": f"data:image/png;base64,{b64}", "detail": "high"}}
    except Exception:
        return None


# #817: every run in the 151-run corpus stages one `spec.md`, and every one is 5,690 bytes — the
# previous 4000 cut dropped 1,690 of them, including the Wiring rule and two whole sections.
# 12000 is 2.1x the observed spec and ~3k tokens, which sits comfortably against the 6000-token
# reply budget alongside a <=5,450-char compact skeleton (#816) and the manifest.
_DOCS_BUDGET_817 = 12000


def _docs_for_prompt_817(docs_text: str) -> str:
    """#817: the reference spec, cut at a SECTION boundary and never silently.

    `docs_text[:4000]` dropped 1,690 of r151's 5,690-char `spec.md` — and every run in the corpus
    stages that same doc, so this fired 151 times out of 151. What fell past the cut was the
    actionable half: the per-screen behaviour list (*"clicking a poster opens the title-detail
    modal"*, *"+ toggles My List"*), the whole `## Data model (tables)` and `## Seed data`
    sections, and the **Wiring rule** — *"EVERY nav link, button, icon and card must call a real
    endpoint ... no dead links, no inert placeholders, no fabricated data"*, which is precisely
    what `frontend_dead_controls` blocks releases over. The analyst writing `build_notes` never
    read it.

    4000 was not a considered budget for a 5,690-char spec. 12,000 fits real specs with margin
    against a 6000-token reply. Beyond that the cut lands on a markdown heading rather than
    mid-sentence, and names the sections it dropped (#811).
    """
    text = str(docs_text or "")
    if len(text) <= _DOCS_BUDGET_817:
        return text
    import re as _re
    heads = [m.start() for m in _re.finditer(r"^#+ ", text, _re.M)]
    cut = max([h for h in heads if h <= _DOCS_BUDGET_817] or [_DOCS_BUDGET_817])
    dropped = [m.group(0).strip()[:60]
               for m in _re.finditer(r"^#+ .*$", text, _re.M) if m.start() >= cut]
    _LOG_813.warning(
        "design-prep: reference docs are %d chars, over the %d budget — cut at a section "
        "boundary (%d chars kept). The analyst will NOT see: %s",
        len(text), _DOCS_BUDGET_817, cut, dropped or ["<unsectioned tail>"])
    return text[:cut]


def _round_region_816(region) -> Optional[List[float]]:
    """A 4-float region rounded for the prompt; None if it is absent or not numeric."""
    try:
        out = [round(float(x), 3) for x in (region or [])]
    except (TypeError, ValueError):
        return None
    return out or None


def _skeleton_for_prompt_816(screen: Dict) -> str:
    """#816: the JOIN KEYS and context the analyst needs, and nothing else.

    The skeleton was serialised whole and cut at 9000 chars. Measured on r151: **7 of 20 screens
    exceed it**, median overflow 2,733 — and a JSON object cut mid-structure is INVALID JSON, so
    the analyst was asked to "enrich THESE components by id" from a malformed document. Components
    past the cut have ids it never saw, which is a fourth way the enrichment evaporates (after the
    call #813, the join #815, and the empty reply).

    The analyst's job is to ADD `build_notes`/`typography`/`copy` per id. It does not need crop
    paths, full colour dicts, geometry or six-decimal regions echoed back at it. Projecting to
    id/role/state/region/bg takes the largest screen from 13,563 to 4,491 chars — every screen now
    fits, with room to spare, and the JSON it sees is always well-formed.
    """
    compact = {
        "name": screen.get("name"),
        "layout": screen.get("layout"),
        "components": [
            {k: v for k, v in (
                ("id", c.get("id")),
                ("role", c.get("role")),
                ("state", c.get("state")),
                # A non-numeric region must not take design-prep down: it runs before any lane,
                # so an exception here costs the whole visual pipeline. My own test caught this.
                ("region", _round_region_816(c.get("region"))),
                ("bg", (c.get("colors") or {}).get("bg")
                 if isinstance(c.get("colors"), dict) else None),
            ) if v not in (None, "", [])}
            for c in (screen.get("components") or []) if isinstance(c, dict)
        ],
    }
    out = json.dumps(compact, indent=1)
    if len(out) > 9000:
        # Still bounded, but no longer silent (#811): a screen this large means the projection
        # needs revisiting, not that the analyst should be handed a broken document.
        _LOG_813.warning(
            "design-prep: screen %r is %d chars even COMPACTED and will be cut at 9000 — the "
            "components past the cut have ids the analyst never sees, so their build_notes/"
            "typography/copy cannot come back.", screen.get("name"), len(out))
        out = out[:9000]
    return out


_SCREEN_PROMPT = (
    "You are a senior UI engineer writing BUILD NOTES for a faithful clone of ONE screen.\n"
    "You get: the screen's MEASURED skeleton (component ids + measured colors — ground "
    "truth, never change a hex), the REAL asset manifest, and the reference screenshot.\n"
    "For EVERY component id in the skeleton, submit one entry with:\n"
    " - build_notes (REQUIRED, 1-3 concrete sentences from the SCREENSHOT: geometry, "
    "paddings/spacing, icon shapes, borders/dividers, states — what a dev needs to copy it)\n"
    " - copy: if the component shows TEXT, transcribe it VERBATIM — the exact heading, "
    "label, placeholder, button caption, link text or notice, character for character, "
    "including punctuation. Do NOT describe it ('muted secondary text', 'static'): the clone "
    "is scored against the reference on COPY, and a description cannot be typed into JSX. "
    "Empty string only when the component genuinely renders no text.\n"
    " - typography (role sizes/weights you can read), and assets (manifest ids this "
    "component should render).\n"
    "Also submit layout (one line) and the GLOBAL scales estimated from the screenshot: "
    "type_scale (roles h1/h2/body/caption with size_px + weight), radius_scale (corner "
    "radii by size, e.g. {\"sm\":4,\"md\":8,\"full\":9999}), shadow_scale (elevation "
    "shadows you can see), iconography ({style, stroke_px}). Estimate rather than omit — "
    "leave a scale out ONLY when the screen truly shows nothing to estimate from.\n"
    "ALSO CLASSIFY the screen itself (FIX #132 — the visual gate navigates by URL, so it "
    "must know which references are reachable pages and which are interaction states):\n"
    " - kind: 'page' if the screenshot is a full standalone screen, 'overlay' if it shows "
    "a modal/dialog/flyout/dropdown/sheet rendered OVER another page (dimmed or visible "
    "background page = overlay).\n"
    " - requires_auth: true if the screen shows logged-in user data (feed, profile, inbox), "
    "false for public screens (login, signup, landing).\n"
    " - route: the SPA path this screen would live at (e.g. '/', '/login', '/explore', "
    "'/reels', '/messages'); for an overlay, the route of the page UNDER it.\n"
    "Submit via the function — nothing else."
)

_SCREEN_TOOL = [{
    "type": "function",
    "function": {
        "name": "submit_screen_enrichment",
        "description": ("Submit THIS screen's design enrichment: one entry per skeleton "
                        "component id, each with REQUIRED concrete build_notes."),
        "parameters": {
            "type": "object",
            "properties": {
                "layout": {"type": "string"},
                # FIX #132: screen-level classification — the visual gate reads these as
                # the AUTHORITATIVE reference->route/overlay mapping (filename heuristics
                # become the fallback).
                "kind": {"type": "string", "enum": ["page", "overlay"]},
                "requires_auth": {"type": "boolean"},
                "route": {"type": "string"},
                "components": {"type": "array", "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "build_notes": {"type": "string"},
                        # #778: the literal words on the component, transcribed. Without a slot
                        # the model has nowhere to put them — 84% of 9152 text components across
                        # 53 runs carry a DESCRIPTION ("static", "collapsed, default value")
                        # instead of the string, and `copy` is the most frequent scoring floor on
                        # `login`, which blocks 73% of runs. The 15% that do quote are burying it
                        # in build_notes prose, which is the tell that the slot was missing.
                        "copy": {"type": "string"},
                        "typography": {"type": "object"},
                        "assets": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["id", "build_notes"],
                }},
                "type_scale": {"type": "array", "items": {"type": "object"}},
                "radius_scale": {"type": "object"},
                # #220b: was absent → structurally impossible to fill via tool call
                "shadow_scale": {"type": "array", "items": {"type": "object"}},
                "iconography": {"type": "object"},
            },
            "required": ["components"],
        },
    },
}]


def _tool_call_args(resp) -> Optional[Dict]:
    for tc in (getattr(resp, "tool_calls", None) or []):
        fn = tc.get("function") if isinstance(tc, dict) else getattr(tc, "function", None)
        args = (fn or {}).get("arguments") if isinstance(fn, dict) else getattr(fn, "arguments", None)
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except Exception:
                args = None
        if isinstance(args, dict):
            return args
    return None


async def _chat_ladder(client, msgs, *, max_tokens: int) -> Optional[Dict]:
    """forced-function → JSON-mode text → plain text; TypeError degrades per rung."""
    import re
    resp = None
    try:
        # #480: send the Anthropic force-tool DICT ({"type":"tool","name":...}) — a bare
        # string "required" is rejected by the (now-stricter) vertex proxy with
        # BadRequestError 400 'tool_choice: Input should be a valid dictionary' (r53: 59×;
        # r51/r52 had 0 → an environment/proxy tightening, not the caller). Force the single
        # screen-enrichment tool by name.
        resp = await client.chat(msgs, temperature=0.0, max_tokens=max_tokens,
                                 tools=_SCREEN_TOOL,
                                 tool_choice={"type": "tool", "name": "submit_screen_enrichment"})
    except Exception:
        # #480: was `except TypeError` — the 400 above is a BadRequestError, NOT TypeError, so
        # it propagated and failed the WHOLE screen enrichment instead of degrading. The
        # ladder's intent is 'forced-function → JSON-mode → plain text; degrade per rung', so
        # degrade on ANY forced-function failure → JSON-mode still yields the structured screen
        # (robust to future provider/proxy changes; generalizable to every run's design phase).
        resp = None
    args = _tool_call_args(resp)
    if args is not None:
        return args
    if resp is None or not (getattr(resp, "content", "") or "").strip():
        try:
            resp = await client.chat(msgs, temperature=0.0, max_tokens=max_tokens,
                                     response_mime_type="application/json")
        except Exception:
            resp = await client.chat(msgs, temperature=0.0, max_tokens=max_tokens)
    text = getattr(resp, "content", "") or ""
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except Exception:
        return None


async def _run_analyst(skeleton: Dict, resolved: Dict, output_dir: Path, llm,
                       docs_text: str, max_ref_images: int, max_asset_images: int) -> Optional[Dict]:
    """FIX #94: enrich PER SCREEN. Three live runs + a controlled offline replay proved the
    -customtools model refuses LARGE one-shot outputs on the mega multimodal prompt no
    matter the format (#88 JSON mode → 11 tokens; #92 forced function → a near-empty doc)
    while doing SMALL structured outputs instantly. One forced-function call per screen
    (its skeleton slice + its reference image + the asset manifest), merged best-effort —
    a failed screen never poisons the rest. Global scales are harvested from the first
    screen that reports them."""
    from utils.llm import Message

    client = getattr(llm, "_client", None) or llm
    ref_by_name = {Path(r).name: r for r in (resolved.get("references") or [])}
    manifest = json.dumps([{"id": a.get("id"), "file": a.get("file")}
                           for a in (skeleton.get("assets") or [])])[:3000]

    enriched_screens: List[Dict] = []
    scales: Dict = {}
    asset_notes: Dict = {}
    for s in (skeleton.get("screens") or []):
        if not isinstance(s, dict):
            continue
        parts: List[Dict] = [
            {"type": "text", "text": _SCREEN_PROMPT},
            {"type": "text", "text": ("SCREEN '" + str(s.get("name")) + "' skeleton "
                                      "(measured facts — enrich THESE components by id):\n"
                                      + _skeleton_for_prompt_816(s))},
            {"type": "text", "text": "REAL ASSET MANIFEST (map ids onto components): " + manifest},
        ]
        if docs_text:
            parts.append({"type": "text", "text": "REFERENCE DOCS:\n"
                                                  + _docs_for_prompt_817(docs_text)})
        ref = ref_by_name.get(str(s.get("reference") or ""))
        p = _img_part(ref) if ref else None
        if p:
            parts.append({"type": "text", "text": f"REFERENCE screenshot for '{s.get('name')}':"})
            parts.append(p)
        try:
            doc = await _chat_ladder(client, [Message.user_multimodal(parts)], max_tokens=6000)
        except Exception as exc:
            # #813: this was `except Exception: doc = None` followed by a bare `continue` — the
            # #769 shape on a MEASUREMENT path. Measured over 12 recent runs and 4,006
            # components: `build_notes` is populated 1 time and `typography` 0 times, while
            # `crop` (which comes from the skeleton, not from here) is populated 3,675 times.
            # So this enrichment yields essentially nothing and has never said why — and the
            # frontend prompt meanwhile directs the lane to read `build_notes`/`typography` on
            # every component. Whether the cause is a transport error, a non-dict reply or a
            # 6000-token truncation, the next run now names it per screen instead of leaving a
            # silently unenriched skeleton.
            _LOG_813.warning(
                "design-prep screen enrichment FAILED for %r (%s: %s) — this screen keeps its "
                "unenriched skeleton, so its components will carry NO build_notes/typography/"
                "copy and the frontend prompt points the lane at fields that will be empty.",
                s.get("name"), type(exc).__name__, exc)
            doc = None
        if not isinstance(doc, dict):
            if doc is not None:
                _LOG_813.warning(
                    "design-prep screen enrichment returned %s, not an object, for %r — same "
                    "consequence: an unenriched skeleton.", type(doc).__name__, s.get("name"))
            continue
        # tolerate both {components:[...]} and a full-doc {design_system,screens} shape
        dsx = doc.get("design_system") if isinstance(doc.get("design_system"), dict) else {}
        comps = doc.get("components")
        layout = doc.get("layout")
        if isinstance(doc.get("screens"), list) and doc["screens"]:
            first = doc["screens"][0]
            if isinstance(first, dict):
                if comps is None:
                    comps = first.get("components")
                if not layout:
                    layout = first.get("layout")
        _entry = {"name": s.get("name"),
                  "layout": str(layout or ""),
                  "components": comps or []}
        # FIX #132: harvest the screen-level classification (kind/requires_auth/route) —
        # tolerate both the flat tool-call shape and a full-doc screens[0] shape.
        _first = (doc.get("screens") or [{}])[0] if isinstance(doc.get("screens"), list) else {}
        for _ck in ("kind", "requires_auth", "route"):
            _cv = doc.get(_ck)
            if _cv is None and isinstance(_first, dict):
                _cv = _first.get(_ck)
            if _cv is not None:
                _entry[_ck] = _cv
        enriched_screens.append(_entry)
        for k in ("type_scale", "radius_scale", "shadow_scale", "iconography", "palette"):
            v = doc.get(k) or dsx.get(k)
            if v and not scales.get(k):
                scales[k] = v
        for a in (doc.get("assets") or []):
            if isinstance(a, dict) and a.get("id") is not None:
                asset_notes.setdefault(a["id"], a)
    if not enriched_screens:
        return None
    return {"design_system": scales, "assets": list(asset_notes.values()),
            "screens": enriched_screens}


def _merge_enrichment(skeleton: Dict, enriched: Dict) -> Dict:
    """Merge the analyst's enrichment over the skeleton — MEASURED facts always win. The skeleton's
    measured palette keys (bg/accent/accents) and every component ``colors`` map are immutable;
    everything else (prose, type/radius/shadow scales, asset mapping, annotations) is taken from
    the analyst when present."""
    import copy
    ds = copy.deepcopy(skeleton)
    e = enriched or {}

    eds = e.get("design_system") or {}
    sds = ds["design_system"]
    # palette: analyst may ADD keys but not overwrite measured ones
    for k, v in (eds.get("palette") or {}).items():
        sds.setdefault("palette", {})
        if k not in sds["palette"]:
            sds["palette"][k] = v
    for key in ("type_scale", "radius_scale", "shadow_scale", "iconography"):
        if eds.get(key):
            sds[key] = eds[key]
    if eds.get("theme"):
        # keep the measured default theme, but let the analyst add extra themes
        cur = sds.get("theme") or {}
        cur_themes = set(cur.get("themes") or [])
        for t in (eds["theme"].get("themes") or []):
            cur_themes.add(t)
        cur["themes"] = sorted(cur_themes) if cur_themes else cur.get("themes")
        sds["theme"] = cur

    # assets: add description/use by id (never touch id/file/type/dims/staged_path)
    e_assets = {a.get("id"): a for a in (e.get("assets") or []) if isinstance(a, dict)}
    for a in ds.get("assets") or []:
        ea = e_assets.get(a.get("id"))
        if ea:
            for k in ("description", "use"):
                if ea.get(k) is not None:
                    a[k] = ea[k]

    # screens/components: layout + role/build_notes/typography/state/assets by id
    e_screens = {s.get("name"): s for s in (e.get("screens") or []) if isinstance(s, dict)}
    for s in ds.get("screens") or []:
        es = e_screens.get(s.get("name"))
        if not es:
            continue
        if es.get("layout"):
            s["layout"] = es["layout"]
        # FIX #132: screen-level classification flows through the merge (else the analyst's
        # kind/requires_auth/route would be silently discarded — only the skeleton copy is
        # what gets written to design_system.json).
        for _ck in ("kind", "requires_auth", "route"):
            if es.get(_ck) is not None:
                s[_ck] = es[_ck]
        e_comps = {c.get("id"): c for c in (es.get("components") or []) if isinstance(c, dict)}
        # #815: this join is by `id` on BOTH sides, and a miss is a silent `continue`. Measured
        # over 12 runs and 4,006 components, `build_notes` lands 1 time and `typography` 0 —
        # while `crop`, which comes from the skeleton rather than through this merge, lands 92%.
        # #813 made the CALL audible; this makes the JOIN audible, which is the other place the
        # enrichment can evaporate. If the analyst answers with its own ids (`nav_bar` for the
        # skeleton's `top-nav-bar`) every component misses and the screen keeps a bare skeleton,
        # with nothing anywhere saying so. Reported per screen, once.
        _matched815 = _missed815 = 0
        for c in s.get("components") or []:
            ec = e_comps.get(c.get("id"))
            if not ec:
                _missed815 += 1
                continue
            _matched815 += 1
            # #778: `copy` MUST be in this list. It is the third fixed-key projection on this
            # path, and #767b/#768b/#771 were each a field added at one end and dropped here.
            for k in ("role", "build_notes", "state", "copy", "typography", "assets", "crop"):
                if ec.get(k) is not None:
                    c[k] = ec[k]
            # measured colors are immutable — c["colors"] is never replaced
        # An EMPTY enrichment is #813's event (the call produced nothing), not a join mismatch.
        # Reporting it here too would present one failure as two causes and send the next reader
        # after an id-naming problem that does not exist — my own test caught this, twice: the
        # `elif` below has to be inside the same guard, or the empty case just moves to INFO.
        if not e_comps:
            pass
        elif _missed815 and not _matched815:
            _LOG_813.warning(
                "design-prep merge: NONE of the %d enriched component(s) for screen %r matched "
                "the skeleton by id — the analyst answered with ids like %s while the skeleton "
                "uses %s. Every build_notes/typography/copy for this screen is discarded here, "
                "and the frontend prompt still tells the lane to read them.",
                _missed815, s.get("name"),
                sorted(e_comps)[:3] or "[]",
                [c.get("id") for c in (s.get("components") or [])][:3])
        elif _missed815:
            _LOG_813.info(
                "design-prep merge: %d of %d component(s) on screen %r matched by id; %d "
                "enrichment(s) discarded.",
                _matched815, _matched815 + _missed815, s.get("name"), _missed815)
    return ds


_MD_RENDER_MARKER = "<!-- rendered by design-prep (derived from design_system.json) -->"


def _render_design_md(ds: Dict) -> str:
    dsys = ds.get("design_system") or {}
    lines: List[str] = ["# Design System", "", _MD_RENDER_MARKER, ""]
    pal = dsys.get("palette") or {}
    if pal:
        lines.append("## Palette (measured)")
        for k, v in pal.items():
            if isinstance(v, str):
                lines.append(f"- **{k}**: `{v}`")
        lines.append("")
    if dsys.get("type_scale"):
        lines.append("## Type scale")
        for t in dsys["type_scale"]:
            lines.append(f"- {t.get('role')}: {t.get('size_px')}px / {t.get('weight')}")
        lines.append("")
    if dsys.get("theme"):
        lines.append(f"**Theme:** default `{dsys['theme'].get('default')}` "
                     f"({', '.join(dsys['theme'].get('themes') or [])})\n")
    assets = ds.get("assets") or []
    if assets:
        lines.append("## Real assets (staged at `public/assets/`)")
        for a in assets:
            desc = a.get("description") or ""
            use = ", ".join(a.get("use") or [])
            lines.append(f"- `{a.get('id')}` → `{a.get('staged_path')}` — {desc}"
                         + (f" (used: {use})" if use else ""))
        lines.append("")
    for s in ds.get("screens") or []:
        lines.append(f"## Screen: {s.get('name')}")
        if s.get("layout"):
            lines.append(f"_{s['layout']}_\n")
        for c in s.get("components") or []:
            colors = c.get("colors") or {}
            col = " ".join(f"{k}=`{v}`" for k, v in colors.items())
            asset_ids = ", ".join(c.get("assets") or [])
            lines.append(f"### {c.get('id')} — {c.get('role') or ''}")
            if col:
                lines.append(f"- colors (measured): {col}")
            if asset_ids:
                lines.append(f"- assets: {asset_ids}")
            if c.get("build_notes"):
                lines.append(f"- build: {c['build_notes']}")
        lines.append("")
    return "\n".join(lines) + "\n"


# #643 — THE KEYS THE FRAMEWORK ACTUALLY CONSUMES.
# Measured over the 45 delivered `design/design_system.json` files: the analyst writes **82
# distinct keys** under `design_system` and **61 of them (74%) are read by no runtime code** —
# 28% of every key-instance written. The biggest are not typos, they are whole specifications
# that land nowhere: `motion` in **27 of 45 runs**, `collapse_checklist` in 24, `brand_boundary`
# in 8.
#
# The tail is free-form synonym invention, the same shape as #360's rejected tool arguments:
# `spacing` / `spacing_scale` / `spacing_scale_px`, `font_stack` / `font_family` /
# `font_families`, `grid` / `grids`, and one `collapse_checklist_塌缩点`. Only the first of each
# group is read.
#
# Nothing here consumes the extras — that would be feature work. What is wrong is that the
# analyst cannot tell: it spends a section of its output on `motion` in 3 runs out of 5 and
# receives no signal that the framework never looks at it. #360 solved the identical problem for
# tool arguments by DROPPING loudly; this reports at the write boundary.
#
# Derived from the artifacts, and pinned by a test that every name below is genuinely referenced
# in runtime code, so the list cannot rot into a second fiction.
_CONSUMED_DESIGN_KEYS_643 = frozenset({
    "brand", "buttons", "font_stack", "fonts", "geometry", "grid", "header", "hero",
    "iconography", "layout", "layout_metrics", "material", "notes", "palette", "player",
    "radius_scale", "screens", "shadow_scale", "spacing", "theme", "type_scale",
})


def unconsumed_design_keys_643(ds: Dict) -> list:
    """Keys under `design_system` that no runtime code reads. Sorted; [] when all land."""
    try:
        if not isinstance(ds, dict):
            return []
        if "design_system" in ds:
            # Present but malformed is NOT a reason to scan the wrapper: doing that reports
            # `design_system` itself as an unconsumed section.
            inner = ds.get("design_system")
            if not isinstance(inner, dict):
                return []
        else:
            inner = ds          # a flat document (the pre-nesting shape)
        return sorted(k for k in inner if k not in _CONSUMED_DESIGN_KEYS_643)
    except Exception:
        return []


def _write_design_system(design_dir: Path, ds: Dict) -> None:
    try:
        design_dir.mkdir(parents=True, exist_ok=True)
        # #643: say which sections will be ignored, at the moment they are written.
        _ignored = unconsumed_design_keys_643(ds)
        if _ignored:
            try:
                import logging
                logging.getLogger("design_prep").warning(
                    "[design_system] %d section(s) written that NO framework code reads: %s — "
                    "the framework consumes %s. Effort spent on the others does not reach the "
                    "app (#643).", len(_ignored), ", ".join(_ignored[:8]),
                    ", ".join(sorted(_CONSUMED_DESIGN_KEYS_643)))
            except Exception:
                pass
        (design_dir / "design_system.json").write_text(
            json.dumps(ds, indent=2) + "\n", encoding="utf-8")
        # FIX #85c (run-6 live): a design_system.md WITHOUT the render marker is AGENT
        # PROSE (the analyst's hand-written doc — its one real deliverable that run) —
        # never clobber it with the derived render. Marked or absent → (re)render.
        md = design_dir / "design_system.md"
        if md.exists():
            try:
                existing = md.read_text(encoding="utf-8")
            except Exception:
                existing = ""
            if existing.strip() and _MD_RENDER_MARKER not in existing:
                return
        md.write_text(_render_design_md(ds), encoding="utf-8")
    except Exception:
        pass


async def enrich_design_system(skeleton: Dict, resolved: Dict, output_dir, llm, *,
                               docs_text: str = "", max_ref_images: int = 6,
                               max_asset_images: int = 24) -> Dict:
    """Single-shot analyst pass: ONE multimodal call enriches the measured skeleton with per-component
    style/UX prose + component→real-asset mapping + asset annotations, then writes
    design/design_system.json + .md. MEASURED colors always win the merge. Best-effort: on ANY LLM
    error the SKELETON is written (deterministic facts still ship). Never raises."""
    out = Path(output_dir)
    enriched: Optional[Dict] = None
    try:
        enriched = await _run_analyst(skeleton, resolved, out, llm,
                                      docs_text, max_ref_images, max_asset_images)
    except Exception as exc:
        # #819: the WIDEST of the silent skips on this path, and the last one uninstrumented.
        # #813 covers the per-screen call and #815 the per-component join; this discards the
        # enrichment for EVERY screen at once, which matches the corpus signature far better:
        # build_notes lands 1 time in 4,006 components across 12 runs, i.e. essentially never
        # rather than sometimes. "Best-effort, the skeleton still ships" is the right behaviour
        # and is kept — the defect is that it shipped without a word, while the frontend prompt
        # kept telling every lane to read fields that were therefore empty.
        _LOG_813.warning(
            "design-prep analyst pass FAILED WHOLESALE (%s: %s) — every screen keeps its "
            "unenriched skeleton, so NO component in this run carries build_notes/typography/"
            "copy. The measured facts (colors, crops, geometry) still ship.",
            type(exc).__name__, exc)
        enriched = None
        _threw819 = True
    else:
        _threw819 = False
    if not enriched and not _threw819:
        # Only when the call RETURNED empty. Firing this after the wholesale-failure warning too
        # would report one event as two causes — #815's misdiagnosis, same day, same file.
        _LOG_813.warning(
            "design-prep analyst produced NO enrichment for any screen — writing the bare "
            "skeleton. Expect empty build_notes/typography/copy across the whole run.")
    ds = _merge_enrichment(skeleton, enriched) if enriched else skeleton
    _write_design_system(out / "design", ds)
    return ds


# ── phase entry ──────────────────────────────────────────────────────────────
_TEXT_DOC_EXTS = (".md", ".markdown", ".txt", ".rst", ".html", ".htm")


def _read_docs_text(docs: List[str], *, cap: int = 20000) -> str:
    """Concatenate the readable text of the reference docs (md/txt/rst/html) for the analyst.
    Binary docs (pdf) are skipped. Best-effort; bounded to ``cap`` chars."""
    chunks: List[str] = []
    total = 0
    for d in docs or []:
        p = Path(d)
        if p.suffix.lower() not in _TEXT_DOC_EXTS:
            continue
        try:
            txt = p.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        chunks.append(f"### {p.name}\n{txt}")
        total += len(txt)
        if total >= cap:
            break
    return ("\n\n".join(chunks))[:cap]


def write_skeleton_design_system(resolved: Dict, output_dir) -> Dict:
    """Build the deterministic skeleton (measured palette + component regions + staged real
    assets) and WRITE it to design/design_system.json — the starting doc the spawned design_analyst
    agent reads and enriches. Returns the skeleton dict. Best-effort; never raises."""
    out = Path(output_dir)
    skel = build_skeleton_design_system(resolved, out)
    _write_design_system(out / "design", skel)
    return skel


def build_design_analyst_briefing(output_dir, resolved: Dict) -> str:
    """The spawn task description for the design_analyst agent — points it at the staged
    references, the skeleton doc to enrich, the asset manifest, and the output contract."""
    refs = [Path(r).name for r in (resolved.get("references") or [])]
    ref_list = ", ".join(refs) if refs else "(none — proceed from requirements)"
    n_docs = len(resolved.get("docs") or [])
    return (
        "MEASURE a design system from the reference set and emit design/design_system.json + "
        "design/design_system.md.\n\n"
        f"References staged under design/references/ — cover EVERY screen: {ref_list}.\n"
        "A SKELETON design/design_system.json is ALREADY written (staged real assets[] + a measured "
        "palette + component regions). READ it FIRST, then for EACH screen run extract_palette + "
        "decompose_reference, and for EACH component crop_reference + view_image + sample_color "
        "(background row-mode AND accent) + measure_layout where geometry matters, and ENRICH the "
        "doc with the measured per-component spec.\n"
        + (f"Reference docs ({n_docs}) are compiled into design/reference_spec.json — read it.\n" if n_docs else "")
        + "Real assets are staged under design/assets/ (also in design_system.json assets[]) — map "
        "each component's brand elements to their asset ids; never ask a lane to draw a logo.\n"
        "Measure, never guess. Apply the 塌缩点 checklist (dropped semantic color is the #1 collapse). "
        "When every component of every screen is measured + specced and the doc is written, finish()."
    )


# ── FIX #80: deterministic completion pass (model-variance hardening) ────────
# The analyst SHOULD crop+eyedrop+map assets per component, but an LLM that batches
# decompose+palette and finishes early leaves crop=null / colors={} / assets=[] (seen live,
# gemini-3.1 customtools run 2026-07-05). The framework owns the floor: everything below is
# measured/derived deterministically, so the doc's guarantees hold regardless of the model.
_GENERIC_ASSET_TOKENS = {"icon", "icons", "image", "img", "asset", "assets"}


def _asset_tokens(file_name: str) -> List[str]:
    """Meaningful lowercase tokens of an asset filename: 'icons/Also_from_Meta_12cc7c0e.svg'
    → ['also', 'from', 'meta'] (content-hash / numeric suffixes dropped)."""
    import re
    toks = [t.lower() for t in re.split(r"[_\-\s]+", Path(file_name).stem) if t]
    toks = [t for t in toks if not re.fullmatch(r"[0-9a-f]{6,}|\d+", t)]
    return toks


def _component_words(comp: Dict) -> set:
    import re
    text = " ".join(str(comp.get(k) or "") for k in ("id", "role", "state")).lower()
    return set(re.findall(r"[a-z0-9]+", text))


def _reference_path(screen: Dict, resolved: Dict, output_dir: Path) -> Optional[Path]:
    name = str(screen.get("reference") or "")
    if not name:
        return None
    staged = output_dir / "design" / "references" / name
    if staged.is_file():
        return staged
    for r in resolved.get("references") or []:
        if Path(r).name == name and Path(r).is_file():
            return Path(r)
    return None


_SCREEN_STOP_TOKENS = frozenset({
    "screen", "page", "view", "state", "default", "empty", "own", "logged",
    "out", "in", "panel", "grid", "menu", "suggested", "creators", "dm",
})


def _screen_tokens(name: str) -> set:
    """Meaningful tokens of a screen name, for spec matching."""
    parts = [t for t in str(name or "").lower().replace("-", "_").split("_") if t]
    core = {t for t in parts if t not in _SCREEN_STOP_TOKENS}
    return core or set(parts)


def assign_screen_routes(design_screens, spec_screens):
    """Deterministically give every MEASURED screen a route and a kind (#352).

    `missing_design_screen_pages` skips a screen without a route, and
    design_system.json has never carried one -- so the #225 page seeding fired 0
    times in r91/r92/r93/r94. The analyst names screens after reference
    FILENAMES ("explore_grid", "profile_own") while reference_spec.json uses
    logical names ("explore", "profile"), so exact-name matching resolves only 2
    of 11; tokens resolve all 11.

    Assignment is greedy by overlap score with deterministic tie-breaking, and
    each spec route may be claimed once -- r93 has two screens
    (fyp_feed_comments_panel, fyp_feed_logged_out) that both overlap fyp_feed
    and fyp_comments, and they must not collapse onto one route.

    `kind` follows REACHABILITY, not the filename: a screen the spec gives a
    route_hint is addressable by URL, so it is a `page`. Only a screen no route
    can be assigned to is an `overlay`. The previous name-regex rule demoted
    r92's login_modal (route_hint `/login`) to advisory and left the visual
    gate's blocking set empty. Geometry cannot help here -- layout_metrics
    measures the whole screenshot, so a modal is full-canvas like a page.
    """
    out = {}
    designs = [d for d in (design_screens or []) if isinstance(d, dict) and d.get("name")]
    specs = [s for s in (spec_screens or []) if isinstance(s, dict) and s.get("name")
             and str(s.get("route_hint") or "").startswith("/")]
    pairs = []
    for d in designs:
        dt = _screen_tokens(d["name"])
        for sp in specs:
            st = _screen_tokens(sp["name"])
            overlap = len(dt & st)
            if overlap:
                # Jaccard breaks "which spec name is the better fit" ties.
                pairs.append((-overlap, -overlap / max(len(dt | st), 1),
                              str(d["name"]), str(sp["name"])))
    pairs.sort()
    taken_design, taken_route, taken_path = set(), set(), set()
    for _o, _j, dname, sname in pairs:
        if dname in taken_design or sname in taken_route:
            continue
        route = next(s["route_hint"] for s in specs if s["name"] == sname)
        # #355: the PATH part decides page-vs-state. A route that only adds a
        # query/fragment to a path another screen already claims is a STATE of
        # that page (r93's fyp_comments is `/?comments=1` — the comments panel
        # opening over the feed), not a second page. Scaffolding it as a page
        # emitted `<Route path="/?comments=1">`, which React Router matches
        # against the PATHNAME only, so it could never match — a dead route, the
        # exact class the #238 nav gate exists to catch. The full route is kept
        # so the visual gate can still navigate to the state.
        _path = route.split("?", 1)[0].split("#", 1)[0].rstrip("/") or "/"
        _kind = "overlay" if _path in taken_path else "page"
        out[dname] = {"route": route, "kind": _kind, "spec_screen": sname}
        taken_design.add(dname)
        taken_route.add(sname)
        taken_path.add(_path)
    for d in designs:
        if d["name"] in out:
            continue
        # No spec route to claim: not URL-addressable as far as the contract
        # knows, so it is an overlay -- but still give it a slug so downstream
        # seeding can decide, rather than dropping it silently.
        slug = "-".join(t for t in str(d["name"]).lower().replace("_", "-").split("-") if t)
        out[d["name"]] = {"route": f"/{slug}", "kind": "overlay", "spec_screen": None}
    return out


def complete_design_system(ds: Dict, resolved: Dict, output_dir) -> Dict:
    """Deterministically COMPLETE an accepted design_system doc in place (never raises):

     - every component with a region gets a physical crop at design/crops/<screen>__<id>.png
       (existing crops kept) so lanes/gates can view each component in isolation;
     - a component missing colors.bg gets it MEASURED (region_background on its region);
     - a component with assets:[] gets conservative filename-token → id/role/state matches
       (all meaningful tokens must appear as whole words; generic names like icon_* never map);
    then rewrites design_system.json/.md. Measured facts and analyst output are never changed."""
    import logging
    out = Path(output_dir)
    stats = {"components": 0, "cropped": 0, "bg_filled": 0, "asset_mapped": 0,
             "screens_routed": 0}
    # #352: backfill route + kind on every measured screen. The analyst is never
    # asked for them (they exist only in the unused single-shot fallback prompt),
    # so missing_design_screen_pages skipped 11/11 screens and the #225 page
    # seeding fired 0 times in r91/r92/r93/r94. Deterministic; never overwrites a
    # field the analyst DID author.
    try:
        _screens = ds.get("screens") if isinstance(ds, dict) else None
        if isinstance(_screens, list) and _screens:
            _spec_p = out / "design" / "reference_spec.json"
            _spec = []
            if _spec_p.exists():
                import json as _json
                _spec = (_json.loads(_spec_p.read_text(encoding="utf-8")) or {}).get("screens") or []
            _assigned = assign_screen_routes(_screens, _spec)
            for _s in _screens:
                if not isinstance(_s, dict):
                    continue
                _a = _assigned.get(str(_s.get("name") or ""))
                if not _a:
                    continue
                if not str(_s.get("route") or "").strip():
                    _s["route"] = _a["route"]
                    stats["screens_routed"] += 1
                if not str(_s.get("kind") or "").strip():
                    _s["kind"] = _a["kind"]
    except Exception:
        pass  # backfill is best-effort; never block design-prep on it
    try:
        from .material_prep import _open_rgb, crop_region, region_background
        import re as _re

        asset_toks = []
        for a in ds.get("assets") or []:
            toks = _asset_tokens(str(a.get("file") or a.get("id") or ""))
            if toks and not set(toks) <= _GENERIC_ASSET_TOKENS:
                asset_toks.append((a.get("id"), toks))

        for screen in ds.get("screens") or []:
            ref = _reference_path(screen, resolved or {}, out)
            im = None
            if ref is not None:
                try:
                    im = _open_rgb(ref)
                except Exception:
                    im = None
            sname = _re.sub(r"[^A-Za-z0-9_\-]", "-", str(screen.get("name") or "screen"))
            for comp in screen.get("components") or []:
                stats["components"] += 1
                region = comp.get("region")
                region = tuple(region) if isinstance(region, (list, tuple)) and len(region) == 4 else None

                crop_rel = comp.get("crop")
                if not (crop_rel and (out / crop_rel).is_file()):
                    comp_crop = None
                    if ref is not None and region:
                        cid = _re.sub(r"[^A-Za-z0-9_\-]", "-", str(comp.get("id") or "component"))
                        rel = f"design/crops/{sname}__{cid}.png"
                        try:
                            crop_region(ref, region, out / rel)
                            comp_crop = rel
                            stats["cropped"] += 1
                        except Exception:
                            comp_crop = None
                    comp["crop"] = comp_crop

                colors = comp.setdefault("colors", {})
                if not colors.get("bg") and im is not None and region:
                    bg = region_background(im, region)
                    if bg:
                        colors["bg"] = bg
                        stats["bg_filled"] += 1

                if not comp.get("assets") and asset_toks:
                    words = _component_words(comp)
                    matched = [aid for aid, toks in asset_toks if all(t in words for t in toks)]
                    if matched:
                        comp["assets"] = matched
                        stats["asset_mapped"] += 1

        _write_design_system(out / "design", ds)
        logging.getLogger("Orchestrator").info(
            "Design-Prep completion pass: %(components)d components — %(cropped)d cropped, "
            "%(bg_filled)d bg measured, %(asset_mapped)d asset-mapped (deterministic floor)", stats)
    except Exception:
        pass
    return ds


def design_system_is_enriched(ds) -> bool:
    """FIX #85a — deterministic ENRICHMENT verdict on an accepted design doc.

    Run-5/run-6 (live, identical signature): the design_analyst finished 'successfully'
    but never touched design_system.json — a MALFORMED-degraded planning step, the
    resident-protocol overhead, and a no-execution-tool dead end (it authored
    measure_and_enrich.py it could never run) left build_notes 0/98 and
    type_scale/radius_scale/iconography empty. The orchestrator's fallback keyed only on
    PARSEABILITY, so the hollow doc sailed through. Enriched == at least one component
    carries build_notes OR a design_system scale/iconography is non-empty."""
    if not isinstance(ds, dict):
        return False
    dsys = ds.get("design_system") or {}
    if any(dsys.get(k) for k in ("type_scale", "radius_scale", "shadow_scale", "iconography")):
        return True
    for s in ds.get("screens") or []:
        for c in (s.get("components") or []) if isinstance(s, dict) else []:
            if isinstance(c, dict) and (c.get("build_notes") or c.get("typography")):
                return True
    return False


def load_valid_design_system(path) -> Optional[Dict]:
    """Load design_system.json ONLY if it parses AND is structurally a design doc (has a
    ``design_system`` block or ``screens``). Returns None on a missing/unreadable/malformed file
    or a non-design shape — so a spawned agent that wrote garbage JSON is DETECTED and the caller
    can rebuild (single-shot) instead of discarding the whole phase to references-only."""
    try:
        d = json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return None
    return d if isinstance(d, dict) and (d.get("design_system") or d.get("screens")) else None


def design_system_summary_for_requirements(ds: Dict) -> str:
    """Compact BINDING block appended to the requirements every lane reads (mirrors
    reference_materials.spec_summary_for_requirements) — so the measured design system drives the
    build from the first turn instead of depending on a voluntary file read. ``""`` when empty."""
    if not isinstance(ds, dict):
        return ""
    dsys = ds.get("design_system") or {}
    screens = ds.get("screens") or []
    if not (dsys.get("palette") or screens):
        return ""
    lines = ["\n\n## DESIGN SYSTEM (measured from the references — BINDING; build to these MEASURED "
             "values, never change a measured hex)"]
    pal = dsys.get("palette") or {}
    pal_txt = ", ".join(f"{k}={v}" for k, v in pal.items() if isinstance(v, str))
    if pal_txt:
        lines.append("Palette (measured): " + pal_txt[:800])
    theme = dsys.get("theme") or {}
    if theme.get("default"):
        lines.append(f"Theme: {theme.get('default')} ({', '.join(theme.get('themes') or [])})")
    if dsys.get("type_scale"):
        lines.append("Type scale: " + ", ".join(
            f"{t.get('role')} {t.get('size_px')}px/{t.get('weight')}"
            for t in dsys["type_scale"] if isinstance(t, dict))[:400])
    if dsys.get("material"):
        lines.append("Material: " + str(dsys["material"])[:200])
    assets = [a for a in (ds.get("assets") or []) if isinstance(a, dict)]
    if assets:
        lines.append("Real assets (STAGED at public/assets/ — reference them, do NOT draw): " + ", ".join(
            f"{a.get('id')}→/assets/{a.get('file')}" for a in assets[:24])[:1200])
    for s in screens[:12]:
        comps = [c for c in (s.get("components") or []) if isinstance(c, dict)]
        if not comps:
            continue
        parts = []
        for c in comps[:10]:
            col = c.get("colors") or {}
            cc = "/".join(f"{k}:{v}" for k, v in col.items()) if col else ""
            am = "+".join(c.get("assets") or [])
            parts.append(f"{c.get('id')}[{cc}{('|' + am) if am else ''}]")
        lines.append(f"{s.get('name')}: " + " ".join(parts)[:600])
    lines.append("Full doc: design/design_system.json (+ .md); crops: design/crops/. "
                 "MEASURE, DON'T GUESS — the colors are sampled truth.")

    # F2b: a real dataset AUTHORITATIVELY defines the schema of the tables it fills.
    # Without this the backend lane builds its own guessed columns and the framework's
    # real rows (seed_dataset.json) can't be inserted (column mismatch — googlemaps
    # run-1: places had no `category` column, 0 rows loaded). State the EXACT tables +
    # columns so the contract matches the data and the loader inserts cleanly.
    from pathlib import Path as _P
    dataset = [d for d in (ds.get("dataset") or [])
               if isinstance(d, dict) and d.get("columns")]
    if dataset:
        lines.append(
            "\n\n## REAL DATASET (BINDING — these tables are seeded from REAL data staged "
            "at app/backend/seed_dataset.json, which the framework loads AUTOMATICALLY):")
        for d in dataset[:20]:
            table = _P(str(d.get("file") or "")).stem or str(d.get("id") or "")
            cols = ", ".join(str(c) for c in (d.get("columns") or [])[:40])
            n = d.get("records")
            lines.append(f"- table `{table}` ({n} real rows) — build it with EXACTLY these "
                         f"columns (match names + plausible types): {cols}")
        lines.append(
            "RULES: (1) the backend MUST create these tables with these EXACT column names "
            "(add a primary key + any FK/owner columns you need, but do NOT rename or drop "
            "the listed columns) so the real rows load. (2) do NOT author these tables' rows "
            "in seed_data.json — the framework seeds them from seed_dataset.json; you only "
            "author users + any association/child rows the app needs. (3) the frontend reads "
            "these exact field names from the API responses.")
    return "\n".join(lines)


async def run_design_prep(design_input: Optional[str], reference_dir: Optional[str],
                          reference_images: Optional[List[str]], output_dir, llm) -> Dict:
    """The one-shot Design-Prep phase: resolve inputs → deterministic measured skeleton (reusing any
    design/component_specs the upstream precompute wrote + staging real assets) → single-shot analyst
    enrichment → emit design/design_system.json + .md. Returns the design_system dict; ``{}`` on total
    failure (the run continues references-only). Best-effort; never raises into the caller."""
    try:
        resolved = resolve_design_input(design_input, reference_dir, reference_images)
        docs_text = _read_docs_text(resolved.get("docs") or [])
        skeleton = build_skeleton_design_system(resolved, output_dir)
        return await enrich_design_system(skeleton, resolved, output_dir, llm, docs_text=docs_text)
    except Exception:
        return {}
