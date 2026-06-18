"""Guard: human↔agent chat reaches a LIVE generation's agents via the EventHub.

Pins the contract that ``send_chat`` injects a real human message into the env's
EventHub thread (visible through HumanConsole), and that an agent's reply in that
thread is returned by ``list_chat`` — i.e. the bridge is wired end-to-end, not a
dead-end DB write.

Uses a TEMP env dir with a freshly-initialised EventHub. It must NEVER touch the
live ``generated/youtube`` env (a generation is running there).

Run with:  cd forgingground-gen && pytest tests/test_chat_humanconsole.py
"""
import os
import sys
import time
from pathlib import Path

# Auth/DB/ENVS_ROOT env is set centrally in conftest.py BEFORE app import; this
# file just reads the resulting secret so the combined `pytest tests/` run is
# order-independent.

import jwt
import pytest
from fastapi.testclient import TestClient

import app.auth as auth
import app.main as m
from app.db import SessionLocal
from app.models import Environment

# Engine root on sys.path so the test can drive the EventHub directly (the
# backend's chat_bridge adds it lazily, but the test simulates an agent reply).
_ENGINE_ROOT = str(Path(__file__).resolve().parents[1] / "agent")
if _ENGINE_ROOT not in sys.path:
    sys.path.insert(0, _ENGINE_ROOT)
from env_generator.llm_generator.multi_agent.runtime.eventhub import EventHub  # noqa: E402

# Sign with whatever secret app.auth ACTUALLY loaded (auth constants bind at
# import time, so if another test module imported app.auth first under a
# different secret, ours wouldn't take — read the live value so this file is
# order-independent within a full `pytest tests/` run).
SECRET = auth.JWT_SECRET or os.environ["AGENTSUITE_JWT_SECRET"]
TENANT = "tenantA"
USER = "alice"


def _tok():
    return jwt.encode(
        {"sub": USER, "tenant_id": TENANT, "is_admin": True, "exp": int(time.time()) + 3600},
        SECRET, algorithm="HS256",
    )


def _hdr():
    return {"Authorization": "Bearer " + _tok()}


@pytest.fixture()
def client():
    with TestClient(m.app) as c:  # context manager fires startup → init_db
        yield c


@pytest.fixture()
def env_dir(tmp_path):
    """A temp env with an initialised EventHub at <env>/shared/hubs."""
    gen = tmp_path / "fake-env"
    hub_dir = gen / "shared" / "hubs"
    hub_dir.mkdir(parents=True)
    EventHub(hub_dir)  # ensure_documents() creates the eventhub_*.json stores
    return gen


def _register_env(eid: str, generated_dir: Path):
    with SessionLocal() as db:
        db.add(Environment(id=eid, name=eid, tenant_id=TENANT, created_by=USER,
                           generated_dir=str(generated_dir), status="generating"))
        db.commit()


def test_send_chat_injects_human_message_into_eventhub(client, env_dir):
    _register_env("chat-env", env_dir)

    r = client.post("/env-forge/environments/chat-env/chat", headers=_hdr(),
                    json={"content": "please add a search endpoint", "recipients": ["backend"]})
    assert r.status_code == 200, r.text
    sent = r.json()
    assert sent["sender"] == USER                      # from_user == authed admin id
    assert sent["recipients"] == ["backend"]
    assert sent["content"] == "please add a search endpoint"
    thread_id = sent["thread_id"]
    assert thread_id

    # The message really landed in the EventHub thread (visible via HumanConsole).
    from app import chat_bridge
    console = chat_bridge.human_console(str(env_dir), default_user_id=USER)
    raw = console.list_messages(thread_id)
    assert any(mm["event_type"] == "human_message" and "search endpoint" in mm["text"] for mm in raw)

    # And list_chat surfaces it back (sourced from the EventHub, not the DB).
    listed = client.get("/env-forge/environments/chat-env/chat", headers=_hdr()).json()
    assert any(c["content"] == "please add a search endpoint" and c["sender"] == USER for c in listed)


def test_agent_reply_round_trips_through_list_chat(client, env_dir):
    _register_env("chat-env2", env_dir)

    # Human starts a conversation with the backend agent.
    sent = client.post("/env-forge/environments/chat-env2/chat", headers=_hdr(),
                       json={"content": "status?", "recipients": ["backend"]}).json()
    thread_id = sent["thread_id"]

    # Simulate the agent replying in that thread (as the eventhub_reply_in_thread
    # tool would during a live run).
    eventhub = EventHub(env_dir / "shared" / "hubs")
    eventhub.publish_agent_reply(thread_id, agent="backend", text="search endpoint shipped")

    # list_chat returns BOTH the human message and the agent reply, time-ordered,
    # with the agent reply attributed to the agent id (sender-distinguished).
    msgs = client.get("/env-forge/environments/chat-env2/chat", headers=_hdr()).json()
    senders = [(c["sender"], c["content"]) for c in msgs]
    assert (USER, "status?") in senders
    assert ("backend", "search endpoint shipped") in senders
    # ordering: human first, reply after
    assert senders.index((USER, "status?")) < senders.index(("backend", "search endpoint shipped"))

    # Scoping to the thread returns the same transcript.
    scoped = client.get(f"/env-forge/environments/chat-env2/chat?thread_id={thread_id}",
                        headers=_hdr()).json()
    assert ("backend", "search endpoint shipped") in [(c["sender"], c["content"]) for c in scoped]


def test_send_chat_into_existing_thread_uses_send_message(client, env_dir):
    _register_env("chat-env3", env_dir)
    first = client.post("/env-forge/environments/chat-env3/chat", headers=_hdr(),
                       json={"content": "hi", "recipients": ["backend"]}).json()
    tid = first["thread_id"]
    # A follow-up into the SAME thread (no need to re-specify recipients).
    r = client.post("/env-forge/environments/chat-env3/chat", headers=_hdr(),
                    json={"content": "any update?", "thread_id": tid})
    assert r.status_code == 200, r.text
    assert r.json()["thread_id"] == tid
    contents = [c["content"] for c in client.get(
        f"/env-forge/environments/chat-env3/chat?thread_id={tid}", headers=_hdr()).json()]
    assert contents == ["hi", "any update?"]


def test_start_conversation_requires_recipient(client, env_dir):
    _register_env("chat-env4", env_dir)
    # New conversation with no agent selected → clear 4xx, not a 500.
    r = client.post("/env-forge/environments/chat-env4/chat", headers=_hdr(),
                    json={"content": "hello?", "recipients": []})
    assert r.status_code == 400, r.text


def test_chat_no_hub_is_empty_not_error(client):
    # Env registered but no generated tree yet → list is empty, send is a clean 400.
    with SessionLocal() as db:
        db.add(Environment(id="no-hub", name="no-hub", tenant_id=TENANT,
                           created_by=USER, generated_dir="", status="generating"))
        db.commit()
    assert client.get("/env-forge/environments/no-hub/chat", headers=_hdr()).json() == []
    r = client.post("/env-forge/environments/no-hub/chat", headers=_hdr(),
                    json={"content": "x", "recipients": ["backend"]})
    assert r.status_code == 400, r.text
