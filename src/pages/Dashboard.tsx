import { useAuth } from "../contexts/AuthContext";
import { usePro } from "../hooks/usePro";
import { Link } from "react-router-dom";

const CARDS = [
  { label: "คำศัพท์", to: "/flashcards", icon: "🔤" },
  { label: "Reading", to: "/reading", icon: "📖" },
  { label: "Listening", to: "/listening", icon: "🎧" },
  { label: "Writing", to: "/writing", icon: "✍️" },
  { label: "สอบจำลอง", to: "/mock-exam", icon: "📝" },
  { label: "จุดอ่อน", to: "/weak-points", icon: "🎯" },
];

export default function Dashboard() {
  const { user } = useAuth();
  const { isPro } = usePro();

  return (
    <div className="p-10">
      <h1 className="text-2xl font-bold text-grove-800 mb-1">
        สวัสดี {user?.user_metadata?.full_name ?? user?.email} 👋
      </h1>
      <p className="text-gray-500 mb-6">พร้อมฝึกภาษาอังกฤษวันนี้หรือยัง?</p>

      {!isPro && (
        <div className="bg-yellow-50 border border-yellow-200 rounded-xl p-4 mb-6 flex items-center justify-between">
          <span className="text-sm text-yellow-800">อัปเกรดเป็น Pro เพื่อปลดล็อกทุกฟีเจอร์</span>
          <Link to="/pro" className="text-sm bg-yellow-400 hover:bg-yellow-500 text-yellow-900 rounded-lg px-3 py-1.5">
            ดูแพ็กเกจ
          </Link>
        </div>
      )}

      <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
        {CARDS.map((c) => (
          <Link
            key={c.to}
            to={c.to}
            className="bg-white rounded-xl shadow p-6 hover:shadow-md transition border border-grove-100"
          >
            <div className="text-2xl mb-1">{c.icon}</div>
            <div className="font-semibold text-grove-800">{c.label}</div>
          </Link>
        ))}
      </div>
    </div>
  );
}
