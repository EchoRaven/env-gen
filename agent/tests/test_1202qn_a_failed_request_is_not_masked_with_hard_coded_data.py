"""#1202qn: a frontend that answers a failed request with hard-coded data is a delivery blocker
routed to the frontend lane (tiktok-r127: `catch { return fallbackVideos }` copied from the
design references; 4 of the last 80 runs shipped the same shape)."""
from pathlib import Path

from env_generator.llm_generator.multi_agent.runtime import frontend_audit as FA
from env_generator.llm_generator.multi_agent.runtime import remediation_dispatcher as RD
from env_generator.llm_generator.multi_agent.runtime.delivery_gate import _deliverability_check_token

R127 = """export async function getFeed(params={}){try{const q=new URLSearchParams(params).toString();return (await request(`/api/videos/feed${q?`?${q}`:''}`,{auth:true})).items||[]}catch{return fallbackVideos}}"""
R125 = """  if (!tenantsPromise) {
    tenantsPromise = fetch(`${API_BASE}/api/v1/tenants`, { headers: {} })
      .then(async (res) => { const data = await res.json(); return data.items; })
      .catch(() => [{ id: 'default', name: 'default' }]);
  }"""
R120 = """const profileLoader = getUser(routeUsername).catch(() => profileFallback(routeUsername));"""
NOT_API = """export function safeGetStorage(key, fallback = '') {
  try { return localStorage.getItem(key) || fallback; }
  catch { return fallback; }
}"""
LOGGED_OUT = """export async function getMe(){try{return await request('/auth/me')}catch{return {authenticated:false,user:null}}}"""
SURFACED = """getFeed().then(setVideos).catch((e) => setError(e.message));"""


def test_the_corpus_shapes_are_flagged():
    for src in (R127, R125, R120):
        assert FA.masked_api_failures_1202qn(src), src


def test_non_api_helpers_and_surfaced_errors_are_not():
    for src in (NOT_API, LOGGED_OUT, SURFACED):
        assert FA.masked_api_failures_1202qn(src) == [], src


def test_the_blocker_names_the_file_and_line_and_routes_to_frontend(tmp_path):
    (tmp_path / "services").mkdir()
    (tmp_path / "services" / "api.js").write_text("\n" + R127)
    b = FA.masked_api_failure_blockers_1202qn(tmp_path)
    assert len(b) == 1 and "services/api.js:2" in b[0] and "masked API failure" in b[0]
    assert _deliverability_check_token(b[0]) == "deliverability_masked_api_failure"
    src = Path(RD.__file__).read_text(encoding="utf-8")
    i = src.index('"deliverability_masked_api_failure": (')
    entry = src[i:src.index('"deliverability_dead_nav_link": (', i)]
    assert '"frontend"' in entry
