import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type {
  GenerateRequest,
  JobState,
  JobSummary,
  Scene,
  Character,
  HealthStatus,
  ComfyUIStatus,
  ComfyUIModel,
  ComfyUIQueue,
  TTSVoice,
  BGMItem,
} from "@/lib/types";

// ==================== System ====================

export function useHealth() {
  return useQuery<HealthStatus>({
    queryKey: ["health"],
    queryFn: api.health,
    refetchInterval: 10000,
  });
}

export function useComfyUICheck() {
  return useQuery<ComfyUIStatus>({
    queryKey: ["comfyui-check"],
    queryFn: api.comfyuiCheck,
    refetchInterval: 15000,
  });
}

export function useComfyUIQueue() {
  return useQuery<ComfyUIQueue>({
    queryKey: ["comfyui-queue"],
    queryFn: api.comfyuiQueue,
    refetchInterval: 3000,
  });
}

// ==================== Models ====================

export function useComfyUIModels() {
  return useQuery<{ models: ComfyUIModel[] }>({
    queryKey: ["comfyui-models"],
    queryFn: api.comfyuiModels,
    staleTime: 60000,
  });
}

// ==================== Jobs ====================

export function useJobs() {
  return useQuery<{ jobs: JobSummary[] }>({
    queryKey: ["jobs"],
    queryFn: api.jobs,
    refetchInterval: 5000,
  });
}

export function useJobStatus(jobId: string | null) {
  return useQuery<JobState>({
    queryKey: ["job-status", jobId],
    queryFn: () => api.jobStatus(jobId!),
    enabled: !!jobId,
    refetchInterval: (query) => {
      // Stop polling when job is complete
      const data = query.state.data;
      if (data?.current_step === "complete" || data?.merged_video_path) {
        return false;
      }
      return 3000;
    },
  });
}

export function useDeleteJob() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (jobId: string) => api.deleteJob(jobId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["jobs"] });
    },
  });
}

// ==================== Generation ====================

export function useGenerate() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (req: GenerateRequest) => api.generate(req),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["jobs"] });
    },
  });
}

export function useCancelGeneration() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (jobId: string) => api.cancelGeneration(jobId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["jobs"] });
      qc.invalidateQueries({ queryKey: ["job-status"] });
    },
  });
}

export function useRemerge() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (jobId: string) => api.rememege(jobId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["jobs"] });
    },
  });
}

// ==================== Scenes ====================

export function useScenes(jobId: string | null) {
  return useQuery<{ scenes: Scene[] }>({
    queryKey: ["scenes", jobId],
    queryFn: () => api.scenes(jobId!),
    enabled: !!jobId,
    refetchInterval: (query) => {
      // Stop polling when all scenes are done
      const data = query.state.data;
      const allDone = data?.scenes?.every(
        (s: Scene) => s.status === "completed" || s.status === "error" || s.status === "skipped"
      );
      return allDone ? false : 3000;
    },
  });
}

export function useRetryScene() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ jobId, sceneId }: { jobId: string; sceneId: number }) =>
      api.retryScene(jobId, sceneId),
    onSuccess: (_, vars) => {
      qc.invalidateQueries({ queryKey: ["scenes", vars.jobId] });
    },
  });
}

export function useSkipScene() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ jobId, sceneId }: { jobId: string; sceneId: number }) =>
      api.skipScene(jobId, sceneId),
    onSuccess: (_, vars) => {
      qc.invalidateQueries({ queryKey: ["scenes", vars.jobId] });
    },
  });
}

// ==================== Characters ====================

export function useCharacters(jobId: string | null) {
  return useQuery<{ characters: Character[] }>({
    queryKey: ["characters", jobId],
    queryFn: () => api.characters(jobId!),
    enabled: !!jobId,
  });
}

export function useAnalyzeCharacters() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (jobId: string) => api.analyzeCharacters(jobId),
    onSuccess: (_, jobId) => {
      qc.invalidateQueries({ queryKey: ["characters", jobId] });
    },
  });
}

export function useUpdateCharacterVoice() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      jobId,
      name,
      voiceId,
      voiceName,
    }: {
      jobId: string;
      name: string;
      voiceId: string;
      voiceName: string;
    }) => api.updateCharacterVoice(jobId, name, voiceId, voiceName),
    onSuccess: (_, vars) => {
      qc.invalidateQueries({ queryKey: ["characters", vars.jobId] });
    },
  });
}

// ==================== TTS ====================

export function useTTSVoices() {
  return useQuery<{ voices: TTSVoice[] }>({
    queryKey: ["tts-voices"],
    queryFn: api.ttsVoices,
    staleTime: 300000, // 5 min cache
  });
}

export function usePreviewTTS() {
  return useMutation({
    mutationFn: ({
      text,
      voice,
      rate,
    }: {
      text: string;
      voice: string;
      rate?: string;
    }) => api.previewTTS(text, voice, rate),
  });
}

// ==================== BGM ====================

export function useBGMList() {
  return useQuery<{ bgms: BGMItem[] }>({
    queryKey: ["bgm-list"],
    queryFn: api.bgmList,
    staleTime: 60000,
  });
}

// ==================== Storyboard ====================

export function useGenerateStoryboard() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      jobId,
      deepseekKey,
    }: {
      jobId: string;
      deepseekKey: string;
    }) => api.generateStoryboard(jobId, deepseekKey),
    onSuccess: (_, vars) => {
      qc.invalidateQueries({ queryKey: ["scenes", vars.jobId] });
      qc.invalidateQueries({ queryKey: ["job-status", vars.jobId] });
    },
  });
}
