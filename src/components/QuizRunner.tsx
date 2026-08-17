import { useEffect, useState } from "react";
import { useAuth } from "../contexts/AuthContext";
import { logAttempt, ActivityType } from "../lib/attempts";
import type { SkillTag } from "../lib/types";

interface QuizQuestion {
  id: string;
  question: string;
  choices: string[];
  correctIndex: number;
  skillTag: SkillTag;
  explanation?: string | null;
}

export default function QuizRunner({
  questions,
  activityType,
  timeGoalSeconds,
  onFinish,
}: {
  questions: QuizQuestion[];
  activityType: ActivityType;
  timeGoalSeconds?: number;
  onFinish?: (score: number, total: number) => void;
}) {
  const { user } = useAuth();
  const [index, setIndex] = useState(0);
  const [selected, setSelected] = useState<number | null>(null);
  const [revealed, setRevealed] = useState(false);
  const [score, setScore] = useState(0);
  const [startedAt] = useState(Date.now());
  const [done, setDone] = useState(false);
  const [remaining, setRemaining] = useState(timeGoalSeconds ?? null);

  useEffect(() => {
    if (remaining === null || done) return;
    if (remaining <= 0) {
      setDone(true);
      return;
    }
    const t = setTimeout(() => setRemaining((r) => (r !== null ? r - 1 : r)), 1000);
    return () => clearTimeout(t);
  }, [remaining, done]);

  const current = questions[index];

  async function submitAnswer() {
    if (selected === null || !current || !user) return;
    const correct = selected === current.correctIndex;
    if (correct) setScore((s) => s + 1);
    setRevealed(true);
    await logAttempt({
      userId: user.id,
      activityType,
      itemId: current.id,
      skillTag: current.skillTag,
      correct,
      timeSpentSeconds: Math.round((Date.now() - startedAt) / 1000),
    });
  }

  function next() {
    setRevealed(false);
    setSelected(null);
    if (index + 1 >= questions.length) {
      setDone(true);
      onFinish?.(score, questions.length);
    } else {
      setIndex(index + 1);
    }
  }

  if (questions.length === 0) {
    return <div className="text-gray-400 text-sm py-8 text-center">ไม่มีโจทย์สำหรับเนื้อหานี้</div>;
  }

  if (done) {
    return (
      <div className="text-center py-10">
        <div className="text-3xl font-bold text-grove-700 mb-1">
          {score} / {questions.length}
        </div>
        <div className="text-gray-500">คะแนนของคุณ</div>
      </div>
    );
  }

  return (
    <div>
      <div className="flex justify-between text-xs text-gray-400 mb-3">
        <span>
          ข้อ {index + 1} / {questions.length}
        </span>
        {remaining !== null && (
          <span className={remaining < 30 ? "text-red-500 font-medium" : ""}>
            ⏱ {Math.floor(remaining / 60)}:{String(remaining % 60).padStart(2, "0")}
          </span>
        )}
      </div>
      <div className="bg-white rounded-xl border border-grove-100 p-6">
        <div className="font-medium text-grove-800 mb-4">{current.question}</div>
        <div className="space-y-2">
          {current.choices.map((choice, i) => {
            const isCorrect = revealed && i === current.correctIndex;
            const isWrongSelected = revealed && selected === i && i !== current.correctIndex;
            return (
              <button
                key={i}
                disabled={revealed}
                onClick={() => setSelected(i)}
                className={`w-full text-left px-4 py-2.5 rounded-lg border text-sm transition ${
                  isCorrect
                    ? "bg-green-50 border-green-400 text-green-800"
                    : isWrongSelected
                    ? "bg-red-50 border-red-400 text-red-700"
                    : selected === i
                    ? "border-grove-500 bg-grove-50"
                    : "border-grove-200 hover:border-grove-400"
                }`}
              >
                {choice}
              </button>
            );
          })}
        </div>
        {revealed && current.explanation && (
          <div className="mt-3 text-xs text-gray-500 bg-grove-50 rounded p-3">
            {current.explanation}
          </div>
        )}
        <div className="mt-5 flex justify-end">
          {!revealed ? (
            <button
              disabled={selected === null}
              onClick={submitAnswer}
              className="bg-grove-600 hover:bg-grove-700 disabled:opacity-40 text-white rounded-lg px-5 py-2 text-sm"
            >
              ตอบ
            </button>
          ) : (
            <button
              onClick={next}
              className="bg-grove-600 hover:bg-grove-700 text-white rounded-lg px-5 py-2 text-sm"
            >
              {index + 1 >= questions.length ? "ดูผล" : "ข้อถัดไป"}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
