import { useParams, useNavigate } from "react-router-dom";
import { useEffect, useState } from "react";
import { useListeningDetail } from "../hooks/useListening";
import QuizRunner from "../components/QuizRunner";

export default function ListeningDetail() {
  const { id } = useParams();
  const navigate = useNavigate();
  const { item, questions, loading } = useListeningDetail(id ?? null);
  const [phase, setPhase] = useState<"listen" | "quiz">("listen");
  const [rate, setRate] = useState(1);
  const [voices, setVoices] = useState<SpeechSynthesisVoice[]>([]);
  const [voiceIdx, setVoiceIdx] = useState(0);
  const [showScript, setShowScript] = useState(false);
  const [playing, setPlaying] = useState(false);

  useEffect(() => {
    function loadVoices() {
      const v = window.speechSynthesis?.getVoices().filter((v) => v.lang.startsWith("en")) ?? [];
      setVoices(v);
    }
    loadVoices();
    window.speechSynthesis?.addEventListener("voiceschanged", loadVoices);
    return () => window.speechSynthesis?.removeEventListener("voiceschanged", loadVoices);
  }, []);

  function play() {
    if (!item) return;
    window.speechSynthesis.cancel();
    const utter = new SpeechSynthesisUtterance(item.script);
    utter.rate = rate;
    if (voices[voiceIdx]) utter.voice = voices[voiceIdx];
    utter.onend = () => setPlaying(false);
    setPlaying(true);
    window.speechSynthesis.speak(utter);
  }

  function stop() {
    window.speechSynthesis.cancel();
    setPlaying(false);
  }

  if (loading) return <div className="p-10 text-gray-400">กำลังโหลด...</div>;
  if (!item) return <div className="p-10 text-gray-400">ไม่พบบทสนทนา</div>;

  return (
    <div className="p-10 max-w-3xl">
      <button onClick={() => navigate("/listening")} className="text-sm text-grove-600 mb-4">
        ← กลับ
      </button>
      <h1 className="text-2xl font-bold text-grove-800 mb-4">{item.title}</h1>

      {phase === "listen" && (
        <div className="bg-white rounded-xl border border-grove-100 p-6 mb-6">
          <div className="flex flex-wrap items-center gap-3 mb-4 text-sm">
            <button
              onClick={playing ? stop : play}
              className="bg-grove-600 hover:bg-grove-700 text-white rounded-lg px-4 py-2"
            >
              {playing ? "⏸ หยุด" : "▶ เล่นเสียง"}
            </button>
            <select
              value={voiceIdx}
              onChange={(e) => setVoiceIdx(Number(e.target.value))}
              className="border border-grove-200 rounded px-2 py-1.5"
            >
              {voices.map((v, i) => (
                <option key={v.name} value={i}>
                  {v.name} ({v.lang})
                </option>
              ))}
            </select>
            <select
              value={rate}
              onChange={(e) => setRate(Number(e.target.value))}
              className="border border-grove-200 rounded px-2 py-1.5"
            >
              <option value={0.75}>ช้า (0.75x)</option>
              <option value={1}>ปกติ (1x)</option>
              <option value={1.25}>เร็ว (1.25x)</option>
            </select>
            <button
              onClick={() => setShowScript((s) => !s)}
              className="text-grove-600 underline"
            >
              {showScript ? "ซ่อน script" : "แสดง script"}
            </button>
          </div>
          {showScript && (
            <div className="text-gray-600 text-sm leading-relaxed border-t border-grove-100 pt-4">
              {item.script}
            </div>
          )}
        </div>
      )}

      {phase === "listen" && (
        <button
          onClick={() => setPhase("quiz")}
          className="bg-grove-600 hover:bg-grove-700 text-white rounded-lg px-5 py-2 text-sm"
        >
          ตอบจากความจำ ({questions.length} ข้อ) →
        </button>
      )}

      {phase === "quiz" && (
        <QuizRunner
          activityType="listening"
          questions={questions.map((q) => ({
            id: q.id,
            question: q.question,
            choices: q.choices,
            correctIndex: q.correct_index,
            skillTag: "detail",
          }))}
        />
      )}
    </div>
  );
}
