import { useEffect, useMemo, useState } from "react";
import { api, unwrapItems } from "../api";
import { openTitleModal } from "../App";

const LANG_NAMES = { en: "English", es: "Spanish", fr: "French", de: "German", it: "Italian", pt: "Portuguese", ja: "Japanese", ko: "Korean", hi: "Hindi" };

export default function BrowseLanguages() {
  const [all, setAll] = useState([]);
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
        <div className="ml-auto flex items-center gap-3">
          <span className="text-[14px] text-[#707070]">Original Language</span>
          <select
            value={lang}
            onChange={(e) => setLang(e.target.value)}
            className="bg-[#2f2f2f] border border-[#4d4d4d] rounded px-3 py-1.5 text-[14px] text-[#e5e5e5]"
          >
            <option value="all">All languages</option>
            {langs.map((l) => (
              <option key={l} value={l}>{LANG_NAMES[l] || l.toUpperCase()}</option>
            ))}
          </select>
        </div>
      </div>

      <div className="mt-[5vh]">
        {visible.length === 0 ? (
          <div className="text-[#999] py-20 text-center">No titles found for this selection.</div>
        ) : (
          <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6 gap-1.5">
            {visible.map((t) => (
              <button key={t.id} onClick={() => openTitleModal(t.id)} className="text-left group">
                <div className="aspect-video rounded overflow-hidden bg-[#1f1f1f]">
                  <img
                    src={t.backdrop || t.poster}
                    alt={t.name}
                    className="w-full h-full object-cover group-hover:opacity-90"
                    loading="lazy"
                  />
                </div>
                <div className="mt-1.5 text-[13px] truncate">{t.name}</div>
                <div className="text-[11px] text-[#707070] uppercase">{t.language ? (LANG_NAMES[t.language] || t.language.toUpperCase()) : "—"}</div>
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
