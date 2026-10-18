"""
Agents - Multi-Agent system for environment generation

Re-exports from multi_agent package.
All agents are now config-driven via ConfigurableAgent.
"""

# #1203nc: BOTH ROOTS, cascading -- the idiom tools/canonical_file_tools/shared.py already
# documents. Under the runtime root this package IS `agents`, so `..multi_agent` is above the
# top level and `import agents` cannot work; under the suite root the absolute form cannot
# work EITHER, because `llm_generator/__init__.py` imports `.agents` on line 26, before
# anything has put LLM_GENERATOR_DIR on sys.path. MEASURED by trying the absolute form alone:
# the whole `env_generator` package stopped importing. A module-level import here has no
# later moment to fall back from, so it needs both forms, not one.
try:
    from ..multi_agent import (
        Orchestrator,
        ConfigurableAgent,
        create_agent,
    )
except ImportError:  # runtime root: `multi_agent` is a sibling TOP-LEVEL package
    from multi_agent import (  # type: ignore[no-redef]
        Orchestrator,
        ConfigurableAgent,
        create_agent,
    )

__all__ = [
    "Orchestrator",
    "ConfigurableAgent",
    "create_agent",
]
