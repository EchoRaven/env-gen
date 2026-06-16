window.MonitorTheme = (function () {
  const { useEffect, useState } = React;
  const STORAGE_KEY = "envgen_theme";

  function get() {
    try { return localStorage.getItem(STORAGE_KEY) || "light"; }
    catch (e) { return "light"; }
  }

  function apply(theme) {
    document.documentElement.setAttribute("data-theme", theme);
    // Swap highlight.js stylesheet (Cutover 43.14)
    const light = document.getElementById("hljs-light-theme");
    const dark = document.getElementById("hljs-dark-theme");
    if (light && dark) {
      light.disabled = theme === "dark";
      dark.disabled = theme !== "dark";
    }
  }

  function set(theme) {
    try { localStorage.setItem(STORAGE_KEY, theme); } catch (e) {}
    apply(theme);
  }

  function useTheme() {
    const [theme, setTheme] = useState(get());
    useEffect(() => { apply(theme); }, [theme]);
    function toggle() {
      const next = theme === "dark" ? "light" : "dark";
      set(next);
      setTheme(next);
    }
    return { theme, toggle, setTheme: (t) => { set(t); setTheme(t); } };
  }

  // Apply immediately on script load so we don't flash the wrong theme.
  apply(get());

  return { useTheme, get, set, apply };
})();
