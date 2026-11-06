import { useEffect, useMemo, useState } from "react";
import { api, unwrapItems } from "../api";
import { openTitleModal } from "../App";

const TABS = [
  { id: "original", label: "Original Language" },
  { id: "dubbing", label: "Dubbing" },
  { id: "subs", label: "Subtitles" }
];

export default function BrowseLanguages() {
  const [all, setAll] = useState([]);
  const [tab, setTab] = useState("original");
  const [lang, setLang] = useState("all");

  useEffect(() => {
    api("/api/titles").then((r) => {
      if (r.ok) setAll(unwrapItems(r));
    });
  }, []);

  const langs = useMemo(
    () => [...new Set(all.map((t) => t.language).filter(Boolean))].sort(),
    [all]
  );

  const visible = useMemo(() => {
    if (tab !== "original") return [];
    return lang === "all" ? all : all.filter((t) => t.language === lang);
  }, [all, tab, lang]);

  return (
    <div className="pt-[104px] pb-10 px-[3.5vw] min-h-screen">
      <div className="flex items-center">
        <h1 className="text-[26px] font-semibold">Browse by Languages</h1>
        <div className="ml-auto flex gap-6 border-b border-[#2a2a2a]">
          {TABS.map((t) => (
            <button
              key={t.id}
              onClick={() => setTab(t.id)}
              className={`pb-2.5 px-1 text-[15px] font-semibold border-b-2 -mb-px ${
                tab === t.id
                  ? "border-white text-white"
                  : "border-transparent text-[#707070] hover:text-white"
              }`}
            >
              {t.label}
            </button>
          ))}
        </div>
      </div>

      {tab === "original" ? (
        <>
          <div className="flex justify-end items-center gap-2 text-sm text-[#e5e5e5] mt-6 mb-4">
            <span className="text-[#707070]">Original Language</span>
            <select
              value={lang}
              onChange={(e) => setLang(e.target.value)}
              className="bg-[#2f2f2f] border border-[#4d4d4d] rounded px-2 py-1"
            >
              <option value="all">All languages</option>
              {langs.map((l) => (
                <option key={l} value={l}>{l.toUpperCase()}</option>
              ))}
            </select>
          </div>
          {visible.length === 0 ? (
            <div className="text-[#999] py-20 text-center">No titles found for this selection.</div>
          ) : (
            <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6 gap-2">
              {visible.map((t) => (
                <button key={t.id} onClick={() => openTitleModal(t.id)} className="text-left group">
                  <div className="aspect-video rounded overflow-hidden bg-[#1f1f1f]">
                    <img
                      src={t.poster}
                      alt={t.name}
                      className="w-full h-full object-cover group-hover:opacity-90"
                      loading="lazy"
                    />
                  </div>
                  <div className="mt-1.5 text-[13px] truncate">{t.name}</div>
                  <div className="text-[11px] text-[#707070] uppercase">{t.language || "—"}</div>
                </button>
              ))}
            </div>
          )}
        </>
      ) : (
        <div className="flex flex-col items-center justify-center py-24 text-center">
          <img src="/assets/icons/search.svg" alt="" className="w-10 h-10 invert opacity-40 mb-4" />
          <div className="text-lg text-[#e5e5e5]">
            {tab === "dubbing" ? "No dubbed titles yet" : "No subtitled titles yet"}
          </div>
          <p className="mt-1 text-sm text-[#707070] max-w-md">
            {tab === "dubbing"
              ? "Dubbed versions are not available in this catalog. Try the Original Language tab to browse by the language a title was made in."
              : "Subtitled versions are not available in this catalog. Try the Original Language tab to browse by the language a title was made in."}
          </p>
        </div>
      )}
    </div>
  );
}
