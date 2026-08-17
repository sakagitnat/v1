import { useMemo, useState } from "react";
import type { VocabWord } from "../lib/types";

interface PlacedWord {
  word: string;
  meaning: string;
  row: number;
  col: number;
  dir: "across" | "down";
  number: number;
}

interface Cell {
  letter: string;
  number: number | null;
}

const GRID_SIZE = 20;

// Simplified crossword generator: place the longest word first in the
// center going across, then greedily try to intersect each subsequent word
// with any already-placed word that shares a letter. Not guaranteed optimal
// (a full solver is out of scope) but produces a valid, playable grid for
// typical vocab-set sizes (5-15 words).
function generateLayout(words: VocabWord[]): { placed: PlacedWord[]; grid: (Cell | null)[][] } {
  const grid: (Cell | null)[][] = Array.from({ length: GRID_SIZE }, () => Array(GRID_SIZE).fill(null));
  const placed: PlacedWord[] = [];
  let clueNumber = 1;

  const candidates = [...words]
    .filter((w) => /^[a-zA-Z]+$/.test(w.word))
    .sort((a, b) => b.word.length - a.word.length)
    .slice(0, 12);

  if (candidates.length === 0) return { placed, grid };

  function canPlace(word: string, row: number, col: number, dir: "across" | "down"): boolean {
    for (let i = 0; i < word.length; i++) {
      const r = dir === "down" ? row + i : row;
      const c = dir === "across" ? col + i : col;
      if (r < 0 || r >= GRID_SIZE || c < 0 || c >= GRID_SIZE) return false;
      const existing = grid[r][c];
      if (existing && existing.letter !== word[i].toUpperCase()) return false;
    }
    return true;
  }

  function place(word: VocabWord, row: number, col: number, dir: "across" | "down") {
    for (let i = 0; i < word.word.length; i++) {
      const r = dir === "down" ? row + i : row;
      const c = dir === "across" ? col + i : col;
      const isNew = !grid[r][c];
      grid[r][c] = { letter: word.word[i].toUpperCase(), number: isNew && i === 0 ? clueNumber : grid[r][c]?.number ?? null };
    }
    placed.push({ word: word.word.toUpperCase(), meaning: word.meaning, row, col, dir, number: clueNumber });
    clueNumber++;
  }

  const first = candidates[0];
  const startRow = Math.floor(GRID_SIZE / 2);
  const startCol = Math.floor((GRID_SIZE - first.word.length) / 2);
  place(first, startRow, startCol, "across");

  for (const word of candidates.slice(1)) {
    let bestPlacement: { row: number; col: number; dir: "across" | "down" } | null = null;

    outer: for (const pw of placed) {
      for (let i = 0; i < word.word.length; i++) {
        for (let j = 0; j < pw.word.length; j++) {
          if (word.word[i].toUpperCase() !== pw.word[j]) continue;
          const newDir = pw.dir === "across" ? "down" : "across";
          const actualRow = pw.dir === "across" ? pw.row - i : pw.row + j;
          const actualCol = pw.dir === "across" ? pw.col + j : pw.col - i;
          if (canPlace(word.word, actualRow, actualCol, newDir)) {
            bestPlacement = { row: actualRow, col: actualCol, dir: newDir };
            break outer;
          }
        }
      }
    }

    if (bestPlacement) {
      place(word, bestPlacement.row, bestPlacement.col, bestPlacement.dir);
    }
    // Words that don't intersect anywhere are skipped — expected for small
    // or unrelated vocab sets since not every word shares a letter.
  }

  return { placed, grid };
}

export function Crossword({ words }: { words: VocabWord[] }) {
  const { placed, grid } = useMemo(() => generateLayout(words), [words]);
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [checked, setChecked] = useState(false);

  const bounds = useMemo(() => {
    let minR = GRID_SIZE, maxR = 0, minC = GRID_SIZE, maxC = 0;
    for (let r = 0; r < GRID_SIZE; r++) {
      for (let c = 0; c < GRID_SIZE; c++) {
        if (grid[r][c]) {
          minR = Math.min(minR, r);
          maxR = Math.max(maxR, r);
          minC = Math.min(minC, c);
          maxC = Math.max(maxC, c);
        }
      }
    }
    return { minR, maxR, minC, maxC };
  }, [grid]);

  if (placed.length < 2) {
    return (
      <div className="text-gray-400 text-sm py-8 text-center">
        ต้องมีคำภาษาอังกฤษที่มีตัวอักษรร่วมกันอย่างน้อย 2 คำถึงจะสร้าง crossword ได้
      </div>
    );
  }

  function key(r: number, c: number) {
    return `${r}-${c}`;
  }

  let correctCount = 0;
  const total = placed.reduce((sum, p) => sum + p.word.length, 0);

  return (
    <div>
      <div className="overflow-auto mb-4">
        <div
          className="inline-grid gap-px bg-grove-200"
          style={{ gridTemplateColumns: `repeat(${bounds.maxC - bounds.minC + 1}, 28px)` }}
        >
          {Array.from({ length: bounds.maxR - bounds.minR + 1 }).map((_, ri) =>
            Array.from({ length: bounds.maxC - bounds.minC + 1 }).map((_, ci) => {
              const r = bounds.minR + ri;
              const c = bounds.minC + ci;
              const cell = grid[r][c];
              if (!cell) return <div key={key(r, c)} className="w-7 h-7 bg-transparent" />;
              const k = key(r, c);
              const isCorrect = checked && answers[k]?.toUpperCase() === cell.letter;
              const isWrong = checked && answers[k] && answers[k].toUpperCase() !== cell.letter;
              if (checked && isCorrect) correctCount++;
              return (
                <div key={k} className="relative w-7 h-7 bg-white">
                  {cell.number && (
                    <span className="absolute top-0 left-0.5 text-[8px] text-grove-400">{cell.number}</span>
                  )}
                  <input
                    maxLength={1}
                    value={answers[k] ?? ""}
                    onChange={(e) => setAnswers((prev) => ({ ...prev, [k]: e.target.value.slice(-1) }))}
                    disabled={checked}
                    className={`w-7 h-7 text-center text-sm font-medium uppercase outline-none border ${
                      isCorrect ? "bg-green-50 border-green-400" : isWrong ? "bg-red-50 border-red-400" : "border-grove-200"
                    }`}
                  />
                </div>
              );
            })
          )}
        </div>
      </div>

      <div className="grid grid-cols-2 gap-4 text-sm mb-4">
        <div>
          <div className="font-medium text-grove-700 mb-1">ตามแนวนอน (Across)</div>
          {placed.filter((p) => p.dir === "across").map((p) => (
            <div key={p.number} className="text-gray-500">
              {p.number}. {p.meaning}
            </div>
          ))}
        </div>
        <div>
          <div className="font-medium text-grove-700 mb-1">ตามแนวตั้ง (Down)</div>
          {placed.filter((p) => p.dir === "down").map((p) => (
            <div key={p.number} className="text-gray-500">
              {p.number}. {p.meaning}
            </div>
          ))}
        </div>
      </div>

      {!checked ? (
        <button
          onClick={() => setChecked(true)}
          className="bg-grove-600 hover:bg-grove-700 text-white rounded-lg px-4 py-2 text-sm"
        >
          ตรวจคำตอบ
        </button>
      ) : (
        <div className="text-sm font-medium text-grove-700">
          ถูก {correctCount}/{total} ช่อง
        </div>
      )}
    </div>
  );
}
