# AgentForge Utils - Agent Infrastructure

## Overview

This is the core infrastructure module for the AgentForge project, providing all components needed to build intelligent Multi-Agent systems.

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                          AgentForge Utils                                │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  ┌────────────────────── INTELLIGENCE LAYER ──────────────────────┐    │
│  │                                                                  │    │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────────┐   │    │
│  │  │   LLM    │  │  Prompt  │  │  Memory  │  │   Reasoning  │   │    │
│  │  │  Client  │  │ Templates│  │  System  │  │   (ReAct)    │   │    │
│  │  └────┬─────┘  └────┬─────┘  └────┬─────┘  └──────┬───────┘   │    │
│  │       │              │             │               │           │    │
│  │       └──────────────┼─────────────┼───────────────┘           │    │
│  │                      │             │                           │    │
│  │                 ┌────▼─────────────▼────┐                      │    │
│  │                 │       Planner         │                      │    │
│  │                 │  (Task Decomposition) │                      │    │
│  │                 └───────────┬───────────┘                      │    │
│  │                             │                                  │    │
│  └─────────────────────────────┼──────────────────────────────────┘    │
│                                │                                        │
│  ┌─────────────────────────────▼──────────────────────────────────┐    │
│  │                       BaseAgent                                 │    │
│  └─────────────────────────────┬──────────────────────────────────┘    │
│                                │                                        │
│  ┌────────────────────── CORE LAYER ──────────────────────────────┐    │
│  │                                                                  │    │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────────┐   │    │
│  │  │ Message  │  │  Config  │  │  State   │  │    Tool      │   │    │
│  │  │ Protocol │  │ Manager  │  │ Manager  │  │  Registry    │   │    │
│  │  └──────────┘  └──────────┘  └──────────┘  └──────────────┘   │    │
│  │                                                                  │    │
│  │  ┌────────────────────────────────────────────────────────┐    │    │
│  │  │              Communication (MessageBus)                 │    │    │
│  │  └────────────────────────────────────────────────────────┘    │    │
│  │                                                                  │    │
│  └──────────────────────────────────────────────────────────────────┘    │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

## Module Overview

### Core Layer

| Module | Description | Key Classes |
|--------|-------------|-------------|
| `message.py` | Message protocol | `TaskMessage`, `ResultMessage`, `ControlMessage` |
| `config.py` | Configuration | `AgentConfig`, `LLMConfig`, `ExecutionConfig` |
| `state.py` | State management | `StateManager`, `AgentState`, `TaskState` |
| `tool.py` | Tool interface | `BaseTool`, `ToolRegistry`, `@tool` |
| `base_agent.py` | Agent base class | `BaseAgent`, `AgentRole` |
| `communication.py` | Communication | `MessageBus`, `EventEmitter`, `MessageRouter` |

### Intelligence Layer

| Module | Description | Key Classes |
|--------|-------------|-------------|
| `llm.py` | LLM clients | `LLM`, `OpenAIClient`, `AnthropicClient` |
| `prompt.py` | Prompt templates | `PromptTemplate`, `PromptBuilder` |
| `memory.py` | Memory systems | `AgentMemory`, `ShortTermMemory`, `LongTermMemory` |
| `planner.py` | Task planning | `Planner`, `Plan`, `PlanStep` |
| `reasoning.py` | Reasoning engines | `ReActEngine`, `ChainOfThought`, `ReflectionEngine` |

## Quick Start

### Basic Agent with Planning

```python
from utils import (
    BaseAgent, AgentConfig, LLMConfig, LLMProvider,
    TaskMessage, ResultMessage, create_result_message,
    LLM, Planner, ReActEngine, AgentMemory
)

class SmartAgent(BaseAgent):
    def __init__(self, config: AgentConfig):
        super().__init__(config)
        
        # Initialize intelligence components
        self.llm = LLM(config.llm)
        self.planner = Planner(config.llm)
        self.reasoner = ReActEngine(config.llm, self.tools)
        self.memory = AgentMemory()
    
    async def process_task(self, task: TaskMessage) -> ResultMessage:
        # 1. Create a plan
        plan = await self.planner.create_plan(
            task=task.task_description,
            tools=self.tools.to_openai_functions(),
        )
        
        # 2. Execute with reasoning
        result = await self.reasoner.run(task.task_description)
        
        # 3. Store in memory
        self.memory.remember(
            f"Task: {task.task_name}, Result: {result.answer}",
            memory_type="long",
            importance=0.8
        )
        
        return create_result_message(
            source_id=self.agent_id,
            target_id=task.header.source_agent_id,
            task_id=task.task_id,
            success=result.success,
            result_data=result.answer,
        )

# Usage
config = AgentConfig(
    agent_name="SmartAgent",
    llm=LLMConfig(
        provider=LLMProvider.OPENAI,
        model_name="gpt-4",
        api_key="your-api-key",
    ),
)

agent = SmartAgent(config)
await agent.initialize()
await agent.start()
```

### Using ReAct Reasoning

```python
from utils import ReActEngine, LLMConfig, ToolRegistry, tool, ToolCategory

# Define tools
@tool(name="search", category=ToolCategory.SEARCH)
async def search(query: str) -> str:
    """Search for information"""
    return f"Search results for: {query}"

@tool(name="calculate", category=ToolCategory.DATA)
async def calculate(expression: str) -> str:
    """Calculate mathematical expression"""
    return str(eval(expression))

# Create registry and register tools
registry = ToolRegistry()
registry.register(search())
registry.register(calculate())

# Create reasoning engine
config = LLMConfig(provider=LLMProvider.OPENAI, model_name="gpt-4")
engine = ReActEngine(config, registry)

# Run reasoning
result = await engine.run("What is the population of France divided by 1000?")

print(f"Answer: {result.answer}")
print(f"Steps taken: {len(result.steps)}")
for step in result.steps:
    print(f"  {step.step_id}. {step.thought[:50]}...")
```

### Using the Planner

```python
from utils import Planner, LLMConfig

config = LLMConfig(provider=LLMProvider.ANTHROPIC, model_name="claude-3-opus")
planner = Planner(config)

# Create a plan
plan = await planner.create_plan(
    task="Build a REST API for a todo list application",
    tools=[
        {"name": "write", "description": "Write code to a file"},
        {"name": "run_tests", "description": "Run test suite"},
    ],
    constraints=[
        "Use Python and FastAPI",
        "Include unit tests",
        "Add proper error handling",
    ],
)

print(plan)
# Plan: Build a REST API for a todo list application
# Status: pending
# Steps:
#   ⏳ 1. Set up project structure
#   ⏳ 2. Create data models
#   ⏳ 3. Implement API endpoints
#   ⏳ 4. Write unit tests
#   ⏳ 5. Add error handling
```

### Memory System

```python
from utils import AgentMemory

memory = AgentMemory(
    short_term_size=20,
    long_term_size=1000,
)

# Remember things
memory.remember("User prefers Python", memory_type="long", importance=0.9)
memory.remember("Current task is API development", memory_type="short")

# Working memory for current task
memory.working.set_task("task_123")
memory.working.set("api_endpoint", "/api/todos")
memory.working.add_step(
    thought="Need to create the model first",
    action="write",
    observation="File created successfully",
)

# Recall memories
results = memory.recall("Python preferences", sources=["long"])

# Get context for prompts
context = memory.get_context_string()
```

## Reasoning Strategies

| Strategy | Description | Best For |
|----------|-------------|----------|
| `ReActEngine` | Reasoning + Acting loop | Complex tasks requiring tools |
| `ChainOfThought` | Step-by-step reasoning | Logical/math problems |
| `SelfAsk` | Asks sub-questions | Knowledge-based queries |
| `ReflectionEngine` | Self-critique and improve | Quality-sensitive tasks |

## Directory Structure

```
utils/
├── __init__.py          # Module entry
├── message.py           # Message protocol
├── config.py            # Configuration
├── state.py             # State management
├── tool.py              # Tool interface
├── base_agent.py        # Agent base class
├── communication.py     # Communication
├── llm.py               # LLM clients
├── prompt.py            # Prompt templates
├── memory.py            # Memory systems
├── planner.py           # Task planning
├── reasoning.py         # Reasoning engines
├── requirements.txt     # Dependencies
├── README.md            # This document
└── examples/            # Usage examples
```

## Requirements

```bash
pip install pyyaml openai anthropic httpx
```

Or selectively install what you need:
- `openai` - For OpenAI GPT models
- `anthropic` - For Claude models
- `httpx` - For local models (Ollama, vLLM)
