"""
Data Engine Tools - Dataset discovery and SQL generation from HuggingFace

Tools:
- discover_datasets: Search HuggingFace for datasets (returns many results)
- preview_dataset: Quick preview with streaming (no full download)
- download_dataset: Full download to local cache (background)
- generate_seed_sql: Generate SQL INSERT statements (streaming mode)

All tools are independent. Use streaming for quick operations, download for large data.
"""

import logging
import threading
import json
import hashlib
import time
import sys
from pathlib import Path
from typing import Optional, Dict, Any, List

from utils.tool import BaseTool, ToolCategory, ToolResult

logger = logging.getLogger(__name__)

# Ensure repo-root packages (e.g., `data_engine`) are importable when running
# from the `agent` working directory.
_repo_root = Path(__file__).resolve().parents[4]
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

# Track background downloads
_download_status: Dict[str, Dict[str, Any]] = {}
_schema_probe_cache: Dict[str, Dict[str, Any]] = {}
_discover_cache: Dict[str, Dict[str, Any]] = {}
_preview_cache: Dict[str, Dict[str, Any]] = {}


def _stable_cache_key(namespace: str, payload: Dict[str, Any]) -> str:
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=True, default=str)
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return f"{namespace}:{digest}"


class DiscoverDatasetsTool(BaseTool):
    """Search HuggingFace for datasets."""
    
    NAME = "discover_datasets"
    DESCRIPTION = """Search HuggingFace for datasets matching your query.

Returns many results (default 15) sorted by relevance and popularity.

Examples:
- discover_datasets(query="steam games")
- discover_datasets(query="movies imdb ratings") 
- discover_datasets(query="restaurant reviews yelp")
- discover_datasets(query="amazon products")
- discover_datasets(query="airbnb listings housing")

You can pass expected_fields to prioritize datasets whose schema matches target columns.

Returns: dataset_id, downloads, description, score for each result.
Next step: Use preview_dataset(dataset_id) to see columns.
"""
    
    def __init__(self):
        super().__init__(name=self.NAME, category=ToolCategory.RUNTIME)
    
    def get_tool_param(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.NAME,
                "description": self.DESCRIPTION,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "What data you need (e.g., 'steam games', 'movies imdb', 'restaurant reviews')"
                        },
                        "limit": {
                            "type": "integer",
                            "description": "Max results to return (default: 15)"
                        },
                        "expected_fields": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Optional target fields to match (e.g., ['title', 'price', 'rating'])"
                        },
                        "schema_probe_count": {
                            "type": "integer",
                            "description": "How many top candidates to schema-probe for field matching (default: 5)"
                        },
                        "force_refresh": {
                            "type": "boolean",
                            "description": "Bypass local discovery cache and fetch fresh results"
                        }
                    },
                    "required": ["query"]
                }
            }
        }
    
    def tool_definition(self):
        return self.get_tool_param()
    
    def execute(
        self,
        query: Optional[str] = None,
        instruction: Optional[str] = None,
        limit: int = 15,
        expected_fields: Optional[List[str]] = None,
        schema_probe_count: int = 5,
        force_refresh: bool = False,
    ) -> ToolResult:
        """Execute dataset discovery."""
        global _discover_cache
        search_query = query or instruction
        if not search_query:
            return ToolResult(success=False, error_message="Please provide a query")

        normalized_expected = [
            str(f).strip().lower()
            for f in (expected_fields or [])
            if str(f).strip()
        ]
        cache_key = _stable_cache_key(
            "discover",
            {
                "query": search_query.strip().lower(),
                "limit": int(limit or 15),
                "expected_fields": sorted(normalized_expected),
                "schema_probe_count": int(schema_probe_count or 0),
            },
        )
        if not force_refresh and cache_key in _discover_cache:
            cached = dict(_discover_cache[cache_key])
            cached["cache"] = {"hit": True, "key": cache_key}
            return ToolResult(success=True, data=cached)
        
        try:
            from data_engine.core.discovery import DatasetDiscovery
            discovery = DatasetDiscovery()
            candidates = discovery.discover(search_query, limit=limit)
            
            if not candidates:
                return ToolResult(
                    success=True,
                    data={
                        "candidates": [],
                        "message": "No datasets found. Try different search terms or use manual seed data."
                    }
                )
            
            results = []
            probe_count = max(0, int(schema_probe_count or 0))

            for i, c in enumerate(candidates):
                base_score = float(c.score)
                structural = None
                if normalized_expected and i < probe_count:
                    structural = self._score_structural_fit(
                        discovery=discovery,
                        dataset_id=c.dataset_id,
                        expected_fields=normalized_expected,
                    )
                structural_score = float(structural.get("structural_score", 0.0)) if structural else 0.0
                total_score = base_score + structural_score
                results.append({
                    "dataset_id": c.dataset_id,
                    "score": round(total_score, 2),
                    "score_base": round(base_score, 2),
                    "score_structural": round(structural_score, 2),
                    "downloads": c.downloads,
                    "size": c.size_category or "unknown",
                    "description": c.description[:300] if c.description else "",
                    "url": c.url,
                    "fit": structural or {},
                })
            
            # Re-sort by total score with structural fit included.
            results.sort(key=lambda x: x.get("score", 0.0), reverse=True)
            
            response = {
                "query": search_query,
                "expected_fields": normalized_expected,
                "total_found": len(results),
                "candidates": results,
                "next_step": "Use preview_dataset(dataset_id) to see columns and sample data",
                "cache": {"hit": False, "key": cache_key, "stored_at": int(time.time())},
            }
            _discover_cache[cache_key] = dict(response)
            return ToolResult(success=True, data=response)
            
        except ImportError:
            return ToolResult(
                success=False,
                error_message="DataEngine not available. Install: pip install datasets huggingface_hub"
            )
        except Exception as e:
            logger.exception(f"Dataset discovery failed: {e}")
            return ToolResult(success=False, error_message=f"Discovery failed: {str(e)}")

    def _score_structural_fit(
        self,
        discovery: Any,
        dataset_id: str,
        expected_fields: List[str],
    ) -> Dict[str, Any]:
        """
        Score dataset schema fit against expected fields.
        """
        global _schema_probe_cache
        cache_key = f"{dataset_id}::{','.join(sorted(expected_fields))}"
        if cache_key in _schema_probe_cache:
            return dict(_schema_probe_cache[cache_key])

        try:
            schema = discovery.get_schema(dataset_id) or {}
            available = [str(k).strip().lower() for k in schema.keys()]
            available_set = set(available)

            direct_matches = [f for f in expected_fields if f in available_set]
            fuzzy_matches: Dict[str, str] = {}
            for f in expected_fields:
                if f in available_set:
                    continue
                hit = next((col for col in available if f in col or col in f), None)
                if hit:
                    fuzzy_matches[f] = hit

            matched_total = len(direct_matches) + len(fuzzy_matches)
            coverage = matched_total / max(1, len(expected_fields))

            # Weighted: exact matches stronger than fuzzy.
            structural_score = (len(direct_matches) * 8.0) + (len(fuzzy_matches) * 3.0) + (coverage * 10.0)
            result = {
                "coverage": round(coverage, 3),
                "expected_count": len(expected_fields),
                "matched_count": matched_total,
                "direct_matches": direct_matches,
                "fuzzy_matches": fuzzy_matches,
                "schema_columns_sample": available[:20],
                "structural_score": round(structural_score, 2),
            }
            _schema_probe_cache[cache_key] = dict(result)
            return result
        except Exception as e:
            logger.debug(f"Schema fit scoring failed for {dataset_id}: {e}")
            return {
                "coverage": 0.0,
                "expected_count": len(expected_fields),
                "matched_count": 0,
                "direct_matches": [],
                "fuzzy_matches": {},
                "schema_columns_sample": [],
                "structural_score": 0.0,
                "error": str(e),
            }


class PreviewDatasetTool(BaseTool):
    """Quick preview of dataset structure using streaming (no full download)."""
    
    NAME = "preview_dataset"
    DESCRIPTION = """Preview a HuggingFace dataset's columns and sample data.

Uses streaming mode - only fetches a few rows, no full download needed!

Example:
  preview_dataset(dataset_id="FronkonGames/steam-games-dataset", sample_size=5)

Returns: columns (with types), sample_data (sample rows)
Also returns quality_summary (null/fill/uniqueness from sampled rows).
Next step: Use generate_seed_sql() to create INSERT statements.
"""
    
    def __init__(self):
        super().__init__(name=self.NAME, category=ToolCategory.RUNTIME)
    
    def get_tool_param(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.NAME,
                "description": self.DESCRIPTION,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "dataset_id": {
                            "type": "string",
                            "description": "HuggingFace dataset ID (e.g., 'FronkonGames/steam-games-dataset')"
                        },
                        "subset": {
                            "type": "string",
                            "description": "Dataset subset/config name (optional, some datasets have multiple)"
                        },
                        "split": {
                            "type": "string",
                            "description": "Dataset split to preview (default: 'train')"
                        },
                        "sample_size": {
                            "type": "integer",
                            "description": "Number of sample rows to return (default: 5)"
                        },
                        "force_refresh": {
                            "type": "boolean",
                            "description": "Bypass local preview cache and fetch fresh sample"
                        }
                    },
                    "required": ["dataset_id"]
                }
            }
        }
    
    def tool_definition(self):
        return self.get_tool_param()
    
    def execute(
        self,
        dataset_id: str,
        subset: Optional[str] = None,
        split: str = "train",
        sample_size: int = 5,
        force_refresh: bool = False,
    ) -> ToolResult:
        """Preview dataset structure using streaming (no full download needed)."""
        global _preview_cache
        cache_key = _stable_cache_key(
            "preview",
            {
                "dataset_id": dataset_id,
                "subset": subset or "",
                "split": split or "train",
                "sample_size": int(sample_size or 5),
            },
        )
        if not force_refresh and cache_key in _preview_cache:
            cached = dict(_preview_cache[cache_key])
            cached["cache"] = {"hit": True, "key": cache_key}
            return ToolResult(success=True, data=cached)

        try:
            from datasets import load_dataset
            
            logger.info(f"Streaming preview for {dataset_id}")
            
            # Use streaming mode - no full download
            load_args = {"path": dataset_id, "streaming": True}
            if subset:
                load_args["name"] = subset
            
            try:
                ds = load_dataset(**load_args)
                if hasattr(ds, '__getitem__'):
                    ds = list(ds[split].take(sample_size + 5))
                else:
                    ds = list(ds.take(sample_size + 5))
            except Exception as e:
                logger.warning(f"Streaming failed, trying slice: {e}")
                load_args = {"path": dataset_id, "split": f"{split}[:20]", "streaming": False}
                if subset:
                    load_args["name"] = subset
                ds = load_dataset(**load_args)
            
            # Get columns info
            if hasattr(ds, 'features'):
                columns = {col: str(dtype) for col, dtype in ds.features.items()}
            elif hasattr(ds, 'column_names'):
                columns = {col: "unknown" for col in ds.column_names}
            elif isinstance(ds, list) and ds:
                columns = {k: type(v).__name__ for k, v in ds[0].items()}
            else:
                columns = {}
            
            # Get sample data
            def truncate_row(row):
                result = {}
                for k, v in row.items():
                    if isinstance(v, str) and len(v) > 150:
                        result[k] = v[:150] + "..."
                    elif isinstance(v, list) and len(v) > 3:
                        result[k] = v[:3] + ["..."]
                    else:
                        result[k] = v
                return result
            
            if isinstance(ds, list):
                sample_rows = [truncate_row(dict(row)) for row in ds[:sample_size]]
            elif hasattr(ds, 'select'):
                sample = ds.select(range(min(sample_size, len(ds)))).to_dict()
                keys = list(sample.keys())
                sample_rows = []
                for i in range(len(sample[keys[0]])):
                    row = {k: sample[k][i] for k in keys}
                    sample_rows.append(truncate_row(row))
            else:
                sample_rows = []
            
            response = {
                "dataset_id": dataset_id,
                "columns": columns,
                "column_count": len(columns),
                "sample_data": sample_rows,
                "quality_summary": self._compute_quality_summary(sample_rows),
                "next_step": "Use generate_seed_sql(dataset_id, table_name, field_mapping, output_file) to create SQL",
                "cache": {"hit": False, "key": cache_key, "stored_at": int(time.time())},
            }
            _preview_cache[cache_key] = dict(response)
            return ToolResult(success=True, data=response)
            
        except ImportError:
            return ToolResult(
                success=False,
                error_message="datasets library not available. Install: pip install datasets"
            )
        except Exception as e:
            logger.exception(f"Dataset preview failed: {e}")
            err = str(e)
            suggestions = []
            # Helpful remediation for common "dataset not found" failures.
            if (
                "doesn't exist on the hub" in err.lower()
                or "not found" in err.lower()
                or "cannot be accessed" in err.lower()
            ):
                query = dataset_id.split("/")[-1].replace("-", " ").replace("_", " ").strip() or dataset_id
                try:
                    discovery = DiscoverDatasetsTool().execute(query=query, limit=5)
                    if discovery.success and isinstance(discovery.data, dict):
                        for item in (discovery.data.get("datasets") or [])[:5]:
                            dsid = item.get("dataset_id")
                            if dsid:
                                suggestions.append(dsid)
                except Exception:
                    pass

            msg = f"Preview failed: {err}"
            if suggestions:
                msg += f". Suggested dataset_id values: {', '.join(suggestions)}"
            else:
                msg += ". Try discover_datasets(query=...) first, then preview_dataset() with an existing dataset_id."
            return ToolResult(success=False, error_message=msg)

    def _compute_quality_summary(self, sample_rows: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Compute lightweight quality summary from sampled rows.
        """
        if not sample_rows:
            return {
                "sample_size": 0,
                "column_count": 0,
                "completeness_score": 0.0,
                "null_rate_by_column": {},
                "fill_rate_by_column": {},
                "uniqueness_ratio_by_column": {},
                "notes": ["No sample rows available to assess quality."],
            }

        keys = set()
        for row in sample_rows:
            keys.update(row.keys())
        ordered_keys = sorted(keys)

        null_rate: Dict[str, float] = {}
        fill_rate: Dict[str, float] = {}
        unique_ratio: Dict[str, float] = {}
        notes: List[str] = []
        n = len(sample_rows)

        for col in ordered_keys:
            values = [row.get(col) for row in sample_rows]
            null_count = sum(1 for v in values if v is None or v == "" or v == [])
            fill_count = n - null_count
            null_rate[col] = round(null_count / max(1, n), 3)
            fill_rate[col] = round(fill_count / max(1, n), 3)

            canonical = [self._canonical_value(v) for v in values if v is not None]
            if canonical:
                unique_ratio[col] = round(len(set(canonical)) / max(1, len(canonical)), 3)
            else:
                unique_ratio[col] = 0.0

        completeness = round(sum(fill_rate.values()) / max(1, len(fill_rate)), 3)

        high_missing = [c for c, r in null_rate.items() if r >= 0.5]
        high_unique = [c for c, r in unique_ratio.items() if r >= 0.9 and fill_rate.get(c, 0) >= 0.8]
        if high_missing:
            notes.append(f"High missing-rate columns (>=50%): {', '.join(high_missing[:8])}")
        if high_unique:
            notes.append(f"High-cardinality columns in sample: {', '.join(high_unique[:8])}")
        if not notes:
            notes.append("Sample quality appears usable; validate with larger sample before final seeding.")

        return {
            "sample_size": n,
            "column_count": len(ordered_keys),
            "completeness_score": completeness,
            "null_rate_by_column": null_rate,
            "fill_rate_by_column": fill_rate,
            "uniqueness_ratio_by_column": unique_ratio,
            "notes": notes,
        }

    def _canonical_value(self, value: Any) -> str:
        try:
            if isinstance(value, (dict, list)):
                return json.dumps(value, sort_keys=True, ensure_ascii=False)
            return str(value)
        except Exception:
            return repr(value)


class DownloadDatasetTool(BaseTool):
    """Download full dataset to local cache (can run in background)."""
    
    NAME = "download_dataset"
    DESCRIPTION = """Download a HuggingFace dataset to local cache.

Can run in BACKGROUND - won't block other operations.
Use this when you need the full dataset, not just a sample.

Example:
  download_dataset(dataset_id="FronkonGames/steam-games-dataset", background=True)
  # Later check status:
  download_dataset(dataset_id="FronkonGames/steam-games-dataset", check_status=True)

Parameters:
- dataset_id: HuggingFace dataset ID
- subset: Dataset subset/config (optional)
- background: Run download in background (default: True)
- check_status: Just check download status, don't start new download

Returns: status, cache_dir, row_count (when complete)
"""
    
    def __init__(self):
        super().__init__(name=self.NAME, category=ToolCategory.RUNTIME)
    
    def get_tool_param(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.NAME,
                "description": self.DESCRIPTION,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "dataset_id": {
                            "type": "string",
                            "description": "HuggingFace dataset ID"
                        },
                        "subset": {
                            "type": "string",
                            "description": "Dataset subset/config name (optional)"
                        },
                        "split": {
                            "type": "string",
                            "description": "Dataset split to download (default: 'train')"
                        },
                        "background": {
                            "type": "boolean",
                            "description": "Run in background (default: True)"
                        },
                        "check_status": {
                            "type": "boolean",
                            "description": "Just check status, don't start download"
                        }
                    },
                    "required": ["dataset_id"]
                }
            }
        }
    
    def tool_definition(self):
        return self.get_tool_param()
    
    def execute(
        self,
        dataset_id: str,
        subset: Optional[str] = None,
        split: str = "train",
        background: bool = True,
        check_status: bool = False
    ) -> ToolResult:
        """Download dataset to local cache."""
        global _download_status
        
        cache_key = f"{dataset_id}:{subset or 'default'}:{split}"
        
        # Check status only
        if check_status:
            if cache_key in _download_status:
                return ToolResult(success=True, data=_download_status[cache_key])
            return ToolResult(
                success=True,
                data={"status": "not_started", "dataset_id": dataset_id}
            )
        
        # Check if already downloaded or in progress
        if cache_key in _download_status:
            status = _download_status[cache_key]
            if status["status"] in ["downloading", "complete"]:
                return ToolResult(success=True, data=status)
        
        # Initialize status
        _download_status[cache_key] = {
            "status": "downloading",
            "dataset_id": dataset_id,
            "subset": subset,
            "split": split,
            "progress": 0,
            "error": None
        }
        
        def do_download():
            try:
                from datasets import load_dataset
                
                logger.info(f"Starting download: {dataset_id}")
                
                load_args = {"path": dataset_id, "split": split}
                if subset:
                    load_args["name"] = subset
                
                # This triggers full download to cache
                ds = load_dataset(**load_args)
                
                # Get cache info
                cache_dir = None
                if hasattr(ds, 'cache_files') and ds.cache_files:
                    cache_dir = str(Path(ds.cache_files[0]['filename']).parent)
                
                _download_status[cache_key] = {
                    "status": "complete",
                    "dataset_id": dataset_id,
                    "subset": subset,
                    "split": split,
                    "row_count": len(ds),
                    "cache_dir": cache_dir,
                    "columns": list(ds.column_names) if hasattr(ds, 'column_names') else [],
                    "error": None
                }
                logger.info(f"Download complete: {dataset_id} ({len(ds)} rows)")
                
            except Exception as e:
                logger.exception(f"Download failed: {dataset_id}")
                _download_status[cache_key] = {
                    "status": "failed",
                    "dataset_id": dataset_id,
                    "error": str(e)
                }
        
        if background:
            # Run in background thread
            thread = threading.Thread(target=do_download, daemon=True)
            thread.start()
            return ToolResult(
                success=True,
                data={
                    "status": "downloading",
                    "dataset_id": dataset_id,
                    "message": "Download started in background. Use check_status=True to monitor."
                }
            )
        else:
            # Run synchronously
            do_download()
            return ToolResult(success=True, data=_download_status[cache_key])


class GenerateSeedSQLTool(BaseTool):
    """Generate SQL INSERT statements from HuggingFace dataset."""
    
    NAME = "generate_seed_sql"
    DESCRIPTION = """Generate SQL INSERT statements from a HuggingFace dataset.

Uses streaming mode - processes data without downloading entire dataset.

Example:
```python
generate_seed_sql(
    dataset_id="FronkonGames/steam-games-dataset",
    table_name="games",
    field_mapping={
        "Name": "title",
        "Header image": "image_url",
        "Price": "price_cents",
        "About the game": "description"
    },
    output_file="app/database/init/02_seed.sql",
    limit=100
)
```

Parameters:
- dataset_id: HuggingFace dataset ID
- table_name: Target SQL table name
- field_mapping: {dataset_column: table_column} mapping (REQUIRED)
- output_file: Output SQL file path
- transforms: Optional {column: "transform"} e.g. {"price": "multiply:100"}
- filters: Optional {column: {condition: value}} e.g. {"image": {"not_empty": true}}
- limit: Max rows to generate (default: 100)
"""
    
    def __init__(self, workspace=None):
        super().__init__(name=self.NAME, category=ToolCategory.RUNTIME)
        self.workspace = workspace
    
    def get_tool_param(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.NAME,
                "description": self.DESCRIPTION,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "dataset_id": {
                            "type": "string",
                            "description": "HuggingFace dataset ID"
                        },
                        "table_name": {
                            "type": "string",
                            "description": "Target database table name"
                        },
                        "field_mapping": {
                            "type": "object",
                            "description": "Mapping: {dataset_column: table_column}",
                            "additionalProperties": {"type": "string"}
                        },
                        "output_file": {
                            "type": "string",
                            "description": "Output SQL file path"
                        },
                        "transforms": {
                            "type": "object",
                            "description": "Optional transforms: {column: 'type:arg'}. Types: multiply, truncate, lowercase, default",
                            "additionalProperties": {"type": "string"}
                        },
                        "filters": {
                            "type": "object",
                            "description": "Optional filters: {column: {condition: value}}. Conditions: min, max, min_length, not_empty",
                            "additionalProperties": {"type": "object"}
                        },
                        "subset": {
                            "type": "string",
                            "description": "Dataset subset/config name (optional)"
                        },
                        "limit": {
                            "type": "integer",
                            "description": "Max records to generate (default: 100)"
                        },
                        "append": {
                            "type": "boolean",
                            "description": "Append to file instead of overwrite (default: false)"
                        },
                        "quality_gate": {
                            "type": "object",
                            "description": "Optional data quality thresholds before SQL generation",
                            "properties": {
                                "min_completeness": {"type": "number"},
                                "max_null_rate": {"type": "number"},
                                "required_source_fields": {
                                    "type": "array",
                                    "items": {"type": "string"}
                                }
                            }
                        },
                        "quality_gate_strict": {
                            "type": "boolean",
                            "description": "If true, fail generation when quality gate fails (default: true)"
                        },
                        "quality_sample_size": {
                            "type": "integer",
                            "description": "Sample size used for quality gate preview (default: 25)"
                        }
                    },
                    "required": ["dataset_id", "table_name", "output_file"]
                }
            }
        }
    
    def tool_definition(self):
        return self.get_tool_param()
    
    def execute(
        self,
        dataset_id: str,
        table_name: str,
        output_file: str,
        field_mapping: Optional[Dict[str, str]] = None,
        transforms: Optional[Dict[str, str]] = None,
        filters: Optional[Dict[str, Dict]] = None,
        subset: Optional[str] = None,
        limit: int = 100,
        append: bool = False,
        quality_gate: Optional[Dict[str, Any]] = None,
        quality_gate_strict: bool = True,
        quality_sample_size: int = 25,
    ) -> ToolResult:
        """Generate SQL INSERT statements using streaming."""
        inferred_mapping_used = False
        
        try:
            from datasets import load_dataset
            
            # Resolve output path
            if self.workspace and not Path(output_file).is_absolute():
                output_file = str(self.workspace.resolve(output_file))
            
            Path(output_file).parent.mkdir(parents=True, exist_ok=True)
            
            logger.info(f"Generating seed SQL from {dataset_id} for {table_name}")
            
            # Streaming mode
            fetch_count = limit * 2
            load_args = {"path": dataset_id, "streaming": True}
            if subset:
                load_args["name"] = subset
            
            try:
                ds = load_dataset(**load_args)
                if hasattr(ds, '__getitem__'):
                    ds = list(ds["train"].take(fetch_count))
                else:
                    ds = list(ds.take(fetch_count))
                logger.info(f"Streamed {len(ds)} records")
            except Exception as e:
                logger.warning(f"Streaming failed: {e}")
                load_args = {"path": dataset_id, "split": f"train[:{fetch_count}]"}
                if subset:
                    load_args["name"] = subset
                ds = load_dataset(**load_args)
            
            transforms = transforms or {}
            filters = filters or {}

            # Allow missing field_mapping by inferring a conservative default mapping.
            if not field_mapping:
                inferred = self._infer_field_mapping(self._extract_available_columns(ds))
                if not inferred:
                    return ToolResult(
                        success=False,
                        error_message=(
                            "E_FIELD_MAPPING_INFER_FAILED: field_mapping missing and could not infer from dataset."
                        ),
                        data={"recommended_action": "preview_dataset_and_provide_field_mapping"},
                    )
                field_mapping = inferred
                inferred_mapping_used = True

            gate_config = self._build_quality_gate_config(field_mapping, quality_gate)
            gate_check = self._run_quality_gate(
                dataset_id=dataset_id,
                subset=subset,
                sample_size=max(5, int(quality_sample_size or 25)),
                gate_config=gate_config,
            )
            if not gate_check.get("passed", True):
                msg = (
                    "E_DATA_QUALITY_GATE_FAILED: "
                    f"{'; '.join(gate_check.get('violations', [])[:3])}. "
                    "Try improving field_mapping, changing dataset/subset, or relaxing quality_gate thresholds."
                )
                if quality_gate_strict:
                    return ToolResult(
                        success=False,
                        error_message=msg,
                        data={
                            "quality_gate": gate_check,
                            "recommended_action": "refine_mapping_or_dataset_then_retry",
                        },
                    )
                logger.warning("Quality gate failed but continuing (non-strict): %s", msg)
            
            # Resolve source fields against actual dataset columns (case-insensitive).
            available_columns = self._extract_available_columns(ds)
            resolved_field_mapping = self._resolve_field_mapping(
                field_mapping=field_mapping,
                available_columns=available_columns,
            )

            unresolved_sources = [
                src for src, resolved in resolved_field_mapping.items()
                if not resolved.get("resolved_source")
            ]
            if unresolved_sources:
                return ToolResult(
                    success=False,
                    error_message=(
                        "E_FIELD_MAPPING_UNRESOLVED: could not resolve source columns "
                        f"{unresolved_sources}. available_columns_sample={available_columns[:20]}"
                    ),
                    data={
                        "resolved_field_mapping": resolved_field_mapping,
                        "available_columns_sample": available_columns[:20],
                        "recommended_action": "preview_dataset_and_fix_mapping_keys",
                    },
                )

            # Process records - use ordered list for stable column order
            table_columns = list(field_mapping.values())
            sql_statements = []
            processed = 0
            skipped = 0
            
            iterator = ds if isinstance(ds, list) else ds
            for row in iterator:
                record = dict(row) if not isinstance(row, dict) else row
                
                # Apply filters
                skip = False
                for col, conditions in filters.items():
                    val = record.get(col)
                    if val is None:
                        skip = True
                        break
                    for cond, threshold in conditions.items():
                        if cond == "min" and (not isinstance(val, (int, float)) or val < threshold):
                            skip = True
                        elif cond == "max" and (not isinstance(val, (int, float)) or val > threshold):
                            skip = True
                        elif cond == "min_length" and (not isinstance(val, str) or len(val) < threshold):
                            skip = True
                        elif cond == "not_empty" and not val:
                            skip = True
                        if skip:
                            break
                    if skip:
                        break
                
                if skip:
                    skipped += 1
                    continue
                
                # Map and transform values
                values = {}
                for src_col, tgt_col in field_mapping.items():
                    resolved_src = resolved_field_mapping.get(src_col, {}).get("resolved_source")
                    val = record.get(resolved_src) if resolved_src else None
                    
                    if tgt_col in transforms:
                        transform = transforms[tgt_col]
                        if transform.startswith("multiply:"):
                            factor = float(transform.split(":")[1])
                            val = int(float(val or 0) * factor) if val else 0
                        elif transform.startswith("truncate:"):
                            max_len = int(transform.split(":")[1])
                            val = str(val)[:max_len] if val else ""
                        elif transform == "lowercase":
                            val = str(val).lower() if val else ""
                        elif transform == "uppercase":
                            val = str(val).upper() if val else ""
                        elif transform.startswith("default:"):
                            default_val = transform.split(":", 1)[1]
                            val = val if val else default_val
                    
                    values[tgt_col] = val
                
                # Generate SQL value
                sql_values = []
                for col in table_columns:
                    val = values.get(col)
                    if val is None:
                        sql_values.append("NULL")
                    elif isinstance(val, (int, float)):
                        sql_values.append(str(val))
                    elif isinstance(val, bool):
                        sql_values.append("TRUE" if val else "FALSE")
                    elif isinstance(val, (list, dict)):
                        import json
                        escaped = json.dumps(val).replace("'", "''")
                        sql_values.append(f"'{escaped}'")
                    else:
                        escaped = str(val).replace("'", "''")
                        sql_values.append(f"'{escaped}'")
                
                sql_statements.append(f"({', '.join(sql_values)})")
                processed += 1
                
                if processed >= limit:
                    break
            
            if not sql_statements:
                return ToolResult(
                    success=False,
                    error_message=f"No records passed filters. Skipped {skipped} records. Try relaxing filters."
                )
            
            # Generate SQL
            columns_str = ", ".join(table_columns)
            sql = f"-- Generated from HuggingFace: {dataset_id}\n"
            sql += f"-- Records: {len(sql_statements)}\n\n"
            sql += f"INSERT INTO {table_name} ({columns_str}) VALUES\n"
            sql += ",\n".join(sql_statements)
            sql += ";\n"
            
            # Write to file
            mode = "a" if append else "w"
            with open(output_file, mode) as f:
                if append:
                    f.write("\n\n")
                f.write(sql)
            
            return ToolResult(
                success=True,
                data={
                    "output_file": output_file,
                    "table_name": table_name,
                    "records_generated": len(sql_statements),
                    "records_skipped": skipped,
                    "columns": table_columns,
                    "resolved_field_mapping": resolved_field_mapping,
                    "field_mapping_inferred": inferred_mapping_used,
                    "message": f"Generated {len(sql_statements)} INSERT statements",
                    "quality_gate": gate_check,
                }
            )
            
        except ImportError:
            return ToolResult(
                success=False,
                error_message="datasets library not available. Install: pip install datasets"
            )
        except Exception as e:
            logger.exception(f"SQL generation failed: {e}")
            return ToolResult(success=False, error_message=f"Generation failed: {str(e)}")

    def _build_quality_gate_config(
        self,
        field_mapping: Dict[str, str],
        quality_gate: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        cfg = dict(quality_gate or {})
        required = cfg.get("required_source_fields")
        if not required:
            required = list(field_mapping.keys())
        cfg["required_source_fields"] = [str(f) for f in required if str(f).strip()]
        cfg["min_completeness"] = float(cfg.get("min_completeness", 0.5))
        cfg["max_null_rate"] = float(cfg.get("max_null_rate", 0.9))
        cfg["min_completeness"] = min(1.0, max(0.0, cfg["min_completeness"]))
        cfg["max_null_rate"] = min(1.0, max(0.0, cfg["max_null_rate"]))
        return cfg

    def _run_quality_gate(
        self,
        dataset_id: str,
        subset: Optional[str],
        sample_size: int,
        gate_config: Dict[str, Any],
    ) -> Dict[str, Any]:
        preview = PreviewDatasetTool().execute(
            dataset_id=dataset_id,
            subset=subset,
            split="train",
            sample_size=sample_size,
        )
        if not preview.success:
            return {
                "passed": False,
                "violations": [f"Preview failed for quality gate: {preview.error_message}"],
                "config": gate_config,
            }

        data = preview.data or {}
        columns = data.get("columns", {}) or {}
        quality = data.get("quality_summary", {}) or {}
        violations: List[str] = []
        normalized_to_actual = self._build_case_insensitive_lookup(list(columns.keys()))

        completeness = float(quality.get("completeness_score", 0.0))
        if completeness < gate_config["min_completeness"]:
            violations.append(
                f"completeness_score {completeness:.3f} < min_completeness {gate_config['min_completeness']:.3f}"
            )

        null_rates = quality.get("null_rate_by_column", {}) or {}
        resolved_required_fields: Dict[str, str] = {}
        for source_col in gate_config.get("required_source_fields", []):
            actual_col = normalized_to_actual.get(self._normalize_column_key(source_col))
            if not actual_col:
                violations.append(f"required_source_field missing: {source_col}")
                continue
            resolved_required_fields[source_col] = actual_col
            rate = float(null_rates.get(actual_col, 0.0))
            if rate > gate_config["max_null_rate"]:
                violations.append(
                    f"null_rate[{actual_col}] {rate:.3f} > max_null_rate {gate_config['max_null_rate']:.3f}"
                )

        return {
            "passed": len(violations) == 0,
            "violations": violations,
            "config": gate_config,
            "resolved_required_source_fields": resolved_required_fields,
            "quality_summary": quality,
            "column_count": len(columns),
        }

    @staticmethod
    def _normalize_column_key(value: Any) -> str:
        return str(value).strip().lower()

    @staticmethod
    def _to_sql_identifier(value: Any) -> str:
        raw = str(value or "").strip().lower()
        safe = "".join(ch if ch.isalnum() else "_" for ch in raw)
        while "__" in safe:
            safe = safe.replace("__", "_")
        safe = safe.strip("_")
        if not safe:
            return "col"
        if safe[0].isdigit():
            safe = f"c_{safe}"
        return safe

    def _infer_field_mapping(self, available_columns: List[str], max_columns: int = 12) -> Dict[str, str]:
        """
        Infer a conservative source->target mapping from dataset columns.
        """
        if not available_columns:
            return {}
        mapping: Dict[str, str] = {}
        used_targets = set()
        for src in available_columns[:max_columns]:
            tgt = self._to_sql_identifier(src)
            base = tgt
            idx = 2
            while tgt in used_targets:
                tgt = f"{base}_{idx}"
                idx += 1
            mapping[str(src)] = tgt
            used_targets.add(tgt)
        return mapping

    def _build_case_insensitive_lookup(self, columns: List[str]) -> Dict[str, str]:
        lookup: Dict[str, str] = {}
        for col in columns:
            key = self._normalize_column_key(col)
            if key and key not in lookup:
                lookup[key] = str(col)
        return lookup

    def _extract_available_columns(self, dataset_obj: Any) -> List[str]:
        """
        Extract candidate source columns from streamed/sliced dataset object.
        """
        if isinstance(dataset_obj, list) and dataset_obj:
            first = dataset_obj[0]
            if isinstance(first, dict):
                return [str(k) for k in first.keys()]
            return [str(k) for k in dict(first).keys()]
        if hasattr(dataset_obj, "column_names"):
            return [str(k) for k in list(getattr(dataset_obj, "column_names", []) or [])]
        return []

    def _resolve_field_mapping(
        self,
        field_mapping: Dict[str, str],
        available_columns: List[str],
    ) -> Dict[str, Dict[str, Any]]:
        """
        Resolve source columns in field_mapping with case-insensitive matching.
        """
        lookup = self._build_case_insensitive_lookup(available_columns)
        resolved: Dict[str, Dict[str, Any]] = {}
        for src_col, tgt_col in field_mapping.items():
            key = self._normalize_column_key(src_col)
            actual = lookup.get(key)
            resolved[str(src_col)] = {
                "target_column": str(tgt_col),
                "resolved_source": actual,
                "matched_case_insensitive": bool(actual and actual != src_col),
            }
        return resolved


def create_data_engine_tools(workspace=None) -> List[BaseTool]:
    """Create all data engine tools."""
    return [
        DiscoverDatasetsTool(),
        PreviewDatasetTool(),
        DownloadDatasetTool(),
        GenerateSeedSQLTool(workspace=workspace),
    ]


__all__ = [
    "DiscoverDatasetsTool",
    "PreviewDatasetTool",
    "DownloadDatasetTool",
    "GenerateSeedSQLTool",
    "create_data_engine_tools",
]
