import { Link } from "react-router-dom";
import { useState } from "react";
import { supabase } from "../lib/supabaseClient";
import { useAuth } from "../contexts/AuthContext";
import { extractTextFromPdf, parseVocabLines, ParsedVocabLine } from "../lib/pdfImport";

const CARDS = [
  { to: "/flashcards", label: "คำศัพท์", icon: "🔤" },
  { to: "/reading/add", label: "บทความ + โจทย์", icon: "📖" },
  { to: "/listening/add", label: "บทสนทนา + โจทย์", icon: "🎧" },
  { to: "/writing", label: "เติมคำ / เรียงประโยค", icon: "✍️" },
  { to: "/skill-banks", label: "Skill Bank", icon: "📦" },
];

export default function AddContentHub() {
  const { user } = useAuth();
  const [jsonText, setJsonText] = useState("");
  const [status, setStatus] = useState<string | null>(null);

  async function importJson() {
    if (!user) return;
    setStatus(null);
    try {
      const parsed = JSON.parse(jsonText);
      let count = 0;

      if (Array.isArray(parsed.vocab)) {
        const { data: set } = await supabase
          .from("vocab_sets")
          .insert({ owner_id: user.id, name: "นำเข้าจาก JSON" })
          .select()
          .single();
        if (set) {
          await supabase.from("vocab_words").insert(
            parsed.vocab.map((w: any) => ({
              set_id: set.id,
              word: w.word,
              meaning: w.meaning,
              pos: w.pos ?? null,
              example: w.example ?? null,
              syllables: w.syllables ?? null,
              grammar_tag: w.grammar_tag ?? null,
            }))
          );
          count += parsed.vocab.length;
        }
      }

      if (Array.isArray(parsed.articles)) {
        for (const a of parsed.articles) {
          const { data: article } = await supabase
            .from("reading_articles")
            .insert({
              owner_id: user.id,
              title: a.title,
              category: a.category ?? "general",
              body: a.body,
              time_goal_seconds: a.time_goal_seconds ?? 300,
            })
            .select()
            .single();
          if (article && Array.isArray(a.questions)) {
            await supabase.from("reading_questions").insert(
              a.questions.map((q: any) => ({
                article_id: article.id,
                question: q.question,
                choices: q.choices,
                correct_index: q.correct_index,
                question_type: q.question_type ?? "detail",
                explanation: q.explanation ?? null,
              }))
            );
          }
          count += 1;
        }
      }

      if (Array.isArray(parsed.conversations)) {
        for (const c of parsed.conversations) {
          const { data: item } = await supabase
            .from("listening_items")
            .insert({ owner_id: user.id, title: c.title, script: c.script })
            .select()
            .single();
          if (item && Array.isArray(c.questions)) {
            await supabase.from("listening_questions").insert(
              c.questions.map((q: any) => ({
                listening_id: item.id,
                question: q.question,
                choices: q.choices,
                correct_index: q.correct_index,
              }))
            );
          }
          count += 1;
        }
      }

      setStatus(`นำเข้าสำเร็จ (${count} รายการ)`);
      setJsonText("");
    } catch (e: any) {
      setStatus(`เกิดข้อผิดพลาด: ${e.message}`);
    }
  }

  return (
    <div className="p-10 max-w-3xl">
      <h1 className="text-2xl font-bold text-grove-800 mb-6">เพิ่มเนื้อหา</h1>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-10">
        {CARDS.map((c) => (
          <Link
            key={c.to}
            to={c.to}
            className="bg-white rounded-xl border border-grove-100 p-5 text-center hover:shadow-md transition"
          >
            <div className="text-2xl mb-1">{c.icon}</div>
            <div className="text-sm font-medium text-grove-800">{c.label}</div>
          </Link>
        ))}
      </div>

      <div className="bg-white rounded-xl border border-grove-100 p-5 mb-6">
        <h2 className="font-semibold text-grove-800 mb-1">นำเข้าจาก JSON</h2>
        <p className="text-xs text-gray-400 mb-3">
          รองรับคีย์ <code>vocab</code>, <code>articles</code>, <code>conversations</code> พร้อมกันในไฟล์เดียว
        </p>
        <textarea
          value={jsonText}
          onChange={(e) => setJsonText(e.target.value)}
          rows={8}
          placeholder='{"vocab": [{"word": "apple", "meaning": "แอปเปิ้ล"}], "articles": [...], "conversations": [...]}'
          className="border border-grove-200 rounded-lg px-3 py-2 text-sm w-full font-mono"
        />
        {status && <div className="text-sm text-grove-600 mt-2">{status}</div>}
        <button
          onClick={importJson}
          disabled={!jsonText.trim()}
          className="bg-grove-600 hover:bg-grove-700 disabled:opacity-40 text-white rounded-lg px-4 py-2 text-sm mt-3"
        >
          นำเข้า
        </button>
      </div>

      <PdfImportSection />
    </div>
  );
}

function PdfImportSection() {
  const { user } = useAuth();
  const [fileName, setFileName] = useState<string | null>(null);
  const [rawText, setRawText] = useState("");
  const [vocabRows, setVocabRows] = useState<ParsedVocabLine[]>([]);
  const [extracting, setExtracting] = useState(false);
  const [status, setStatus] = useState<string | null>(null);

  async function handleFile(file: File) {
    setFileName(file.name);
    setExtracting(true);
    setStatus(null);
    try {
      const text = await extractTextFromPdf(file);
      setRawText(text);
      setVocabRows(parseVocabLines(text));
    } catch (e: any) {
      setStatus(`อ่านไฟล์ไม่สำเร็จ: ${e.message}`);
    } finally {
      setExtracting(false);
    }
  }

  async function importAsVocabSet() {
    if (!user || vocabRows.length === 0) return;
    const { data: set } = await supabase
      .from("vocab_sets")
      .insert({ owner_id: user.id, name: fileName ? `นำเข้าจาก ${fileName}` : "นำเข้าจาก PDF" })
      .select()
      .single();
    if (!set) return;
    await supabase.from("vocab_words").insert(
      vocabRows.slice(0, 200).map((r) => ({ set_id: set.id, word: r.word, meaning: r.meaning }))
    );
    setStatus(`นำเข้าคำศัพท์ ${Math.min(vocabRows.length, 200)} คำเป็นชุดใหม่แล้ว`);
  }

  async function importAsReadingArticle() {
    if (!user || !rawText.trim()) return;
    await supabase.from("reading_articles").insert({
      owner_id: user.id,
      title: fileName ?? "บทความจาก PDF",
      category: "general",
      body: rawText.slice(0, 20000),
      time_goal_seconds: 300,
    });
    setStatus("นำเข้าเป็นบทความ Reading แล้ว (ไปเพิ่มโจทย์ต่อได้ที่หน้า Reading)");
  }

  function removeRow(i: number) {
    setVocabRows((prev) => prev.filter((_, idx) => idx !== i));
  }

  return (
    <div className="bg-white rounded-xl border border-grove-100 p-5">
      <h2 className="font-semibold text-grove-800 mb-1">นำเข้าจาก PDF</h2>
      <p className="text-xs text-gray-400 mb-3">
        ระบบจะดึงข้อความออกมาก่อน แล้วพยายามจับคู่ "คำ - ความหมาย" อัตโนมัติ (รูปแบบ word - meaning /
        word: meaning / เว้นวรรคสองครั้งขึ้นไป) — ตรวจสอบก่อนบันทึกเสมอ เพราะ PDF แต่ละไฟล์จัดรูปแบบไม่เหมือนกัน
      </p>
      <input
        type="file"
        accept="application/pdf"
        onChange={(e) => e.target.files?.[0] && handleFile(e.target.files[0])}
        className="text-sm mb-3"
      />
      {extracting && <div className="text-sm text-gray-400">กำลังอ่านไฟล์...</div>}

      {!extracting && vocabRows.length > 0 && (
        <div className="mb-4">
          <div className="text-sm font-medium text-grove-700 mb-2">
            พบคำศัพท์ที่น่าจะใช่ {vocabRows.length} คู่ (ลบทิ้งได้ถ้าไม่ถูกต้อง)
          </div>
          <div className="max-h-64 overflow-y-auto border border-grove-100 rounded-lg divide-y divide-grove-100">
            {vocabRows.map((r, i) => (
              <div key={i} className="flex items-center justify-between px-3 py-1.5 text-sm">
                <span>
                  <b className="text-grove-800">{r.word}</b> — {r.meaning}
                </span>
                <button onClick={() => removeRow(i)} className="text-red-400 text-xs">
                  ลบ
                </button>
              </div>
            ))}
          </div>
          <button
            onClick={importAsVocabSet}
            className="bg-grove-600 hover:bg-grove-700 text-white rounded-lg px-4 py-2 text-sm mt-3"
          >
            นำเข้าเป็นชุดคำศัพท์ใหม่ ({vocabRows.length} คำ)
          </button>
        </div>
      )}

      {!extracting && rawText && (
        <div>
          <div className="text-sm font-medium text-grove-700 mb-2">หรือนำเข้าข้อความทั้งหมดเป็นบทความ Reading</div>
          <textarea
            value={rawText}
            onChange={(e) => setRawText(e.target.value)}
            rows={6}
            className="border border-grove-200 rounded-lg px-3 py-2 text-sm w-full font-mono mb-2"
          />
          <button
            onClick={importAsReadingArticle}
            className="bg-grove-100 hover:bg-grove-200 text-grove-800 rounded-lg px-4 py-2 text-sm"
          >
            นำเข้าเป็นบทความ Reading
          </button>
        </div>
      )}

      {status && <div className="text-sm text-grove-600 mt-3">{status}</div>}
    </div>
  );
}
