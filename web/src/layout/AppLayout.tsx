import { Outlet } from "react-router-dom";
import { Sidebar } from "./Sidebar";
import { Header } from "./Header";
import { useSettingsStore } from "@/stores/settingsStore";
import { cn } from "@/lib/utils";
import { Toaster } from "react-hot-toast";

export function AppLayout() {
  const sidebarCollapsed = useSettingsStore((s) => s.sidebarCollapsed);

  return (
    <div className="flex h-screen overflow-hidden bg-gray-50 dark:bg-ink-950">
      <Sidebar />
      <div
        className={cn(
          "flex flex-col flex-1 overflow-hidden transition-all",
          sidebarCollapsed ? "ml-16" : "ml-64"
        )}
      >
        <Header />
        <main className="flex-1 overflow-y-auto p-6">
          <Outlet />
        </main>
      </div>
      <Toaster
        position="top-right"
        toastOptions={{
          duration: 4000,
          style: {
            background: "var(--color-surface)",
            color: "var(--color-text)",
            border: "1px solid var(--color-border)",
          },
        }}
      />
    </div>
  );
}
