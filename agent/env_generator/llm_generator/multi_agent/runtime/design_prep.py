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

    try:
        if design_input:
            root = Path(design_input)
            references = _list_files(root / "references", _IMG_EXTS)
            docs = _list_files(root / "docs", _DOC_EXTS)
            adir = root / "assets"
            assets_dir = str(adir) if adir.is_dir() else None
            return {"references": references, "docs": docs, "assets_dir": assets_dir}

        # back-compat: references-only
        references = list(reference_images or [])
        if reference_dir:
            references.extend(_list_files(Path(reference_dir), _IMG_EXTS))
    except Exception:
        pass
    return {"references": references, "docs": docs, "assets_dir": assets_dir}


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


def _skeleton_components(spec: Optional[Dict]) -> List[Dict]:
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
            "assets": [],              # analyst maps real assets here
            "role": c.get("role") or "",
            "state": c.get("state") or "",
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

    palette = _measure_palette(references)
    theme = _theme_from_palette(palette)

    specs = existing_specs if existing_specs is not None else _load_component_specs(out)
    screens: List[Dict] = []
    for ref in references:
        stem = Path(ref).stem
        screens.append({
            "name": stem,
            "reference": Path(ref).name,
            "layout": "",
            "components": _skeleton_components(specs.get(stem)),
        })

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


async def _run_analyst(skeleton: Dict, resolved: Dict, output_dir: Path, llm,
                       docs_text: str, max_ref_images: int, max_asset_images: int) -> Optional[Dict]:
    import re
    from utils.llm import Message

    parts: List[Dict] = [{"type": "text", "text": _ANALYST_PROMPT}]
    parts.append({"type": "text",
                  "text": "SKELETON (measured facts):\n" + json.dumps(skeleton, indent=2)[:12000]})
    if docs_text:
        parts.append({"type": "text", "text": "REFERENCE DOCS:\n" + docs_text[:8000]})

    for ref in (resolved.get("references") or [])[:max_ref_images]:
        p = _img_part(ref)
        if p:
            parts.append({"type": "text", "text": f"REFERENCE screen: {Path(ref).name}"})
            parts.append(p)

    # raster asset images only (svg/vector go to the model as manifest text)
    assets_dir = output_dir / "design" / "assets"
    shown = 0
    for a in skeleton.get("assets") or []:
        if shown >= max_asset_images:
            break
        if a.get("type") in ("svg",):
            continue
        ap = assets_dir / a.get("file", "")
        part = _img_part(str(ap)) if ap.is_file() else None
        if part:
            parts.append({"type": "text", "text": f"ASSET id={a.get('id')} file={a.get('file')}"})
            parts.append(part)
            shown += 1

    client = getattr(llm, "_client", llm)
    # FIX #88: JSON mode + a 16k output budget. Run-8 live: the -customtools model emitted
    # a TOOL CALL on this no-tools call (20 tokens, finish=tool_calls) → regex found no
    # JSON → silent skeleton; and 4k max_tokens cannot hold a ~93-component enriched doc
    # (truncated JSON parses to None the same silent way). Providers without the kwarg
    # degrade gracefully (TypeError → plain retry).
    _msgs = [Message.user_multimodal(parts)]
    try:
        resp = await client.chat(_msgs, temperature=0.0, max_tokens=16000,
                                 response_mime_type="application/json")
    except TypeError:
        resp = await client.chat(_msgs, temperature=0.0, max_tokens=16000)
    text = getattr(resp, "content", "") or ""
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except Exception:
        return None


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
        e_comps = {c.get("id"): c for c in (es.get("components") or []) if isinstance(c, dict)}
        for c in s.get("components") or []:
            ec = e_comps.get(c.get("id"))
            if not ec:
                continue
            for k in ("role", "build_notes", "state", "typography", "assets", "crop"):
                if ec.get(k) is not None:
                    c[k] = ec[k]
            # measured colors are immutable — c["colors"] is never replaced
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


def _write_design_system(design_dir: Path, ds: Dict) -> None:
    try:
        design_dir.mkdir(parents=True, exist_ok=True)
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
    except Exception:
        enriched = None
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
    stats = {"components": 0, "cropped": 0, "bg_filled": 0, "asset_mapped": 0}
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
