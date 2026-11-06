import { useEffect, useState } from "react";
import { api, unwrapItems } from "../api";

const OPTIONS = [
  { value: 3, icon: "/assets/icons/thumbs-up.svg", line1: "Excellent", line2: "I really enjoyed it" },
  { value: 2, icon: "/assets/icons/netflix/thumbs_up_two.svg", line1: "Good", line2: "It was pretty good" },
  { value: 1, icon: "/assets/icons/thumbs-down.svg", line1: "Poor", line2: "Not for me" }
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

  const name = title ? title.name : "…";

  return (
    <div
      className="fixed inset-0 z-50 bg-black/80 flex items-center justify-center"
      onMouseDown={(e) => e.target === e.currentTarget && onClose()}
    >
      <div className="w-[min(94vw,1080px)] bg-[#141414] rounded-lg relative flex flex-col items-center pt-[24px] pb-[56px]">
        <h2 className="text-[30px] font-semibold text-white text-center px-8">
          How do you rate {name}?
        </h2>
        <p className="mt-[1.7vh] text-[16px] text-[#8c8c8c] text-center">
          Your rating helps us recommend more shows and films you'll love.
        </p>
        <div className="mt-[4vh] flex items-start justify-center">
          {OPTIONS.map((o) => (
            <button
              key={o.value}
              disabled={busy}
              onClick={() => pick(o.value)}
              className={`w-[10.4vw] min-w-[170px] flex flex-col items-center group ${
                current === o.value ? "" : "opacity-80 hover:opacity-100"
              }`}
            >
              <img src={o.icon} alt="" className="w-10 h-10 invert" />
              <span className="mt-[1.6vh] text-[13px] leading-[1.5] text-[#e5e5e5] text-center">
                {o.line1}
                <br />
                <span className="text-[#999]">{o.line2}</span>
              </span>
            </button>
          ))}
        </div>
        <button
          onClick={onClose}
          className="mt-[4.5vh] text-[14px] text-[#8c8c8c] hover:text-white transition-colors"
        >
          Done
        </button>
      </div>
    </div>
  );
}
