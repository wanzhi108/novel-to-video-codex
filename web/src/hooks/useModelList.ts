import { useMemo } from "react";
import { useComfyUIModels } from "./useApi";
import type { ComfyUIModel } from "@/lib/types";

/**
 * Dynamic model list hook — fetches and categorizes models from ComfyUI
 */
export function useModelList() {
  const query = useComfyUIModels();

  const categorized = useMemo(() => {
    const models = query.data?.models || [];
    // 严格按 ComfyUI 返回的 type 归类；不再用后缀兜底，
    // 否则 VAE（wanvideo\Wan2_1_VAE_bf16.safetensors）/ LoRA（ltx-2.3-…lora-384.safetensors）
    // 会被误收进"图像模型(Checkpoint)"下拉。
    return {
      // 老版本后端用 "checkpoints" 作 type；新版本统一 "checkpoint"。两者都兼容。
      checkpoints: models.filter((m: ComfyUIModel) =>
        m.type === "checkpoint" || m.type === "checkpoints"
      ),
      loras: models.filter((m: ComfyUIModel) => m.type === "lora" || m.type === "loras"),
      vae: models.filter((m: ComfyUIModel) => m.type === "vae"),
      clipVision: models.filter(
        (m: ComfyUIModel) =>
          m.type === "clip_vision" || m.name.toLowerCase().includes("clip")
      ),
    };
  }, [query.data]);

  return {
    ...query,
    models: query.data?.models || [],
    ...categorized,
  };
}
