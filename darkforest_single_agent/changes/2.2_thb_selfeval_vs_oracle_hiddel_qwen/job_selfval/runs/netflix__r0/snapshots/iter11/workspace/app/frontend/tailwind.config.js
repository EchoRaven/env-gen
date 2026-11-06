/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  theme: {
    extend: {
      colors: {
        nfg: "#141414",
        nfred: "#e50914",
        nfgray: "#2f2f2f"
      },
      fontFamily: {
        display: ["Anton", "Impact", "sans-serif"],
        ui: ["Inter", "Helvetica Neue", "Arial", "sans-serif"]
      }
    }
  },
  plugins: []
};
