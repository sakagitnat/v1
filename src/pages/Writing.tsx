import { useState } from "react";
import { useAuth } from "../contexts/AuthContext";
import { useFillBlankList, useReorderList, FillBlankItem, ReorderItem } from "../hooks/useWriting";
import { POS_DRILL, POS_LABEL, POSQuestion } from "../lib/posDrill";
import { logAttempt } from "../lib/attempts";

type Tab = "fill" | "reorder" | "pos";

export default function Writing() {
  const [tab, setTab] = useState<Tab>("fill");
  return (
    <div className="p-10 max-w-3xl">
      <h1 className="text-2xl font-bold text-grove-800 mb-4">Writing</h1>
      <div className="flex gap-2 mb-6">
        {(
          [
            ["fill", "เติมคำ"],
            ["reorder", "เรียงประโยค"],
            ["pos", "ระบุชนิดคำ"],
          ] as [Tab, string][]
        ).map(([key, label]) => (
          <button
            key={key}
            onClick={() => setTab(key)}
            className={`px-4 py-1.5 rounded-full text-sm border ${
              tab === key
                ? "bg-grove-600 text-white border-grove-600"
                : "bg-white text-grove-700 border-grove-200"
            }`}
          >
            {label}
          </button>
        ))}
      </div>
      {tab === "fill" && <FillBlankTab />}
      {tab === "reorder" && <ReorderTab />}
      {tab === "pos" && <PosTab />}
    </div>
  );
}

// ---------------- Fill in the blank ----------------
function FillBlankTab() {
  const { items, loading, createItem, deleteItem } = useFillBlankList();
  const [active, setActive] = useState<FillBlankItem | null>(null);
  const [addingMode, setAddingMode] = useState(false);

  if (active) return <FillBlankRunner item={active} onDone={() => setActive(null)} />;
  if (addingMode) return <AddFillBlank onDone={() => setAddingMode(false)} onCreate={createItem} />;

  return (
    <div>
      <button
        onClick={() => setAddingMode(true)}
        className="bg-grove-600 hover:bg-grove-700 text-white rounded-lg px-4 py-2 text-sm mb-4"
      >
        + เพิ่มโจทย์เติมคำ
      </button>
      {loading && <div className="text-gray-400 text-sm">กำลังโหลด...</div>}
      {!loading && items.length === 0 && (
        <div className="text-gray-400 text-sm py-8 text-center">ยังไม่มีโจทย์เติมคำ</div>
      )}
      <div className="space-y-2">
        {items.map((it) => (
          <div
            key={it.id}
            className="bg-white rounded-xl border border-grove-100 p-4 flex justify-between items-center"
          >
            <button onClick={() => setActive(it)} className="text-left flex-1 text-sm text-grove-800 truncate">
              {it.passage.slice(0, 80)}...
            </button>
            <button onClick={() => deleteItem(it.id)} className="text-red-400 text-xs ml-3">
              ลบ
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}

function AddFillBlank({
  onDone,
  onCreate,
}: {
  onDone: () => void;
  onCreate: (passage: string, blanks: FillBlankItem["blanks"]) => Promise<any>;
}) {
  const [passage, setPassage] = useState("");
  const [blanks, setBlanks] = useState<FillBlankItem["blanks"]>([
    { id: "blank_1", choices: ["", "", "", ""], correct_index: 0 },
  ]);

  return (
    <div className="bg-white rounded-xl border border-grove-100 p-5 space-y-3">
      <p className="text-xs text-gray-400">
        ใช้ {"{{blank_1}}"}, {"{{blank_2}}"} ฯลฯ ในเนื้อหาแทนตำแหน่งช่องว่าง
      </p>
      <textarea
        value={passage}
        onChange={(e) => setPassage(e.target.value)}
        rows={5}
        placeholder="เนื้อหาบทความ พร้อม {{blank_1}}"
        className="border border-grove-200 rounded-lg px-3 py-2 text-sm w-full"
      />
      {blanks.map((b, bi) => (
        <div key={b.id} className="border-t border-grove-100 pt-3">
          <div className="text-xs text-gray-400 mb-1">{b.id}</div>
          {b.choices.map((c, ci) => (
            <div key={ci} className="flex items-center gap-2 mb-1">
              <input
                type="radio"
                checked={b.correct_index === ci}
                onChange={() =>
                  setBlanks((prev) =>
                    prev.map((x, i) => (i === bi ? { ...x, correct_index: ci } : x))
                  )
                }
              />
              <input
                value={c}
                onChange={(e) =>
                  setBlanks((prev) =>
                    prev.map((x, i) =>
                      i === bi
                        ? { ...x, choices: x.choices.map((cc, cci) => (cci === ci ? e.target.value : cc)) }
                        : x
                    )
                  )
                }
                placeholder={`ตัวเลือก ${ci + 1}`}
                className="border border-grove-200 rounded px-2 py-1 text-sm flex-1"
              />
            </div>
          ))}
        </div>
      ))}
      <button
        onClick={() =>
          setBlanks((prev) => [
            ...prev,
            { id: `blank_${prev.length + 1}`, choices: ["", "", "", ""], correct_index: 0 },
          ])
        }
        className="text-grove-600 text-sm underline"
      >
        + เพิ่มช่องว่าง
      </button>
      <div className="flex gap-2">
        <button onClick={onDone} className="text-gray-400 text-sm">
          ยกเลิก
        </button>
        <button
          onClick={async () => {
            await onCreate(passage, blanks);
            onDone();
          }}
          disabled={!passage.trim()}
          className="bg-grove-600 hover:bg-grove-700 disabled:opacity-40 text-white rounded-lg px-4 py-2 text-sm ml-auto"
        >
          บันทึก
        </button>
      </div>
    </div>
  );
}

function FillBlankRunner({ item, onDone }: { item: FillBlankItem; onDone: () => void }) {
  const { user } = useAuth();
  const [answers, setAnswers] = useState<Record<string, number>>({});
  const [revealed, setRevealed] = useState(false);
  const [startedAt] = useState(Date.now());

  async function submit() {
    setRevealed(true);
    if (!user) return;
    for (const b of item.blanks) {
      const correct = answers[b.id] === b.correct_index;
      await logAttempt({
        userId: user.id,
        activityType: "writing_fill",
        itemId: item.id,
        skillTag: "grammar",
        correct,
        timeSpentSeconds: Math.round((Date.now() - startedAt) / 1000),
      });
    }
  }

  const parts = item.passage.split(/(\{\{blank_\d+\}\})/g);

  return (
    <div className="bg-white rounded-xl border border-grove-100 p-6">
      <div className="leading-loose text-gray-700 mb-4">
        {parts.map((part, i) => {
          const match = part.match(/\{\{(blank_\d+)\}\}/);
          if (!match) return <span key={i}>{part}</span>;
          const blankId = match[1];
          const blank = item.blanks.find((b) => b.id === blankId);
          if (!blank) return null;
          return (
            <select
              key={i}
              value={answers[blankId] ?? ""}
              onChange={(e) => setAnswers((prev) => ({ ...prev, [blankId]: Number(e.target.value) }))}
              disabled={revealed}
              className={`mx-1 border rounded px-2 py-0.5 text-sm ${
                revealed
                  ? answers[blankId] === blank.correct_index
                    ? "border-green-400 bg-green-50"
                    : "border-red-400 bg-red-50"
                  : "border-grove-300"
              }`}
            >
              <option value="">-- เลือก --</option>
              {blank.choices.map((c, ci) => (
                <option key={ci} value={ci}>
                  {c}
                </option>
              ))}
            </select>
          );
        })}
      </div>
      <div className="flex gap-2">
        <button onClick={onDone} className="text-gray-400 text-sm">
          ← กลับ
        </button>
        {!revealed && (
          <button
            onClick={submit}
            className="bg-grove-600 hover:bg-grove-700 text-white rounded-lg px-4 py-2 text-sm ml-auto"
          >
            ตรวจคำตอบ
          </button>
        )}
      </div>
    </div>
  );
}

// ---------------- Reorder sentences ----------------
function ReorderTab() {
  const { items, loading, createItem, deleteItem } = useReorderList();
  const [active, setActive] = useState<ReorderItem | null>(null);
  const [addingMode, setAddingMode] = useState(false);

  if (active) return <ReorderRunner item={active} onDone={() => setActive(null)} />;
  if (addingMode) return <AddReorder onDone={() => setAddingMode(false)} onCreate={createItem} />;

  return (
    <div>
      <button
        onClick={() => setAddingMode(true)}
        className="bg-grove-600 hover:bg-grove-700 text-white rounded-lg px-4 py-2 text-sm mb-4"
      >
        + เพิ่มโจทย์เรียงประโยค
      </button>
      {loading && <div className="text-gray-400 text-sm">กำลังโหลด...</div>}
      {!loading && items.length === 0 && (
        <div className="text-gray-400 text-sm py-8 text-center">ยังไม่มีโจทย์เรียงประโยค</div>
      )}
      <div className="space-y-2">
        {items.map((it) => (
          <div
            key={it.id}
            className="bg-white rounded-xl border border-grove-100 p-4 flex justify-between items-center"
          >
            <button onClick={() => setActive(it)} className="text-left flex-1 text-sm text-grove-800">
              ย่อหน้า {it.sentences.length} ประโยค
            </button>
            <button onClick={() => deleteItem(it.id)} className="text-red-400 text-xs ml-3">
              ลบ
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}

function AddReorder({
  onDone,
  onCreate,
}: {
  onDone: () => void;
  onCreate: (sentences: string[]) => Promise<any>;
}) {
  const [text, setText] = useState("");
  return (
    <div className="bg-white rounded-xl border border-grove-100 p-5 space-y-3">
      <p className="text-xs text-gray-400">พิมพ์ประโยคเรียงลำดับที่ถูกต้อง หนึ่งบรรทัดต่อหนึ่งประโยค</p>
      <textarea
        value={text}
        onChange={(e) => setText(e.target.value)}
        rows={6}
        placeholder={"First, ...\nThen, ...\nFinally, ..."}
        className="border border-grove-200 rounded-lg px-3 py-2 text-sm w-full"
      />
      <div className="flex gap-2">
        <button onClick={onDone} className="text-gray-400 text-sm">
          ยกเลิก
        </button>
        <button
          onClick={async () => {
            const sentences = text.split("\n").map((s) => s.trim()).filter(Boolean);
            await onCreate(sentences);
            onDone();
          }}
          disabled={!text.trim()}
          className="bg-grove-600 hover:bg-grove-700 disabled:opacity-40 text-white rounded-lg px-4 py-2 text-sm ml-auto"
        >
          บันทึก
        </button>
      </div>
    </div>
  );
}

function shuffle<T>(arr: T[]): T[] {
  const a = [...arr];
  for (let i = a.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [a[i], a[j]] = [a[j], a[i]];
  }
  return a;
}

function ReorderRunner({ item, onDone }: { item: ReorderItem; onDone: () => void }) {
  const { user } = useAuth();
  const [order, setOrder] = useState<string[]>(() => shuffle(item.sentences));
  const [revealed, setRevealed] = useState(false);
  const [startedAt] = useState(Date.now());

  function move(i: number, dir: -1 | 1) {
    const j = i + dir;
    if (j < 0 || j >= order.length) return;
    const next = [...order];
    [next[i], next[j]] = [next[j], next[i]];
    setOrder(next);
  }

  const correct = JSON.stringify(order) === JSON.stringify(item.sentences);

  async function submit() {
    setRevealed(true);
    if (!user) return;
    await logAttempt({
      userId: user.id,
      activityType: "writing_reorder",
      itemId: item.id,
      skillTag: "cohesion",
      correct,
      timeSpentSeconds: Math.round((Date.now() - startedAt) / 1000),
    });
  }

  return (
    <div className="bg-white rounded-xl border border-grove-100 p-6">
      <p className="text-xs text-gray-400 mb-3">ใช้ปุ่ม ↑↓ เพื่อจัดเรียงประโยคให้ถูกต้อง</p>
      <div className="space-y-2 mb-4">
        {order.map((s, i) => (
          <div
            key={s + i}
            className={`flex items-center gap-2 p-2.5 rounded-lg border text-sm ${
              revealed
                ? s === item.sentences[i]
                  ? "border-green-400 bg-green-50"
                  : "border-red-400 bg-red-50"
                : "border-grove-200"
            }`}
          >
            <div className="flex flex-col">
              <button onClick={() => move(i, -1)} disabled={revealed} className="text-xs text-grove-500">
                ▲
              </button>
              <button onClick={() => move(i, 1)} disabled={revealed} className="text-xs text-grove-500">
                ▼
              </button>
            </div>
            <span>{s}</span>
          </div>
        ))}
      </div>
      <div className="flex gap-2">
        <button onClick={onDone} className="text-gray-400 text-sm">
          ← กลับ
        </button>
        {!revealed ? (
          <button
            onClick={submit}
            className="bg-grove-600 hover:bg-grove-700 text-white rounded-lg px-4 py-2 text-sm ml-auto"
          >
            ตรวจคำตอบ
          </button>
        ) : (
          <span className={`ml-auto text-sm font-medium ${correct ? "text-green-600" : "text-red-500"}`}>
            {correct ? "ถูกต้อง! 🎉" : "ยังไม่ถูก ลองดูลำดับที่ถูกต้องด้านบน"}
          </span>
        )}
      </div>
    </div>
  );
}

// ---------------- Part of speech (fixed drill) ----------------
function PosTab() {
  const { user } = useAuth();
  const [index, setIndex] = useState(0);
  const [selected, setSelected] = useState<POSQuestion["correctAnswer"] | null>(null);
  const [revealed, setRevealed] = useState(false);
  const [score, setScore] = useState(0);
  const current = POS_DRILL[index];

  async function submit() {
    if (!selected) return;
    const correct = selected === current.correctAnswer;
    if (correct) setScore((s) => s + 1);
    setRevealed(true);
    if (user) {
      await logAttempt({
        userId: user.id,
        activityType: "writing_fill",
        itemId: current.id,
        skillTag: "word_form",
        correct,
        timeSpentSeconds: 0,
      });
    }
  }

  function next() {
    setRevealed(false);
    setSelected(null);
    setIndex((i) => (i + 1) % POS_DRILL.length);
  }

  return (
    <div className="bg-white rounded-xl border border-grove-100 p-6">
      <div className="text-xs text-gray-400 mb-3">
        ข้อ {index + 1} / {POS_DRILL.length} · คะแนนสะสม {score}
      </div>
      <div className="font-medium text-grove-800 mb-1">{current.sentence}</div>
      <div className="text-sm text-gray-400 mb-4">คำว่า "{current.word}" เป็นชนิดคำอะไร?</div>
      <div className="grid grid-cols-2 gap-2 mb-4">
        {(Object.keys(POS_LABEL) as POSQuestion["correctAnswer"][]).map((opt) => (
          <button
            key={opt}
            disabled={revealed}
            onClick={() => setSelected(opt)}
            className={`px-3 py-2 rounded-lg border text-sm text-left ${
              revealed && opt === current.correctAnswer
                ? "border-green-400 bg-green-50"
                : revealed && selected === opt
                ? "border-red-400 bg-red-50"
                : selected === opt
                ? "border-grove-500 bg-grove-50"
                : "border-grove-200"
            }`}
          >
            {POS_LABEL[opt]}
          </button>
        ))}
      </div>
      {!revealed ? (
        <button
          onClick={submit}
          disabled={!selected}
          className="bg-grove-600 hover:bg-grove-700 disabled:opacity-40 text-white rounded-lg px-4 py-2 text-sm"
        >
          ตอบ
        </button>
      ) : (
        <button
          onClick={next}
          className="bg-grove-600 hover:bg-grove-700 text-white rounded-lg px-4 py-2 text-sm"
        >
          ข้อถัดไป
        </button>
      )}
    </div>
  );
}
