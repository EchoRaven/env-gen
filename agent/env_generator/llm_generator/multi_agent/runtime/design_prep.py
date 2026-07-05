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
