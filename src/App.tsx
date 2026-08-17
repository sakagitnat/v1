import { Routes, Route, Navigate } from "react-router-dom";
import { useAuth } from "./contexts/AuthContext";
import Layout from "./components/Layout";
import ReferralProcessor from "./components/ReferralProcessor";
import Login from "./pages/Login";
import Dashboard from "./pages/Dashboard";
import Flashcards from "./pages/Flashcards";
import Reading from "./pages/Reading";
import ReadingDetail from "./pages/ReadingDetail";
import AddReading from "./pages/AddReading";
import Listening from "./pages/Listening";
import ListeningDetail from "./pages/ListeningDetail";
import AddListening from "./pages/AddListening";
import Writing from "./pages/Writing";
import MockExam from "./pages/MockExam";
import WeakPoints from "./pages/WeakPoints";
import Community from "./pages/Community";
import MyContent from "./pages/MyContent";
import AddContentHub from "./pages/AddContentHub";
import ProfilePage from "./pages/Profile";
import Settings from "./pages/Settings";
import Admin from "./pages/Admin";
import Invite from "./pages/Invite";
import Pro from "./pages/Pro";
import SkillBanks from "./pages/SkillBanks";

function RequireAuth({ children }: { children: JSX.Element }) {
  const { user, loading } = useAuth();
  if (loading) return <div className="p-8 text-center text-grove-700">กำลังโหลด...</div>;
  if (!user) return <Navigate to="/login" replace />;
  return children;
}

export default function App() {
  return (
    <>
      <ReferralProcessor />
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route
          path="/"
          element={
            <RequireAuth>
              <Layout />
            </RequireAuth>
          }
        >
          <Route index element={<Dashboard />} />
          <Route path="flashcards" element={<Flashcards />} />
          <Route path="reading" element={<Reading />} />
          <Route path="reading/add" element={<AddReading />} />
          <Route path="reading/:id" element={<ReadingDetail />} />
          <Route path="listening" element={<Listening />} />
          <Route path="listening/add" element={<AddListening />} />
          <Route path="listening/:id" element={<ListeningDetail />} />
          <Route path="writing" element={<Writing />} />
          <Route path="mock-exam" element={<MockExam />} />
          <Route path="weak-points" element={<WeakPoints />} />
          <Route path="community" element={<Community />} />
          <Route path="my-content" element={<MyContent />} />
          <Route path="add-content" element={<AddContentHub />} />
          <Route path="profile" element={<ProfilePage />} />
          <Route path="settings" element={<Settings />} />
          <Route path="admin" element={<Admin />} />
          <Route path="invite" element={<Invite />} />
          <Route path="pro" element={<Pro />} />
          <Route path="skill-banks" element={<SkillBanks />} />
        </Route>
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </>
  );
}
