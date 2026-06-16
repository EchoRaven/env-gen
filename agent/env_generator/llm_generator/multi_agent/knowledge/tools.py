"""
Knowledge tools compatibility wrapper.

Single source-of-truth for runtime tool schemas and behavior is
`tools/knowledge_tools.py` (BaseTool implementations used by multi-agent runtime).

This module keeps legacy functional APIs for callers importing from
`multi_agent.knowledge.tools`, while delegating to the canonical implementation.
"""

from typing import Dict, Any, List, Optional

from tools.knowledge_tools import (
    QueryKnowledgeTool,
    StoreKnowledgeTool,
    GetRelevantKnowledgeTool,
)
from .types import Knowledge, KnowledgeCategory, Severity, KnowledgeQuery


# Reuse the same global store instance as canonical tools module.
import tools.knowledge_tools as canonical_knowledge_tools


def get_store():
    """Return shared knowledge store instance."""
    return canonical_knowledge_tools._get_store()  # pylint: disable=protected-access


def set_store(store):
    """Inject shared knowledge store instance (for tests/custom setup)."""
    canonical_knowledge_tools._knowledge_store = store  # pylint: disable=protected-access


QUERY_KNOWLEDGE_TOOL = QueryKnowledgeTool().tool_definition
STORE_KNOWLEDGE_TOOL = StoreKnowledgeTool().tool_definition
GET_RELEVANT_KNOWLEDGE_TOOL = GetRelevantKnowledgeTool().tool_definition


def query_knowledge(
    query: str,
    category: str = None,
    tags: List[str] = None,
    limit: int = 3,
) -> Dict[str, Any]:
    """Legacy functional wrapper for querying knowledge."""
    store = get_store()
    kq = KnowledgeQuery(
        query=query,
        category=KnowledgeCategory(category) if category else None,
        tags=tags or [],
        limit=limit,
    )
    results = store.search(kq)
    if not results:
        return {
            "found": False,
            "message": "No matching knowledge found. You might be encountering something new.",
            "suggestion": "If you solve this, consider storing the knowledge for future reference.",
        }
    return {
        "found": True,
        "count": len(results),
        "results": [
            {
                "id": r.knowledge.id,
                "title": r.knowledge.title,
                "relevance": round(r.score, 2),
                "match_type": r.match_type,
                "content": r.knowledge.to_agent_prompt(),
                "snippet": r.snippet,
            }
            for r in results
        ],
    }


def store_knowledge(
    title: str,
    category: str,
    solution: str,
    summary: str = "",
    problem: str = "",
    symptoms: List[str] = None,
    root_cause: str = "",
    example_code: str = "",
    wrong_code: str = "",
    tags: List[str] = None,
    severity: str = "medium",
) -> Dict[str, Any]:
    """Legacy functional wrapper for storing knowledge."""
    store = get_store()
    knowledge = Knowledge(
        title=title,
        category=KnowledgeCategory(category),
        summary=summary,
        problem=problem,
        symptoms=symptoms or [],
        root_cause=root_cause,
        solution=solution,
        example_code=example_code,
        wrong_code=wrong_code,
        tags=tags or [],
        severity=Severity(severity),
        source="agent",
    )
    knowledge_id = store.add(knowledge)
    return {
        "success": True,
        "id": knowledge_id,
        "message": f"Stored knowledge: {title}",
        "tip": "This knowledge will be available for future searches.",
    }


def get_relevant_knowledge(context: str, limit: int = 3) -> Dict[str, Any]:
    """Legacy functional wrapper for context-relevant knowledge."""
    store = get_store()
    knowledge_list = store.get_context_relevant(context, limit=limit)
    if not knowledge_list:
        return {"found": False, "message": "No contextually relevant knowledge found."}
    return {
        "found": True,
        "count": len(knowledge_list),
        "knowledge": [
            {
                "id": k.id,
                "title": k.title,
                "category": k.category.value,
                "content": k.to_agent_prompt(),
            }
            for k in knowledge_list
        ],
        "tip": "Review this knowledge before proceeding with your task.",
    }


def mark_knowledge_useful(knowledge_id: str, useful: bool = True) -> Dict[str, Any]:
    store = get_store()
    store.mark_useful(knowledge_id, useful)
    return {"success": True, "message": f"Marked knowledge as {'useful' if useful else 'not useful'}"}


def list_knowledge(category: str = None, limit: int = 20) -> Dict[str, Any]:
    store = get_store()
    if category:
        entries = store.list_by_category(KnowledgeCategory(category), limit)
    else:
        entries = store.list_all(limit)
    return {
        "count": len(entries),
        "entries": [
            {
                "id": k.id,
                "title": k.title,
                "category": k.category.value,
                "severity": k.severity.value,
                "usage_count": k.usage_count,
            }
            for k in entries
        ],
    }


def get_knowledge_stats() -> Dict[str, Any]:
    return get_store().get_stats()


def list_skills(workspace_root: str) -> Dict[str, Any]:
    from multi_agent.skill_loader import list_skill_summaries

    skills = list_skill_summaries(workspace_root)
    return {
        "count": len(skills),
        "skills": [
            {
                "name": skill.name,
                "summary": skill.description,
                "path": skill.file_path,
                "source": skill.source,
            }
            for skill in skills
        ],
    }


def get_skill(workspace_root: str, name: str) -> Dict[str, Any]:
    from multi_agent.skill_loader import get_skill as load_skill

    skill = load_skill(workspace_root, name)
    if not skill:
        return {"found": False, "message": f"Skill not found: {name}"}
    return {
        "found": True,
        "skill": {
            "name": skill.name,
            "summary": skill.description,
            "path": skill.file_path,
            "source": skill.source,
            "instructions": skill.instructions,
        },
    }


def upsert_skill(
    workspace_root: str,
    *,
    name: str,
    summary: str,
    instructions: str = "",
    scope: str = "project-agent",
    append: bool = False,
) -> Dict[str, Any]:
    from multi_agent.skill_loader import upsert_skill as write_skill

    skill = write_skill(
        workspace_root,
        name=name,
        description=summary,
        instructions=instructions,
        scope=scope,
        append=append,
    )
    return {
        "success": True,
        "skill": {
            "name": skill.name,
            "summary": skill.description,
            "path": skill.file_path,
            "source": skill.source,
            "instructions": skill.instructions,
        },
    }


KNOWLEDGE_TOOLS = [
    QUERY_KNOWLEDGE_TOOL,
    STORE_KNOWLEDGE_TOOL,
    GET_RELEVANT_KNOWLEDGE_TOOL,
]


def get_tool_executor():
    return {
        "query_knowledge": query_knowledge,
        "store_knowledge": store_knowledge,
        "get_relevant_knowledge": get_relevant_knowledge,
        "list_skills": list_skills,
        "get_skill": get_skill,
        "upsert_skill": upsert_skill,
        "mark_knowledge_useful": mark_knowledge_useful,
        "list_knowledge": list_knowledge,
        "get_knowledge_stats": get_knowledge_stats,
    }
