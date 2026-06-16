// Compatibility shim.
//
// The live monitor is now split into small browser-loaded modules under `src/`.
// `index.html` loads those modules directly, so this file is intentionally kept
// minimal for anyone opening the historical `/app.jsx` path.
console.warn("live_monitor/app.jsx is deprecated. Load /index.html, which uses src/*.jsx modules.");
