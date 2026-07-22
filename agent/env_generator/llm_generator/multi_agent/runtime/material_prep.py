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
from typing import Dict, List, Optional, Tuple

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
                    fixed.append({safe_column_name(k): v for k, v in r.items()})
                else:
                    fixed.append(r)
            out[path.stem] = fixed
    return out


__all__ = ["row_mode_color", "region_background", "find_accent", "extract_palette",
           "crop_region", "decompose_reference", "make_side_by_side",
           "color_distance", "spec_color_deviations", "theme_inversion",
           "ingest_assets", "ingest_dataset", "assemble_seed_dataset"]
