import { useState, useEffect } from "react";
import { useParams } from "react-router-dom";
import {
  Film,
  RefreshCw,
  SkipForward,
  Edit3,
  X,
  Save,
  Clock,
  Image as ImageIcon,
  Video,
  Volume2,
  Loader2,
  MapPin,
  FileDown,
} from "lucide-react";
import toast from "react-hot-toast";
import {
  DndContext,
  closestCenter,
  KeyboardSensor,
  PointerSensor,
  useSensor,
  useSensors,
  type DragEndEvent,
} from "@dnd-kit/core";
import {
  arrayMove,
  SortableContext,
  sortableKeyboardCoordinates,
  verticalListSortingStrategy,
  useSortable,
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import {
  useScenes,
  useRetryScene,
  useSkipScene,
  useJobStatus,
} from "@/hooks/useApi";
import { useWebSocket } from "@/hooks/useWebSocket";
import { useProjectStore } from "@/stores/projectStore";
import { api } from "@/lib/api";
import { cn, getSceneStatusColor, getSceneStatusText } from "@/lib/utils";
import type { Scene } from "@/lib/types";

export function StoryboardEditor() {
  const { jobId: paramJobId } = useParams<{ jobId: string }>();
  const currentJobId = useProjectStore((s) => s.currentJobId);
  const jobId = paramJobId || currentJobId;

  const scenesQuery = useScenes(jobId);
  const jobQuery = useJobStatus(jobId);
  const retryMutation = useRetryScene();
  const skipMutation = useSkipScene();
  const [editingScene, setEditingScene] = useState<Scene | null>(null);
  const [localScenes, setLocalScenes] = useState<Scene[]>([]);

  // Connect WebSocket for real-time updates
  useWebSocket(jobId);

  // Sync remote scenes to local state
  useEffect(() => {
    if (scenesQuery.data?.scenes) {
      setLocalScenes(scenesQuery.data.scenes);
    }
  }, [scenesQuery.data]);

  const sensors = useSensors(
    useSensor(PointerSensor),
    useSensor(KeyboardSensor, {
      coordinateGetter: sortableKeyboardCoordinates,
    })
  );

  const handleDragEnd = (event: DragEndEvent) => {
    const { active, over } = event;
    if (over && active.id !== over.id) {
      const newScenes = arrayMove(
        localScenes,
        localScenes.findIndex((s) => s.id === active.id),
        localScenes.findIndex((s) => s.id === over.id)
      );
      setLocalScenes(newScenes);
      // Call reorder API
      if (jobId) {
        api.reorderScenes(jobId, newScenes.map((s) => s.id)).catch(() => {
          toast.error("排序保存失败，将在刷新后恢复");
        });
      }
      toast.success("排序已更新");
    }
  };

  const handleRetry = async (sceneId: number) => {
    if (!jobId) return;
    try {
      await retryMutation.mutateAsync({ jobId, sceneId });
      toast.success(`分镜 ${sceneId + 1} 重新生成中...`);
    } catch {
      toast.error("重新生成失败");
    }
  };

  const handleSkip = async (sceneId: number) => {
    if (!jobId) return;
    try {
      await skipMutation.mutateAsync({ jobId, sceneId });
      toast.success(`分镜 ${sceneId + 1} 已跳过`);
    } catch {
      toast.error("跳过失败");
    }
  };

  const handleExportPrompts = async () => {
    if (!jobId) return;
    try {
      const res = await api.exportScenePrompts(jobId, "txt");
      const blob = new Blob([res.content || ""], { type: "text/plain;charset=utf-8" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${jobQuery.data?.novel_title || jobId}_prompts.txt`;
      a.click();
      URL.revokeObjectURL(url);
      toast.success("提示词已导出");
    } catch {
      toast.error("导出失败");
    }
  };

  if (!jobId) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="text-center">
          <Film className="w-12 h-12 text-gray-300 dark:text-ink-700 mx-auto mb-3" />
          <p className="text-gray-500 dark:text-ink-400">
            请从仪表盘选择一个项目
          </p>
        </div>
      </div>
    );
  }

  if (scenesQuery.isLoading) {
    return (
      <div className="flex items-center justify-center h-full">
        <Loader2 className="w-8 h-8 text-gold-500 animate-spin" />
      </div>
    );
  }

  const scenes = localScenes;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 dark:text-ink-50">
            分镜编辑器
          </h1>
          <p className="text-sm text-gray-500 dark:text-ink-400 mt-1">
            {jobQuery.data?.novel_title || jobId} · {scenes.length} 个分镜
          </p>
        </div>
        <div className="flex gap-2">
          <button
            onClick={handleExportPrompts}
            className="btn-ghost"
            title="导出全部场景提示词"
          >
            <FileDown className="w-4 h-4" />
            导出提示词
          </button>
          <button
            onClick={() => scenesQuery.refetch()}
            className="btn-ghost"
          >
            <RefreshCw className="w-4 h-4" />
            刷新
          </button>
        </div>
      </div>

      {/* Scene timeline */}
      <DndContext
        sensors={sensors}
        collisionDetection={closestCenter}
        onDragEnd={handleDragEnd}
      >
        <SortableContext
          items={scenes.map((s) => s.id)}
          strategy={verticalListSortingStrategy}
        >
          <div className="space-y-3">
            {scenes.map((scene) => (
              <SortableSceneCard
                key={scene.id}
                scene={scene}
                jobId={jobId}
                onEdit={() => setEditingScene(scene)}
                onRetry={() => handleRetry(scene.id)}
                onSkip={() => handleSkip(scene.id)}
              />
            ))}
          </div>
        </SortableContext>
      </DndContext>

      {/* Edit drawer */}
      {editingScene && (
        <SceneEditDrawer
          scene={editingScene}
          jobId={jobId}
          onClose={() => setEditingScene(null)}
          onSave={(updated) => {
            setLocalScenes((scenes) =>
              scenes.map((s) => (s.id === updated.id ? updated : s))
            );
            // Persist to backend via batch-edit API
            if (jobId) {
              const fields: Record<string, unknown> = {};
              const keys = [
                "subtitle_text", "description", "image_prompt", "video_prompt",
                "mood", "camera", "duration", "emotional_intensity", "negative_prompt",
              ] as const;
              for (const k of keys) {
                if (updated[k] !== editingScene?.[k]) {
                  fields[k] = updated[k];
                }
              }
              if (Object.keys(fields).length > 0) {
                api.batchEditScenes(jobId, [updated.id], fields).catch(() => {
                  toast.error("保存到后端失败");
                });
              }
            }
            setEditingScene(null);
            toast.success("分镜已保存");
          }}
        />
      )}
    </div>
  );
}

// ==================== Sortable Scene Card ====================

function SortableSceneCard({
  scene,
  jobId,
  onEdit,
  onRetry,
  onSkip,
}: {
  scene: Scene;
  jobId: string;
  onEdit: () => void;
  onRetry: () => void;
  onSkip: () => void;
}) {
  const {
    attributes,
    listeners,
    setNodeRef,
    transform,
    transition,
    isDragging,
  } = useSortable({ id: scene.id });

  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
  };

  return (
    <div
      ref={setNodeRef}
      style={style}
      className={cn(
        "card p-4 flex gap-4",
        isDragging && "shadow-lg ring-2 ring-gold-400"
      )}
    >
      {/* Drag handle */}
      <div
        {...attributes}
        {...listeners}
        className="flex items-center cursor-grab active:cursor-grabbing text-gray-300 hover:text-gray-400"
      >
        ⋮⋮
      </div>

      {/* Scene number */}
      <div className="flex-shrink-0 w-8 text-center pt-2">
        <span className="text-lg font-bold text-gold-500">{scene.id + 1}</span>
      </div>

      {/* Thumbnail */}
      <div className="flex-shrink-0 w-28 h-28 rounded-lg overflow-hidden bg-gray-100 dark:bg-ink-800">
        {scene.image_path ? (
          <img
            src={api.sceneImageUrl(jobId, scene.id)}
            alt={`Scene ${scene.id + 1}`}
            className="w-full h-full object-cover"
          />
        ) : (
          <div className="flex items-center justify-center w-full h-full">
            <ImageIcon className="w-8 h-8 text-gray-300 dark:text-ink-700" />
          </div>
        )}
      </div>

      {/* Content */}
      <div className="flex-1 min-w-0 space-y-1">
        <div className="flex items-center gap-2">
          <span className={getSceneStatusColor(scene.status)}>
            {getSceneStatusText(scene.status)}
          </span>
          {scene.comfyui_progress > 0 && scene.status === "generating" && (
            <span className="text-xs text-gray-400">
              {Math.round(scene.comfyui_progress * 100)}%
            </span>
          )}
          {scene.mood && (
            <span className="badge-info">{scene.mood}</span>
          )}
          {scene.camera && (
            <span className="text-xs text-gray-400">运镜: {scene.camera}</span>
          )}
        </div>

        <p className="text-sm text-gray-700 dark:text-ink-200 line-clamp-2">
          {scene.subtitle_display || scene.description}
        </p>

        {scene.characters && (
          <div className="flex items-center gap-1 flex-wrap">
            {scene.characters.split(",").map((char, i) => (
              <span
                key={i}
                className="px-1.5 py-0.5 text-xs rounded bg-purple-50 text-purple-600 dark:bg-purple-900/20 dark:text-purple-400"
                title={`角色: ${char.trim()}`}
              >
                {char.trim()}
              </span>
            ))}
          </div>
        )}

        {/* v12.0: 环境信息 */}
        {scene.setting && (
          <div className="flex items-center gap-1 text-xs text-gray-400">
            <MapPin className="w-3 h-3" />
            <span className="truncate">{scene.setting}</span>
          </div>
        )}

        {scene.error_msg && (
          <p className="text-xs text-red-500 truncate">⚠ {scene.error_msg}</p>
        )}
      </div>

      {/* Actions */}
      <div className="flex flex-col gap-1.5 flex-shrink-0">
        <button
          onClick={onEdit}
          className="btn-ghost text-xs"
          title="编辑"
        >
          <Edit3 className="w-4 h-4" />
        </button>
        <button
          onClick={onRetry}
          className="btn-ghost text-xs"
          title="重新生成"
          disabled={scene.status === "generating"}
        >
          <RefreshCw className="w-4 h-4" />
        </button>
        <button
          onClick={onSkip}
          className="btn-ghost text-xs"
          title="跳过"
        >
          <SkipForward className="w-4 h-4" />
        </button>
      </div>

      {/* Video/Audio indicators */}
      <div className="flex flex-col gap-1 flex-shrink-0 justify-center">
        {scene.video_path && (
          <Video className="w-4 h-4 text-green-500" />
        )}
        {scene.audio_path && (
          <Volume2 className="w-4 h-4 text-blue-500" />
        )}
        <div className="flex items-center gap-0.5 text-xs text-gray-400">
          <Clock className="w-3 h-3" />
          {scene.duration}
        </div>
      </div>
    </div>
  );
}

// ==================== Scene Edit Drawer ====================

function SceneEditDrawer({
  scene,
  jobId,
  onClose,
  onSave,
}: {
  scene: Scene;
  jobId: string;
  onClose: () => void;
  onSave: (scene: Scene) => void;
}) {
  const [edited, setEdited] = useState<Scene>(scene);
  const [saving, setSaving] = useState(false);

  const handleSave = async () => {
    setSaving(true);
    try {
      // Save via API (if available) or just update locally
      // TODO: Call /api/scenes/{job_id}/batch-edit when backend supports it
      onSave(edited);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex justify-end">
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-black/30"
        onClick={onClose}
      />

      {/* Drawer */}
      <div className="relative w-full max-w-lg bg-white dark:bg-ink-900 shadow-xl overflow-y-auto">
        {/* Header */}
        <div className="sticky top-0 flex items-center justify-between px-6 py-4 bg-white dark:bg-ink-900 border-b border-gray-200 dark:border-ink-800 z-10">
          <h3 className="font-semibold text-lg">
            编辑分镜 {scene.id + 1}
          </h3>
          <button onClick={onClose} className="btn-ghost">
            <X className="w-5 h-5" />
          </button>
        </div>

        <div className="p-6 space-y-4">
          {/* Preview */}
          {scene.image_path && (
            <div className="aspect-video rounded-lg overflow-hidden bg-gray-100 dark:bg-ink-800">
              <img
                src={api.sceneImageUrl(jobId, scene.id)}
                alt="Preview"
                className="w-full h-full object-cover"
              />
            </div>
          )}

          {/* Subtitle text */}
          <div>
            <label className="text-sm font-medium mb-1 block">字幕文本</label>
            <textarea
              value={edited.subtitle_text}
              onChange={(e) =>
                setEdited({ ...edited, subtitle_text: e.target.value })
              }
              rows={2}
              className="input"
            />
          </div>

          {/* Description */}
          <div>
            <label className="text-sm font-medium mb-1 block">场景描述</label>
            <textarea
              value={edited.description}
              onChange={(e) =>
                setEdited({ ...edited, description: e.target.value })
              }
              rows={3}
              className="input"
            />
          </div>

          {/* Image prompt */}
          <div>
            <label className="text-sm font-medium mb-1 block">图像提示词</label>
            <textarea
              value={edited.image_prompt}
              onChange={(e) =>
                setEdited({ ...edited, image_prompt: e.target.value })
              }
              rows={4}
              className="input font-mono text-sm"
            />
          </div>

          {/* Video prompt */}
          <div>
            <label className="text-sm font-medium mb-1 block">视频提示词</label>
            <textarea
              value={edited.video_prompt}
              onChange={(e) =>
                setEdited({ ...edited, video_prompt: e.target.value })
              }
              rows={3}
              className="input font-mono text-sm"
            />
          </div>

          {/* Grid: mood, camera, duration, intensity */}
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-sm font-medium mb-1 block">情绪</label>
              <input
                type="text"
                value={edited.mood}
                onChange={(e) =>
                  setEdited({ ...edited, mood: e.target.value })
                }
                className="input"
              />
            </div>
            <div>
              <label className="text-sm font-medium mb-1 block">运镜</label>
              <input
                type="text"
                value={edited.camera}
                onChange={(e) =>
                  setEdited({ ...edited, camera: e.target.value })
                }
                className="input"
              />
            </div>
            <div>
              <label className="text-sm font-medium mb-1 block">时长</label>
              <input
                type="text"
                value={edited.duration}
                onChange={(e) =>
                  setEdited({ ...edited, duration: e.target.value })
                }
                className="input"
              />
            </div>
            <div>
              <label className="text-sm font-medium mb-1 block">
                情绪强度 (1-10)
              </label>
              <input
                type="number"
                min={1}
                max={10}
                value={edited.emotional_intensity}
                onChange={(e) =>
                  setEdited({
                    ...edited,
                    emotional_intensity: parseInt(e.target.value) || 5,
                  })
                }
                className="input"
              />
            </div>
          </div>

          {/* Negative prompt */}
          <div>
            <label className="text-sm font-medium mb-1 block">负面提示词</label>
            <input
              type="text"
              value={edited.negative_prompt}
              onChange={(e) =>
                setEdited({ ...edited, negative_prompt: e.target.value })
              }
              className="input"
              placeholder="lowres, bad anatomy, bad hands..."
            />
          </div>
        </div>

        {/* Footer */}
        <div className="sticky bottom-0 flex justify-end gap-2 px-6 py-4 bg-white dark:bg-ink-900 border-t border-gray-200 dark:border-ink-800">
          <button onClick={onClose} className="btn-secondary">
            取消
          </button>
          <button
            onClick={handleSave}
            disabled={saving}
            className="btn-primary"
          >
            {saving ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : (
              <Save className="w-4 h-4" />
            )}
            保存
          </button>
        </div>
      </div>
    </div>
  );
}
