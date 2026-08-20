import { useState, useCallback } from "react";
import { useCharacters, useTTSVoices, usePreviewTTS, useUpdateCharacterVoice } from "./useApi";
import type { Character, TTSVoice } from "@/lib/types";

/**
 * Character voice management hook
 */
export function useCharacterVoice(jobId: string | null) {
  const charactersQuery = useCharacters(jobId);
  const voicesQuery = useTTSVoices();
  const previewMutation = usePreviewTTS();
  const updateVoiceMutation = useUpdateCharacterVoice();

  const [previewingVoice, setPreviewingVoice] = useState<string | null>(null);
  const [previewAudio, setPreviewAudio] = useState<string | null>(null);

  const voices: TTSVoice[] = voicesQuery.data?.voices || [];
  const characters: Character[] = charactersQuery.data?.characters || [];

  const previewVoice = useCallback(
    async (text: string, voice: string, rate?: string) => {
      setPreviewingVoice(voice);
      try {
        await previewMutation.mutateAsync({ text, voice, rate });
        // The audio is available at /api/tts-preview-audio
        setPreviewAudio(`/api/tts-preview-audio?job_id=${jobId}&voice=${voice}&t=${Date.now()}`);
      } finally {
        setPreviewingVoice(null);
      }
    },
    [previewMutation, jobId]
  );

  const assignVoice = useCallback(
    async (characterName: string, voiceId: string, voiceName: string) => {
      if (!jobId) return;
      await updateVoiceMutation.mutateAsync({
        jobId,
        name: characterName,
        voiceId,
        voiceName,
      });
    },
    [jobId, updateVoiceMutation]
  );

  return {
    characters,
    voices,
    isLoading: charactersQuery.isLoading || voicesQuery.isLoading,
    previewVoice,
    previewingVoice,
    previewAudio,
    assignVoice,
    isAssigning: updateVoiceMutation.isPending,
  };
}
