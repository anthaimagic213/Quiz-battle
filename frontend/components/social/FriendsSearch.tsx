"use client";

import React, { useState, useCallback, useEffect } from "react";
import { friendsService, User } from "@/services/friendsService";

interface FriendsSearchProps {
  onFriendSelected?: (friend: User) => void;
  onRequestSent?: () => void;
}

export default function FriendsSearch({
  onFriendSelected,
  onRequestSent,
}: FriendsSearchProps) {
  const [searchQuery, setSearchQuery] = useState("");
  const [searchResults, setSearchResults] = useState<User[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [currentPage, setCurrentPage] = useState(1);
  const [totalResults, setTotalResults] = useState(0);
  const [requestSentIds, setRequestSentIds] = useState<Set<string>>(
    new Set()
  );

  const itemsPerPage = 10;
  const totalPages = Math.ceil(totalResults / itemsPerPage);

  const handleSearch = useCallback(async (query: string, page: number = 1) => {
    if (!query.trim()) {
      setSearchResults([]);
      setTotalResults(0);
      return;
    }

    try {
      setIsLoading(true);
      setError(null);
      const response = await friendsService.searchUsers(query, page, itemsPerPage);
      setSearchResults(response.users);
      setTotalResults(response.total);
    } catch (err) {
      setError("Không thể tìm kiếm người dùng. Vui lòng thử lại.");
      console.error("Search error:", err);
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    const timer = setTimeout(() => {
      setCurrentPage(1);
      void handleSearch(searchQuery, 1);
    }, 300);

    return () => clearTimeout(timer);
  }, [searchQuery, handleSearch]);

  const handleSendRequest = async (userId: string) => {
    try {
      await friendsService.sendFriendRequest(userId as any);
      setRequestSentIds((prev) => new Set(prev).add(userId));
      if (onRequestSent) {
        onRequestSent();
      }
      // Show success message
      const user = searchResults.find((u) => u.id === userId);
      if (user) {
        alert(`Đã gửi lời mời kết bạn đến ${user.username}`);
      }
    } catch (err: any) {
      if (err.response?.status === 400) {
        alert("Bạn đã gửi lời mời cho người dùng này rồi hoặc đã là bạn bè.");
      } else {
        alert("Không thể gửi lời mời. Vui lòng thử lại.");
      }
      console.error("Send request error:", err);
    }
  };

  const handleSelectFriend = (user: User) => {
    if (onFriendSelected) {
      onFriendSelected(user);
    }
  };

  return (
    <div className="friends-search">
      <div className="friends-search-input-wrapper">
        <input
          type="text"
          className="friends-search-input"
          placeholder="Tìm kiếm theo tên hoặc username..."
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          autoFocus
        />
        {searchQuery && (
          <button
            className="friends-search-clear"
            onClick={() => {
              setSearchQuery("");
              setSearchResults([]);
              setTotalResults(0);
            }}
          >
            ✕
          </button>
        )}
      </div>

      {error && <div className="friends-search-error">{error}</div>}

      <div className="friends-search-results">
        {isLoading && (
          <div className="friends-search-loading">
            <div className="spinner">⟳</div>
            <p>Đang tìm kiếm...</p>
          </div>
        )}

        {!isLoading && searchQuery && searchResults.length === 0 && (
          <div className="friends-search-empty">
            <div className="empty-icon">🔍</div>
            <p className="empty-title">Không tìm thấy kết quả</p>
            <p className="empty-subtitle">
              Thử tìm kiếm bằng tên hoặc username khác
            </p>
          </div>
        )}

        {!isLoading && searchQuery && searchResults.length > 0 && (
          <>
            <div className="friends-search-count">
              Tìm thấy {totalResults} người dùng
            </div>
            <div className="friends-search-list">
              {searchResults.map((user) => (
                <div key={user.id} className="friends-search-item">
                  <div
                    className="friends-search-item-info"
                    onClick={() => handleSelectFriend(user)}
                  >
                    <div className="friends-search-item-avatar">
                      {user.avatar_url ? (
                        <img src={user.avatar_url} alt={user.username} />
                      ) : (
                        <div className="avatar-placeholder">
                          {(user.username || "?")[0].toUpperCase()}
                        </div>
                      )}
                    </div>
                    <div className="friends-search-item-content">
                      <div className="friends-search-item-name">
                        {user.full_name || user.username}
                      </div>
                      <div className="friends-search-item-username">
                        @{user.username}
                      </div>
                    </div>
                  </div>
                  <button
                    className={`friends-search-item-btn ${
                      requestSentIds.has(user.id as string) ? "sent" : ""
                    }`}
                    onClick={() => handleSendRequest(user.id as string)}
                    disabled={requestSentIds.has(user.id as string)}
                  >
                    {requestSentIds.has(user.id as string)
                      ? "✓ Đã gửi"
                      : "+ Kết bạn"}
                  </button>
                </div>
              ))}
            </div>

            {totalPages > 1 && (
              <div className="friends-search-pagination">
                <button
                  className="pagination-btn"
                  onClick={() => setCurrentPage((p) => Math.max(1, p - 1))}
                  disabled={currentPage === 1}
                >
                  ← Trước
                </button>

                <div className="pagination-info">
                  Trang {currentPage} / {totalPages}
                </div>

                <button
                  className="pagination-btn"
                  onClick={() =>
                    setCurrentPage((p) => Math.min(totalPages, p + 1))
                  }
                  disabled={currentPage === totalPages}
                >
                  Sau →
                </button>
              </div>
            )}
          </>
        )}

        {!searchQuery && (
          <div className="friends-search-hint">
            <div className="hint-icon">💡</div>
            <p>Nhập tên hoặc username để tìm kiếm người dùng</p>
          </div>
        )}
      </div>
    </div>
  );
}
