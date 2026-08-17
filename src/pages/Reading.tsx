import { Link } from "react-router-dom";
import { useReadingList } from "../hooks/useReading";

const CATEGORY_LABEL: Record<string, string> = {
  ad: "โฆษณา",
  review: "บทวิจารณ์",
  news: "ข่าว",
  infographic: "ข้อมูลภาพ/ตาราง",
  general: "บทความทั่วไป",
};

export default function Reading() {
  const { articles, loading, deleteArticle } = useReadingList();

  return (
    <div className="p-10 max-w-3xl">
      <div className="flex items-center justify-between mb-1">
        <h1 className="text-2xl font-bold text-grove-800">Reading</h1>
        <Link
          to="/reading/add"
          className="bg-grove-600 hover:bg-grove-700 text-white rounded-lg px-4 py-2 text-sm"
        >
          + เพิ่มบทความเอง
        </Link>
      </div>
      <p className="text-gray-500 mb-6">เลือกบทความจากรายการของคุณ</p>

      {loading && <div className="text-gray-400 text-sm">กำลังโหลด...</div>}

      {!loading && articles.length === 0 && (
        <div className="text-center py-16 text-gray-400">
          ยังไม่มีบทความ — เพิ่มเองด้านบน หรือไปนำเข้าจาก
          <Link to="/community" className="text-grove-600 underline ml-1">
            คลังสาธารณะ
          </Link>
        </div>
      )}

      <div className="space-y-2">
        {articles.map((a) => (
          <div
            key={a.id}
            className="bg-white rounded-xl border border-grove-100 p-4 flex items-center justify-between"
          >
            <Link to={`/reading/${a.id}`} className="flex-1">
              <div className="font-medium text-grove-800">{a.title}</div>
              <div className="text-xs text-gray-400 mt-1">
                {CATEGORY_LABEL[a.category]} · เป้าหมาย {Math.round(a.time_goal_seconds / 60)} นาที
              </div>
            </Link>
            <button
              onClick={() => deleteArticle(a.id)}
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
