import { useParams } from "react-router-dom";
import {
  Users,
  Volume2,
  Play,
  Loader2,
  User,
  Mic,
  Shirt,
  Image as ImageIcon,
} from "lucide-react";
import toast from "react-hot-toast";
import { useCharacterVoice } from "@/hooks/useCharacterVoice";
import { useProjectStore } from "@/stores/projectStore";
import { cn } from "@/lib/utils";
import type { TTSVoice, Character } from "@/lib/types";

export function CharacterPanel() {
  const { jobId: paramJobId } = useParams<{ jobId: string }>();
  const currentJobId = useProjectStore((s) => s.currentJobId);
  const jobId = paramJobId || currentJobId;

  const {
    characters,
    voices,
    isLoading,
    previewVoice,
    previewingVoice,
    previewAudio,
    assignVoice,
    isAssigning,
  } = useCharacterVoice(jobId);

  if (!jobId) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="text-center">
          <Users className="w-12 h-12 text-gray-300 dark:text-ink-700 mx-auto mb-3" />
          <p className="text-gray-500 dark:text-ink-400">
            请从仪表盘选择一个项目
          </p>
        </div>
      </div>
    );
  }

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-full">
        <Loader2 className="w-8 h-8 text-gold-500 animate-spin" />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold text-gray-900 dark:text-ink-50">
          角色配音面板
        </h1>
        <p className="text-sm text-gray-500 dark:text-ink-400 mt-1">
          {characters.length} 个角色 · {voices.length} 个可用声音
        </p>
      </div>

      {/* Character grid */}
      {characters.length === 0 ? (
        <div className="card p-12 text-center">
          <Users className="w-12 h-12 text-gray-300 dark:text-ink-700 mx-auto mb-3" />
          <p className="text-gray-500 dark:text-ink-400">
            暂无角色数据，请先生成分镜
          </p>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {characters.map((char, idx) => (
            <CharacterCard
              key={idx}
              character={char}
              voices={voices}
              onPreview={previewVoice}
              previewingVoice={previewingVoice}
              onAssign={assignVoice}
              isAssigning={isAssigning}
            />
          ))}
        </div>
      )}

      {/* Preview audio player */}
      {previewAudio && (
        <div className="fixed bottom-6 right-6 card p-4 shadow-lg z-40 w-80">
          <div className="flex items-center gap-2 mb-2">
            <Volume2 className="w-5 h-5 text-gold-500" />
            <span className="font-medium text-sm">配音预览</span>
          </div>
          <audio
            src={previewAudio}
            controls
            autoPlay
            className="w-full"
          />
        </div>
      )}
    </div>
  );
}

function CharacterCard({
  character,
  voices,
  onPreview,
  previewingVoice,
  onAssign,
  isAssigning,
}: {
  character: Character;
  voices: TTSVoice[];
  onPreview: (text: string, voice: string, rate?: string) => void;
  previewingVoice: string | null;
  onAssign: (name: string, voiceId: string, voiceName: string) => Promise<void>;
  isAssigning: boolean;
}) {
  const roleTypeColors: Record<string, string> = {
    主角: "bg-gold-100 text-gold-700 dark:bg-gold-900/30 dark:text-gold-400",
    配角: "bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400",
    反派: "bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400",
    旁白: "bg-gray-100 text-gray-700 dark:bg-gray-800 dark:text-gray-400",
    路人: "bg-gray-100 text-gray-500 dark:bg-gray-800 dark:text-gray-500",
  };

  const previewText = `你好，我是${character.name}。`;

  // v12.0: 素材库参考图预览
  const matlibPath = character.material_library_path;

  return (
    <div className="card p-4 space-y-3">
      {/* Character info */}
      <div className="flex items-start gap-3">
        <div className="flex-shrink-0 w-10 h-10 rounded-full bg-gradient-to-br from-purple-400 to-purple-600 flex items-center justify-center">
          <User className="w-5 h-5 text-white" />
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <h3 className="font-medium text-gray-900 dark:text-ink-50">
              {character.name || "未命名"}
            </h3>
            {character.role_type && (
              <span
                className={cn(
                  "badge",
                  roleTypeColors[character.role_type] || roleTypeColors["路人"]
                )}
              >
                {character.role_type}
              </span>
            )}
          </div>
          <div className="flex items-center gap-2 text-xs text-gray-400 mt-0.5">
            {character.gender && <span>{character.gender}</span>}
            {character.age_range && <span>· {character.age_range}</span>}
            {character.personality && (
              <span className="truncate">· {character.personality}</span>
            )}
          </div>
        </div>
      </div>

      {/* Appearance & Clothing */}
      <div className="space-y-1.5">
        {character.appearance && (
          <div className="text-xs text-gray-500 dark:text-ink-400 bg-gray-50 dark:bg-ink-800/50 rounded p-2">
            <span className="font-medium">外貌: </span>
            {character.appearance}
          </div>
        )}
        {character.clothing && (
          <div className="text-xs text-gray-500 dark:text-ink-400 bg-gray-50 dark:bg-ink-800/50 rounded p-2 flex items-start gap-1.5">
            <Shirt className="w-3.5 h-3.5 mt-0.5 flex-shrink-0 text-blue-400" />
            <div>
              <span className="font-medium">着装: </span>
              {character.clothing}
            </div>
          </div>
        )}
      </div>

      {/* v12.0: Material Library Preview */}
      {matlibPath && (
        <div className="bg-blue-50 dark:bg-blue-900/20 rounded p-2 border border-blue-200 dark:border-blue-800">
          <div className="flex items-center gap-1.5 text-xs text-blue-600 dark:text-blue-400 mb-1.5">
            <ImageIcon className="w-3.5 h-3.5" />
            <span className="font-medium">角色素材库</span>
            <span className="text-blue-400 dark:text-blue-500">3 角度参考图</span>
          </div>
          <div className="flex gap-1.5">
            {["front", "side", "halfbody"].map((angle) => (
              <div
                key={angle}
                className="flex-1 aspect-square bg-gray-100 dark:bg-ink-800 rounded flex items-center justify-center text-[10px] text-gray-400"
              >
                {angle === "front" ? "正面" : angle === "side" ? "侧面" : "半身"}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Voice selection */}
      <div className="space-y-2">
        <label className="text-sm font-medium text-gray-700 dark:text-ink-300 flex items-center gap-1">
          <Mic className="w-3.5 h-3.5" />
          配音声音
        </label>
        <div className="flex gap-2">
          <select
            value={character.voice_id}
            onChange={(e) => {
              const voice = voices.find((v) => v.id === e.target.value);
              if (voice) {
                onAssign(character.name, voice.id, voice.name).then(() =>
                  toast.success(`${character.name} 的声音已更新`)
                );
              }
            }}
            disabled={isAssigning}
            className="input flex-1"
          >
            <option value="">-- 选择声音 --</option>
            {voices.map((v) => (
              <option key={v.id} value={v.id}>
                {v.name} ({v.gender})
              </option>
            ))}
          </select>
          <button
            onClick={() =>
              character.voice_id
                ? onPreview(previewText, character.voice_id)
                : toast.error("请先选择声音")
            }
            disabled={previewingVoice === character.voice_id}
            className="btn-secondary px-3"
            title="试听"
          >
            {previewingVoice === character.voice_id ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : (
              <Play className="w-4 h-4" />
            )}
          </button>
        </div>
      </div>

      {/* Current voice info */}
      {character.voice_name && (
        <div className="flex items-center gap-1.5 text-xs text-blue-500">
          <Volume2 className="w-3 h-3" />
          当前: {character.voice_name}
        </div>
      )}
    </div>
  );
}
