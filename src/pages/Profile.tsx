import { useEffect, useState } from "react";
import { useAuth } from "../contexts/AuthContext";
import { useProfile } from "../hooks/useProfile";
import { usePro } from "../hooks/usePro";
import { supabase } from "../lib/supabaseClient";

export default function ProfilePage() {
  const { user } = useAuth();
  const { profile, streak, badges, loading, checkIn } = useProfile();
  const { isPro, proUntil } = usePro();
  const [leaderboard, setLeaderboard] = useState<{ username: string; xp: number }[]>([]);

  useEffect(() => {
    supabase
      .from("profiles")
      .select("username, xp")
      .order("xp", { ascending: false })
      .limit(10)
      .then(({ data }) => setLeaderboard(data ?? []));
  }, []);

  if (loading) return <div className="p-10 text-gray-400">กำลังโหลด...</div>;

  const today = new Date().toISOString().slice(0, 10);
  const checkedInToday = streak?.last_checkin === today;

  return (
    <div className="p-10 max-w-2xl">
      <div className="flex items-center gap-4 mb-6">
        <div className="w-16 h-16 rounded-full bg-grove-200 flex items-center justify-center text-2xl">
          {profile?.avatar_url ? (
            <img src={profile.avatar_url} className="w-full h-full rounded-full object-cover" />
          ) : (
            "🙂"
          )}
        </div>
        <div>
          <div className="font-bold text-lg text-grove-800">{profile?.username}</div>
          <div className="text-sm text-gray-400">{user?.email}</div>
          {isPro && (
            <span className="inline-block mt-1 text-xs bg-yellow-100 text-yellow-700 px-2 py-0.5 rounded-full">
              ⭐ Pro Member
              {proUntil && proUntil !== "epoch" && ` — จนถึง ${new Date(proUntil).toLocaleDateString("th-TH")}`}
            </span>
          )}
        </div>
      </div>

      <div className="grid grid-cols-3 gap-3 mb-6">
        <Stat label="เลเวล" value={profile?.level ?? 1} />
        <Stat label="XP" value={profile?.xp ?? 0} />
        <Stat label="Streak" value={`${streak?.current_streak ?? 0} วัน`} />
      </div>

      <button
        onClick={checkIn}
        disabled={checkedInToday}
        className="bg-grove-600 hover:bg-grove-700 disabled:opacity-40 text-white rounded-lg px-4 py-2 text-sm mb-8"
      >
        {checkedInToday ? "เช็คอินวันนี้แล้ว ✓" : "🔥 เช็คอินวันนี้"}
      </button>

      <div className="mb-8">
        <h2 className="font-semibold text-grove-800 mb-3">แบดจ์</h2>
        {badges.length === 0 ? (
          <div className="text-gray-400 text-sm">ยังไม่มีแบดจ์ — เริ่มฝึกเพื่อปลดล็อก!</div>
        ) : (
          <div className="flex flex-wrap gap-2">
            {badges.map((b) => (
              <div key={b.code} className="bg-white border border-grove-100 rounded-lg px-3 py-2 text-sm">
                🏅 {b.label}
              </div>
            ))}
          </div>
        )}
      </div>

      <div>
        <h2 className="font-semibold text-grove-800 mb-3">Leaderboard</h2>
        <div className="bg-white rounded-xl border border-grove-100 divide-y divide-grove-100">
          {leaderboard.map((row, i) => (
            <div key={i} className="flex justify-between px-4 py-2 text-sm">
              <span>
                {i + 1}. {row.username}
              </span>
              <span className="text-gray-400">{row.xp} XP</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="bg-white rounded-xl border border-grove-100 p-4 text-center">
      <div className="text-xl font-bold text-grove-700">{value}</div>
      <div className="text-xs text-gray-400">{label}</div>
    </div>
  );
}
