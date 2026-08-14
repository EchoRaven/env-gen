"""
Knowledge Tools - Agent-callable tools for knowledge management

These tools allow agents to:
- Search for relevant knowledge
- Store new knowledge (issues, patterns, best practices)
- Get contextually relevant knowledge

Implements BaseTool interface for integration with agent system.
"""

import logging
from typing import List, Optional, Dict, Any

from utils.tool import BaseTool, ToolResult, ToolCategory, create_tool_param
from workspace import Workspace
from multi_agent.skill_loader import get_skill, list_skill_summaries, upsert_skill

logger = logging.getLogger(__name__)

# Lazy import to avoid circular dependencies
_knowledge_store = None


def _get_store():
    """Lazy load knowledge store."""
    global _knowledge_store
    if _knowledge_store is None:
        from multi_agent.knowledge.store import KnowledgeStore
        _knowledge_store = KnowledgeStore(db_url=KnowledgeStore.default_sqlite_url())
        logger.info("Knowledge store initialized")
    return _knowledge_store


class QueryKnowledgeTool(BaseTool):
    """Search the knowledge base for relevant information."""
    
    NAME = "query_knowledge"
    DESCRIPTION = """Search the knowledge base for relevant information.

Use this tool when you:
- Encounter an error and want to check if there's a known solution
- Need to know the correct way to use a tool (like generate_seed_sql)
- Want to find patterns or best practices
- Are unsure about how to implement something

Examples:
- query_knowledge(query="generate_seed_sql field_mapping error")
- query_knowledge(query="frontend API integration patterns", category="react_pattern")
- query_knowledge(query="nginx proxy configuration issues")

Returns matched knowledge with solutions, code examples, and context."""
    
    def __init__(self):
        super().__init__(name=self.NAME, category=ToolCategory.KNOWLEDGE)
    
    @property
    def tool_definition(self) -> dict:
        from multi_agent.knowledge.types import KnowledgeCategory
        return create_tool_param(
            name=self.NAME,
            description=self.DESCRIPTION,
            parameters={
                "query": {
                    "type": "string",
                    "description": "Natural language query describing what you're looking for"
                },
                "category": {
                    "type": "string",
                    "enum": [c.value for c in KnowledgeCategory],
                    "description": "Optional: filter by category"
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of results (default: 3)"
                }
            },
            required=["query"]
        )
    
    async def execute(
        self,
        query: str,
        category: Optional[str] = None,
        limit: int = 3,
        **kwargs
    ) -> ToolResult:
        """Execute knowledge search."""
        try:
            store = _get_store()
            from multi_agent.knowledge.types import KnowledgeCategory, KnowledgeQuery
            
            kq = KnowledgeQuery(
                query=query,
                category=KnowledgeCategory(category) if category else None,
                limit=limit
            )
            
            results = store.search(kq)
            
            if not results:
                return ToolResult.ok({
                    "found": False,
                    "message": "No matching knowledge found. This might be a new issue.",
                    "suggestion": "If you solve this, use store_knowledge() to save the solution."
                })
            
            # Format results for agent
            formatted = []
            for r in results:
                formatted.append({
                    "id": r.knowledge.id,
                    "title": r.knowledge.title,
                    "relevance": round(r.score, 2),
                    "category": r.knowledge.category.value,
                    "content": r.knowledge.to_agent_prompt(),
                    "snippet": r.snippet
                })
            
            return ToolResult.ok({
                "found": True,
                "count": len(formatted),
                "results": formatted
            })
            
        except Exception as e:
            logger.error(f"Knowledge query failed: {e}")
            return ToolResult.fail(f"Search failed: {str(e)}")


class StoreKnowledgeTool(BaseTool):
    """Store new knowledge for future reference."""
    
    NAME = "store_knowledge"
    DESCRIPTION = """Store new knowledge for future reference.

Use this tool when you:
- Discover a bug/issue and its solution
- Learn a pattern that should be remembered
- Find a best practice worth documenting
- Want to record how to correctly use a tool

Good knowledge entries include:
- Clear problem description
- Root cause analysis (why it happened)
- Step-by-step solution
- Code examples (correct AND wrong if applicable)

Example:
store_knowledge(
    title="generate_seed_sql requires field_mapping",
    category="tool_usage",
    problem="Tool call failed with missing argument error",
    solution="Always provide field_mapping parameter mapping dataset columns to SQL columns",
    example_code='generate_seed_sql(dataset_id="...", table_name="games", field_mapping={"name": "title"})',
    tags=["data-engine", "huggingface"]
)

This builds a persistent knowledge base that improves over time!"""
    
    def __init__(self):
        super().__init__(name=self.NAME, category=ToolCategory.KNOWLEDGE)
    
    @property
    def tool_definition(self) -> dict:
        from multi_agent.knowledge.types import KnowledgeCategory
        return create_tool_param(
            name=self.NAME,
            description=self.DESCRIPTION,
            parameters={
                "title": {
                    "type": "string",
                    "description": "Short, descriptive title"
                },
                "category": {
                    "type": "string",
                    "enum": [c.value for c in KnowledgeCategory],
                    "description": "Category of knowledge"
                },
                "solution": {
                    "type": "string",
                    "description": "How to fix/handle the problem"
                },
                "problem": {
                    "type": "string",
                    "description": "What's the problem/issue (optional)"
                },
                "example_code": {
                    "type": "string",
                    "description": "Correct code example (optional)"
                },
                "wrong_code": {
                    "type": "string",
                    "description": "What NOT to do (optional)"
                },
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Tags for searchability"
                },
                "severity": {
                    "type": "string",
                    "enum": ["critical", "high", "medium", "low"],
                    "description": "How critical is this knowledge (default: medium)"
                }
            },
            required=["title", "category", "solution"]
        )
    
    async def execute(
        self,
        title: str,
        category: str,
        solution: str,
        problem: str = "",
        example_code: str = "",
        wrong_code: str = "",
        tags: Optional[List[str]] = None,
        severity: str = "medium",
        **kwargs
    ) -> ToolResult:
        """Store new knowledge."""
        try:
            store = _get_store()
            from multi_agent.knowledge.types import Knowledge, KnowledgeCategory, Severity
            
            knowledge = Knowledge(
                title=title,
                category=KnowledgeCategory(category),
                problem=problem,
                solution=solution,
                example_code=example_code,
                wrong_code=wrong_code,
                tags=tags or [],
                severity=Severity(severity),
                source="agent"
            )
            
            knowledge_id = store.add(knowledge)
            
            return ToolResult.ok({
                "success": True,
                "id": knowledge_id,
                "message": f"Stored knowledge: {title}",
                "tip": "This knowledge will be available for future searches."
            })
            
        except Exception as e:
            logger.error(f"Failed to store knowledge: {e}")
            return ToolResult.fail(f"Store failed: {str(e)}")


class GetRelevantKnowledgeTool(BaseTool):
    """Get knowledge relevant to your current task context."""
    
    NAME = "get_relevant_knowledge"
    DESCRIPTION = """Get knowledge relevant to your current task context.

Unlike query_knowledge which requires a specific question, this tool
proactively fetches knowledge based on what you're working on.

Use this when starting a new task to get relevant background knowledge.

Examples:
- get_relevant_knowledge(context="database seeding with HuggingFace datasets")
- get_relevant_knowledge(context="React API integration with axios")
- get_relevant_knowledge(context="Docker nginx proxy configuration")
"""
    
    def __init__(self):
        super().__init__(name=self.NAME, category=ToolCategory.KNOWLEDGE)
    
    @property
    def tool_definition(self) -> dict:
        return create_tool_param(
            name=self.NAME,
            description=self.DESCRIPTION,
            parameters={
                "context": {
                    "type": "string",
                    "description": "Description of what you're working on"
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of results (default: 3)"
                }
            },
            required=["context"]
        )
    
    async def execute(self, context: str, limit: int = 3, **kwargs) -> ToolResult:
        """Get context-relevant knowledge."""
        try:
            store = _get_store()
            knowledge_list = store.get_context_relevant(context, limit=limit)
            
            if not knowledge_list:
                return ToolResult.ok({
                    "found": False,
                    "message": "No contextually relevant knowledge found."
                })
            
            formatted = []
            for k in knowledge_list:
                formatted.append({
                    "id": k.id,
                    "title": k.title,
                    "category": k.category.value,
                    "content": k.to_agent_prompt()
                })
            
            return ToolResult.ok({
                "found": True,
                "count": len(formatted),
                "knowledge": formatted,
                "tip": "Review this knowledge before proceeding with your task."
            })
            
        except Exception as e:
            logger.error(f"Failed to get relevant knowledge: {e}")
            return ToolResult.fail(f"Failed: {str(e)}")


class SubmitLearningTool(BaseTool):
    """Submit a reusable learning candidate to the knowledge agent."""

    NAME = "submit_learning"
    DESCRIPTION = """Submit a reusable learning candidate to the knowledge agent.

Use this when you discover:
- a high-value issue and its fix
- a reusable review checklist or playbook
- an implementation pattern worth preserving
- a lesson that should be remembered beyond the current task

The knowledge agent will inspect the submission and decide whether to store it
as searchable knowledge or promote it into a reusable skill."""

    def __init__(self):
        super().__init__(name=self.NAME, category=ToolCategory.KNOWLEDGE)
        self.agent = None

    def set_agent(self, agent):
        self.agent = agent

    @property
    def tool_definition(self) -> dict:
        return create_tool_param(
            name=self.NAME,
            description=self.DESCRIPTION,
            parameters={
                "title": {
                    "type": "string",
                    "description": "Short title for the learning candidate",
                },
                "content": {
                    "type": "string",
                    "description": "Detailed lesson, pattern, or procedure content",
                },
                "summary": {
                    "type": "string",
                    "description": "Short summary for the knowledge agent",
                },
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional tags describing the lesson",
                },
                "storage_hint": {
                    "type": "string",
                    "enum": ["auto", "knowledge", "skill"],
                    "description": "Optional hint for the knowledge agent (default: auto)",
                },
                "importance": {
                    "type": "string",
                    "enum": ["low", "normal", "high"],
                    "description": "Priority for the submission (default: normal)",
                },
            },
            required=["title", "content"],
        )

    async def execute(
        self,
        title: str,
        content: str,
        summary: str = "",
        tags: Optional[List[str]] = None,
        storage_hint: str = "auto",
        importance: str = "normal",
        **kwargs,
    ) -> ToolResult:
        if not self.agent:
            return ToolResult.fail("Agent not available")

        bus = getattr(self.agent, "_external_bus", None) or getattr(self.agent, "_message_bus", None)
        if not bus or not hasattr(bus, "list_agents"):
            return ToolResult.fail("Message bus not available for learning submission")

        try:
            available_agents = set(bus.list_agents())
        except Exception:
            available_agents = set()
        if "knowledge" not in available_agents:
            return ToolResult.fail("Knowledge agent is not available")

        if not hasattr(self.agent, "_pending_learning_submissions"):
            self.agent._pending_learning_submissions = []

        payload = {
            "title": str(title).strip(),
            "summary": str(summary).strip(),
            "content": str(content).strip(),
            "tags": [str(tag).strip() for tag in (tags or []) if str(tag).strip()],
            "storage_hint": str(storage_hint or "auto").strip(),
            "importance": str(importance or "normal").strip(),
        }
        self.agent._pending_learning_submissions.append(payload)

        return ToolResult.ok({
            "queued": True,
            "target_agent": "knowledge",
            "title": payload["title"],
            "storage_hint": payload["storage_hint"],
        })


class ListSkillsTool(BaseTool):
    """List skill summaries visible in the current workspace."""

    NAME = "list_skills"
    DESCRIPTION = """List skill summaries visible in this workspace.

Use this when you want to:
- see which reusable skills are available
- inspect skill summaries before choosing one to open
- audit whether a workflow already exists as a skill

This returns compact metadata only. Use `get_skill(...)` for full instructions."""

    def __init__(self, workspace: Workspace):
        super().__init__(name=self.NAME, category=ToolCategory.KNOWLEDGE)
        self.workspace = workspace

    @property
    def tool_definition(self) -> dict:
        return create_tool_param(
            name=self.NAME,
            description=self.DESCRIPTION,
            parameters={},
            required=[],
        )

    async def execute(self, **kwargs) -> ToolResult:
        try:
            skills = list_skill_summaries(self.workspace.code_root)
            return ToolResult.ok({
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
            })
        except Exception as e:
            logger.error(f"Failed to list skills: {e}")
            return ToolResult.fail(f"List skills failed: {str(e)}")


class GetSkillTool(BaseTool):
    """Read one skill's summary and instructions."""

    NAME = "get_skill"
    DESCRIPTION = """Get one skill by name, including summary and full instructions.

Use this when you want to:
- inspect a skill before applying it
- review existing workflow instructions
- verify whether a skill already captures a reusable procedure"""

    def __init__(self, workspace: Workspace):
        super().__init__(name=self.NAME, category=ToolCategory.KNOWLEDGE)
        self.workspace = workspace

    @property
    def tool_definition(self) -> dict:
        return create_tool_param(
            name=self.NAME,
            description=self.DESCRIPTION,
            parameters={
                "name": {
                    "type": "string",
                    "description": "Skill name to retrieve",
                },
            },
            required=["name"],
        )

    async def execute(self, name: str, **kwargs) -> ToolResult:
        try:
            skill = get_skill(self.workspace.code_root, name)
            if not skill:
                return ToolResult.ok({
                    "found": False,
                    "message": f"Skill not found: {name}",
                })
            return ToolResult.ok({
                "found": True,
                "skill": {
                    "name": skill.name,
                    "summary": skill.description,
                    "path": skill.file_path,
                    "source": skill.source,
                    "instructions": skill.instructions,
                },
            })
        except Exception as e:
            logger.error(f"Failed to get skill: {e}")
            return ToolResult.fail(f"Get skill failed: {str(e)}")


class UpsertSkillTool(BaseTool):
    """Create or update a workspace-visible skill."""

    NAME = "upsert_skill"
    DESCRIPTION = """Create or update a skill visible to agents in this workspace.

Use this when you want to:
- add a new reusable skill summary
- capture a new operating procedure as SKILL.md
- refine or extend an existing skill

By default skills are stored in the global durable skill library so future
generations can reuse them. Use `scope="project-agent"` only for run-specific
skills.

The `summary` becomes the SKILL.md description/frontmatter.
The `instructions` become the markdown body.
With `append=true`, new instructions are appended to the existing body."""

    def __init__(self, workspace: Workspace):
        super().__init__(name=self.NAME, category=ToolCategory.KNOWLEDGE)
        self.workspace = workspace

    @property
    def tool_definition(self) -> dict:
        return create_tool_param(
            name=self.NAME,
            description=self.DESCRIPTION,
            parameters={
                "name": {
                    "type": "string",
                    "description": "Skill name. Example: release-readiness",
                },
                "summary": {
                    "type": "string",
                    "description": "Short summary/description for the skill",
                },
                "instructions": {
                    "type": "string",
                    "description": "Markdown instructions stored in SKILL.md body",
                },
                "scope": {
                    "type": "string",
                    "enum": ["global", "project-agent", "workspace"],
                    "description": "Where to store the skill (default: global, persisted across generations)",
                },
                "append": {
                    "type": "boolean",
                    "description": "Append new instructions to existing skill body instead of replacing it",
                },
            },
            required=["name", "summary"],
        )

    async def execute(
        self,
        name: str,
        summary: str,
        instructions: str = "",
        scope: str = "global",
        append: bool = False,
        **kwargs,
    ) -> ToolResult:
        try:
            skill = upsert_skill(
                self.workspace.code_root,
                name=name,
                description=summary,
                instructions=instructions,
                scope=scope,
                append=append,
            )
            return ToolResult.ok({
                "success": True,
                "skill": {
                    "name": skill.name,
                    "summary": skill.description,
                    "path": skill.file_path,
                    "source": skill.source,
                    "instructions": skill.instructions,
                },
                "message": f"Skill saved: {skill.name}",
            })
        except Exception as e:
            logger.error(f"Failed to upsert skill: {e}")
            return ToolResult.fail(f"Upsert skill failed: {str(e)}")


def create_knowledge_tools(workspace: Optional[Workspace] = None) -> List[BaseTool]:
    """Create all knowledge management tools."""
    # Hard requirement: knowledge must be available at startup.
    # Any configuration/DB init failure should fail fast.
    _get_store()
    tools: List[BaseTool] = [
        QueryKnowledgeTool(),
        StoreKnowledgeTool(),
        GetRelevantKnowledgeTool(),
        SubmitLearningTool(),
    ]
    if workspace is not None:
        tools.extend([
            ListSkillsTool(workspace=workspace),
            GetSkillTool(workspace=workspace),
            UpsertSkillTool(workspace=workspace),
        ])
    return tools
