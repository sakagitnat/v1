import { useParams, useNavigate } from "react-router-dom";
import { useEffect, useState } from "react";
import { useReadingDetail } from "../hooks/useReading";
import { useVocabSets, useVocabWords } from "../hooks/useVocabSets";
import { useTranslationQuota } from "../hooks/useTranslationQuota";
import QuizRunner from "../components/QuizRunner";

export default function ReadingDetail() {
  const { id } = useParams();
  const navigate = useNavigate();
  const { article, questions, loading } = useReadingDetail(id ?? null);
  const [phase, setPhase] = useState<"read" | "quiz">("read");

  // tap-to-add-vocab popover
  const { sets } = useVocabSets();
  const [activeSetId, setActiveSetId] = useState<string | null>(null);
  const { addWord } = useVocabWords(activeSetId);
  const [selectedWord, setSelectedWord] = useState<string | null>(null);
  const [meaningInput, setMeaningInput] = useState("");
  const { canTranslate, remaining, recordUsage, limit } = useTranslationQuota();

  useEffect(() => {
    if (sets.length > 0 && !activeSetId) setActiveSetId(sets[0].id);
  }, [sets, activeSetId]);

  function handleWordClick(word: string) {
    if (!canTranslate) {
      alert(`ใช้โควตาแปลคำวันนี้ครบ ${limit} ครั้งแล้ว อัปเกรดเป็น Pro เพื่อแปลไม่จำกัด`);
      return;
    }
    setSelectedWord(word.replace(/[^\wก-๙'-]/g, ""));
    setMeaningInput("");
  }

  async function saveWord() {
    if (!selectedWord || !meaningInput.trim() || !activeSetId) return;
    await addWord({
      word: selectedWord,
      meaning: meaningInput.trim(),
      example: null,
      pos: null,
      syllables: null,
      grammar_tag: null,
    });
    await recordUsage();
    setSelectedWord(null);
  }

  if (loading) return <div className="p-10 text-gray-400">กำลังโหลด...</div>;
  if (!article) return <div className="p-10 text-gray-400">ไม่พบบทความ</div>;

  return (
    <div className="p-10 max-w-3xl">
      <button onClick={() => navigate("/reading")} className="text-sm text-grove-600 mb-4">
        ← กลับ
      </button>
      <h1 className="text-2xl font-bold text-grove-800 mb-4">{article.title}</h1>

      {phase === "read" && (
        <>
          {sets.length > 0 && (
            <div className="mb-3 text-xs text-gray-500 flex items-center gap-2">
              แตะคำที่ไม่รู้จักเพื่อเพิ่มลงชุด
              {remaining !== Infinity && (
                <span className="text-grove-500">(เหลือ {remaining}/{limit} ครั้งวันนี้)</span>
              )}
              <select
                value={activeSetId ?? ""}
                onChange={(e) => setActiveSetId(e.target.value)}
                className="border border-grove-200 rounded px-2 py-1"
              >
                {sets.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.name}
                  </option>
                ))}
              </select>
            </div>
          )}

          <div className="bg-white rounded-xl border border-grove-100 p-6 leading-relaxed text-gray-700 mb-6">
            {article.body.split(/(\s+)/).map((token, i) =>
              /^\s+$/.test(token) ? (
                token
              ) : (
                <span
                  key={i}
                  onClick={() => handleWordClick(token)}
                  className="cursor-pointer hover:bg-grove-100 rounded px-0.5"
                >
                  {token}
                </span>
              )
            )}
          </div>

          {selectedWord && (
            <div className="fixed bottom-6 right-6 bg-white shadow-xl rounded-xl border border-grove-200 p-4 w-72">
              <div className="font-medium text-grove-800 mb-2">{selectedWord}</div>
              <input
                autoFocus
                value={meaningInput}
                onChange={(e) => setMeaningInput(e.target.value)}
                placeholder="ใส่คำแปล"
                className="border border-grove-200 rounded px-2 py-1.5 text-sm w-full mb-2"
              />
              <div className="flex gap-2 justify-end text-sm">
                <button onClick={() => setSelectedWord(null)} className="text-gray-400">
                  ยกเลิก
                </button>
                <button
                  onClick={saveWord}
                  className="bg-grove-600 text-white rounded px-3 py-1"
                >
                  เพิ่มลงชุด
                </button>
              </div>
            </div>
          )}

          <button
            onClick={() => setPhase("quiz")}
            className="bg-grove-600 hover:bg-grove-700 text-white rounded-lg px-5 py-2 text-sm"
          >
            เริ่มทำโจทย์ ({questions.length} ข้อ) →
          </button>
        </>
      )}

      {phase === "quiz" && (
        <QuizRunner
          activityType="reading"
          timeGoalSeconds={article.time_goal_seconds}
          questions={questions.map((q) => ({
            id: q.id,
            question: q.question,
            choices: q.choices,
            correctIndex: q.correct_index,
            skillTag: q.question_type,
            explanation: q.explanation,
          }))}
        />
      )}
    </div>
  );
}
