import { useState } from "react";
import { useReadingList } from "../hooks/useReading";
import { useListeningList } from "../hooks/useListening";
import { useFillBlankList, useReorderList } from "../hooks/useWriting";

type Tab = "reading" | "listening" | "fill" | "reorder";

export default function MyContent() {
  const [tab, setTab] = useState<Tab>("reading");
  const reading = useReadingList();
  const listening = useListeningList();
  const fill = useFillBlankList();
  const reorder = useReorderList();

  return (
    <div className="p-10 max-w-3xl">
      <h1 className="text-2xl font-bold text-grove-800 mb-1">จัดการเนื้อหาของฉัน</h1>
      <p className="text-gray-500 mb-6">
        บทความ/บทสนทนา/โจทย์ที่สร้างเอง — คำศัพท์จัดการแยกในหน้า "เพิ่มเนื้อหา → คำศัพท์"
      </p>
      <div className="flex gap-2 mb-6">
        {(
          [
            ["reading", "Reading"],
            ["listening", "Listening"],
            ["fill", "เติมคำ"],
            ["reorder", "เรียงประโยค"],
          ] as [Tab, string][]
        ).map(([key, label]) => (
          <button
            key={key}
            onClick={() => setTab(key)}
            className={`px-4 py-1.5 rounded-full text-sm border ${
              tab === key ? "bg-grove-600 text-white border-grove-600" : "bg-white border-grove-200"
            }`}
          >
            {label}
          </button>
        ))}
      </div>

      {tab === "reading" && (
        <List
          items={reading.articles}
          render={(a) => a.title}
          onDelete={(id) => reading.deleteArticle(id)}
          loading={reading.loading}
        />
      )}
      {tab === "listening" && (
        <List
          items={listening.items}
          render={(a) => a.title}
          onDelete={(id) => listening.deleteItem(id)}
          loading={listening.loading}
        />
      )}
      {tab === "fill" && (
        <List
          items={fill.items}
          render={(a) => a.passage.slice(0, 60) + "..."}
          onDelete={(id) => fill.deleteItem(id)}
          loading={fill.loading}
        />
      )}
      {tab === "reorder" && (
        <List
          items={reorder.items}
          render={(a) => `${a.sentences.length} ประโยค`}
          onDelete={(id) => reorder.deleteItem(id)}
          loading={reorder.loading}
        />
      )}
    </div>
  );
}

function List<T extends { id: string }>({
  items,
  render,
  onDelete,
  loading,
}: {
  items: T[];
  render: (item: T) => string;
  onDelete: (id: string) => void;
  loading: boolean;
}) {
  if (loading) return <div className="text-gray-400 text-sm">กำลังโหลด...</div>;
  if (items.length === 0) return <div className="text-gray-400 text-sm py-8 text-center">ยังไม่มีรายการ</div>;
  return (
    <div className="space-y-2">
      {items.map((it) => (
        <div key={it.id} className="bg-white rounded-xl border border-grove-100 p-4 flex items-center justify-between">
          <div className="text-sm text-grove-800 truncate flex-1">{render(it)}</div>
          <button onClick={() => onDelete(it.id)} className="text-red-400 hover:text-red-600 text-xs ml-3">
            ลบ
          </button>
        </div>
      ))}
    </div>
  );
}
