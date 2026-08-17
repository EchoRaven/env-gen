"""#557 (R1) — contract-completeness oracle.

Every test/coverage layer in the generator derives from the DECLARED endpoint
contract; nothing reconciles that contract against the INTENDED feature set. So a
MISSING endpoint (e.g. the Continue-Watching progress write-path) is invisible —
business_chain_api_coverage reports "100%" of declared endpoints while the feature
is broken. These tests pin the oracle that catches that class:

  * a state entity (mutable data column) READABLE but with only GET → flagged;
  * the same entity once a POST exists → clean;
  * a pure-lookup table (only PK/FK/timestamp columns) with only GET → NOT flagged;
  * a mutation flow with no backing write endpoint → flagged;
  * empty/missing feature_inventory → no crash (best-effort).

Plus the ground-truth reconciliation shape (Netflix continue_watching /
progress_seconds) and no-false-positive on read-only reference/catalog tables.
"""

from env_generator.llm_generator.multi_agent.runtime.completeness_audit import (
    compute_completeness,
    check_state_entity_no_write,
    check_flow_no_write,
    check_entity_no_read,
    _is_state_column,
    _state_entities,
)


# ---------------------------------------------------------------------------
# Fakes (duck-typed like the real hubs — mirrors test_delivery_gate_infra_chain_486)
# ---------------------------------------------------------------------------

class _FakeRH:
    def __init__(self, endpoints, tables):
        self._eps = endpoints
        self._tbls = tables

    def get_endpoints(self):
        return dict(self._eps)

    def list_tables(self, provider=None):
        return dict(self._tbls)


class _FakeWorkhub:
    def __init__(self, feature_inventory=None, section="frontend"):
        self._fi = feature_inventory
        self._section = section

    def list_documents(self, kind=None, status=None):
        if kind not in (None, "kickoff"):
            return []
        if self._fi is None:
            return []
        return [{
            "kind": "kickoff",
            "metadata": {
                "decisions": [
                    {"section": self._section, "milestone_index": 1,
                     "content": {"done_def": ["x"], "feature_inventory": self._fi}},
                ]
            },
        }]


class _FakeHubs:
    def __init__(self, rh, wh=None):
        self.registryhub = rh
        self.schema_hub = rh  # real HubRegistry aliases schema_hub -> registryhub
        self.workhub = wh or _FakeWorkhub()


def _col(name, type_="integer", **kw):
    return {"name": name, "type": type_, **kw}


def _table(name, columns, status="implemented"):
    return {"id": name, "name": name, "status": status,
            "schema": {"columns": columns}}


def _ep(method, path, status="implemented", **kw):
    return {"method": method, "path": path, "status": status, **kw}


# A state-bearing table: PK + owner FK + a mutable scalar + a timestamp
_STATE_TABLE = _table("watch_progress", [
    _col("id", "integer", primary_key=True),
    _col("user_id", "integer", references="users.id"),
    _col("item_id", "integer", references="items.id"),
    _col("progress_seconds", "integer", default=0),
    _col("updated_at", "timestamp"),
])

# A pure lookup/join table: only PK + FK + timestamp (NO mutable data column)
_LOOKUP_TABLE = _table("item_tags", [
    _col("id", "integer", primary_key=True),
    _col("item_id", "integer", references="items.id"),
    _col("tag_id", "integer", references="tags.id"),
    _col("created_at", "timestamp"),
])


# ---------------------------------------------------------------------------
# _is_state_column classifier
# ---------------------------------------------------------------------------

def test_is_state_column_positive_examples():
    assert _is_state_column("progress_seconds", "integer")
    assert _is_state_column("status", "string")
    assert _is_state_column("value", "string")
    assert _is_state_column("position", "integer")
    assert _is_state_column("is_watched", "boolean")
    # booleans are toggle-state regardless of the exact name
    assert _is_state_column("enabled", "boolean")


def test_is_state_column_negatives_keys_timestamps_descriptive():
    # primary key / foreign key / timestamps are structural, never state
    assert not _is_state_column("id", "integer")
    assert not _is_state_column("user_id", "integer")
    assert not _is_state_column("created_at", "timestamp")
    assert not _is_state_column("updated_at", "timestamp")
    # descriptive / catalog columns are set-once content, not mutable state
    assert not _is_state_column("name", "string")
    assert not _is_state_column("title", "string")
    assert not _is_state_column("rating", "float")           # catalog rating
    assert not _is_state_column("top10_rank", "integer")     # catalog ranking
    assert not _is_state_column("last_name", "string")       # 'last' must not leak


# ---------------------------------------------------------------------------
# state_entity_no_write
# ---------------------------------------------------------------------------

def test_state_entity_only_get_is_flagged():
    tables = {"watch_progress": _STATE_TABLE}
    endpoints = {"e1": _ep("GET", "/api/watch-progress")}
    results = check_state_entity_no_write(tables, endpoints)
    assert len(results) == 1
    r = results[0]
    assert r.check_id == "completeness_state_entity_no_write"
    assert r.ok is False
    assert r.severity == "error"
    assert r.entity == "watch_progress"
    assert "POST" in (r.missing_verb or "")


def test_state_entity_with_post_is_clean():
    tables = {"watch_progress": _STATE_TABLE}
    endpoints = {
        "e1": _ep("GET", "/api/watch-progress"),
        "e2": _ep("POST", "/api/watch-progress"),
    }
    results = check_state_entity_no_write(tables, endpoints)
    assert results == []


def test_state_entity_with_put_on_nested_path_is_clean():
    # a write endpoint that reaches the entity via a nested/singular path still
    # counts (token-based matching: 'watch_progress' <- 'watch-progress' segment).
    tables = {"watch_progress": _STATE_TABLE}
    endpoints = {
        "e1": _ep("GET", "/api/watch-progress"),
        "e2": _ep("PUT", "/api/watch-progress/{id}"),
    }
    assert check_state_entity_no_write(tables, endpoints) == []


def test_pure_lookup_table_only_get_not_flagged():
    tables = {"item_tags": _LOOKUP_TABLE}
    endpoints = {"e1": _ep("GET", "/api/item-tags")}
    # No mutable data column -> not a state entity -> never flagged.
    assert _state_entities(tables) == {}
    assert check_state_entity_no_write(tables, endpoints) == []


def test_reference_catalog_table_with_name_not_flagged():
    # A read-only reference table whose only non-key column is descriptive
    # ('name') must NOT be misclassified as state (genres-style).
    tables = {"genres": _table("genres", [
        _col("id", "integer", primary_key=True),
        _col("name", "string", unique=True),
    ])}
    endpoints = {"e1": _ep("GET", "/api/genres")}
    assert _state_entities(tables) == {}
    assert check_state_entity_no_write(tables, endpoints) == []


def test_state_entity_with_no_endpoints_at_all_not_flagged():
    # An unexposed state table (no GET either) is a DIFFERENT bug (dead table);
    # this check is scoped to readable-but-not-writable to avoid false positives.
    tables = {"watch_progress": _STATE_TABLE}
    endpoints = {}
    assert check_state_entity_no_write(tables, endpoints) == []


def test_spine_tables_excluded():
    # framework-owned identity/tenancy tables are not app features.
    tables = {"users": _table("users", [
        _col("id", "integer", primary_key=True),
        _col("email", "string"),
        _col("status", "string"),  # would look state-y, but users is spine
    ])}
    endpoints = {"e1": _ep("GET", "/api/users")}
    assert "users" not in _state_entities(tables)
    assert check_state_entity_no_write(tables, endpoints) == []


# ---------------------------------------------------------------------------
# flow_no_write
# ---------------------------------------------------------------------------

def test_mutation_flow_without_backing_endpoint_flagged():
    endpoints = {"e1": _ep("GET", "/api/continue-watching")}
    results = check_flow_no_write(None, endpoints, ["continue_watching"])
    assert len(results) == 1
    assert results[0].check_id == "completeness_flow_no_write"
    assert results[0].flow == "continue_watching"
    assert results[0].missing_verb == "watch"
    assert results[0].severity == "warn"


def test_mutation_flow_with_backing_endpoint_clean():
    endpoints = {
        "e1": _ep("GET", "/api/continue-watching"),
        "e2": _ep("POST", "/api/continue-watching"),
    }
    assert check_flow_no_write(None, endpoints, ["continue_watching"]) == []


def test_non_mutation_flow_not_flagged():
    # a read-only flow name (no mutation verb) is never flagged
    endpoints = {"e1": _ep("GET", "/api/search")}
    assert check_flow_no_write(None, endpoints, ["search", "catalog_browse"]) == []


# ---------------------------------------------------------------------------
# entity_no_read (secondary)
# ---------------------------------------------------------------------------

def test_entity_without_get_flagged():
    endpoints = {"e1": _ep("POST", "/api/widgets")}
    results = check_entity_no_read(endpoints, ["widgets"])
    assert len(results) == 1
    assert results[0].check_id == "completeness_entity_no_read"
    assert results[0].missing_verb == "GET"


def test_entity_with_get_clean():
    endpoints = {"e1": _ep("GET", "/api/widgets")}
    assert check_entity_no_read(endpoints, ["widgets"]) == []


# ---------------------------------------------------------------------------
# compute_completeness end-to-end + robustness
# ---------------------------------------------------------------------------

def test_compute_completeness_flags_continue_watching_ground_truth():
    """Netflix-shaped reconciliation: continue_watching (progress_seconds, GET
    only) is flagged state_entity_no_write; genres/my_list are not."""
    tables = {
        "genres": _table("genres", [
            _col("id", "integer", primary_key=True),
            _col("name", "string", unique=True),
        ]),
        "my_list": _table("my_list", [
            _col("id", "integer", primary_key=True),
            _col("profile_id", "integer", references="profiles.id"),
            _col("title_id", "integer", references="titles.id"),
            _col("created_at", "timestamp"),
        ]),
        "continue_watching": _table("continue_watching", [
            _col("id", "integer", primary_key=True),
            _col("profile_id", "integer", references="profiles.id"),
            _col("title_id", "integer", references="titles.id"),
            _col("progress_seconds", "integer", default=0),
            _col("updated_at", "timestamp"),
        ]),
    }
    endpoints = {
        "e1": _ep("GET", "/api/genres"),
        "e2": _ep("GET", "/api/my-list"),
        "e3": _ep("POST", "/api/my-list"),
        "e4": _ep("DELETE", "/api/my-list/{id}"),
        "e5": _ep("GET", "/api/continue-watching"),
    }
    fi = {"catalog_browse": "browse rails", "my_list": "add/remove saved",
          "continue_watching": "GET /api/continue-watching rail with progress bar"}
    hubs = _FakeHubs(_FakeRH(endpoints, tables), _FakeWorkhub(fi))

    report = compute_completeness(hubs)
    state_writes = [r for r in report.results
                    if r.check_id == "completeness_state_entity_no_write"]
    assert [r.entity for r in state_writes] == ["continue_watching"]
    assert report.blocking_check_ids("error") == ["completeness_state_entity_no_write"]
    assert not report.is_clean


def test_compute_completeness_empty_inventory_no_crash():
    tables = {"widgets": _table("widgets", [
        _col("id", "integer", primary_key=True),
        _col("name", "string"),
    ])}
    endpoints = {"e1": _ep("GET", "/api/widgets")}
    # feature_inventory missing entirely
    hubs = _FakeHubs(_FakeRH(endpoints, tables), _FakeWorkhub(None))
    report = compute_completeness(hubs)
    assert report.is_clean  # nothing to flag; no crash


def test_compute_completeness_missing_workhub_no_crash():
    tables = {"watch_progress": _STATE_TABLE}
    endpoints = {"e1": _ep("GET", "/api/watch-progress")}

    class _NoWorkhub:
        registryhub = _FakeRH(endpoints, tables)
        schema_hub = registryhub
        # no workhub attribute

    report = compute_completeness(_NoWorkhub())
    # still reconciles the table/endpoint sources even with no inventory source
    assert any(r.check_id == "completeness_state_entity_no_write"
               for r in report.results)


def test_compute_completeness_canonical_inventory_shape():
    # {entities, flows} shape: an entity with no GET is (secondarily) flagged.
    tables = {}
    endpoints = {"e1": _ep("POST", "/api/orders")}
    fi = {"entities": ["orders"], "flows": ["create_order"]}
    hubs = _FakeHubs(_FakeRH(endpoints, tables), _FakeWorkhub(fi, section="backend"))
    report = compute_completeness(hubs)
    ids = {r.check_id for r in report.results}
    assert "completeness_entity_no_read" in ids   # orders has no GET
    assert "completeness_flow_no_write" in ids     # create_order has no write
