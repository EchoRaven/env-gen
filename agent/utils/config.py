"""
Configuration Management Module - Defines Agent configuration structures

Supports:
- AgentConfig: Main agent configuration
- LLMConfig: LLM model configuration
- ExecutionConfig: Execution settings
- LoggingConfig: Logging settings
- NetworkConfig: Network settings
"""

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Optional
import json
import yaml


class LogLevel(Enum):
    """Log level enumeration"""
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class LLMProvider(Enum):
    """LLM service provider"""
    OPENAI = "openai"
    OPENROUTER = "openrouter"  # OpenAI-compatible aggregator
    ANTHROPIC = "anthropic"
    GOOGLE = "google"  # Gemini models
    AZURE = "azure"
    METAGEN = "metagen"  # Meta's MetaGen platform (llama/GPT/Claude/Gemini via the metagen SDK)
    LOCAL = "local"
    CUSTOM = "custom"


class ExecutionMode(Enum):
    """Execution mode"""
    SYNC = "sync"           # Synchronous execution
    ASYNC = "async"         # Asynchronous execution
    PARALLEL = "parallel"   # Parallel execution


@dataclass
class LLMConfig:
    """LLM model configuration"""
    provider: LLMProvider = LLMProvider.OPENAI
    model_name: str = "gpt-4"
    api_key: Optional[str] = None
    api_base: Optional[str] = None
    temperature: float = 0.7
    max_tokens: int = 4096
    top_p: float = 1.0
    frequency_penalty: float = 0.0
    presence_penalty: float = 0.0
    timeout: int = 1800  # 30 minutes
    retry_attempts: int = 3
    retry_delay: float = 1.0  # seconds
    extra_params: dict = field(default_factory=dict)
    
    def to_dict(self) -> dict:
        return {
            "provider": self.provider.value,
            "model_name": self.model_name,
            "api_key": "***" if self.api_key else None,  # Hide API key
            "api_base": self.api_base,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "top_p": self.top_p,
            "frequency_penalty": self.frequency_penalty,
            "presence_penalty": self.presence_penalty,
            "timeout": self.timeout,
            "retry_attempts": self.retry_attempts,
            "retry_delay": self.retry_delay,
            "extra_params": self.extra_params,
        }


@dataclass
class ExecutionConfig:
    """Execution configuration"""
    mode: ExecutionMode = ExecutionMode.ASYNC
    max_concurrent_tasks: int = 5
    task_timeout: int = 300  # seconds
    retry_on_failure: bool = True
    max_retries: int = 3
    retry_backoff: float = 2.0  # Exponential backoff multiplier
    queue_size: int = 100
    priority_queue: bool = True
    
    def to_dict(self) -> dict:
        return {
            "mode": self.mode.value,
            "max_concurrent_tasks": self.max_concurrent_tasks,
            "task_timeout": self.task_timeout,
            "retry_on_failure": self.retry_on_failure,
            "max_retries": self.max_retries,
            "retry_backoff": self.retry_backoff,
            "queue_size": self.queue_size,
            "priority_queue": self.priority_queue,
        }


@dataclass
class LoggingConfig:
    """Logging configuration"""
    level: LogLevel = LogLevel.INFO
    log_to_file: bool = True
    log_file_path: Optional[str] = None
    log_format: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    max_file_size: int = 10 * 1024 * 1024  # 10MB
    backup_count: int = 5
    log_to_console: bool = True
    include_timestamp: bool = True
    include_agent_id: bool = True
    
    def to_dict(self) -> dict:
        return {
            "level": self.level.value,
            "log_to_file": self.log_to_file,
            "log_file_path": self.log_file_path,
            "log_format": self.log_format,
            "max_file_size": self.max_file_size,
            "backup_count": self.backup_count,
            "log_to_console": self.log_to_console,
            "include_timestamp": self.include_timestamp,
            "include_agent_id": self.include_agent_id,
        }


@dataclass
class NetworkConfig:
    """Network/communication configuration"""
    host: str = "localhost"
    port: int = 8000
    use_ssl: bool = False
    ssl_cert_path: Optional[str] = None
    ssl_key_path: Optional[str] = None
    connection_timeout: int = 30
    read_timeout: int = 60
    max_connections: int = 100
    heartbeat_interval: int = 30  # seconds
    
    def to_dict(self) -> dict:
        return {
            "host": self.host,
            "port": self.port,
            "use_ssl": self.use_ssl,
            "ssl_cert_path": self.ssl_cert_path,
            "ssl_key_path": self.ssl_key_path,
            "connection_timeout": self.connection_timeout,
            "read_timeout": self.read_timeout,
            "max_connections": self.max_connections,
            "heartbeat_interval": self.heartbeat_interval,
        }


@dataclass
class MemoryConfig:
    """Memory/context configuration"""
    max_context_length: int = 32768  # tokens (increased for complex projects)
    short_term_memory_size: int = 10  # Recent N conversation turns
    long_term_memory_enabled: bool = False
    long_term_memory_backend: str = "local"  # local, redis, vector_db
    vector_db_config: dict = field(default_factory=dict)
    context_compression: bool = True
    
    def to_dict(self) -> dict:
        return {
            "max_context_length": self.max_context_length,
            "short_term_memory_size": self.short_term_memory_size,
            "long_term_memory_enabled": self.long_term_memory_enabled,
            "long_term_memory_backend": self.long_term_memory_backend,
            "vector_db_config": self.vector_db_config,
            "context_compression": self.context_compression,
        }


@dataclass
class AgentConfig:
    """Main Agent configuration class"""
    # Basic info
    agent_id: str = ""
    agent_name: str = ""
    agent_type: str = "generic"
    description: str = ""
    version: str = "1.0.0"
    
    # Sub-configurations
    llm: LLMConfig = field(default_factory=LLMConfig)
    execution: ExecutionConfig = field(default_factory=ExecutionConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)
    network: NetworkConfig = field(default_factory=NetworkConfig)
    memory: MemoryConfig = field(default_factory=MemoryConfig)
    
    # Feature flags
    enabled: bool = True
    auto_start: bool = True
    allow_parallel_execution: bool = True
    
    # Extended configuration
    custom_config: dict = field(default_factory=dict)
    tags: list[str] = field(default_factory=list)
    
    def to_dict(self) -> dict:
        """Convert to dictionary"""
        return {
            "agent_id": self.agent_id,
            "agent_name": self.agent_name,
            "agent_type": self.agent_type,
            "description": self.description,
            "version": self.version,
            "llm": self.llm.to_dict(),
            "execution": self.execution.to_dict(),
            "logging": self.logging.to_dict(),
            "network": self.network.to_dict(),
            "memory": self.memory.to_dict(),
            "enabled": self.enabled,
            "auto_start": self.auto_start,
            "allow_parallel_execution": self.allow_parallel_execution,
            "custom_config": self.custom_config,
            "tags": self.tags,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "AgentConfig":
        """Create configuration from dictionary"""
        llm_data = data.get("llm", {})
        llm_config = LLMConfig(
            provider=LLMProvider(llm_data.get("provider", "openai")),
            model_name=llm_data.get("model_name", "gpt-4"),
            api_key=llm_data.get("api_key"),
            api_base=llm_data.get("api_base"),
            temperature=llm_data.get("temperature", 0.7),
            max_tokens=llm_data.get("max_tokens", 4096),
            top_p=llm_data.get("top_p", 1.0),
            timeout=llm_data.get("timeout", 1800),
            retry_attempts=llm_data.get("retry_attempts", 3),
        )
        
        exec_data = data.get("execution", {})
        exec_config = ExecutionConfig(
            mode=ExecutionMode(exec_data.get("mode", "async")),
            max_concurrent_tasks=exec_data.get("max_concurrent_tasks", 5),
            task_timeout=exec_data.get("task_timeout", 300),
            retry_on_failure=exec_data.get("retry_on_failure", True),
            max_retries=exec_data.get("max_retries", 3),
        )
        
        log_data = data.get("logging", {})
        log_config = LoggingConfig(
            level=LogLevel(log_data.get("level", "info")),
            log_to_file=log_data.get("log_to_file", True),
            log_file_path=log_data.get("log_file_path"),
            log_to_console=log_data.get("log_to_console", True),
        )
        
        net_data = data.get("network", {})
        net_config = NetworkConfig(
            host=net_data.get("host", "localhost"),
            port=net_data.get("port", 8000),
            use_ssl=net_data.get("use_ssl", False),
            heartbeat_interval=net_data.get("heartbeat_interval", 30),
        )
        
        mem_data = data.get("memory", {})
        mem_config = MemoryConfig(
            max_context_length=mem_data.get("max_context_length", 8192),
            short_term_memory_size=mem_data.get("short_term_memory_size", 10),
            long_term_memory_enabled=mem_data.get("long_term_memory_enabled", False),
        )
        
        return cls(
            agent_id=data.get("agent_id", ""),
            agent_name=data.get("agent_name", ""),
            agent_type=data.get("agent_type", "generic"),
            description=data.get("description", ""),
            version=data.get("version", "1.0.0"),
            llm=llm_config,
            execution=exec_config,
            logging=log_config,
            network=net_config,
            memory=mem_config,
            enabled=data.get("enabled", True),
            auto_start=data.get("auto_start", True),
            allow_parallel_execution=data.get("allow_parallel_execution", True),
            custom_config=data.get("custom_config", {}),
            tags=data.get("tags", []),
        )
    
    def save_to_file(self, file_path: str) -> None:
        """Save configuration to file"""
        path = Path(file_path)
        data = self.to_dict()
        
        if path.suffix in [".yaml", ".yml"]:
            with open(path, "w", encoding="utf-8") as f:
                yaml.dump(data, f, default_flow_style=False, allow_unicode=True)
        else:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
    
    @classmethod
    def load_from_file(cls, file_path: str) -> "AgentConfig":
        """Load configuration from file"""
        path = Path(file_path)
        
        with open(path, "r", encoding="utf-8") as f:
            if path.suffix in [".yaml", ".yml"]:
                data = yaml.safe_load(f)
            else:
                data = json.load(f)
        
        return cls.from_dict(data)
    
    def merge(self, other: "AgentConfig") -> "AgentConfig":
        """Merge another configuration (other values override self)"""
        self_dict = self.to_dict()
        other_dict = other.to_dict()
        
        def deep_merge(base: dict, override: dict) -> dict:
            result = base.copy()
            for key, value in override.items():
                if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                    result[key] = deep_merge(result[key], value)
                elif value is not None:
                    result[key] = value
            return result
        
        merged = deep_merge(self_dict, other_dict)
        return AgentConfig.from_dict(merged)
