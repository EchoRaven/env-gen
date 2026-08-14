"""
Database Tools - Direct database query and inspection tools

Provides:
- DatabaseQueryTool: Execute SQL queries against PostgreSQL
- DatabaseSchemaTool: Inspect database schema
- DatabaseTestTool: Test database connectivity and data
"""

import os
import subprocess
import json
import re
from pathlib import Path
from typing import Dict, List, Any, Optional

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.tool import BaseTool, ToolResult, ToolCategory, create_tool_param
from workspace import Workspace


class DatabaseQueryTool(BaseTool):
    """Execute SQL queries against PostgreSQL database."""
    
    NAME = "db_query"
    
    DESCRIPTION = """Execute a SQL query against the PostgreSQL database.

IMPORTANT: This tool connects to the database running in Docker.
Use for debugging data issues, verifying schema, or testing queries.

Examples:
    db_query("SELECT * FROM users LIMIT 5")
    db_query("SELECT COUNT(*) FROM issues")
    db_query("SHOW TABLES")  # Lists all tables
    db_query("\\d users")     # Describe table structure

Safety:
- SELECT queries are safe
- INSERT/UPDATE/DELETE require confirmation
- DROP/TRUNCATE are blocked by default

Connection uses docker-compose service name 'db' by default.
"""
    
    DEFAULT_TIMEOUT = 30
    MAX_ROWS = 100
    
    def __init__(self, *, workspace: Workspace):
        super().__init__(name=self.NAME, category=ToolCategory.RUNTIME)
        if workspace is None:
            raise ValueError(f"{self.NAME}: workspace is required (no bypass construction)")
        self.workspace = workspace
    
    @property
    def tool_definition(self):
        return create_tool_param(
            name=self.NAME,
            description=self.DESCRIPTION,
            parameters={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "SQL query to execute"
                    },
                    "database": {
                        "type": "string",
                        "description": "Database name (default: from docker-compose)"
                    },
                    "allow_write": {
                        "type": "boolean",
                        "description": "Allow INSERT/UPDATE/DELETE (default: false)"
                    }
                },
                "required": ["query"]
            }
        )
    
    def execute(
        self,
        query: str,
        database: Optional[str] = None,
        allow_write: bool = False,
        _retried_after_start: bool = False,
    ) -> ToolResult:
        query = query.strip()
        
        if not query:
            return ToolResult.fail("Empty query")
        
        # Safety check for destructive operations
        query_upper = query.upper()
        
        # Block dangerous operations
        dangerous_keywords = ["DROP", "TRUNCATE", "ALTER", "CREATE DATABASE", "DROP DATABASE"]
        for keyword in dangerous_keywords:
            if keyword in query_upper:
                return ToolResult.fail(
                    f"Blocked: '{keyword}' operations are not allowed for safety. "
                    f"Use execute_bash with psql directly if you really need this."
                )
        
        # Warn about write operations
        write_keywords = ["INSERT", "UPDATE", "DELETE"]
        is_write = any(kw in query_upper for kw in write_keywords)
        
        if is_write and not allow_write:
            return ToolResult.fail(
                f"Write operation detected. Set allow_write=true to execute INSERT/UPDATE/DELETE."
            )
        
        # Find database config from docker-compose
        db_config = self._get_db_config()
        if not db_config:
            return ToolResult.fail(
                "Could not find database configuration. "
                "Ensure docker-compose.yml exists with a 'db' service."
            )
        
        database = database or db_config.get("database", "postgres")
        
        # Build command candidates:
        # 1) docker exec <container> psql
        # 2) docker compose exec -T <service> psql
        # 3) local psql
        run_t_flag = "-t" if "SELECT" in query_upper else ""
        psql_args = [
            "psql",
            "-U", db_config.get("user", "postgres"),
            "-d", database,
            "-c", query,
            "--no-align",
        ]
        if run_t_flag:
            psql_args.append(run_t_flag)

        candidate_cmds: List[List[str]] = []
        container_name = self._find_db_container()
        if container_name:
            candidate_cmds.append(["docker", "exec", container_name, *psql_args])

        compose_files = self._existing_compose_files()
        for svc in ("db", "database", "postgres"):
            candidate_cmds.append(["docker", "compose", "exec", "-T", svc, *psql_args])
            candidate_cmds.append(["docker-compose", "exec", "-T", svc, *psql_args])
            for compose_file in compose_files:
                candidate_cmds.append(["docker", "compose", "-f", str(compose_file), "exec", "-T", svc, *psql_args])
                candidate_cmds.append(["docker-compose", "-f", str(compose_file), "exec", "-T", svc, *psql_args])

        candidate_cmds.append([
            "psql",
            "-h", "localhost",
            "-p", str(db_config.get("port", 5432)),
            "-U", db_config.get("user", "postgres"),
            "-d", database,
            "-c", query,
            "--no-align",
            *([run_t_flag] if run_t_flag else []),
        ])

        env = {
            "PGPASSWORD": db_config.get("password", "postgres"),
            "PATH": "/usr/local/bin:/usr/bin:/bin",
        }

        last_error = ""
        saw_transport_failure = False
        transport_errors = (
            "No such service",
            "No such container",
            "is not running",
            "Cannot connect to the Docker daemon",
            "unknown shorthand flag",
            "no configuration file provided",
        )

        for cmd in candidate_cmds:
            try:
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=self.DEFAULT_TIMEOUT,
                    env=env,
                    cwd=str(self.workspace.base_root),
                    encoding='utf-8',
                    errors='replace',
                )
            except subprocess.TimeoutExpired:
                return ToolResult.fail(f"Query timed out after {self.DEFAULT_TIMEOUT}s")
            except FileNotFoundError:
                # command binary missing on host, try next strategy
                continue
            except Exception as e:
                last_error = str(e)
                continue

            output = result.stdout.strip()
            error = result.stderr.strip()

            if result.returncode != 0:
                if any(msg in error for msg in transport_errors):
                    saw_transport_failure = True
                    last_error = error or "transport failed"
                    continue

                error_info = self._parse_db_error(error)
                return ToolResult.fail(
                    f"Query failed: {error_info['message']}",
                    data={"error_type": error_info["type"], "suggestion": error_info["suggestion"]}
                )

            if not output:
                return ToolResult.ok(data={
                    "query": query,
                    "result": "(empty result set)",
                    "rows": 0
                })

            lines = output.split("\n")
            row_count = len(lines)
            if row_count > self.MAX_ROWS:
                lines = lines[:self.MAX_ROWS]
                output = "\n".join(lines) + f"\n... ({row_count - self.MAX_ROWS} more rows)"

            return ToolResult.ok(data={
                "query": query,
                "result": output,
                "rows": row_count,
                "truncated": row_count > self.MAX_ROWS
            })

        # Common real-world failure mode: DB service not started yet.
        # Try a one-time auto-start and re-run query transports.
        if saw_transport_failure and not _retried_after_start:
            if self._try_start_db_service():
                return self.execute(
                    query=query,
                    database=database,
                    allow_write=allow_write,
                    _retried_after_start=True,
                )

        return ToolResult.fail(
            "Unable to run SQL query: no working database transport (docker exec/compose/local psql).",
            data={
                "error_type": "db_transport_unavailable",
                "suggestion": "Ensure DB container is running (docker ps / docker compose ps) or install local psql.",
                "last_error": last_error,
            },
        )

    def _try_start_db_service(self) -> bool:
        """Best-effort start of DB compose service before giving up."""
        compose_files = self._existing_compose_files()
        if not compose_files:
            return False

        # R2 round-11 Fix A env (classic builder pin) for fallback compose-up
        # builds — same rationale as docker_tools._run_compose.
        _classic_env = {**os.environ, "DOCKER_BUILDKIT": "0", "COMPOSE_DOCKER_CLI_BUILD": "0"}
        for compose_file in compose_files:
            for svc in ("db", "database", "postgres"):
                for cmd in (
                    ["docker", "compose", "-f", str(compose_file), "up", "-d", svc],
                    ["docker-compose", "-f", str(compose_file), "up", "-d", svc],
                ):
                    try:
                        result = subprocess.run(
                            cmd,
                            capture_output=True,
                            text=True,
                            timeout=60,
                            cwd=str(self.workspace.base_root),
                            encoding='utf-8',
                            errors='replace',
                            env=_classic_env,
                        )
                    except FileNotFoundError:
                        continue
                    except Exception:
                        continue

                    if result.returncode == 0:
                        return True

                    err = (result.stderr or "").lower()
                    # Try next service if this one doesn't exist in compose.
                    if "no such service" in err:
                        continue

        return False
    
    def _get_db_config(self) -> Optional[Dict[str, Any]]:
        """Extract database config from docker-compose.yml"""
        compose_paths = self._existing_compose_files()
        
        for compose_path in compose_paths:
            if compose_path.exists():
                try:
                    import yaml
                    with open(compose_path) as f:
                        compose = yaml.safe_load(f)
                    
                    services = compose.get("services", {})
                    db_service = services.get("db") or services.get("database") or services.get("postgres")
                    
                    if db_service:
                        env = db_service.get("environment", {})
                        if isinstance(env, list):
                            env = dict(e.split("=", 1) for e in env if "=" in e)
                        
                        return {
                            "user": env.get("POSTGRES_USER", "postgres"),
                            "password": env.get("POSTGRES_PASSWORD", "postgres"),
                            "database": env.get("POSTGRES_DB", "postgres"),
                            "port": 5432,
                        }
                except Exception:
                    continue
        
        return None

    def _existing_compose_files(self) -> List[Path]:
        """Return existing compose files in priority order."""
        compose_paths = [
            self.workspace.resolve("docker/docker-compose.yml"),
            self.workspace.resolve("docker/docker-compose.dev.yml"),
            self.workspace.resolve("docker-compose.yml"),
        ]
        return [p for p in compose_paths if p.exists()]
    
    def _find_db_container(self) -> Optional[str]:
        """Find the running database container name."""
        try:
            result = subprocess.run(
                ["docker", "ps", "--format", "{{.Names}}"],
                capture_output=True,
                text=True,
                timeout=10,
                encoding='utf-8',
                errors='replace',
            )
            
            if result.returncode == 0:
                containers = result.stdout.strip().split("\n")
                for name in containers:
                    if any(kw in name.lower() for kw in ["db", "postgres", "database"]):
                        return name
        except Exception:
            pass
        
        return None
    
    def _parse_db_error(self, error: str) -> Dict[str, str]:
        """Parse database error and provide helpful suggestion."""
        error_lower = error.lower()
        
        patterns = {
            "relation.*does not exist": {
                "type": "missing_table",
                "message": "Table does not exist",
                "suggestion": "Check table name spelling. Run db_schema() to see available tables."
            },
            "column.*does not exist": {
                "type": "missing_column",
                "message": "Column does not exist",
                "suggestion": "Check column name. Run db_query('\\d tablename') to see columns."
            },
            "permission denied": {
                "type": "permission",
                "message": "Permission denied",
                "suggestion": "Check database user permissions."
            },
            "connection refused": {
                "type": "connection",
                "message": "Cannot connect to database",
                "suggestion": "Ensure database container is running: docker_status()"
            },
            "syntax error": {
                "type": "syntax",
                "message": "SQL syntax error",
                "suggestion": "Check query syntax. Common issues: missing quotes, commas, or keywords."
            },
        }
        
        for pattern, info in patterns.items():
            if re.search(pattern, error_lower):
                return info
        
        return {
            "type": "unknown",
            "message": error[:200],
            "suggestion": "Check the error message for details."
        }


class DatabaseSchemaTool(BaseTool):
    """Inspect database schema - tables, columns, relationships."""
    
    NAME = "db_schema"
    
    DESCRIPTION = """Inspect database schema to understand table structure.

Returns:
- List of all tables
- Column definitions for each table
- Foreign key relationships
- Indexes

Examples:
    db_schema()                    # List all tables
    db_schema(table="users")       # Show users table structure
    db_schema(table="issues", include_data=True)  # Include sample data
"""
    
    def __init__(self, *, workspace: Workspace):
        super().__init__(name=self.NAME, category=ToolCategory.RUNTIME)
        if workspace is None:
            raise ValueError(f"{self.NAME}: workspace is required (no bypass construction)")
        self.workspace = workspace
        self._query_tool = DatabaseQueryTool(workspace=self.workspace)
    
    @property
    def tool_definition(self):
        return create_tool_param(
            name=self.NAME,
            description=self.DESCRIPTION,
            parameters={
                "type": "object",
                "properties": {
                    "table": {
                        "type": "string",
                        "description": "Specific table to inspect (optional)"
                    },
                    "include_data": {
                        "type": "boolean",
                        "description": "Include sample data rows (default: false)"
                    }
                },
                "required": []
            }
        )
    
    def execute(self, table: Optional[str] = None, include_data: bool = False) -> ToolResult:
        if table:
            return self._inspect_table(table, include_data)
        else:
            return self._list_tables()
    
    def _list_tables(self) -> ToolResult:
        """List all tables in the database."""
        query = """
            SELECT table_name, 
                   pg_size_pretty(pg_total_relation_size(quote_ident(table_name))) as size
            FROM information_schema.tables 
            WHERE table_schema = 'public' 
            ORDER BY table_name;
        """
        
        result = self._query_tool.execute(query)
        
        if not result.success:
            return result
        
        return ToolResult.ok(data={
            "tables": result.data.get("result", ""),
            "query": "List all public tables"
        })
    
    def _inspect_table(self, table: str, include_data: bool) -> ToolResult:
        """Inspect a specific table."""
        results = {}
        
        # Get column info
        columns_query = f"""
            SELECT column_name, data_type, is_nullable, column_default
            FROM information_schema.columns
            WHERE table_name = '{table}'
            ORDER BY ordinal_position;
        """
        
        columns_result = self._query_tool.execute(columns_query)
        if columns_result.success:
            results["columns"] = columns_result.data.get("result", "")
        
        # Get foreign keys
        fk_query = f"""
            SELECT
                kcu.column_name,
                ccu.table_name AS foreign_table,
                ccu.column_name AS foreign_column
            FROM information_schema.table_constraints AS tc
            JOIN information_schema.key_column_usage AS kcu
                ON tc.constraint_name = kcu.constraint_name
            JOIN information_schema.constraint_column_usage AS ccu
                ON ccu.constraint_name = tc.constraint_name
            WHERE tc.constraint_type = 'FOREIGN KEY'
                AND tc.table_name = '{table}';
        """
        
        fk_result = self._query_tool.execute(fk_query)
        if fk_result.success:
            results["foreign_keys"] = fk_result.data.get("result", "")
        
        # Get indexes
        idx_query = f"""
            SELECT indexname, indexdef
            FROM pg_indexes
            WHERE tablename = '{table}';
        """
        
        idx_result = self._query_tool.execute(idx_query)
        if idx_result.success:
            results["indexes"] = idx_result.data.get("result", "")
        
        # Get sample data if requested
        if include_data:
            data_query = f"SELECT * FROM {table} LIMIT 5;"
            data_result = self._query_tool.execute(data_query)
            if data_result.success:
                results["sample_data"] = data_result.data.get("result", "")
        
        # Get row count
        count_query = f"SELECT COUNT(*) FROM {table};"
        count_result = self._query_tool.execute(count_query)
        if count_result.success:
            results["row_count"] = count_result.data.get("result", "").strip()
        
        return ToolResult.ok(data={
            "table": table,
            **results
        })


class DatabaseTestTool(BaseTool):
    """Test database connectivity and verify data integrity."""
    
    NAME = "db_test"
    
    DESCRIPTION = """Test database connectivity and run data verification.

Use this to:
- Check if database is accessible
- Verify required tables exist
- Check data integrity (foreign keys, required fields)
- Validate seed data was loaded

Examples:
    db_test()                           # Basic connectivity test
    db_test(check_tables=["users", "issues"])  # Verify tables exist
    db_test(check_seed=True)            # Verify seed data loaded
"""
    
    def __init__(self, *, workspace: Workspace):
        super().__init__(name=self.NAME, category=ToolCategory.RUNTIME)
        if workspace is None:
            raise ValueError(f"{self.NAME}: workspace is required (no bypass construction)")
        self.workspace = workspace
        self._query_tool = DatabaseQueryTool(workspace=self.workspace)
    
    @property
    def tool_definition(self):
        return create_tool_param(
            name=self.NAME,
            description=self.DESCRIPTION,
            parameters={
                "type": "object",
                "properties": {
                    "check_tables": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of tables to verify exist"
                    },
                    "check_seed": {
                        "type": "boolean",
                        "description": "Check if seed data was loaded"
                    }
                },
                "required": []
            }
        )
    
    def execute(
        self,
        check_tables: Optional[List[str]] = None,
        check_seed: bool = False
    ) -> ToolResult:
        results = {
            "connectivity": False,
            "tables_checked": [],
            "issues": [],
            "summary": ""
        }
        
        # Test connectivity
        conn_result = self._query_tool.execute("SELECT 1 as test;")
        
        if not conn_result.success:
            results["issues"].append(f"Connection failed: {conn_result.error_message}")
            results["summary"] = "Database connection FAILED"
            return ToolResult.fail(
                "Database connectivity test failed",
                data=results
            )
        
        results["connectivity"] = True
        
        # Get list of existing tables
        tables_result = self._query_tool.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public';"
        )
        
        existing_tables = set()
        if tables_result.success:
            existing_tables = set(
                line.strip() for line in tables_result.data.get("result", "").split("\n")
                if line.strip()
            )
            results["existing_tables"] = list(existing_tables)
        
        # Check required tables
        if check_tables:
            for table in check_tables:
                if table in existing_tables:
                    results["tables_checked"].append({"table": table, "exists": True})
                else:
                    results["tables_checked"].append({"table": table, "exists": False})
                    results["issues"].append(f"Missing table: {table}")
        
        # Check seed data
        if check_seed:
            seed_checks = []
            
            # Check for users
            if "users" in existing_tables:
                user_count = self._query_tool.execute("SELECT COUNT(*) FROM users;")
                if user_count.success:
                    count = int(user_count.data.get("result", "0").strip() or 0)
                    seed_checks.append({"table": "users", "rows": count})
                    if count == 0:
                        results["issues"].append("No users found - seed data may not be loaded")
            
            results["seed_data"] = seed_checks
        
        # Summary
        if results["issues"]:
            results["summary"] = f"Database OK but {len(results['issues'])} issues found"
            return ToolResult.ok(data=results)
        else:
            results["summary"] = "Database OK - all checks passed"
            return ToolResult.ok(data=results)


def create_database_tools(*, workspace: Workspace) -> List[BaseTool]:
    """Create all database tools."""
    return [
        DatabaseQueryTool(workspace=workspace),
        DatabaseSchemaTool(workspace=workspace),
        DatabaseTestTool(workspace=workspace),
    ]


__all__ = [
    "DatabaseQueryTool",
    "DatabaseSchemaTool",
    "DatabaseTestTool",
    "create_database_tools",
]

