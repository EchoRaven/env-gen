"""Material-prep agent TOOLS (USER directive 2026-06-29).

Give agents runtime capabilities to MEASURE colors, CROP components, and read the measured
PALETTE off a reference screenshot — so the frontend lane builds to MEASURED truth
(/data/common/haibotong/outlook_components/PIPELINE.md §3 "最关键：别猜颜色"), not the
model's color hallucination (the #1 fidelity collapse). These are pipeline-conforming AGENT
TOOL CALLS (one of the four building blocks: hard gates / prompts / framework / agent tools);
the deterministic backend is multi_agent/runtime/material_prep.py.

Mirrors the file-based tool convention of analysis_tools.py: BaseTool subclass, ``workspace``
in __init__, ``self.workspace.resolve(path)`` for project-relative paths, ``execute`` →
ToolResult. Reference screenshots live under ``design/references/``; crops are saved wherever
the agent asks (e.g. ``design/component_crops/``) so it can then ``view_image`` them.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.tool import BaseTool, ToolResult, ToolCategory, create_tool_param  # noqa: E402
from workspace import Workspace  # noqa: E402
from multi_agent.runtime import material_prep as mp  # noqa: E402

# #464: per-run cache of the deterministic per-image vision decomposition (keyed by
# resolved image path) — the design_analyst re-decomposes the same screens many times;
# reusing the first result skips the redundant vision calls (time + tokens). Module-
# level → per generation process (each run is a fresh process), cleared with the process.
_DECOMPOSE_MEM_CACHE: dict = {}

_REGION_SCHEMA = {
    "type": "array", "items": {"type": "number"}, "minItems": 4, "maxItems": 4,
    "description": "[x0,y0,x1,y1] as 0..1 FRACTIONS of width/height (e.g. the top 5.7% strip "
                   "= [0,0,1,0.057]). Omit/empty = whole image.",
}


def _region(arg):
    if not arg:
        return None
    try:
        r = [float(v) for v in arg][:4]
        return tuple(r) if len(r) == 4 else None
    except Exception:
        return None


class SampleColorTool(BaseTool):
    """Measure a color off a reference screenshot — never guess it."""

    NAME = "sample_color"
    DESCRIPTION = (
        "MEASURE a real color from a reference screenshot (don't guess hex — the #1 fidelity "
        "mistake). kind='background' → ROW-MODE of the region (the TRUE opaque background; "
        "single-point sampling catches wallpaper bleeding through a translucent panel → wrong "
        "navy). kind='accent' → the most-SATURATED pixel of `hue` (the royal-blue button / the "
        "semantic ribbon-icon color). Pass `region` to target one component (a chrome strip vs "
        "a translucent content panel sample DIFFERENT colors — measure each).\n"
        "Example: sample_color(image='design/references/outlook_inbox.png', region=[0,0,1,0.057], kind='background')"
    )

    def __init__(self, *, workspace: Workspace):
        super().__init__(name=self.NAME, category=ToolCategory.SEARCH)
        if workspace is None:
            raise ValueError(f"{self.NAME}: workspace is required")
        self.workspace = workspace

    @property
    def tool_definition(self):
        return create_tool_param(name=self.NAME, description=self.DESCRIPTION, parameters={
            "type": "object",
            "properties": {
                "image": {"type": "string", "description": "reference image path (e.g. design/references/<x>.png)"},
                "region": _REGION_SCHEMA,
                "kind": {"type": "string", "enum": ["background", "accent"], "default": "background"},
                "hue": {"type": "string", "enum": ["blue", "red", "green", "purple", "gold"],
                        "default": "blue", "description": "for kind='accent': which hue to find"},
            },
            "required": ["image"],
        })

    async def execute(self, image: str, region=None, kind: str = "background",
                      hue: str = "blue") -> ToolResult:
        p = self.workspace.resolve(image)
        if not p.exists():
            return ToolResult.fail(f"reference image not found: {image}")
        try:
            im = mp._open_rgb(str(p))
            reg = _region(region)
            if kind == "accent":
                hexv = mp.find_accent(im, reg, hue)
                if hexv is None:
                    return ToolResult(success=True, data={"hex": None, "kind": "accent", "hue": hue,
                                                          "note": f"no {hue} pixels in the region"})
                return ToolResult(success=True, data={"hex": hexv, "kind": "accent", "hue": hue})
            return ToolResult(success=True, data={"hex": mp.region_background(im, reg), "kind": "background"})
        except Exception as exc:
            return ToolResult.fail(f"sample_color failed: {type(exc).__name__}: {exc}")


class CropReferenceTool(BaseTool):
    """Crop a named component out of a reference screenshot + save it (then view_image it)."""

    NAME = "crop_reference"
    DESCRIPTION = (
        "CROP a (x0,y0,x1,y1)-fraction region out of a reference screenshot and SAVE it, so you "
        "can then view_image the single component up close (the whole page is too big to study "
        "detail — crop into named components, PIPELINE.md §2). Crop a touch LOOSE so a 1% "
        "misalignment doesn't slice it. Returns the saved path.\n"
        "Example: crop_reference(image='design/references/outlook_inbox.png', region=[0.205,0.288,0.43,0.355], "
        "save_as='design/component_crops/inbox__message_row.png')"
    )

    def __init__(self, *, workspace: Workspace):
        super().__init__(name=self.NAME, category=ToolCategory.SEARCH)
        if workspace is None:
            raise ValueError(f"{self.NAME}: workspace is required")
        self.workspace = workspace

    @property
    def tool_definition(self):
        return create_tool_param(name=self.NAME, description=self.DESCRIPTION, parameters={
            "type": "object",
            "properties": {
                "image": {"type": "string", "description": "reference image path"},
                "region": dict(_REGION_SCHEMA, description="[x0,y0,x1,y1] crop box, 0..1 fractions"),
                "save_as": {"type": "string", "description": "where to save the crop (e.g. design/component_crops/<name>.png)"},
            },
            "required": ["image", "region", "save_as"],
        })

    async def execute(self, image: str, region, save_as: str) -> ToolResult:
        p = self.workspace.resolve(image)
        if not p.exists():
            return ToolResult.fail(f"reference image not found: {image}")
        reg = _region(region)
        if reg is None:
            return ToolResult.fail("region must be 4 numbers [x0,y0,x1,y1] as 0..1 fractions")
        dest = self.workspace.resolve(save_as)
        try:
            w, h = mp.crop_region(str(p), reg, str(dest))
            return ToolResult(success=True, data={"saved_path": save_as, "width": w, "height": h,
                                                  "next": f"view_image('{save_as}') to study it"})
        except Exception as exc:
            return ToolResult.fail(f"crop_reference failed: {type(exc).__name__}: {exc}")


class ExtractPaletteTool(BaseTool):
    """The full measured palette of a reference screenshot (background + every accent hue)."""

    NAME = "extract_palette"
    DESCRIPTION = (
        "Return the MEASURED palette of a reference screenshot: the dominant background + every "
        "accent hue present (blue/red/green/purple/gold) — sampled, not guessed. Use it up front "
        "to seed your color tokens, then sample_color per component for the exact local colors. "
        "Catches SEMANTIC COLORS generators drop (count-blue, ribbon icons red/purple/gold).\n"
        "Example: extract_palette(image='design/references/outlook_inbox.png')"
    )

    def __init__(self, *, workspace: Workspace):
        super().__init__(name=self.NAME, category=ToolCategory.SEARCH)
        if workspace is None:
            raise ValueError(f"{self.NAME}: workspace is required")
        self.workspace = workspace

    @property
    def tool_definition(self):
        return create_tool_param(name=self.NAME, description=self.DESCRIPTION, parameters={
            "type": "object",
            "properties": {"image": {"type": "string", "description": "reference image path"}},
            "required": ["image"],
        })

    async def execute(self, image: str) -> ToolResult:
        p = self.workspace.resolve(image)
        if not p.exists():
            return ToolResult.fail(f"reference image not found: {image}")
        pal = mp.extract_palette(str(p))
        if "error" in pal:
            return ToolResult.fail(f"extract_palette failed: {pal['error']}")
        return ToolResult(success=True, data=pal)


class ZoomCompareTool(BaseTool):
    """2x-zoom REFERENCE-over-MINE side-by-side of a component — the §6 per-component zoom diff."""

    NAME = "zoom_compare"
    DESCRIPTION = (
        "Build a labeled REFERENCE-over-MINE comparison image (optionally 2x-ZOOMED) so you can "
        "view_image it and catch the micro-differences a whole-page glance misses — semantic-color "
        "loss, density/line-height, a missing star/icon, wrong unread/read state distribution "
        "(PIPELINE.md §6, the 'good→very good' kilometer). Pass `region` to compare ONE component "
        "(the SAME region is cropped from BOTH); `scale=2` zooms both. `mine` is a screenshot you "
        "captured of your running page (capture_webpage).\n"
        "Example: zoom_compare(reference='design/references/outlook_inbox.png', mine='design/captures/inbox.png', "
        "region=[0.205,0.288,0.43,0.355], save_as='design/compare/message_row.png', scale=2)"
    )

    def __init__(self, *, workspace: Workspace):
        super().__init__(name=self.NAME, category=ToolCategory.SEARCH)
        if workspace is None:
            raise ValueError(f"{self.NAME}: workspace is required")
        self.workspace = workspace

    @property
    def tool_definition(self):
        return create_tool_param(name=self.NAME, description=self.DESCRIPTION, parameters={
            "type": "object",
            "properties": {
                "reference": {"type": "string", "description": "reference image path"},
                "mine": {"type": "string", "description": "your captured screenshot path"},
                "save_as": {"type": "string", "description": "where to save the comparison (e.g. design/compare/<name>.png)"},
                "region": dict(_REGION_SCHEMA, description="[x0,y0,x1,y1] component box (0..1); omit = whole image"),
                "scale": {"type": "integer", "default": 2, "description": "zoom factor (2 or 3 for components)"},
            },
            "required": ["reference", "mine", "save_as"],
        })

    async def execute(self, reference: str, mine: str, save_as: str, region=None, scale: int = 2) -> ToolResult:
        rp = self.workspace.resolve(reference)
        mp_ = self.workspace.resolve(mine)
        if not rp.exists():
            return ToolResult.fail(f"reference not found: {reference}")
        if not mp_.exists():
            return ToolResult.fail(f"your screenshot not found: {mine} (capture_webpage it first)")
        dest = self.workspace.resolve(save_as)
        try:
            w, h = mp.make_side_by_side(str(rp), str(mp_), str(dest), region=_region(region),
                                        scale=int(scale or 2))
            return ToolResult(success=True, data={"saved_path": save_as, "width": w, "height": h,
                                                  "next": f"view_image('{save_as}') to spot the deviations"})
        except Exception as exc:
            return ToolResult.fail(f"zoom_compare failed: {type(exc).__name__}: {exc}")


class DecomposeReferenceTool(BaseTool):
    """Decompose a reference screenshot into named components + MEASURED colors (one vision call)."""

    NAME = "decompose_reference"
    DESCRIPTION = (
        "Decompose a reference screenshot into its named UI components, each with its region, "
        "role, state, AND the MEASURED background + accent colors (gemini names the components; "
        "the framework measures the colors from each region — truth, not a guess). Saves a "
        "per-component build spec to design/component_specs/<name>.json that you then build to, "
        "component-by-component (PIPELINE.md §2-4). Run it ONCE per reference screen up front.\n"
        "Example: decompose_reference(image='design/references/outlook_inbox.png')"
    )

    def __init__(self, *, workspace: Workspace, llm_client=None):
        super().__init__(name=self.NAME, category=ToolCategory.SEARCH)
        if workspace is None:
            raise ValueError(f"{self.NAME}: workspace is required")
        self.workspace = workspace
        self._llm = llm_client

    @property
    def tool_definition(self):
        return create_tool_param(name=self.NAME, description=self.DESCRIPTION, parameters={
            "type": "object",
            "properties": {
                "image": {"type": "string", "description": "reference image path"},
                "save_as": {"type": "string", "description": "spec output path (default design/component_specs/<stem>.json)"},
            },
            "required": ["image"],
        })

    async def execute(self, image: str, save_as: str = "") -> ToolResult:
        if self._llm is None:
            return ToolResult.fail("decompose_reference needs an LLM client (vision-capable)")
        p = self.workspace.resolve(image)
        if not p.exists():
            return ToolResult.fail(f"reference image not found: {image}")
        # #464: cache the (deterministic) per-image vision decomposition within this
        # run. The design_analyst re-decomposes the same screens many times (r44: 92
        # decompose calls for 20 screens ≈ 4.6× each), and decompose is a pure vision
        # call on a fixed image → the repeats only waste time + vision tokens (~5-8 min/
        # run). Key by the resolved image path; reuse the first result on repeats (still
        # runs the cheap write/gate below). Generalizable to any app; 防止浪费token.
        _ck = str(p)
        res = _DECOMPOSE_MEM_CACHE.get(_ck)
        if res is None:
            res = await mp.decompose_reference(str(p), self._llm)
            if "error" in res:
                return ToolResult.fail(f"decompose_reference failed: {res['error']}")
            _DECOMPOSE_MEM_CACHE[_ck] = res
        import json as _json
        out_rel = save_as or f"design/component_specs/{Path(image).stem}.json"
        dest = self.workspace.resolve(out_rel)
        # Route the write through the per-agent role write-gate. ``save_as`` is
        # agent-controllable, so without this a caller could drop a JSON spec into
        # another role's tree (e.g. ``app/backend/main.py``) — a cross-role write
        # that bypasses ROUTING_TABLE. At runtime ``self.workspace`` is the
        # ``PathRoutedWorkspace`` (which enforces the gate) and ``_agent_id`` is
        # injected by ``AgentTooling.attach``; a plain ``Workspace`` (early-init /
        # tests, pre-worktree) returns True by design. Gate on ``dest`` (the same
        # path we write) so the write-gate invariant is satisfied by construction.
        # #453: prefer the WRITE identity (_write_agent_id, the resolved profile e.g.
        # 'design_analyst') over _agent_id, which set_team_protocols clobbers to the raw
        # instance id ('design_analyst_1') ∉ the design/ writers set → false 'write
        # denied'. Fall back to _agent_id when the write attr isn't set (plain Workspace/
        # tests). Generalizable to any dynamic-suffixed self-gating agent.
        _gate_id = getattr(self, "_write_agent_id", None) or getattr(self, "_agent_id", None)
        if hasattr(self.workspace, "is_write_allowed") and not self.workspace.is_write_allowed(
                dest, _gate_id):
            return ToolResult.fail(f"write denied by role gate: {out_rel}")
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(_json.dumps(res, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception as exc:
            return ToolResult.fail(f"could not save spec: {exc}")
        return ToolResult(success=True, data={
            "saved_path": out_rel, "count": res.get("count"),
            "components": [c.get("name") for c in res.get("components", [])],
            "next": f"read('{out_rel}') and build each component to its measured colors"})


class MeasureLayoutTool(BaseTool):
    """MEASURE spacing / column-count / content-width off a reference (§15 — 肉眼量不准，用 PIL 测)."""

    NAME = "measure_layout"
    DESCRIPTION = (
        "MEASURE layout geometry off a reference screenshot with pixel scanning (spacing / columns "
        "/ width are impossible to eyeball — measure them, PIPELINE.md §15). "
        "metric='grid_columns' → column count + pitch (a HINT — robust for clean/UI grids, but a "
        "photo grid's 2x2 spanning tiles can hide a gutter and undercount; CONFIRM by view_image-"
        "ing the grid crop and use pitch_px+width to sanity-check). metric='content_width' → the "
        "content bounding box (find the true left/"
        "right edges, e.g. explore ~1110px vs feed ~935px). metric='row_spacing' → the y-centers "
        "of stacked items + the gap between them (e.g. nav glyph→first-item 183px, item gap 56px). "
        "Pass `region` to scope to one component (a nav column, a grid). Theme-agnostic (content = "
        "pixels far from the region background), works on light AND dark UIs.\n"
        "Example: measure_layout(image='design/references/ig_explore.png', region=[0.24,0.1,1,1], metric='grid_columns')"
    )

    def __init__(self, *, workspace: Workspace):
        super().__init__(name=self.NAME, category=ToolCategory.SEARCH)
        if workspace is None:
            raise ValueError(f"{self.NAME}: workspace is required")
        self.workspace = workspace

    @property
    def tool_definition(self):
        return create_tool_param(name=self.NAME, description=self.DESCRIPTION, parameters={
            "type": "object",
            "properties": {
                "image": {"type": "string", "description": "reference image path"},
                "region": _REGION_SCHEMA,
                "metric": {"type": "string",
                           "enum": ["grid_columns", "content_width", "row_spacing"],
                           "default": "content_width"},
            },
            "required": ["image", "metric"],
        })

    async def execute(self, image: str, metric: str = "content_width", region=None) -> ToolResult:
        p = self.workspace.resolve(image)
        if not p.exists():
            return ToolResult.fail(f"reference image not found: {image}")
        try:
            im = mp._open_rgb(str(p))
            data = mp.measure_layout(im, _region(region), metric)
            if isinstance(data, dict) and data.get("error"):
                return ToolResult.fail(data["error"])
            return ToolResult(success=True, data=data)
        except Exception as exc:
            return ToolResult.fail(f"measure_layout failed: {type(exc).__name__}: {exc}")


MATERIAL_PREP_TOOL_CLASSES = [SampleColorTool, CropReferenceTool, ExtractPaletteTool,
                              ZoomCompareTool, MeasureLayoutTool]


def create_material_prep_tools(workspace: Workspace = None) -> list:
    """The DETERMINISTIC material-prep tools (no LLM): sample_color / crop_reference / extract_palette."""
    return [cls(workspace=workspace) for cls in MATERIAL_PREP_TOOL_CLASSES]


def create_material_prep_vision_tools(workspace: Workspace = None, llm_client=None) -> list:
    """The vision-backed material-prep tool: decompose_reference (needs an LLM)."""
    return [DecomposeReferenceTool(workspace=workspace, llm_client=llm_client)]


__all__ = ["SampleColorTool", "CropReferenceTool", "ExtractPaletteTool", "ZoomCompareTool",
           "MeasureLayoutTool", "DecomposeReferenceTool", "MATERIAL_PREP_TOOL_CLASSES",
           "create_material_prep_tools", "create_material_prep_vision_tools"]
