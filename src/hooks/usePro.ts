import { useEffect, useState } from "react";
import { supabase } from "../lib/supabaseClient";
import { useAuth } from "../contexts/AuthContext";

export function usePro() {
  const { user } = useAuth();
  const [isPro, setIsPro] = useState(false);
  const [proUntil, setProUntil] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!user) {
      setLoading(false);
      return;
    }
    supabase
      .from("pro_status")
      .select("is_pro, pro_until")
      .eq("user_id", user.id)
      .maybeSingle()
      .then(({ data }) => {
        setIsPro(!!data?.is_pro);
        setProUntil(data?.pro_until ?? null);
        setLoading(false);
      });
  }, [user]);

  return { isPro, proUntil, loading };
}
