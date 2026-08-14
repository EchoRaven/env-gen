"""
Knowledge Store - Persistent storage and intelligent retrieval.

Supports PostgreSQL or SQLite via explicit configuration.
Uses semantic search via embeddings when available.

Set KNOWLEDGE_DB_URL to either:
- postgresql://user:pass@host:port/dbname
- sqlite:///absolute/path/to/knowledge.db
"""

import os
import json
import logging
import re
from pathlib import Path
from typing import List, Optional, Dict, Any, Union
from datetime import datetime
from contextlib import contextmanager
from urllib.parse import urlparse

from .types import (
    Knowledge, KnowledgeCategory, Severity, 
    KnowledgeQuery, SearchResult
)

logger = logging.getLogger(__name__)


class KnowledgeStore:
    """
    Intelligent knowledge storage and retrieval.
    
    Features:
    - PostgreSQL for production (concurrent access)
    - SQLite support for local development
    - Semantic search via embeddings (when available)
    - Full-text and semantic retrieval
    - Usage tracking and relevance scoring
    """
    
    DEFAULT_SQLITE_PATH = Path.home() / ".env-gen" / "knowledge" / "knowledge.db"

    @classmethod
    def default_sqlite_url(cls) -> str:
        """Canonical local sqlite URL for knowledge storage."""
        return f"sqlite:///{cls.DEFAULT_SQLITE_PATH}"
    
    def __init__(self, db_url: Optional[str] = None):
        """
        Initialize knowledge store.
        
        Args:
            db_url: Database URL. Supports:
                - postgresql://user:pass@host:port/dbname
                - sqlite:///path/to/db.db
                - None: Uses KNOWLEDGE_DB_URL env var
        """
        self.db_url = db_url or os.getenv("KNOWLEDGE_DB_URL")
        if not self.db_url:
            raise ValueError(
                "KnowledgeStore requires explicit DB configuration via db_url or KNOWLEDGE_DB_URL."
            )

        if self.db_url.startswith("postgres"):
            self._backend = "postgresql"
            self._init_postgres()
        elif self.db_url.startswith("sqlite"):
            self._backend = "sqlite"
            self._init_sqlite()
        else:
            raise ValueError(
                f"Unsupported KnowledgeStore db_url: {self.db_url}. "
                "Use postgresql://... or sqlite:///..."
            )
        
        self._embedder = None
        self._vector_store = None
        self._init_embeddings()
        
        logger.info(f"KnowledgeStore initialized ({self._backend})")
    
    # =========================================================================
    # PostgreSQL Backend
    # =========================================================================
    
    def _init_postgres(self):
        """Initialize PostgreSQL connection and schema"""
        try:
            import psycopg2
            from psycopg2 import pool
            from psycopg2.extras import RealDictCursor
            
            # Create connection pool for concurrency
            parsed = urlparse(self.db_url)
            self._pool = pool.ThreadedConnectionPool(
                minconn=1,
                maxconn=10,
                host=parsed.hostname,
                port=parsed.port or 5432,
                database=parsed.path[1:],  # Remove leading /
                user=parsed.username,
                password=parsed.password
            )
            
            # Initialize schema
            with self._get_pg_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        CREATE TABLE IF NOT EXISTS knowledge (
                            id TEXT PRIMARY KEY,
                            title TEXT NOT NULL,
                            category TEXT NOT NULL,
                            summary TEXT,
                            content TEXT,
                            problem TEXT,
                            symptoms JSONB DEFAULT '[]'::jsonb,
                            root_cause TEXT,
                            solution TEXT,
                            example_code TEXT,
                            wrong_code TEXT,
                            tags JSONB DEFAULT '[]'::jsonb,
                            keywords JSONB DEFAULT '[]'::jsonb,
                            severity TEXT DEFAULT 'medium',
                            applies_to JSONB DEFAULT '[]'::jsonb,
                            prerequisites JSONB DEFAULT '[]'::jsonb,
                            related_ids JSONB DEFAULT '[]'::jsonb,
                            usage_count INTEGER DEFAULT 0,
                            usefulness_score REAL DEFAULT 0.0,
                            last_used TIMESTAMP,
                            source TEXT,
                            source_url TEXT,
                            created_at TIMESTAMP DEFAULT NOW(),
                            updated_at TIMESTAMP DEFAULT NOW(),
                            search_vector tsvector
                        )
                    """)
                    
                    # Full-text search index
                    cur.execute("""
                        CREATE INDEX IF NOT EXISTS idx_knowledge_search 
                        ON knowledge USING GIN(search_vector)
                    """)
                    
                    # Other indexes
                    cur.execute("CREATE INDEX IF NOT EXISTS idx_knowledge_category ON knowledge(category)")
                    cur.execute("CREATE INDEX IF NOT EXISTS idx_knowledge_severity ON knowledge(severity)")
                    cur.execute("CREATE INDEX IF NOT EXISTS idx_knowledge_usage ON knowledge(usage_count DESC)")
                    
                    # Search vector update trigger
                    cur.execute("""
                        CREATE OR REPLACE FUNCTION knowledge_search_update() RETURNS trigger AS $$
                        BEGIN
                            NEW.search_vector := 
                                setweight(to_tsvector('english', COALESCE(NEW.title, '')), 'A') ||
                                setweight(to_tsvector('english', COALESCE(NEW.problem, '')), 'B') ||
                                setweight(to_tsvector('english', COALESCE(NEW.solution, '')), 'B') ||
                                setweight(to_tsvector('english', COALESCE(NEW.summary, '')), 'C') ||
                                setweight(to_tsvector('english', COALESCE(NEW.content, '')), 'D');
                            RETURN NEW;
                        END
                        $$ LANGUAGE plpgsql
                    """)
                    
                    cur.execute("""
                        DROP TRIGGER IF EXISTS knowledge_search_trigger ON knowledge
                    """)
                    cur.execute("""
                        CREATE TRIGGER knowledge_search_trigger
                        BEFORE INSERT OR UPDATE ON knowledge
                        FOR EACH ROW EXECUTE FUNCTION knowledge_search_update()
                    """)
                    
                conn.commit()
            
            logger.info(f"PostgreSQL initialized: {parsed.hostname}:{parsed.port}")
            
        except ImportError as e:
            raise RuntimeError("psycopg2 is required for PostgreSQL KnowledgeStore backend.") from e
        except Exception as e:
            raise RuntimeError(f"PostgreSQL initialization failed: {e}") from e
    
    @contextmanager
    def _get_pg_conn(self):
        """Get PostgreSQL connection from pool"""
        conn = self._pool.getconn()
        try:
            yield conn
        finally:
            self._pool.putconn(conn)
    
    # =========================================================================
    # SQLite Backend
    # =========================================================================
    
    def _init_sqlite(self):
        """Initialize SQLite database"""
        import sqlite3
        
        if self.db_url and self.db_url.startswith("sqlite"):
            self._sqlite_path = Path(self.db_url.replace("sqlite:///", ""))
        else:
            self._sqlite_path = self.DEFAULT_SQLITE_PATH
        
        self._sqlite_path.parent.mkdir(parents=True, exist_ok=True)
        
        with self._get_sqlite_conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS knowledge (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    category TEXT NOT NULL,
                    summary TEXT,
                    content TEXT,
                    problem TEXT,
                    symptoms TEXT,
                    root_cause TEXT,
                    solution TEXT,
                    example_code TEXT,
                    wrong_code TEXT,
                    tags TEXT,
                    keywords TEXT,
                    severity TEXT DEFAULT 'medium',
                    applies_to TEXT,
                    prerequisites TEXT,
                    related_ids TEXT,
                    usage_count INTEGER DEFAULT 0,
                    usefulness_score REAL DEFAULT 0.0,
                    last_used TEXT,
                    source TEXT,
                    source_url TEXT,
                    created_at TEXT,
                    updated_at TEXT,
                    search_text TEXT
                )
            """)
            
            conn.execute("CREATE INDEX IF NOT EXISTS idx_category ON knowledge(category)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_severity ON knowledge(severity)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_usage ON knowledge(usage_count DESC)")
            
            # FTS5 for full-text search
            try:
                conn.execute("""
                    CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_fts USING fts5(
                        id UNINDEXED,
                        search_text,
                        tokenize='porter unicode61'
                    )
                """)
            except Exception:
                logger.debug("FTS5 not available")
        
        logger.info(f"SQLite initialized: {self._sqlite_path}")
    
    @contextmanager
    def _get_sqlite_conn(self):
        """Get SQLite connection"""
        import sqlite3
        conn = sqlite3.connect(str(self._sqlite_path))
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()
    
    # =========================================================================
    # Embeddings (Optional)
    # =========================================================================
    
    def _init_embeddings(self):
        """Initialize embedding model for semantic search"""
        try:
            from sentence_transformers import SentenceTransformer
            import chromadb
            from chromadb.config import Settings
            
            self._embedder = SentenceTransformer('all-MiniLM-L6-v2')
            
            if self._backend == "sqlite":
                chroma_path = self._sqlite_path.parent / "vectors"
            else:
                chroma_path = Path.home() / ".env-gen" / "knowledge" / "vectors"
            
            chroma_path.mkdir(parents=True, exist_ok=True)
            
            self._vector_store = chromadb.PersistentClient(
                path=str(chroma_path),
                settings=Settings(anonymized_telemetry=False)
            )
            self._collection = self._vector_store.get_or_create_collection(
                name="knowledge_embeddings",
                metadata={"hnsw:space": "cosine"}
            )
            
            logger.info("Semantic search enabled (sentence-transformers + ChromaDB)")
            
        except ImportError:
            logger.debug("Semantic search not available (missing dependencies)")
        except Exception as e:
            logger.warning(f"Failed to initialize embeddings: {e}")
    
    # =========================================================================
    # CRUD Operations
    # =========================================================================
    
    def add(self, knowledge: Knowledge) -> str:
        """Add or update a knowledge entry"""
        existing = self._find_similar(knowledge)
        if existing:
            return self._merge(existing, knowledge)
        
        if self._backend == "postgresql":
            return self._add_postgres(knowledge)
        else:
            return self._add_sqlite(knowledge)
    
    def _add_postgres(self, k: Knowledge) -> str:
        """Add to PostgreSQL"""
        with self._get_pg_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO knowledge (
                        id, title, category, summary, content, problem, symptoms,
                        root_cause, solution, example_code, wrong_code, tags, keywords,
                        severity, applies_to, prerequisites, related_ids, usage_count,
                        usefulness_score, last_used, source, source_url, created_at, updated_at
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                    )
                    ON CONFLICT (id) DO UPDATE SET
                        title = EXCLUDED.title,
                        solution = EXCLUDED.solution,
                        updated_at = NOW()
                """, (
                    k.id, k.title, k.category.value, k.summary, k.content, k.problem,
                    json.dumps(k.symptoms), k.root_cause, k.solution, k.example_code,
                    k.wrong_code, json.dumps(k.tags), json.dumps(k.keywords),
                    k.severity.value, json.dumps(k.applies_to), json.dumps(k.prerequisites),
                    json.dumps(k.related_ids), k.usage_count, k.usefulness_score,
                    k.last_used, k.source, k.source_url, k.created_at, k.updated_at
                ))
            conn.commit()
        
        self._add_embedding(k)
        logger.info(f"Added knowledge: {k.title}")
        return k.id
    
    def _add_sqlite(self, k: Knowledge) -> str:
        """Add to SQLite"""
        search_text = k.get_search_text()
        
        with self._get_sqlite_conn() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO knowledge (
                    id, title, category, summary, content, problem, symptoms,
                    root_cause, solution, example_code, wrong_code, tags, keywords,
                    severity, applies_to, prerequisites, related_ids, usage_count,
                    usefulness_score, last_used, source, source_url, created_at,
                    updated_at, search_text
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                k.id, k.title, k.category.value, k.summary, k.content, k.problem,
                json.dumps(k.symptoms), k.root_cause, k.solution, k.example_code,
                k.wrong_code, json.dumps(k.tags), json.dumps(k.keywords),
                k.severity.value, json.dumps(k.applies_to), json.dumps(k.prerequisites),
                json.dumps(k.related_ids), k.usage_count, k.usefulness_score,
                k.last_used.isoformat() if k.last_used else None,
                k.source, k.source_url, k.created_at.isoformat(),
                k.updated_at.isoformat(), search_text
            ))
            
            # Update FTS
            try:
                conn.execute("DELETE FROM knowledge_fts WHERE id = ?", (k.id,))
                conn.execute(
                    "INSERT INTO knowledge_fts (id, search_text) VALUES (?, ?)",
                    (k.id, search_text)
                )
            except Exception:
                pass
        
        self._add_embedding(k)
        logger.info(f"Added knowledge: {k.title}")
        return k.id
    
    def _add_embedding(self, k: Knowledge):
        """Add embedding for semantic search"""
        if self._embedder and self._collection:
            try:
                embedding = self._embedder.encode(k.get_search_text()).tolist()
                self._collection.upsert(
                    ids=[k.id],
                    embeddings=[embedding],
                    metadatas=[{
                        "category": k.category.value,
                        "severity": k.severity.value,
                        "tags": ",".join(k.tags)
                    }]
                )
            except Exception as e:
                logger.debug(f"Failed to add embedding: {e}")
    
    def _find_similar(self, k: Knowledge) -> Optional[Knowledge]:
        """Find similar existing entry"""
        if self._backend == "postgresql":
            with self._get_pg_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT * FROM knowledge WHERE title = %s AND category = %s",
                        (k.title, k.category.value)
                    )
                    row = cur.fetchone()
                    if row:
                        return self._row_to_knowledge_pg(row, cur.description)
        else:
            with self._get_sqlite_conn() as conn:
                row = conn.execute(
                    "SELECT * FROM knowledge WHERE title = ? AND category = ?",
                    (k.title, k.category.value)
                ).fetchone()
                if row:
                    return self._row_to_knowledge_sqlite(row)
        return None
    
    def _merge(self, existing: Knowledge, new: Knowledge) -> str:
        """Merge new knowledge into existing"""
        existing.symptoms = list(set(existing.symptoms + new.symptoms))
        existing.tags = list(set(existing.tags + new.tags))
        existing.keywords = list(set(existing.keywords + new.keywords))
        
        if len(new.solution or "") > len(existing.solution or ""):
            existing.solution = new.solution
        if len(new.example_code or "") > len(existing.example_code or ""):
            existing.example_code = new.example_code
        
        existing.usage_count += 1
        existing.updated_at = datetime.now()
        
        self.update(existing)
        return existing.id
    
    def update(self, k: Knowledge):
        """Update existing knowledge"""
        k.updated_at = datetime.now()
        
        if self._backend == "postgresql":
            with self._get_pg_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        UPDATE knowledge SET
                            title=%s, category=%s, summary=%s, content=%s, problem=%s,
                            symptoms=%s, root_cause=%s, solution=%s, example_code=%s,
                            wrong_code=%s, tags=%s, keywords=%s, severity=%s, applies_to=%s,
                            prerequisites=%s, related_ids=%s, usage_count=%s, usefulness_score=%s,
                            last_used=%s, source=%s, source_url=%s, updated_at=%s
                        WHERE id=%s
                    """, (
                        k.title, k.category.value, k.summary, k.content, k.problem,
                        json.dumps(k.symptoms), k.root_cause, k.solution, k.example_code,
                        k.wrong_code, json.dumps(k.tags), json.dumps(k.keywords),
                        k.severity.value, json.dumps(k.applies_to), json.dumps(k.prerequisites),
                        json.dumps(k.related_ids), k.usage_count, k.usefulness_score,
                        k.last_used, k.source, k.source_url, k.updated_at, k.id
                    ))
                conn.commit()
        else:
            search_text = k.get_search_text()
            with self._get_sqlite_conn() as conn:
                conn.execute("""
                    UPDATE knowledge SET
                        title=?, category=?, summary=?, content=?, problem=?,
                        symptoms=?, root_cause=?, solution=?, example_code=?,
                        wrong_code=?, tags=?, keywords=?, severity=?, applies_to=?,
                        prerequisites=?, related_ids=?, usage_count=?, usefulness_score=?,
                        last_used=?, source=?, source_url=?, updated_at=?, search_text=?
                    WHERE id=?
                """, (
                    k.title, k.category.value, k.summary, k.content, k.problem,
                    json.dumps(k.symptoms), k.root_cause, k.solution, k.example_code,
                    k.wrong_code, json.dumps(k.tags), json.dumps(k.keywords),
                    k.severity.value, json.dumps(k.applies_to), json.dumps(k.prerequisites),
                    json.dumps(k.related_ids), k.usage_count, k.usefulness_score,
                    k.last_used.isoformat() if k.last_used else None,
                    k.source, k.source_url, k.updated_at.isoformat(), search_text, k.id
                ))
                
                try:
                    conn.execute("DELETE FROM knowledge_fts WHERE id=?", (k.id,))
                    conn.execute(
                        "INSERT INTO knowledge_fts (id, search_text) VALUES (?, ?)",
                        (k.id, search_text)
                    )
                except Exception:
                    pass
        
        self._add_embedding(k)
    
    def get(self, id: str) -> Optional[Knowledge]:
        """Get knowledge by ID"""
        if self._backend == "postgresql":
            with self._get_pg_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT * FROM knowledge WHERE id = %s", (id,))
                    row = cur.fetchone()
                    if row:
                        return self._row_to_knowledge_pg(row, cur.description)
        else:
            with self._get_sqlite_conn() as conn:
                row = conn.execute("SELECT * FROM knowledge WHERE id = ?", (id,)).fetchone()
                if row:
                    return self._row_to_knowledge_sqlite(row)
        return None
    
    def delete(self, id: str):
        """Delete knowledge"""
        if self._backend == "postgresql":
            with self._get_pg_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("DELETE FROM knowledge WHERE id = %s", (id,))
                conn.commit()
        else:
            with self._get_sqlite_conn() as conn:
                conn.execute("DELETE FROM knowledge WHERE id = ?", (id,))
                try:
                    conn.execute("DELETE FROM knowledge_fts WHERE id = ?", (id,))
                except Exception:
                    pass
        
        if self._collection:
            try:
                self._collection.delete(ids=[id])
            except Exception:
                pass
    
    # =========================================================================
    # Search
    # =========================================================================
    
    def search(self, query: KnowledgeQuery) -> List[SearchResult]:
        """Search for relevant knowledge"""
        results: List[SearchResult] = []
        seen_ids = set()
        
        # Semantic search first
        if self._embedder and self._collection and query.query:
            for r in self._semantic_search(query):
                if r.knowledge.id not in seen_ids:
                    results.append(r)
                    seen_ids.add(r.knowledge.id)
        
        # Full-text search
        if len(results) < query.limit:
            for r in self._fts_search(query):
                if r.knowledge.id not in seen_ids:
                    results.append(r)
                    seen_ids.add(r.knowledge.id)
        
        # Filter and sort
        results = [r for r in results if self._matches_filters(r.knowledge, query)]
        results.sort(key=lambda r: (r.score, r.knowledge.usage_count), reverse=True)
        
        # Record access
        for r in results[:query.limit]:
            self._record_access(r.knowledge.id)
        
        return results[:query.limit]
    
    def _semantic_search(self, query: KnowledgeQuery) -> List[SearchResult]:
        """Semantic search using embeddings"""
        results = []
        try:
            embedding = self._embedder.encode(query.query).tolist()
            
            where = {}
            if query.category:
                where["category"] = query.category.value
            
            search_results = self._collection.query(
                query_embeddings=[embedding],
                n_results=query.limit * 2,
                where=where if where else None
            )
            
            if search_results["ids"] and search_results["ids"][0]:
                ids = search_results["ids"][0]
                distances = search_results.get("distances", [[]])[0]
                
                for i, id in enumerate(ids):
                    k = self.get(id)
                    if k:
                        score = 1.0 - (distances[i] if i < len(distances) else 0.5)
                        results.append(SearchResult(
                            knowledge=k,
                            score=max(0, min(1, score)),
                            match_type="semantic",
                            snippet=self._extract_snippet(k, query.query)
                        ))
        except Exception as e:
            logger.debug(f"Semantic search error: {e}")
        
        return results
    
    def _fts_search(self, query: KnowledgeQuery) -> List[SearchResult]:
        """Full-text search"""
        results = []
        terms = re.sub(r'[^\w\s]', ' ', query.query).split()
        if not terms:
            return results
        
        if self._backend == "postgresql":
            search_query = " | ".join(terms)
            with self._get_pg_conn() as conn:
                with conn.cursor() as cur:
                    sql = """
                        SELECT *, ts_rank(search_vector, to_tsquery('english', %s)) as rank
                        FROM knowledge
                        WHERE search_vector @@ to_tsquery('english', %s)
                    """
                    params = [search_query, search_query]
                    
                    if query.category:
                        sql += " AND category = %s"
                        params.append(query.category.value)
                    
                    sql += " ORDER BY rank DESC LIMIT %s"
                    params.append(query.limit * 2)
                    
                    cur.execute(sql, params)
                    
                    for row in cur.fetchall():
                        k = self._row_to_knowledge_pg(row, cur.description)
                        score = min(1.0, row[-1] * 2) if row[-1] else 0.5
                        results.append(SearchResult(
                            knowledge=k,
                            score=score,
                            match_type="fts",
                            snippet=self._extract_snippet(k, query.query)
                        ))
        else:
            fts_query = " OR ".join(f'"{t}"' for t in terms if len(t) > 2)
            if not fts_query:
                return results
            
            with self._get_sqlite_conn() as conn:
                try:
                    sql = """
                        SELECT k.*, bm25(knowledge_fts) as rank
                        FROM knowledge k
                        JOIN knowledge_fts fts ON k.id = fts.id
                        WHERE knowledge_fts MATCH ?
                        ORDER BY rank
                        LIMIT ?
                    """
                    rows = conn.execute(sql, (fts_query, query.limit * 2)).fetchall()
                    
                    for row in rows:
                        k = self._row_to_knowledge_sqlite(row)
                        score = min(1.0, abs(row["rank"]) / 10) if row["rank"] else 0.5
                        results.append(SearchResult(
                            knowledge=k,
                            score=score,
                            match_type="fts",
                            snippet=self._extract_snippet(k, query.query)
                        ))
                except Exception as e:
                    logger.debug(f"FTS search error: {e}")
        
        return results
    
    def _matches_filters(self, k: Knowledge, q: KnowledgeQuery) -> bool:
        """Check filter match"""
        if q.tags and not any(t in k.tags for t in q.tags):
            return False
        if q.agent and k.applies_to and q.agent not in k.applies_to:
            return False
        if q.severity_min:
            levels = ["low", "medium", "high", "critical"]
            if levels.index(k.severity.value) < levels.index(q.severity_min.value):
                return False
        return True
    
    def _extract_snippet(self, k: Knowledge, query: str) -> str:
        """Extract relevant snippet"""
        content = k.solution or k.content or k.summary or ""
        if not content:
            return ""
        
        query_terms = query.lower().split()
        sentences = re.split(r'[.!?\n]', content)
        
        best = ""
        best_score = 0
        for s in sentences:
            if len(s.strip()) < 10:
                continue
            score = sum(1 for t in query_terms if t in s.lower())
            if score > best_score:
                best_score = score
                best = s.strip()
        
        if best:
            return best[:200] + ("..." if len(best) > 200 else "")
        return content[:200] + ("..." if len(content) > 200 else "")
    
    def _record_access(self, id: str):
        """Record knowledge access"""
        if self._backend == "postgresql":
            with self._get_pg_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        UPDATE knowledge 
                        SET usage_count = usage_count + 1, last_used = NOW()
                        WHERE id = %s
                    """, (id,))
                conn.commit()
        else:
            with self._get_sqlite_conn() as conn:
                conn.execute("""
                    UPDATE knowledge 
                    SET usage_count = usage_count + 1, last_used = ?
                    WHERE id = ?
                """, (datetime.now().isoformat(), id))
    
    # =========================================================================
    # Row Conversion
    # =========================================================================
    
    def _row_to_knowledge_pg(self, row, description) -> Knowledge:
        """Convert PostgreSQL row to Knowledge"""
        cols = [d[0] for d in description]
        data = dict(zip(cols, row))
        
        return Knowledge(
            id=data["id"],
            title=data["title"],
            category=KnowledgeCategory(data["category"]),
            summary=data.get("summary") or "",
            content=data.get("content") or "",
            problem=data.get("problem") or "",
            symptoms=data.get("symptoms") or [],
            root_cause=data.get("root_cause") or "",
            solution=data.get("solution") or "",
            example_code=data.get("example_code") or "",
            wrong_code=data.get("wrong_code") or "",
            tags=data.get("tags") or [],
            keywords=data.get("keywords") or [],
            severity=Severity(data.get("severity") or "medium"),
            applies_to=data.get("applies_to") or [],
            prerequisites=data.get("prerequisites") or [],
            related_ids=data.get("related_ids") or [],
            usage_count=data.get("usage_count") or 0,
            usefulness_score=data.get("usefulness_score") or 0.0,
            last_used=data.get("last_used"),
            source=data.get("source") or "",
            source_url=data.get("source_url") or "",
            created_at=data.get("created_at") or datetime.now(),
            updated_at=data.get("updated_at") or datetime.now(),
        )
    
    def _row_to_knowledge_sqlite(self, row) -> Knowledge:
        """Convert SQLite row to Knowledge"""
        return Knowledge(
            id=row["id"],
            title=row["title"],
            category=KnowledgeCategory(row["category"]),
            summary=row["summary"] or "",
            content=row["content"] or "",
            problem=row["problem"] or "",
            symptoms=json.loads(row["symptoms"]) if row["symptoms"] else [],
            root_cause=row["root_cause"] or "",
            solution=row["solution"] or "",
            example_code=row["example_code"] or "",
            wrong_code=row["wrong_code"] or "",
            tags=json.loads(row["tags"]) if row["tags"] else [],
            keywords=json.loads(row["keywords"]) if row["keywords"] else [],
            severity=Severity(row["severity"] or "medium"),
            applies_to=json.loads(row["applies_to"]) if row["applies_to"] else [],
            prerequisites=json.loads(row["prerequisites"]) if row["prerequisites"] else [],
            related_ids=json.loads(row["related_ids"]) if row["related_ids"] else [],
            usage_count=row["usage_count"] or 0,
            usefulness_score=row["usefulness_score"] or 0.0,
            last_used=datetime.fromisoformat(row["last_used"]) if row["last_used"] else None,
            source=row["source"] or "",
            source_url=row["source_url"] or "",
            created_at=datetime.fromisoformat(row["created_at"]) if row["created_at"] else datetime.now(),
            updated_at=datetime.fromisoformat(row["updated_at"]) if row["updated_at"] else datetime.now(),
        )
    
    # =========================================================================
    # Utilities
    # =========================================================================
    
    def get_context_relevant(self, context: str, agent: Optional[str] = None, limit: int = 3) -> List[Knowledge]:
        """Get knowledge relevant to context"""
        query = KnowledgeQuery(query=context, agent=agent, limit=limit)
        results = self.search(query)
        return [r.knowledge for r in results if r.score > 0.3]
    
    def mark_useful(self, id: str, useful: bool = True):
        """Mark knowledge usefulness"""
        delta = 0.1 if useful else -0.1
        if self._backend == "postgresql":
            with self._get_pg_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE knowledge SET usefulness_score = usefulness_score + %s WHERE id = %s",
                        (delta, id)
                    )
                conn.commit()
        else:
            with self._get_sqlite_conn() as conn:
                conn.execute(
                    "UPDATE knowledge SET usefulness_score = usefulness_score + ? WHERE id = ?",
                    (delta, id)
                )
    
    def list_by_category(self, category: KnowledgeCategory, limit: int = 50) -> List[Knowledge]:
        """List by category"""
        if self._backend == "postgresql":
            with self._get_pg_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT * FROM knowledge WHERE category = %s ORDER BY usage_count DESC LIMIT %s",
                        (category.value, limit)
                    )
                    return [self._row_to_knowledge_pg(r, cur.description) for r in cur.fetchall()]
        else:
            with self._get_sqlite_conn() as conn:
                rows = conn.execute(
                    "SELECT * FROM knowledge WHERE category = ? ORDER BY usage_count DESC LIMIT ?",
                    (category.value, limit)
                ).fetchall()
                return [self._row_to_knowledge_sqlite(r) for r in rows]
    
    def list_all(self, limit: int = 100) -> List[Knowledge]:
        """List all knowledge"""
        if self._backend == "postgresql":
            with self._get_pg_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT * FROM knowledge ORDER BY usage_count DESC LIMIT %s",
                        (limit,)
                    )
                    return [self._row_to_knowledge_pg(r, cur.description) for r in cur.fetchall()]
        else:
            with self._get_sqlite_conn() as conn:
                rows = conn.execute(
                    "SELECT * FROM knowledge ORDER BY usage_count DESC LIMIT ?",
                    (limit,)
                ).fetchall()
                return [self._row_to_knowledge_sqlite(r) for r in rows]
    
    def get_stats(self) -> Dict[str, Any]:
        """Get statistics"""
        if self._backend == "postgresql":
            with self._get_pg_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT COUNT(*) FROM knowledge")
                    total = cur.fetchone()[0]
                    
                    cur.execute("SELECT category, COUNT(*) FROM knowledge GROUP BY category")
                    by_category = dict(cur.fetchall())
                    
                    cur.execute("SELECT title, usage_count FROM knowledge ORDER BY usage_count DESC LIMIT 10")
                    top_used = [{"title": r[0], "count": r[1]} for r in cur.fetchall()]
        else:
            with self._get_sqlite_conn() as conn:
                total = conn.execute("SELECT COUNT(*) FROM knowledge").fetchone()[0]
                by_category = dict(conn.execute(
                    "SELECT category, COUNT(*) FROM knowledge GROUP BY category"
                ).fetchall())
                top_used = [
                    {"title": r["title"], "count": r["usage_count"]}
                    for r in conn.execute(
                        "SELECT title, usage_count FROM knowledge ORDER BY usage_count DESC LIMIT 10"
                    ).fetchall()
                ]
        
        return {
            "total_entries": total,
            "by_category": by_category,
            "top_used": top_used,
            "backend": self._backend,
            "has_semantic_search": self._embedder is not None
        }
    
    def export_json(self, path: str):
        """Export to JSON"""
        data = [k.to_dict() for k in self.list_all(limit=10000)]
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        logger.info(f"Exported {len(data)} entries to {path}")
    
    def import_json(self, path: str) -> int:
        """Import from JSON"""
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        for item in data:
            self.add(Knowledge.from_dict(item))
        logger.info(f"Imported {len(data)} entries from {path}")
        return len(data)
