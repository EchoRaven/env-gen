import { useEffect, useState } from "react";
import { api } from "../api";
import { useApp } from "../store";

export default function Account() {
  const { user, profile, logout } = useApp();
  const [me, setMe] = useState(null);

  useEffect(() => {
    api("/api/me").then((r) => {
      if (r.ok) setMe(r.data.item);
    });
  }, []);

  return (
    <div className="pt-[88px] pb-16 px-4 md:px-[4vw] min-h-screen max-w-3xl">
      <h1 className="text-2xl md:text-3xl font-semibold mb-6">Account</h1>
      <div className="bg-[#181818] border border-[#333] rounded p-6 space-y-5">
        <div>
          <div className="text-xs text-[#707070]">Name</div>
          <div className="text-lg">{me ? me.name : (user ? user.name : "—")}</div>
        </div>
        <div>
          <div className="text-xs text-[#707070]">Email</div>
          <div className="text-lg">{me ? me.email : (user ? user.email : "—")}</div>
        </div>
        <div>
          <div className="text-xs text-[#707070]">Active profile</div>
          <div className="text-lg">{profile ? profile.name : "—"}</div>
        </div>
        <button
          onClick={() => { logout(); window.location.href = "/"; }}
          className="bg-[#e50914] hover:bg-[#c11119] text-white font-semibold rounded px-6 py-2.5"
        >
          Sign out of Netflix
        </button>
      </div>
    </div>
  );
}
