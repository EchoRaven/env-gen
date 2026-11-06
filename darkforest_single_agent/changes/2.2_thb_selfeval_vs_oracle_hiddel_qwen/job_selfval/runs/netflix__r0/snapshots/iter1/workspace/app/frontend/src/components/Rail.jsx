import { useRef } from "react";
import Card from "./Card";

export default function Rail({ title, items, numbered = false, titleLink }) {
  const scroller = useRef(null);
  if (!items || items.length === 0) return null;

  const scroll = (dir) => {
    const el = scroller.current;
    if (!el) return;
    el.scrollBy({ left: dir * el.clientWidth * 0.9, behavior: "smooth" });
  };

  return (
    <section className="relative mb-8 md:mb-10 group/rail">
      <h2 className="px-4 md:px-[4vw] mb-2 text-[15px] md:text-[17px] font-semibold text-[#e5e5e5] flex items-center gap-2">
        {title}
        {titleLink && (
          <a href={titleLink} className="text-[12px] text-[#53c1de] opacity-0 group-hover/rail:opacity-100 hover:underline">
            Explore All >
          </a>
        )}
      </h2>
      <div className="relative">
        <button
          onClick={() => scroll(-1)}
          aria-label="Scroll left"
          className="hidden md:flex absolute left-1 top-1/2 -translate-y-1/2 z-20 w-8 h-24 items-center justify-center bg-black/50 opacity-0 group-hover/rail:opacity-100 hover:bg-black/70 rounded"
        >
          <img src="/assets/icons/chevron-left.svg" alt="" className="w-6 h-6 invert" />
        </button>
        <div
          ref={scroller}
          className="flex gap-2 overflow-x-auto no-scrollbar px-4 md:px-[4vw] py-4"
        >
          {items.map((t, i) => (
            <Card key={t.id + "-" + i} title={t} rank={numbered ? i + 1 : null} />
          ))}
        </div>
        <button
          onClick={() => scroll(1)}
          aria-label="Scroll right"
          className="hidden md:flex absolute right-1 top-1/2 -translate-y-1/2 z-20 w-8 h-24 items-center justify-center bg-black/50 opacity-0 group-hover/rail:opacity-100 hover:bg-black/70 rounded"
        >
          <img src="/assets/icons/chevron-right.svg" alt="" className="w-6 h-6 invert" />
        </button>
      </div>
    </section>
  );
}
