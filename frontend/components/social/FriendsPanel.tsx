"use client";

import React, { useState, useEffect, useCallback } from "react";
import { UUID } from "crypto";
import { friendsService, Friendship, FriendRequest, User } from "@/services/friendsService";
import { conversationsService, Conversation } from "@/services/conversationsService";
import  FriendsList  from "./FriendsList.tsx";
import  FriendsSearch from "./FriendsSearch.tsx";
import  FriendRequestInbox  from "./FriendRequestInbox.tsx";
import  ChatWindow  from "./ChatWindow.tsx";
import "@/styles/friends-panel.css";

type TabType = "friends" | "search" | "inbox";

interface SelectedFriend extends User {
  conversationId?: string;
}

interface FriendsPanelProps {
  isOpen: boolean;
  onClose: () => void;
}

export default function FriendsPanel({ isOpen, onClose }: FriendsPanelProps) {
  const [activeTab, setActiveTab] = useState<TabType>("friends");
  const [friends, setFriends] = useState<Friendship[]>([]);
  const [pendingRequests, setPendingRequests] = useState<FriendRequest[]>([]);
  const [selectedFriend, setSelectedFriend] = useState<SelectedFriend | null>(
    null
  );
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Load friends and pending requests
  const loadData = useCallback(async () => {
    try {
      setIsLoading(true);
      setError(null);
      const [friendsData, requestsData] = await Promise.all([
        friendsService.getFriends(),
        friendsService.getPendingRequests(),
      ]);
      setFriends(friendsData);
      setPendingRequests(requestsData);
    } catch (err) {
      setError("Không thể tải danh sách bạn bè. Vui lòng thử lại.");
      console.error("Error loading friends:", err);
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    if (isOpen) {
      void loadData();
    }
  }, [isOpen, loadData]);

  const handleSelectFriend = async (friend: User) => {
    try {
      setSelectedFriend({ ...friend, conversationId: undefined });
      // Try to find or create conversation with this friend
      const conversations = await conversationsService.listConversations();
      const existingConversation = conversations.find((conv) => {
        if (conv.type === "direct") {
          // Check if this conversation is with the selected friend
          return true; // Simplified for now, backend should filter
        }
        return false;
      });

      if (existingConversation) {
        setSelectedFriend((prev) =>
          prev
            ? { ...prev, conversationId: existingConversation.id as string }
            : null
        );
      } else {
        // Create new direct conversation
        const newConversation =
          await conversationsService.createDirectConversation(friend.id);
        setSelectedFriend((prev) =>
          prev
            ? { ...prev, conversationId: newConversation.id as string }
            : null
        );
      }
    } catch (err) {
      setError("Không thể tạo cuộc trò chuyện. Vui lòng thử lại.");
      console.error("Error selecting friend:", err);
    }
  };

  const handleRequestAccepted = () => {
    void loadData();
    setActiveTab("friends");
  };

  const handleBackFromChat = () => {
    setSelectedFriend(null);
  };

  if (!isOpen) return null;

  // Show chat window if friend is selected
  if (selectedFriend && selectedFriend.conversationId) {
    return (
      <ChatWindow
        friend={selectedFriend}
        conversationId={selectedFriend.conversationId}
        onBack={handleBackFromChat}
      />
    );
  }

  return (
    <div className="friends-panel">
      <div className="friends-panel-header">
        <h2>Bạn bè & Chat</h2>
        <button className="friends-panel-close" onClick={onClose}>
          ✕
        </button>
      </div>

      {error && <div className="friends-panel-error">{error}</div>}

      <div className="friends-panel-tabs">
        <button
          className={`friends-tab ${activeTab === "friends" ? "active" : ""}`}
          onClick={() => setActiveTab("friends")}
        >
          👥 Bạn bè ({friends.length})
        </button>
        <button
          className={`friends-tab ${activeTab === "search" ? "active" : ""}`}
          onClick={() => setActiveTab("search")}
        >
          🔍 Tìm kiếm
        </button>
        <button
          className={`friends-tab ${activeTab === "inbox" ? "active" : ""}`}
          onClick={() => setActiveTab("inbox")}
        >
          📬 Lời mời ({pendingRequests.length})
        </button>
      </div>

      <div className="friends-panel-content">
        {activeTab === "friends" && (
          <FriendsList
            friends={friends}
            isLoading={isLoading}
            onSelectFriend={handleSelectFriend}
          />
        )}

        {activeTab === "search" && (
          <FriendsSearch
            onFriendSelected={handleSelectFriend}
            onRequestSent={() => void loadData()}
          />
        )}

        {activeTab === "inbox" && (
          <FriendRequestInbox
            requests={pendingRequests}
            isLoading={isLoading}
            onRequestAccepted={handleRequestAccepted}
            onRequestRejected={() => void loadData()}
          />
        )}
      </div>
    </div>
  );
}
