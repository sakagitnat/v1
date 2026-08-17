import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useReadingList } from "../hooks/useReading";

type Q = { question: string; choices: string[]; correct_index: number; question_type: "detail" | "bigpicture"; explanation: string };

export default function AddReading() {
  const navigate = useNavigate();
  const { createArticle } = useReadingList();
  const [step, setStep] = useState(1);
  const [title, setTitle] = useState("");
  const [category, setCategory] = useState<"ad" | "review" | "news" | "infographic" | "general">("general");
  const [body, setBody] = useState("");
  const [timeGoal, setTimeGoal] = useState(300);
  const [questions, setQuestions] = useState<Q[]>([
    { question: "", choices: ["", "", "", ""], correct_index: 0, question_type: "detail", explanation: "" },
  ]);

  function updateQ(i: number, patch: Partial<Q>) {
    setQuestions((prev) => prev.map((q, idx) => (idx === i ? { ...q, ...patch } : q)));
  }
  function updateChoice(qi: number, ci: number, value: string) {
    setQuestions((prev) =>
      prev.map((q, idx) =>
        idx === qi ? { ...q, choices: q.choices.map((c, cidx) => (cidx === ci ? value : c)) } : q
      )
    );
  }

  async function handleSubmit() {
    await createArticle({
      title,
      category,
      body,
      time_goal_seconds: timeGoal,
      questions: questions
        .filter((q) => q.question.trim())
        .map((q) => ({
          question: q.question,
          choices: q.choices,
          correct_index: q.correct_index,
          question_type: q.question_type,
          explanation: q.explanation || null,
        })),
    });
    navigate("/reading");
  }

  return (
    <div className="p-10 max-w-2xl">
      <h1 className="text-2xl font-bold text-grove-800 mb-6">เพิ่มบทความ+โจทย์ ({step}/2)</h1>

      {step === 1 && (
        <div className="space-y-3">
          <input
            placeholder="ชื่อบทความ"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            className="border border-grove-200 rounded-lg px-3 py-2 text-sm w-full"
          />
          <div className="flex gap-3">
            <select
              value={category}
              onChange={(e) => setCategory(e.target.value as any)}
              className="border border-grove-200 rounded-lg px-3 py-2 text-sm"
            >
              <option value="general">บทความทั่วไป</option>
              <option value="ad">โฆษณา</option>
              <option value="review">บทวิจารณ์</option>
              <option value="news">ข่าว</option>
              <option value="infographic">ข้อมูลภาพ/ตาราง</option>
            </select>
            <input
              type="number"
              value={timeGoal}
              onChange={(e) => setTimeGoal(Number(e.target.value))}
              className="border border-grove-200 rounded-lg px-3 py-2 text-sm w-32"
            />
            <span className="text-sm text-gray-400 self-center">วินาที เป้าหมายเวลา</span>
          </div>
          <textarea
            placeholder="เนื้อหาบทความ"
            value={body}
            onChange={(e) => setBody(e.target.value)}
            rows={8}
            className="border border-grove-200 rounded-lg px-3 py-2 text-sm w-full"
          />
          <button
            onClick={() => setStep(2)}
            disabled={!title.trim() || !body.trim()}
            className="bg-grove-600 hover:bg-grove-700 disabled:opacity-40 text-white rounded-lg px-5 py-2 text-sm"
          >
            ถัดไป: เพิ่มโจทย์ →
          </button>
        </div>
      )}

      {step === 2 && (
        <div className="space-y-6">
          {questions.map((q, qi) => (
            <div key={qi} className="bg-white rounded-xl border border-grove-100 p-4 space-y-2">
              <input
                placeholder={`คำถามข้อ ${qi + 1}`}
                value={q.question}
                onChange={(e) => updateQ(qi, { question: e.target.value })}
                className="border border-grove-200 rounded px-2 py-1.5 text-sm w-full"
              />
              {q.choices.map((c, ci) => (
                <div key={ci} className="flex items-center gap-2">
                  <input
                    type="radio"
                    checked={q.correct_index === ci}
                    onChange={() => updateQ(qi, { correct_index: ci })}
                  />
                  <input
                    placeholder={`ตัวเลือก ${ci + 1}`}
                    value={c}
                    onChange={(e) => updateChoice(qi, ci, e.target.value)}
                    className="border border-grove-200 rounded px-2 py-1 text-sm flex-1"
                  />
                </div>
              ))}
              <div className="flex gap-2 items-center">
                <select
                  value={q.question_type}
                  onChange={(e) => updateQ(qi, { question_type: e.target.value as any })}
                  className="border border-grove-200 rounded px-2 py-1 text-sm"
                >
                  <option value="detail">detail</option>
                  <option value="bigpicture">bigpicture</option>
                </select>
                <input
                  placeholder="คำอธิบายเฉลย (ถ้ามี)"
                  value={q.explanation}
                  onChange={(e) => updateQ(qi, { explanation: e.target.value })}
                  className="border border-grove-200 rounded px-2 py-1 text-sm flex-1"
                />
              </div>
            </div>
          ))}
          <button
            onClick={() =>
              setQuestions((prev) => [
                ...prev,
                { question: "", choices: ["", "", "", ""], correct_index: 0, question_type: "detail", explanation: "" },
              ])
            }
            className="text-grove-600 text-sm underline"
          >
            + เพิ่มข้ออีก
          </button>
          <div className="flex gap-2">
            <button onClick={() => setStep(1)} className="text-sm text-gray-500">
              ← กลับ
            </button>
            <button
              onClick={handleSubmit}
              className="bg-grove-600 hover:bg-grove-700 text-white rounded-lg px-5 py-2 text-sm ml-auto"
            >
              บันทึกบทความ
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
