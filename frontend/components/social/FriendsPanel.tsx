"use client";

import React, { useState, useEffect, useCallback, useMemo } from "react";
import {
  friendsService,
  Friendship,
  FriendRequest,
  User,
} from "@/services/friendsService";
import { conversationsService, Conversation } from "@/services/conversationsService";
import { useAuth } from "@/contexts/AuthContext";
import FriendsList from "./FriendsList";
import FriendsSearch from "./FriendsSearch";
import FriendRequestInbox from "./FriendRequestInbox";
import ChatWindow from "./ChatWindow";
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
  const { user: currentUser } = useAuth();
  const [activeTab, setActiveTab] = useState<TabType>("friends");
  const [friends, setFriends] = useState<Friendship[]>([]);
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [pendingRequests, setPendingRequests] = useState<FriendRequest[]>([]);
  const [selectedFriend, setSelectedFriend] = useState<SelectedFriend | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const currentUserId = currentUser?.id;

  const loadData = useCallback(async () => {
    try {
      setIsLoading(true);
      setError(null);
      const [friendsData, requestsData, convsData] = await Promise.all([
        friendsService.getFriends(),
        friendsService.getPendingRequests(),
        conversationsService.listConversations().catch(() => []),
      ]);
      setFriends(friendsData);
      setPendingRequests(requestsData);
      setConversations(convsData);
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

  // Build a quick lookup from friend_id -> conversationId (only direct chats).
  const conversationByFriendId = useMemo(() => {
    const map = new Map<string, string>();
    if (!currentUserId) return map;
    for (const conv of conversations) {
      if (conv.type === "direct" && conv.other_member?.id) {
        if (conv.other_member.id !== currentUserId) {
          map.set(conv.other_member.id, conv.id);
        }
      }
    }
    return map;
  }, [conversations, currentUserId]);

  const handleSelectFriend = async (friend: User) => {
    try {
      setError(null);
      const existingConvId = conversationByFriendId.get(friend.id);
      if (existingConvId) {
        setSelectedFriend({ ...friend, conversationId: existingConvId });
        return;
      }

      // No existing conversation — create (or fetch) the direct conversation.
      const newConversation = await conversationsService.createDirectConversation(
        friend.id
      );
      setConversations((prev) => {
        if (prev.some((c) => c.id === newConversation.id)) return prev;
        return [newConversation, ...prev];
      });
      setSelectedFriend({ ...friend, conversationId: newConversation.id });
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
    void loadData();
  };

  if (!isOpen) return null;

  if (selectedFriend && selectedFriend.conversationId && currentUserId) {
    return (
      <ChatWindow
        friend={selectedFriend}
        conversationId={selectedFriend.conversationId}
        currentUserId={currentUserId}
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
