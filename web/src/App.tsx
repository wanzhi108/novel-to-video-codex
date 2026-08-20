import { useEffect } from "react";
import { Routes, Route, useNavigate } from "react-router-dom";
import { AppLayout } from "./layout/AppLayout";
import { Dashboard } from "./pages/Dashboard";
import { CreateProject } from "./pages/CreateProject";
import { StoryboardEditor } from "./pages/StoryboardEditor";
import { CharacterPanel } from "./pages/CharacterPanel";
import { TaskManager } from "./pages/TaskManager";
import { Settings } from "./pages/Settings";
import { ScenePreview } from "./pages/ScenePreview";
import { useSettingsStore } from "./stores/settingsStore";
import { useKeyboardShortcuts } from "./hooks/useKeyboardShortcuts";
import { ToastContainer } from "./components/ToastContainer";
import { api } from "./lib/api";
import { useToastStore } from "./stores/toastStore";

export default function App() {
  const loadSettings = useSettingsStore((s) => s.loadFromLocalStorage);
  const show = useToastStore((s) => s.show);
  const navigate = useNavigate();

  useEffect(() => {
    loadSettings();
  }, [loadSettings]);

  useKeyboardShortcuts([
    { key: "h", ctrl: true, handler: () => navigate("/") },
    { key: "n", ctrl: true, handler: () => navigate("/create") },
    { key: "t", ctrl: true, handler: () => navigate("/tasks") },
    { key: "s", ctrl: true, handler: () => navigate("/settings") },
    { key: "e", ctrl: true, shift: true, handler: () => {
      api.health().then(() => show("服务运行正常", "success")).catch(() => show("服务未连接", "error"));
    }},
  ]);

  return (
    <>
      <ToastContainer />
      <Routes>
        <Route element={<AppLayout />}>
          <Route path="/" element={<Dashboard />} />
          <Route path="/create" element={<CreateProject />} />
          <Route path="/storyboard" element={<StoryboardEditor />} />
          <Route path="/storyboard/:jobId" element={<StoryboardEditor />} />
          <Route path="/characters" element={<CharacterPanel />} />
          <Route path="/characters/:jobId" element={<CharacterPanel />} />
          <Route path="/tasks" element={<TaskManager />} />
          <Route path="/settings" element={<Settings />} />
          <Route path="/scene/:jobId/:sceneId" element={<ScenePreview />} />
        </Route>
      </Routes>
    </>
  );
}
