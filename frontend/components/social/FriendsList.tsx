"use client";

import React, { useMemo } from "react";
import { Friendship } from "@/services/friendsService";

interface FriendsListProps {
  friends: Friendship[];
  isLoading: boolean;
  onSelectFriend: (friend: any) => void;
}

export default function FriendsList({
  friends,
  isLoading,
  onSelectFriend,
}: FriendsListProps) {
  if (isLoading) {
    return (
      <div className="friends-list-loading">
        <div className="spinner">⟳</div>
        <p>Đang tải danh sách bạn bè...</p>
      </div>
    );
  }

  if (friends.length === 0) {
    return (
      <div className="friends-list-empty">
        <div className="empty-icon">👥</div>
        <p className="empty-title">Chưa có bạn bè</p>
        <p className="empty-subtitle">
          Hãy tìm kiếm và thêm bạn bè để bắt đầu chat
        </p>
      </div>
    );
  }

  return (
    <div className="friends-list">
      {friends.map((friendship) => {
        // Get the friend info (friend is one of the two users in the friendship)
        const friend = (friendship as any).friend || {
          id: friendship.user_id_2 || friendship.user_id_1,
          username: "Unknown User",
          avatar_url: null,
        };

        return (
          <div
            key={friendship.id}
            className="friends-list-item"
            onClick={() => onSelectFriend(friend)}
          >
            <div className="friends-list-item-avatar">
              {friend.avatar_url ? (
                <img src={friend.avatar_url} alt={friend.username} />
              ) : (
                <div className="avatar-placeholder">
                  {(friend.username || "?")[0].toUpperCase()}
                </div>
              )}
              <div className="online-status"></div>
            </div>
            <div className="friends-list-item-content">
              <div className="friends-list-item-name">
                {friend.full_name || friend.username}
              </div>
              <div className="friends-list-item-username">
                @{friend.username}
              </div>
            </div>
            <button className="friends-list-item-action">💬</button>
          </div>
        );
      })}
    </div>
  );
}
