import { useState } from "react";
import { Link } from "react-router-dom";
import { useSkillBanks, useSkillBankItems, SkillBankItem } from "../hooks/useSkillBanks";
import { usePro } from "../hooks/usePro";
import { useReadingList } from "../hooks/useReading";
import { useListeningList } from "../hooks/useListening";
import { useFillBlankList, useReorderList } from "../hooks/useWriting";

export default function SkillBanks() {
  const { banks, loading, createBank, togglePublic, deleteBank } = useSkillBanks();
  const { isPro } = usePro();
  const [activeId, setActiveId] = useState<string | null>(null);
  const [newName, setNewName] = useState("");
  const [newDesc, setNewDesc] = useState("");

  const active = banks.find((b) => b.id === activeId) ?? null;

  async function handleCreate() {
    if (!newName.trim()) return;
    const bank = await createBank(newName.trim(), newDesc.trim());
    setNewName("");
    setNewDesc("");
    if (bank) setActiveId(bank.id);
  }

  return (
    <div className="p-10 max-w-3xl">
      <h1 className="text-2xl font-bold text-grove-800 mb-1">Skill Bank ของฉัน</h1>
      <p className="text-gray-500 mb-6">
        รวมบทความ/บทสนทนา/โจทย์ที่มีอยู่แล้วเป็นชุดเดียว แล้วแชร์เป็นคลังทักษะสาธารณะได้ (ต้อง Pro)
      </p>

      <div className="flex flex-wrap gap-2 mb-4">
        {loading && <span className="text-sm text-gray-400">กำลังโหลด...</span>}
        {banks.map((b) => (
          <button
            key={b.id}
            onClick={() => setActiveId(b.id)}
            className={`px-3 py-1.5 rounded-full text-sm border ${
              activeId === b.id ? "bg-grove-600 text-white border-grove-600" : "bg-white border-grove-200"
            }`}
          >
            {b.name} {b.is_public && "🌐"}
          </button>
        ))}
      </div>

      <div className="flex gap-2 mb-8">
        <input
          value={newName}
          onChange={(e) => setNewName(e.target.value)}
          placeholder="ชื่อ Skill Bank"
          className="border border-grove-200 rounded-lg px-3 py-2 text-sm flex-1"
        />
        <input
          value={newDesc}
          onChange={(e) => setNewDesc(e.target.value)}
          placeholder="คำอธิบาย (ถ้ามี)"
          className="border border-grove-200 rounded-lg px-3 py-2 text-sm flex-1"
        />
        <button onClick={handleCreate} className="bg-grove-600 hover:bg-grove-700 text-white rounded-lg px-4 py-2 text-sm">
          + สร้าง
        </button>
      </div>

      {active && (
        <BankDetail
          bank={active}
          isPro={isPro}
          onTogglePublic={(v) => togglePublic(active.id, v)}
          onDelete={() => {
            deleteBank(active.id);
            setActiveId(null);
          }}
        />
      )}

      {!active && banks.length === 0 && !loading && (
        <div className="text-center py-16 text-gray-400">ยังไม่มี Skill Bank — สร้างอันแรกด้านบน</div>
      )}
    </div>
  );
}

function BankDetail({
  bank,
  isPro,
  onTogglePublic,
  onDelete,
}: {
  bank: { id: string; name: string; description: string | null; is_public: boolean };
  isPro: boolean;
  onTogglePublic: (v: boolean) => void;
  onDelete: () => void;
}) {
  const { items, addItem, removeItem } = useSkillBankItems(bank.id);
  const reading = useReadingList();
  const listening = useListeningList();
  const fill = useFillBlankList();
  const reorder = useReorderList();

  return (
    <div className="bg-white rounded-xl border border-grove-100 p-6">
      <div className="flex items-center justify-between mb-1">
        <div className="font-semibold text-lg text-grove-800">{bank.name}</div>
        <div className="flex items-center gap-3 text-sm">
          {isPro ? (
            <label className="flex items-center gap-1.5 cursor-pointer">
              <input type="checkbox" checked={bank.is_public} onChange={(e) => onTogglePublic(e.target.checked)} />
              แชร์สาธารณะ
            </label>
          ) : (
            <Link to="/pro" className="text-yellow-600 text-xs">
              ⭐ อัปเกรด Pro เพื่อแชร์
            </Link>
          )}
          <button onClick={onDelete} className="text-red-500 hover:underline">
            ลบ Bank นี้
          </button>
        </div>
      </div>
      {bank.description && <div className="text-sm text-gray-400 mb-4">{bank.description}</div>}

      <div className="mb-4">
        <div className="text-sm font-medium text-grove-700 mb-2">รายการในชุดนี้ ({items.length})</div>
        {items.length === 0 && <div className="text-gray-400 text-sm">ยังไม่มีรายการ — เพิ่มจากด้านล่าง</div>}
        <div className="divide-y divide-grove-100">
          {items.map((it) => (
            <div key={it.id} className="flex items-center justify-between py-1.5 text-sm">
              <span>
                <span className="text-xs text-grove-400 mr-2">[{labelFor(it.content_type)}]</span>
                {it.content_title}
              </span>
              <button onClick={() => removeItem(it.id)} className="text-red-400 text-xs">
                นำออก
              </button>
            </div>
          ))}
        </div>
      </div>

      <ContentPicker
        title="Reading"
        list={reading.articles.map((a) => ({ id: a.id, title: a.title }))}
        disabledIds={items.map((i) => i.content_id)}
        onAdd={(id, title) => addItem("reading_article", id, title)}
      />
      <ContentPicker
        title="Listening"
        list={listening.items.map((a) => ({ id: a.id, title: a.title }))}
        disabledIds={items.map((i) => i.content_id)}
        onAdd={(id, title) => addItem("listening_item", id, title)}
      />
      <ContentPicker
        title="เติมคำ"
        list={fill.items.map((a) => ({ id: a.id, title: a.passage.slice(0, 40) + "..." }))}
        disabledIds={items.map((i) => i.content_id)}
        onAdd={(id, title) => addItem("writing_fill_blank", id, title)}
      />
      <ContentPicker
        title="เรียงประโยค"
        list={reorder.items.map((a) => ({ id: a.id, title: `${a.sentences.length} ประโยค` }))}
        disabledIds={items.map((i) => i.content_id)}
        onAdd={(id, title) => addItem("writing_reorder", id, title)}
      />
    </div>
  );
}

function labelFor(t: SkillBankItem["content_type"]) {
  return (
    {
      reading_article: "Reading",
      listening_item: "Listening",
      writing_fill_blank: "เติมคำ",
      writing_reorder: "เรียงประโยค",
    } as const
  )[t];
}

function ContentPicker({
  title,
  list,
  disabledIds,
  onAdd,
}: {
  title: string;
  list: { id: string; title: string }[];
  disabledIds: string[];
  onAdd: (id: string, title: string) => void;
}) {
  if (list.length === 0) return null;
  return (
    <div className="mb-3">
      <div className="text-xs text-gray-400 mb-1">+ เพิ่มจาก {title}</div>
      <div className="flex flex-wrap gap-1.5">
        {list.map((item) => (
          <button
            key={item.id}
            disabled={disabledIds.includes(item.id)}
            onClick={() => onAdd(item.id, item.title)}
            className="text-xs border border-grove-200 rounded-full px-2 py-1 disabled:opacity-30 hover:border-grove-400"
          >
            {item.title}
          </button>
        ))}
      </div>
    </div>
  );
}
