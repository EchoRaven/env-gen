"""
Verification Tools - Automated verification for generated applications

1. CompareScreenshotsTool - Compare reference images with generated UI screenshots
2. VerifyAPIContractTool - Verify frontend API calls match backend routes
"""

import json
import logging
import re
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple

from utils.tool import BaseTool, ToolCategory, ToolResult
from workspace import Workspace

logger = logging.getLogger(__name__)


# =============================================================================
# 1. SCREENSHOT COMPARISON TOOL
# =============================================================================

class CompareScreenshotsTool(BaseTool):
    """Compare reference screenshots with generated UI screenshots."""
    
    NAME = "compare_screenshots"
    DESCRIPTION = """Compare reference images with generated screenshots.

Calculates visual similarity score between reference design and actual UI.

Examples:
    compare_screenshots("screenshots/reference/home.png", "screenshots/generated/home.png")
    compare_screenshots()  # Auto-compare all matching pairs

Returns:
- similarity_score: 0.0-1.0 (1.0 = identical)
- differences: List of regions that differ
- recommendation: Pass/Fail with suggestions

Requires: pip install pillow scikit-image
"""
    
    def __init__(self, workspace: Optional[Workspace] = None):
        super().__init__(name=self.NAME, category=ToolCategory.FILE)
        self.workspace = workspace
        self._logger = logging.getLogger(__name__)
    
    @property
    def tool_definition(self):
        return self.get_tool_param()
    
    def get_tool_param(self):
        return {
            "type": "function",
            "function": {
                "name": self.NAME,
                "description": self.DESCRIPTION,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "reference": {
                            "type": "string",
                            "description": "Path to reference image (optional, auto-detects if not provided)"
                        },
                        "generated": {
                            "type": "string",
                            "description": "Path to generated screenshot (optional, auto-detects if not provided)"
                        },
                        "threshold": {
                            "type": "number",
                            "description": "Minimum similarity score to pass (default: 0.7)"
                        }
                    },
                    "required": []
                }
            }
        }
    
    async def execute(
        self, 
        reference: Optional[str] = None, 
        generated: Optional[str] = None,
        threshold: float = 0.7
    ) -> ToolResult:
        """Compare screenshots and return similarity analysis."""
        
        # Check dependencies
        try:
            from PIL import Image
            import numpy as np
        except ImportError:
            return ToolResult(
                success=False,
                error_message="Missing dependencies. Run: pip install pillow numpy"
            )
        
        try:
            from skimage.metrics import structural_similarity as ssim
            HAS_SKIMAGE = True
        except ImportError:
            HAS_SKIMAGE = False
            self._logger.warning("scikit-image not installed, using basic comparison")
        
        if not self.workspace:
            return ToolResult(success=False, error_message="Workspace not configured")
        
        # Auto-detect image pairs if not specified
        if not reference or not generated:
            pairs = self._find_image_pairs()
            if not pairs:
                return ToolResult(
                    success=True,
                    data={
                        "status": "no_pairs",
                        "message": "No matching reference/generated image pairs found.",
                        "hint": "Place reference images in 'screenshots/' and generated ones will be compared automatically."
                    }
                )
        else:
            pairs = [(reference, generated)]
        
        results = []
        overall_score = 0.0
        
        for ref_path, gen_path in pairs:
            try:
                ref_full = self.workspace.resolve(ref_path)
                gen_full = self.workspace.resolve(gen_path)
                
                if not ref_full.exists():
                    results.append({
                        "reference": ref_path,
                        "generated": gen_path,
                        "error": f"Reference not found: {ref_path}"
                    })
                    continue
                
                if not gen_full.exists():
                    results.append({
                        "reference": ref_path,
                        "generated": gen_path,
                        "error": f"Generated not found: {gen_path}"
                    })
                    continue
                
                # Load images
                ref_img = Image.open(ref_full).convert('RGB')
                gen_img = Image.open(gen_full).convert('RGB')
                
                # Resize to same dimensions for comparison
                if ref_img.size != gen_img.size:
                    gen_img = gen_img.resize(ref_img.size, Image.Resampling.LANCZOS)
                
                # Convert to numpy arrays
                ref_arr = np.array(ref_img)
                gen_arr = np.array(gen_img)
                
                # Calculate similarity
                if HAS_SKIMAGE:
                    # Use SSIM (Structural Similarity Index)
                    score, diff_map = ssim(ref_arr, gen_arr, multichannel=True, full=True, channel_axis=2)
                    
                    # Find regions with low similarity
                    diff_regions = self._find_diff_regions(diff_map, threshold=0.5)
                else:
                    # Basic pixel-wise comparison
                    diff = np.abs(ref_arr.astype(float) - gen_arr.astype(float))
                    score = 1.0 - (np.mean(diff) / 255.0)
                    diff_regions = []
                
                overall_score += score
                
                # Determine pass/fail
                passed = score >= threshold
                
                result = {
                    "reference": ref_path,
                    "generated": gen_path,
                    "similarity_score": round(score, 3),
                    "passed": passed,
                    "threshold": threshold,
                    "diff_regions": diff_regions[:5] if diff_regions else [],  # Top 5 differences
                }
                
                if not passed:
                    result["suggestions"] = self._get_suggestions(score, diff_regions)
                
                results.append(result)
                
            except Exception as e:
                results.append({
                    "reference": ref_path,
                    "generated": gen_path,
                    "error": str(e)
                })
        
        # Calculate overall results
        valid_results = [r for r in results if "similarity_score" in r]
        avg_score = overall_score / len(valid_results) if valid_results else 0.0
        all_passed = all(r.get("passed", False) for r in valid_results)
        
        return ToolResult(
            success=True,
            data={
                "overall_score": round(avg_score, 3),
                "overall_passed": all_passed,
                "threshold": threshold,
                "comparisons": results,
                "summary": f"Compared {len(pairs)} image pairs. Average similarity: {avg_score:.1%}. {'PASSED' if all_passed else 'NEEDS IMPROVEMENT'}"
            }
        )
    
    def _find_image_pairs(self) -> List[Tuple[str, str]]:
        """Find matching reference and generated image pairs."""
        pairs = []
        
        # Look for reference images
        ref_dirs = [
            self.workspace.resolve("screenshots"),
            self.workspace.resolve("design/screenshots"),
            self.workspace.resolve("reference"),
        ]
        
        # Look for generated screenshots
        gen_dirs = [
            self.workspace.resolve("screenshots/generated"),
            self.workspace.resolve("screenshots/test"),
            self.workspace.resolve("app/screenshots"),
        ]
        
        ref_images = {}
        for ref_dir in ref_dirs:
            if ref_dir.exists():
                for img in ref_dir.glob("*.png"):
                    # Skip if in 'generated' or 'test' subdirectory
                    if "generated" not in str(img) and "test" not in str(img):
                        name = img.stem.lower()
                        ref_images[name] = str(self.workspace.relative(img))
        
        # Match with generated images
        for gen_dir in gen_dirs:
            if gen_dir.exists():
                for img in gen_dir.glob("*.png"):
                    name = img.stem.lower()
                    # Try to match by name
                    for ref_name, ref_path in ref_images.items():
                        if name in ref_name or ref_name in name:
                            gen_path = str(self.workspace.relative(img))
                            pairs.append((ref_path, gen_path))
                            break
        
        return pairs
    
    def _find_diff_regions(self, diff_map: Any, threshold: float) -> List[Dict]:
        """Find regions with significant differences."""
        import numpy as np
        
        # Convert to grayscale if needed
        if len(diff_map.shape) == 3:
            diff_gray = np.mean(diff_map, axis=2)
        else:
            diff_gray = diff_map
        
        # Find low-similarity regions
        low_sim = diff_gray < threshold
        
        # Simple region detection (divide into grid)
        h, w = diff_gray.shape
        grid_size = 4
        regions = []
        
        for i in range(grid_size):
            for j in range(grid_size):
                y1, y2 = i * h // grid_size, (i + 1) * h // grid_size
                x1, x2 = j * w // grid_size, (j + 1) * w // grid_size
                
                region_diff = 1.0 - np.mean(diff_gray[y1:y2, x1:x2])
                if region_diff > 0.1:  # More than 10% difference
                    regions.append({
                        "location": f"Row {i+1}, Col {j+1}",
                        "area": f"({x1},{y1}) to ({x2},{y2})",
                        "difference": round(region_diff, 2)
                    })
        
        # Sort by difference (most different first)
        regions.sort(key=lambda r: r["difference"], reverse=True)
        return regions
    
    def _get_suggestions(self, score: float, diff_regions: List[Dict]) -> List[str]:
        """Get improvement suggestions based on comparison results."""
        suggestions = []
        
        if score < 0.3:
            suggestions.append("Layout is very different - check component structure and positioning")
            suggestions.append("Verify correct page is being rendered")
        elif score < 0.5:
            suggestions.append("Significant differences - check colors, fonts, and spacing")
            suggestions.append("Compare component hierarchy with reference")
        elif score < 0.7:
            suggestions.append("Minor differences - fine-tune padding, margins, colors")
            suggestions.append("Check responsive breakpoints")
        
        if diff_regions:
            top_region = diff_regions[0]
            suggestions.append(f"Largest difference at {top_region['location']} - focus there first")
        
        return suggestions


# =============================================================================
# 2. API CONTRACT VERIFICATION TOOL
# =============================================================================

class VerifyAPIContractTool(BaseTool):
    """Verify frontend API calls match backend routes."""
    
    NAME = "verify_api_contract"
    DESCRIPTION = """Verify that frontend API calls match backend routes.

Analyzes:
- Backend: Express routes from src/routes/*.js
- Frontend: API calls from src/services/api.js
- Spec: Expected endpoints from design/spec.api.json

Returns:
- matched: APIs that exist in both frontend and backend
- missing_in_backend: Frontend calls routes that don't exist
- missing_in_frontend: Backend routes not used by frontend
- mismatched: Routes with different methods or paths

Example:
    verify_api_contract()  # Auto-detect and verify
"""
    
    def __init__(self, workspace: Optional[Workspace] = None):
        super().__init__(name=self.NAME, category=ToolCategory.FILE)
        self.workspace = workspace
        self._logger = logging.getLogger(__name__)
    
    @property
    def tool_definition(self):
        return self.get_tool_param()
    
    def get_tool_param(self):
        return {
            "type": "function",
            "function": {
                "name": self.NAME,
                "description": self.DESCRIPTION,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "backend_dir": {
                            "type": "string",
                            "description": "Backend routes directory (default: app/backend/src/routes)"
                        },
                        "frontend_api": {
                            "type": "string",
                            "description": "Frontend API file (default: app/frontend/src/services/api.js)"
                        },
                        "spec_file": {
                            "type": "string",
                            "description": "API spec file (default: design/spec.api.json)"
                        }
                    },
                    "required": []
                }
            }
        }
    
    async def execute(
        self,
        backend_dir: str = "app/backend/src/routes",
        frontend_api: str = "app/frontend/src/services/api.js",
        spec_file: str = "design/spec.api.json"
    ) -> ToolResult:
        """Verify API contract between frontend and backend."""
        
        if not self.workspace:
            return ToolResult(success=False, error_message="Workspace not configured")
        
        # Extract backend routes
        backend_routes = self._extract_backend_routes(backend_dir)
        
        # Extract frontend API calls
        frontend_calls = self._extract_frontend_calls(frontend_api)
        
        # Extract spec (if exists)
        spec_endpoints = self._extract_spec_endpoints(spec_file)
        
        # Compare and analyze
        analysis = self._analyze_contract(backend_routes, frontend_calls, spec_endpoints)
        
        # Generate report
        issues = []
        
        # Missing in backend (critical)
        for call in analysis["missing_in_backend"]:
            issues.append({
                "severity": "critical",
                "type": "missing_backend_route",
                "frontend_call": call,
                "message": f"Frontend calls {call['method']} {call['path']} but backend has no matching route",
                "fix": f"Add route in backend: router.{call['method'].lower()}('{call['path']}', ...)"
            })
        
        # Missing in frontend (warning)
        for route in analysis["missing_in_frontend"]:
            issues.append({
                "severity": "warning",
                "type": "unused_backend_route",
                "backend_route": route,
                "message": f"Backend has {route['method']} {route['path']} but frontend doesn't use it",
                "fix": "Consider if this route is needed, or add frontend function to use it"
            })
        
        # Method mismatches (critical)
        for mismatch in analysis["method_mismatches"]:
            backend_methods = mismatch.get("backend_methods", [mismatch.get("backend_method", "unknown")])
            issues.append({
                "severity": "critical",
                "type": "method_mismatch",
                "path": mismatch["path"],
                "frontend_method": mismatch["frontend_method"],
                "backend_methods": backend_methods,
                "message": mismatch.get("message", f"Method mismatch for {mismatch['path']}: frontend uses {mismatch['frontend_method']}, backend expects {', '.join(backend_methods)}"),
                "fix": f"Change frontend to use one of [{', '.join(backend_methods)}] or add {mismatch['frontend_method']} route to backend"
            })
        
        # Param format issues (warning)
        for issue in analysis.get("param_format_issues", []):
            issues.append({
                "severity": "warning",
                "type": "param_format_issue",
                "path": issue["path"],
                "message": issue["warning"],
                "fix": issue["recommendation"]
            })
        
        # Auth consistency warnings
        for warn in analysis.get("auth_warnings", []):
            issues.append({
                "severity": "warning",
                "type": "auth_inconsistency",
                "path": warn["path"],
                "message": warn["warning"],
                "fix": warn["recommendation"]
            })
        
        # Spec violations (if design spec exists)
        spec_violations = analysis.get("spec_violations")
        spec_issues_count = 0
        if spec_violations:
            # Spec not implemented in backend (critical)
            for ep in spec_violations.get("spec_not_in_backend", []):
                issues.append({
                    "severity": "critical",
                    "type": "spec_not_implemented_backend",
                    "path": ep.get("path", ""),
                    "method": ep.get("method", ""),
                    "message": f"Design spec defines {ep.get('method')} {ep.get('path')} but backend doesn't implement it",
                    "fix": "Implement this endpoint in backend as specified in design/spec.api.json"
                })
                spec_issues_count += 1
            
            # Spec not called in frontend (warning)
            for ep in spec_violations.get("spec_not_in_frontend", []):
                issues.append({
                    "severity": "warning",
                    "type": "spec_not_used_frontend",
                    "path": ep.get("path", ""),
                    "method": ep.get("method", ""),
                    "message": f"Design spec defines {ep.get('method')} {ep.get('path')} but frontend doesn't use it",
                    "fix": "Add API call in frontend or remove from spec if not needed"
                })
            
            # Backend has extra routes not in spec (info)
            for route in spec_violations.get("backend_missing_from_spec", []):
                issues.append({
                    "severity": "info",
                    "type": "backend_extra_route",
                    "path": route.get("path", ""),
                    "method": route.get("method", ""),
                    "message": f"Backend has {route.get('method')} {route.get('path')} but it's not in design spec",
                    "fix": "Add to design spec if intentional, or remove if not needed"
                })
        
        # Calculate health score
        total_calls = len(frontend_calls)
        matched = len(analysis["matched"])
        critical_issues = len([i for i in issues if i["severity"] == "critical"])
        
        if total_calls == 0:
            health_score = 0.0
            status = "NO_API_CALLS"
        elif critical_issues == 0:
            health_score = 1.0
            status = "HEALTHY"
        else:
            health_score = matched / total_calls if total_calls > 0 else 0.0
            status = "ISSUES_FOUND"
        
        # Build summary
        summary = {
            "backend_routes": len(backend_routes),
            "frontend_calls": len(frontend_calls),
            "spec_endpoints": len(spec_endpoints),
            "matched": matched,
            "missing_in_backend": len(analysis["missing_in_backend"]),
            "missing_in_frontend": len(analysis["missing_in_frontend"]),
            "method_mismatches": len(analysis["method_mismatches"]),
            "param_format_issues": len(analysis.get("param_format_issues", [])),
            "auth_warnings": len(analysis.get("auth_warnings", []))
        }
        
        # Add spec validation counts if spec exists
        if spec_violations:
            summary["spec_violations"] = {
                "backend_missing_from_spec": len(spec_violations.get("backend_missing_from_spec", [])),
                "frontend_missing_from_spec": len(spec_violations.get("frontend_missing_from_spec", [])),
                "spec_not_in_backend": len(spec_violations.get("spec_not_in_backend", [])),
                "spec_not_in_frontend": len(spec_violations.get("spec_not_in_frontend", [])),
            }
        
        return ToolResult(
            success=True,
            data={
                "status": status,
                "health_score": round(health_score, 2),
                "summary": summary,
                "matched_endpoints": analysis["matched"],
                "issues": issues,
                "recommendation": self._get_recommendation(status, issues)
            }
        )
    
    def _extract_backend_routes(self, backend_dir: str) -> List[Dict]:
        """Extract routes from Express backend."""
        routes = []
        
        dir_path = self.workspace.resolve(backend_dir)
        if not dir_path.exists():
            # No more multi-candidate guess loop — the workspace router
            # decides where the path goes. If the caller passed a path
            # that doesn't exist, log it and bail with an empty result.
            self._logger.warning(
                f"Backend routes directory not found: {backend_dir} "
                f"(resolved to {dir_path}). Pass a path like 'app/backend/routes' "
                f"or whichever subdir holds the route files in this project."
            )
            return routes
        
        # First, try to parse server.js to get route mount points
        route_mounts = self._parse_server_route_mounts(dir_path.parent.parent)
        
        # Parse route files
        route_pattern = re.compile(
            r'router\.(get|post|put|patch|delete)\s*\(\s*[\'"]([^\'"]+)[\'"]',
            re.IGNORECASE
        )
        
        # Also match app.get/post/etc patterns
        app_route_pattern = re.compile(
            r'app\.(get|post|put|patch|delete)\s*\(\s*[\'"]([^\'"]+)[\'"]',
            re.IGNORECASE
        )
        
        for js_file in dir_path.glob("*.js"):
            try:
                content = js_file.read_text(encoding='utf-8', errors='replace')
                
                # Get mount prefix from server.js parsing or infer from filename
                file_stem = js_file.stem
                if file_stem in route_mounts:
                    prefix = route_mounts[file_stem]
                else:
                    # Infer from filename
                    prefix = f"/api/{file_stem}" if file_stem not in ["index", "router"] else "/api"
                
                # Check for requireAuth in routes to mark auth requirement
                has_auth_pattern = re.compile(r'(requireAuth|authMiddleware|verifyToken)', re.IGNORECASE)
                
                for match in route_pattern.finditer(content):
                    method = match.group(1).upper()
                    path = match.group(2)
                    
                    # Build full path
                    if path.startswith("/"):
                        full_path = prefix + path if prefix != "/api" else "/api" + path
                    else:
                        full_path = prefix + "/" + path
                    full_path = full_path.replace("//", "/")
                    
                    # Check if this route requires auth (look nearby in the code)
                    line_start = max(0, match.start() - 200)
                    line_end = min(len(content), match.end() + 100)
                    context = content[line_start:line_end]
                    requires_auth = bool(has_auth_pattern.search(context))
                    
                    routes.append({
                        "method": method,
                        "path": full_path,
                        "file": js_file.name,
                        "requires_auth": requires_auth,
                        "normalized": self._normalize_path(full_path)
                    })
                    
            except Exception as e:
                self._logger.debug(f"Error parsing {js_file}: {e}")
        
        return routes
    
    def _parse_server_route_mounts(self, backend_root: Path) -> Dict[str, str]:
        """Parse server.js to find route mount points."""
        mounts = {}
        
        server_files = [
            backend_root / "server.js",
            backend_root / "app.js",
            backend_root / "index.js",
            backend_root / "src" / "server.js",
            backend_root / "src" / "app.js",
        ]
        
        server_path = None
        for sf in server_files:
            if sf.exists():
                server_path = sf
                break
        
        if not server_path:
            return mounts
        
        try:
            content = server_path.read_text(encoding='utf-8', errors='replace')
            
            # Pattern: app.use('/api/movies', require('./routes/movies'))
            # Pattern: app.use('/api/movies', moviesRoutes)
            mount_pattern = re.compile(
                r'app\.use\s*\(\s*[\'"]([^\'"]+)[\'"].*?(?:require\s*\([\'"]\.?/?(?:src/)?routes/(\w+)[\'"]|(\w+)Routes)',
                re.IGNORECASE | re.DOTALL
            )
            
            for match in mount_pattern.finditer(content):
                mount_path = match.group(1)
                route_file = match.group(2) or match.group(3)
                if route_file:
                    mounts[route_file.lower()] = mount_path
            
            # Also check for imported route usage
            # import moviesRoutes from './routes/movies'
            # app.use('/api/movies', moviesRoutes)
            import_pattern = re.compile(
                r'import\s+(\w+)\s+from\s+[\'"]\.?/?(?:src/)?routes/(\w+)[\'"]',
                re.IGNORECASE
            )
            
            imports = {}
            for match in import_pattern.finditer(content):
                var_name = match.group(1)
                file_name = match.group(2)
                imports[var_name] = file_name
            
            use_pattern = re.compile(
                r'app\.use\s*\(\s*[\'"]([^\'"]+)[\'"],\s*(\w+)\s*\)',
                re.IGNORECASE
            )
            
            for match in use_pattern.finditer(content):
                mount_path = match.group(1)
                var_name = match.group(2)
                if var_name in imports:
                    mounts[imports[var_name].lower()] = mount_path
            
        except Exception as e:
            self._logger.debug(f"Error parsing server file: {e}")
        
        return mounts
    
    def _extract_frontend_calls(self, frontend_api: str) -> List[Dict]:
        """Extract API calls from frontend service."""
        calls = []
        
        api_path = self.workspace.resolve(frontend_api)
        if not api_path.exists():
            self._logger.warning(
                f"Frontend API file not found: {frontend_api} "
                f"(resolved to {api_path}). Pass the full project-relative "
                f"path (e.g. 'app/frontend/src/api.js')."
            )
            return calls
        
        try:
            content = api_path.read_text(encoding='utf-8', errors='replace')
            
            # Pattern 1: Axios-style http.method() calls
            # e.g., http.get('/api/users'), http.post('/api/login', payload)
            axios_pattern = re.compile(
                r'(?:http|axios|api|client)\s*\.\s*(get|post|put|patch|delete)\s*\(\s*[`\'"]([^`\'"]+)[`\'"]',
                re.IGNORECASE
            )
            
            # Pattern 2: fetch() with method
            fetch_pattern = re.compile(
                r'fetch\s*\(\s*[`\'"]([^`\'"]+)[`\'"].*?method:\s*[\'"](\w+)[\'"]',
                re.IGNORECASE | re.DOTALL
            )
            
            # Pattern 3: request() helper with method option
            request_pattern = re.compile(
                r'request\s*\(\s*[`\'"]([^`\'"]+)[`\'"].*?method:\s*[\'"](\w+)[\'"]',
                re.IGNORECASE | re.DOTALL
            )
            
            # Pattern 4: Simple GET requests
            simple_get = re.compile(
                r'(?:return\s+)?(?:await\s+)?(?:http|axios|api|client)\s*\.\s*get\s*\(\s*[`\'"]([^`\'"]+)[`\'"]',
                re.IGNORECASE
            )
            
            # Pattern 5: fetch without explicit method (defaults to GET)
            simple_fetch = re.compile(
                r'fetch\s*\(\s*[`\'"]([^`\'"]+)[`\'"](?:\s*\)|\s*,\s*\{(?![^}]*method:))',
                re.IGNORECASE
            )
            
            seen_paths = set()
            
            # Extract axios-style calls (most common pattern)
            for match in axios_pattern.finditer(content):
                method = match.group(1).upper()
                path = match.group(2)
                key = (path, method)
                if key not in seen_paths:
                    seen_paths.add(key)
                    calls.append(self._create_call_entry(path, method))
            
            # Extract fetch calls with method
            for match in fetch_pattern.finditer(content):
                path = match.group(1)
                method = match.group(2).upper()
                key = (path, method)
                if key not in seen_paths:
                    seen_paths.add(key)
                    calls.append(self._create_call_entry(path, method))
            
            # Extract request helper calls
            for match in request_pattern.finditer(content):
                path = match.group(1)
                method = match.group(2).upper()
                key = (path, method)
                if key not in seen_paths:
                    seen_paths.add(key)
                    calls.append(self._create_call_entry(path, method))
            
            # Extract simple fetch (GET)
            for match in simple_fetch.finditer(content):
                path = match.group(1)
                key = (path, "GET")
                if key not in seen_paths:
                    seen_paths.add(key)
                    calls.append(self._create_call_entry(path, "GET"))
                    
        except Exception as e:
            self._logger.debug(f"Error parsing frontend API: {e}")
        
        return calls
    
    def _create_call_entry(self, path: str, method: str) -> Dict:
        """Create standardized call entry."""
        # Handle template literals
        path = re.sub(r'\$\{[^}]+\}', ':id', path)
        path = path.replace('${', ':').replace('}', '')
        
        # Normalize
        if not path.startswith("/"):
            path = "/" + path
        
        return {
            "method": method.upper(),
            "path": path,
            "normalized": self._normalize_path(path)
        }
    
    def _extract_spec_endpoints(self, spec_file: str) -> List[Dict]:
        """Extract endpoints from API spec."""
        endpoints = []
        
        spec_path = self.workspace.resolve(spec_file)
        if not spec_path.exists():
            return endpoints
        
        try:
            spec = json.loads(spec_path.read_text(encoding='utf-8'))
            
            for endpoint in spec.get("endpoints", []):
                endpoints.append({
                    "method": endpoint.get("method", "GET").upper(),
                    "path": endpoint.get("path", ""),
                    "normalized": self._normalize_path(endpoint.get("path", ""))
                })
                
        except Exception as e:
            self._logger.debug(f"Error parsing spec: {e}")
        
        return endpoints
    
    def _normalize_path(self, path: str) -> str:
        """Normalize path for comparison (replace params with :param)."""
        # Replace UUIDs and numbers with :id
        path = re.sub(r'/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}', '/:id', path)
        path = re.sub(r'/\d+', '/:id', path)
        # Replace path params
        path = re.sub(r'/:[\w]+', '/:id', path)
        # Remove trailing slash
        path = path.rstrip('/')
        # Lowercase
        return path.lower()
    
    def _analyze_contract(
        self,
        backend_routes: List[Dict],
        frontend_calls: List[Dict],
        spec_endpoints: List[Dict]
    ) -> Dict:
        """Analyze the API contract against design spec."""
        
        # Create lookup maps
        backend_by_normalized = {}
        for r in backend_routes:
            key = (r["normalized"], r["method"])
            if key not in backend_by_normalized:
                backend_by_normalized[key] = r
        
        backend_set = set(backend_by_normalized.keys())
        frontend_set = {(c["normalized"], c["method"]) for c in frontend_calls}
        spec_set = {(s["normalized"], s["method"]) for s in spec_endpoints} if spec_endpoints else set()
        
        # Find matches between frontend and backend
        matched = []
        for call in frontend_calls:
            key = (call["normalized"], call["method"])
            if key in backend_set:
                backend_route = backend_by_normalized[key]
                matched.append({
                    "method": call["method"],
                    "path": call["path"],
                    "backend_file": backend_route.get("file", "unknown"),
                    "requires_auth": backend_route.get("requires_auth", False)
                })
        
        # Find missing in backend (frontend calls but backend doesn't have)
        missing_in_backend = []
        for call in frontend_calls:
            key = (call["normalized"], call["method"])
            if key not in backend_set:
                # Check if path exists with different method
                path_exists = any(r["normalized"] == call["normalized"] for r in backend_routes)
                if not path_exists:
                    missing_in_backend.append(call)
        
        # Find missing in frontend (backend has but frontend doesn't call)
        missing_in_frontend = []
        for route in backend_routes:
            key = (route["normalized"], route["method"])
            if key not in frontend_set:
                # Skip common utility routes
                if not any(skip in route["path"] for skip in ["/health", "/status", "/metrics"]):
                    missing_in_frontend.append(route)
        
        # === NEW: Validate against Design Spec ===
        spec_violations = {
            "backend_missing_from_spec": [],  # Backend has routes not in spec
            "frontend_missing_from_spec": [],  # Frontend calls endpoints not in spec
            "spec_not_in_backend": [],  # Spec defines but backend doesn't have
            "spec_not_in_frontend": [],  # Spec defines but frontend doesn't call
        }
        
        if spec_set:
            # Check backend against spec
            for route in backend_routes:
                key = (route["normalized"], route["method"])
                if key not in spec_set:
                    # Skip common utility routes
                    if not any(skip in route["path"] for skip in ["/health", "/status", "/metrics"]):
                        spec_violations["backend_missing_from_spec"].append(route)
            
            # Check frontend against spec
            for call in frontend_calls:
                key = (call["normalized"], call["method"])
                if key not in spec_set:
                    spec_violations["frontend_missing_from_spec"].append(call)
            
            # Check spec endpoints are implemented
            for spec_ep in spec_endpoints:
                key = (spec_ep["normalized"], spec_ep["method"])
                if key not in backend_set:
                    spec_violations["spec_not_in_backend"].append(spec_ep)
                if key not in frontend_set:
                    spec_violations["spec_not_in_frontend"].append(spec_ep)
        
        # Find method mismatches
        # Only report mismatch if frontend calls a path that exists in backend
        # but the specific method doesn't exist (not just different)
        method_mismatches = []
        for call in frontend_calls:
            call_key = (call["normalized"], call["method"])
            # Path exists but method doesn't match ANY backend route for that path
            if call_key not in backend_set:
                matching_paths = [r for r in backend_routes if r["normalized"] == call["normalized"]]
                if matching_paths:
                    # Path exists but method doesn't - this is a real mismatch
                    available_methods = [r["method"] for r in matching_paths]
                    method_mismatches.append({
                        "path": call["path"],
                        "frontend_method": call["method"],
                        "backend_methods": available_methods,
                        "message": f"Frontend uses {call['method']} but backend only supports {', '.join(available_methods)}"
                    })
        
        # Find path parameter format mismatches (slug vs UUID)
        param_mismatches = self._check_param_format_issues(backend_routes, frontend_calls)
        
        # Find potential auth mismatches
        auth_warnings = self._check_auth_consistency(matched, backend_routes)
        
        return {
            "matched": matched,
            "missing_in_backend": missing_in_backend,
            "missing_in_frontend": missing_in_frontend,
            "method_mismatches": method_mismatches,
            "param_format_issues": param_mismatches,
            "auth_warnings": auth_warnings,
            "spec_violations": spec_violations if spec_set else None,
        }
    
    def _check_param_format_issues(
        self,
        backend_routes: List[Dict],
        frontend_calls: List[Dict]
    ) -> List[Dict]:
        """Check for potential slug vs UUID parameter issues."""
        issues = []
        
        # Look for nested routes that might have param format issues
        nested_pattern = re.compile(r'/:\w+/(cast|showtimes|reviews|similar|related)')
        
        for call in frontend_calls:
            if nested_pattern.search(call["path"]):
                # This is a nested route - check if parent route supports slug
                issues.append({
                    "path": call["path"],
                    "warning": "Nested route detected. Ensure parent ID parameter supports both UUID and slug if parent route does.",
                    "recommendation": "Backend should use resolveId() helper to convert slug to UUID before nested queries"
                })
        
        return issues
    
    def _check_auth_consistency(
        self,
        matched: List[Dict],
        backend_routes: List[Dict]
    ) -> List[Dict]:
        """Check for potential auth requirement inconsistencies."""
        warnings = []
        
        # Common patterns that typically require auth
        auth_required_patterns = [
            r'/cart',
            r'/orders',
            r'/checkout',
            r'/profile',
            r'/favorites',
            r'/watchlist',
            r'/booking',
        ]
        
        for match in matched:
            path = match["path"].lower()
            requires_auth = match.get("requires_auth", False)
            
            # Check if path pattern suggests auth should be required
            should_require = any(re.search(p, path) for p in auth_required_patterns)
            
            if should_require and not requires_auth:
                warnings.append({
                    "path": match["path"],
                    "warning": "This endpoint likely needs authentication but backend doesn't seem to require it",
                    "recommendation": "Add requireAuth middleware to this route"
                })
        
        return warnings
    
    def _infer_from_function_name(self, func_name: str) -> Optional[str]:
        """Infer API path from function name."""
        # Common patterns
        patterns = {
            r'^get(\w+)s$': ('GET', '/api/{0}s'),           # getUsers -> GET /api/users
            r'^get(\w+)ById$': ('GET', '/api/{0}s/:id'),    # getUserById -> GET /api/users/:id
            r'^create(\w+)$': ('POST', '/api/{0}s'),        # createUser -> POST /api/users
            r'^update(\w+)$': ('PUT', '/api/{0}s/:id'),     # updateUser -> PUT /api/users/:id
            r'^delete(\w+)$': ('DELETE', '/api/{0}s/:id'),  # deleteUser -> DELETE /api/users/:id
            r'^search(\w+)s$': ('GET', '/api/{0}s/search'), # searchUsers -> GET /api/users/search
        }
        
        for pattern, (method, path_template) in patterns.items():
            match = re.match(pattern, func_name, re.IGNORECASE)
            if match:
                resource = match.group(1).lower()
                return path_template.format(resource)
        
        return None
    
    def _get_recommendation(self, status: str, issues: List[Dict]) -> str:
        """Get recommendation based on analysis."""
        if status == "HEALTHY":
            return "API contract is healthy. All frontend calls have matching backend routes."
        
        if status == "NO_API_CALLS":
            return "No API calls detected in frontend. Check if api.js exists and contains fetch/request calls."
        
        critical = [i for i in issues if i["severity"] == "critical"]
        warnings = [i for i in issues if i["severity"] == "warning"]
        
        if critical:
            return f"Found {len(critical)} critical issues. Fix these first - frontend will fail without matching backend routes."
        
        if warnings:
            return f"Found {len(warnings)} warnings. Backend has routes that frontend doesn't use - consider cleanup or future use."
        
        return "Review the issues above and fix as needed."


# =============================================================================
# 3. API SPEC GENERATION TOOL (Backend uses this)
# =============================================================================

class GenerateAPISpecTool(BaseTool):
    """Generate formal API specification from backend routes."""
    
    NAME = "generate_api_spec"
    DESCRIPTION = """Generate a formal API specification file from backend routes.

Backend Agent should call this BEFORE finish() to create a standardized API spec
that Frontend Agent can use.

Example:
    generate_api_spec()  # Auto-scan routes and generate spec
    generate_api_spec(output="design/api_spec_generated.json")

The generated spec includes:
- All endpoints with methods and paths
- Request/response schemas (inferred)
- Authentication requirements
- Parameter types (UUID vs slug support)

After generation, use send_message() to notify Frontend Agent.
"""
    
    # Phase 2 Fix B (attempt-4): role-gate so only backend (and the
    # broad-writers / orchestrator override) may author the API spec.
    # Frontend and design must NEVER write to spec.api.json — that's
    # the Phase 1/2 backend-owns-spec.api ownership invariant.
    # ``_BROAD_WRITERS`` mirrors path_routed_workspace's broad-writer
    # set so admin/coordinator agents can repair from the same
    # privilege level as elsewhere.
    _ALLOWED_AGENTS = frozenset({
        "backend",
        "orchestrator",
        "worker",
        "analysis_worker",
        "review_worker",
    })

    def __init__(self, workspace: Optional[Workspace] = None, agent_id: str = ""):
        super().__init__(name=self.NAME, category=ToolCategory.FILE)
        self.workspace = workspace
        self._logger = logging.getLogger(__name__)
        # ``_agent_id`` is wired up by ``AgentTooling.attach`` via
        # ``set_agent(self)`` or its setattr fallback (tooling.py:147-150).
        # Default "" means "unknown caller" → denied by the role gate.
        self._agent_id = agent_id

    def set_agent(self, agent) -> None:
        """Bind the caller agent's identity onto the tool instance so
        ``execute()`` can role-gate. Mirrors HubTool.set_agent."""
        self._agent_id = getattr(agent, "agent_id", self._agent_id)

    @property
    def tool_definition(self):
        return self.get_tool_param()

    def get_tool_param(self):
        return {
            "type": "function",
            "function": {
                "name": self.NAME,
                "description": self.DESCRIPTION,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "backend_dir": {
                            "type": "string",
                            "description": "Backend routes directory (default: app/backend/src/routes)"
                        },
                        "output": {
                            "type": "string",
                            "description": "Output file path (default: design/api_spec_generated.json)"
                        }
                    },
                    "required": []
                }
            }
        }

    async def execute(
        self,
        backend_dir: str = "app/backend/src/routes",
        output: str = "design/api_spec_generated.json"
    ) -> ToolResult:
        """Generate API spec from backend routes."""

        # Phase 2 Fix B: role-gate. The tool writes to ``design/``
        # (default ``design/api_spec_generated.json``, but any caller
        # may pass ``output="design/spec.api.json"``). The
        # backend-owns-spec.api ownership invariant says only backend
        # (or an admin override) may author here. Reject anyone else
        # before the file write happens — defence-in-depth alongside
        # the path-routed write gate.
        caller = (self._agent_id or "").strip().lower()
        if caller not in self._ALLOWED_AGENTS:
            return ToolResult(
                success=False,
                error_message=(
                    f"generate_api_spec role denied: agent_id={caller!r} "
                    f"is not permitted to author API spec files. "
                    f"Only backend (or orchestrator/broad-writers) may "
                    f"write design/spec.api.json or design/api_spec_generated.json. "
                    f"This is the Phase 1/2 backend-owns-spec.api invariant."
                ),
                metadata={"role_denied": True, "agent_id": caller},
            )

        if not self.workspace:
            return ToolResult(success=False, error_message="Workspace not configured")

        # Reuse route extraction from VerifyAPIContractTool
        verifier = VerifyAPIContractTool(workspace=self.workspace)
        routes = verifier._extract_backend_routes(backend_dir)
        
        if not routes:
            return ToolResult(
                success=False,
                error_message=f"No routes found in {backend_dir}. Create backend routes first."
            )
        
        # Group by resource
        endpoints_by_resource = {}
        for route in routes:
            # Extract resource from path (e.g., /api/movies/:id -> movies)
            parts = route["path"].split("/")
            resource = parts[2] if len(parts) > 2 else "root"
            
            if resource not in endpoints_by_resource:
                endpoints_by_resource[resource] = []
            
            endpoints_by_resource[resource].append({
                "method": route["method"],
                "path": route["path"],
                "requires_auth": route.get("requires_auth", False),
                "accepts_slug": self._infer_slug_support(route["path"]),
                "file": route.get("file", "unknown"),
                "request_schema": self._infer_request_schema(route),
                "response_schema": self._infer_response_schema(route),
            })
        
        # Build spec
        spec = {
            "version": "1.0",
            "generated_at": __import__("datetime").datetime.now().isoformat(),
            "base_url": "/api",
            "response_format": {
                "success": {
                    "single": "{ item: {...} }",
                    "list": "{ items: [...], pagination: {limit, offset, total} }"
                },
                "error": "{ error: { code: '...', message: '...' } }"
            },
            "authentication": {
                "type": "Bearer",
                "header": "Authorization",
                "format": "Bearer <token>",
                "obtain_from": "POST /api/auth/login"
            },
            "endpoints": endpoints_by_resource,
            "total_routes": len(routes),
            "notes": [
                "All :id parameters that accept slug are marked with accepts_slug: true",
                "Use this spec for frontend api.js implementation",
                "Date fields are ISO 8601 strings"
            ]
        }
        
        # Write to file
        output_path = self.workspace.resolve(output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(spec, indent=2, ensure_ascii=False))
        
        # Generate markdown summary for messaging
        summary = self._generate_markdown_summary(spec)
        
        return ToolResult(
            success=True,
            data={
                "output_file": output,
                "total_routes": len(routes),
                "resources": list(endpoints_by_resource.keys()),
                "markdown_summary": summary,
                "next_step": "Use send_message() to notify FrontendAgent about this spec file"
            }
        )
    
    def _infer_slug_support(self, path: str) -> bool:
        """Infer if path supports slug parameter."""
        # Routes with :idOrSlug or common patterns
        if ":idOrSlug" in path:
            return True
        # Single resource routes typically support slug
        if re.search(r'/\w+/:[\w]+$', path) and ":id" in path:
            return True
        return False
    
    def _infer_request_schema(self, route: Dict) -> Optional[Dict]:
        """Infer request schema from method and path."""
        method = route["method"]
        path = route["path"]
        
        if method == "GET":
            return {"type": "query_params", "note": "See implementation for params"}
        
        if method == "POST" and "auth" in path and "login" in path:
            return {"type": "json", "fields": ["email", "password"]}
        
        if method == "POST" and "auth" in path and "register" in path:
            return {"type": "json", "fields": ["email", "password", "fullName"]}
        
        if method in ["POST", "PUT", "PATCH"]:
            return {"type": "json", "note": "See implementation for fields"}
        
        return None
    
    def _infer_response_schema(self, route: Dict) -> Dict:
        """Infer response schema from method and path."""
        method = route["method"]
        path = route["path"]
        
        # List endpoints
        if method == "GET" and not re.search(r'/:[\w]+$', path):
            return {"type": "list", "format": "{ items: [...], pagination }"}
        
        # Single resource
        if method == "GET" and re.search(r'/:[\w]+$', path):
            return {"type": "single", "format": "{ item: {...} }"}
        
        # Create/Update
        if method in ["POST", "PUT", "PATCH"]:
            return {"type": "single", "format": "{ item: {...} }"}
        
        # Delete
        if method == "DELETE":
            return {"type": "success", "format": "{ success: true }"}
        
        return {"type": "unknown"}
    
    def _generate_markdown_summary(self, spec: Dict) -> str:
        """Generate markdown summary for send_message."""
        lines = [
            "## API Specification Generated",
            "",
            f"**Total Routes:** {spec['total_routes']}",
            f"**Base URL:** {spec['base_url']}",
            "",
            "### Response Format",
            "- **List:** `{ items: [...], pagination: {limit, offset, total} }`",
            "- **Single:** `{ item: {...} }`",
            "- **Error:** `{ error: { code, message } }`",
            "",
            "### Authentication",
            f"- Header: `{spec['authentication']['header']}: {spec['authentication']['format']}`",
            f"- Obtain from: `{spec['authentication']['obtain_from']}`",
            "",
            "### Endpoints by Resource",
            ""
        ]
        
        for resource, endpoints in spec["endpoints"].items():
            lines.append(f"**{resource.upper()}:**")
            for ep in endpoints:
                auth = "🔒" if ep["requires_auth"] else ""
                slug = "(accepts slug)" if ep["accepts_slug"] else ""
                lines.append(f"- `{ep['method']} {ep['path']}` {auth} {slug}")
            lines.append("")
        
        lines.extend([
            "### Important",
            "1. All date fields return ISO 8601 strings",
            "2. Check `design/api_spec_generated.json` for full details",
            "3. Use this spec to implement `api.js`"
        ])
        
        return "\n".join(lines)


# =============================================================================
# 4. WAIT FOR API SPEC TOOL (Frontend uses this)
# =============================================================================

class WaitForAPISpecTool(BaseTool):
    """Wait for backend API specification before implementing frontend."""
    
    NAME = "wait_for_api_spec"
    DESCRIPTION = """Wait for Backend Agent to generate API specification.

Frontend Agent should call this BEFORE implementing api.js.

Example:
    wait_for_api_spec()  # Check if spec exists, wait if not
    wait_for_api_spec(timeout=180)  # Wait up to 3 minutes

Returns the API spec content if available, or instructions to wait.
"""
    
    def __init__(self, workspace: Optional[Workspace] = None):
        super().__init__(name=self.NAME, category=ToolCategory.FILE)
        self.workspace = workspace
        self._logger = logging.getLogger(__name__)
    
    @property
    def tool_definition(self):
        return self.get_tool_param()
    
    def get_tool_param(self):
        return {
            "type": "function",
            "function": {
                "name": self.NAME,
                "description": self.DESCRIPTION,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "spec_file": {
                            "type": "string",
                            "description": "Path to API spec file (default: design/api_spec_generated.json)"
                        },
                        "timeout": {
                            "type": "integer",
                            "description": "Max seconds to wait (default: 120)"
                        }
                    },
                    "required": []
                }
            }
        }
    
    async def execute(
        self,
        spec_file: str = "design/api_spec_generated.json",
        timeout: int = 120
    ) -> ToolResult:
        """Check for API spec file."""
        
        if not self.workspace:
            return ToolResult(success=False, error_message="Workspace not configured")
        
        spec_path = self.workspace.resolve(spec_file)

        if not spec_path.exists():
            # Single canonical fallback — design specs live at
            # ``design/spec.api.json`` (project root). No more multi-
            # candidate guess loop; if the caller wants a different
            # spec, pass its path explicitly.
            spec_path = self.workspace.resolve("design/spec.api.json")
            if not spec_path.exists():
                return ToolResult(
                    success=True,
                    data={
                        "status": "NOT_READY",
                        "message": "API spec not found. Backend Agent may not have completed yet.",
                        "action_required": [
                            "1. Check inbox for messages from BackendAgent: check_inbox()",
                            "2. Ask Backend directly: ask_agent(agent_id='backend', question='Is API spec ready?')",
                            "3. Wait and retry: wait(seconds=60) then wait_for_api_spec()",
                            "4. If Backend is done, ask them to run generate_api_spec()"
                        ],
                        "expected_file": spec_file
                    }
                )
        
        # Read and parse spec
        try:
            spec = json.loads(spec_path.read_text(encoding='utf-8'))
            endpoints = spec.get("endpoints", {})
            if isinstance(endpoints, dict):
                resources = list(endpoints.keys())
                endpoints_count = len(endpoints)
            elif isinstance(endpoints, list):
                # Some generators serialize endpoints as a list; normalize for callers.
                resources = []
                for item in endpoints:
                    if not isinstance(item, dict):
                        continue
                    candidate = (
                        item.get("resource")
                        or item.get("group")
                        or item.get("tag")
                        or item.get("name")
                    )
                    if candidate:
                        resources.append(str(candidate))
                resources = sorted(set(resources))
                endpoints_count = len(endpoints)
            else:
                resources = []
                endpoints_count = 0
            
            # Extract key info for frontend
            return ToolResult(
                success=True,
                data={
                    "status": "READY",
                    "spec_file": str(self.workspace.relative(spec_path)),
                    "total_routes": spec.get("total_routes", endpoints_count),
                    "base_url": spec.get("base_url", "/api"),
                    "response_format": spec.get("response_format", {}),
                    "authentication": spec.get("authentication", {}),
                    "resources": resources,
                    "spec_content": spec,
                    "next_step": "Use this spec to implement services/api.js with correct endpoints and response handling"
                }
            )
            
        except Exception as e:
            return ToolResult(
                success=False,
                error_message=f"Failed to parse API spec: {e}"
            )


# =============================================================================
# FACTORY FUNCTION
# =============================================================================

def create_verification_tools(workspace: Optional[Workspace] = None) -> List[BaseTool]:
    """Create all verification tools."""
    # Imported lazily to avoid a module-load cycle (validation_tools pulls in the
    # runtime lifecycle/validation_runner).
    from tools.validation_tools import RunValidationTool
    return [
        CompareScreenshotsTool(workspace=workspace),
        VerifyAPIContractTool(workspace=workspace),
        GenerateAPISpecTool(workspace=workspace),
        WaitForAPISpecTool(workspace=workspace),
        RunValidationTool(workspace=workspace),
    ]

