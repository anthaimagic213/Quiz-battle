"use client";

/**
 * Lightweight WebSocket client for the social chat endpoint
 * /ws/chat/{conversation_id}.
 *
 * Reconnects automatically with exponential backoff and exposes a
 * subscription API so React components can mount/unmount handlers
 * without worrying about the underlying connection lifecycle.
 */

export interface ChatMessageData {
  id: string;
  conversation_id: string;
  sender_id: string;
  sender_type: string;
  content: string;
  is_ai_generated: boolean;
  metadata?: Record<string, any> | null;
  created_at: string;
  updated_at: string;
  sender?: {
    id: string;
    username: string;
    full_name?: string | null;
    avatar_url?: string | null;
  } | null;
}

export type ChatEvent =
  | { type: "CHAT_MESSAGE"; data: ChatMessageData }
  | {
    type: "CONVERSATION_JOINED";
    data: { conversation_id: string; member_ids: string[] };
  }
  | { type: "CONNECTION_OPEN" }
  | { type: "CONNECTION_CLOSED" }
  | { type: "RECONNECT_SCHEDULED"; data: { attempt: number; delay_ms: number } }
  | { type: "PONG"; data?: Record<string, any> }
  | { type: "ERROR"; data: { detail: string } }
  | { type: string; data: any };

type Listener = (event: ChatEvent) => void;

interface ChatSocketOptions {
  conversationId: string;
  token: string;
  baseUrl?: string;
}

class ChatSocket {
  private ws: WebSocket | null = null;
  private listeners: Set<Listener> = new Set();
  private reconnectAttempts = 0;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private pingTimer: ReturnType<typeof setInterval> | null = null;
  private isUnmounted = false;
  private conversationId: string;
  private token: string;
  private baseUrl: string;
  private messageQueue: Array<{ type: string; data: Record<string, any> }> = [];

  constructor(opts: ChatSocketOptions) {
    this.conversationId = opts.conversationId;
    this.token = opts.token;
    this.baseUrl =
      opts.baseUrl || process.env.NEXT_PUBLIC_WS_URL || "ws://localhost:8000";
  }

  connect(): void {
    if (this.isUnmounted) return;
    if (
      this.ws &&
      (this.ws.readyState === WebSocket.OPEN ||
        this.ws.readyState === WebSocket.CONNECTING)
    ) {
      return;
    }

    const url = `${this.baseUrl}/ws/chat/${this.conversationId}?token=${encodeURIComponent(this.token)}`;
    const socket = new WebSocket(url);
    this.ws = socket;

    socket.onopen = () => {
      this.reconnectAttempts = 0;
      this.startPing();
      this.flushMessageQueue();
      // notify listeners that connection is open
      this.listeners.forEach((cb) => cb({ type: "CONNECTION_OPEN", data: undefined }));
    };

    socket.onmessage = (ev) => {
      try {
        const event = JSON.parse(ev.data) as ChatEvent;
        this.listeners.forEach((cb) => cb(event));
      } catch {
        // ignore malformed messages
      }
    };

    socket.onerror = () => {
      // onclose will be called next; the reconnect logic lives there.
    };

    socket.onclose = () => {
      this.stopPing();
      this.ws = null;
      if (this.isUnmounted) return;
      // notify listeners that connection closed
      this.listeners.forEach((cb) => cb({ type: "CONNECTION_CLOSED", data: undefined }));
      this.scheduleReconnect();
    };
  }

  private scheduleReconnect() {
    if (this.isUnmounted) return;
    if (this.reconnectTimer) return;
    const delay = Math.min(1000 * Math.pow(2, this.reconnectAttempts), 15000);
    const attempt = this.reconnectAttempts + 1;
    this.reconnectAttempts = attempt;
    // notify listeners a reconnect was scheduled
    this.listeners.forEach((cb) =>
      cb({ type: "RECONNECT_SCHEDULED", data: { attempt, delay_ms: delay } })
    );
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      this.connect();
    }, delay);
  }

  private startPing() {
    this.stopPing();
    this.pingTimer = setInterval(() => {
      this.send({ type: "PING", data: {} });
    }, 25000);
  }

  private stopPing() {
    if (this.pingTimer) {
      clearInterval(this.pingTimer);
      this.pingTimer = null;
    }
  }

  send(payload: { type: string; data: Record<string, any> }): void {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(payload));
    } else {
      // Queue the message if the socket is not open yet
      if (this.messageQueue.length < 50) {
        this.messageQueue.push(payload);
      }
    }
  }

  private flushMessageQueue(): void {
    while (
      this.messageQueue.length > 0 &&
      this.ws &&
      this.ws.readyState === WebSocket.OPEN
    ) {
      const payload = this.messageQueue.shift();
      if (payload) {
        this.ws.send(JSON.stringify(payload));
      }
    }
  }

  isConnected(): boolean {
    return this.ws?.readyState === WebSocket.OPEN;
  }

  sendMessage(content: string, metadata?: Record<string, any>): void {
    this.send({ type: "SEND_MESSAGE", data: { content, metadata } });
  }

  markRead(): void {
    this.send({ type: "MARK_READ", data: {} });
  }

  subscribe(listener: Listener): () => void {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  }

  close(): void {
    this.isUnmounted = true;
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    this.stopPing();
    if (this.ws) {
      try {
        this.ws.close();
      } catch {
        // ignore
      }
      this.ws = null;
    }
    this.listeners.clear();
  }
}

export default ChatSocket;
