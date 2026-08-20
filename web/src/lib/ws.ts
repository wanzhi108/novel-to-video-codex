/**
 * WebSocket 客户端 — 实时进度推送
 * 端点: ws://localhost:8190/ws/progress/{job_id}
 */

import type { WSMessage } from "./types";

type MessageHandler = (msg: WSMessage) => void;
type StatusHandler = (connected: boolean) => void;

export class WebSocketClient {
  private ws: WebSocket | null = null;
  private jobId: string | null = null;
  private messageHandlers = new Set<MessageHandler>();
  private statusHandlers = new Set<StatusHandler>();
  private reconnectAttempts = 0;
  private maxReconnectAttempts = 5;
  private reconnectDelay = 2000;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;

  connect(jobId: string) {
    this.disconnect();
    this.jobId = jobId;
    this.reconnectAttempts = 0;
    this.doConnect();
  }

  private doConnect() {
    if (!this.jobId) return;

    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const host = window.location.host;
    // In dev mode, Vite proxy handles /ws → :8190
    const url = `${protocol}//${host}/ws/progress/${this.jobId}`;

    try {
      this.ws = new WebSocket(url);
    } catch (err) {
      console.error("[WS] Failed to connect:", err);
      this.scheduleReconnect();
      return;
    }

    this.ws.onopen = () => {
      console.log("[WS] Connected to job:", this.jobId);
      this.reconnectAttempts = 0;
      this.notifyStatus(true);
    };

    this.ws.onmessage = (event) => {
      try {
        const msg: WSMessage = JSON.parse(event.data);
        this.messageHandlers.forEach((handler) => handler(msg));
      } catch (err) {
        console.error("[WS] Parse error:", err, event.data);
      }
    };

    this.ws.onclose = (event) => {
      console.log("[WS] Disconnected:", event.code, event.reason);
      this.notifyStatus(false);
      if (event.code !== 1000) {
        this.scheduleReconnect();
      }
    };

    this.ws.onerror = (err) => {
      console.error("[WS] Error:", err);
    };
  }

  private scheduleReconnect() {
    if (this.reconnectAttempts >= this.maxReconnectAttempts) {
      console.warn("[WS] Max reconnect attempts reached");
      return;
    }
    this.reconnectAttempts++;
    const delay = this.reconnectDelay * this.reconnectAttempts;
    console.log(`[WS] Reconnecting in ${delay}ms (attempt ${this.reconnectAttempts})`);
    this.reconnectTimer = setTimeout(() => this.doConnect(), delay);
  }

  disconnect() {
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    if (this.ws) {
      this.ws.onclose = null;
      this.ws.close(1000);
      this.ws = null;
    }
    this.notifyStatus(false);
  }

  onMessage(handler: MessageHandler): () => void {
    this.messageHandlers.add(handler);
    return () => this.messageHandlers.delete(handler);
  }

  onStatusChange(handler: StatusHandler): () => void {
    this.statusHandlers.add(handler);
    return () => this.statusHandlers.delete(handler);
  }

  private notifyStatus(connected: boolean) {
    this.statusHandlers.forEach((handler) => handler(connected));
  }

  get isConnected(): boolean {
    return this.ws?.readyState === WebSocket.OPEN;
  }
}

// Singleton instance
export const wsClient = new WebSocketClient();
