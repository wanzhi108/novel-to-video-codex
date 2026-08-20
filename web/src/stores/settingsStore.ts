import { create } from "zustand";

interface SettingsStore {
  // API Keys
  deepseekKey: string;
  klingApiKey: string;

  // ComfyUI
  comfyuiUrl: string;

  // Model selections
  imgCheckpoint: string;
  vidCheckpoint: string;
  useHiresFix: boolean;
  useIpadapter: boolean;
  usePulid: boolean;
  useWan21: boolean;
  useKenBurns: boolean;
  useDualFrame: boolean;

  // TTS
  ttsEnabled: boolean;
  ttsVoice: string;
  ttsRate: string;
  smartDubbing: boolean;
  useAssSubtitles: boolean;
  autoCosyvoice: boolean;

  // Post-processing
  useColorGrading: boolean;
  useFadeTransition: boolean;
  useMangaFx: boolean;
  useMultiShot: boolean;

  // Video mode
  videoMode: string; // "local" | "cloud_t2v" | "ltx_t2v"
  style: string;

  // UI
  darkMode: boolean;
  sidebarCollapsed: boolean;

  // Actions
  update: (updates: Partial<SettingsStore>) => void;
  toggleDarkMode: () => void;
  toggleSidebar: () => void;
  loadFromLocalStorage: () => void;
  saveToLocalStorage: () => void;
}

const STORAGE_KEY = "luminaforge-settings";

const DEFAULTS = {
  deepseekKey: "",
  klingApiKey: "",
  comfyuiUrl: "http://127.0.0.1:8188",
  imgCheckpoint: "animagine-xl-4.0.safetensors",
  vidCheckpoint: "ltx-2.3-22b-dev-fp8.safetensors",
  useHiresFix: true,
  useIpadapter: false,
  usePulid: false,
  useWan21: false,
  useKenBurns: false,
  useDualFrame: false,
  ttsEnabled: true,
  ttsVoice: "zh-CN-XiaoxiaoNeural",
  ttsRate: "+5%",
  smartDubbing: true,
  useAssSubtitles: true,
  autoCosyvoice: true,
  useColorGrading: true,
  useFadeTransition: true,
  useMangaFx: true,
  useMultiShot: false,
  videoMode: "local",
  style: "cinematic",
  darkMode: false,
  sidebarCollapsed: false,
};

export const useSettingsStore = create<SettingsStore>((set, get) => ({
  ...DEFAULTS,

  update: (updates) => {
    set(updates);
    get().saveToLocalStorage();
  },

  toggleDarkMode: () => {
    const newValue = !get().darkMode;
    set({ darkMode: newValue });
    if (newValue) {
      document.documentElement.classList.add("dark");
    } else {
      document.documentElement.classList.remove("dark");
    }
    get().saveToLocalStorage();
  },

  toggleSidebar: () => {
    set({ sidebarCollapsed: !get().sidebarCollapsed });
    get().saveToLocalStorage();
  },

  loadFromLocalStorage: () => {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (raw) {
        const saved = JSON.parse(raw);
        set({ ...DEFAULTS, ...saved });
        if (saved.darkMode) {
          document.documentElement.classList.add("dark");
        }
      }
    } catch {
      // Ignore parse errors
    }
  },

  saveToLocalStorage: () => {
    try {
      const state = get();
      const toSave = { ...state };
      // Remove functions
      delete (toSave as Record<string, unknown>).update;
      delete (toSave as Record<string, unknown>).toggleDarkMode;
      delete (toSave as Record<string, unknown>).toggleSidebar;
      delete (toSave as Record<string, unknown>).loadFromLocalStorage;
      delete (toSave as Record<string, unknown>).saveToLocalStorage;
      localStorage.setItem(STORAGE_KEY, JSON.stringify(toSave));
    } catch {
      // Ignore quota errors
    }
  },
}));
