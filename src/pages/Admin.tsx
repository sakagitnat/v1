import { useEffect, useState } from "react";
import { supabase } from "../lib/supabaseClient";
import { useAuth } from "../contexts/AuthContext";

export default function Admin() {
  const { user } = useAuth();
  const [isAdmin, setIsAdmin] = useState<boolean | null>(null);
  const [deleteRequests, setDeleteRequests] = useState<any[]>([]);
  const [reports, setReports] = useState<any[]>([]);
  const [giftCode, setGiftCode] = useState("");
  const [giftDays, setGiftDays] = useState(30);

  useEffect(() => {
    if (!user) return;
    supabase
      .from("profiles")
      .select("is_admin")
      .eq("id", user.id)
      .single()
      .then(({ data }) => setIsAdmin(!!data?.is_admin));
  }, [user]);

  useEffect(() => {
    if (!isAdmin) return;
    supabase
      .from("content_delete_requests")
      .select("*")
      .eq("status", "pending")
      .then(({ data }) => setDeleteRequests(data ?? []));
    supabase
      .from("content_reports")
      .select("*")
      .eq("status", "open")
      .then(({ data }) => setReports(data ?? []));
  }, [isAdmin]);

  async function resolveDeleteRequest(id: string, approve: boolean, contentType: string, contentId: string) {
    if (approve) {
      // Actually remove the underlying content row.
      const table =
        contentType === "vocab_word"
          ? "vocab_words"
          : contentType === "vocab_set"
          ? "vocab_sets"
          : contentType === "reading_article"
          ? "reading_articles"
          : contentType === "listening_item"
          ? "listening_items"
          : contentType === "writing_fill_blank"
          ? "writing_fill_blank"
          : contentType === "writing_reorder"
          ? "writing_reorder"
          : "skill_banks";
      await supabase.from(table).delete().eq("id", contentId);
    }
    await supabase
      .from("content_delete_requests")
      .update({ status: approve ? "approved" : "rejected", resolved_at: new Date().toISOString() })
      .eq("id", id);
    setDeleteRequests((prev) => prev.filter((r) => r.id !== id));
  }

  async function resolveReport(id: string, action: "resolved" | "dismissed") {
    await supabase.from("content_reports").update({ status: action }).eq("id", id);
    setReports((prev) => prev.filter((r) => r.id !== id));
  }

  async function issueGiftCode() {
    if (!giftCode.trim()) return;
    await supabase.from("gift_codes").insert({ code: giftCode.trim(), pro_days: giftDays });
    setGiftCode("");
    alert("ออกโค้ดแล้ว");
  }

  if (isAdmin === null) return <div className="p-10 text-gray-400">กำลังตรวจสอบสิทธิ์...</div>;
  if (!isAdmin)
    return (
      <div className="p-10 text-gray-400">
        หน้านี้สำหรับแอดมินเท่านั้น (ต้องตั้ง <code>profiles.is_admin = true</code> ใน Supabase)
      </div>
    );

  return (
    <div className="p-10 max-w-3xl">
      <h1 className="text-2xl font-bold text-grove-800 mb-6">แอดมิน</h1>

      <section className="mb-8">
        <h2 className="font-semibold text-grove-800 mb-3">คำขอลบเนื้อหา ({deleteRequests.length})</h2>
        {deleteRequests.length === 0 && <div className="text-gray-400 text-sm">ไม่มีคำขอค้าง</div>}
        <div className="space-y-2">
          {deleteRequests.map((r) => (
            <div key={r.id} className="bg-white rounded-xl border border-grove-100 p-4 flex items-center justify-between text-sm">
              <div>
                <div>{r.content_type}: {r.content_id}</div>
                {r.reason && <div className="text-gray-400 text-xs mt-0.5">เหตุผล: {r.reason}</div>}
              </div>
              <div className="flex gap-2">
                <button
                  onClick={() => resolveDeleteRequest(r.id, true, r.content_type, r.content_id)}
                  className="text-green-600"
                >
                  อนุมัติ
                </button>
                <button
                  onClick={() => resolveDeleteRequest(r.id, false, r.content_type, r.content_id)}
                  className="text-red-500"
                >
                  ปฏิเสธ
                </button>
              </div>
            </div>
          ))}
        </div>
      </section>

      <section className="mb-8">
        <h2 className="font-semibold text-grove-800 mb-3">รายงานเนื้อหา ({reports.length})</h2>
        {reports.length === 0 && <div className="text-gray-400 text-sm">ไม่มีรายงานค้าง</div>}
        <div className="space-y-2">
          {reports.map((r) => (
            <div key={r.id} className="bg-white rounded-xl border border-grove-100 p-4 flex items-center justify-between text-sm">
              <div>
                <div>{r.content_type}: {r.content_id}</div>
                <div className="text-gray-400 text-xs mt-0.5">{r.reason}</div>
              </div>
              <div className="flex gap-2">
                <button onClick={() => resolveReport(r.id, "resolved")} className="text-green-600">
                  แก้ไขแล้ว
                </button>
                <button onClick={() => resolveReport(r.id, "dismissed")} className="text-gray-400">
                  ยกเลิก
                </button>
              </div>
            </div>
          ))}
        </div>
      </section>

      <section>
        <h2 className="font-semibold text-grove-800 mb-3">ออกโค้ดของขวัญ Pro</h2>
        <div className="flex gap-2">
          <input
            placeholder="โค้ด เช่น GROVE2026"
            value={giftCode}
            onChange={(e) => setGiftCode(e.target.value)}
            className="border border-grove-200 rounded-lg px-3 py-2 text-sm"
          />
          <input
            type="number"
            value={giftDays}
            onChange={(e) => setGiftDays(Number(e.target.value))}
            className="border border-grove-200 rounded-lg px-3 py-2 text-sm w-24"
          />
          <span className="text-sm text-gray-400 self-center">วัน</span>
          <button onClick={issueGiftCode} className="bg-grove-600 hover:bg-grove-700 text-white rounded-lg px-4 py-2 text-sm">
            ออกโค้ด
          </button>
        </div>
      </section>
    </div>
  );
}
