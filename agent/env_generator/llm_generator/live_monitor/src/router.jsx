// Cutover 28: minimal hash-based router.
// Cutover 41: extended to recognize per-section project routes.
// Routes:
//   #/                              -> { kind: "home" }
//   #/projects/<id>                 -> { kind: "project", projectId: <id>, section: "overview" }
//   #/projects/<id>/<section>       -> { kind: "project", projectId: <id>, section: <section> }
const { useState, useEffect } = window.React;

function parseHash(hash) {
  const clean = (hash || "").replace(/^#/, "");
  if (!clean || clean === "/") return { kind: "home" };
  // Cutover 44: single full-page route for project creation (start generation).
  // The legacy /start route was removed; it now falls through to home.
  if (clean === "/new" || clean === "/new/") return { kind: "new-project" };
  if (clean === "/knowledge" || clean === "/knowledge/") return { kind: "knowledge" };
  // Cutover 43.10: sub-resource routes — #/projects/<id>/<section>/<resource>/<resourceId>
  const detail = clean.match(/^\/projects\/([^/]+)\/([^/]+)\/([^/]+)\/([^/]+)\/?$/);
  if (detail) {
    return {
      kind: "project",
      projectId: decodeURIComponent(detail[1]),
      section: decodeURIComponent(detail[2]),
      subResource: decodeURIComponent(detail[3]),
      subResourceId: decodeURIComponent(detail[4]),
    };
  }
  // Per-hub / per-section routes: #/projects/<id>/<section>
  const sub = clean.match(/^\/projects\/([^/]+)\/([^/]+)\/?$/);
  if (sub) {
    return {
      kind: "project",
      projectId: decodeURIComponent(sub[1]),
      section: decodeURIComponent(sub[2]),
    };
  }
  const proj = clean.match(/^\/projects\/([^/]+)\/?$/);
  if (proj) {
    return {
      kind: "project",
      projectId: decodeURIComponent(proj[1]),
      section: "overview",  // default
    };
  }
  return { kind: "home" };
}

function useRoute() {
  const [route, setRoute] = useState(parseHash(window.location.hash));
  useEffect(() => {
    function onHashChange() {
      setRoute(parseHash(window.location.hash));
    }
    window.addEventListener("hashchange", onHashChange);
    return () => window.removeEventListener("hashchange", onHashChange);
  }, []);
  return route;
}

function navigateTo(path) {
  window.location.hash = path.startsWith("#") ? path : `#${path}`;
}

// Cutover 43.21: deep-link to a specific file in CodeHub's code browser.
// Stashes the target path in a module-global the CodeHub page reads on mount,
// then navigates to the code tab. Used by RegistryHub (consumer files, test files)
// and anywhere that references a source file by path.
function openCodeFile(projectId, filePath, branch) {
  window.__envgenPendingCodeFile = { path: filePath, branch: branch || null };
  navigateTo(`/projects/${encodeURIComponent(projectId)}/codehub`);
}

window.LiveMonitorRouter = { useRoute, navigateTo, openCodeFile };
