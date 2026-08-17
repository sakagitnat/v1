import { supabase } from "./supabaseClient";
import type { SkillTag } from "./types";
import { awardBadgeIfMissing, addXp } from "./gamification";

export type ActivityType = "reading" | "listening" | "writing_fill" | "writing_reorder" | "mock_exam";

const XP_PER_CORRECT = 10;
const XP_PER_INCORRECT = 2; // small XP just for attempting

export async function logAttempt(params: {
  userId: string;
  activityType: ActivityType;
  itemId: string;
  skillTag: SkillTag;
  correct: boolean;
  timeSpentSeconds: number;
}) {
  const { error } = await supabase.from("attempts").insert({
    user_id: params.userId,
    activity_type: params.activityType,
    item_id: params.itemId,
    skill_tag: params.skillTag,
    correct: params.correct,
    time_spent_seconds: params.timeSpentSeconds,
  });
  if (error) {
    console.error("logAttempt failed:", error.message);
    return;
  }

  await addXp(params.userId, params.correct ? XP_PER_CORRECT : XP_PER_INCORRECT);

  // "First step" badge — first attempt ever.
  const { count } = await supabase
    .from("attempts")
    .select("*", { count: "exact", head: true })
    .eq("user_id", params.userId);
  if (count === 1) {
    await awardBadgeIfMissing(params.userId, "first_step");
  }
}
