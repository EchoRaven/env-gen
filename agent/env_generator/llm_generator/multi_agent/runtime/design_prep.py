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
    resp = await client.chat([Message.user_multimodal(parts)], temperature=0.0, max_tokens=4000)
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


def _render_design_md(ds: Dict) -> str:
    dsys = ds.get("design_system") or {}
    lines: List[str] = ["# Design System", ""]
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
        (design_dir / "design_system.md").write_text(_render_design_md(ds), encoding="utf-8")
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
