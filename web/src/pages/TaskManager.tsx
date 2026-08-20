import { useNavigate } from "react-router-dom";
import {
  ListTodo,
  Trash2,
  Download,
  XCircle,
  RefreshCw,
  Film,
  Clock,
  CheckCircle2,
  XCircle as XCircleIcon,
  Loader2,
  Eye,
} from "lucide-react";
import toast from "react-hot-toast";
import {
  useJobs,
  useDeleteJob,
  useCancelGeneration,
  useRemerge,
} from "@/hooks/useApi";
import { useProjectStore } from "@/stores/projectStore";
import type { JobSummary } from "@/lib/types";

export function TaskManager() {
  const navigate = useNavigate();
  const jobsQuery = useJobs();
  const deleteMutation = useDeleteJob();
  const cancelMutation = useCancelGeneration();
  const remergeMutation = useRemerge();
  const setCurrentJob = useProjectStore((s) => s.setCurrentJob);

  const jobs = jobsQuery.data?.jobs || [];

  const handleDelete = (jobId: string) => {
    if (!confirm("确定删除此任务？此操作不可撤销。")) return;
    deleteMutation.mutate(jobId, {
      onSuccess: () => toast.success("任务已删除"),
      onError: () => toast.error("删除失败"),
    });
  };

  const handleCancel = (jobId: string) => {
    cancelMutation.mutate(jobId, {
      onSuccess: () => toast.success("任务已取消"),
      onError: () => toast.error("取消失败"),
    });
  };

  const handleRemerge = (jobId: string) => {
    remergeMutation.mutate(jobId, {
      onSuccess: () => toast.success("重新合并已启动"),
      onError: () => toast.error("合并失败"),
    });
  };

  const handleDownload = (jobId: string) => {
    window.open(`/api/merged-video/${jobId}`, "_blank");
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 dark:text-ink-50">
            任务管理
          </h1>
          <p className="text-sm text-gray-500 dark:text-ink-400 mt-1">
            {jobs.length} 个任务
          </p>
        </div>
        <button
          onClick={() => jobsQuery.refetch()}
          className="btn-ghost"
        >
          <RefreshCw className="w-4 h-4" />
          刷新
        </button>
      </div>

      {/* Task list */}
      {jobsQuery.isLoading ? (
        <div className="flex items-center justify-center h-48">
          <Loader2 className="w-8 h-8 text-gold-500 animate-spin" />
        </div>
      ) : jobs.length === 0 ? (
        <div className="card p-12 text-center">
          <ListTodo className="w-12 h-12 text-gray-300 dark:text-ink-700 mx-auto mb-3" />
          <p className="text-gray-500 dark:text-ink-400">
            暂无任务
          </p>
        </div>
      ) : (
        <div className="space-y-3">
          {jobs.map((job) => (
            <TaskCard
              key={job.id}
              job={job}
              onView={() => {
                setCurrentJob(job.id);
                navigate(`/storyboard/${job.id}`);
              }}
              onCancel={() => handleCancel(job.id)}
              onDelete={() => handleDelete(job.id)}
              onRemerge={() => handleRemerge(job.id)}
              onDownload={() => handleDownload(job.id)}
              isCancelling={cancelMutation.isPending}
              isRemerging={remergeMutation.isPending}
            />
          ))}
        </div>
      )}
    </div>
  );
}

function TaskCard({
  job,
  onView,
  onCancel,
  onDelete,
  onRemerge,
  onDownload,
  isCancelling,
  isRemerging,
}: {
  job: JobSummary;
  onView: () => void;
  onCancel: () => void;
  onDelete: () => void;
  onRemerge: () => void;
  onDownload: () => void;
  isCancelling: boolean;
  isRemerging: boolean;
}) {
  const isRunning =
    job.status === "running" || job.status === "generating";
  const isComplete =
    job.status === "complete" || job.status === "completed";
  const isError = job.status === "error" || job.status === "failed";

  const completedScenes = job.completed_scenes || 0;
  const totalScenes = job.scene_count || 0;
  const progress =
    totalScenes > 0 ? Math.round((completedScenes / totalScenes) * 100) : 0;

  return (
    <div className="card p-4">
      <div className="flex items-start gap-4">
        {/* Cover thumbnail */}
        <div className="flex-shrink-0 w-20 h-20 rounded-lg overflow-hidden bg-gray-100 dark:bg-ink-800">
          {job.cover_path ? (
            <img
              src={`/output/${job.cover_path}`}
              alt={job.title}
              className="w-full h-full object-cover"
            />
          ) : (
            <div className="flex items-center justify-center w-full h-full">
              <Film className="w-8 h-8 text-gray-300 dark:text-ink-700" />
            </div>
          )}
        </div>

        {/* Content */}
        <div className="flex-1 min-w-0 space-y-2">
          <div className="flex items-center gap-2">
            <h3 className="font-medium text-gray-900 dark:text-ink-50 truncate">
              {job.title || job.id}
            </h3>
            <StatusIcon
              isRunning={isRunning}
              isComplete={isComplete}
              isError={isError}
            />
          </div>

          <div className="flex items-center gap-3 text-xs text-gray-400 dark:text-ink-500">
            <span className="font-mono">{job.id.slice(0, 8)}</span>
            {totalScenes > 0 && (
              <span>
                {completedScenes}/{totalScenes} 分镜
              </span>
            )}
            {job.style && <span>{job.style}</span>}
          </div>

          {/* Progress bar */}
          {isRunning && totalScenes > 0 && (
            <div className="w-full bg-gray-200 dark:bg-ink-800 rounded-full h-1.5">
              <div
                className="bg-gold-500 h-1.5 rounded-full transition-all"
                style={{ width: `${progress}%` }}
              />
            </div>
          )}

          {/* Error message */}
          {isError && (
            <p className="text-xs text-red-500">任务执行出错</p>
          )}
        </div>

        {/* Actions */}
        <div className="flex items-center gap-1.5 flex-shrink-0">
          <button
            onClick={onView}
            className="btn-ghost text-xs"
            title="查看分镜"
          >
            <Eye className="w-4 h-4" />
          </button>

          {isRunning && (
            <button
              onClick={onCancel}
              disabled={isCancelling}
              className="btn-ghost text-xs text-red-500"
              title="取消任务"
            >
              {isCancelling ? (
                <Loader2 className="w-4 h-4 animate-spin" />
              ) : (
                <XCircle className="w-4 h-4" />
              )}
            </button>
          )}

          {isComplete && (
            <>
              <button
                onClick={onDownload}
                className="btn-ghost text-xs text-green-500"
                title="下载视频"
              >
                <Download className="w-4 h-4" />
              </button>
              <button
                onClick={onRemerge}
                disabled={isRemerging}
                className="btn-ghost text-xs"
                title="重新合并"
              >
                {isRemerging ? (
                  <Loader2 className="w-4 h-4 animate-spin" />
                ) : (
                  <RefreshCw className="w-4 h-4" />
                )}
              </button>
            </>
          )}

          <button
            onClick={onDelete}
            className="btn-ghost text-xs text-red-500"
            title="删除任务"
          >
            <Trash2 className="w-4 h-4" />
          </button>
        </div>
      </div>
    </div>
  );
}

function StatusIcon({
  isRunning,
  isComplete,
  isError,
}: {
  isRunning: boolean;
  isComplete: boolean;
  isError: boolean;
}) {
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
        <XCircleIcon className="w-3 h-3 mr-1" />
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
  return <span className="badge-info">{isRunning ? "" : ""}</span>;
}
