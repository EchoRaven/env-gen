"""#264 — a real-dataset table override must not drop the SCOPE column it omits.

r56 (opus-4.7) built a fully-populated app and then failed every browse-then-act chain:

    GET  /api/feed/for-you   -> 200 but "save FAILED (response lacks the path)" for
                                items.0.id   => items was EMPTY
    POST /api/videos/16/like -> 201          => the row EXISTS (that read is unscoped)
    POST /api/videos/7/share -> 404          => the tenant-scoped read cannot see it

The database was FULL and every tenant-scoped read was empty. The loader merges
seed_dataset.json (the real design-prep data) over seed_data.json by replacing whole
tables, and the dataset's 35 videos carry no ``tenant_id`` — so they loaded NULL-scoped
and vanished from every scoped query. Indistinguishable from a seeding failure, which is
why r55 and r56 both spent their convergence budget on it.

ONLY the scope column is carried over, and that restraint is the point. Measured on r56's
own files, the dataset also omits:

    users     email, password   -> unique; 9 identical emails fail the insert outright
    comments  parent_id         -> a self-FK; every comment becomes a reply to comment 1
    videos    sound_id, category

so the blanket "backfill every key the base row has" version I wrote first would have
corrupted the seed rather than repaired it.
"""
import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

sys.path.insert(0, str(Path(__file__).parent))
from test_seed_data_generator import _TABLES, render_seed_data  # noqa: E402


def _rendered() -> str:
    return render_seed_data(_TABLES)


def _merge_fn():
    """Compile the EMITTED merge body and return it as a callable — the generated code
    itself is under test, never a mirror of it."""
    src = _rendered()
    start = src.index("            merged = dict(base)")
    end = src.index("            return merged") + len("            return merged")
    body = "\n".join(l[8:] for l in src[start:end].splitlines())
    ns: dict = {}
    exec(compile("def _merge(base, real):\n" + body + "\n",   # noqa: S102
                 "<generated-seed-loader>", "exec"), ns)
    return ns["_merge"]


def test_the_whole_generated_file_still_compiles():
    """The gate that caught the first attempt: a fragment compiling proves nothing — an
    emitted file that does not parse takes the app down at boot."""
    ast.parse(_rendered())


def test_the_seed_assignment_is_still_extractable():
    """Sibling tests read _SEED out of the rendered file; keep that contract."""
    m = re.search(r"^_SEED = (\{.*\})$", _rendered(), re.M)
    assert m and isinstance(ast.literal_eval(m.group(1)), dict)


def test_r56_regression_tenant_id_is_carried_onto_dataset_rows():
    base = {"videos": [{"id": 1, "tenant_id": "default", "caption": "seed"}]}
    real = {"videos": [{"id": 7, "caption": "real a"}, {"id": 9, "caption": "real b"}]}
    got = _merge_fn()(base, real)["videos"]
    assert len(got) == 2, "the dataset rows must still win"
    assert all(r["tenant_id"] == "default" for r in got), got
    assert [r["caption"] for r in got] == ["real a", "real b"]


def test_unique_and_self_fk_columns_are_NEVER_copied():
    """The restraint that keeps this a repair instead of a corruption."""
    base = {"users": [{"id": 1, "tenant_id": "t", "email": "a@x.io", "password": "p"}],
            "comments": [{"id": 1, "tenant_id": "t", "parent_id": 1, "like_count": 9}]}
    real = {"users": [{"id": 2, "name": "A"}, {"id": 3, "name": "B"}],
            "comments": [{"id": 5, "text": "hi"}, {"id": 6, "text": "yo"}]}
    got = _merge_fn()(base, real)
    assert all("email" not in r and "password" not in r for r in got["users"])
    assert all("parent_id" not in r and "like_count" not in r for r in got["comments"])
    assert all(r["tenant_id"] == "t" for r in got["users"] + got["comments"])


def test_dataset_scope_values_are_never_overwritten():
    base = {"videos": [{"id": 1, "tenant_id": "default"}]}
    real = {"videos": [{"id": 7, "tenant_id": "other"}]}
    assert _merge_fn()(base, real)["videos"][0]["tenant_id"] == "other"


def test_other_scope_column_names_are_handled():
    for key in ("tenant", "org_id", "organization_id", "workspace_id", "account_id"):
        base = {"t": [{"id": 1, key: "S"}]}
        real = {"t": [{"id": 2}]}
        assert _merge_fn()(base, real)["t"][0][key] == "S", key


def test_table_absent_from_base_passes_through():
    assert _merge_fn()({}, {"sounds": [{"id": 3}]})["sounds"] == [{"id": 3}]


def test_base_only_tables_are_kept():
    got = _merge_fn()({"users": [{"id": 1}]}, {"videos": [{"id": 2}]})
    assert got["users"] == [{"id": 1}] and got["videos"] == [{"id": 2}]


def test_empty_dataset_table_does_not_wipe_the_base():
    base = {"videos": [{"id": 1, "tenant_id": "default"}]}
    assert _merge_fn()(base, {"videos": []})["videos"] == base["videos"]


def test_non_dict_rows_survive_untouched():
    got = _merge_fn()({"videos": [{"id": 1, "tenant_id": "d"}]}, {"videos": ["raw"]})
    assert got["videos"] == ["raw"]


def test_base_without_a_scope_column_changes_nothing():
    base = {"videos": [{"id": 1, "caption": "c"}]}
    real = {"videos": [{"id": 7}]}
    assert _merge_fn()(base, real)["videos"] == [{"id": 7}]
