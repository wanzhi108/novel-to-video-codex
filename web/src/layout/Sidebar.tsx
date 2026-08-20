import { NavLink } from "react-router-dom";
import {
  LayoutDashboard,
  FilePlus2,
  Film,
  Users,
  ListTodo,
  Settings,
  ChevronLeft,
  ChevronRight,
  Sparkles,
} from "lucide-react";
import { useSettingsStore } from "@/stores/settingsStore";
import { cn } from "@/lib/utils";

const navItems = [
  { to: "/", icon: LayoutDashboard, label: "仪表盘" },
  { to: "/create", icon: FilePlus2, label: "创建项目" },
  { to: "/storyboard", icon: Film, label: "分镜编辑" },
  { to: "/characters", icon: Users, label: "角色配音" },
  { to: "/tasks", icon: ListTodo, label: "任务管理" },
  { to: "/settings", icon: Settings, label: "设置" },
];

export function Sidebar() {
  const collapsed = useSettingsStore((s) => s.sidebarCollapsed);
  const toggleSidebar = useSettingsStore((s) => s.toggleSidebar);

  return (
    <aside
      className={cn(
        "fixed left-0 top-0 h-full bg-white dark:bg-ink-900 border-r border-gray-200 dark:border-ink-800 transition-all z-30",
        collapsed ? "w-16" : "w-64"
      )}
    >
      {/* Logo */}
      <div className="flex items-center gap-3 h-16 px-4 border-b border-gray-200 dark:border-ink-800">
        <div className="flex items-center justify-center w-8 h-8 rounded-lg bg-gradient-to-br from-gold-400 to-gold-600 shrink-0">
          <Sparkles className="w-5 h-5 text-white" />
        </div>
        {!collapsed && (
          <div className="flex flex-col">
            <span className="text-sm font-bold text-gray-900 dark:text-ink-50">
              LuminaForge
            </span>
            <span className="text-xs text-gold-500">墨影流光</span>
          </div>
        )}
      </div>

      {/* Navigation */}
      <nav className="flex flex-col gap-1 p-2">
        {navItems.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.to === "/"}
            className={({ isActive }) =>
              cn(
                "flex items-center gap-3 px-3 py-2.5 rounded-lg transition-colors",
                isActive
                  ? "bg-gold-50 text-gold-700 dark:bg-gold-900/20 dark:text-gold-400 font-medium"
                  : "text-gray-600 dark:text-ink-300 hover:bg-gray-100 dark:hover:bg-ink-800"
              )
            }
            title={collapsed ? item.label : undefined}
          >
            <item.icon className="w-5 h-5 shrink-0" />
            {!collapsed && <span className="text-sm">{item.label}</span>}
          </NavLink>
        ))}
      </nav>

      {/* Collapse toggle */}
      <button
        onClick={toggleSidebar}
        className="absolute top-1/2 -right-3 w-6 h-6 flex items-center justify-center rounded-full bg-white dark:bg-ink-800 border border-gray-200 dark:border-ink-700 shadow-sm hover:bg-gray-50 dark:hover:bg-ink-700 transition-colors"
      >
        {collapsed ? (
          <ChevronRight className="w-4 h-4 text-gray-500" />
        ) : (
          <ChevronLeft className="w-4 h-4 text-gray-500" />
        )}
      </button>
    </aside>
  );
}
