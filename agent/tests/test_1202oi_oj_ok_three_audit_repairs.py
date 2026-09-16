"""#1202oi/#1202oj/#1202ok — three repairs from the full-pipeline audit.

#1202oi  An internal marker must not travel in an HTTP body. The projected create's 400 said
         "…is nothing but its own id and owner (#1202bl)" — a string an API consumer receives.
         Count per delivered backend: r123 2, r124 3, r125 2, r126 6, i.e. rising.
#1202oj  `framework_guard_tampering_1202lj` (lane code that strips the framework's auth guard)
         had NO call site outside its own unit test. Its condition is present in all four runs
         since it shipped — r126 `custom_routes.py:352` `app.router.routes[:] = kept`, r125:618
         rebinding `_FW_PUBLIC_API_1202KH`, r123:221 rebinding `_fw_contract_public_1202kh` —
         and it fired zero times. Its sibling `auth_override_findings_1202s` reaches the gate
         through the channel this now uses.
#1202ok  A mechanism that WORKED announced itself through `warn_once_1201`, whose sentence is
         "treat this as the mechanism being OFF". That channel is how an auditor finds inert
         mechanisms; r122-r125 each carry a false entry from this site.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime import deliverability as DL  # noqa: E402
from multi_agent.runtime.route_projector import project_missing_routes  # noqa: E402

_MODELS = '''
from sqlalchemy import Column, Integer, String, ForeignKey
from db import Base

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)

class Video(Base):
    __tablename__ = "videos"
    id = Column(Integer, primary_key=True)
    author_id = Column(Integer, ForeignKey("users.id"))

class Comment(Base):
    __tablename__ = "comments"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    video_id = Column(Integer, ForeignKey("videos.id"))
    body = Column(String)
'''


def test_1202oi_no_internal_marker_rides_out_in_an_api_response(tmp_path):
    backend = tmp_path / "app" / "backend"
    backend.mkdir(parents=True)
    (backend / "models.py").write_text(_MODELS)
    (backend / "main.py").write_text("from fastapi import Depends, FastAPI\napp = FastAPI()\n")
    project_missing_routes(backend, [{"method": "POST", "path": "/api/comments",
                                      "auth_required": True}])
    src = (backend / "main.py").read_text()
    details = re.findall(r'detail="([^"]*)"', src) + re.findall(r"detail='([^']*)'", src)
    assert details, "no projected error detail emitted — fixture drifted"
    leaked = [d for d in details if re.search(r"#\d{3,}[a-z]*", d)]
    assert leaked == [], leaked
    # the sentence itself must survive — this is about the marker, not the explanation
    assert any("subject FK" in d for d in details), details


def test_1202oj_the_tamper_finding_reaches_the_gate(tmp_path, monkeypatch):
    backend = tmp_path / "backend"
    backend.mkdir(parents=True)
    (backend / "custom_routes.py").write_text(
        "from fastapi import APIRouter\nrouter = APIRouter()\n"
        "app.router.routes[:] = kept\n")
    (backend / "seed_data.py").write_text("SEED = {}\n")
    out = DL._guard_tampering_blockers_1202oj(tmp_path)
    assert out and any("custom_routes.py" in b for b in out), out
    assert all(b.startswith("framework auth guard tampered") for b in out), out
    monkeypatch.setenv("ENVGEN_GUARD_TAMPER_GATE", "0")
    assert DL._guard_tampering_blockers_1202oj(tmp_path) == []


def test_1202oj_a_clean_lane_file_produces_no_blocker(tmp_path):
    backend = tmp_path / "backend"
    backend.mkdir(parents=True)
    (backend / "custom_routes.py").write_text(
        "from fastapi import APIRouter\nrouter = APIRouter()\n"
        "@router.get('/api/x')\ndef x():\n    return {'items': []}\n")
    assert DL._guard_tampering_blockers_1202oj(tmp_path) == []


def test_1202oj_it_is_called_where_its_siblings_are():
    import inspect
    src = inspect.getsource(DL.compute_deliverability)
    assert "_guard_tampering_blockers_1202oj(app_root)" in src
    assert (src.index("_auth_override_blockers_1202s(app_root)")
            < src.index("_guard_tampering_blockers_1202oj(app_root)"))


def test_1202ok_a_working_normalisation_does_not_claim_to_be_off():
    src = (LLM / "multi_agent" / "runtime" / "registryhub.py").read_text()
    assert 'ValueError("id used as name")' not in src      # no fabricated failure
    i = src.index('if _n1202ly != str(name or ""):')
    branch = src[i:src.index("name = _n1202ly", i)]
    code = [ln for ln in branch.splitlines() if not ln.strip().startswith("#")]
    assert not any("warn_once_1201" in ln for ln in code), branch
    assert "NORMALISED to" in branch
