"""Pre-generation MATERIAL-PREP phase (USER directive 2026-06-29) — brick 1: MEASURED
color extraction from reference screenshots.

Methodology: /data/common/haibotong/outlook_components/PIPELINE.md §3 ("最关键：别猜颜色").
The #1 systematic error in page-mimicry is GUESSING colors, or single-point sampling that
catches the wallpaper bleeding through a translucent (Mica) panel → a wrong navy chrome that
should be neutral gray. The fix is deterministic measurement:
  * BACKGROUND  → ROW-MODE: the most-frequent color along a horizontal row IS the true
    opaque background (ignores icons/text/translucency noise).
  * ACCENT/BUTTON → SATURATION SCAN: the most-saturated pixel of a target hue is the
    accent/primary color.

Pure + deterministic (PIL only, no LLM, no network). The component DECOMPOSITION + spec
generation (brick 2, gemini vision) consumes these measured tokens so the spec's colors are
truth, not the model's guess. Best-effort: returns {} / None rather than raising.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Dict, Optional, Tuple

Region = Tuple[float, float, float, float]  # (x0,y0,x1,y1) as 0..1 fractions


def _hex(rgb) -> str:
    r, g, b = (int(rgb[0]), int(rgb[1]), int(rgb[2]))
    return f"#{r:02x}{g:02x}{b:02x}"


def _open_rgb(image_path):
    from PIL import Image
    return Image.open(image_path).convert("RGB")


def row_mode_color(im, fy: float, x0f: float = 0.0, x1f: float = 1.0, step: int = 2) -> Optional[str]:
    """Most-frequent color along the horizontal row at fraction ``fy`` (the TRUE opaque
    background of a chrome strip). PIPELINE.md §3.1 row-mode sampling."""
    W, H = im.size
    y = min(H - 1, max(0, int(fy * H)))
    cnt: Counter = Counter()
    x1 = max(int(x0f * W) + 1, int(x1f * W))
    for x in range(int(x0f * W), min(W, x1), max(1, step)):
        cnt[im.getpixel((x, y))] += 1
    if not cnt:
        return None
    return _hex(cnt.most_common(1)[0][0])


def region_background(im, region: Optional[Region] = None, rows: int = 9) -> Optional[str]:
    """Background of a region = the most common ROW-MODE color across ``rows`` evenly-spaced
    rows (robust to a band of icons/text). region defaults to the whole image."""
    x0, y0, x1, y1 = region or (0.0, 0.0, 1.0, 1.0)
    votes: Counter = Counter()
    for i in range(rows):
        fy = y0 + (y1 - y0) * (i + 0.5) / rows
        c = row_mode_color(im, fy, x0, x1)
        if c:
            votes[c] += 1
    if not votes:
        return None
    return votes.most_common(1)[0][0]


_HUE_TESTS = {
    # name -> predicate(r,g,b) for "is this pixel that hue", + score(r,g,b) "how much"
    "blue":   (lambda r, g, b: b > 110 and b - r > 35 and g < b, lambda r, g, b: b - (r + g) // 2),
    "red":    (lambda r, g, b: r > 120 and r - g > 45 and r - b > 45, lambda r, g, b: r - (g + b) // 2),
    "green":  (lambda r, g, b: g > 110 and g - r > 35 and g - b > 25, lambda r, g, b: g - (r + b) // 2),
    "purple": (lambda r, g, b: r > 90 and b > 110 and g < r and g < b, lambda r, g, b: (r + b) // 2 - g),
    "gold":   (lambda r, g, b: r > 150 and g > 110 and b < 100, lambda r, g, b: (r + g) // 2 - b),
}


def find_accent(im, region: Optional[Region] = None, hue: str = "blue", step: int = 3) -> Optional[str]:
    """The most-SATURATED pixel of ``hue`` in the region = the accent/button color. The
    methodology's saturation scan (PIPELINE.md §3.1) — catches the royal-blue New-mail button
    / the periwinkle link that a mode/average would wash out. Returns None if no such hue."""
    test = _HUE_TESTS.get(hue)
    if test is None:
        return None
    pred, score = test
    W, H = im.size
    x0, y0, x1, y1 = region or (0.0, 0.0, 1.0, 1.0)
    best = None
    for x in range(int(x0 * W), int(x1 * W), max(1, step)):
        for y in range(int(y0 * H), int(y1 * H), max(1, step)):
            r, g, b = im.getpixel((x, y))
            if pred(r, g, b):
                s = score(r, g, b)
                if best is None or s > best[0]:
                    best = (s, (r, g, b))
    return _hex(best[1]) if best else None


def extract_palette(image_path, regions: Optional[Dict[str, Region]] = None,
                    accent_hues=("blue", "red", "green", "purple", "gold")) -> Dict[str, object]:
    """Measured palette for a reference screenshot — NEVER guessed. With ``regions`` (a
    {name: (x0,y0,x1,y1)} map, e.g. PIPELINE.md's per-component crops) returns a per-region
    background; always returns the dominant background + every accent hue present. Feeds the
    component spec (brick 2) so its color tokens are truth. Best-effort; {} on any error."""
    try:
        im = _open_rgb(image_path)
    except Exception as exc:
        return {"error": f"{type(exc).__name__}: {exc}"}
    out: Dict[str, object] = {"background": region_background(im)}
    accents: Dict[str, str] = {}
    for hue in accent_hues:
        c = find_accent(im, None, hue)
        if c:
            accents[hue] = c
    out["accents"] = accents
    if regions:
        per: Dict[str, Dict[str, object]] = {}
        for name, reg in regions.items():
            per[name] = {"background": region_background(im, reg),
                         "accent_blue": find_accent(im, reg, "blue")}
        out["regions"] = per
    return out


def crop_region(image_path, region: Region, save_path) -> Tuple[int, int]:
    """Crop a (x0,y0,x1,y1)-FRACTION region from ``image_path`` and save it to
    ``save_path`` (parent dirs created). PIPELINE.md §2 component cropping — crop the
    reference into named components so each can be studied/specced/diffed in isolation
    (the whole page is too big for the eye/agent to hold). Crop a touch LOOSE (include a
    little boundary) so a 1% misalignment doesn't slice the component. Returns the saved
    crop's (w, h). Raises on a bad path/region (the caller/tool turns it into a ToolResult)."""
    im = _open_rgb(image_path)
    W, H = im.size
    x0, y0, x1, y1 = region
    box = (max(0, int(x0 * W)), max(0, int(y0 * H)),
           min(W, int(x1 * W)), min(H, int(y1 * H)))
    if box[2] <= box[0] or box[3] <= box[1]:
        raise ValueError(f"empty crop region {region} on a {W}x{H} image")
    crop = im.crop(box)
    Path(save_path).parent.mkdir(parents=True, exist_ok=True)
    crop.save(save_path)
    return crop.size


_DECOMPOSE_PROMPT = (
    "You are a UI component analyst preparing a build spec from a REFERENCE screenshot.\n"
    "Decompose this screen into its distinct, NAMED UI components, top-to-bottom / left-to-right "
    "(e.g. top_bar, nav_rail, command_ribbon, folder_pane, list_header, message_row, reading_pane, "
    "calendar_grid, sign_in_card — use the names that fit THIS app).\n"
    "For EACH component output an object: {\"name\": snake_case, \"region\": [x0,y0,x1,y1] as 0..1 "
    "FRACTIONS of width/height (a loose bounding box — include a little margin), \"role\": one short "
    "line of what it is + its layout, \"state\": notable state the data shows (e.g. 'mostly UNREAD "
    "→ blue-dominant', 'one row selected/highlighted', 'empty reading pane with wallpaper')}.\n"
    "Do NOT report colors — the framework MEASURES those from your regions (your color guesses are "
    "unreliable). Cover the WHOLE screen; 6-14 components. Output ONLY a JSON array, nothing else."
)


async def decompose_reference(image_path, llm, *, max_components: int = 14):
    """Decompose a reference screenshot into named UI components with MEASURED colors per
    component (PIPELINE.md §2-4 stage output — the per-component build spec the frontend lane
    consumes). Gemini-vision identifies each component + its region + role + state; this then
    MEASURES the background + accent hues from each region with material_prep (truth, not the
    model's color guess — the #1 fidelity mistake). Returns ``{components: [...], count}`` or
    ``{error: ...}``. Async (one vision call); best-effort, never raises into the caller."""
    import base64
    import json
    import re
    try:
        from utils.llm import Message
    except Exception as exc:
        return {"error": f"import failed: {exc}"}
    try:
        _src = str(image_path)
        try:  # use the shared LLM image-compression cache when available (big references)
            from tools.file_tools import _compressed_image_for_llm
            _src = _compressed_image_for_llm(_src) or _src
        except Exception:
            pass
        with open(_src, "rb") as _f:
            _b64 = base64.b64encode(_f.read()).decode()
    except Exception as exc:
        return {"error": f"read image failed: {exc}"}
    parts = [
        {"type": "text", "text": _DECOMPOSE_PROMPT},
        {"type": "image_url",
         "image_url": {"url": f"data:image/png;base64,{_b64}", "detail": "high"}},
    ]
    try:
        client = getattr(llm, "_client", llm)
        resp = await client.chat([Message.user_multimodal(parts)], temperature=0.0, max_tokens=3000)
        text = getattr(resp, "content", "") or ""
    except Exception as exc:
        return {"error": f"vision call failed: {type(exc).__name__}: {exc}"}
    m = re.search(r"\[.*\]", text, re.DOTALL)
    if not m:
        return {"error": "no component JSON array in the vision response", "raw": text[:200]}
    try:
        comps = json.loads(m.group(0))
    except Exception as exc:
        return {"error": f"component JSON parse failed: {exc}", "raw": m.group(0)[:200]}
    try:
        im = _open_rgb(str(image_path))
    except Exception as exc:
        return {"error": f"open image failed: {exc}"}
    out = []
    for c in (comps if isinstance(comps, list) else [])[:max_components]:
        if not isinstance(c, dict):
            continue
        reg = c.get("region")
        rt = None
        try:
            if reg and len(reg) >= 4:
                rt = tuple(min(1.0, max(0.0, float(v))) for v in reg[:4])
                if rt[2] <= rt[0] or rt[3] <= rt[1]:
                    rt = None
        except Exception:
            rt = None
        bg = region_background(im, rt) if rt else region_background(im)
        accents = {h: find_accent(im, rt, h) for h in ("blue", "red", "green", "purple", "gold")}
        accents = {h: v for h, v in accents.items() if v}
        out.append({"name": c.get("name"), "region": list(rt) if rt else None,
                    "role": c.get("role"), "state": c.get("state"),
                    "background": bg, "accents": accents})
    return {"components": out, "count": len(out)}


def _rgb_of_hex(h: str) -> Optional[Tuple[int, int, int]]:
    try:
        s = str(h).strip().lstrip("#")
        if len(s) != 6:
            return None
        return (int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16))
    except Exception:
        return None


def color_distance(hex_a: str, hex_b: str) -> Optional[float]:
    """Perceptual-ish distance between two #rrggbb colors ("redmean" — the
    standard cheap approximation; 0 = identical, ~765 = black↔white). PIL-only,
    no numpy. None when either hex is unparseable."""
    a, b = _rgb_of_hex(hex_a), _rgb_of_hex(hex_b)
    if a is None or b is None:
        return None
    rbar = (a[0] + b[0]) / 2.0
    dr, dg, db = a[0] - b[0], a[1] - b[1], a[2] - b[2]
    return ((2 + rbar / 256.0) * dr * dr + 4 * dg * dg
            + (2 + (255 - rbar) / 256.0) * db * db) ** 0.5


def spec_color_deviations(spec, screenshot_path, *, threshold: Optional[float] = None,
                          min_region_frac: float = 0.005):
    """Deterministic per-component color diff: the pre-measured reference spec
    (design/component_specs/<screen>.json — regions are 0..1 FRACTIONS, so they
    apply to a screenshot of ANY resolution) vs the SAME region sampled from the
    implementation screenshot. PIPELINE.md §11's "determinist color-diff gate":
    the LLM judge gives an OPINION; this gives NAMED, MEASURED facts the fixing
    lane can act on exactly ("top_bar renders #ffffff, reference measures
    #292929"). Two deviation kinds:
      * background — row-mode background of the region differs beyond
        ``threshold`` (redmean; env ENVGEN_COLOR_DIFF_THRESHOLD, default 40 —
        catches any real token drift, tolerates sampling noise);
      * accent_missing — the spec measured a saturated accent of some hue in
        the region but the screenshot has NO pixel of that hue there NOR
        anywhere on the screen (the methodology's #1 collapse point: SEMANTIC
        COLOR LOSS — unread-blue / ribbon reds going all-gray). The whole-image
        condition filters CONTENT noise: a reference avatar/photo seeds spec
        accents (red/gold skin tones) that are user content, not design — if
        the hue exists elsewhere on the implemented screen it is not a loss.
    Regions smaller than ``min_region_frac`` of the image are skipped (too small
    to sample reliably once layouts differ slightly). NOTE: values are
    trustworthy once the layout ROUGHLY matches the reference (the polish phase
    this exists for); on a structurally-unrelated screen the judge's structural
    verdict is the signal, not these. Best-effort: [] on any failure."""
    if threshold is None:
        import os as _os
        try:
            threshold = float(_os.environ.get("ENVGEN_COLOR_DIFF_THRESHOLD", "40"))
        except Exception:
            threshold = 40.0
    try:
        im = _open_rgb(screenshot_path)
    except Exception:
        return []
    out = []
    _hue_on_screen: Dict[str, bool] = {}  # whole-image accent presence, per hue

    def _present_anywhere(hue: str) -> bool:
        if hue not in _hue_on_screen:
            _hue_on_screen[hue] = find_accent(im, None, hue) is not None
        return _hue_on_screen[hue]

    comps = (spec or {}).get("components") if isinstance(spec, dict) else None
    for c in comps or []:
        if not isinstance(c, dict):
            continue
        reg = c.get("region")
        try:
            if not reg or len(reg) < 4:
                continue
            rt = tuple(min(1.0, max(0.0, float(v))) for v in reg[:4])
            if rt[2] <= rt[0] or rt[3] <= rt[1]:
                continue
            if (rt[2] - rt[0]) * (rt[3] - rt[1]) < min_region_frac:
                continue
        except Exception:
            continue
        name = str(c.get("name") or "component")
        try:
            spec_bg = c.get("background")
            if spec_bg:
                actual = region_background(im, rt)
                dist = color_distance(spec_bg, actual) if actual else None
                if dist is not None and dist > threshold:
                    out.append({"component": name, "kind": "background",
                                "expected": spec_bg, "actual": actual,
                                "distance": round(dist, 1), "region": list(rt)})
            for hue, spec_hex in (c.get("accents") or {}).items():
                if hue not in _HUE_TESTS or not spec_hex:
                    continue
                if find_accent(im, rt, hue) is None and not _present_anywhere(hue):
                    out.append({"component": name, "kind": "accent_missing",
                                "hue": hue, "expected": spec_hex,
                                "region": list(rt)})
        except Exception:
            continue
    return out


def _resize_to_width(im, w: int):
    w = max(1, int(w))
    return im.resize((w, max(1, int(im.height * w / max(1, im.width)))))


def make_side_by_side(ref_path, mine_path, save_path, *, region: Optional[Region] = None,
                      scale: int = 1, width: int = 760) -> Tuple[int, int]:
    """Build a labeled REFERENCE-over-MINE comparison image and save it (PIPELINE.md §5.2): the
    eye (and a critic agent) catch differences 10x faster on a side-by-side than from prose.
    With ``region`` (0..1 fractions, applied to EACH image) it crops the SAME component out of
    both; with ``scale``>1 it 2x/3x-ZOOMS both first — that's the §6 per-component zoom diff
    that exposes the micro-differences a whole-page diff misses (semantic-color loss, density,
    a missing star/icon). Both panes are normalized to ``width``. Returns the saved (w,h).
    Raises on bad input (the tool turns it into a ToolResult)."""
    from PIL import Image, ImageDraw
    r = _open_rgb(ref_path)
    m = _open_rgb(mine_path)
    if region is not None:
        x0, y0, x1, y1 = region
        def _cr(im):
            W, H = im.size
            box = (max(0, int(x0 * W)), max(0, int(y0 * H)), min(W, int(x1 * W)), min(H, int(y1 * H)))
            if box[2] <= box[0] or box[3] <= box[1]:
                raise ValueError(f"empty crop region {region}")
            return im.crop(box)
        r, m = _cr(r), _cr(m)
    if scale and scale > 1:
        r = r.resize((r.width * scale, r.height * scale))
        m = m.resize((m.width * scale, m.height * scale))
    r = _resize_to_width(r, width)
    m = _resize_to_width(m, width)
    lab = 22
    canvas = Image.new("RGB", (width, r.height + m.height + lab * 2 + 6), (45, 45, 45))
    d = ImageDraw.Draw(canvas)
    d.text((6, 4), "REFERENCE:", fill=(220, 220, 120))
    canvas.paste(r, (0, lab))
    d.text((6, lab + r.height + 4), "MINE:", fill=(120, 200, 255))
    canvas.paste(m, (0, lab * 2 + r.height + 6))
    Path(save_path).parent.mkdir(parents=True, exist_ok=True)
    canvas.save(save_path)
    return canvas.size


__all__ = ["row_mode_color", "region_background", "find_accent", "extract_palette",
           "crop_region", "decompose_reference", "make_side_by_side",
           "color_distance", "spec_color_deviations"]
