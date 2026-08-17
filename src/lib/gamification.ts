import { supabase } from "./supabaseClient";

// Simple level curve: level = floor(sqrt(xp / 50)) + 1
// e.g. 0-49 xp = level 1, 50-199 = level 2, 200-449 = level 3, ...
function levelForXp(xp: number): number {
  return Math.floor(Math.sqrt(xp / 50)) + 1;
}

export async function addXp(userId: string, amount: number) {
  const { data: profile } = await supabase.from("profiles").select("xp, level").eq("id", userId).single();
  if (!profile) return;

  const newXp = profile.xp + amount;
  const newLevel = levelForXp(newXp);

  await supabase.from("profiles").update({ xp: newXp, level: newLevel }).eq("id", userId);

  if (newLevel > profile.level) {
    if (newLevel >= 5) await awardBadgeIfMissing(userId, "level_5");
    if (newLevel >= 10) await awardBadgeIfMissing(userId, "level_10");
  }
}

export async function awardBadgeIfMissing(userId: string, code: string) {
  const { data: badge } = await supabase.from("badges").select("id").eq("code", code).maybeSingle();
  if (!badge) return; // badge must be seeded in the `badges` table first (see schema.sql seed section)

  const { data: existing } = await supabase
    .from("user_badges")
    .select("badge_id")
    .eq("user_id", userId)
    .eq("badge_id", badge.id)
    .maybeSingle();
  if (existing) return;

  await supabase.from("user_badges").insert({ user_id: userId, badge_id: badge.id });
}
