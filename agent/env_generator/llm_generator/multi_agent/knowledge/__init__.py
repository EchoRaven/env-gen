"""
Knowledge Management System

A persistent knowledge base that helps agents learn and improve over time.

Features:
- Semantic search for finding relevant knowledge
- Issue/solution tracking with root cause analysis
- UI/UX patterns and best practices
- Tool usage guidelines
- Automatic deduplication and merging

Usage:
    from multi_agent.knowledge import KnowledgeStore, query_knowledge, store_knowledge
    
    # Search for knowledge
    results = query_knowledge("how to use generate_seed_sql")
    
    # Store new knowledge
    store_knowledge(
        title="New pattern discovered",
        category="code_pattern",
        solution="Here's how to do it correctly..."
    )
"""

from .types import (
    Knowledge,
    KnowledgeCategory,
    Severity,
    KnowledgeQuery,
    SearchResult
)

from .store import KnowledgeStore

from .tools import (
    KNOWLEDGE_TOOLS,
    QUERY_KNOWLEDGE_TOOL,
    STORE_KNOWLEDGE_TOOL,
    GET_RELEVANT_KNOWLEDGE_TOOL,
    query_knowledge,
    store_knowledge,
    get_relevant_knowledge,
    mark_knowledge_useful,
    list_knowledge,
    get_knowledge_stats,
    get_tool_executor,
    get_store,
    set_store
)

from .seed_data import seed_knowledge, get_seed_knowledge

__all__ = [
    # Types
    'Knowledge',
    'KnowledgeCategory', 
    'Severity',
    'KnowledgeQuery',
    'SearchResult',
    
    # Store
    'KnowledgeStore',
    
    # Tool definitions
    'KNOWLEDGE_TOOLS',
    'QUERY_KNOWLEDGE_TOOL',
    'STORE_KNOWLEDGE_TOOL',
    'GET_RELEVANT_KNOWLEDGE_TOOL',
    
    # Tool functions
    'query_knowledge',
    'store_knowledge',
    'get_relevant_knowledge',
    'mark_knowledge_useful',
    'list_knowledge',
    'get_knowledge_stats',
    'get_tool_executor',
    'get_store',
    'set_store',
    
    # Seeding
    'seed_knowledge',
    'get_seed_knowledge'
]
