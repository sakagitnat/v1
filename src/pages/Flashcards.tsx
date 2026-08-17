import { useState } from "react";
import { Link } from "react-router-dom";
import { useVocabSets, useVocabWords } from "../hooks/useVocabSets";
import { usePro } from "../hooks/usePro";
import { LearnMode, MatchGame } from "../components/FlashcardGames";
import { Crossword } from "../components/Crossword";

type Mode = "list" | "learn" | "match" | "crossword" | "az";

export default function Flashcards() {
  const { sets, loading, createSet, renameSet, deleteSet, togglePublic, error: setsError } =
    useVocabSets();
  const [activeSetId, setActiveSetId] = useState<string | null>(null);
  const activeSet = sets.find((s) => s.id === activeSetId) ?? null;
  const { words, addWord, updateWord, deleteWord, error: wordsError } = useVocabWords(activeSetId);
  const { isPro } = usePro();

  const [mode, setMode] = useState<Mode>("list");
  const [newSetName, setNewSetName] = useState("");
  const [form, setForm] = useState({ word: "", meaning: "", example: "", pos: "" });

  async function handleCreateSet() {
    if (!newSetName.trim()) return;
    const set = await createSet(newSetName.trim());
    setNewSetName("");
    if (set) setActiveSetId(set.id);
  }

  async function handleAddWord() {
    if (!form.word.trim() || !form.meaning.trim()) return;
    await addWord({
      word: form.word.trim(),
      meaning: form.meaning.trim(),
      example: form.example.trim() || null,
      pos: form.pos.trim() || null,
      syllables: null,
      grammar_tag: null,
    });
    setForm({ word: "", meaning: "", example: "", pos: "" });
  }

  return (
    <div className="p-10 max-w-4xl">
      <h1 className="text-2xl font-bold text-grove-800 mb-1">คำศัพท์</h1>
      <p className="text-gray-500 mb-6">
        มีได้หลายชุดพร้อมกัน แต่ละชุดสูงสุด 200 คำ — สลับชุดได้ทันทีด้านล่าง
      </p>

      {/* Deck switcher */}
      <div className="flex flex-wrap gap-2 mb-4">
        {loading && <span className="text-sm text-gray-400">กำลังโหลด...</span>}
        {sets.map((s) => (
          <button
            key={s.id}
            onClick={() => setActiveSetId(s.id)}
            className={`px-3 py-1.5 rounded-full text-sm border ${
              activeSetId === s.id
                ? "bg-grove-600 text-white border-grove-600"
                : "bg-white text-grove-700 border-grove-200 hover:border-grove-400"
            }`}
          >
            {s.name} {s.is_public && "🌐"}
          </button>
        ))}
      </div>

      {/* Create new set */}
      <div className="flex gap-2 mb-8">
        <input
          value={newSetName}
          onChange={(e) => setNewSetName(e.target.value)}
          placeholder="ชื่อชุดใหม่ เช่น TOEIC Unit 1"
          className="border border-grove-200 rounded-lg px-3 py-2 text-sm flex-1"
        />
        <button
          onClick={handleCreateSet}
          className="bg-grove-600 hover:bg-grove-700 text-white rounded-lg px-4 py-2 text-sm"
        >
          + สร้างชุดใหม่
        </button>
      </div>

      {(setsError || wordsError) && (
        <div className="text-red-600 text-sm mb-4">{setsError ?? wordsError}</div>
      )}

      {!activeSet && sets.length === 0 && !loading && (
        <div className="text-center py-16 text-gray-400">
          ยังไม่มีชุดคำศัพท์ — สร้างชุดแรกด้านบน หรือไปดูคลังสาธารณะ
        </div>
      )}

      {activeSet && (
        <div className="bg-white rounded-xl border border-grove-100 p-6">
          <div className="flex items-center justify-between mb-4">
            <div>
              <input
                value={activeSet.name}
                onChange={(e) => renameSet(activeSet.id, e.target.value)}
                className="font-semibold text-lg text-grove-800 border-b border-transparent focus:border-grove-300 outline-none"
              />
              <div className="text-xs text-gray-400 mt-1">{words.length} / 200 คำ</div>
            </div>
            <div className="flex gap-3 items-center text-sm">
              {isPro ? (
                <label className="flex items-center gap-1.5 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={activeSet.is_public}
                    onChange={(e) => togglePublic(activeSet.id, e.target.checked)}
                  />
                  แชร์สู่คลังสาธารณะ
                </label>
              ) : (
                <Link to="/pro" className="text-yellow-600 text-xs">
                  ⭐ อัปเกรด Pro เพื่อแชร์สาธารณะ
                </Link>
              )}
              <button
                onClick={() => {
                  deleteSet(activeSet.id);
                  setActiveSetId(null);
                }}
                className="text-red-500 hover:underline"
              >
                ลบชุดนี้
              </button>
            </div>
          </div>

          {/* Mode tabs */}
          <div className="flex gap-2 mb-4">
            {(
              [
                ["list", "รายการ"],
                ["learn", "ท่องคำ"],
                ["match", "จับคู่"],
                ["crossword", "Crossword"],
                ["az", "เรียง a-z"],
              ] as [Mode, string][]
            ).map(([key, label]) => (
              <button
                key={key}
                onClick={() => setMode(key)}
                className={`px-3 py-1 rounded-full text-xs border ${
                  mode === key ? "bg-grove-600 text-white border-grove-600" : "border-grove-200 text-grove-600"
                }`}
              >
                {label}
              </button>
            ))}
          </div>

          {mode === "list" && (
            <>
              {/* Add word form */}
              <div className="grid grid-cols-2 gap-2 mb-4 bg-grove-50 p-4 rounded-lg">
                <input
                  placeholder="คำศัพท์"
                  value={form.word}
                  onChange={(e) => setForm({ ...form, word: e.target.value })}
                  className="border border-grove-200 rounded px-2 py-1.5 text-sm"
                />
                <input
                  placeholder="คำแปล"
                  value={form.meaning}
                  onChange={(e) => setForm({ ...form, meaning: e.target.value })}
                  className="border border-grove-200 rounded px-2 py-1.5 text-sm"
                />
                <input
                  placeholder="Part of speech (เช่น n., v.)"
                  value={form.pos}
                  onChange={(e) => setForm({ ...form, pos: e.target.value })}
                  className="border border-grove-200 rounded px-2 py-1.5 text-sm"
                />
                <input
                  placeholder="ประโยคตัวอย่าง (ถ้ามี)"
                  value={form.example}
                  onChange={(e) => setForm({ ...form, example: e.target.value })}
                  className="border border-grove-200 rounded px-2 py-1.5 text-sm"
                />
                <button
                  onClick={handleAddWord}
                  className="col-span-2 bg-grove-600 hover:bg-grove-700 text-white rounded py-1.5 text-sm"
                >
                  + เพิ่มคำ
                </button>
              </div>

              <div className="divide-y divide-grove-100">
                {words.map((w) => (
                  <div key={w.id} className="py-2 flex items-center justify-between text-sm">
                    <div>
                      <span className="font-medium text-grove-800">{w.word}</span>
                      {w.pos && <span className="text-gray-400 ml-1">({w.pos})</span>}
                      <span className="text-gray-500 ml-2">— {w.meaning}</span>
                      {w.example && <div className="text-xs text-gray-400 italic">{w.example}</div>}
                    </div>
                    <button
                      onClick={() => deleteWord(w.id)}
                      className="text-red-400 hover:text-red-600 text-xs"
                    >
                      ลบ
                    </button>
                  </div>
                ))}
                {words.length === 0 && (
                  <div className="text-center text-gray-400 text-sm py-8">ยังไม่มีคำในชุดนี้</div>
                )}
              </div>
            </>
          )}

          {mode === "learn" && <LearnMode words={words} />}
          {mode === "match" && <MatchGame words={words} />}
          {mode === "crossword" && <Crossword words={words} />}
          {mode === "az" && (
            <div className="space-y-4">
              {Object.entries(
                words
                  .slice()
                  .sort((a, b) => a.word.localeCompare(b.word))
                  .reduce<Record<string, typeof words>>((groups, w) => {
                    const letter = w.word[0]?.toUpperCase() ?? "#";
                    (groups[letter] ??= []).push(w);
                    return groups;
                  }, {})
              ).map(([letter, group]) => (
                <div key={letter}>
                  <div className="text-xs font-bold text-grove-500 mb-1">{letter}</div>
                  <div className="divide-y divide-grove-100">
                    {group.map((w) => (
                      <div key={w.id} className="py-1.5 text-sm">
                        <span className="font-medium text-grove-800">{w.word}</span>
                        <span className="text-gray-500 ml-2">— {w.meaning}</span>
                      </div>
                    ))}
                  </div>
                </div>
              ))}
              {words.length === 0 && (
                <div className="text-center text-gray-400 text-sm py-8">ยังไม่มีคำในชุดนี้</div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
