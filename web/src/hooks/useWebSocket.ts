import { useEffect, useRef, useCallback } from "react";
import { wsClient } from "@/lib/ws";
import { useJobStore } from "@/stores/jobStore";
import { useProjectStore } from "@/stores/projectStore";
import type { WSMessage, Scene } from "@/lib/types";

/**
 * WebSocket hook — connects to /ws/progress/{job_id} and routes messages to stores
 */
export function useWebSocket(jobId: string | null) {
  const addWsMessage = useJobStore((s) => s.addWsMessage);
  const setWsConnected = useJobStore((s) => s.setWsConnected);
  const setError = useJobStore((s) => s.setError);
  const updateScene = useProjectStore((s) => s.updateScene);
  const isConnectedRef = useRef(false);

  const handleMessage = useCallback(
    (msg: WSMessage) => {
      addWsMessage(msg);

      // Route scene status updates to project store
      if (msg.type === "scene_status" && typeof msg.scene_id === "number") {
        updateScene(msg.scene_id, {
          status: ((msg.status as string) || "generating") as Scene["status"],
          comfyui_progress:
            typeof msg.progress === "number" ? msg.progress : 0,
          error_msg: (msg.error as string) || "",
        });
      }
    },
    [addWsMessage, updateScene]
  );

  const handleStatus = useCallback(
    (connected: boolean) => {
      setWsConnected(connected);
      isConnectedRef.current = connected;
    },
    [setWsConnected]
  );

  useEffect(() => {
    if (!jobId) return;

    wsClient.connect(jobId);
    const unsubMsg = wsClient.onMessage(handleMessage);
    const unsubStatus = wsClient.onStatusChange(handleStatus);

    return () => {
      unsubMsg();
      unsubStatus();
      wsClient.disconnect();
      setWsConnected(false);
      setError(null);
    };
  }, [jobId, handleMessage, handleStatus, setWsConnected, setError]);

  return {
    connected: useJobStore((s) => s.wsConnected),
    disconnect: () => wsClient.disconnect(),
  };
}
