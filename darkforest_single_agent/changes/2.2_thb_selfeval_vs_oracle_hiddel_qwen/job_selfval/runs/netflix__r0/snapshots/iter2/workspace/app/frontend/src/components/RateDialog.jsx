import { useEffect, useState } from "react";
import { api, unwrapItems } from "../api";

const OPTIONS = [
  { value: 1, icon: "/assets/icons/thumbs-down.svg", label: "I did not like it" },
  { value: 2, icon: "/assets/icons/thumbs-up.svg", label: "I liked it" },
  { value: 3, icon: "/assets/icons/netflix/thumbs_up_two.svg", label: "I loved it" }
];

export default function RateDialog({ titleId, onClose }) {
  const [current, setCurrent] = useState(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let live = true;
    api("/api/ratings").then((r) => {
      if (!live || !r.ok) return;
      const row = unwrapItems(r).find((x) => x.title_id === titleId);
      setCurrent(row ? row.value : null);
    });
    return () => { live = false; };
  }, [titleId]);

  const pick = async (value) => {
    setBusy(true);
    await api(`/api/titles/${titleId}/rating`, { method: "POST", body: { value } });
    setBusy(false);
    setCurrent(value);
    setTimeout(onClose, 350);
  };

  return (
    <div
      className="fixed inset-0 z-50 bg-black/70 flex items-center justify-center"
      onMouseDown={(e) => e.target === e.currentTarget && onClose()}
    >
      <div className="w-[min(92vw,480px)] bg-[#181818] border border-[#333] rounded-lg p-6 shadow-2xl">
        <div className="flex items-start justify-between">
          <h2 className="text-xl font-semibold">Rate for better recommendations</h2>
          <button onClick={onClose} aria-label="Close">
            <img src="/assets/icons/x.svg" alt="" className="w-5 h-5 invert" />
          </button>
        </div>
        <div className="mt-6 flex items-center justify-between gap-2">
          {OPTIONS.map((o) => (
            <button
              key={o.value}
              disabled={busy}
              onClick={() => pick(o.value)}
              className={`flex-1 flex flex-col items-center gap-2 py-5 rounded border transition-colors ${
                current === o.value ? "border-white bg-white/10" : "border-[#4d4d4d] hover:border-white"
              }`}
            >
              <img src={o.icon} alt="" className="w-8 h-8 invert" />
              <span className="text-xs text-center leading-tight">{o.label}</span>
            </button>
          ))}
        </div>
        <p className="mt-4 text-xs text-[#777]">
          Your rating is saved to this profile and improves what we recommend to you.
        </p>
      </div>
    </div>
  );
}
