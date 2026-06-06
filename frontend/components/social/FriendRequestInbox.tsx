"use client";

import React, { useState } from "react";
import { friendsService, FriendRequest } from "@/services/friendsService";

interface FriendRequestInboxProps {
  requests: FriendRequest[];
  isLoading: boolean;
  onRequestAccepted?: () => void;
  onRequestRejected?: () => void;
}

export default function FriendRequestInbox({
  requests,
  isLoading,
  onRequestAccepted,
  onRequestRejected,
}: FriendRequestInboxProps) {
  const [processingIds, setProcessingIds] = useState<Set<string>>(new Set());

  const handleRespond = async (
    requestId: string,
    status: "accepted" | "rejected"
  ) => {
    try {
      setProcessingIds((prev) => new Set(prev).add(requestId));
      await friendsService.respondFriendRequest(requestId as any, status);

      if (status === "accepted" && onRequestAccepted) {
        onRequestAccepted();
      } else if (status === "rejected" && onRequestRejected) {
        onRequestRejected();
      }
    } catch (err) {
      alert("Không thể xử lý lời mời. Vui lòng thử lại.");
      console.error("Error responding to request:", err);
    } finally {
      setProcessingIds((prev) => {
        const next = new Set(prev);
        next.delete(requestId);
        return next;
      });
    }
  };

  if (isLoading) {
    return (
      <div className="inbox-loading">
        <div className="spinner">⟳</div>
        <p>Đang tải lời mời...</p>
      </div>
    );
  }

  if (requests.length === 0) {
    return (
      <div className="inbox-empty">
        <div className="empty-icon">📬</div>
        <p className="empty-title">Không có lời mời nào</p>
        <p className="empty-subtitle">
          Khi có người gửi lời mời kết bạn, nó sẽ hiển thị ở đây
        </p>
      </div>
    );
  }

  return (
    <div className="inbox">
      <div className="inbox-count">Có {requests.length} lời mời chưa xử lý</div>
      <div className="inbox-list">
        {requests.map((request) => {
          const isProcessing = processingIds.has(request.id as string);
          const requester = (request as any).requester || {
            username: "Unknown User",
            avatar_url: null,
          };

          return (
            <div key={request.id} className="inbox-item">
              <div className="inbox-item-avatar">
                {requester.avatar_url ? (
                  <img src={requester.avatar_url} alt={requester.username} />
                ) : (
                  <div className="avatar-placeholder">
                    {(requester.username || "?")[0].toUpperCase()}
                  </div>
                )}
              </div>

              <div className="inbox-item-content">
                <div className="inbox-item-name">
                  {requester.full_name || requester.username}
                </div>
                <div className="inbox-item-username">@{requester.username}</div>
                <div className="inbox-item-time">
                  {new Date(request.created_at).toLocaleDateString("vi-VN")}
                </div>
              </div>

              <div className="inbox-item-actions">
                <button
                  className="inbox-btn inbox-btn-accept"
                  onClick={() =>
                    handleRespond(request.id as string, "accepted")
                  }
                  disabled={isProcessing}
                >
                  ✓ Đồng ý
                </button>
                <button
                  className="inbox-btn inbox-btn-reject"
                  onClick={() =>
                    handleRespond(request.id as string, "rejected")
                  }
                  disabled={isProcessing}
                >
                  ✕ Từ chối
                </button>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
