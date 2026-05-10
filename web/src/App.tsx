import { Navigate, Route, Routes } from "react-router-dom";

import Layout from "./components/Layout";
import AuditView from "./views/AuditView";
import ChatView from "./views/ChatView";
import PersonasView from "./views/PersonasView";
import PrefsView from "./views/PrefsView";
import ReportsView from "./views/ReportsView";

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<Navigate to="/chat" replace />} />
        <Route path="/chat" element={<ChatView />} />
        <Route path="/chat/:threadId" element={<ChatView />} />
        <Route path="/reports" element={<ReportsView />} />
        <Route path="/audit" element={<AuditView />} />
        <Route path="/prefs" element={<PrefsView />} />
        <Route path="/personas" element={<PersonasView />} />
        <Route path="*" element={<Navigate to="/chat" replace />} />
      </Route>
    </Routes>
  );
}
