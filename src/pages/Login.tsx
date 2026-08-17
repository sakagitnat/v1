import { Navigate } from "react-router-dom";
import { useEffect } from "react";
import { useAuth } from "../contexts/AuthContext";

export default function Login() {
  const { user, loading, signInWithGoogle } = useAuth();

  useEffect(() => {
    const ref = new URLSearchParams(window.location.search).get("ref");
    if (ref) localStorage.setItem("grove_pending_ref", ref);
  }, []);

  if (loading) return null;
  if (user) return <Navigate to="/" replace />;

  return (
    <div className="min-h-screen flex items-center justify-center bg-grove-50">
      <div className="bg-white rounded-2xl shadow-lg p-10 text-center max-w-sm w-full">
        <div className="text-4xl mb-2">🌱</div>
        <h1 className="text-2xl font-bold text-grove-800 mb-1">Grove</h1>
        <p className="text-gray-500 mb-6 text-sm">เรียนภาษาอังกฤษทุกทักษะในที่เดียว</p>
        <button
          onClick={() => signInWithGoogle()}
          className="w-full bg-grove-600 hover:bg-grove-700 text-white rounded-xl py-3 font-medium transition"
        >
          เข้าสู่ระบบด้วย Google
        </button>
      </div>
    </div>
  );
}
