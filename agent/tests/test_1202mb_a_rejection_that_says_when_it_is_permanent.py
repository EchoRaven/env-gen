"""#1202mb — "not permanent: register the schema" was an invitation to retry sixteen times.

GROUND TRUTH (tiktok-web-r121 resume #3):

    11:27:45 … 14:39:45   `chain rejected: unenforceable owner denial — step[N]
                           PUT /api/sounds/${soundId} on `sounds` …`     × 16

Every one of the sixteen is the same endpoint. Across that same window `sounds` carried
`visibility=public` in the registry, and the framework said so out loud about its siblings:

    #1202le chain `feed_discovery_engagement_flow` asserts a cross-user denial on `comments`,
    but the MATERIALS declare that table PUBLIC

The rejection closed with "Judged against the tables as REGISTERED TODAY, so this is not
permanent: register the schema and the same chain is accepted." For a table whose schema has
merely not landed yet that is true and useful. For a table the materials declare PUBLIC it is
false — materials outrank the contract and table metadata, so no owner column is ever coming.

The tell that the lanes were obeying rather than ignoring it: eleven backend tasks mentioning
sounds/owner were filed AND completed in that window. They did what the message asked; what
it asked could not work.
"""
import inspect

import pytest

from env_generator.llm_generator.multi_agent.runtime.hub_registry import HubRegistry


def _reg(tmp_path, visibility):
    r = HubRegistry(tmp_path)
    r.registryhub.register_table(
        "sounds", columns=[{"name": "id", "type": "integer"},
                           {"name": "title", "type": "string"}],
        agent="backend", visibility=visibility)
    return r


def _reject(reg):
    return reg.registryhub.register_verification_chain(
        name="creator_publish_update_flow",
        # The real shape, read out of `unenforceable_owner_denials_1202jd` rather than
        # guessed: the actor key is `auth` and must name an intruder, and `expect` is a LIST
        # of status codes. My first draft used `as`/`{"status": 403}` and matched nothing —
        # a fixture the producer would never emit proves nothing about the producer.
        steps=[{"method": "PUT", "path": "/api/sounds/{id}",
                "auth": "intruder", "expect": [403]}],
        agent="verifier")


def test_a_public_table_is_told_the_denial_is_permanent(tmp_path):
    """★ r121's exact case."""
    err = str(_reject(_reg(tmp_path, "public")).get("error") or "")
    assert "unenforceable owner denial" in err, err
    assert "PERMANENT" in err
    assert "MATERIALS declare" in err
    assert "`sounds`" in err
    assert "Do NOT re-register this chain unchanged" in err
    assert "1202mb" in err


def test_a_public_table_is_not_told_to_register_the_schema(tmp_path):
    """★ The sentence that bought sixteen retries must not survive for this case."""
    err = str(_reject(_reg(tmp_path, "public")).get("error") or "")
    assert "not permanent" not in err
    assert "register the schema and the same chain is accepted" not in err


@pytest.mark.parametrize("visibility", [None, "", "private", "owner"])
def test_a_non_public_table_keeps_the_retryable_wording(tmp_path, visibility):
    """★ Non-regression: for a table whose schema has merely not landed, "register the
    schema" is the correct advice and must stay."""
    err = str(_reject(_reg(tmp_path, visibility)).get("error") or "")
    if not err:
        pytest.skip("this fixture did not produce an unenforceable-denial rejection")
    assert "not permanent" in err
    assert "PERMANENT for" not in err


def test_the_untouched_halves_survive(tmp_path):
    """READS and POST carve-outs are unrelated to this change."""
    err = str(_reject(_reg(tmp_path, "public")).get("error") or "")
    assert "READS are untouched" in err
    assert "POST is" in err and "exempt" in err


def test_the_visibility_lookup_never_raises():
    """A message builder that can raise turns a rejection into a crash."""
    src = inspect.getsource(
        __import__("env_generator.llm_generator.multi_agent.runtime.registryhub",
                   fromlist=["x"]))
    i = src.index("_public_1202mb = []")
    seg = src[i:src.index("return {\"error\": (", i)]
    assert "except Exception:" in seg
    assert "_public_1202mb = []" in seg.split("except Exception:")[1]


def test_the_table_list_declares_its_own_cut():
    """#1034: a list printed for a reader must say when it was cut."""
    src = inspect.getsource(
        __import__("env_generator.llm_generator.multi_agent.runtime.registryhub",
                   fromlist=["x"]))
    i = src.index("PERMANENT for %s")
    seg = src[i:src.index("else:", i)]
    assert "join_capped" in seg
