"use client";

import React, { useState, useEffect, useRef, useCallback } from "react";
import { messagesService, Message } from "@/services/conversationsService";

interface ChatWindowProps {
  friend: {
    id: string;
    username: string;
    full_name?: string;
    avatar_url?: string;
  };
  conversationId: string;
  onBack: () => void;
}

export default function ChatWindow({
  friend,
  conversationId,
  onBack,
}: ChatWindowProps) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [inputValue, setInputValue] = useState("");
  const [isLoading, setIsLoading] = useState(true);
  const [isSending, setIsSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const messageInputRef = useRef<HTMLTextAreaElement>(null);

  // Load messages
  const loadMessages = useCallback(async () => {
    try {
      setIsLoading(true);
      const response = await messagesService.getMessages(
        conversationId as any,
        50,
        0
      );
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

  // Auto scroll to bottom
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  // Auto focus input
  useEffect(() => {
    messageInputRef.current?.focus();
  }, []);

  const handleSendMessage = async (e: React.FormEvent) => {
    e.preventDefault();

    if (!inputValue.trim()) return;

    try {
      setIsSending(true);
      setError(null);

      const newMessage = await messagesService.sendMessage(
        conversationId as any,
        inputValue.trim()
      );

      setMessages((prev) => [...prev, newMessage]);
      setInputValue("");
      messageInputRef.current?.focus();
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
      handleSendMessage(e as any);
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
            {messages.map((message) => (
              <div
                key={message.id}
                className={`chat-message ${
                  message.sender_type === "user" ? "sent" : "received"
                }`}
              >
                <div className="chat-message-avatar">
                  {message.sender_avatar_url ? (
                    <img
                      src={message.sender_avatar_url}
                      alt={message.sender_username}
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
                      {
                        hour: "2-digit",
                        minute: "2-digit",
                      }
                    )}
                  </div>
                </div>
              </div>
            ))}
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
