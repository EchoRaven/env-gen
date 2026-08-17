"""synthesize_missing_tables must canonicalize kebab endpoint resources to snake_case.

A POST /api/my-list endpoint must recognize the data-model `my_list` table as the same
resource — else it synthesizes a spurious `my-list` table → a 2nd `class MyList(Base)` in
models.py that `import *` shadows (no profile_id) → GET/POST /api/my-list 500 (netflix r1).
"""
from env_generator.llm_generator.multi_agent.runtime.database_scaffold import synthesize_missing_tables

def _tbl(name, cols): return {name: {"id": name, "schema": {"columns": cols}}}

def test_kebab_endpoint_matches_snake_table_no_duplicate():
    tables = _tbl("my_list", [{"name":"id","type":"int","primary_key":True},{"name":"profile_id","type":"int"}])
    eps = [{"method":"POST","path":"/api/my-list","schema":{"request":{"title_id":"int"}}}]
    out = synthesize_missing_tables(tables, eps)
    assert set(out.keys()) == {"my_list"}, out.keys()  # no 'my-list'

def test_genuinely_missing_kebab_synthesized_as_snake():
    out = synthesize_missing_tables({}, [{"method":"POST","path":"/api/watch-history","schema":{"request":{"x":"int"}}}])
    assert "watch_history" in out and "watch-history" not in out

def test_existing_snake_unregressed():
    tables = _tbl("posts", [{"name":"id","type":"int","primary_key":True}])
    out = synthesize_missing_tables(tables, [{"method":"POST","path":"/api/posts","schema":{"request":{}}}])
    assert set(out.keys()) == {"posts"}

if __name__ == "__main__":
    import pytest; raise SystemExit(pytest.main([__file__, "-q"]))
