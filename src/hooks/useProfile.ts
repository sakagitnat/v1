import { useEffect, useState } from "react";
import { supabase } from "../lib/supabaseClient";
import { useAuth } from "../contexts/AuthContext";
import type { Profile } from "../lib/types";
import { awardBadgeIfMissing } from "../lib/gamification";

interface Streak {
  current_streak: number;
  longest_streak: number;
  last_checkin: string | null;
}

interface EarnedBadge {
  code: string;
  label: string;
  description: string | null;
  earned_at: string;
}

export function useProfile() {
  const { user } = useAuth();
  const [profile, setProfile] = useState<Profile | null>(null);
  const [streak, setStreak] = useState<Streak | null>(null);
  const [badges, setBadges] = useState<EarnedBadge[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!user) return;
    Promise.all([
      supabase.from("profiles").select("*").eq("id", user.id).single(),
      supabase.from("streaks").select("*").eq("user_id", user.id).maybeSingle(),
      supabase
        .from("user_badges")
        .select("earned_at, badges(code, label, description)")
        .eq("user_id", user.id),
    ]).then(([p, s, b]) => {
      setProfile((p.data as Profile) ?? null);
      setStreak((s.data as Streak) ?? null);
      setBadges(
        ((b.data as any[]) ?? []).map((row) => ({
          code: row.badges.code,
          label: row.badges.label,
          description: row.badges.description,
          earned_at: row.earned_at,
        }))
      );
      setLoading(false);
    });
  }, [user]);

  async function checkIn() {
    if (!user) return;
    const today = new Date().toISOString().slice(0, 10);
    if (streak?.last_checkin === today) return; // already checked in today

    const yesterday = new Date(Date.now() - 86400000).toISOString().slice(0, 10);
    const isConsecutive = streak?.last_checkin === yesterday;
    const newCurrent = isConsecutive ? (streak?.current_streak ?? 0) + 1 : 1;
    const newLongest = Math.max(newCurrent, streak?.longest_streak ?? 0);

    const { data } = await supabase
      .from("streaks")
      .upsert({
        user_id: user.id,
        current_streak: newCurrent,
        longest_streak: newLongest,
        last_checkin: today,
      })
      .select()
      .single();
    setStreak(data as Streak);

    if (newCurrent >= 3) {
      await awardBadgeIfMissing(user.id, "fire_3_days");
    }
  }

  return { profile, streak, badges, loading, checkIn };
}
