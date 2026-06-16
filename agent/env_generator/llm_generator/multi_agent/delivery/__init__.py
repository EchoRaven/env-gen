"""Delivery-gate support: contract extraction + (future) gate result types.

Extracted out of the orchestrator god-object so the delivery/contract-alignment
concern lives in one place. See contract_extract.py for the stack assumptions.
"""

from .contract_extract import (
    normalize_api_path,
    param_agnostic,
    detect_backend_stack,
    extract_sql_tables,
    extract_backend_sql_refs,
    extract_backend_routes,
    extract_frontend_calls,
    extract_api_endpoints,
    extract_spec_pages,
)

__all__ = [
    "normalize_api_path",
    "param_agnostic",
    "detect_backend_stack",
    "extract_sql_tables",
    "extract_backend_sql_refs",
    "extract_backend_routes",
    "extract_frontend_calls",
    "extract_api_endpoints",
    "extract_spec_pages",
]
