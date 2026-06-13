"use client";

import React, { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useAuth } from "@/contexts/AuthContext";
import GuidedTour, { GuidedTourStep } from "@/components/common/GuidedTour";

const ONBOARDING_STATE_KEY = "quizbattle_onboarding_state";
const LOGIN_TOUR_DONE_KEY = "login_play_tour_done";

const loginTourSteps: GuidedTourStep[] = [
  {
    selector: '[data-tour="login-form"]',
    title: "Đăng nhập để vào khu chơi",
    body: "Nhập tài khoản của bạn ở đây. Sau khi đăng nhập thành công, hệ thống sẽ đưa bạn vào Dashboard để tạo quiz, tạo phòng hoặc nhập mã phòng.",
  },
  {
    selector: '[data-tour="register-link"]',
    title: "Chưa có tài khoản?",
    body: "Nếu bạn là người mới, bấm Đăng ký miễn phí trước. Đăng ký xong quay lại đăng nhập, tour sẽ tiếp tục ở Dashboard.",
    actionLabel: "Đã hiểu",
  },
];

export default function LoginScreen() {
  const [loginMode, setLoginMode] = useState<"password" | "emailOtp">("password");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [otpEmail, setOtpEmail] = useState("");
  const [otpCode, setOtpCode] = useState("");
  const [otpSent, setOtpSent] = useState(false);
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState("");
  const [successMessage, setSuccessMessage] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [isTourOpen, setIsTourOpen] = useState(false);
  const router = useRouter();
  const { login, requestEmailOtp, loginWithEmailOtp } = useAuth();

  const redirectAfterLogin = useMemo(() => {
    if (typeof window === "undefined") return "/dashboard";

    const params = new URLSearchParams(window.location.search);
    const nextParam = params.get("next");
    const savedRedirect = sessionStorage.getItem("postLoginRedirect");
    const target = nextParam || savedRedirect || "/dashboard";

    if (!target.startsWith("/") || target.startsWith("//")) {
      return "/dashboard";
    }

    return target;
  }, []);
  const loginReasonMessage = redirectAfterLogin.startsWith("/room/")
    ? "Bạn cần đăng nhập để vào phòng được mời. Đăng nhập xong hệ thống sẽ đưa bạn quay lại phòng."
    : "";

  useEffect(() => {
    const shouldShowTour = localStorage.getItem(ONBOARDING_STATE_KEY) === "login";
    const wasLoginTourDone = localStorage.getItem(LOGIN_TOUR_DONE_KEY) === "true";
    if (shouldShowTour && !wasLoginTourDone) {
      const timeout = window.setTimeout(() => setIsTourOpen(true), 500);
      return () => window.clearTimeout(timeout);
    }
  }, []);

  const getLoginErrorMessage = (err: any) => {
    const status = err?.response?.status;
    const detail = err?.response?.data?.detail || err?.response?.data?.message;

    if (status === 401 || detail === "Invalid username or password") {
      return "Tên tài khoản hoặc mật khẩu không đúng.";
    }

    if (typeof detail === "string") {
      return detail;
    }

    return "Đăng nhập thất bại. Vui lòng thử lại.";
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setSuccessMessage("");
    setIsLoading(true);

    try {
      await login(username, password);
      await finishSuccessfulLogin();
    } catch (err: any) {
      setError(getLoginErrorMessage(err));
    } finally {
      setIsLoading(false);
    }
  };

  const finishSuccessfulLogin = async () => {
    setSuccessMessage("Đăng nhập thành công! Đang chuyển đến Dashboard...");
    await new Promise((resolve) => setTimeout(resolve, 1500));
    if (typeof window !== "undefined") {
      sessionStorage.removeItem("postLoginRedirect");
      if (localStorage.getItem(ONBOARDING_STATE_KEY) === "login") {
        localStorage.setItem(ONBOARDING_STATE_KEY, "dashboard");
      }
    }
    router.push(redirectAfterLogin);
  };

  const getOtpErrorMessage = (err: any) => {
    const detail = err?.response?.data?.detail || err?.response?.data?.message;
    return typeof detail === "string" ? detail : "Không thể xử lý mã đăng nhập. Vui lòng thử lại.";
  };

  const handleRequestOtp = async (e?: React.FormEvent | React.MouseEvent) => {
    e?.preventDefault();
    setError("");
    setSuccessMessage("");
    setIsLoading(true);

    try {
      await requestEmailOtp(otpEmail);
      setOtpSent(true);
      setSuccessMessage("Mã đăng nhập đã được gửi. Vui lòng kiểm tra email của bạn.");
    } catch (err: any) {
      setError(getOtpErrorMessage(err));
    } finally {
      setIsLoading(false);
    }
  };

  const handleVerifyOtp = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setSuccessMessage("");
    setIsLoading(true);

    try {
      await loginWithEmailOtp(otpEmail, otpCode);
      await finishSuccessfulLogin();
    } catch (err: any) {
      setError(getOtpErrorMessage(err));
    } finally {
      setIsLoading(false);
    }
  };

    const handleGoogleLogin = () => {
    const clientId = process.env.NEXT_PUBLIC_GOOGLE_CLIENT_ID || "your-google-client-id-here.apps.googleusercontent.com";
    const redirectUri = process.env.NEXT_PUBLIC_GOOGLE_REDIRECT_URI || "http://localhost:3000/auth/callback";
    const scope = "openid email profile";
    const responseType = "code";

    if (
      process.env.NODE_ENV === "production" &&
      redirectUri.startsWith("http://localhost")
    ) {
      // eslint-disable-next-line no-console
      console.warn(
        "[GoogleLogin] NEXT_PUBLIC_GOOGLE_REDIRECT_URI chưa được set khi build production. " +
        "Google sẽ redirect về localhost sau khi đăng nhập — user sẽ không vào được app."
      );
    }

    const authUrl = `https://accounts.google.com/o/oauth2/v2/auth?client_id=${encodeURIComponent(clientId)}&redirect_uri=${encodeURIComponent(redirectUri)}&response_type=${responseType}&scope=${encodeURIComponent(scope)}&prompt=select_account`;

    window.location.href = authUrl;
  };


  return (
    <div className="login-wrap">
      <Link className="login-back-btn" href="/">
        <span aria-hidden="true">←</span>
        Quay lại trang giới thiệu
      </Link>
      <div className="login-left">
        <div className="brand-badge"><span className="dot" /> Quiz đấu thời gian thực</div>
        <h1 className="login-title">
          <img className="login-title-icon" src="/favicon.png" alt="QuizBattle" />
          <span>Chào mừng trở lại <strong>QuizBattle</strong></span>
        </h1>
        <p className="login-sub">Nền tảng đấu quiz thời gian thực. Tạo phòng, mời bạn bè và thi đấu ngay!</p>

        {loginReasonMessage && !error && !successMessage && (
          <div className="login-alert info" role="status" aria-live="polite">
            {loginReasonMessage}
          </div>
        )}

        {(error || successMessage) && (
          <div className={`login-alert ${error ? "error" : "success"}`} role="alert" aria-live="polite">
            {error || successMessage}
          </div>
        )}

        <div className="login-mode-tabs" role="tablist" aria-label="Chọn kiểu đăng nhập">
          <button
            className={`login-mode-tab ${loginMode === "password" ? "active" : ""}`}
            type="button"
            onClick={() => {
              setLoginMode("password");
              setError("");
              setSuccessMessage("");
            }}
          >
            Mật khẩu
          </button>
          <button
            className={`login-mode-tab ${loginMode === "emailOtp" ? "active" : ""}`}
            type="button"
            onClick={() => {
              setLoginMode("emailOtp");
              setError("");
              setSuccessMessage("");
            }}
          >
            Mã email
          </button>
        </div>

        {loginMode === "password" ? (
          <form onSubmit={handleSubmit} data-tour="login-form">
            <div className="form-group">
              <label className="form-label">Tên tài khoản</label>
              <input
                className="form-input"
                type="text"
                placeholder="Nhập tên tài khoản..."
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                required
              />
            </div>
            <div className="form-group">
              <label className="form-label">Mật khẩu</label>
              <div className="password-wrapper">
                <input
                  className="form-input"
                  type={showPassword ? "text" : "password"}
                  placeholder="Nhập mật khẩu..."
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  required
                />
                <button
                  type="button"
                  className="password-toggle"
                  onClick={() => setShowPassword(!showPassword)}
                  aria-label={showPassword ? "Ẩn mật khẩu" : "Hiện mật khẩu"}
                >
                  {showPassword ? "👁" : "🙈"}
                </button>
              </div>
            </div>

            <button className="btn-primary" type="submit" disabled={isLoading}>
              {isLoading ? "Đang đăng nhập..." : "Đăng nhập →"}
            </button>
          </form>
        ) : (
          <form onSubmit={otpSent ? handleVerifyOtp : handleRequestOtp} data-tour="login-form">
            <div className="form-group">
              <label className="form-label">Email tài khoản</label>
              <input
                className="form-input"
                type="email"
                placeholder="Nhập email đã đăng ký..."
                value={otpEmail}
                onChange={(e) => setOtpEmail(e.target.value)}
                required
              />
            </div>

            {otpSent && (
              <div className="form-group">
                <label className="form-label">Mã xác thực</label>
                <input
                  className="form-input otp-code-input"
                  type="text"
                  inputMode="numeric"
                  pattern="[0-9]{6}"
                  maxLength={6}
                  placeholder="000000"
                  value={otpCode}
                  onChange={(e) => setOtpCode(e.target.value.replace(/\D/g, "").slice(0, 6))}
                  required
                />
              </div>
            )}

            <button className="btn-primary" type="submit" disabled={isLoading || (otpSent && otpCode.length !== 6)}>
              {isLoading ? "Đang xử lý..." : otpSent ? "Xác thực mã →" : "Gửi mã đăng nhập"}
            </button>

            {otpSent && (
              <button
                className="otp-resend-btn"
                type="button"
                disabled={isLoading}
                onClick={handleRequestOtp}
              >
                Gửi lại mã
              </button>
            )}
          </form>
        )}

        <div className="login-divider">hoặc</div>
        <button className="btn-outline" type="button" onClick={handleGoogleLogin}>
          <svg width="16" height="16" viewBox="0 0 24 24">
            <path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z" />
            <path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" />
            <path fill="#FBBC05" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z" />
            <path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z" />
          </svg>
          Tiếp tục với Google
        </button>

        <p className="login-footer">Chưa có tài khoản? <Link className="link" href="/register" data-tour="register-link">Đăng ký miễn phí</Link></p>
      </div>

      <div className="login-right">
        <div className="orb orb-1" />
        <div className="orb orb-2" />
        <div className="floating-demo">
          <div className="demo-card">
            <div className="demo-card-title">Thống kê hôm nay</div>
            <div className="demo-stat-row">
              <div className="demo-stat">
                <div className="demo-stat-val">1,247</div>
                <div className="demo-stat-lbl">Phòng đang chơi</div>
              </div>
              <div className="demo-stat">
                <div className="demo-stat-val" style={{ color: "var(--accent)" }}>8,931</div>
                <div className="demo-stat-lbl">Người online</div>
              </div>
            </div>
          </div>
          <div className="demo-card">
            <div className="demo-card-title">Leaderboard</div>
            <div className="demo-players">
              <div className="demo-player"><div className="demo-avatar" style={{ background: "rgba(245,158,11,.2)", color: "var(--gold)" }}>🥇</div><span className="demo-player-name">Minh Khoa</span><span className="demo-player-score">9,850</span></div>
              <div className="demo-player"><div className="demo-avatar" style={{ background: "rgba(148,163,184,.15)", color: "#94A3B8" }}>🥈</div><span className="demo-player-name">Lan Anh</span><span className="demo-player-score">8,600</span></div>
              <div className="demo-player"><div className="demo-avatar" style={{ background: "rgba(205,127,50,.15)", color: "#CD7F32" }}>🥉</div><span className="demo-player-name">Tuấn Hùng</span><span className="demo-player-score">7,200</span></div>
            </div>
          </div>
          <div className="demo-card">
            <div className="demo-card-title">Quiz đang hot</div>
            <div style={{ fontSize: "13px", marginBottom: "6px", fontWeight: 600 }}>Địa Lý Thế Giới</div>
            <div style={{ fontSize: "11px", color: "var(--muted)" }}>234 người đã chơi hôm nay • 10 câu hỏi</div>
          </div>
        </div>
      </div>
      <GuidedTour
        steps={loginTourSteps}
        isOpen={isTourOpen}
        onClose={() => setIsTourOpen(false)}
        storageKey={LOGIN_TOUR_DONE_KEY}
      />
    </div>
  );
}
