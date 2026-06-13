import { WSRoomEvent } from "@/types";

const WS_URL = process.env.NEXT_PUBLIC_WS_URL || "ws://localhost:8000";

if (
  process.env.NODE_ENV === "production" &&
  WS_URL.startsWith("ws://localhost")
) {
  // eslint-disable-next-line no-console
  console.warn(
    "[wsService] NEXT_PUBLIC_WS_URL chưa được set khi build production. " +
      "WebSocket sẽ kết nối về localhost — game realtime sẽ không hoạt động.",
  );
}

function buildWebSocketUrl(roomCode: string, token?: string) {
  const normalizedBaseUrl = WS_URL.startsWith("http")
    ? WS_URL.replace(/^http/, "ws")
    : WS_URL;
  const url = new URL(normalizedBaseUrl);
  url.pathname = `/ws/game/${roomCode}`;

  if (token) {
    url.searchParams.set("token", token);
  }

  return url.toString();
}

class WebSocketService {
  private socket: WebSocket | null = null;
  private listeners: Map<string, Set<(data: any) => void>> = new Map();
  private shouldReconnect = false;
  private reconnectAttempts = 0;
  private maxReconnectAttempts = 5;
  private baseReconnectDelayMs = 1000;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private currentToken: string | null = null;
  private currentRoomCode: string | null = null;

  private clearReconnectTimer(): void {
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
  }

  private scheduleReconnect(): void {
    if (!this.shouldReconnect || !this.currentToken || !this.currentRoomCode)
      return;
    if (this.reconnectAttempts >= this.maxReconnectAttempts) return;

    const delay =
      this.baseReconnectDelayMs * Math.pow(2, this.reconnectAttempts);
    this.reconnectAttempts += 1;

    this.clearReconnectTimer();
    this.reconnectTimer = setTimeout(() => {
      this.connect(this.currentToken!, this.currentRoomCode!).catch(() => {
        // Keep silent here; retries continue until max attempts.
      });
    }, delay);
  }

  connect(token: string, roomCode: string): Promise<void> {
    return new Promise((resolve, reject) => {
      try {
        const wsUrl = buildWebSocketUrl(roomCode, token);
        // console.log("WebSocket connecting to:", wsUrl);
        this.currentToken = token;
        this.currentRoomCode = roomCode;
        this.shouldReconnect = true;
        this.clearReconnectTimer();

        if (this.socket && this.socket.readyState === WebSocket.OPEN) {
          // console.log("WebSocket already connected");
          resolve();
          return;
        }

        if (this.socket) {
          this.socket.onopen = null;
          this.socket.onmessage = null;
          this.socket.onerror = null;
          this.socket.onclose = null;
          this.socket.close();
          this.socket = null;
        }

        this.socket = new WebSocket(wsUrl);

        this.socket.onopen = () => {
          console.log("WebSocket connected");
          this.reconnectAttempts = 0;
          resolve();
        };

        this.socket.onerror = (error) => {
          console.error("WebSocket error:", error);
          if (this.socket?.readyState !== WebSocket.OPEN) {
            reject(error);
          }
        };

        this.socket.onclose = (event) => {
          if (event.code !== 1000) {
            console.log("WebSocket disconnected:", event.reason || event.code);
            this.scheduleReconnect();
          }
        };

        this.socket.onmessage = (event) => {
          try {
            const parsed: WSRoomEvent = JSON.parse(event.data);
            // Debug: log incoming websocket events
            try {
              console.debug("WS recv:", parsed.type, parsed.data);
            } catch (e) {
              // ignore debug errors
            }
            this.notifyListeners(parsed.type, parsed.data);
          } catch (error) {
            console.error("Failed to parse websocket message:", error);
          }
        };

        console.log("WebSocket connecting...");
      } catch (error) {
        reject(error);
      }
    });
  }

  disconnect(): void {
    this.shouldReconnect = false;
    this.reconnectAttempts = 0;
    this.currentToken = null;
    this.currentRoomCode = null;
    this.clearReconnectTimer();

    if (this.socket) {
      this.socket.onopen = null;
      this.socket.onmessage = null;
      this.socket.onerror = null;
      this.socket.onclose = null;
      this.socket.close();
      this.socket = null;
    }
  }

  emit(eventType: string, data: any): void {
    if (this.socket && this.socket.readyState === WebSocket.OPEN) {
      this.socket.send(
        JSON.stringify({
          type: eventType,
          data,
        }),
      );
    }
  }

  on(eventType: string, callback: (data: any) => void): void {
    if (!this.listeners.has(eventType)) {
      this.listeners.set(eventType, new Set());
    }
    this.listeners.get(eventType)!.add(callback);
  }

  off(eventType: string, callback: (data: any) => void): void {
    if (this.listeners.has(eventType)) {
      this.listeners.get(eventType)!.delete(callback);
    }
  }

  private notifyListeners(eventType: string, data: any): void {
    // Debug: log dispatch
    try {
      console.debug("WS dispatch:", eventType);
    } catch (e) {}

    if (this.listeners.has(eventType)) {
      this.listeners.get(eventType)!.forEach((callback) => {
        try {
          callback(data);
        } catch (error) {
          console.error(`Error in listener for ${eventType}:`, error);
        }
      });
    }
  }

  isConnected(): boolean {
    return this.socket?.readyState === WebSocket.OPEN;
  }
}

export const wsService = new WebSocketService();
