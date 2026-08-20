import { useParams, useNavigate } from "react-router-dom";
import {
  ArrowLeft,
  Image as ImageIcon,
  Video,
  Volume2,
  Film,
  Loader2,
} from "lucide-react";
import { useScenes } from "@/hooks/useApi";
import { api } from "@/lib/api";
import { getSceneStatusColor, getSceneStatusText } from "@/lib/utils";

export function ScenePreview() {
  const { jobId, sceneId } = useParams<{ jobId: string; sceneId: string }>();
  const navigate = useNavigate();
  const scenesQuery = useScenes(jobId || null);

  if (!jobId || sceneId === undefined) {
    navigate("/tasks");
    return null;
  }

  const sid = parseInt(sceneId);
  const scene = scenesQuery.data?.scenes?.find((s) => s.id === sid);

  if (scenesQuery.isLoading) {
    return (
      <div className="flex items-center justify-center h-full">
        <Loader2 className="w-8 h-8 text-gold-500 animate-spin" />
      </div>
    );
  }

  if (!scene) {
    return (
      <div className="text-center py-12">
        <p className="text-gray-500">分镜不存在</p>
        <button
          onClick={() => navigate(`/storyboard/${jobId}`)}
          className="btn-secondary mt-4"
        >
          返回分镜编辑器
        </button>
      </div>
    );
  }

  return (
    <div className="max-w-4xl mx-auto space-y-6">
      {/* Back */}
      <button
        onClick={() => navigate(`/storyboard/${jobId}`)}
        className="btn-ghost"
      >
        <ArrowLeft className="w-4 h-4" />
        返回分镜编辑器
      </button>

      {/* Scene info */}
      <div className="flex items-center gap-3">
        <h1 className="text-2xl font-bold text-gray-900 dark:text-ink-50">
          分镜 {scene.id + 1}
        </h1>
        <span className={getSceneStatusColor(scene.status)}>
          {getSceneStatusText(scene.status)}
        </span>
      </div>

      {/* Media previews */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {/* Image */}
        <div className="card p-4">
          <div className="flex items-center gap-2 mb-3">
            <ImageIcon className="w-4 h-4 text-blue-500" />
            <h3 className="font-medium text-sm">生成图片</h3>
          </div>
          {scene.image_path ? (
            <img
              src={api.sceneImageUrl(jobId, scene.id)}
              alt={`Scene ${scene.id + 1}`}
              className="w-full rounded-lg"
            />
          ) : (
            <div className="aspect-video bg-gray-100 dark:bg-ink-800 rounded-lg flex items-center justify-center">
              <ImageIcon className="w-12 h-12 text-gray-300 dark:text-ink-700" />
            </div>
          )}
        </div>

        {/* Video */}
        <div className="card p-4">
          <div className="flex items-center gap-2 mb-3">
            <Video className="w-4 h-4 text-green-500" />
            <h3 className="font-medium text-sm">生成视频</h3>
          </div>
          {scene.video_path || scene.final_video_path ? (
            <video
              src={api.sceneVideoUrl(jobId, scene.id)}
              controls
              className="w-full rounded-lg"
            />
          ) : (
            <div className="aspect-video bg-gray-100 dark:bg-ink-800 rounded-lg flex items-center justify-center">
              <Film className="w-12 h-12 text-gray-300 dark:text-ink-700" />
            </div>
          )}
        </div>

        {/* Audio */}
        <div className="card p-4">
          <div className="flex items-center gap-2 mb-3">
            <Volume2 className="w-4 h-4 text-purple-500" />
            <h3 className="font-medium text-sm">配音音频</h3>
            <span className="text-xs text-gray-400 ml-auto">
              {scene.audio_duration > 0
                ? `${scene.audio_duration.toFixed(1)}s`
                : ""}
            </span>
          </div>
          {scene.audio_path ? (
            <audio
              src={api.sceneAudioUrl(jobId, scene.id)}
              controls
              className="w-full"
            />
          ) : (
            <div className="h-20 bg-gray-100 dark:bg-ink-800 rounded-lg flex items-center justify-center">
              <Volume2 className="w-8 h-8 text-gray-300 dark:text-ink-700" />
            </div>
          )}
        </div>

        {/* Subtitle */}
        <div className="card p-4">
          <div className="flex items-center gap-2 mb-3">
            <Film className="w-4 h-4 text-gold-500" />
            <h3 className="font-medium text-sm">字幕文本</h3>
          </div>
          <div className="space-y-2">
            <p className="text-sm text-gray-700 dark:text-ink-200">
              {scene.subtitle_display || scene.subtitle_text}
            </p>
            {scene.subtitle_timings.length > 0 && (
              <div className="text-xs text-gray-400 space-y-1">
                {scene.subtitle_timings.map((t, i) => (
                  <div key={i} className="flex gap-2">
                    <span className="font-mono">
                      {t.start.toFixed(1)}s - {t.end.toFixed(1)}s
                    </span>
                    <span>{t.speaker}: {t.text}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Prompt details */}
      <div className="card p-4 space-y-3">
        <h3 className="font-medium text-sm">提示词详情</h3>
        <div className="grid grid-cols-2 gap-3 text-xs">
          <Detail label="情绪" value={scene.mood} />
          <Detail label="运镜" value={scene.camera} />
          <Detail label="时长" value={scene.duration} />
          <Detail
            label="情绪强度"
            value={`${scene.emotional_intensity}/10`}
          />
          <Detail label="故事幕次" value={scene.story_act} />
          <Detail label="节奏" value={scene.storytelling_rhythm} />
          <Detail label="视频模式" value={scene.video_mode_used || "—"} />
          <Detail label="角色" value={scene.characters} />
        </div>
        {scene.image_prompt && (
          <div>
            <label className="text-xs font-medium text-gray-500">
              图像提示词
            </label>
            <p className="text-xs font-mono text-gray-700 dark:text-ink-200 mt-1 p-2 bg-gray-50 dark:bg-ink-800/50 rounded">
              {scene.image_prompt}
            </p>
          </div>
        )}
        {scene.video_prompt && (
          <div>
            <label className="text-xs font-medium text-gray-500">
              视频提示词
            </label>
            <p className="text-xs font-mono text-gray-700 dark:text-ink-200 mt-1 p-2 bg-gray-50 dark:bg-ink-800/50 rounded">
              {scene.video_prompt}
            </p>
          </div>
        )}
        {scene.error_msg && (
          <div className="p-2 bg-red-50 dark:bg-red-900/20 rounded text-xs text-red-500">
            ⚠ {scene.error_msg}
          </div>
        )}
      </div>
    </div>
  );
}

function Detail({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <span className="text-gray-400">{label}: </span>
      <span className="text-gray-700 dark:text-ink-200">{value || "—"}</span>
    </div>
  );
}
