import { useEffect, useMemo, useState } from "react";
import type { VocabWord } from "../lib/types";
import { useAuth } from "../contexts/AuthContext";
import { awardBadgeIfMissing } from "../lib/gamification";

// ---------------- Learn mode: unlock words in batches of 5/10 ----------------
export function LearnMode({ words }: { words: VocabWord[] }) {
  const [batchSize, setBatchSize] = useState<5 | 10>(5);
  const [unlockedCount, setUnlockedCount] = useState(batchSize);
  const [index, setIndex] = useState(0);
  const [flipped, setFlipped] = useState(false);

  const unlocked = words.slice(0, unlockedCount);
  const current = unlocked[index];

  useEffect(() => {
    setUnlockedCount(batchSize);
    setIndex(0);
  }, [batchSize]);

  if (words.length === 0) return <div className="text-gray-400 text-sm py-8 text-center">ยังไม่มีคำในชุดนี้</div>;

  return (
    <div>
      <div className="flex items-center gap-3 mb-4 text-sm">
        <span className="text-gray-400">ปลดล็อกทีละ</span>
        {([5, 10] as const).map((n) => (
          <button
            key={n}
            onClick={() => setBatchSize(n)}
            className={`px-3 py-1 rounded-full border ${
              batchSize === n ? "bg-grove-600 text-white border-grove-600" : "border-grove-200"
            }`}
          >
            {n} คำ
          </button>
        ))}
        <span className="text-gray-400 ml-auto">
          ปลดล็อกแล้ว {Math.min(unlockedCount, words.length)}/{words.length}
        </span>
      </div>

      {current && (
        <div
          onClick={() => setFlipped((f) => !f)}
          className="bg-white rounded-xl border border-grove-100 p-10 text-center cursor-pointer min-h-[160px] flex items-center justify-center"
        >
          <div>
            <div className="text-xl font-semibold text-grove-800">
              {flipped ? current.meaning : current.word}
            </div>
            {flipped && current.example && (
              <div className="text-sm text-gray-400 mt-2 italic">{current.example}</div>
            )}
            <div className="text-xs text-gray-300 mt-3">แตะเพื่อพลิกการ์ด</div>
          </div>
        </div>
      )}

      <div className="flex justify-between mt-4">
        <button
          onClick={() => {
            setFlipped(false);
            setIndex((i) => Math.max(0, i - 1));
          }}
          disabled={index === 0}
          className="text-sm text-grove-600 disabled:opacity-30"
        >
          ← คำก่อนหน้า
        </button>
        <button
          onClick={() => {
            setFlipped(false);
            if (index + 1 >= unlocked.length && unlockedCount < words.length) {
              setUnlockedCount((c) => Math.min(words.length, c + batchSize));
            }
            setIndex((i) => Math.min(words.length - 1, i + 1));
          }}
          className="text-sm text-grove-600"
        >
          คำถัดไป →
        </button>
      </div>
    </div>
  );
}

// ---------------- Match game: word-to-meaning pairs, lives + combo ----------------
function shuffle<T>(arr: T[]): T[] {
  const a = [...arr];
  for (let i = a.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [a[i], a[j]] = [a[j], a[i]];
  }
  return a;
}

export function MatchGame({ words }: { words: VocabWord[] }) {
  const { user } = useAuth();
  const roundWords = useMemo(() => shuffle(words).slice(0, 8), [words]);
  const [wordTiles, setWordTiles] = useState<VocabWord[]>([]);
  const [meaningTiles, setMeaningTiles] = useState<VocabWord[]>([]);
  const [selectedWord, setSelectedWord] = useState<string | null>(null);
  const [selectedMeaning, setSelectedMeaning] = useState<string | null>(null);
  const [matched, setMatched] = useState<Set<string>>(new Set());
  const [lives, setLives] = useState(3);
  const [combo, setCombo] = useState(0);
  const [maxCombo, setMaxCombo] = useState(0);
  const [gameOver, setGameOver] = useState(false);

  useEffect(() => {
    setWordTiles(shuffle(roundWords));
    setMeaningTiles(shuffle(roundWords));
  }, [roundWords]);

  useEffect(() => {
    if (selectedWord && selectedMeaning) {
      const correct = selectedWord === selectedMeaning;
      if (correct) {
        setMatched((prev) => new Set(prev).add(selectedWord));
        const newCombo = combo + 1;
        setCombo(newCombo);
        setMaxCombo((m) => Math.max(m, newCombo));
        if (newCombo >= 8 && user) awardBadgeIfMissing(user.id, "combo_king_8x");
      } else {
        setLives((l) => {
          const next = l - 1;
          if (next <= 0) setGameOver(true);
          return next;
        });
        setCombo(0);
      }
      setTimeout(() => {
        setSelectedWord(null);
        setSelectedMeaning(null);
      }, 400);
    }
  }, [selectedWord, selectedMeaning]);

  if (words.length < 4) {
    return <div className="text-gray-400 text-sm py-8 text-center">ต้องมีอย่างน้อย 4 คำในชุดถึงจะเล่นได้</div>;
  }

  if (gameOver) {
    return (
      <div className="text-center py-10">
        <div className="text-xl font-bold text-red-500 mb-1">หมดชีวิต 💔</div>
        <div className="text-gray-500">คอมโบสูงสุด {maxCombo}x</div>
      </div>
    );
  }

  if (matched.size === roundWords.length) {
    return (
      <div className="text-center py-10">
        <div className="text-xl font-bold text-green-600 mb-1">จับคู่ครบแล้ว! 🎉</div>
        <div className="text-gray-500">คอมโบสูงสุด {maxCombo}x</div>
      </div>
    );
  }

  return (
    <div>
      <div className="flex justify-between text-sm mb-3">
        <span>{"❤️".repeat(lives)}</span>
        <span className="text-grove-600 font-medium">คอมโบ {combo}x</span>
      </div>
      <div className="grid grid-cols-2 gap-4">
        <div className="space-y-2">
          {wordTiles
            .filter((w) => !matched.has(w.id))
            .map((w) => (
              <button
                key={w.id}
                onClick={() => setSelectedWord(w.id)}
                className={`w-full text-left px-3 py-2 rounded-lg border text-sm ${
                  selectedWord === w.id ? "border-grove-500 bg-grove-50" : "border-grove-200"
                }`}
              >
                {w.word}
              </button>
            ))}
        </div>
        <div className="space-y-2">
          {meaningTiles
            .filter((w) => !matched.has(w.id))
            .map((w) => (
              <button
                key={w.id}
                onClick={() => setSelectedMeaning(w.id)}
                className={`w-full text-left px-3 py-2 rounded-lg border text-sm ${
                  selectedMeaning === w.id ? "border-grove-500 bg-grove-50" : "border-grove-200"
                }`}
              >
                {w.meaning}
              </button>
            ))}
        </div>
      </div>
    </div>
  );
}
