/**
 * TypeScript 类型定义 — 对应后端 Pydantic 模型
 * Source: app/models.py
 */

// ==================== 数据模型 ====================

export interface Character {
  name: string;
  gender: string; // 男/女/未知
  age_range: string; // 儿童/少年/青年/中年/老年
  personality: string;
  role_type: string; // 主角/配角/反派/旁白/路人
  voice_id: string; // Edge-TTS 声音 ID
  voice_name: string; // 声音中文名
  cosyvoice_voice: string; // CosyVoice2 speaker 名
  speaking_style: string;
  // v5.3: 外貌/身体/着装特征
  appearance: string;
  body_type: string;
  clothing: string;
  kling_prompt: string;
  // 扩展字段 (阶段2新增)
  voice_candidates?: string[];
  importance_level?: string; // primary/secondary/antagonist/extra
  // v12.0: 角色素材库
  material_library_path?: string; // 多角度参考图目录路径
}

export interface Scene {
  id: number;
  subtitle_text: string;
  subtitle_display: string;
  title: string;
  description: string;
  characters: string;
  speaking_characters: string[];
  setting: string;
  mood: string;
  camera: string;
  duration: string; // "5s"
  image_prompt: string;
  video_prompt: string;
  negative_prompt: string;
  image_path: string | null;
  video_path: string | null;
  final_video_path: string | null;
  audio_path: string | null;
  audio_duration: number;
  subtitle_timings: SubtitleTiming[];
  status: SceneStatus;
  error_msg: string;
  comfyui_progress: number;
  // v5.0 好莱坞级分镜字段
  emotional_intensity: number; // 1-10
  visual_motif_note: string;
  continuity_note: string;
  story_act: string; // act1/act2/act3
  story_position: string;
  storytelling_rhythm: string;
  // v7.0 VMix 美学标签
  vmix_tags: Record<string, string>;
  // v7.2 视频引擎扩展
  video_mode_used: string;
  parallax_layers: string[];
  end_image_path: string | null;
}

export interface SubtitleTiming {
  start: number;
  end: number;
  text: string;
  speaker?: string;
}

export type SceneStatus =
  | "pending"
  | "generating"
  | "image_done"
  | "video_done"
  | "audio_done"
  | "completed"
  | "error"
  | "skipped";

export interface JobState {
  id: string;
  novel_text: string;
  novel_title: string;
  deepseek_key: string;
  scenes: Scene[];
  characters: Character[];
  current_step: string;
  progress: Record<string, unknown>;
  error: string;
  cancel_flag: boolean;
  story_structure: Record<string, unknown>;
  // 模型选择
  img_checkpoint: string;
  vid_checkpoint: string;
  // Hires.fix
  use_hires_fix: boolean;
  // IP-Adapter
  use_ipadapter: boolean;
  ipadapter_model: string;
  ipadapter_reference_image: string;
  clip_vision_model: string;
  // PuLID
  use_pulid: boolean;
  pulid_model: string;
  pulid_reference_image: string;
  kling_api_key: string;
  kling_face_description: string;
  // Wan2.1
  use_wan21: boolean;
  wan21_model: string;
  wan21_t5_encoder: string;
  wan21_vae: string;
  wan21_clip_vision: string;
  // Ken Burns
  use_ken_burns: boolean;
  // Dual frame
  use_dual_frame: boolean;
  // TTS + 字幕
  tts_enabled: boolean;
  tts_voice: string;
  tts_rate: string;
  video_mode: string; // "local" | "cloud_t2v" | "ltx_t2v"
  tts_volume: string;
  narrator_voice: string;
  smart_dubbing: boolean;
  use_ass_subtitles: boolean;
  // 后期处理
  use_color_grading: boolean;
  use_fade_transition: boolean;
  use_manga_fx: boolean;
  use_multi_shot: boolean;
  // QA
  qa_enabled: boolean;
  qa_results: Record<string, unknown>[];
  qa_passed: boolean;
  // 风格
  style: string;
  subject_preference: string;
  // 预分析
  character_analysis: Record<string, unknown> | null;
  environment_analysis: Record<string, unknown> | null;
  // 输出
  merged_video_path: string;
  cover_path: string;
}

export interface GenerateRequest {
  novel_text: string;
  novel_title?: string;
  deepseek_key?: string;
  img_checkpoint?: string;
  vid_checkpoint?: string;
  use_hires_fix?: boolean;
  use_ipadapter?: boolean;
  use_pulid?: boolean;
  pulid_reference_image?: string;
  kling_api_key?: string;
  kling_face_description?: string;
  use_wan21?: boolean;
  use_color_grading?: boolean;
  use_fade_transition?: boolean;
  style?: string;
  use_ken_burns?: boolean;
  use_dual_frame?: boolean;
  use_manga_fx?: boolean;
  use_multi_shot?: boolean;
  video_mode?: string;
  tts_enabled?: boolean;
  smart_dubbing?: boolean;
}

// ==================== API 响应 ====================

export interface ApiResponse<T = unknown> {
  [key: string]: unknown;
  error?: string;
  message?: string;
  job_id?: string;
  status?: string;
  data?: T;
}

export interface JobSummary {
  id: string;
  title: string;
  status: string;
  created_at?: string;
  scene_count?: number;
  completed_scenes?: number;
  merged_video_path?: string;
  cover_path?: string;
  style?: string;
}

export interface HealthStatus {
  status: string;
  comfyui_url: string;
  comfyui_connected?: boolean;
  ffmpeg_available?: boolean;
  tts_available?: boolean;
  version?: string;
}

export interface ComfyUIStatus {
  status: string;
  url: string;
  models?: string[];
  queue?: number;
  running?: number;
}

export interface ComfyUIModel {
  name: string;
  type: string; // checkpoint / lora / vae / clip_vision
  size?: number;
  path?: string;
}

export interface ComfyUIQueue {
  queue_running: unknown[];
  queue_pending: unknown[];
}

export interface TTSVoice {
  id: string;
  name: string;
  gender: string;
  locale: string;
  preview_url?: string;
}

export interface BGMItem {
  name: string;
  path: string;
  mood?: string;
  duration?: number;
}

// ==================== WebSocket 消息 ====================

export type WSMessageType =
  | "comfyui_progress"
  | "kling_face_progress"
  | "kling_face_done"
  | "kling_progress"
  | "step"
  | "story_structure_done"
  | "storyboard_done"
  | "character_analysis"
  | "scene_status"
  | "merging"
  | "job_complete"
  | "error"
  | "qa"
  | "qa_fix"
  | "safety_warning"
  | "prompts_progress";

export interface WSMessage {
  type: WSMessageType;
  [key: string]: unknown;
  // Common fields
  step?: string;
  status?: string;
  scene_id?: number;
  progress?: number;
  message?: string;
  error?: string;
  merged_video?: string;
  scenes?: number;
}
