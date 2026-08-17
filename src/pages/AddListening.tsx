import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useListeningList } from "../hooks/useListening";

type Q = { question: string; choices: string[]; correct_index: number };

export default function AddListening() {
  const navigate = useNavigate();
  const { createItem } = useListeningList();
  const [title, setTitle] = useState("");
  const [script, setScript] = useState("");
  const [questions, setQuestions] = useState<Q[]>([
    { question: "", choices: ["", "", "", ""], correct_index: 0 },
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
    await createItem({
      title,
      script,
      questions: questions.filter((q) => q.question.trim()),
    });
    navigate("/listening");
  }

  return (
    <div className="p-10 max-w-2xl">
      <h1 className="text-2xl font-bold text-grove-800 mb-6">เพิ่มบทสนทนา+โจทย์</h1>
      <div className="space-y-3 mb-6">
        <input
          placeholder="ชื่อบทสนทนา"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          className="border border-grove-200 rounded-lg px-3 py-2 text-sm w-full"
        />
        <textarea
          placeholder="Script (ข้อความที่จะอ่านออกเสียง)"
          value={script}
          onChange={(e) => setScript(e.target.value)}
          rows={6}
          className="border border-grove-200 rounded-lg px-3 py-2 text-sm w-full"
        />
      </div>

      {questions.map((q, qi) => (
        <div key={qi} className="bg-white rounded-xl border border-grove-100 p-4 space-y-2 mb-3">
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
        </div>
      ))}
      <button
        onClick={() =>
          setQuestions((prev) => [...prev, { question: "", choices: ["", "", "", ""], correct_index: 0 }])
        }
        className="text-grove-600 text-sm underline"
      >
        + เพิ่มข้ออีก
      </button>
      <div>
        <button
          onClick={handleSubmit}
          disabled={!title.trim() || !script.trim()}
          className="bg-grove-600 hover:bg-grove-700 disabled:opacity-40 text-white rounded-lg px-5 py-2 text-sm mt-4"
        >
          บันทึก
        </button>
      </div>
    </div>
  );
}
