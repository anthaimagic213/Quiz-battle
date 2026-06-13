"use client";

import React, { useState, useCallback, useEffect, useMemo } from "react";
import { friendsService, User, Friendship } from "@/services/friendsService";

interface FriendsSearchProps {
  onFriendSelected?: (friend: User) => void;
  onRequestSent?: () => void;
  /**
   * Danh sách bạn bè hiện tại (Friendship[]) để hiển thị trạng thái "Bạn bè"
   * cho những user đã kết bạn thay vì nút "+ Kết bạn".
   */
  friends?: Friendship[];
  /**
   * ID người dùng hiện tại (để loại trừ chính mình khi build set bạn bè).
   */
  currentUserId?: string;
}

export default function FriendsSearch({
  onFriendSelected,
  onRequestSent,
  friends = [],
  currentUserId,
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

  // Yêu cầu: chỉ tìm kiếm khi người dùng đã gõ đủ 6 ký tự liền nhau
  // (6 ký tự liên tục trong username hoặc email, không tính khoảng trắng ở đầu/cuối).
  const MIN_SEARCH_LENGTH = 6;
  const trimmedQuery = searchQuery.trim();
  const isQueryLongEnough = trimmedQuery.length >= MIN_SEARCH_LENGTH;
  const remainingChars = Math.max(0, MIN_SEARCH_LENGTH - trimmedQuery.length);

  const handleSearch = useCallback(async (query: string, page: number = 1) => {
    const q = query.trim();
    if (q.length < MIN_SEARCH_LENGTH) {
      // Chưa đủ 6 ký tự: clear kết quả, không gọi API
      setSearchResults([]);
      setTotalResults(0);
      setIsLoading(false);
      return;
    }

    try {
      setIsLoading(true);
      setError(null);
      const response = await friendsService.searchUsers(q, page, itemsPerPage);
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
    // Nếu chưa đủ 6 ký tự, reset ngay không cần debounce.
    if (!isQueryLongEnough) {
      setSearchResults([]);
      setTotalResults(0);
      setError(null);
      return;
    }

    const timer = setTimeout(() => {
      setCurrentPage(1);
      void handleSearch(searchQuery, 1);
    }, 300);

    return () => clearTimeout(timer);
  }, [searchQuery, isQueryLongEnough, handleSearch]);

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

  const handlePageChange = (newPage: number) => {
    setCurrentPage(newPage);
    void handleSearch(searchQuery, newPage);
  };

  // Tập ID của những user đã là bạn bè với current user
  // (tính từ cả 2 chiều user_id_1 / user_id_2 của friendships).
  const friendIds = useMemo(() => {
    const ids = new Set<string>();
    for (const friendship of friends) {
      const u1 = String(friendship.user_id_1);
      const u2 = String(friendship.user_id_2);
      if (currentUserId && u1 === String(currentUserId)) {
        ids.add(u2);
      } else if (currentUserId && u2 === String(currentUserId)) {
        ids.add(u1);
      } else if (!currentUserId) {
        // Không rõ current user: thêm cả 2 để tránh hiển thị sai (defensive)
        ids.add(u1);
        ids.add(u2);
      }
    }
    return ids;
  }, [friends, currentUserId]);

  return (
    <div className="friends-search">
      <div className="friends-search-input-wrapper">
        <input
          type="text"
          className="friends-search-input"
          placeholder="Nhập username hoặc email (tối thiểu 6 ký tự)..."
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
            aria-label="Xóa tìm kiếm"
          >
            ✕
          </button>
        )}
      </div>

      {error && <div className="friends-search-error">{error}</div>}

      <div className="friends-search-results">
        {/* Gợi ý khi chưa đủ 6 ký tự */}
        {!isLoading && trimmedQuery.length > 0 && !isQueryLongEnough && (
          <div className="friends-search-hint">
            <div className="hint-icon">✏️</div>
            <p>
              Bạn cần nhập thêm <strong>{remainingChars}</strong> ký tự nữa (tối thiểu {MIN_SEARCH_LENGTH} ký tự) để bắt đầu tìm kiếm.
            </p>
          </div>
        )}

        {isLoading && (
          <div className="friends-search-loading">
            <div className="spinner">⟳</div>
            <p>Đang tìm kiếm...</p>
          </div>
        )}

        {!isLoading && isQueryLongEnough && searchResults.length === 0 && (
          <div className="friends-search-empty">
            <div className="empty-icon">🔍</div>
            <p className="empty-title">Không tìm thấy kết quả</p>
            <p className="empty-subtitle">
              Thử tìm kiếm bằng tên, username hoặc email khác
            </p>
          </div>
        )}

        {!isLoading && isQueryLongEnough && searchResults.length > 0 && (
          <>
            <div className="friends-search-count">
              Tìm thấy {totalResults} người dùng
            </div>
            <div className="friends-search-list">
              {searchResults.map((user) => {
                const userId = String(user.id);
                const isFriend = friendIds.has(userId);
                const isRequestSent = requestSentIds.has(userId);
                let buttonClass = "friends-search-item-btn";
                let buttonLabel = "+ Kết bạn";
                let buttonDisabled = false;

                if (isFriend) {
                  buttonClass += " friend";
                  buttonLabel = "✓ Bạn bè";
                  buttonDisabled = true;
                } else if (isRequestSent) {
                  buttonClass += " sent";
                  buttonLabel = "✓ Đã gửi";
                  buttonDisabled = true;
                }

                return (
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
                        {user.email && (
                          <div className="friends-search-item-email">{user.email}</div>
                        )}
                      </div>
                    </div>
                    <button
                      className={buttonClass}
                      onClick={() => handleSendRequest(userId)}
                      disabled={buttonDisabled}
                    >
                      {buttonLabel}
                    </button>
                  </div>
                );
              })}
            </div>

            {totalPages > 1 && (
              <div className="friends-search-pagination">
                <button
                  className="pagination-btn"
                  onClick={() => handlePageChange(Math.max(1, currentPage - 1))}
                  disabled={currentPage === 1}
                >
                  ← Trước
                </button>

                <div className="pagination-info">
                  Trang {currentPage} / {totalPages}
                </div>

                <button
                  className="pagination-btn"
                  onClick={() => handlePageChange(Math.min(totalPages, currentPage + 1))}
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
            <p>Nhập username hoặc email (ít nhất {MIN_SEARCH_LENGTH} ký tự) để tìm kiếm người dùng.</p>
          </div>
        )}
      </div>
    </div>
  );
}
