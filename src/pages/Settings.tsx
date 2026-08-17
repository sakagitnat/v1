import { useEffect, useState, ReactNode } from "react";

type Theme = "light" | "dark";
type Lang = "th" | "en";

function useLocalSetting<T extends string>(key: string, initial: T) {
  const [value, setValue] = useState<T>(() => (localStorage.getItem(key) as T) || initial);
  useEffect(() => {
    localStorage.setItem(key, value);
  }, [key, value]);
  return [value, setValue] as const;
}

export default function Settings() {
  const [theme, setTheme] = useLocalSetting<Theme>("grove-theme", "light");
  const [soundOn, setSoundOn] = useLocalSetting<"on" | "off">("grove-sound", "on");
  const [lang, setLang] = useLocalSetting<Lang>("grove-lang", "th");
  const [onboardingSeen] = useLocalSetting("grove-onboarding-seen", "true");

  useEffect(() => {
    document.documentElement.classList.toggle("dark", theme === "dark");
  }, [theme]);

  return (
    <div className="p-10 max-w-lg">
      <h1 className="text-2xl font-bold text-grove-800 mb-6">ตั้งค่า</h1>

      <div className="space-y-5">
        <Row label="ธีม">
          <div className="flex gap-2">
            {(["light", "dark"] as Theme[]).map((t) => (
              <button
                key={t}
                onClick={() => setTheme(t)}
                className={`px-3 py-1.5 rounded-lg text-sm border ${
                  theme === t ? "bg-grove-600 text-white border-grove-600" : "border-grove-200"
                }`}
              >
                {t === "light" ? "สว่าง" : "มืด"}
              </button>
            ))}
          </div>
        </Row>

        <Row label="เสียง">
          <button
            onClick={() => setSoundOn(soundOn === "on" ? "off" : "on")}
            className={`px-3 py-1.5 rounded-lg text-sm border ${
              soundOn === "on" ? "bg-grove-600 text-white border-grove-600" : "border-grove-200"
            }`}
          >
            {soundOn === "on" ? "เปิด" : "ปิด"}
          </button>
        </Row>

        <Row label="ภาษา UI">
          <select
            value={lang}
            onChange={(e) => setLang(e.target.value as Lang)}
            className="border border-grove-200 rounded-lg px-3 py-1.5 text-sm"
          >
            <option value="th">ไทย</option>
            <option value="en">English</option>
          </select>
        </Row>

        <Row label="วิธีใช้แอป">
          <button
            onClick={() => localStorage.removeItem("grove-onboarding-seen")}
            className="text-grove-600 underline text-sm"
          >
            เปิด onboarding อีกครั้ง
          </button>
        </Row>
      </div>
    </div>
  );
}

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex items-center justify-between bg-white rounded-xl border border-grove-100 px-4 py-3">
      <span className="text-sm text-grove-700">{label}</span>
      {children}
    </div>
  );
}
