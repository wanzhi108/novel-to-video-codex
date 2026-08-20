import { useJobStore } from "@/stores/jobStore";
import type { WSMessage } from "@/lib/types";

/**
 * Job progress hook — subscribes to WebSocket messages and exposes derived state
 */
export function useJobProgress() {
  const wsMessages = useJobStore((s) => s.wsMessages);
  const currentStep = useJobStore((s) => s.currentStep);
  const progress = useJobStore((s) => s.progress);
  const wsConnected = useJobStore((s) => s.wsConnected);
  const error = useJobStore((s) => s.error);

  // Derive step display text
  const stepDisplay: Record<string, string> = {
    upload: "上传文本",
    story_structure: "故事结构分析",
    story_structure_auto: "自动故事分析",
    character_env_analysis: "角色环境分析",
    storyboard: "分镜生成",
    prompts_progress: "提示词生成",
    generating: "素材生成",
    merging: "视频合并",
    complete: "已完成",
  };

  const currentStepText = stepDisplay[currentStep] || currentStep;
  const isComplete = currentStep === "complete" || progress >= 100;
  const isError = !!error;

  // Get latest scene_status messages
  const sceneUpdates = wsMessages.filter(
    (m: WSMessage) => m.type === "scene_status"
  );
  const latestSceneUpdate = sceneUpdates[sceneUpdates.length - 1];

  // Check for job_complete message
  const completeMsg = wsMessages.find((m: WSMessage) => m.type === "job_complete");

  return {
    currentStep,
    currentStepText,
    progress,
    wsConnected,
    error,
    isError,
    isComplete,
    latestSceneUpdate,
    mergedVideoPath: completeMsg?.merged_video as string | undefined,
    messageCount: wsMessages.length,
  };
}
