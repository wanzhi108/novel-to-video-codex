import { useState, useEffect } from "react";
import { useMatch } from "react-router-dom";
import { Wifi, WifiOff, Server, Cpu, Moon, Sun, Layers } from "lucide-react";
import { useComfyUI } from "@/hooks/useComfyUI";
import { useHealth } from "@/hooks/useApi";
import { useSettingsStore } from "@/stores/settingsStore";
import { useJobStore } from "@/stores/jobStore";
import { cn } from "@/lib/utils";

export function Header() {
  const comfyUI = useComfyUI();
  const health = useHealth();
  const darkMode = useSettingsStore((s) => s.darkMode);
  const toggleDarkMode = useSettingsStore((s) => s.toggleDarkMode);
  const wsConnected = useJobStore((s) => s.wsConnected);
  const currentStep = useJobStore((s) => s.currentStep);

  // WS is only meaningful when a project is open
  const onProjectPage =
    useMatch("/storyboard/:jobId") ||
    useMatch("/characters/:jobId") ||
    useMatch("/scene/:jobId/:sceneId");

  const [time, setTime] = useState(new Date());
  useEffect(() => {
    const timer = setInterval(() => setTime(new Date()), 1000);
    return () => clearInterval(timer);
  }, []);

  return (
    <header className="flex items-center justify-between h-14 px-6 bg-white dark:bg-ink-900 border-b border-gray-200 dark:border-ink-800 shrink-0">
      {/* Left: Current step */}
      <div className="flex items-center gap-3">
        {currentStep && (
          <span className="text-sm text-gray-500 dark:text-ink-400">
            当前步骤:{" "}
            <span className="font-medium text-gold-600 dark:text-gold-400">
              {currentStep}
            </span>
          </span>
        )}
      </div>

      {/* Right: Status indicators */}
      <div className="flex items-center gap-4">
        {/* ComfyUI status */}
        <div className="flex items-center gap-1.5 text-xs">
          <Server
            className={cn(
              "w-4 h-4",
              comfyUI.connected ? "text-green-500" : "text-red-500"
            )}
          />
          <span className="text-gray-600 dark:text-ink-300">
            ComfyUI {comfyUI.connected ? "在线" : "离线"}
          </span>
          {comfyUI.totalQueue > 0 && (
            <span className="badge-warning">{comfyUI.totalQueue} 排队</span>
          )}
        </div>

        {/* Backend health */}
        <div className="flex items-center gap-1.5 text-xs">
          <Cpu
            className={cn(
              "w-4 h-4",
              health.data?.status === "ok" ? "text-green-500" : "text-red-500"
            )}
          />
          <span className="text-gray-600 dark:text-ink-300">
            后端 {health.data?.status === "ok" ? "正常" : "异常"}
          </span>
        </div>

        {/* WebSocket status */}
        <div className="flex items-center gap-1.5 text-xs">
          {onProjectPage ? (
            wsConnected ? (
              <Wifi className="w-4 h-4 text-green-500" />
            ) : (
              <WifiOff className="w-4 h-4 text-red-500" />
            )
          ) : (
            <Layers className="w-4 h-4 text-gray-400" />
          )}
          <span className="text-gray-600 dark:text-ink-300">
            {onProjectPage
              ? `WS ${wsConnected ? "已连接" : "未连接"}`
              : "未选择项目"}
          </span>
        </div>

        {/* Time */}
        <span className="text-xs text-gray-400 dark:text-ink-500 tabular-nums">
          {time.toLocaleTimeString("zh-CN")}
        </span>

        {/* Dark mode toggle */}
        <button
          onClick={toggleDarkMode}
          className="p-1.5 rounded-lg hover:bg-gray-100 dark:hover:bg-ink-800 transition-colors"
          title={darkMode ? "切换亮色" : "切换暗色"}
        >
          {darkMode ? (
            <Sun className="w-4 h-4 text-gold-400" />
          ) : (
            <Moon className="w-4 h-4 text-gray-500" />
          )}
        </button>
      </div>
    </header>
  );
}
