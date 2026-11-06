import { useEffect, useState } from "react";
import { api, unwrapItems } from "../api";

const OPTIONS = [
  { value: 1, icon: "/assets/icons/thumbs-down.svg", label: "I did not like it" },
  { value: 2, icon: "/assets/icons/thumbs-up.svg", label: "I liked it" },
  { value: 3, icon: "/assets/icons/netflix/thumbs_up_two.svg", label: "I loved it" }
];

export default function RateDialog({ titleId, onClose }) {
  const [title, setTitle] = useState(null);
  const [current, setCurrent] = useState(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let live = true;
    api(`/api/titles/${titleId}`).then((r) => {
      if (live && r.ok) setTitle(r.data.item);
    });
    api("/api/ratings").then((r) => {
      if (!live || !r.ok) return;
      const row = unwrapItems(r).find((x) => x.title_id === titleId);
      setCurrent(row ? row.value : null);
    });
    return () => { live = false; };
  }, [titleId]);

  const pick = async (value) => {
    if (busy) return;
    setBusy(true);
    await api(`/api/titles/${titleId}/rating`, { method: "POST", body: { value } });
    setBusy(false);
    setCurrent(value);
    setTimeout(onClose, 350);
  };

  const img = title ? title.backdrop || title.poster : null;

  return (
    <div
      className="fixed inset-0 z-50 bg-black/70 flex items-center justify-center"
      onMouseDown={(e) => e.target === e.currentTarget && onClose()}
    >
      <div className="w-[min(94vw,1080px)] bg-[#181818] border border-[#333] rounded-xl px-10 pt-9 pb-8 shadow-2xl relative">
        <div className="flex items-start justify-between">
          <h2 className="text-[26px] font-semibold">Rate for better recommendations</h2>
          <button onClick={onClose} aria-label="Close" className="mt-1">
            <img src="/assets/icons/x.svg" alt="" className="w-5 h-5 invert" />
          </button>
        </div>

        <div className="mt-7">
          {img && (
            <img
              src={img}
              alt={title ? title.name : ""}
              className="w-[430px] max-w-full h-[150px] object-cover rounded"
            />
          )}
          <div className="mt-4 max-w-[75%]">
            <div className="text-[20px] font-semibold">
              {title ? title.name : "Loading…"}
            </div>
            <p className="mt-1.5 text-[14px] text-[#999] line-clamp-2">
              {title ? title.synopsis : ""}
            </p>
          </div>
        </div>

        <div className="mt-8 flex items-center justify-around">
          {OPTIONS.map((o) => (
            <button
              key={o.value}
              disabled={busy}
              onClick={() => pick(o.value)}
              className={`flex flex-col items-center gap-2.5 ${
                current === o.value ? "opacity-100" : "opacity-80 hover:opacity-100"
              }`}
            >
              <span
                className={`w-16 h-16 rounded-full border-2 flex items-center justify-center transition-colors ${
                  current === o.value ? "border-white bg-white/10" : "border-[#6d6d6e] hover:border-white"
                }`}
              >
                <img src={o.icon} alt="" className="w-7 h-7 invert" />
              </span>
              <span className="text-[13px] text-[#e5e5e5]">{o.label}</span>
            </button>
          ))}
        </div>
        <p className="mt-5 text-center text-xs text-[#777]">
          Your rating is saved to this profile and improves what we recommend to you.
        </p>
      </div>
    </div>
  );
}
