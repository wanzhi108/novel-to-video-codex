import {
  Key,
  Server,
  Palette,
  Volume2,
  Save,
  Loader2,
  Users,
} from "lucide-react";
import toast from "react-hot-toast";
import { useState, useEffect } from "react";
import { useSettingsStore } from "@/stores/settingsStore";
import { useModelList } from "@/hooks/useModelList";
import { api } from "@/lib/api";

export function Settings() {
  const settings = useSettingsStore();
  const models = useModelList();
  const [saving, setSaving] = useState(false);

  // v12.1: 挂载时读取 launcher 启动配置，回填真实持久化值
  useEffect(() => {
    api.getLauncherConfig()
      .then((res) => {
        const cfg: Record<string, unknown> = (res && res.config) || {};
        settings.update({
          autoCosyvoice:
            cfg.auto_cosyvoice !== undefined ? !!cfg.auto_cosyvoice : settings.autoCosyvoice,
        });
      })
      .catch(() => {
        // 读取失败则用本地默认值，不影响界面
      });
  }, []);

  const handleSaveToBackend = async () => {
    setSaving(true);
    try {
      await api.updateSettings({
        deepseek_key: settings.deepseekKey,
        kling_api_key: settings.klingApiKey,
        comfyui_url: settings.comfyuiUrl,
        img_checkpoint: settings.imgCheckpoint,
        vid_checkpoint: settings.vidCheckpoint,
        tts_voice: settings.ttsVoice,
        tts_rate: settings.ttsRate,
        style: settings.style,
        video_mode: settings.videoMode,
      });
      // v12.1: 同步 launcher 启动配置（auto_cosyvoice 等，下次启动主程序生效）
      try {
        await api.updateLauncherConfig({ auto_cosyvoice: settings.autoCosyvoice });
      } catch {
        // launcher 配置写入失败不阻断主流程
      }
      toast.success("设置已同步到后端");
    } catch {
      toast.error("同步失败，设置已保存在本地");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="max-w-2xl mx-auto space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 dark:text-ink-50">
            设置
          </h1>
          <p className="text-sm text-gray-500 dark:text-ink-400 mt-1">
            API 密钥、模型路径、生成参数
          </p>
        </div>
        <button
          onClick={handleSaveToBackend}
          disabled={saving}
          className="btn-primary"
        >
          {saving ? (
            <Loader2 className="w-4 h-4 animate-spin" />
          ) : (
            <Save className="w-4 h-4" />
          )}
          同步到后端
        </button>
      </div>

      {/* API Keys */}
      <Section icon={Key} title="API 密钥">
        <div>
          <label className="text-sm font-medium text-gray-700 dark:text-ink-300 mb-1 block">
            DeepSeek API Key
          </label>
          <input
            type="password"
            value={settings.deepseekKey}
            onChange={(e) => settings.update({ deepseekKey: e.target.value })}
            placeholder="sk-..."
            className="input"
          />
          <p className="text-xs text-gray-400 mt-1">
            用于分镜分析、提示词生成。获取: platform.deepseek.com
          </p>
        </div>
        <div>
          <label className="text-sm font-medium text-gray-700 dark:text-ink-300 mb-1 block">
            可灵 API Key
          </label>
          <input
            type="password"
            value={settings.klingApiKey}
            onChange={(e) => settings.update({ klingApiKey: e.target.value })}
            placeholder="kling-..."
            className="input"
          />
          <p className="text-xs text-gray-400 mt-1">
            用于角色正脸图生成。获取: klingai.com
          </p>
        </div>
      </Section>

      {/* ComfyUI */}
      <Section icon={Server} title="ComfyUI 配置">
        <div>
          <label className="text-sm font-medium text-gray-700 dark:text-ink-300 mb-1 block">
            ComfyUI 地址
          </label>
          <input
            type="text"
            value={settings.comfyuiUrl}
            onChange={(e) => settings.update({ comfyuiUrl: e.target.value })}
            placeholder="http://127.0.0.1:8188"
            className="input"
          />
        </div>
        <div>
          <label className="text-sm font-medium text-gray-700 dark:text-ink-300 mb-1 block">
            图像模型
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
                {settings.imgCheckpoint}
              </option>
            )}
          </select>
        </div>
        <div>
          <label className="text-sm font-medium text-gray-700 dark:text-ink-300 mb-1 block">
            视频模型
          </label>
          <input
            type="text"
            value={settings.vidCheckpoint}
            onChange={(e) => settings.update({ vidCheckpoint: e.target.value })}
            className="input"
          />
        </div>
      </Section>

      {/* TTS */}
      <Section icon={Volume2} title="TTS 配音">
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="text-sm font-medium text-gray-700 dark:text-ink-300 mb-1 block">
              默认声音
            </label>
            <select
              value={settings.ttsVoice}
              onChange={(e) => settings.update({ ttsVoice: e.target.value })}
              className="input"
            >
              <option value="zh-CN-XiaoxiaoNeural">晓晓 (女声)</option>
              <option value="zh-CN-YunxiNeural">云希 (男声)</option>
              <option value="zh-CN-YunyangNeural">云扬 (男声)</option>
              <option value="zh-CN-XiaoyiNeural">晓伊 (女声)</option>
              <option value="zh-CN-YunjianNeural">云健 (男声)</option>
            </select>
          </div>
          <div>
            <label className="text-sm font-medium text-gray-700 dark:text-ink-300 mb-1 block">
              语速
            </label>
            <select
              value={settings.ttsRate}
              onChange={(e) => settings.update({ ttsRate: e.target.value })}
              className="input"
            >
              <option value="+0%">正常</option>
              <option value="+5%">稍快 +5%</option>
              <option value="+10%">快 +10%</option>
              <option value="-5%">稍慢 -5%</option>
              <option value="-10%">慢 -10%</option>
            </select>
          </div>
        </div>
        <div className="flex gap-4 flex-wrap">
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={settings.ttsEnabled}
              onChange={(e) => settings.update({ ttsEnabled: e.target.checked })}
              className="rounded"
            />
            启用 TTS
          </label>
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={settings.smartDubbing}
              onChange={(e) => settings.update({ smartDubbing: e.target.checked })}
              className="rounded"
            />
            智能多角色配音
          </label>
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={settings.useAssSubtitles}
              onChange={(e) => settings.update({ useAssSubtitles: e.target.checked })}
              className="rounded"
            />
            ASS 动态字幕
          </label>
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={settings.autoCosyvoice}
              onChange={(e) => settings.update({ autoCosyvoice: e.target.checked })}
              className="rounded"
            />
            启动时自动拉起 CosyVoice2
          </label>
        </div>
        {/* v12.0: 字幕与音效增强信息 */}
        <div className="mt-3 p-3 bg-blue-50 dark:bg-blue-900/20 rounded-lg border border-blue-200 dark:border-blue-800">
          <p className="text-xs text-blue-700 dark:text-blue-300 font-medium mb-1">
            v12.0 字幕与音效增强
          </p>
          <ul className="text-xs text-blue-600 dark:text-blue-400 space-y-0.5 ml-4 list-disc">
            <li>字幕: 思源黑体 · 1080×1920 竖屏标准 · 3px描边+阴影 · 角色自动配色</li>
            <li>配音: CosyVoice2 优先 → Edge-TTS 回退 → 静默降级</li>
            <li>混音: 三轨（对白+环境音+BGM）· 自动 ducking · 情绪动态语速</li>
            <li>环境音: 森林/雨声/风声/夜晚/集市/心跳 自动匹配场景</li>
          </ul>
        </div>
      </Section>

      {/* Style */}
      <Section icon={Palette} title="风格与后期">
        <div>
          <label className="text-sm font-medium text-gray-700 dark:text-ink-300 mb-1 block">
            风格预设
          </label>
          <select
            value={settings.style}
            onChange={(e) => settings.update({ style: e.target.value })}
            className="input"
          >
            <option value="cinematic">电影感</option>
            <option value="anime">动漫风</option>
            <option value="realistic">写实风</option>
            <option value="watercolor">水彩风</option>
            <option value="ink">水墨风</option>
          </select>
        </div>
        <div>
          <label className="text-sm font-medium text-gray-700 dark:text-ink-300 mb-1 block">
            视频模式
          </label>
          <select
            value={settings.videoMode}
            onChange={(e) => settings.update({ videoMode: e.target.value })}
            className="input"
          >
            <option value="local">本地 (LTX/ComfyUI)</option>
            <option value="cloud_t2v">云端文生视频</option>
            <option value="ltx_t2v">LTX 文生视频</option>
            <option value="wan_i2v">Wan 2.2 I2V (稳定管线)</option>
          </select>
        </div>
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
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={settings.useHiresFix}
              onChange={(e) => settings.update({ useHiresFix: e.target.checked })}
              className="rounded"
            />
            Hires.fix 高清修复
          </label>
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={settings.usePulid}
              onChange={(e) => settings.update({ usePulid: e.target.checked })}
              className="rounded"
            />
            PuLID 角色一致性
          </label>
        </div>
      </Section>

      {/* v12.0: Character & Environment Generation */}
      <Section icon={Users} title="角色与环境生成">
        <div>
          <label className="text-sm font-medium text-gray-700 dark:text-ink-300 mb-1 block">
            角色一致性策略
          </label>
          <select
            value={settings.usePulid ? "pulid" : settings.useIpadapter ? "ipadapter" : "text"}
            onChange={(e) => {
              const v = e.target.value;
              settings.update({
                usePulid: v === "pulid",
                useIpadapter: v === "ipadapter",
              });
            }}
            className="input"
          >
            <option value="pulid">PuLID (最强一致性, 需可灵API)</option>
            <option value="ipadapter">IP-Adapter (中等, 需定妆照)</option>
            <option value="text">纯文本描述 (最弱, 无需额外资源)</option>
          </select>
          <p className="text-xs text-gray-400 mt-1">
            PuLID 通过可灵AI生成多角度参考图, 实现跨镜角色面孔一致
          </p>
        </div>
        <div>
          <label className="text-sm font-medium text-gray-700 dark:text-ink-300 mb-2 block">
            环境与道具图生成
          </label>
          <div className="space-y-2">
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={settings.usePulid}
                onChange={(e) => settings.update({ usePulid: e.target.checked })}
                className="rounded"
              />
              预生成环境参考图 (同地点复用, 提升场景一致性)
            </label>
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                defaultChecked
                className="rounded"
              />
              关键道具特写图 (武器/法宝/信物等)
            </label>
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                defaultChecked
                className="rounded"
              />
              角色素材库自动构建 (3角度参考图)
            </label>
          </div>
        </div>
      </Section>
    </div>
  );
}

function Section({
  icon: Icon,
  title,
  children,
}: {
  icon: React.ComponentType<{ className?: string }>;
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div className="card p-5 space-y-4">
      <div className="flex items-center gap-2">
        <Icon className="w-5 h-5 text-gold-500" />
        <h2 className="font-semibold">{title}</h2>
      </div>
      {children}
    </div>
  );
}
