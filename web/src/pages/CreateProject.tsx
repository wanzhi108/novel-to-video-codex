import { useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  Upload,
  FileText,
  Settings2,
  Sparkles,
  ChevronRight,
  ChevronLeft,
  Loader2,
} from "lucide-react";
import toast from "react-hot-toast";
import { useGenerate } from "@/hooks/useApi";
import { useModelList } from "@/hooks/useModelList";
import { useSettingsStore } from "@/stores/settingsStore";
import { useProjectStore } from "@/stores/projectStore";
import { cn } from "@/lib/utils";
import type { GenerateRequest } from "@/lib/types";

const STEPS = ["上传文本", "模型选择", "高级配置", "确认生成"];

const STYLE_PRESETS = [
  { value: "cinematic", label: "电影感", desc: "好莱坞级调色，质感厚重" },
  { value: "anime", label: "动漫风", desc: "日式动画色彩，明亮鲜艳" },
  { value: "realistic", label: "写实风", desc: "照片级真实感" },
  { value: "watercolor", label: "水彩风", desc: "柔和水彩画风格" },
  { value: "ink", label: "水墨风", desc: "中国传统水墨画" },
];

export function CreateProject() {
  const navigate = useNavigate();
  const [step, setStep] = useState(0);
  const [novelText, setNovelText] = useState("");
  const [novelTitle, setNovelTitle] = useState("");
  const generateMutation = useGenerate();
  const models = useModelList();
  const settings = useSettingsStore();
  const setCurrentJob = useProjectStore((s) => s.setCurrentJob);

  const handleFileUpload = async (file: File) => {
    try {
      const text = await file.text();
      setNovelText(text);
      setNovelTitle(file.name.replace(/\.[^.]+$/, ""));
      toast.success(`已加载: ${file.name}`);
    } catch {
      toast.error("文件读取失败");
    }
  };

  const handleGenerate = async () => {
    if (!novelText.trim()) {
      toast.error("请输入或上传小说文本");
      return;
    }

    const req: GenerateRequest = {
      novel_text: novelText,
      novel_title: novelTitle,
      deepseek_key: settings.deepseekKey,
      img_checkpoint: settings.imgCheckpoint,
      vid_checkpoint: settings.vidCheckpoint,
      use_hires_fix: settings.useHiresFix,
      use_ipadapter: settings.useIpadapter,
      use_pulid: settings.usePulid,
      kling_api_key: settings.klingApiKey,
      use_wan21: settings.useWan21,
      use_color_grading: settings.useColorGrading,
      use_fade_transition: settings.useFadeTransition,
      style: settings.style,
      use_ken_burns: settings.useKenBurns,
      use_dual_frame: settings.useDualFrame,
      use_manga_fx: settings.useMangaFx,
      use_multi_shot: settings.useMultiShot,
      video_mode: settings.videoMode,
      tts_enabled: settings.ttsEnabled,
      smart_dubbing: settings.smartDubbing,
    };

    try {
      const result = await generateMutation.mutateAsync(req);
      if (result.job_id) {
        setCurrentJob(result.job_id);
        toast.success("项目已创建，开始生成...");
        navigate(`/storyboard/${result.job_id}`);
      }
    } catch (err) {
      toast.error(`生成失败: ${err instanceof Error ? err.message : "未知错误"}`);
    }
  };

  const canProceed = () => {
    switch (step) {
      case 0:
        return novelText.trim().length > 0;
      case 1:
        return true; // Model selection has defaults
      case 2:
        return true; // Advanced config is optional
      case 3:
        return true;
      default:
        return false;
    }
  };

  return (
    <div className="max-w-4xl mx-auto space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-gray-900 dark:text-ink-50">
          创建项目
        </h1>
        <p className="text-sm text-gray-500 dark:text-ink-400 mt-1">
          从文本到视频，四步完成创作
        </p>
      </div>

      {/* Step indicator */}
      <div className="flex items-center gap-2">
        {STEPS.map((label, i) => (
          <div key={i} className="flex items-center gap-2 flex-1">
            <div
              className={cn(
                "flex items-center gap-2 px-3 py-1.5 rounded-lg text-sm font-medium transition-colors",
                i === step
                  ? "bg-gold-500 text-white"
                  : i < step
                  ? "bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400"
                  : "bg-gray-100 text-gray-400 dark:bg-ink-800 dark:text-ink-500"
              )}
            >
              <span className="w-5 h-5 flex items-center justify-center rounded-full text-xs">
                {i < step ? "✓" : i + 1}
              </span>
              {label}
            </div>
            {i < STEPS.length - 1 && (
              <ChevronRight className="w-4 h-4 text-gray-300 dark:text-ink-700" />
            )}
          </div>
        ))}
      </div>

      {/* Step content */}
      <div className="card p-6 min-h-[400px]">
        {step === 0 && (
          <div className="space-y-4">
            <div className="flex items-center gap-2 mb-4">
              <FileText className="w-5 h-5 text-gold-500" />
              <h2 className="text-lg font-semibold">输入小说文本</h2>
            </div>

            {/* Upload area */}
            <label className="flex flex-col items-center justify-center border-2 border-dashed border-gray-300 dark:border-ink-700 rounded-lg p-8 cursor-pointer hover:border-gold-400 transition-colors">
              <Upload className="w-8 h-8 text-gray-400 mb-2" />
              <span className="text-sm text-gray-500 dark:text-ink-400">
                点击或拖拽上传 .txt 文件
              </span>
              <input
                type="file"
                accept=".txt,.md"
                className="hidden"
                onChange={(e) => {
                  const file = e.target.files?.[0];
                  if (file) handleFileUpload(file);
                }}
              />
            </label>

            {/* Title input */}
            <div>
              <label className="text-sm font-medium text-gray-700 dark:text-ink-300 mb-1 block">
                标题（可选）
              </label>
              <input
                type="text"
                value={novelTitle}
                onChange={(e) => setNovelTitle(e.target.value)}
                placeholder="给项目起个名字..."
                className="input"
              />
            </div>

            {/* Text area */}
            <div>
              <label className="text-sm font-medium text-gray-700 dark:text-ink-300 mb-1 block">
                小说文本
              </label>
              <textarea
                value={novelText}
                onChange={(e) => setNovelText(e.target.value)}
                placeholder="粘贴或输入小说文本..."
                rows={10}
                className="input font-mono text-sm resize-y"
              />
              <div className="text-xs text-gray-400 mt-1">
                {novelText.length} 字
              </div>
            </div>
          </div>
        )}

        {step === 1 && (
          <div className="space-y-4">
            <div className="flex items-center gap-2 mb-4">
              <Settings2 className="w-5 h-5 text-gold-500" />
              <h2 className="text-lg font-semibold">选择模型</h2>
            </div>

            {/* Image model */}
            <div>
              <label className="text-sm font-medium text-gray-700 dark:text-ink-300 mb-1 block">
                图像模型 (Checkpoint)
              </label>
              <select
                value={settings.imgCheckpoint}
                onChange={(e) => settings.update({ imgCheckpoint: e.target.value })}
                className="input"
              >
                {models.checkpoints.length > 0 ? (
                  models.checkpoints.map((m) => (
                    <option key={m.name} value={m.name}>
                      {m.name}
                    </option>
                  ))
                ) : (
                  <option value={settings.imgCheckpoint}>
                    {settings.imgCheckpoint} (默认)
                  </option>
                )}
              </select>
            </div>

            {/* Video model */}
            <div>
              <label className="text-sm font-medium text-gray-700 dark:text-ink-300 mb-1 block">
                视频模型
              </label>
              <select
                value={settings.vidCheckpoint}
                onChange={(e) => settings.update({ vidCheckpoint: e.target.value })}
                className="input"
              >
                <option value={settings.vidCheckpoint}>
                  {settings.vidCheckpoint} (默认)
                </option>
              </select>
            </div>

            {/* Style preset */}
            <div>
              <label className="text-sm font-medium text-gray-700 dark:text-ink-300 mb-2 block">
                风格预设
              </label>
              <div className="grid grid-cols-2 md:grid-cols-3 gap-2">
                {STYLE_PRESETS.map((preset) => (
                  <button
                    key={preset.value}
                    onClick={() => settings.update({ style: preset.value })}
                    className={cn(
                      "p-3 rounded-lg border text-left transition-colors",
                      settings.style === preset.value
                        ? "border-gold-400 bg-gold-50 dark:bg-gold-900/20"
                        : "border-gray-200 dark:border-ink-700 hover:border-gray-300"
                    )}
                  >
                    <div className="font-medium text-sm">{preset.label}</div>
                    <div className="text-xs text-gray-400 mt-0.5">
                      {preset.desc}
                    </div>
                  </button>
                ))}
              </div>
            </div>

            {/* Character consistency */}
            <div className="space-y-2">
              <label className="text-sm font-medium text-gray-700 dark:text-ink-300 block">
                角色一致性
              </label>
              <div className="flex gap-4">
                <label className="flex items-center gap-2 text-sm">
                  <input
                    type="checkbox"
                    checked={settings.usePulid}
                    onChange={(e) => settings.update({ usePulid: e.target.checked })}
                    className="rounded"
                  />
                  PuLID (最强)
                </label>
                <label className="flex items-center gap-2 text-sm">
                  <input
                    type="checkbox"
                    checked={settings.useIpadapter}
                    onChange={(e) => settings.update({ useIpadapter: e.target.checked })}
                    className="rounded"
                  />
                  IP-Adapter (中等)
                </label>
                <label className="flex items-center gap-2 text-sm">
                  <input
                    type="checkbox"
                    checked={settings.useHiresFix}
                    onChange={(e) => settings.update({ useHiresFix: e.target.checked })}
                    className="rounded"
                  />
                  Hires.fix 高清修复
                </label>
              </div>
            </div>
          </div>
        )}

        {step === 2 && (
          <div className="space-y-4">
            <div className="flex items-center gap-2 mb-4">
              <Sparkles className="w-5 h-5 text-gold-500" />
              <h2 className="text-lg font-semibold">高级配置</h2>
            </div>

            {/* TTS */}
            <div className="space-y-2">
              <label className="flex items-center gap-2 text-sm font-medium">
                <input
                  type="checkbox"
                  checked={settings.ttsEnabled}
                  onChange={(e) => settings.update({ ttsEnabled: e.target.checked })}
                  className="rounded"
                />
                启用 TTS 配音
              </label>
              {settings.ttsEnabled && (
                <div className="ml-6 space-y-2">
                  <label className="flex items-center gap-2 text-sm">
                    <input
                      type="checkbox"
                      checked={settings.smartDubbing}
                      onChange={(e) => settings.update({ smartDubbing: e.target.checked })}
                      className="rounded"
                    />
                    智能多角色配音
                  </label>
                  <div className="flex gap-2">
                    <select
                      value={settings.ttsVoice}
                      onChange={(e) => settings.update({ ttsVoice: e.target.value })}
                      className="input flex-1"
                    >
                      <option value="zh-CN-XiaoxiaoNeural">晓晓 (女声)</option>
                      <option value="zh-CN-YunxiNeural">云希 (男声)</option>
                      <option value="zh-CN-YunyangNeural">云扬 (男声)</option>
                      <option value="zh-CN-XiaoyiNeural">晓伊 (女声)</option>
                      <option value="zh-CN-YunjianNeural">云健 (男声)</option>
                    </select>
                    <select
                      value={settings.ttsRate}
                      onChange={(e) => settings.update({ ttsRate: e.target.value })}
                      className="input w-32"
                    >
                      <option value="+0%">正常语速</option>
                      <option value="+5%">稍快 +5%</option>
                      <option value="+10%">快 +10%</option>
                      <option value="-5%">稍慢 -5%</option>
                      <option value="-10%">慢 -10%</option>
                    </select>
                  </div>
                </div>
              )}
            </div>

            {/* Post-processing */}
            <div className="space-y-2">
              <label className="text-sm font-medium text-gray-700 dark:text-ink-300 block">
                后期处理
              </label>
              <div className="grid grid-cols-2 gap-3">
                <label className="flex items-center gap-2 text-sm">
                  <input
                    type="checkbox"
                    checked={settings.useColorGrading}
                    onChange={(e) => settings.update({ useColorGrading: e.target.checked })}
                    className="rounded"
                  />
                  调色
                </label>
                <label className="flex items-center gap-2 text-sm">
                  <input
                    type="checkbox"
                    checked={settings.useFadeTransition}
                    onChange={(e) => settings.update({ useFadeTransition: e.target.checked })}
                    className="rounded"
                  />
                  淡入淡出转场
                </label>
                <label className="flex items-center gap-2 text-sm">
                  <input
                    type="checkbox"
                    checked={settings.useMangaFx}
                    onChange={(e) => settings.update({ useMangaFx: e.target.checked })}
                    className="rounded"
                  />
                  漫剧特效
                </label>
                <label className="flex items-center gap-2 text-sm">
                  <input
                    type="checkbox"
                    checked={settings.useMultiShot}
                    onChange={(e) => settings.update({ useMultiShot: e.target.checked })}
                    className="rounded"
                  />
                  多镜头合成
                </label>
              </div>
            </div>

            {/* Video mode */}
            <div>
              <label className="text-sm font-medium text-gray-700 dark:text-ink-300 mb-1 block">
                视频生成模式
              </label>
              <select
                value={settings.videoMode}
                onChange={(e) => settings.update({ videoMode: e.target.value })}
                className="input"
              >
                <option value="local">本地 (LTX/ComfyUI)</option>
                <option value="cloud_t2v">云端文生视频</option>
                <option value="ltx_t2v">LTX 文生视频</option>
              </select>
            </div>
          </div>
        )}

        {step === 3 && (
          <div className="space-y-4">
            <div className="flex items-center gap-2 mb-4">
              <Sparkles className="w-5 h-5 text-gold-500" />
              <h2 className="text-lg font-semibold">确认生成</h2>
            </div>

            <div className="space-y-3">
              <SummaryRow label="标题" value={novelTitle || "(未命名)"} />
              <SummaryRow label="文本长度" value={`${novelText.length} 字`} />
              <SummaryRow label="图像模型" value={settings.imgCheckpoint} />
              <SummaryRow label="风格" value={settings.style} />
              <SummaryRow
                label="角色一致性"
                value={[
                  settings.usePulid && "PuLID",
                  settings.useIpadapter && "IP-Adapter",
                  settings.useHiresFix && "Hires.fix",
                ]
                  .filter(Boolean)
                  .join(" + ") || "无"}
              />
              <SummaryRow
                label="TTS 配音"
                value={settings.ttsEnabled ? `${settings.ttsVoice} (${settings.ttsRate})` : "关闭"}
              />
              <SummaryRow label="视频模式" value={settings.videoMode} />
              <SummaryRow
                label="后期处理"
                value={[
                  settings.useColorGrading && "调色",
                  settings.useFadeTransition && "转场",
                  settings.useMangaFx && "漫剧特效",
                ]
                  .filter(Boolean)
                  .join(" + ") || "无"}
              />
            </div>

            <div className="bg-gold-50 dark:bg-gold-900/10 border border-gold-200 dark:border-gold-800 rounded-lg p-4">
              <p className="text-sm text-gold-700 dark:text-gold-400">
                点击「开始生成」后，系统将自动执行：分镜分析 → 提示词生成 →
                图像生成 → 视频生成 → TTS配音 → 字幕烧录 → 视频合并 → QA质检
              </p>
            </div>
          </div>
        )}
      </div>

      {/* Navigation buttons */}
      <div className="flex justify-between">
        <button
          onClick={() => setStep((s) => Math.max(0, s - 1))}
          disabled={step === 0}
          className="btn-secondary disabled:opacity-30"
        >
          <ChevronLeft className="w-4 h-4" />
          上一步
        </button>

        {step < STEPS.length - 1 ? (
          <button
            onClick={() => setStep((s) => s + 1)}
            disabled={!canProceed()}
            className="btn-primary disabled:opacity-30"
          >
            下一步
            <ChevronRight className="w-4 h-4" />
          </button>
        ) : (
          <button
            onClick={handleGenerate}
            disabled={generateMutation.isPending}
            className="btn-primary"
          >
            {generateMutation.isPending ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : (
              <Sparkles className="w-4 h-4" />
            )}
            开始生成
          </button>
        )}
      </div>
    </div>
  );
}

function SummaryRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between py-2 border-b border-gray-100 dark:border-ink-800 last:border-0">
      <span className="text-sm text-gray-500 dark:text-ink-400">{label}</span>
      <span className="text-sm font-medium text-gray-900 dark:text-ink-100">
        {value}
      </span>
    </div>
  );
}
