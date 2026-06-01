"use client";

import React, { FormEvent, useEffect, useState } from "react";
import { useAuth } from "@/contexts/AuthContext";
import { authService } from "@/services/authService";
import "../../styles/settings-modal.css";

interface AccountModalProps {
  isOpen: boolean;
  onClose: () => void;
}

function getErrorMessage(error: unknown, fallback: string) {
  const detail = (error as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
  return detail || fallback;
}

export default function AccountModal({ isOpen, onClose }: AccountModalProps) {
  const { user, updateUser } = useAuth();
  const [username, setUsername] = useState("");
  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [avatarUrl, setAvatarUrl] = useState("");
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [showCurrentPassword, setShowCurrentPassword] = useState(false);
  const [showNewPassword, setShowNewPassword] = useState(false);
  const [showConfirmPassword, setShowConfirmPassword] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isSavingProfile, setIsSavingProfile] = useState(false);
  const [isSavingPassword, setIsSavingPassword] = useState(false);
  const [isUploadingAvatar, setIsUploadingAvatar] = useState(false);
  const [activeTab, setActiveTab] = useState<"profile" | "password">("profile");

  useEffect(() => {
    if (!isOpen || !user) return;
    setUsername(user.username);
    setFullName(user.full_name || "");
    setEmail(user.email);
    setAvatarUrl(user.avatar_url || "");
    setCurrentPassword("");
    setNewPassword("");
    setConfirmPassword("");
    setShowCurrentPassword(false);
    setShowNewPassword(false);
    setShowConfirmPassword(false);
    setMessage(null);
    setError(null);
    setActiveTab("profile");
  }, [isOpen]);

  if (!isOpen) return null;

  const handleUpdateProfile = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();

    try {
      setIsSavingProfile(true);
      setError(null);
      setMessage(null);
      const updatedUser = await authService.updateProfile({
        username,
        full_name: fullName.trim() || null,
        email,
        avatar_url: avatarUrl.trim() || null,
      });
      updateUser(updatedUser);
      setMessage("Đã cập nhật thông tin tài khoản.");
    } catch (err) {
      setError(getErrorMessage(err, "Không cập nhật được thông tin tài khoản."));
    } finally {
      setIsSavingProfile(false);
    }
  };

  const handleChangePassword = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();

    if (newPassword !== confirmPassword) {
      setError("Mật khẩu mới và xác nhận mật khẩu không khớp.");
      setMessage(null);
      return;
    }

    try {
      setIsSavingPassword(true);
      setError(null);
      setMessage(null);
      await authService.changePassword({
        current_password: currentPassword,
        new_password: newPassword,
      });
      setCurrentPassword("");
      setNewPassword("");
      setConfirmPassword("");
      setMessage("Đã đổi mật khẩu thành công.");
    } catch (err) {
      setError(getErrorMessage(err, "Không đổi được mật khẩu."));
    } finally {
      setIsSavingPassword(false);
    }
  };

  const handleAvatarFileChange = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;

    try {
      setIsUploadingAvatar(true);
      setError(null);
      setMessage(null);
      const updatedUser = await authService.uploadAvatar(file);
      updateUser(updatedUser);
      setAvatarUrl(updatedUser.avatar_url || "");
      setMessage("Đã cập nhật ảnh đại diện.");
    } catch (err) {
      setError(getErrorMessage(err, "Không tải được ảnh đại diện."));
    } finally {
      setIsUploadingAvatar(false);
    }
  };

  return (
    <div className="settings-modal-overlay" onClick={onClose}>
      <div className="settings-modal-content account-modal-content" onClick={(event) => event.stopPropagation()}>
        <div className="settings-modal-header">
          <h2>🗂️ Quản lý thông tin</h2>
          <button type="button" className="settings-modal-close" onClick={onClose}>
            ✕
          </button>
        </div>

        <div className="settings-modal-body account-modal-body">
          {message && <div className="account-alert success">{message}</div>}
          {error && <div className="account-alert error">{error}</div>}

          <div className="account-tabs" role="tablist" aria-label="Quản lý tài khoản">
            <button
              type="button"
              className={`account-tab${activeTab === "profile" ? " active" : ""}`}
              onClick={() => setActiveTab("profile")}
              role="tab"
              aria-selected={activeTab === "profile"}
            >
              Thông tin tài khoản
            </button>
            <button
              type="button"
              className={`account-tab${activeTab === "password" ? " active" : ""}`}
              onClick={() => setActiveTab("password")}
              role="tab"
              aria-selected={activeTab === "password"}
            >
              Đổi mật khẩu
            </button>
          </div>

          {activeTab === "profile" && (
            <form className="account-section" onSubmit={handleUpdateProfile}>
              <div>
                <div className="settings-label">Thông tin tài khoản</div>
                <p className="account-help">Xem và cập nhật tên hiển thị, email đăng nhập.</p>
              </div>
              <label className="account-field">
                <span>Họ và tên</span>
                <input value={fullName} onChange={(event) => setFullName(event.target.value)} placeholder="Nhập họ và tên ..." />
              </label>
              <label className="account-field">
                <span>Tên tài khoản</span>
                <input value={username} onChange={(event) => setUsername(event.target.value)} required />
              </label>
              <label className="account-field">
                <span>Email</span>
                <input type="email" value={email} onChange={(event) => setEmail(event.target.value)} required />
              </label>
              <label className="account-field">
                <span>Avatar URL</span>
                <input
                  type="url"
                  value={avatarUrl}
                  onChange={(event) => setAvatarUrl(event.target.value)}
                  placeholder="https://example.com/avatar.jpg"
                />
              </label>
              <div className="account-avatar-actions">
                <label className="account-file-btn">
                  {isUploadingAvatar ? "Đang tải ảnh..." : "Chọn ảnh từ máy"}
                  <input type="file" accept="image/*" onChange={handleAvatarFileChange} disabled={isUploadingAvatar} />
                </label>
                {avatarUrl && (
                  <button type="button" className="account-secondary-btn" onClick={() => setAvatarUrl("")}>
                    Xóa avatar
                  </button>
                )}
              </div>
              <div className="account-avatar-preview">
                <div className="account-avatar-frame">
                  {avatarUrl ? (
                    <img src={avatarUrl} alt="Avatar preview" />
                  ) : (
                    <span>{username.trim().slice(0, 1).toUpperCase() || "?"}</span>
                  )}
                </div>
                <span>Ảnh đại diện sẽ hiện ở menu và lobby.</span>
              </div>
              <button type="submit" className="account-primary-btn" disabled={isSavingProfile}>
                {isSavingProfile ? "Đang lưu..." : "Lưu thông tin"}
              </button>
            </form>
          )}

          {activeTab === "password" && (
            <form className="account-section" onSubmit={handleChangePassword}>
              <div>
                <div className="settings-label">Đổi mật khẩu</div>
                <p className="account-help">Nhập mật khẩu hiện tại trước khi đặt mật khẩu mới.</p>
              </div>
              <label className="account-field">
                <span>Mật khẩu hiện tại</span>
                <div className="account-password-wrapper">
                  <input
                    type={showCurrentPassword ? "text" : "password"}
                    value={currentPassword}
                    onChange={(event) => setCurrentPassword(event.target.value)}
                    placeholder="Nhập mật khẩu hiện tại"
                    required
                  />
                  <button
                    type="button"
                    className="account-password-toggle"
                    onClick={() => setShowCurrentPassword((value) => !value)}
                    aria-label={showCurrentPassword ? "Ẩn mật khẩu hiện tại" : "Hiện mật khẩu hiện tại"}
                  >
                    {showCurrentPassword ? "👁" : "🙈"}
                  </button>
                </div>
              </label>
              <label className="account-field">
                <span>Mật khẩu mới</span>
                <div className="account-password-wrapper">
                  <input
                    type={showNewPassword ? "text" : "password"}
                    value={newPassword}
                    minLength={6}
                    onChange={(event) => setNewPassword(event.target.value)}
                    placeholder="Ví dụ: QuizBattle2026"
                    required
                  />
                  <button
                    type="button"
                    className="account-password-toggle"
                    onClick={() => setShowNewPassword((value) => !value)}
                    aria-label={showNewPassword ? "Ẩn mật khẩu mới" : "Hiện mật khẩu mới"}
                  >
                    {showNewPassword ? "👁" : "🙈"}
                  </button>
                </div>
              </label>
              <label className="account-field">
                <span>Xác nhận mật khẩu mới</span>
                <div className="account-password-wrapper">
                  <input
                    type={showConfirmPassword ? "text" : "password"}
                    value={confirmPassword}
                    minLength={6}
                    onChange={(event) => setConfirmPassword(event.target.value)}
                    placeholder="Nhập lại mật khẩu mới"
                    required
                  />
                  <button
                    type="button"
                    className="account-password-toggle"
                    onClick={() => setShowConfirmPassword((value) => !value)}
                    aria-label={showConfirmPassword ? "Ẩn xác nhận mật khẩu" : "Hiện xác nhận mật khẩu"}
                  >
                    {showConfirmPassword ? "👁" : "🙈"}
                  </button>
                </div>
              </label>
              <button type="submit" className="account-primary-btn" disabled={isSavingPassword}>
                {isSavingPassword ? "Đang đổi..." : "Đổi mật khẩu"}
              </button>
            </form>
          )}
        </div>
      </div>
    </div>
  );
}
