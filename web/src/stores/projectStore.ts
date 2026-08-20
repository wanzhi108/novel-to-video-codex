import { create } from "zustand";
import type { JobState, Scene, Character } from "@/lib/types";

interface ProjectStore {
  // Current job
  currentJobId: string | null;
  jobState: JobState | null;
  scenes: Scene[];
  characters: Character[];

  // Actions
  setCurrentJob: (jobId: string | null) => void;
  setJobState: (state: JobState | null) => void;
  setScenes: (scenes: Scene[]) => void;
  updateScene: (sceneId: number, updates: Partial<Scene>) => void;
  setCharacters: (characters: Character[]) => void;
  updateCharacter: (name: string, updates: Partial<Character>) => void;
  reset: () => void;
}

export const useProjectStore = create<ProjectStore>((set) => ({
  currentJobId: null,
  jobState: null,
  scenes: [],
  characters: [],

  setCurrentJob: (jobId) => set({ currentJobId: jobId }),
  setJobState: (state) =>
    set({
      jobState: state,
      scenes: state?.scenes ?? [],
      characters: state?.characters ?? [],
    }),
  setScenes: (scenes) => set({ scenes }),
  updateScene: (sceneId, updates) =>
    set((state) => ({
      scenes: state.scenes.map((s) =>
        s.id === sceneId ? { ...s, ...updates } : s
      ),
    })),
  setCharacters: (characters) => set({ characters }),
  updateCharacter: (name, updates) =>
    set((state) => ({
      characters: state.characters.map((c) =>
        c.name === name ? { ...c, ...updates } : c
      ),
    })),
  reset: () =>
    set({
      currentJobId: null,
      jobState: null,
      scenes: [],
      characters: [],
    }),
}));
