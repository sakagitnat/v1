import { useEffect, useState } from "react";
import { supabase } from "../lib/supabaseClient";
import { useAuth } from "../contexts/AuthContext";

export default function Invite() {
  const { user } = useAuth();
  const [code, setCode] = useState<string | null>(null);
  const [redeemInput, setRedeemInput] = useState("");
  const [redeemStatus, setRedeemStatus] = useState<string | null>(null);

  useEffect(() => {
    if (!user) return;
    supabase
      .from("referrals")
      .select("code")
      .eq("referrer_id", user.id)
      .is("redeemed_at", null)
      .limit(1)
      .maybeSingle()
      .then(async ({ data }) => {
        if (data) {
          setCode(data.code);
          return;
        }
        const newCode = `${user.id.slice(0, 6)}-${Math.random().toString(36).slice(2, 8)}`;
        await supabase.from("referrals").insert({ referrer_id: user.id, code: newCode });
        setCode(newCode);
      });
  }, [user]);

  const link = code ? `${window.location.origin}/login?ref=${code}` : "";

  async function redeemGiftCode() {
    if (!user || !redeemInput.trim()) return;
    setRedeemStatus(null);
    const { data: gift } = await supabase
      .from("gift_codes")
      .select("*")
      .eq("code", redeemInput.trim())
      .is("redeemed_by", null)
      .maybeSingle();
    if (!gift) {
      setRedeemStatus("โค้ดไม่ถูกต้องหรือถูกใช้ไปแล้ว");
      return;
    }
    const proUntil = new Date(Date.now() + gift.pro_days * 86400000).toISOString();
    await supabase.from("gift_codes").update({ redeemed_by: user.id, redeemed_at: new Date().toISOString() }).eq("code", gift.code);
    await supabase.from("subscriptions").upsert({ user_id: user.id, gift_pro_end: proUntil });
    setRedeemStatus(`รับสิทธิ์ Pro ${gift.pro_days} วันแล้ว 🎉`);
    setRedeemInput("");
  }

  return (
    <div className="p-10 max-w-lg">
      <h1 className="text-2xl font-bold text-grove-800 mb-1">ชวนเพื่อน</h1>
      <p className="text-gray-500 mb-6">คุณได้ Pro 14 วัน เพื่อนที่ถูกชวนได้ 7 วัน เมื่อสมัครผ่านลิงก์นี้</p>

      <div className="bg-white rounded-xl border border-grove-100 p-4 mb-8">
        <div className="text-xs text-gray-400 mb-1">ลิงก์เฉพาะของคุณ</div>
        <div className="flex gap-2">
          <input readOnly value={link} className="border border-grove-200 rounded px-2 py-1.5 text-sm flex-1" />
          <button
            onClick={() => navigator.clipboard.writeText(link)}
            className="bg-grove-600 hover:bg-grove-700 text-white rounded px-3 py-1.5 text-sm"
          >
            คัดลอก
          </button>
        </div>
      </div>

      <div className="bg-white rounded-xl border border-grove-100 p-4">
        <div className="text-sm font-medium text-grove-700 mb-2">แลกโค้ดของขวัญ</div>
        <div className="flex gap-2">
          <input
            value={redeemInput}
            onChange={(e) => setRedeemInput(e.target.value)}
            placeholder="ใส่โค้ด"
            className="border border-grove-200 rounded px-2 py-1.5 text-sm flex-1"
          />
          <button onClick={redeemGiftCode} className="bg-grove-600 hover:bg-grove-700 text-white rounded px-3 py-1.5 text-sm">
            แลกโค้ด
          </button>
        </div>
        {redeemStatus && <div className="text-sm text-grove-600 mt-2">{redeemStatus}</div>}
      </div>
    </div>
  );
}
