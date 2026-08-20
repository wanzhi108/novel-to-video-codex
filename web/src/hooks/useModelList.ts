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
    return {
      checkpoints: models.filter((m: ComfyUIModel) =>
        m.type === "checkpoint" || m.name.match(/\.(safetensors|ckpt|pt)$/i)
      ),
      loras: models.filter((m: ComfyUIModel) => m.type === "lora"),
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
