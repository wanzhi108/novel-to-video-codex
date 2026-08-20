import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function formatTime(seconds: number): string {
  if (seconds < 1) return "0s";
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds % 60);
  return m > 0 ? `${m}m${s}s` : `${s}s`;
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(2)} GB`;
}

export function getSceneStatusColor(status: string): string {
  const map: Record<string, string> = {
    pending: "badge-info",
    generating: "badge-warning",
    image_done: "badge-info",
    video_done: "badge-info",
    audio_done: "badge-info",
    completed: "badge-success",
    error: "badge-error",
    skipped: "badge-warning",
  };
  return map[status] || "badge-info";
}

export function getSceneStatusText(status: string): string {
  const map: Record<string, string> = {
    pending: "等待中",
    generating: "生成中",
    image_done: "图片完成",
    video_done: "视频完成",
    audio_done: "音频完成",
    completed: "已完成",
    error: "错误",
    skipped: "已跳过",
  };
  return map[status] || status;
}
