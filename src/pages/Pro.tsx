import { useState } from "react";
import { useAuth } from "../contexts/AuthContext";
import { usePro } from "../hooks/usePro";

const PLANS = [
  { id: "monthly", label: "รายเดือน", price: "฿99/เดือน" },
  { id: "yearly", label: "รายปี", price: "฿899/ปี (ประหยัด 25%)" },
];

export default function Pro() {
  const { user } = useAuth();
  const { isPro, proUntil } = usePro();
  const [loadingPlan, setLoadingPlan] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function startCheckout(planId: string) {
    if (!user) return;
    setLoadingPlan(planId);
    setError(null);
    try {
      // Calls the Cloudflare Pages Function in /functions/api/create-checkout-session.ts
      // which needs STRIPE_SECRET_KEY set as an environment variable in Cloudflare.
      const res = await fetch("/api/create-checkout-session", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ planId, userId: user.id, email: user.email }),
      });
      const data = await res.json();
      if (data.url) {
        window.location.href = data.url;
      } else {
        setError(data.error ?? "ไม่สามารถเริ่ม checkout ได้");
      }
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoadingPlan(null);
    }
  }

  async function openBillingPortal() {
    if (!user) return;
    const res = await fetch("/api/create-billing-portal-session", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ userId: user.id }),
    });
    const data = await res.json();
    if (data.url) window.location.href = data.url;
  }

  return (
    <div className="p-10 max-w-lg">
      <h1 className="text-2xl font-bold text-grove-800 mb-1">Grove Pro</h1>
      <p className="text-gray-500 mb-6">ปลดล็อกโควตาแปลคำไม่จำกัด, สร้าง skill bank/ชุดคำศัพท์สาธารณะของตัวเอง</p>

      {isPro ? (
        <div className="bg-white rounded-xl border border-grove-100 p-5">
          <div className="text-grove-700 mb-3">
            ✅ คุณเป็นสมาชิก Pro อยู่แล้ว
            {proUntil && proUntil !== "epoch" && ` (ถึง ${new Date(proUntil).toLocaleDateString("th-TH")})`}
          </div>
          <button onClick={openBillingPortal} className="text-sm text-grove-600 underline">
            จัดการการชำระเงิน
          </button>
        </div>
      ) : (
        <div className="space-y-3">
          {PLANS.map((p) => (
            <div key={p.id} className="bg-white rounded-xl border border-grove-100 p-5 flex items-center justify-between">
              <div>
                <div className="font-medium text-grove-800">{p.label}</div>
                <div className="text-sm text-gray-400">{p.price}</div>
              </div>
              <button
                onClick={() => startCheckout(p.id)}
                disabled={loadingPlan === p.id}
                className="bg-grove-600 hover:bg-grove-700 disabled:opacity-50 text-white rounded-lg px-4 py-2 text-sm"
              >
                {loadingPlan === p.id ? "กำลังเปิด..." : "สมัคร"}
              </button>
            </div>
          ))}
          {error && <div className="text-red-500 text-sm">{error}</div>}
        </div>
      )}
    </div>
  );
}
