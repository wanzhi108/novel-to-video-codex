/**
 * REST API 客户端 — 对接后端 51 个 FastAPI 端点
 * Base URL: http://localhost:8190 (dev proxy)
 */

import type {
  BGMItem,
  Character,
  ComfyUIModel,
  ComfyUIQueue,
  ComfyUIStatus,
  GenerateRequest,
  HealthStatus,
  JobState,
  JobSummary,
  Scene,
  TTSVoice,
} from "./types";

const BASE = ""; // Vite proxy handles /api → :8190

async function request<T>(
  url: string,
  options?: RequestInit
): Promise<T> {
  const isFormData = options?.body instanceof FormData;
  const res = await fetch(`${BASE}${url}`, {
    ...options,
    headers: isFormData
      ? { ...options?.headers }
      : {
          "Content-Type": "application/json",
          ...options?.headers,
        },
  });
  if (!res.ok) {
    const errorBody = await res.text();
    throw new Error(`HTTP ${res.status}: ${errorBody}`);
  }
  return res.json() as Promise<T>;
}

// ==================== 系统 ====================

export const api = {
  // /api/health
  health: () => request<HealthStatus>("/api/health"),

  // /api/comfyui-check
  comfyuiCheck: () => request<ComfyUIStatus>("/api/comfyui-check"),

  // /api/ffmpeg-check
  ffmpegCheck: () =>
    request<{ status: string; available: boolean }>("/api/ffmpeg-check"),

  // ==================== 模型 ====================

  // /api/comfyui-models
  comfyuiModels: () =>
    request<{ models: ComfyUIModel[]; checkpoints: string[] }>("/api/comfyui-models"),

  // /api/models
  models: () => request<Record<string, unknown>>("/api/models"),

  // /api/comfyui-queue
  comfyuiQueue: () => request<ComfyUIQueue>("/api/comfyui-queue"),

  // ==================== 任务 ====================

  // /api/jobs
  jobs: () => request<{ jobs: JobSummary[] }>("/api/jobs"),

  // /api/jobs/{job_id}/export (v12.1)
  exportJob: (jobId: string) =>
    request<{ job: JobState }>(`/api/jobs/${jobId}/export`),

  // /api/jobs/import (v12.1)
  importJob: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<{ job_id: string; status: string }>("/api/jobs/import", {
      method: "POST",
      body: form,
    });
  },

  // /api/jobs/archive (v12.1)
  archiveOldJobs: (days?: number) =>
    request<{ archived: string[]; count: number }>("/api/jobs/archive", {
      method: "POST",
      body: JSON.stringify({ days }),
    }),

  // /api/jobs/archived (v12.1)
  archivedJobs: () => request<{ jobs: JobSummary[] }>("/api/jobs/archived"),

  // /api/jobs/archived/{job_id}/restore (v12.1)
  restoreArchivedJob: (jobId: string) =>
    request<{ job_id: string; status: string }>(
      `/api/jobs/archived/${jobId}/restore`,
      { method: "POST" }
    ),

  // /api/scenes/{job_id}/export-prompts (v12.1)
  exportScenePrompts: (jobId: string, format: "txt" | "json" = "txt") =>
    request<{ content?: string; prompts?: unknown[]; title?: string; format?: string }>(
      `/api/scenes/${jobId}/export-prompts?format=${format}`
    ),

  // /api/status/{job_id}
  jobStatus: (jobId: string) =>
    request<JobState>(`/api/status/${jobId}`),

  // /api/job/{job_id} (DELETE)
  deleteJob: (jobId: string) =>
    request<{ status: string }>(`/api/job/${jobId}`, { method: "DELETE" }),

  // ==================== 生成 ====================

  // /api/generate — 一键生成 (上传文本 + 生成全流程)
  generate: (req: GenerateRequest) =>
    request<{ job_id: string; status: string }>("/api/generate", {
      method: "POST",
      body: JSON.stringify(req),
    }),

  // /api/start-generation — 分步生成 (已有 job_id, 启动管线)
  startGeneration: (jobId: string) =>
    request<{ status: string }>("/api/start-generation", {
      method: "POST",
      body: JSON.stringify({ job_id: jobId }),
    }),

  // /api/cancel-generation
  cancelGeneration: (jobId: string) =>
    request<{ status: string }>("/api/cancel-generation", {
      method: "POST",
      body: JSON.stringify({ job_id: jobId }),
    }),

  // /api/run-pipeline
  runPipeline: (jobId: string) =>
    request<{ status: string }>("/api/run-pipeline", {
      method: "POST",
      body: JSON.stringify({ job_id: jobId }),
    }),

  // ==================== 分镜 ====================

  // /api/scenes/{job_id}
  scenes: (jobId: string) =>
    request<{ scenes: Scene[] }>(`/api/scenes/${jobId}`),

  // /api/scene/{job_id}/{scene_id}/retry
  retryScene: (jobId: string, sceneId: number) =>
    request<{ status: string }>(`/api/scene/${jobId}/${sceneId}/retry`, {
      method: "POST",
    }),

  // /api/scene/{job_id}/{scene_id}/skip
  skipScene: (jobId: string, sceneId: number) =>
    request<{ status: string }>(`/api/scene/${jobId}/${sceneId}/skip`, {
      method: "POST",
    }),

  // /api/scenes/{job_id}/batch-edit (new)
  batchEditScenes: (
    jobId: string,
    sceneIds: number[],
    fields: Record<string, unknown>
  ) =>
    request<{ status: string; updated: number }>(
      `/api/scenes/${jobId}/batch-edit`,
      {
        method: "POST",
        body: JSON.stringify({ scene_ids: sceneIds, fields }),
      }
    ),

  // /api/scenes/{job_id}/reorder (new)
  reorderScenes: (jobId: string, sceneIds: number[]) =>
    request<{ status: string }>(`/api/scenes/${jobId}/reorder`, {
      method: "POST",
      body: JSON.stringify({ scene_ids: sceneIds }),
    }),

  // /api/retry-scene/{job_id}/{scene_id} (legacy)
  retrySceneLegacy: (jobId: string, sceneId: number) =>
    request<{ status: string }>(`/api/retry-scene/${jobId}/${sceneId}`, {
      method: "POST",
    }),

  // /api/debug-prompts/{job_id}
  debugPrompts: (jobId: string) =>
    request<Record<string, unknown>>(`/api/debug-prompts/${jobId}`),

  // /api/scene-error/{job_id}
  sceneError: (jobId: string) =>
    request<{ error: string }>(`/api/scene-error/${jobId}`),

  // ==================== 媒体 ====================

  // /api/scene-image/{job_id}/{scene_id}
  sceneImageUrl: (jobId: string, sceneId: number) =>
    `/api/scene-image/${jobId}/${sceneId}`,

  // /api/scene-video/{job_id}/{scene_id}
  sceneVideoUrl: (jobId: string, sceneId: number) =>
    `/api/scene-video/${jobId}/${sceneId}`,

  // /api/scene-audio/{job_id}/{scene_id}
  sceneAudioUrl: (jobId: string, sceneId: number) =>
    `/api/scene-audio/${jobId}/${sceneId}`,

  // /api/merged-video/{job_id}
  mergedVideoUrl: (jobId: string) => `/api/merged-video/${jobId}`,

  // /api/remerge/{job_id}
  rememege: (jobId: string) =>
    request<{ status: string; merged_video?: string }>(
      `/api/remerge/${jobId}`,
      { method: "POST" }
    ),

  // /api/merge-videos/{job_id}
  mergeVideos: (jobId: string) =>
    request<{ status: string; merged_video?: string }>(
      `/api/merge-videos/${jobId}`,
      { method: "POST" }
    ),

  // ==================== 角色 ====================

  // /api/characters/{job_id}
  characters: (jobId: string) =>
    request<{ characters: Character[] }>(`/api/characters/${jobId}`),

  // /api/analyze-characters
  analyzeCharacters: (jobId: string) =>
    request<{ status: string; characters?: Character[] }>(
      "/api/analyze-characters",
      { method: "POST", body: JSON.stringify({ job_id: jobId }) }
    ),

  // /api/update-character-voice
  updateCharacterVoice: (
    jobId: string,
    characterName: string,
    voiceId: string,
    voiceName: string
  ) =>
    request<{ status: string }>("/api/update-character-voice", {
      method: "POST",
      body: JSON.stringify({
        job_id: jobId,
        character_name: characterName,
        voice_id: voiceId,
        voice_name: voiceName,
      }),
    }),

  // ==================== TTS ====================

  // /api/tts-voices
  ttsVoices: () => request<{ voices: TTSVoice[] }>("/api/tts-voices"),

  // /api/preview-tts
  previewTTS: (text: string, voice: string, rate?: string) =>
    request<{ status: string }>("/api/preview-tts", {
      method: "POST",
      body: JSON.stringify({ text, voice, rate: rate || "+0%" }),
    }),

  // /api/tts-preview-audio
  ttsPreviewAudioUrl: (jobId: string) =>
    `/api/tts-preview-audio?job_id=${jobId}`,

  // ==================== 可灵 ====================

  // /api/generate-kling-face
  generateKlingFace: (jobId: string, apiKey: string, description: string) =>
    request<{ status: string; image_path?: string }>(
      "/api/generate-kling-face",
      {
        method: "POST",
        body: JSON.stringify({
          job_id: jobId,
          kling_api_key: apiKey,
          kling_face_description: description,
        }),
      }
    ),

  // /api/kling-face-preview/{job_id}
  klingFacePreviewUrl: (jobId: string) =>
    `/api/kling-face-preview/${jobId}`,

  // ==================== 分镜分析 ====================

  // /api/generate-storyboard
  generateStoryboard: (jobId: string, deepseekKey: string) =>
    request<{ status: string; scene_count?: number }>(
      "/api/generate-storyboard",
      {
        method: "POST",
        body: JSON.stringify({ job_id: jobId, deepseek_key: deepseekKey }),
      }
    ),

  // /api/generate-prompts
  generatePrompts: (jobId: string) =>
    request<{ status: string }>("/api/generate-prompts", {
      method: "POST",
      body: JSON.stringify({ job_id: jobId }),
    }),

  // ==================== 上传 ====================

  // /api/upload-novel
  uploadNovel: (file: File) => {
    const formData = new FormData();
    formData.append("file", file);
    return request<{ status: string; text: string; filename: string }>(
      "/api/upload-novel",
      { method: "POST", body: formData, headers: {} }
    );
  },

  // /api/upload-text
  uploadText: (text: string, title?: string) =>
    request<{ status: string; job_id?: string }>("/api/upload-text", {
      method: "POST",
      body: JSON.stringify({ text, title }),
    }),

  // /api/upload-pulid-ref
  uploadPulidRef: (file: File) => {
    const formData = new FormData();
    formData.append("file", file);
    return request<{ status: string; path: string }>("/api/upload-pulid-ref", {
      method: "POST",
      body: formData,
      headers: {},
    });
  },

  // ==================== 设置 ====================

  // /api/update-settings
  updateSettings: (settings: Record<string, unknown>) =>
    request<{ status: string }>("/api/update-settings", {
      method: "POST",
      body: JSON.stringify(settings),
    }),

  // /api/launcher-config — v12.1: launcher 启动配置（auto_cosyvoice 等）
  getLauncherConfig: () =>
    request<{ status: string; config: Record<string, unknown> }>(
      "/api/launcher-config",
      { method: "GET" }
    ),

  updateLauncherConfig: (config: Record<string, unknown>) =>
    request<{ status: string; config: Record<string, unknown> }>(
      "/api/launcher-config",
      { method: "POST", body: JSON.stringify(config) }
    ),

  // ==================== BGM ====================

  // /api/bgm-list
  bgmList: () => request<{ bgms: BGMItem[] }>("/api/bgm-list"),

  // /api/bgm-upload
  bgmUpload: (file: File, mood?: string) => {
    const formData = new FormData();
    formData.append("file", file);
    if (mood) formData.append("mood", mood);
    return request<{ status: string; name: string }>("/api/bgm-upload", {
      method: "POST",
      body: formData,
      headers: {},
    });
  },

  // ==================== QA ====================

  // /api/qa-test/{job_id}
  qaTest: (jobId: string) =>
    request<{ status: string; results?: unknown[]; passed?: boolean }>(
      `/api/qa-test/${jobId}`,
      { method: "POST" }
    ),

  // /api/qa-fix/{job_id}
  qaFix: (jobId: string) =>
    request<{ status: string }>(`/api/qa-fix/${jobId}`, { method: "POST" }),

  // /api/qa-settings
  qaSettings: (settings: Record<string, unknown>) =>
    request<{ status: string }>("/api/qa-settings", {
      method: "POST",
      body: JSON.stringify(settings),
    }),

  // ==================== 其他 ====================

  // /api/auto-pipeline/{job_id}
  autoPipeline: (jobId: string) =>
    request<{ status: string }>(`/api/auto-pipeline/${jobId}`, {
      method: "POST",
    }),

  // /api/create-job
  createJob: (novelText: string, deepseekKey: string, title?: string) =>
    request<{ job_id: string; status: string }>("/api/create-job", {
      method: "POST",
      body: JSON.stringify({
        novel_text: novelText,
        deepseek_key: deepseekKey,
        novel_title: title || "",
      }),
    }),

  // /api/split-dialogues
  splitDialogues: (jobId: string) =>
    request<{ status: string }>("/api/split-dialogues", {
      method: "POST",
      body: JSON.stringify({ job_id: jobId }),
    }),

  // /api/update-smart-dubbing
  updateSmartDubbing: (jobId: string, enabled: boolean) =>
    request<{ status: string }>("/api/update-smart-dubbing", {
      method: "POST",
      body: JSON.stringify({ job_id: jobId, enabled }),
    }),

  // /api/regenerate-images
  regenerateImages: (jobId: string, sceneIds?: number[]) =>
    request<{ status: string }>("/api/regenerate-images", {
      method: "POST",
      body: JSON.stringify({ job_id: jobId, scene_ids: sceneIds }),
    }),

  // /api/test-scene
  testScene: (jobId: string, sceneId: number) =>
    request<{ status: string }>("/api/test-scene", {
      method: "POST",
      body: JSON.stringify({ job_id: jobId, scene_id: sceneId }),
    }),
};
