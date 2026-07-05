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
