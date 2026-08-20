import { useComfyUICheck, useComfyUIQueue } from "./useApi";

/**
 * ComfyUI status hook — combines check + queue data
 */
export function useComfyUI() {
  const checkQuery = useComfyUICheck();
  const queueQuery = useComfyUIQueue();

  const connected = checkQuery.data?.status === "ok";
  const url = checkQuery.data?.url || "";
  const queueRunning = queueQuery.data?.queue_running?.length || 0;
  const queuePending = queueQuery.data?.queue_pending?.length || 0;
  const totalQueue = queueRunning + queuePending;

  return {
    connected,
    url,
    queueRunning,
    queuePending,
    totalQueue,
    isLoading: checkQuery.isLoading,
    error: checkQuery.error,
  };
}
