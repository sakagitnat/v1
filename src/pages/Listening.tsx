import { Link } from "react-router-dom";
import { useListeningList } from "../hooks/useListening";

export default function Listening() {
  const { items, loading, deleteItem } = useListeningList();

  return (
    <div className="p-10 max-w-3xl">
      <div className="flex items-center justify-between mb-1">
        <h1 className="text-2xl font-bold text-grove-800">Listening</h1>
        <Link
          to="/listening/add"
          className="bg-grove-600 hover:bg-grove-700 text-white rounded-lg px-4 py-2 text-sm"
        >
          + เพิ่มบทสนทนาเอง
        </Link>
      </div>
      <p className="text-gray-500 mb-6">เลือกบทสนทนาจากรายการของคุณ</p>

      {loading && <div className="text-gray-400 text-sm">กำลังโหลด...</div>}
      {!loading && items.length === 0 && (
        <div className="text-center py-16 text-gray-400">
          ยังไม่มีบทสนทนา — เพิ่มเองด้านบน หรือไปนำเข้าจาก
          <Link to="/community" className="text-grove-600 underline ml-1">
            คลังสาธารณะ
          </Link>
        </div>
      )}

      <div className="space-y-2">
        {items.map((it) => (
          <div
            key={it.id}
            className="bg-white rounded-xl border border-grove-100 p-4 flex items-center justify-between"
          >
            <Link to={`/listening/${it.id}`} className="flex-1 font-medium text-grove-800">
              {it.title}
            </Link>
            <button
              onClick={() => deleteItem(it.id)}
              className="text-red-400 hover:text-red-600 text-xs ml-4"
            >
              ลบ
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}
