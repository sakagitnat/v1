import { useEffect } from "react";
import { supabase } from "../lib/supabaseClient";
import { useAuth } from "../contexts/AuthContext";

const REFERRER_BONUS_DAYS = 14;
const REFERRED_BONUS_DAYS = 7;

// Mounted once near the app root. On first authenticated load, checks for a
// pending referral code (saved by Login.tsx from ?ref=... query param) and
// grants the bonus to both sides exactly once.
export default function ReferralProcessor() {
  const { user } = useAuth();

  useEffect(() => {
    if (!user) return;
    const pendingRef = localStorage.getItem("grove_pending_ref");
    if (!pendingRef) return;

    async function process() {
      const { data: referral } = await supabase
        .from("referrals")
        .select("*")
        .eq("code", pendingRef)
        .is("redeemed_at", null)
        .maybeSingle();

      if (!referral || referral.referrer_id === user!.id) {
        localStorage.removeItem("grove_pending_ref");
        return;
      }

      await supabase
        .from("referrals")
        .update({ referred_id: user!.id, redeemed_at: new Date().toISOString() })
        .eq("code", pendingRef);

      const referrerBonus = new Date(Date.now() + REFERRER_BONUS_DAYS * 86400000).toISOString();
      const referredBonus = new Date(Date.now() + REFERRED_BONUS_DAYS * 86400000).toISOString();

      await supabase.from("subscriptions").upsert({
        user_id: referral.referrer_id,
        referral_bonus_end: referrerBonus,
      });
      await supabase.from("subscriptions").upsert({
        user_id: user!.id,
        referral_bonus_end: referredBonus,
      });

      localStorage.removeItem("grove_pending_ref");
    }

    process();
  }, [user]);

  return null;
}
