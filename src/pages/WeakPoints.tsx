import { useEffect, useState } from "react";
import { supabase } from "../lib/supabaseClient";
import { useAuth } from "../contexts/AuthContext";
import type { SkillTag } from "../lib/types";

const SKILL_LABEL: Record<SkillTag, string> = {
  grammar: "ไวยากรณ์",
  word_form: "ชนิดคำ",
  cohesion: "การเรียงประโยค/เชื่อมความ",
  detail: "รายละเอียด",
  bigpicture: "ภาพรวม",
  vocab: "คำศัพท์",
};

interface Stat {
  skill: SkillTag;
  total: number;
  correct: number;
}

export default function WeakPoints() {
  const { user } = useAuth();
  const [stats, setStats] = useState<Stat[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!user) return;
    supabase
      .from("attempts")
      .select("skill_tag, correct")
      .eq("user_id", user.id)
      .then(({ data }) => {
        const grouped: Record<string, Stat> = {};
        for (const row of data ?? []) {
          const tag = row.skill_tag as SkillTag;
          if (!grouped[tag]) grouped[tag] = { skill: tag, total: 0, correct: 0 };
          grouped[tag].total += 1;
          if (row.correct) grouped[tag].correct += 1;
        }
        setStats(Object.values(grouped).sort((a, b) => a.correct / a.total - b.correct / b.total));
        setLoading(false);
      });
  }, [user]);

  return (
    <div className="p-10 max-w-2xl">
      <h1 className="text-2xl font-bold text-grove-800 mb-1">จุดอ่อน</h1>
      <p className="text-gray-500 mb-6">วิเคราะห์จากผลการทำโจทย์ทุกกิจกรรม เรียงจากอ่อนสุด</p>

      {loading && <div className="text-gray-400 text-sm">กำลังโหลด...</div>}
      {!loading && stats.length === 0 && (
        <div className="text-gray-400 text-sm py-8 text-center">
          ยังไม่มีข้อมูล — ลองทำโจทย์ Reading, Listening หรือ Writing สักสองสามข้อก่อน
        </div>
      )}

      <div className="space-y-3">
        {stats.map((s) => {
          const pct = Math.round((s.correct / s.total) * 100);
          return (
            <div key={s.skill} className="bg-white rounded-xl border border-grove-100 p-4">
              <div className="flex justify-between text-sm mb-1.5">
                <span className="font-medium text-grove-800">{SKILL_LABEL[s.skill]}</span>
                <span className="text-gray-400">
                  {s.correct}/{s.total} ({pct}%)
                </span>
              </div>
              <div className="h-2 bg-grove-100 rounded-full overflow-hidden">
                <div
                  className={`h-full ${pct < 50 ? "bg-red-400" : pct < 75 ? "bg-yellow-400" : "bg-green-400"}`}
                  style={{ width: `${pct}%` }}
                />
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
