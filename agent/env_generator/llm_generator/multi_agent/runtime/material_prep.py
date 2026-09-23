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

import json
import re
import shutil
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

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
    "unreliable). Cover the WHOLE screen; 6-24 components — use MORE for dense screens (a browse "
    "page with many rails, each rail a distinct component; individual hero/nav/card regions). "
    "Output ONLY a JSON array, nothing else."
)


async def decompose_reference(image_path, llm, *, max_components: int = 24):
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


def _luminance(hex_c: str) -> Optional[float]:
    """Perceived luminance 0..255 of a #rrggbb color (Rec. 601). None if bad."""
    rgb = _rgb_of_hex(hex_c)
    if rgb is None:
        return None
    return 0.299 * rgb[0] + 0.587 * rgb[1] + 0.114 * rgb[2]


def theme_inversion(deviations, *, light_thresh: float = 150.0,
                    dark_thresh: float = 105.0, min_bg: int = 3) -> Optional[str]:
    """Fix #65 — detect a WHOLESALE light/dark theme inversion from the measured
    background deviations (material-prep methodology: 'large-area background is
    the #1 similarity lever'). When most component backgrounds are inverted the
    SAME way — the build renders light where the reference is dark (or vice
    versa) — the app is on the WRONG BASE THEME, and a scattered per-component
    color list buries that under noise (outlook run-50: every page 0.20, every
    top_bar/nav_rail rendered #ffffff vs a #292929/#09101a dark reference — the
    run's text said 'light theme' but the references are dark Outlook). Returns
    'light'/'dark' (the theme the REFERENCE wants and the build lacks) when >=
    min_bg background deviations exist and >= 2/3 are same-direction inversions;
    else None. Env-agnostic; feeds a single high-signal remediation line."""
    bg = [d for d in (deviations or []) if isinstance(d, dict)
          and d.get("kind") == "background" and d.get("actual") and d.get("expected")]
    if len(bg) < min_bg:
        return None
    build_light_ref_dark = 0   # build renders light, reference is dark → want DARK
    build_dark_ref_light = 0   # build renders dark, reference is light → want LIGHT
    for d in bg:
        la = _luminance(d["actual"])       # what the build renders
        le = _luminance(d["expected"])     # what the reference measures
        if la is None or le is None:
            continue
        if la >= light_thresh and le <= dark_thresh:
            build_light_ref_dark += 1
        elif la <= dark_thresh and le >= light_thresh:
            build_dark_ref_light += 1
    n = len(bg)
    if build_light_ref_dark >= max(min_bg, (2 * n + 2) // 3):
        return "dark"
    if build_dark_ref_light >= max(min_bg, (2 * n + 2) // 3):
        return "light"
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


# ── §15 PIL layout measurement (columns / width / spacing) — theme-agnostic ──
def _rgb_dist(a, b) -> float:
    """redmean distance between two RGB tuples (0=identical). No hex round-trip (fast per-pixel)."""
    rm = (a[0] + b[0]) / 2.0
    dr, dg, db = a[0] - b[0], a[1] - b[1], a[2] - b[2]
    return ((2 + rm / 256) * dr * dr + 4 * dg * dg + (2 + (255 - rm) / 256) * db * db) ** 0.5


def _region_px(im, region):
    W, H = im.size
    x0, y0, x1, y1 = region or (0.0, 0.0, 1.0, 1.0)
    return (max(0, int(x0 * W)), max(0, int(y0 * H)),
            min(W, int(x1 * W)), min(H, int(y1 * H)))


def _bg_rgb(im, region):
    hexc = region_background(im, region)
    rgb = _rgb_of_hex(hexc) if hexc else None
    return rgb or (0, 0, 0)


def content_bounds(im, region: Optional[Region] = None, *, thresh: float = 60.0,
                   step: int = 2) -> Dict[str, object]:
    """Bounding box of CONTENT (pixels far from the region's measured background) — §15① content
    width/edges. Returns px + 0..1 fractions (of the FULL image), or {"content": False} if empty."""
    W, H = im.size
    px0, py0, px1, py1 = _region_px(im, region)
    bg = _bg_rgb(im, region)
    minx = miny = 10 ** 9
    maxx = maxy = -1
    for y in range(py0, py1, step):
        for x in range(px0, px1, step):
            if _rgb_dist(im.getpixel((x, y)), bg) > thresh:
                if x < minx: minx = x
                if x > maxx: maxx = x
                if y < miny: miny = y
                if y > maxy: maxy = y
    if maxx < 0:
        return {"content": False}
    return {"content": True,
            "left_px": minx, "right_px": maxx, "top_px": miny, "bottom_px": maxy,
            "width_px": maxx - minx, "height_px": maxy - miny,
            "left": round(minx / W, 4), "right": round(maxx / W, 4),
            "top": round(miny / H, 4), "bottom": round(maxy / H, 4),
            "width": round((maxx - minx) / W, 4), "height": round((maxy - miny) / H, 4)}


def _bands(counts, coords, *, min_run: int = 1):
    """Group consecutive 'has-content' samples into bands → list of (start,end,center)."""
    bands = []
    run_start = None
    for i, c in enumerate(counts):
        if c:
            if run_start is None:
                run_start = i
        else:
            if run_start is not None:
                if i - run_start >= min_run:
                    bands.append((coords[run_start], coords[i - 1]))
                run_start = None
    if run_start is not None and len(coords) - run_start >= min_run:
        bands.append((coords[run_start], coords[-1]))
    return [(s, e, (s + e) // 2) for s, e in bands]


def grid_columns(im, region: Optional[Region] = None, *, thresh: float = 60.0,
                 step: int = 2, min_fill: float = 0.15) -> Dict[str, object]:
    """Count content columns of a grid — §15② (推翻 '3列' → 数出真列数). Content columns (x with
    >``min_fill`` content-vs-bg rows) form bands; ``columns`` = the band count, and ``pitch_px`` =
    the column pitch (smallest band-to-band spacing) for cross-checking. Robust for UI/clean grids;
    APPROXIMATE for photo grids with spanning cells (a 2×2 explore tile hides a gutter and merges
    two bands → undercount). The caller should CONFIRM the count by view_image-ing the grid crop
    (a vision pass counts columns reliably); use pitch_px + width to sanity-check. Returns
    {columns, pitch_px, band_centers_px, gap_centers_px}."""
    px0, py0, px1, py1 = _region_px(im, region)
    bg = _bg_rgb(im, region)
    rows = max(1, (py1 - py0) // step)
    counts, coords = [], []
    for x in range(px0, px1, step):
        n = sum(1 for y in range(py0, py1, step)
                if _rgb_dist(im.getpixel((x, y)), bg) > thresh)
        counts.append(1 if n >= min_fill * rows else 0)
        coords.append(x)
    bands = _bands(counts, coords)
    centers = [c for _, _, c in bands]
    gaps = [(bands[i][1] + bands[i + 1][0]) // 2 for i in range(len(bands) - 1)]
    pitch = None
    if len(centers) >= 2:
        pitch = min(centers[i + 1] - centers[i] for i in range(len(centers) - 1))
    return {"columns": len(bands), "pitch_px": pitch,
            "band_centers_px": centers, "gap_centers_px": gaps}


def row_bands(im, region: Optional[Region] = None, *, thresh: float = 60.0,
              step: int = 2, min_fill: float = 0.15,
              cluster_px: Optional[int] = None) -> Dict[str, object]:
    """Y-centers of stacked items (nav-item / row spacing) — §15③ (glyph→首项 183px, 项间 56px).
    Raw content bands FRAGMENT a structured item (a line icon has internal gaps → several sub-
    bands), so the raw bands are CLUSTERED into items by y-proximity (the manual's "聚类成各图标 y
    中心"): consecutive bands within ``cluster_px`` (default = half the typical band spacing) are one
    item. ``item_gap_px`` is the typical (outlier-trimmed) inter-item gap; large gaps (section
    breaks like glyph→first-item) are in ``section_gaps_px``. Returns {items, item_centers_px,
    item_gap_px, first_gap_px, section_gaps_px, bands, centers_px, gaps_px}."""
    px0, py0, px1, py1 = _region_px(im, region)
    bg = _bg_rgb(im, region)
    cols = max(1, (px1 - px0) // step)
    counts, coords = [], []
    for y in range(py0, py1, step):
        n = sum(1 for x in range(px0, px1, step)
                if _rgb_dist(im.getpixel((x, y)), bg) > thresh)
        counts.append(1 if n >= min_fill * cols else 0)
        coords.append(y)
    bands = _bands(counts, coords)
    centers = [c for _, _, c in bands]
    if len(centers) < 2:
        return {"items": len(centers), "item_centers_px": centers,
                "item_gap_px": 0, "first_gap_px": (centers[0] - py0) if centers else 0,
                "section_gaps_px": [], "bands": len(bands), "centers_px": centers, "gaps_px": []}
    raw_gaps = [centers[i + 1] - centers[i] for i in range(len(centers) - 1)]
    if cluster_px is None:                                   # adaptive: half the typical (upper-half) gap
        srt = sorted(raw_gaps)
        upper = srt[len(srt) // 2:]
        typ = upper[len(upper) // 2] if upper else srt[-1]
        cluster_px = max(8, int(typ * 0.5))
    items: List[int] = []
    cur = [centers[0]]
    for c in centers[1:]:
        if c - cur[-1] <= cluster_px:
            cur.append(c)
        else:
            items.append(sum(cur) // len(cur))
            cur = [c]
    items.append(sum(cur) // len(cur))
    item_gaps = [items[i + 1] - items[i] for i in range(len(items) - 1)]
    # typical item gap = median of the outlier-trimmed gaps; big gaps are section breaks
    ig_sorted = sorted(item_gaps)
    small = ig_sorted[:max(1, int(len(ig_sorted) * 0.7))] if ig_sorted else []
    item_gap = small[len(small) // 2] if small else 0
    section = [g for g in item_gaps if item_gap and g > 1.8 * item_gap]
    return {"items": len(items), "item_centers_px": items,
            "item_gap_px": item_gap, "first_gap_px": items[0] - py0,
            "section_gaps_px": section,
            "bands": len(bands), "centers_px": centers, "gaps_px": item_gaps}


def measure_layout(im, region: Optional[Region], metric: str) -> Dict[str, object]:
    """Dispatch §15 measurements. metric ∈ {content_width, grid_columns, row_spacing}."""
    if metric in ("content_width", "content_bounds"):
        return content_bounds(im, region)
    if metric == "grid_columns":
        return grid_columns(im, region)
    if metric in ("row_spacing", "row_bands", "nav_spacing"):
        return row_bands(im, region)
    return {"error": f"unknown metric '{metric}' (want content_width|grid_columns|row_spacing)"}


# ── Design-Prep: real-asset ingestion + staging (deterministic) ──────────────
_IMG_EXT = {".png": "png", ".jpg": "jpg", ".jpeg": "jpg", ".webp": "webp",
            ".gif": "gif", ".svg": "svg", ".bmp": "bmp", ".ico": "ico"}
_SVG_LEN_RE = re.compile(r'\b(width|height)\s*=\s*["\']?\s*([0-9.]+)', re.I)
_SVG_VB_RE = re.compile(r'viewBox\s*=\s*["\']\s*[-0-9.]+\s+[-0-9.]+\s+([0-9.]+)\s+([0-9.]+)', re.I)
_HEX_RE = re.compile(r'#[0-9a-fA-F]{6}\b')


def _slug(stem: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", stem.strip().lower()).strip("-")
    return s or "asset"


def _dominant_colors(im, n: int = 4) -> List[str]:
    """Top-``n`` dominant colors of a raster (median-cut quantize). Transparent pixels are
    composited over white first so an icon's real ink dominates, not the fill-over-black."""
    try:
        if im.mode in ("RGBA", "LA") or "transparency" in getattr(im, "info", {}):
            from PIL import Image
            base = Image.new("RGB", im.size, (255, 255, 255))
            base.paste(im.convert("RGBA"), mask=im.convert("RGBA").split()[-1])
            im = base
        small = im.convert("RGB").resize((48, 48))
        q = small.quantize(colors=max(2, n))
        pal = q.getpalette() or []
        counts = Counter(q.getdata())
        out: List[str] = []
        for idx, _cnt in counts.most_common(n):
            rgb = pal[idx * 3:idx * 3 + 3]
            if len(rgb) == 3:
                out.append(_hex(rgb))
        return out
    except Exception:
        return []


def _svg_dims(text: str) -> Optional[list]:
    # viewBox is the most reliable intrinsic size (an inner element's width/height must not win).
    vb = _SVG_VB_RE.search(text)
    if vb:
        try:
            return [int(round(float(vb.group(1)))), int(round(float(vb.group(2))))]
        except ValueError:
            pass
    # else the ROOT width/height — take the FIRST match of each (the <svg> element's), not a later
    # inner <rect width=..>'s (which mis-sized IG's comment icon to [2,24]).
    dims: Dict[str, float] = {}
    for name, val in _SVG_LEN_RE.findall(text):
        k = name.lower()
        if k in dims:
            continue
        try:
            dims[k] = float(val)
        except ValueError:
            pass
    if "width" in dims and "height" in dims:
        return [int(round(dims["width"])), int(round(dims["height"]))]
    return None


def _ingest_one(path: Path, rel: Path) -> Optional[Dict]:
    suffix = path.suffix.lower()
    kind = _IMG_EXT.get(suffix)
    if not kind:
        return None
    dims: Optional[list] = None
    transparent = False
    colors: List[str] = []
    if kind == "svg":
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            text = ""
        dims = _svg_dims(text)
        transparent = True  # vector assets are transparent by convention
        seen: List[str] = []
        for h in _HEX_RE.findall(text):
            h = h.lower()
            if h not in seen:
                seen.append(h)
        colors = seen[:4]
    else:
        try:
            from PIL import Image
            im = Image.open(path)
            dims = [im.width, im.height]
            transparent = im.mode in ("RGBA", "LA", "P") and (
                im.mode in ("RGBA", "LA") or "transparency" in getattr(im, "info", {}))
            colors = _dominant_colors(im)
        except Exception:
            dims, transparent, colors = None, False, []
    return {
        "id": _slug(path.stem),
        "file": rel.as_posix(),
        "type": kind,
        "dims": dims,
        "transparent": bool(transparent),
        "dominant_colors": colors,
        "staged_path": f"public/assets/{rel.as_posix()}",
    }


# #183/#184: NON-image design-input assets that ingest must stage anyway. A font/video/audio
# never opens as an image, so _ingest_one returns None and it would be dropped — losing real
# typography ("文字风格一致") and, far worse for a video-centric clone, the actual VIDEOS
# (gmtiktok staged 35 jpg thumbnails but 0 mp4). Recognized non-image types are staged with a
# minimal manifest entry so design_system assets[] carries them and lanes can reference them.
_FONT_EXTS = {".woff2", ".woff", ".ttf", ".otf", ".eot"}
_VIDEO_EXTS = {".mp4", ".webm", ".mov", ".m4v", ".ogv"}
_AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".ogg", ".aac", ".flac"}


def _video_codec_1202qf(path: Path) -> str:
    """'hevc' / 'h264' / '' from the container's sample-entry tags (no ffprobe needed)."""
    try:
        with open(path, "rb") as fh:
            head = fh.read(4_000_000)
        if b"hvc1" in head or b"hev1" in head:
            return "hevc"
        if b"avc1" in head or b"avc3" in head:
            return "h264"
    except Exception:
        pass
    return ""


def _ffmpeg_1202qf() -> str:
    exe = shutil.which("ffmpeg") or ""
    if not exe:
        try:
            import imageio_ffmpeg  # optional: a bundled static ffmpeg
            exe = imageio_ffmpeg.get_ffmpeg_exe()
        except Exception:
            exe = ""
    return exe


def _stage_video_1202qf(path: Path, dest: Path, entry: Dict) -> bool:
    """#1202qf: an HEVC video is staged as H.264 when ffmpeg is available.

    Chromium on Linux and most desktop browsers without hardware HEVC cannot decode `hvc1`;
    tiktok's 35 real videos were all HEVC, so every feed card errored, the page hid the
    element, and the capture judged a black card (fyp_feed_logged_out 0.56). Without ffmpeg the
    file is staged as-is and the entry says `browser_playable: False` so the poster must carry
    the frame. Returns True when this function wrote `dest`.
    """
    import logging
    log = logging.getLogger(__name__)
    codec = _video_codec_1202qf(path)
    entry["codec"] = codec or None
    if codec != "hevc":
        return False
    exe = _ffmpeg_1202qf()
    if not exe:
        entry["browser_playable"] = False
        log.warning("#1202qf %s is HEVC and no ffmpeg is available to transcode it: most "
                    "browsers will not play it - render its poster image", path.name)
        return False
    tmp = dest.with_name(".tmp_" + dest.name)
    try:
        import subprocess
        res = subprocess.run(
            [exe, "-y", "-loglevel", "error", "-i", str(path), "-c:v", "libx264",
             "-profile:v", "high", "-pix_fmt", "yuv420p", "-preset", "veryfast", "-crf", "26",
             "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", str(tmp)],
            capture_output=True, text=True, timeout=900)
        if res.returncode == 0 and tmp.exists() and tmp.stat().st_size > 0:
            tmp.replace(dest)
            entry["codec"], entry["transcoded_from"] = "h264", "hevc"
            return True
        log.warning("#1202qf transcoding %s failed: %s", path.name, (res.stderr or "")[-200:])
    except Exception as exc:
        log.warning("#1202qf transcoding %s failed: %s", path.name, exc)
    try:
        tmp.unlink()
    except Exception:
        pass
    entry["browser_playable"] = False
    return False


def _nonimage_asset_type(suffix: str) -> Optional[str]:
    if suffix in _FONT_EXTS:
        return "font"
    if suffix in _VIDEO_EXTS:
        return "video"
    if suffix in _AUDIO_EXTS:
        return "audio"
    return None


def ingest_assets(assets_dir, stage_dir) -> List[Dict]:
    """Scan a user-provided ``assets/`` folder → a manifest (one entry per image) + physically
    stage each file into ``stage_dir`` (preserving any icons/ logos/ subfolder grouping so
    ``staged_path`` = ``public/assets/<relpath>``). Deterministic, best-effort: missing dir → [],
    unreadable files skipped, never raises. Manifest entry:
    {id, file, type, dims:[w,h]|None, transparent, dominant_colors:[hex], staged_path}."""
    src = Path(assets_dir)
    if not src.is_dir():
        return []
    stage = Path(stage_dir)
    manifest: List[Dict] = []
    seen_ids: Dict[str, int] = {}
    for path in sorted(src.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(src)
        try:
            entry = _ingest_one(path, rel)
        except Exception:
            entry = None
        if not entry:
            # #183/#184: a font/video/audio never opens as an image (_ingest_one → None); stage
            # recognized non-image assets anyway with a minimal entry so real typography AND the
            # actual video/audio reach the app. Other non-image files are still skipped.
            _atype = _nonimage_asset_type(path.suffix.lower())
            if not _atype:
                continue
            entry = {"id": path.stem, "file": rel.as_posix(), "type": _atype,
                     "dims": None, "transparent": False, "dominant_colors": [],
                     "staged_path": f"public/assets/{rel.as_posix()}"}
        base_id = entry["id"]
        seen_ids[base_id] = seen_ids.get(base_id, 0) + 1
        if seen_ids[base_id] > 1:
            entry["id"] = f"{base_id}-{seen_ids[base_id]}"
        try:
            dest = stage / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            if not (entry.get("type") == "video" and _stage_video_1202qf(path, dest, entry)):
                shutil.copy2(path, dest)
        except Exception:
            continue
        manifest.append(entry)
    return manifest


_DATA_EXTS = {".json", ".csv", ".ndjson", ".jsonl"}


def _dataset_columns(path: Path, kind: str) -> List[str]:
    """F2b: the union of row keys (first-seen order) for a JSON-array data file — the
    schema the real dataset defines, so the contract can build a matching table. []
    for non-JSON or non-array data (never raises)."""
    if kind not in ("json",):
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="ignore"))
    except Exception:
        return []
    if not isinstance(data, list):
        return []
    # FIX #158: sanitize each column name to a valid, non-keyword identifier (the SAME
    # function the ORM render + seed-key assembly use) so the requirements-binding block
    # tells the backend the FINAL safe name — a real dataset column like ``from`` never
    # reaches the contract as a Python keyword that would break ``import models``.
    from .backend_skeleton import safe_column_name
    cols: List[str] = []
    seen = set()
    for row in data:
        if not isinstance(row, dict):
            continue
        for k in row.keys():
            sk = safe_column_name(k)
            if sk not in seen:
                seen.add(sk)
                cols.append(sk)
    return cols


def _dataset_record_count(path: Path, kind: str) -> Optional[int]:
    """Best-effort row count for a staged data file — a top-level JSON array's
    length, or a dict's summed list lengths, or line count for ndjson/csv.
    None when unknown (never raises)."""
    try:
        if kind in ("ndjson", "jsonl", "csv"):
            n = sum(1 for ln in path.read_text(encoding="utf-8", errors="ignore").splitlines()
                    if ln.strip())
            return max(0, n - 1) if kind == "csv" else n
        data = json.loads(path.read_text(encoding="utf-8", errors="ignore"))
        if isinstance(data, list):
            return len(data)
        if isinstance(data, dict):
            return sum(len(v) for v in data.values() if isinstance(v, list))
    except Exception:
        return None
    return None


def ingest_dataset(dataset_dir, stage_dir) -> List[Dict]:
    """F1 — the FOURTH design-input channel. Scan a user-provided ``dataset/`` folder of
    REAL structured data (JSON/CSV/NDJSON) → a manifest + physically stage each file into
    ``stage_dir`` (preserving subfolders). Mirrors ``ingest_assets`` but for data rows, not
    images: the design-prep phase carries these into the app's seed so the DB ships REAL
    domain data deterministically (not LLM-synthesized). ``staged_path`` points at the
    app-relative runtime location ``backend/dataset/<relpath>`` (build-infra copies it next
    to seed_data.json). Deterministic, best-effort: missing dir → [], unreadable files
    skipped, never raises. Manifest entry: {id, file, type, records:int|None, staged_path}."""
    src = Path(dataset_dir)
    if not src.is_dir():
        return []
    stage = Path(stage_dir)
    manifest: List[Dict] = []
    seen_ids: Dict[str, int] = {}
    for path in sorted(src.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in _DATA_EXTS:
            continue
        rel = path.relative_to(src)
        kind = path.suffix.lower().lstrip(".")
        base_id = _slug(path.stem)
        seen_ids[base_id] = seen_ids.get(base_id, 0) + 1
        entry_id = base_id if seen_ids[base_id] == 1 else f"{base_id}-{seen_ids[base_id]}"
        try:
            dest = stage / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, dest)
        except Exception:
            continue
        manifest.append({
            "id": entry_id,
            "file": rel.as_posix(),
            "type": kind,
            "records": _dataset_record_count(path, kind),
            "columns": _dataset_columns(path, kind),
            "staged_path": f"backend/dataset/{rel.as_posix()}",
        })
    return manifest


# #483 — dataset↔contract field-name alignment. design-prep's REAL dataset uses domain
# field names (name/synopsis/kind/year/poster/backdrop/rating), but the contract-projected
# ORM model's column names are NON-DETERMINISTIC across runs (netflix r54: titles.`name`;
# r55: titles.`title`). When they diverge, the seed loader's `hasattr(cls,k)` filter DROPS
# every unmatched field → a NOT-NULL column (r55: titles.title) is left unset → EVERY row
# silently fails its per-row insert → empty table → chains 404 → 0 release (r55, live: 0
# titles seeded from a 60-title dataset). Each group's FIRST element is the canonical/contract
# name; the rest are common domain synonyms design-prep tends to emit.
# #1202ro: the first eight groups are all film vocabulary -- poster_url, release_year,
# average_rating, runtime -- because #483 was written against a netflix clone. A short-video
# env shares none of them, so its dataset lost every column whose name differed by a suffix.
# Measured across r129/r130/r131, all three, the dataset swap dropped 18-22 columns per run:
# `likes` never reached `like_count`, `thumbnail` never reached `thumbnail_url`, `cover` never
# reached `cover_url`. The data WAS there; the names did not line up and the swap replaces a
# table wholesale, so the column simply ceased to exist. An unprimed agent found the far end
# of that: every engagement figure 0 while the video_likes rows sat in the database, and a
# login form that could not log in because `users.email` had been dropped on the same path.
#
# The groups below are deliberately domain-NEUTRAL -- count/url/time suffix pairs any product
# has -- rather than another vertical's vocabulary. Adding tiktok words here would repeat the
# original mistake one env later.
_FIELD_SYNONYM_GROUPS = (
    ("title", "name"),
    ("description", "synopsis", "summary", "overview"),
    ("type", "kind", "category"),
    ("release_year", "year"),
    ("poster_url", "poster"),
    ("backdrop_url", "backdrop"),
    ("average_rating", "rating"),
    ("duration_minutes", "duration", "runtime"),
    # engagement counters: the dataset carries the bare noun, the model the _count column
    ("like_count", "likes"),
    ("comment_count", "comments"),
    ("share_count", "shares"),
    ("save_count", "saves", "favorites"),
    ("view_count", "views"),
    ("follower_count", "followers", "followers_count"),
    ("following_count", "following"),
    ("reply_count", "replies"),
    ("viewer_count", "viewers"),
    # media/image references: bare noun vs the _url/_image column
    ("thumbnail_url", "thumbnail", "thumb"),
    ("cover_url", "cover", "cover_image"),
    ("avatar_url", "avatar", "profile_image", "profile_pic"),
    ("image_url", "image", "photo"),
    ("video_url", "video", "media_url"),
    ("banner_url", "banner"),
    ("logo_url", "logo"),
    # identity and time
    ("display_name", "displayname", "full_name"),
    ("username", "handle", "screen_name"),
    ("created_at", "created", "timestamp", "posted_at", "published_at"),
    ("updated_at", "updated", "modified_at"),
)


def model_columns_from_models_py(models_py_path) -> Dict[str, set]:
    """Parse the generated ``models.py`` → ``{table_name: {column, ...}}`` by regex — the
    SQLAlchemy attribute names the seed loader inserts through (``hasattr(cls, k)``). No
    import/subprocess (introspect_orm_schema needs the app's deps and returns None from the
    framework venv), so this is the deterministic, dependency-free source. Best-effort:
    unreadable/absent file → {}."""
    import re as _re
    from pathlib import Path as _P
    try:
        text = _P(models_py_path).read_text(encoding="utf-8")
    except Exception:
        return {}
    out: Dict[str, set] = {}
    # split into class blocks: `class X(Base):` ... up to the next top-level `class `/EOF
    for m in _re.finditer(r"^class\s+\w+\s*\([^)]*\):\s*$(.*?)(?=^class\s|\Z)",
                          text, _re.M | _re.S):
        block = m.group(1)
        tm = _re.search(r"__tablename__\s*=\s*['\"]([^'\"]+)['\"]", block)
        if not tm:
            continue
        cols = set(_re.findall(r"^\s{4,}(\w+)\s*=\s*Column\(", block, _re.M))
        if cols:
            out[tm.group(1)] = cols
    return out


# ── #1202ru — a counter column the dataset spells as a bare noun ──────────────
# `#483`'s groups enumerate SPELLINGS, and enumeration is exactly what fails here: tiktok-r131's
# own schema spells the video counter `like_count` and the user counter `likes_count`. The group
# ("like_count", "likes") matches neither a column named `likes_count` nor anything else on that
# table, so `align_dataset_field_names` skipped it, `User.likes_count` kept its
# `Column(Integer, default=0)`, and a creator with 24.1M followers served `likes_count: 0`.
# That contradiction is what an unprimed M1 judge flagged on r131 while simply using the app --
# a profile page cannot have 74M followers and zero total likes and still read as a real account.
#
# Measured over generated/: 23 of 131 runs carrying both a dataset and a lane seed lose at least
# one counter this way; `users.likes_count <- likes` alone in 19 of them.
#
# So this pass matches STRUCTURE instead of spelling: a column that READS AS A COUNTER is filled
# from a dataset field naming the same thing. Deliberately narrow, three ways:
#   * only names carrying an explicit count marker are counter targets, so a text column named
#     `comment` is never mistaken for `comment_count`;
#   * `_total` is NOT a marker -- `order_total` is money, and `orders` must not fill it;
#   * the value must be an int. Tightening from (int, float) and dropping `_total`/`num_` cost
#     zero true positives across all 131 runs, which is the whole argument for the narrowness.
_COUNT_SUFFIXES_1202RU = ("_counts", "_count", "_num")
_COUNT_PREFIXES_1202RU = ("num_",)


def _singular_1202ru(word: str) -> str:
    return word[:-1] if word.endswith("s") and not word.endswith("ss") else word


def _counter_stem_1202ru(name: Any) -> Optional[str]:
    """The thing being counted, or None when the name does not read as a counter."""
    text = str(name or "").lower()
    marked = False
    for prefix in _COUNT_PREFIXES_1202RU:
        if text.startswith(prefix):
            text, marked = text[len(prefix):], True
            break
    for suffix in _COUNT_SUFFIXES_1202RU:
        if text.endswith(suffix):
            text, marked = text[:-len(suffix)], True
            break
    if not (marked and text):
        return None
    return _singular_1202ru(text)


def _fill_counter_columns_1202ru(rows: Any, colset: Any) -> int:
    """Same safety envelope as #483: additive, never overwrites, never cannibalizes a column."""
    targets: Dict[str, str] = {}
    for col in sorted(colset):
        stem = _counter_stem_1202ru(col)
        if stem:
            targets.setdefault(stem, col)
    if not targets:
        return 0
    filled = 0
    for row in rows:
        if not isinstance(row, dict):
            continue
        for src, val in list(row.items()):
            # #1202rv: NOT skipped when `src` is itself a column. 10 of 149 corpus runs declare
            # BOTH `like_count` and `likes` as real Integer columns on one table -- two columns
            # for one fact -- and in 8 of them exactly one side is seeded: the bare noun on
            # every row, the `_count` twin on none, left at its Column(Integer, default=0). The
            # direction never varies. Whichever column the frontend happens to read then decides
            # whether a video shows 3.6M likes or 0, and r115 serves both numbers in one row.
            # This mirrors rather than moves -- `src` keeps its value, so nothing is lost -- and
            # only for counter targets, where a same-stem twin cannot mean a different fact the
            # way `title` and `name` can.
            if not isinstance(val, int) or isinstance(val, bool):
                continue  # a count is an integer; this is what keeps money columns out
            stem = _counter_stem_1202ru(src) or _singular_1202ru(str(src).lower())
            target = targets.get(stem)
            if not target or target == src or row.get(target) is not None:
                continue  # unset targets only -- NEVER overwrite real data
            row[target] = val
            filled += 1
    return filled


def align_dataset_field_names(dataset, columns_by_table) -> Dict[str, List]:
    """#483 — map each dataset row's fields onto the ORM model's column names via
    ``_FIELD_SYNONYM_GROUPS``. ADDITIVE + BEST-EFFORT (the crux of its safety): a target
    column is filled from a synonym ONLY when (a) the target IS a real model column for that
    table, (b) it is currently UNSET in the row, and (c) the source field is present but is
    NOT itself a model column (so the loader would otherwise DROP it). A run whose names
    already match (r54) has no unset target with a droppable synonym → byte-IDENTICAL; the
    worst case is a no-op, never a regression. The original key is left in place (the loader's
    hasattr filter drops it harmlessly). Generalizable to every table/env."""
    try:
        if not isinstance(dataset, dict) or not isinstance(columns_by_table, dict):
            return dataset
        for table, rows in dataset.items():
            cols = columns_by_table.get(table)
            if not cols or not isinstance(rows, list):
                continue
            colset = set(cols)
            for row in rows:
                if not isinstance(row, dict):
                    continue
                for group in _FIELD_SYNONYM_GROUPS:
                    targets = [c for c in group if c in colset]
                    if not targets:
                        continue  # this table has no column in this synonym group
                    target = targets[0]
                    if row.get(target) is not None:
                        continue  # already set — NEVER overwrite real data
                    for syn in group:
                        if syn == target or syn in colset:
                            continue  # don't cannibalize a field that is its own column
                        val = row.get(syn)
                        if val is None:
                            continue
                        if (_counter_stem_1202ru(target)
                                and (not isinstance(val, int) or isinstance(val, bool))):
                            # #1202ru: the spelling path had no type guard, so a dataset field
                            # holding comment TEXT (or a list of comment objects) could land in
                            # Column(Integer) comment_count -- a row the loader then drops. It
                            # has never fired: 0 rows across the 131 corpus runs. Added because
                            # the structural pass below enforces this and a spelling path that
                            # does not is the same hole with a different name.
                            continue
                        row[target] = val
                        break
            # #1202ru: then the structural pass, for the counters no spelling list caught.
            _fill_counter_columns_1202ru(rows, colset)
        return dataset
    except Exception:
        return dataset


# ── #552 — deterministic Top-N ranking seed enrichment ───────────────────────
# The generated projector already emits Netflix-signature Top-10 rank numerals /
# "#N in X Today" badges + a data-derived Top-10 rail (frontend_scaffold #455/#531,
# gated on a row's ``top10_rank``/``rank`` being non-null), but the REAL design-prep
# dataset (design/dataset/*.json → seed_dataset.json) leaves those declared columns
# NULL, so every ranked treatment renders NOTHING (live GET /api/titles: top10_rank
# null, trending_score null). This fills the DECLARED-BUT-UNSEEDED ranking column at
# authoring time so the delivered DB carries real ranks. Keyed off the SCHEMA (a
# declared int rank column that the seed leaves null), never a product literal, so
# ANY app whose ORM declares such a column gets ranks.
_RANK_TOP_N = 10  # N≈10 (Netflix Top-10 rail; capped at the row count for small sets)
# Integer-family column types (a rank is an ordinal → must be int/nullable).
_SEED_INT_TYPES = frozenset({
    "integer", "int", "biginteger", "bigint", "smallinteger", "smallint"})
# Numeric column types that can carry a descending trending/popularity score.
_SEED_NUM_TYPES = _SEED_INT_TYPES | frozenset({
    "float", "numeric", "decimal", "double", "real", "number"})


def _is_ranking_col(name: str) -> bool:
    """A column that holds an ordinal Top-N rank (``top10_rank``/``rank``/``ranking``/
    ``*_rank``). Deliberately narrow — it must be the ranking POSITION, not a score."""
    n = (name or "").lower()
    return n in ("rank", "ranking") or n.endswith("_rank")


def _is_trending_col(name: str) -> bool:
    """A numeric column that expresses trending/popularity magnitude (the projector's
    ordering signal for a Top-N rail)."""
    n = (name or "").lower()
    return n in ("trending_score", "trending", "popularity", "popularity_score") \
        or "trending" in n or "popularity" in n


def align_dataset_id_types(dataset, schema) -> Dict[str, List]:
    """#808 — coerce each dataset row's PK (and same-named FK columns) to the TYPE the generated
    model declares for it.

    The staging pipeline already aligns dataset field NAMES to the model's columns (#483) and
    fills a declared ranking column (#552). It never checked the PK's TYPE. design-prep emits
    integer ids; a lane that declares ``id TEXT PRIMARY KEY`` (r145: `titles.id` is `text`, with
    every dependent `title_id TEXT REFERENCES titles(id)`) therefore receives integers into a text
    column, and every row in the app's dependent tables is left pointing at an id space that no
    longer exists -- 93 rows across 5 tables in that run.

    #807b refuses the whole swap when that happens, which protects the app but throws away the
    real domain data. This is the root-cause half: make the ids the right TYPE at staging so the
    two sources can agree in the cases where the values would match.

    ADDITIVE + BEST-EFFORT, deliberately narrow:
      * only columns the schema marks ``pk``, plus ``<singular>_id`` columns naming another table
        whose PK was coerced -- never a free-form data column;
      * only int<->str, the mismatch design-prep can actually produce; nothing else is touched;
      * unknown table, unknown column or unparsable schema -> row returned untouched.
    Matching types (the common case) -> byte-identical output.
    """
    if not isinstance(dataset, dict) or not isinstance(schema, dict):
        return dataset
    out: Dict[str, List] = {}
    pk_type: Dict[str, str] = {}
    for _t, _cols in schema.items():
        if not isinstance(_cols, dict):
            continue
        for _c, _meta in _cols.items():
            if isinstance(_meta, dict) and _meta.get("pk"):
                pk_type[str(_t)] = str(_meta.get("type") or "")
                break

    def _coerce(val, want):
        if want in ("text", "varchar", "string") and isinstance(val, int) \
                and not isinstance(val, bool):
            return str(val)
        if want in ("integer", "bigint", "smallint") and isinstance(val, str) \
                and val.strip().lstrip("-").isdigit():
            return int(val)
        return val

    for table, rows in dataset.items():
        if not isinstance(rows, list):
            out[table] = rows
            continue
        cols = schema.get(table) if isinstance(schema.get(table), dict) else {}
        new_rows = []
        for row in rows:
            if not isinstance(row, dict):
                new_rows.append(row)
                continue
            r = dict(row)
            for col, val in list(r.items()):
                meta = cols.get(col) if isinstance(cols, dict) else None
                want = ""
                if isinstance(meta, dict) and meta.get("pk"):
                    want = str(meta.get("type") or "")
                elif str(col).endswith("_id"):
                    stem = str(col)[:-3]
                    for cand in (stem + "s", stem, stem + "es"):
                        if cand in pk_type:
                            want = pk_type[cand]
                            break
                if want:
                    r[col] = _coerce(val, want)
            new_rows.append(r)
        out[table] = new_rows
    return out


def model_schema_from_models_py(models_py_path) -> Dict[str, Dict[str, Dict]]:
    """Parse the generated ``models.py`` → ``{table: {col: {type, nullable, pk}}}`` by
    regex (no import/subprocess — same rationale as ``model_columns_from_models_py``:
    the app's SQLAlchemy deps aren't importable from the framework venv). ``type`` is the
    first type token inside ``Column(...)`` lower-cased (``integer``/``float``/…);
    ``nullable`` is True unless ``nullable=False``/``primary_key=True``; ``pk`` reflects
    ``primary_key=True``. Best-effort: unreadable/absent file → {}."""
    import re as _re
    from pathlib import Path as _P
    try:
        text = _P(models_py_path).read_text(encoding="utf-8")
    except Exception:
        return {}
    out: Dict[str, Dict[str, Dict]] = {}
    for m in _re.finditer(r"^class\s+\w+\s*\([^)]*\):\s*$(.*?)(?=^class\s|\Z)",
                          text, _re.M | _re.S):
        block = m.group(1)
        tm = _re.search(r"__tablename__\s*=\s*['\"]([^'\"]+)['\"]", block)
        if not tm:
            continue
        cols: Dict[str, Dict] = {}
        for cm in _re.finditer(r"^\s{4,}(\w+)\s*=\s*Column\((.*)$", block, _re.M):
            cname, args = cm.group(1), cm.group(2)
            # skip an optional leading explicit column-name string: Column("db_name", Integer)
            ttok = _re.match(r"\s*(?:['\"][^'\"]*['\"]\s*,\s*)?([A-Za-z_]\w*)", args)
            ctype = (ttok.group(1) if ttok else "").lower()
            is_pk = "primary_key=true" in args.lower().replace(" ", "")
            nullable = not is_pk and "nullable=false" not in args.lower().replace(" ", "")
            # #1202rw: the FK target ("table.col"), so a consumer can order tables by
            # dependency. Additive -- every existing reader takes type/nullable/pk by name.
            _fk = _re.search(r"ForeignKey\(\s*['\"]([^'\"]+)['\"]", args)
            cols[cname] = {"type": ctype, "nullable": nullable, "pk": is_pk,
                           "fk": _fk.group(1) if _fk else None}
        if cols:
            out[tm.group(1)] = cols
    return out



# ── #1202rw — a declared timestamp that no seed ever fills ────────────────────
# 85 of the 129 corpus runs carrying a dataset declare a DateTime column that NOT ONE row
# fills: users.created_at in 74 of them, comments.created_at in 59, videos.created_at in 46.
# The column is emitted as a bare `Column(DateTime)` with no default, so the value is NULL
# forever -- and 111 of the 170 generated frontends render a timestamp field. Three distinct
# visible tells follow, each observed in the corpus:
#   * r131 and r115 render `<span>{c.created_at}</span>` while the backend serialises
#     `str(created)`, so the line beside every comment literally reads "None";
#   * instagram-run77 renders `new Date(post.created_at).toLocaleDateString()`, and null
#     gives the epoch -- the post is dated 1/1/1970;
#   * that same frontend's HomeFeedPage then fabricates `Date.now() - 5h` client-side, which
#     is the static-twin class `#1202rl` exists to catch.
#
# DETERMINISTIC, and that is not a stylistic preference: the emitted loader re-seeds whenever
# the fingerprint changes, with TRUNCATE ... RESTART IDENTITY. A wall-clock anchor would
# therefore wipe the database on every re-staging. No clock, no random -- a CRC of the row's
# own identity supplies the spread.
#
# FK-AWARE, because the obvious implementation produces a WORSE tell than the one it removes:
# fill each table on its own and comments land before the videos they reply to, which is a
# contradiction no amount of NULL ever was. Tables are banded by their depth in the FK graph
# -- accounts, then their videos, then the comments on them -- so every child row is later
# than every parent row by construction.
_TIME_TYPES_1202RW = frozenset({"datetime", "date", "timestamp"})
# ONLY the row's own lifecycle, and the list is short on purpose. Across the corpus the `_at`
# columns are created_at (963 table-occurrences), updated_at (39), last_message_at (36),
# started_at (16), read_at (16), added_at (3), last_watched_at, checked_at, ended_at. For all
# but the first two a NULL is not a gap, it is the ANSWER: read_at null means unread, ended_at
# null means still live, started_at null means not yet begun. Filling those would seed every
# notification already read and every stream already over -- a contradiction the app then
# serves as fact. The two that survive cover 1002 of the 1076 occurrences.
_RECORD_TIME_NAMES_1202RW = ("created_at", "updated_at", "modified_at", "inserted_at")
# ONLY a record timestamp -- when the row came to exist -- never a CONTENT date. netflix-r12
# and r5 declare `titles.release_date` as a null Date while the same row carries `year: 2026`;
# banding titles at depth 0 would have dated those films to 2025 and contradicted their own
# year field, which is a sharper tell than the null it replaces. `_at` is the ORM convention
# for exactly this distinction (created_at/updated_at/posted_at vs release_date/birth_date),
# and it covers 21,239 of the 21,654 rows this pass fills across the corpus -- the 415 it
# gives up are `release_date` (120, the dangerous ones) and one run's `created_time` (295).
# Fixed by necessity (see above). It ages: a run generated long after this date ships content
# whose newest item is dated then. That is the price of a stable fingerprint, and it is only
# paid when the dataset itself carries no timestamp to anchor on -- when one exists, the
# newest value in the data wins, which keeps a freshly generated run current for free.
_SEED_TIME_ANCHOR_1202RW = "2026-09-20T12:00:00"
# One band per FK depth. 180d over three typical depths (accounts -> posts -> comments) puts
# the oldest account ~18 months back and the newest comment at the anchor, which is the shape
# of every corpus app that does carry dates ('2023-01-01' through '2026-09-18').
_SEED_TIME_BAND_DAYS_1202RW = 180.0


def _parse_ts_1202rw(value: Any):
    """An ISO-8601 string -> naive datetime, or None. The emitted loader coerces with
    ``datetime.fromisoformat(v.replace('Z', '+00:00'))``, so this accepts what it accepts."""
    from datetime import datetime as _dt
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        out = _dt.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return out.replace(tzinfo=None)


def _seed_time_anchor_1202rw(dataset: Any):
    """The newest timestamp the data already carries, else the fixed anchor."""
    newest = None
    for rows in (dataset or {}).values():
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            for value in row.values():
                got = _parse_ts_1202rw(value)
                if got is not None and (newest is None or got > newest):
                    newest = got
    return newest or _parse_ts_1202rw(_SEED_TIME_ANCHOR_1202RW)


def _fk_depth_1202rw(schema: Any, tables: Any) -> Dict[str, int]:
    """Depth of each table in the FK graph, counting only edges between `tables`.

    Cycles (a self-FK like comments.parent_comment_id, or two tables referencing each other)
    are simply not followed twice -- the walk is bounded by the table count, so a cycle
    settles at a depth instead of hanging.
    """
    parents: Dict[str, set] = {}
    for table in tables:
        cols = schema.get(table)
        got = set()
        if isinstance(cols, dict):
            for meta in cols.values():
                target = (meta or {}).get("fk") if isinstance(meta, dict) else None
                if not isinstance(target, str):
                    continue
                other = target.split(".", 1)[0]
                if other in tables and other != table:
                    got.add(other)
        parents[table] = got
    depth = {t: 0 for t in tables}
    for _ in range(len(tables)):
        changed = False
        for table, ps in parents.items():
            want = max([depth[p] + 1 for p in ps], default=0)
            if want > depth[table]:
                depth[table], changed = want, True
        if not changed:
            break
    return depth


def enrich_seed_timestamps_1202rw(dataset, schema) -> Dict[str, List]:
    """#1202rw — fill a DECLARED time column that no row populates. See the note above.

    Same envelope as `#552`: additive, keyed off the declared column rather than any table or
    product name, byte-identical when the table declares no time column or the seed already
    carries one value for it, and deterministic so the runtime seed fingerprint stays stable.
    """
    from datetime import timedelta as _td
    try:
        if not isinstance(dataset, dict) or not isinstance(schema, dict):
            return dataset
        todo = {}
        for table, rows in dataset.items():
            cols = schema.get(table)
            if not isinstance(cols, dict) or not isinstance(rows, list):
                continue
            drows = [r for r in rows if isinstance(r, dict)]
            if not drows:
                continue
            tcols = sorted(
                c for c, meta in cols.items()
                if isinstance(meta, dict) and not meta.get("pk")
                and str(meta.get("type") or "").lower() in _TIME_TYPES_1202RW
                and c.lower() in _RECORD_TIME_NAMES_1202RW
                and all(r.get(c) is None for r in drows))  # author value -> byte-identical
            if tcols:
                todo[table] = (drows, tcols)
        if not todo:
            return dataset
        anchor = _seed_time_anchor_1202rw(dataset)
        if anchor is None:
            return dataset
        depth = _fk_depth_1202rw(schema, set(todo))
        deepest = max(depth.values()) if depth else 0
        band = _SEED_TIME_BAND_DAYS_1202RW
        for table in sorted(todo):
            drows, tcols = todo[table]
            end = anchor - _td(days=band * (deepest - depth.get(table, 0)))
            start = end - _td(days=band)
            span = (end - start).total_seconds()
            order = sorted(range(len(drows)), key=lambda i: _seed_row_rank_1202rw(drows[i], i))
            total = len(order)
            step = span / (total + 1)
            for slot, idx in enumerate(order):
                row = drows[idx]
                # CRC of the row's own identity, not `hash()` -- PYTHONHASHSEED randomises
                # that per process, and a seed that changes between stagings re-seeds the DB.
                import zlib as _zlib
                key = "%s:%s:%s" % (table, row.get("id", idx), slot)
                jitter = (_zlib.crc32(key.encode("utf-8")) % 1000) / 1000.0 - 0.5
                when = start + _td(seconds=step * (slot + 1 + jitter * 0.8))
                stamp = when.replace(microsecond=0).isoformat()
                for col in tcols:
                    row[col] = stamp
        return dataset
    except Exception:
        return dataset


def _seed_row_rank_1202rw(row: Any, idx: int):
    """Oldest first, by id where there is one. In a real database the primary key grows with
    time, so id order IS creation order -- the only ordering assumption available that the
    schema itself justifies."""
    value = (row or {}).get("id")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return (1, 0.0, str(value), idx)
    return (0, float(value), "", idx)



# ── #1202ry — the dataset rows that carry no id at all ───────────────────────
# tiktok-r126, live, from the backend's own log:
#
#   [seed] #807b REFUSED the dataset swap for comments: it would orphan 2 of 2 dependent
#   row(s) -- the two sources do not share an id space (lane ids look like 1, dataset ids
#   like None). Keeping the lane rows.
#
# The database then held 26 comments. The dataset staged into that same image holds 295 real
# ones. 283 authentic comments were discarded to keep 2 comment_likes rows resolvable.
#
# `#807b` is right about the case it was written for -- r145's lane keyed titles on TEXT
# slugs while the dataset supplied integers 1..60, two REAL and incompatible id spaces, and
# swapping orphaned 93 dependent rows. This is not that. Design-prep's comments carry NO id
# field at all, because scraped comments have no natural one; the model's PK is autoincrement
# and the database assigns it on insert. `_new_ids` then collapses to `{None}`, every
# dependent row counts as orphaned, and the majority test fires every time.
#
# So the repair is upstream of the test rather than a loosening of it: give those rows ids
# before anything reasons about the id space. Measured over generated/: 50 of 131 runs have
# the comments swap refused for exactly this reason, discarding 13,588 real rows between
# them. Refusals where the two sources genuinely differ (videos 17 runs, users 4) are
# untouched -- those datasets do carry ids.
def assign_dataset_ids_1202ry(dataset, schema) -> Dict[str, List]:
    """Number a dataset table whose rows carry NO primary key at all. Never renumbers.

    Deliberately all-or-nothing per table: one author-supplied id anywhere in the table means
    the author had an id space in mind, and a partial fill would invent collisions inside it.
    Integer PKs only -- a TEXT key is a slug, and a slug is content we cannot invent.
    """
    try:
        if not isinstance(dataset, dict) or not isinstance(schema, dict):
            return dataset
        for table, rows in dataset.items():
            cols = schema.get(table)
            if not isinstance(cols, dict) or not isinstance(rows, list):
                continue
            pks = [c for c, m in cols.items() if isinstance(m, dict) and m.get("pk")]
            if len(pks) != 1:
                continue  # no PK, or a composite one: not a row number
            pk = pks[0]
            meta = cols.get(pk) or {}
            if str(meta.get("type") or "").lower() not in _SEED_INT_TYPES:
                continue
            drows = [r for r in rows if isinstance(r, dict)]
            if not drows or any(r.get(pk) is not None for r in drows):
                continue  # author ids -> byte-identical
            for number, row in enumerate(drows, 1):
                row[pk] = number
        return dataset
    except Exception:
        return dataset


def _seed_order_keyfn(col, numeric, descending):
    """Deterministic sort key over ``(index, row)`` pairs by ``col``. None values sort
    LAST; numeric=True coerces to float (non-numeric → treated as absent); descending=True
    flips the numeric sign (Top-N: highest trending first). Original index breaks ties, so
    the sort is stable and clock/random-free."""
    def keyfn(pair):
        idx, r = pair
        v = r.get(col)
        if v is None:
            return (2, 0.0, "", idx)
        if numeric:
            fv = _coerce_float(v)
            if fv is None:
                return (1, 0.0, str(v), idx)
            return (0, -fv if descending else fv, "", idx)
        return (0, 0.0, str(v), idx)
    return keyfn


def enrich_ranking_seed(dataset, schema, top_n: int = _RANK_TOP_N) -> Dict[str, List]:
    """#552 — deterministically assign Top-N ranks to the first N rows of any table whose
    SCHEMA declares an int/nullable ranking column (``top10_rank``/``rank``/``*_rank``)
    that the seed leaves NULL, and populate a declared+null trending/popularity score with
    a descending value that matches the assigned ranks. This is what makes the projector's
    Top-10 numerals / "#N in X Today" badges / data-derived Top-10 rail render (they gate
    on the row's ``top10_rank`` being non-null).

    GENERALIZABLE — keys off the declared column, never a table/product name; any app whose
    ORM declares a ranking column gets ranks. DETERMINISTIC — stable order (an existing
    order signal if present: trending desc, else created/id asc, else the dataset's own
    order), no clock/random. CONTAINED + byte-IDENTICAL when: the table has no such column,
    the schema is unknown, or the seed ALREADY populates the rank (author-provided ranks are
    preserved, never overwritten). RE-SEED-SAFE — applied at authoring time (the resulting
    seed_dataset.json is deterministic, so the runtime seed fingerprint stays stable).

    ``schema`` is ``{table: {col: {type, nullable, pk}}}`` (see model_schema_from_models_py)."""
    try:
        if not isinstance(dataset, dict) or not isinstance(schema, dict):
            return dataset
        for table, rows in dataset.items():
            if not isinstance(rows, list) or not rows:
                continue
            cols = schema.get(table)
            if not isinstance(cols, dict) or not cols:
                continue  # schema unknown for this table → no-op
            # locate a declared int/nullable ranking column
            rank_col = None
            for cname, meta in cols.items():
                if not _is_ranking_col(cname):
                    continue
                m = meta if isinstance(meta, dict) else {}
                ctype = str(m.get("type") or "").lower()
                if ctype and ctype not in _SEED_INT_TYPES:
                    continue  # a rank must be an integer ordinal
                if m.get("pk") or m.get("nullable") is False:
                    continue
                rank_col = cname
                break
            if rank_col is None:
                continue  # table declares no ranking column → byte-identical
            dict_rows = [r for r in rows if isinstance(r, dict)]
            if not dict_rows:
                continue
            if any(r.get(rank_col) is not None for r in dict_rows):
                continue  # author-provided ranks → preserve, byte-identical
            # optional trending/popularity score column (numeric)
            trend_col = None
            trend_is_int = False
            for cname, meta in cols.items():
                if not _is_trending_col(cname):
                    continue
                m = meta if isinstance(meta, dict) else {}
                ctype = str(m.get("type") or "").lower()
                if ctype and ctype not in _SEED_NUM_TYPES:
                    continue
                trend_col = cname
                trend_is_int = ctype in _SEED_INT_TYPES
                break
            # choose a stable order signal (no clock/random)
            order_col, order_numeric, descending = None, True, False
            if trend_col and any(r.get(trend_col) is not None for r in dict_rows):
                order_col, order_numeric, descending = trend_col, True, True  # trending desc
            else:
                for cand in ("created_at", "created", "created_time", "id"):
                    if cand in cols and any(r.get(cand) is not None for r in dict_rows):
                        order_col, order_numeric, descending = cand, (cand == "id"), False
                        break
            indexed = list(enumerate(dict_rows))
            if order_col is None:
                ordered = indexed  # the dataset's own (deterministic) order
            else:
                ordered = sorted(
                    indexed, key=_seed_order_keyfn(order_col, order_numeric, descending))
            n = min(top_n, len(ordered))
            for rank, (_idx, r) in enumerate(ordered[:n], start=1):
                r[rank_col] = rank
                if trend_col is not None and r.get(trend_col) is None:
                    tval = top_n - rank + 1  # descending: rank 1 → highest
                    r[trend_col] = int(tval) if trend_is_int else float(tval)
        return dataset
    except Exception:
        return dataset


def _coerce_float(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _root_relative_asset_1202co(v):
    """A staged-asset path in a seed row must be ROOT-relative, or it 404s off the home route.

    The staged dataset writes `assets/posters/movie_1275779.jpg` with no leading slash, and
    that value goes into the DB, out of the API and straight into an `<img src>`. On `/browse`
    the browser resolves it against the route, asks for `/browse/assets/posters/...`, and the
    SPA fallback answers — with **200 and index.html**, not a 404. So nothing detects it:
    no network error, no console error, no failing gate. The image simply renders as nothing.

    r38 is what that costs. 368 assets staged, 31 paths seeded, 12 of 12 `<img>`/
    backgroundImage sites rendering the raw value, every hero black and every poster a solid
    block. Its visual verdict: eleven screens, median 0.27 against a 0.65 bar, and the judge's
    own words were "implementation has only an empty black background". The app was otherwise
    right — dark theme, correct nav, hero title, metadata row, TOP-10 badge, synopsis,
    Play/More Info, rails — and it scored 0.27 because none of the pictures loaded.

    Verified on the live r38 stack: `/assets/posters/movie_1275779.jpg` returns 200 with
    102,684 bytes; `/browse/assets/posters/movie_1275779.jpg` returns 200 with 1,226 — the
    SPA shell.

    Fixed HERE rather than in each page, because the frontend has one normalizer (`_url`)
    and it reached exactly one of twenty-four page files. A value that is correct in the
    database is correct everywhere; a helper has to be remembered at every render site.

    Only touches strings that already point into the staged tree. An absolute URL, a data:
    URI, an already-rooted path and every non-asset string are returned unchanged.
    """
    if not isinstance(v, str) or not v:
        return v
    t = v.lstrip()
    if t.startswith(("assets/", "./assets/")):
        return "/" + t.split("./", 1)[-1] if t.startswith("./") else "/" + t
    return v


def assemble_seed_dataset(design_dataset_dir) -> Dict[str, List]:
    """F2 — fold the staged real dataset (design/dataset/*.json) into a single
    ``{table: [rows]}`` seed dict: each JSON file whose stem is a table name and whose
    content is a row ARRAY contributes that table. Files that are not JSON arrays
    (MANIFEST.md, a config object) are skipped. This is what the build-infra writes to
    the framework-owned app/backend/seed_dataset.json (which the loader merges OVER the
    lane's seed_data.json). Deterministic, best-effort: missing dir / bad file → skipped,
    never raises."""
    src = Path(design_dataset_dir)
    out: Dict[str, List] = {}
    if not src.is_dir():
        return out
    for path in sorted(src.rglob("*.json")):
        if not path.is_file():
            continue
        try:
            rows = json.loads(path.read_text(encoding="utf-8", errors="ignore"))
        except Exception:
            continue
        if isinstance(rows, list) and rows:
            # the file stem IS the table name — keep it VERBATIM (no _slug: it would
            # rewrite transit_stops → transit-stops and break the ORM table match).
            # FIX #158: sanitize the ROW KEYS to the safe identifier so a seed key equals
            # the ORM ATTRIBUTE the loader inserts through (a keyword column ``from`` is
            # exposed as attribute ``from_``; a raw ``from`` key would be dropped by the
            # loader's hasattr filter → that column silently NULL). Same function as render.
            from .backend_skeleton import safe_column_name
            fixed = []
            for r in rows:
                if isinstance(r, dict):
                    fixed.append({safe_column_name(k): _root_relative_asset_1202co(v)
                                 for k, v in r.items()})
                else:
                    fixed.append(r)
            out[path.stem] = fixed
    return out


__all__ = ["row_mode_color", "region_background", "find_accent", "extract_palette",
           "crop_region", "decompose_reference", "make_side_by_side",
           "color_distance", "spec_color_deviations", "theme_inversion",
           "ingest_assets", "ingest_dataset", "assemble_seed_dataset",
           "model_schema_from_models_py", "enrich_ranking_seed",
           "enrich_seed_timestamps_1202rw",
           "assign_dataset_ids_1202ry"]
