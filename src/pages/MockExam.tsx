import { useEffect, useState } from "react";
import { supabase } from "../lib/supabaseClient";
import QuizRunner from "../components/QuizRunner";

interface ExamQuestion {
  id: string;
  question: string;
  choices: string[];
  correctIndex: number;
  skillTag: "detail" | "bigpicture" | "grammar";
}

// Mock exam intentionally is NOT scoped to "my content only" — it always
// pulls from official + public content so there's always a full exam
// available, per the spec.
export default function MockExam() {
  const [questions, setQuestions] = useState<ExamQuestion[]>([]);
  const [loading, setLoading] = useState(true);
  const [started, setStarted] = useState(false);

  useEffect(() => {
    async function load() {
      setLoading(true);
      const { data: readingQ } = await supabase
        .from("reading_questions")
        .select("*, reading_articles!inner(is_official, is_public)")
        .or("is_official.eq.true,is_public.eq.true", { foreignTable: "reading_articles" })
        .limit(10);

      const mapped: ExamQuestion[] = (readingQ ?? []).map((q: any) => ({
        id: q.id,
        question: q.question,
        choices: q.choices,
        correctIndex: q.correct_index,
        skillTag: q.question_type,
      }));
      setQuestions(mapped);
      setLoading(false);
    }
    load();
  }, []);

  if (loading) return <div className="p-10 text-gray-400">กำลังโหลดข้อสอบ...</div>;

  if (!started) {
    return (
      <div className="p-10 max-w-2xl">
        <h1 className="text-2xl font-bold text-grove-800 mb-2">สอบจำลอง</h1>
        <p className="text-gray-500 mb-6">
          รวมโจทย์จากเนื้อหาทางการและคลังสาธารณะ {questions.length} ข้อ จับเวลาแบบข้อสอบจริง
        </p>
        {questions.length === 0 ? (
          <div className="text-gray-400 text-sm">
            ยังไม่มีเนื้อหาทางการในระบบ — เพิ่มบทความที่ตั้ง is_official=true ผ่าน Supabase หรือรอแอดมินเพิ่ม
          </div>
        ) : (
          <button
            onClick={() => setStarted(true)}
            className="bg-grove-600 hover:bg-grove-700 text-white rounded-lg px-5 py-2 text-sm"
          >
            เริ่มทำข้อสอบ
          </button>
        )}
      </div>
    );
  }

  return (
    <div className="p-10 max-w-2xl">
      <h1 className="text-2xl font-bold text-grove-800 mb-4">สอบจำลอง</h1>
      <QuizRunner
        activityType="mock_exam"
        timeGoalSeconds={questions.length * 60}
        questions={questions}
      />
    </div>
  );
}
