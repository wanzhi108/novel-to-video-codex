import { create } from "zustand";
import type { WSMessage, JobSummary } from "@/lib/types";

interface JobStore {
  // Job list
  jobs: JobSummary[];

  // Current job progress
  currentStep: string;
  progress: number;
  wsConnected: boolean;
  wsMessages: WSMessage[];
  error: string | null;

  // Actions
  setJobs: (jobs: JobSummary[]) => void;
  setCurrentStep: (step: string) => void;
  setProgress: (progress: number) => void;
  setWsConnected: (connected: boolean) => void;
  addWsMessage: (msg: WSMessage) => void;
  setError: (error: string | null) => void;
  clearMessages: () => void;
}

export const useJobStore = create<JobStore>((set) => ({
  jobs: [],
  currentStep: "",
  progress: 0,
  wsConnected: false,
  wsMessages: [],
  error: null,

  setJobs: (jobs) => set({ jobs }),
  setCurrentStep: (step) => set({ currentStep: step }),
  setProgress: (progress) => set({ progress }),
  setWsConnected: (connected) => set({ wsConnected: connected }),
  addWsMessage: (msg) =>
    set((state) => ({
      wsMessages: [...state.wsMessages.slice(-99), msg],
      // Auto-update step/progress from common message types
      ...(msg.type === "step" && msg.step
        ? { currentStep: msg.step }
        : {}),
      ...(msg.type === "comfyui_progress" && typeof msg.progress === "number"
        ? { progress: msg.progress }
        : {}),
      ...(msg.type === "error"
        ? { error: msg.error || msg.message || "未知错误" }
        : {}),
      ...(msg.type === "job_complete"
        ? { currentStep: "complete", progress: 100 }
        : {}),
    })),
  setError: (error) => set({ error }),
  clearMessages: () => set({ wsMessages: [], currentStep: "", progress: 0, error: null }),
}));
