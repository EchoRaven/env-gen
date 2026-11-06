import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useApp } from "../store";
import { api, unwrapItems } from "../api";
import { avatarClass } from "../components/Header";

const AVATAR_COUNT = 8;

export default function Profiles() {
  const { profiles, selectProfile, refreshProfiles, booted, load } = useApp();
  const nav = useNavigate();
  const [manage, setManage] = useState(false);
  const [name, setName] = useState("");
  const [avatar, setAvatar] = useState("0");
  const [isKids, setIsKids] = useState(false);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (booted) refreshProfiles();
  }, [booted]);

  const pick = (p) => {
    selectProfile(p);
    nav("/browse");
  };

  const create = async () => {
    if (!name.trim() || busy) return;
    setBusy(true);
    const r = await api("/api/profiles", {
      method: "POST",
      body: { name: name.trim(), avatar, is_kids: isKids }
    });
    setBusy(false);
    if (r.ok) {
      const fresh = await refreshProfiles();
      const p = fresh.find((x) => x.name === name.trim() && x.id !== profiles[0]?.id);
      setName("");
      setManage(false);
      if (p) pick(p);
    }
  };

  return (
    <div className="min-h-screen bg-nfg flex flex-col items-center pt-[10vh] px-4">
      <h1 className="text-3xl md:text-5xl mb-8">Who's watching?</h1>

      <div className="flex flex-wrap justify-center gap-4 md:gap-6 max-w-3xl">
        {profiles.map((p) => (
          <button key={p.id} onClick={() => pick(p)} className="group flex flex-col items-center w-24 md:w-32">
            <span
              className={`w-24 h-24 md:w-32 md:h-32 rounded-lg bg-gradient-to-br ${avatarClass(p.avatar)} flex items-center justify-center text-4xl md:text-5xl font-bold border-2 border-transparent group-hover:border-white transition-all`}
            >
              {p.name.charAt(0).toUpperCase()}
            </span>
            <span className="mt-3 text-lg text-[#606063] group-hover:text-white group-hover:underline">
              {p.name}
            </span>
          </button>
        ))}
        <button
          onClick={() => setManage(true)}
          className="group flex flex-col items-center w-24 md:w-32"
        >
          <span className="w-24 h-24 md:w-32 md:h-32 rounded-lg bg-[#333] border-2 border-dashed border-[#6d6d6e] group-hover:border-white flex items-center justify-center text-5xl text-[#999] group-hover:text-white transition-colors">
            +
          </span>
          <span className="mt-3 text-lg text-[#606063] group-hover:text-white group-hover:underline">
            Manage Profiles
          </span>
        </button>
      </div>

      {manage && (
        <div className="mt-10 w-[min(92vw,420px)] bg-[#181818] border border-[#333] rounded p-6">
          <h2 className="text-lg font-semibold mb-4">Add a profile</h2>
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Profile name"
            className="w-full bg-[#303030] border border-[#555] rounded px-3 py-2 mb-4 outline-none focus:border-white"
          />
          <div className="grid grid-cols-8 gap-2 mb-4">
            {Array.from({ length: AVATAR_COUNT }).map((_, i) => (
              <button
                key={i}
                onClick={() => setAvatar(String(i))}
                className={`aspect-square rounded bg-gradient-to-br ${avatarClass(i)} flex items-center justify-center font-bold border-2 ${
                  avatar === String(i) ? "border-white" : "border-transparent"
                }`}
              >
                {(name || "P").charAt(0).toUpperCase()}
              </button>
            ))}
          </div>
          <label className="flex items-center gap-2 text-sm text-[#e5e5e5] mb-5">
            <input type="checkbox" checked={isKids} onChange={(e) => setIsKids(e.target.checked)} />
            Kids profile
          </label>
          <div className="flex gap-3">
            <button
              onClick={create}
              disabled={!name.trim() || busy}
              className="flex-1 bg-[#e50914] disabled:opacity-40 hover:bg-[#c11119] text-white font-semibold py-2.5 rounded"
            >
              Add profile
            </button>
            <button
              onClick={() => setManage(false)}
              className="px-4 border border-[#6d6d6e] rounded hover:border-white"
            >
              Done
            </button>
          </div>
        </div>
      )}

      <button
        onClick={() => { load(); nav("/"); }}
        className="mt-16 text-sm text-[#707070] hover:text-white hover:underline"
      >
        Sign out
      </button>
    </div>
  );
}
