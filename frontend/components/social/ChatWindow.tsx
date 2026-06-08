"use client";

import React, { useState, useEffect, useRef, useCallback } from "react";
import { messagesService, Message } from "@/services/conversationsService";
import ChatSocket, { ChatMessageData } from "@/services/chatSocket";

interface ChatWindowProps {
  friend: {
    id: string;
    username: string;
    full_name?: string | null;
    avatar_url?: string | null;
  };
  conversationId: string;
  currentUserId: string;
  onBack: () => void;
}

export default function ChatWindow({
  friend,
  conversationId,
  currentUserId,
  onBack,
}: ChatWindowProps) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [inputValue, setInputValue] = useState("");
  const [isLoading, setIsLoading] = useState(true);
  const [isSending, setIsSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [isSocketReady, setIsSocketReady] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const messageInputRef = useRef<HTMLTextAreaElement>(null);
  const socketRef = useRef<ChatSocket | null>(null);

  // Load message history once per conversation.
  const loadMessages = useCallback(async () => {
    try {
      setIsLoading(true);
      setError(null);
      const response = await messagesService.getMessages(conversationId, 50, 0);
      setMessages(response.messages);
    } catch (err) {
      setError("Không thể tải tin nhắn");
      console.error("Error loading messages:", err);
    } finally {
      setIsLoading(false);
    }
  }, [conversationId]);

  useEffect(() => {
    void loadMessages();
  }, [conversationId, loadMessages]);

  // Mark conversation as read when the window opens / new messages arrive.
  useEffect(() => {
    if (!isSocketReady) return;
    socketRef.current?.markRead();
  }, [isSocketReady, messages.length]);

  // Auto scroll to bottom when new messages appear.
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  // Auto focus the input.
  useEffect(() => {
    messageInputRef.current?.focus();
  }, [conversationId]);

  // Setup WebSocket connection.
  useEffect(() => {
    if (typeof window === "undefined") return;
    const token = localStorage.getItem("access_token");
    if (!token) return;

    const socket = new ChatSocket({ conversationId, token });
    socketRef.current = socket;

    const unsubscribe = socket.subscribe((event) => {
      if (event.type === "CHAT_MESSAGE") {
        const data = event.data as ChatMessageData;
        setMessages((prev) => {
          // Deduplicate by id (in case the REST send echoes back the message).
          if (prev.some((m) => m.id === data.id)) return prev;
          const incoming: Message = {
            id: data.id,
            conversation_id: data.conversation_id,
            sender_id: data.sender_id,
            sender_type: data.sender_type,
            content: data.content,
            is_ai_generated: data.is_ai_generated,
            metadata: data.metadata ?? null,
            created_at: data.created_at,
            updated_at: data.updated_at,
            sender_username: data.sender?.username ?? null,
            sender_full_name: data.sender?.full_name ?? null,
            sender_avatar_url: data.sender?.avatar_url ?? null,
          };
          return [...prev, incoming];
        });
      } else if (event.type === "ERROR") {
        setError(event.data?.detail || "Đã xảy ra lỗi chat");
      } else if (event.type === "CONVERSATION_JOINED") {
        setIsSocketReady(true);
      }
    });

    socket.connect();
    setIsSocketReady(false);

    return () => {
      unsubscribe();
      socket.close();
      socketRef.current = null;
    };
  }, [conversationId]);

  const handleSendMessage = async (e: React.FormEvent) => {
    e.preventDefault();
    const trimmed = inputValue.trim();
    if (!trimmed) return;

    try {
      setIsSending(true);
      setError(null);

      // Check if WebSocket is actually connected before sending
      if (socketRef.current?.isConnected()) {
        // Send via WebSocket for real-time delivery
        socketRef.current.sendMessage(trimmed);
        setInputValue("");
        messageInputRef.current?.focus();
      } else {
        // Fallback to REST if WebSocket is not connected
        const newMessage = await messagesService.sendMessage(conversationId, trimmed);
        setMessages((prev) =>
          prev.some((m) => m.id === newMessage.id) ? prev : [...prev, newMessage]
        );
        setInputValue("");
        messageInputRef.current?.focus();
      }
    } catch (err) {
      setError("Không thể gửi tin nhắn. Vui lòng thử lại.");
      console.error("Error sending message:", err);
    } finally {
      setIsSending(false);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSendMessage(e as unknown as React.FormEvent);
    }
  };

  return (
    <div className="chat-window">
      <div className="chat-header">
        <button className="chat-back-btn" onClick={onBack}>
          ← Quay lại
        </button>
        <div className="chat-header-info">
          <div className="chat-header-avatar">
            {friend.avatar_url ? (
              <img src={friend.avatar_url} alt={friend.username} />
            ) : (
              <div className="avatar-placeholder">
                {(friend.username || "?")[0].toUpperCase()}
              </div>
            )}
          </div>
          <div className="chat-header-content">
            <div className="chat-header-name">
              {friend.full_name || friend.username}
            </div>
            <div className="chat-header-username">@{friend.username}</div>
          </div>
        </div>
      </div>

      {error && <div className="chat-error">{error}</div>}

      <div className="chat-messages">
        {isLoading ? (
          <div className="chat-loading">
            <div className="spinner">⟳</div>
            <p>Đang tải tin nhắn...</p>
          </div>
        ) : messages.length === 0 ? (
          <div className="chat-empty">
            <div className="empty-icon">💬</div>
            <p className="empty-title">Chưa có tin nhắn nào</p>
            <p className="empty-subtitle">
              Bắt đầu cuộc trò chuyện với {friend.username}
            </p>
          </div>
        ) : (
          <>
            {messages.map((message) => {
              const isMine = message.sender_id === currentUserId;
              return (
                <div
                  key={message.id}
                  className={`chat-message ${
                    isMine ? "sent" : "received"
                  }`}
                >
                  <div className="chat-message-avatar">
                    {message.sender_avatar_url ? (
                      <img
                        src={message.sender_avatar_url}
                        alt={message.sender_username || ""}
                      />
                    ) : (
                      <div className="avatar-placeholder">
                        {(message.sender_username || "?")[0].toUpperCase()}
                      </div>
                    )}
                  </div>
                  <div className="chat-message-content">
                    <div className="chat-message-bubble">
                      {message.content}
                    </div>
                    <div className="chat-message-time">
                      {new Date(message.created_at).toLocaleTimeString(
                        "vi-VN",
                        { hour: "2-digit", minute: "2-digit" }
                      )}
                    </div>
                  </div>
                </div>
              );
            })}
            <div ref={messagesEndRef} />
          </>
        )}
      </div>

      <form className="chat-input-form" onSubmit={handleSendMessage}>
        <textarea
          ref={messageInputRef}
          className="chat-input"
          placeholder="Nhập tin nhắn (Shift+Enter để xuống dòng)..."
          value={inputValue}
          onChange={(e) => setInputValue(e.target.value)}
          onKeyDown={handleKeyDown}
          rows={3}
          disabled={isSending}
        />
        <button
          type="submit"
          className="chat-send-btn"
          disabled={!inputValue.trim() || isSending}
        >
          {isSending ? "⟳" : "📤"} Gửi
        </button>
      </form>
    </div>
  );
}
