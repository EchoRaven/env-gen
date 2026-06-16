"""
Vision Tools - Screenshot analysis and design extraction for web generation
Enables agent to build web pages based on reference images/screenshots
"""
import base64
import logging
from pathlib import Path
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field

from utils.tool import BaseTool, ToolResult, ToolCategory, create_tool_param
from workspace import Workspace
from jinja2 import Environment, FileSystemLoader


@dataclass
class DesignAnalysis:
    """Extracted design information from a screenshot"""
    # Layout
    layout_type: str = ""  # grid, flex, sidebar, dashboard, etc.
    sections: List[Dict] = field(default_factory=list)  # [{name, position, description}]
    
    # Colors
    primary_color: str = ""
    secondary_color: str = ""
    background_color: str = ""
    text_color: str = ""
    accent_colors: List[str] = field(default_factory=list)
    
    # Typography
    heading_font: str = ""
    body_font: str = ""
    font_sizes: Dict[str, str] = field(default_factory=dict)
    
    # Components identified
    components: List[Dict] = field(default_factory=list)  # [{type, description, position}]
    
    # Overall style
    style_description: str = ""
    design_system: str = ""  # material, fluent, atlassian, custom, etc.
    
    # Raw LLM analysis
    raw_analysis: str = ""


def encode_image_to_base64(image_path: str) -> Optional[str]:
    """Encode image file to base64 string"""
    path = Path(image_path)
    if not path.exists():
        return None
    
    try:
        with open(path, "rb") as f:
            return base64.b64encode(f.read()).decode("utf-8")
    except Exception:
        return None


def get_image_mime_type(image_path: str) -> str:
    """Get MIME type from file extension"""
    ext = Path(image_path).suffix.lower()
    mime_map = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".gif": "image/gif",
        ".webp": "image/webp",
    }
    return mime_map.get(ext, "image/png")


def _fuzzy_match_filename(target_dir: Path, filename: str) -> Optional[Path]:
    """Try to find a file with fuzzy matching (handles missing/extra spaces in filenames)."""
    if not target_dir.exists():
        return None
    
    # Normalize: remove all spaces for comparison
    normalized_target = filename.replace(" ", "").lower()
    
    for file in target_dir.iterdir():
        if file.is_file():
            normalized_file = file.name.replace(" ", "").lower()
            if normalized_file == normalized_target:
                return file
    
    return None


def resolve_image_path(workspace: Optional[Workspace], image_path: str) -> Optional[Path]:
    """
    Resolve an image path using the workspace when available.
    Reference images should be copied to workspace/screenshot/ at startup.
    Includes fuzzy matching for filenames with space issues (common LLM error).
    """
    if not image_path:
        return None

    # If it's an absolute path that exists, use it directly
    abs_path = Path(image_path)
    if abs_path.is_absolute() and abs_path.exists():
        return abs_path

    # Prefer workspace resolution
    if workspace is not None:
        try:
            p = workspace.resolve(image_path)
            if p.exists():
                return p
        except Exception:
            pass

        # Try common subdirectories within workspace (screenshot/ is primary)
        prefixes = ("screenshot", "screenshots", "design", "images", "assets", "artifacts")
        for prefix in prefixes:
            try:
                p2 = workspace.resolve(f"{prefix}/{image_path}")
                if p2.exists():
                    return p2
                # Also try just filename (e.g., "Flight-Detail.png" -> "screenshot/Flight-Detail.png")
                p3 = workspace.resolve(f"{prefix}/{Path(image_path).name}")
                if p3.exists():
                    return p3
            except Exception:
                continue
        
        # Fuzzy matching: handle space issues in filenames (common LLM error)
        # e.g., "Screenshot 2026-01-06 at 12.26.40AM.png" -> "Screenshot 2026-01-06 at 12.26.40 AM.png"
        path_obj = Path(image_path)
        search_dirs = [workspace.resolve(str(path_obj.parent))] if path_obj.parent != Path(".") else []
        search_dirs.extend([workspace.resolve(prefix) for prefix in prefixes])
        
        for search_dir in search_dirs:
            matched = _fuzzy_match_filename(search_dir, path_obj.name)
            if matched:
                return matched

    # Fall back to raw path
    p = Path(image_path)
    return p if p.exists() else None


def _get_prompt_env() -> Environment:
    """Jinja environment for prompts."""
    prompt_dir = Path(__file__).parent.parent / "multi_agent" / "prompts"
    return Environment(
        loader=FileSystemLoader(str(prompt_dir)),
        trim_blocks=True,
        lstrip_blocks=True,
    )


class AnalyzeImageTool(BaseTool):
    """Analyze an image to extract design information for web generation."""

    NAME = "analyze_image"

    description = """Analyze a screenshot/mockup image to extract design information.
Returns detailed analysis including:
- Layout structure (grid, flex, sections)
- Color palette (primary, secondary, background, accent)
- Typography (fonts, sizes)
- UI components identified (buttons, cards, navigation, etc.)
- Overall style and design system

Use this when you have a reference image to build a web page from.
"""
    
    def __init__(self, llm_client=None, workspace: Workspace = None):
        super().__init__()
        self._llm = llm_client
        self._logger = logging.getLogger(__name__)
        self._workspace = workspace
        self._jinja = None
    
    def set_llm(self, llm_client):
        """Set the LLM client (must support vision)"""
        self._llm = llm_client
    
    @property
    def tool_definition(self):
        return create_tool_param(
            name=self.name,
            description=self.description,
            parameters={
                "image_path": {"type": "string", "description": "Path to the screenshot/mockup image"},
                "focus_area": {"type": "string", "description": "Optional: specific area to focus on (e.g., 'header', 'sidebar')"}
            },
            required=["image_path"]
        )
    
    async def execute(self, image_path: str, focus_area: str = None) -> ToolResult:
        if not self._llm:
            return ToolResult(
                success=False,
                error_message="LLM client not configured. Cannot analyze image."
            )
        
        resolved = resolve_image_path(self._workspace, image_path)
        if not resolved:
            return ToolResult(
                success=False,
                error_message=f"Could not read image: {image_path}"
            )

        # Encode image
        image_base64 = encode_image_to_base64(str(resolved))
        if not image_base64:
            return ToolResult(
                success=False,
                error_message=f"Could not read image: {image_path}"
            )
        
        mime_type = get_image_mime_type(str(resolved))
        
        # Build analysis prompt
        prompt = self._build_analysis_prompt(focus_area)
        
        try:
            # Call vision LLM
            response = await self._call_vision_llm(image_base64, mime_type, prompt)
            
            # Parse response into DesignAnalysis
            analysis = self._parse_analysis(response)
            
            return ToolResult(
                success=True,
                data={
                    "image_path": image_path,
                    "analysis": {
                        "layout_type": analysis.layout_type,
                        "sections": analysis.sections,
                        "colors": {
                            "primary": analysis.primary_color,
                            "secondary": analysis.secondary_color,
                            "background": analysis.background_color,
                            "text": analysis.text_color,
                            "accents": analysis.accent_colors,
                        },
                        "typography": {
                            "heading_font": analysis.heading_font,
                            "body_font": analysis.body_font,
                            "sizes": analysis.font_sizes,
                        },
                        "components": analysis.components,
                        "style_description": analysis.style_description,
                        "design_system": analysis.design_system,
                    },
                    "raw_analysis": analysis.raw_analysis,
                }
            )
        except Exception as e:
            self._logger.error(f"Screenshot analysis failed: {e}")
            return ToolResult(
                success=False,
                error_message=f"Analysis failed: {str(e)}"
            )
    
    def _build_analysis_prompt(self, focus_area: str = None) -> str:
        if self._jinja is None:
            self._jinja = _get_prompt_env()
        return self._jinja.get_template("vision/analyze_image.j2").render(
            focus_area=focus_area or ""
        )
    
    async def _call_vision_llm(self, image_base64: str, mime_type: str, prompt: str) -> str:
        """Call the vision-capable LLM with the image"""
        from utils.llm import Message
        
        # Build multimodal message
        message = Message.user_with_image(
            text=prompt,
            image_base64=image_base64,
            mime_type=mime_type
        )
        
        # Call LLM with multimodal message
        response = await self._llm.chat_messages(
            messages=[message],
            temperature=0.3,
        )
        
        return response.content if hasattr(response, 'content') else str(response)
    
    def _parse_analysis(self, response: str) -> DesignAnalysis:
        """Parse LLM response into DesignAnalysis object"""
        import json
        import re
        
        analysis = DesignAnalysis(raw_analysis=response)
        
        # Try to extract JSON from response
        json_match = re.search(r'\{[\s\S]*\}', response)
        if json_match:
            try:
                data = json.loads(json_match.group())
                
                analysis.layout_type = data.get("layout_type", "")
                analysis.sections = data.get("sections", [])
                
                colors = data.get("colors", {})
                analysis.primary_color = colors.get("primary", "")
                analysis.secondary_color = colors.get("secondary", "")
                analysis.background_color = colors.get("background", "")
                analysis.text_color = colors.get("text", "")
                analysis.accent_colors = colors.get("accents", [])
                
                typography = data.get("typography", {})
                analysis.heading_font = typography.get("heading_font", "")
                analysis.body_font = typography.get("body_font", "")
                analysis.font_sizes = typography.get("sizes", {})
                
                analysis.components = data.get("components", [])
                analysis.style_description = data.get("style_description", "")
                analysis.design_system = data.get("design_system", "")
                
            except json.JSONDecodeError:
                pass
        
        return analysis


class CompareWithScreenshotTool(BaseTool):
    """Compare generated UI with reference screenshot"""

    NAME = "compare_with_screenshot"

    description = """Compare a generated web page screenshot with the reference design.
Returns similarity analysis and specific differences to fix.
Use this after generating UI code to verify it matches the reference.
"""

    def __init__(self, llm_client=None, workspace: Workspace = None):
        super().__init__()
        self._llm = llm_client
        self._logger = logging.getLogger(__name__)
        self._workspace = workspace
        self._jinja = None
    
    def set_llm(self, llm_client):
        self._llm = llm_client
    
    @property
    def tool_definition(self):
        return create_tool_param(
            name=self.name,
            description=self.description,
            parameters={
                "reference_image": {"type": "string", "description": "Path to the reference screenshot"},
                "generated_image": {"type": "string", "description": "Path to screenshot of generated UI"}
            },
            required=["reference_image", "generated_image"]
        )
    
    async def execute(self, reference_image: str, generated_image: str) -> ToolResult:
        if not self._llm:
            return ToolResult(success=False, error_message="LLM client not configured")
        
        ref_resolved = resolve_image_path(self._workspace, reference_image)
        gen_resolved = resolve_image_path(self._workspace, generated_image)

        if not ref_resolved:
            return ToolResult(success=False, error_message=f"Cannot read reference: {reference_image}")
        if not gen_resolved:
            return ToolResult(success=False, error_message=f"Cannot read generated: {generated_image}")

        ref_base64 = encode_image_to_base64(str(ref_resolved))
        gen_base64 = encode_image_to_base64(str(gen_resolved))
        
        if not ref_base64:
            return ToolResult(success=False, error_message=f"Cannot read reference: {reference_image}")
        if not gen_base64:
            return ToolResult(success=False, error_message=f"Cannot read generated: {generated_image}")
        
        ref_mime = get_image_mime_type(str(ref_resolved))
        gen_mime = get_image_mime_type(str(gen_resolved))
        
        if not hasattr(self, "_jinja") or self._jinja is None:
            self._jinja = _get_prompt_env()
        prompt = self._jinja.get_template("vision/compare_images.j2").render()
        
        try:
            from utils.llm import Message
            
            # Build multimodal message with both images
            message = Message.user_multimodal([
                {"type": "text", "text": "Reference design:"},
                {"type": "image_url", "image_url": {"url": f"data:{ref_mime};base64,{ref_base64}", "detail": "high"}},
                {"type": "text", "text": "Generated output:"},
                {"type": "image_url", "image_url": {"url": f"data:{gen_mime};base64,{gen_base64}", "detail": "high"}},
                {"type": "text", "text": prompt}
            ])
            
            response = await self._llm.chat_messages(messages=[message], temperature=0.3)
            content = response.content if hasattr(response, 'content') else str(response)
            
            import json
            import re
            json_match = re.search(r'\{[\s\S]*\}', content)
            if json_match:
                data = json.loads(json_match.group())
                return ToolResult(success=True, data=data)
            
            return ToolResult(success=True, data={"raw_comparison": content})
            
        except Exception as e:
            return ToolResult(success=False, error_message=f"Comparison failed: {e}")


class ExtractComponentsTool(BaseTool):
    """Extract specific UI components from a screenshot for targeted generation"""

    NAME = "extract_components"
    name = "extract_components"

    description = """Extract specific UI components from a screenshot.
Use this to get detailed specs for individual components like:
- Navigation bars
- Cards
- Forms
- Buttons
- Modals
- Tables
- Sidebars
"""
    
    def __init__(self, llm_client=None, workspace: Workspace = None):
        super().__init__()
        self._llm = llm_client
        self._workspace = workspace
        self._jinja = None

    def set_llm(self, llm_client):
        self._llm = llm_client

    @property
    def tool_definition(self):
        return create_tool_param(
            name=self.name,
            description=self.description,
            parameters={
                "image_path": {"type": "string", "description": "Path to the screenshot"},
                "component_type": {"type": "string", "description": "Type of component to extract (navbar, card, form, button, etc.)"}
            },
            required=["image_path", "component_type"]
        )
    
    async def execute(self, image_path: str, component_type: str) -> ToolResult:
        if not self._llm:
            return ToolResult(success=False, error_message="LLM client not configured")
        
        resolved = resolve_image_path(self._workspace, image_path)
        if not resolved:
            return ToolResult(success=False, error_message=f"Cannot read image: {image_path}")

        image_base64 = encode_image_to_base64(str(resolved))
        if not image_base64:
            return ToolResult(success=False, error_message=f"Cannot read image: {image_path}")
        
        mime_type = get_image_mime_type(str(resolved))
        
        if not hasattr(self, "_jinja") or self._jinja is None:
            self._jinja = _get_prompt_env()
        prompt = self._jinja.get_template("vision/extract_components.j2").render(
            component_type=component_type
        )
        
        try:
            from utils.llm import Message
            
            message = Message.user_with_image(
                text=prompt,
                image_base64=image_base64,
                mime_type=mime_type
            )
            
            response = await self._llm.chat_messages(messages=[message], temperature=0.3)
            content = response.content if hasattr(response, 'content') else str(response)
            
            import json
            import re
            json_match = re.search(r'\{[\s\S]*\}', content)
            if json_match:
                data = json.loads(json_match.group())
                return ToolResult(success=True, data=data)
            
            return ToolResult(success=True, data={"raw_extraction": content})
            
        except Exception as e:
            return ToolResult(success=False, error_message=f"Extraction failed: {e}")


def create_vision_tools(llm_client=None, workspace: Workspace = None) -> List[BaseTool]:
    """Create all vision tools with optional LLM client"""
    tools = [
        AnalyzeImageTool(llm_client, workspace=workspace),
        CompareWithScreenshotTool(llm_client, workspace=workspace),
        ExtractComponentsTool(llm_client, workspace=workspace),
    ]
    return tools
