import { useEffect, useState } from "react";
import { supabase } from "../lib/supabaseClient";
import { useAuth } from "../contexts/AuthContext";
import { usePro } from "./usePro";

const FREE_DAILY_LIMIT = 10;

export function useTranslationQuota() {
  const { user } = useAuth();
  const { isPro } = usePro();
  const [usedToday, setUsedToday] = useState(0);
  const [loading, setLoading] = useState(true);

  const today = new Date().toISOString().slice(0, 10);

  useEffect(() => {
    if (!user) return;
    supabase
      .from("translation_usage")
      .select("count")
      .eq("user_id", user.id)
      .eq("date", today)
      .maybeSingle()
      .then(({ data }) => {
        setUsedToday(data?.count ?? 0);
        setLoading(false);
      });
  }, [user, today]);

  const remaining = isPro ? Infinity : Math.max(0, FREE_DAILY_LIMIT - usedToday);
  const canTranslate = isPro || usedToday < FREE_DAILY_LIMIT;

  async function recordUsage() {
    if (!user || isPro) return; // Pro users aren't metered
    const next = usedToday + 1;
    await supabase
      .from("translation_usage")
      .upsert({ user_id: user.id, date: today, count: next });
    setUsedToday(next);
  }

  return { usedToday, remaining, canTranslate, recordUsage, loading, limit: FREE_DAILY_LIMIT };
}
