import { NavLink, Outlet } from "react-router-dom";
import { useAuth } from "../contexts/AuthContext";
import { usePro } from "../hooks/usePro";

const NAV_ITEMS = [
  { to: "/", label: "หน้าหลัก", end: true },
  { to: "/flashcards", label: "คำศัพท์" },
  { to: "/reading", label: "Reading" },
  { to: "/listening", label: "Listening" },
  { to: "/writing", label: "Writing" },
  { to: "/mock-exam", label: "สอบจำลอง" },
  { to: "/weak-points", label: "จุดอ่อน" },
  { to: "/add-content", label: "เพิ่มเนื้อหา" },
  { to: "/community", label: "คลังสาธารณะ" },
  { to: "/my-content", label: "เนื้อหาของฉัน" },
  { to: "/skill-banks", label: "Skill Bank" },
  { to: "/invite", label: "ชวนเพื่อน" },
  { to: "/profile", label: "โปรไฟล์" },
  { to: "/settings", label: "ตั้งค่า" },
];

export default function Layout() {
  const { signOut, user } = useAuth();
  const { isPro } = usePro();

  return (
    <div className="min-h-screen flex bg-grove-50">
      <aside className="w-56 shrink-0 bg-grove-800 text-white flex flex-col">
        <div className="px-4 py-5 text-xl font-bold flex items-center gap-2">
          🌱 Grove {isPro && <span className="text-xs bg-yellow-400 text-yellow-900 px-1.5 py-0.5 rounded-full">PRO</span>}
        </div>
        <nav className="flex-1 px-2 space-y-1 overflow-y-auto">
          {NAV_ITEMS.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              className={({ isActive }) =>
                `block rounded-lg px-3 py-2 text-sm ${
                  isActive ? "bg-grove-600 font-medium" : "hover:bg-grove-700"
                }`
              }
            >
              {item.label}
            </NavLink>
          ))}
          <NavLink
            to="/admin"
            className={({ isActive }) =>
              `block rounded-lg px-3 py-2 text-sm ${
                isActive ? "bg-grove-600 font-medium" : "hover:bg-grove-700"
              }`
            }
          >
            แอดมิน
          </NavLink>
        </nav>
        <div className="px-4 py-4 text-xs text-grove-200 border-t border-grove-700">
          <div className="truncate mb-2">{user?.email}</div>
          <button onClick={() => signOut()} className="underline hover:text-white">
            ออกจากระบบ
          </button>
        </div>
      </aside>
      <main className="flex-1 overflow-y-auto">
        <Outlet />
      </main>
    </div>
  );
}
