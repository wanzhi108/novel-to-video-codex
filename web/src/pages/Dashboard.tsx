import { useNavigate } from "react-router-dom";
import { useRef } from "react";
import {
  Film,
  CheckCircle2,
  XCircle,
  Clock,
  ArrowRight,
  Server,
  Cpu,
  HardDrive,
  Upload,
  Archive,
  Download,
} from "lucide-react";
import { useJobs, useHealth, useComfyUIModels } from "@/hooks/useApi";
import { useComfyUI } from "@/hooks/useComfyUI";
import { useProjectStore } from "@/stores/projectStore";
import { useToastStore } from "@/stores/toastStore";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";

export function Dashboard() {
  const navigate = useNavigate();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const jobsQuery = useJobs();
  const health = useHealth();
  const comfyUI = useComfyUI();
  const modelsQuery = useComfyUIModels();
  const setCurrentJob = useProjectStore((s) => s.setCurrentJob);
  const show = useToastStore((s) => s.show);

  const jobs = jobsQuery.data?.jobs || [];
  const recentJobs = jobs.slice(0, 6);

  const handleImport = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    try {
      const res = await api.importJob(file);
      show(`已导入项目: ${res.job_id}`, "success");
      jobsQuery.refetch();
    } catch (err) {
      show(`导入失败: ${err instanceof Error ? err.message : String(err)}`, "error");
    } finally {
      e.target.value = "";
    }
  };

  const handleArchive = async () => {
    if (!confirm("确定归档 30 天未更新的项目？可在设置中恢复。")) return;
    try {
      const res = await api.archiveOldJobs(30);
      show(`已归档 ${res.count} 个项目`, "info");
      jobsQuery.refetch();
    } catch (err) {
      show(`归档失败: ${err instanceof Error ? err.message : String(err)}`, "error");
    }
  };

  const handleExport = async (jobId: string, title?: string) => {
    try {
      const res = await api.exportJob(jobId);
      const blob = new Blob([JSON.stringify(res, null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${title || jobId}.luminaforge.json`;
      a.click();
      URL.revokeObjectURL(url);
      show("项目已导出", "success");
    } catch (err) {
      show(`导出失败: ${err instanceof Error ? err.message : String(err)}`, "error");
    }
  };

  const modelCount = modelsQuery.data?.models?.length || 0;

  const stats = [
    {
      label: "ComfyUI 状态",
      value: comfyUI.connected ? "在线" : "离线",
      icon: Server,
      color: comfyUI.connected ? "text-green-500" : "text-red-500",
      detail: comfyUI.url,
    },
    {
      label: "后端服务",
      value: health.data?.status === "ok" ? "正常" : "异常",
      icon: Cpu,
      color: health.data?.status === "ok" ? "text-green-500" : "text-red-500",
      detail: health.data?.version || "v11",
    },
    {
      label: "可用模型",
      value: `${modelCount} 个`,
      icon: HardDrive,
      color: "text-blue-500",
      detail: "ComfyUI checkpoints/loras/vae",
    },
    {
      label: "ComfyUI 队列",
      value: `${comfyUI.totalQueue} 个任务`,
      icon: Film,
      color: comfyUI.totalQueue > 0 ? "text-yellow-500" : "text-gray-400",
      detail: `${comfyUI.queueRunning} 运行 / ${comfyUI.queuePending} 等待`,
    },
  ];

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-gray-900 dark:text-ink-50">
          仪表盘
        </h1>
        <p className="text-sm text-gray-500 dark:text-ink-400 mt-1">
          系统状态概览与近期项目
        </p>
      </div>

      {/* Status cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        {stats.map((stat) => (
          <div key={stat.label} className="card p-4">
            <div className="flex items-center justify-between mb-2">
              <span className="text-sm text-gray-500 dark:text-ink-400">
                {stat.label}
              </span>
              <stat.icon className={cn("w-5 h-5", stat.color)} />
            </div>
            <div className="text-xl font-bold text-gray-900 dark:text-ink-50">
              {stat.value}
            </div>
            <div className="text-xs text-gray-400 dark:text-ink-500 mt-1 truncate">
              {stat.detail}
            </div>
          </div>
        ))}
      </div>

      {/* Quick actions */}
      <div className="flex flex-wrap gap-3">
        <button
          onClick={() => navigate("/create")}
          className="btn-primary"
        >
          <Film className="w-4 h-4" />
          新建项目
        </button>
        <button
          onClick={() => navigate("/tasks")}
          className="btn-secondary"
        >
          <Clock className="w-4 h-4" />
          查看任务
        </button>
        <button
          onClick={() => fileInputRef.current?.click()}
          className="btn-secondary"
        >
          <Upload className="w-4 h-4" />
          导入项目
        </button>
        <input
          ref={fileInputRef}
          type="file"
          accept=".json"
          className="hidden"
          onChange={handleImport}
        />
        <button
          onClick={handleArchive}
          className="btn-secondary"
        >
          <Archive className="w-4 h-4" />
          归档旧项目
        </button>
      </div>

      {/* Recent projects */}
      <div>
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-lg font-semibold text-gray-900 dark:text-ink-50">
            近期项目
          </h2>
          {jobs.length > 6 && (
            <button
              onClick={() => navigate("/tasks")}
              className="text-sm text-gold-600 dark:text-gold-400 hover:underline flex items-center gap-1"
            >
              查看全部 <ArrowRight className="w-3 h-3" />
            </button>
          )}
        </div>

        {recentJobs.length === 0 ? (
          <div className="card p-12 text-center">
            <Film className="w-12 h-12 text-gray-300 dark:text-ink-700 mx-auto mb-3" />
            <p className="text-gray-500 dark:text-ink-400">
              暂无项目，点击「新建项目」开始创作
            </p>
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {recentJobs.map((job) => (
              <div
                key={job.id}
                className="card p-4 cursor-pointer hover:shadow-md transition-shadow"
                onClick={() => {
                  setCurrentJob(job.id);
                  navigate(`/storyboard/${job.id}`);
                }}
              >
                <div className="flex items-start justify-between mb-2">
                  <h3 className="font-medium text-gray-900 dark:text-ink-50 truncate flex-1">
                    {job.title || job.id}
                  </h3>
                  <div className="flex items-center gap-1">
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        handleExport(job.id, job.title);
                      }}
                      className="p-1 rounded hover:bg-gray-100 dark:hover:bg-ink-700 text-gray-400 hover:text-gold-600 dark:hover:text-gold-400 transition-colors"
                      title="导出项目"
                    >
                      <Download className="w-3.5 h-3.5" />
                    </button>
                    <StatusBadge status={job.status} />
                  </div>
                </div>
                <div className="flex items-center gap-3 text-xs text-gray-400 dark:text-ink-500">
                  {job.scene_count && (
                    <span>{job.scene_count} 个分镜</span>
                  )}
                  {job.completed_scenes !== undefined && (
                    <span>
                      完成 {job.completed_scenes}/{job.scene_count}
                    </span>
                  )}
                  {job.style && <span>{job.style}</span>}
                </div>
                {job.cover_path && (
                  <div className="mt-3 aspect-video bg-gray-100 dark:bg-ink-800 rounded-lg overflow-hidden">
                    <img
                      src={`/output/${job.cover_path}`}
                      alt={job.title}
                      className="w-full h-full object-cover"
                    />
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function StatusBadge({ status }: { status: string }) {
  const isComplete = status === "complete" || status === "completed";
  const isError = status === "error" || status === "failed";
  const isRunning = status === "running" || status === "generating";

  if (isComplete) {
    return (
      <span className="badge-success">
        <CheckCircle2 className="w-3 h-3 mr-1" />
        完成
      </span>
    );
  }
  if (isError) {
    return (
      <span className="badge-error">
        <XCircle className="w-3 h-3 mr-1" />
        失败
      </span>
    );
  }
  if (isRunning) {
    return (
      <span className="badge-warning">
        <Clock className="w-3 h-3 mr-1" />
        进行中
      </span>
    );
  }
  return <span className="badge-info">{status}</span>;
}
