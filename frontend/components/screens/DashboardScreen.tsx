"use client";

import React, { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/contexts/AuthContext";
import { quizService } from "@/services/quizService";
import { statisticsService } from "@/services/statisticsService";
import { Quiz, StatisticsResponse } from "@/types";
import GuidedTour, { GuidedTourStep } from "@/components/common/GuidedTour";
import FriendsPanel from "@/components/social/FriendsPanel";
import "@/styles/friends-panel.css";

const recentActivities = [
  {
    dot: "gold",
    title: "Thắng 🥇 Địa Lý Thế Giới",
    detail: "9,850 điểm",
    time: "2h trước",
  },
  {
    dot: "green",
    title: "Tạo quiz Khoa Học",
    detail: "15 câu hỏi",
    time: "hôm qua",
  },
  {
    dot: "cyan",
    title: "Tham gia phòng TF82KL",
    detail: "Hạng 3 - 7,200 điểm",
    time: "2 ngày",
  },
];

const SEARCH_DEBOUNCE_MS = 250;
const MY_QUIZZES_PER_PAGE = 6;
const PROFILE_REMINDER_DISMISSED_KEY = "profile_reminder_dismissed";
const DASHBOARD_TOUR_DONE_KEY = "dashboard_play_tour_done";
const ONBOARDING_STATE_KEY = "quizbattle_onboarding_state";

const dashboardTourSteps: GuidedTourStep[] = [
  {
    selector: '[data-tour="profile"]',
    title: "Bước 1: Hoàn thiện hồ sơ",
    body: "Thêm tên hiển thị và avatar trước khi vào chơi để bạn bè dễ nhận ra bạn trong lobby và bảng xếp hạng.",
  },
  {
    selector: '[data-tour="create-quiz"]',
    title: "Bước 2: Tạo quiz",
    body: "Nếu bạn là chủ phòng, hãy tạo hoặc chọn một bộ câu hỏi trước. Quiz này sẽ dùng làm nội dung trận đấu.",
  },
  {
    selector: '[data-tour="create-room"]',
    title: "Bước 3: Tạo phòng",
    body: "Sau khi có quiz, bấm tạo phòng để lấy mã phòng và gửi cho bạn bè cùng tham gia.",
  },
  {
    selector: '[data-tour="join-room"]',
    title: "Bước 4: Vào phòng bằng mã",
    body: "Nếu bạn nhận được mã phòng từ người khác, nhập mã ở đây rồi bấm Join để vào lobby.",
    actionLabel: "Hoàn tất",
  },
];

function getGreeting() {
  const hour = new Date().getHours();

  if (hour < 11) return "Chào buổi sáng";
  if (hour < 14) return "Chào buổi trưa";
  if (hour < 18) return "Chào buổi chiều";
  return "Chào buổi tối";
}

function formatDate(value?: string) {
  if (!value) return "Vừa tạo";

  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Vừa tạo";

  return new Intl.DateTimeFormat("vi-VN", {
    hour: "2-digit",
    minute: "2-digit",
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
  }).format(date);
}

function getQuestionCount(quiz: Quiz) {
  return quiz.question_count ?? quiz.questions?.length ?? 0;
}

function getApiErrorMessage(err: unknown, fallback: string) {
  const status = (err as { response?: { status?: number } })?.response?.status;

  if (status === 401) {
    return "Phiên đăng nhập đã hết hạn hoặc chưa đăng nhập. Vui lòng đăng nhập lại.";
  }

  if (status === 403) {
    return "Bạn không có quyền truy cập dữ liệu quiz này.";
  }

  return fallback;
}

function normalizeSearchText(value: string) {
  return value
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/đ/g, "d")
    .replace(/Đ/g, "D")
    .toLowerCase()
    .trim();
}

function getVisiblePageItems(currentPage: number, totalPages: number) {
  if (totalPages <= 5) {
    return Array.from({ length: totalPages }, (_, index) => index + 1);
  }

  if (currentPage <= 3) {
    return [1, 2, 3, 4, "end-ellipsis", totalPages] as const;
  }

  if (currentPage >= totalPages - 2) {
    return [1, "start-ellipsis", totalPages - 3, totalPages - 2, totalPages - 1, totalPages] as const;
  }

  return [1, "start-ellipsis", currentPage - 1, currentPage, currentPage + 1, "end-ellipsis", totalPages] as const;
}

export default function DashboardScreen() {
  const router = useRouter();
  const { user, isLoading: isAuthLoading } = useAuth();
  const [quizzes, setQuizzes] = useState<Quiz[]>([]);
  const [joinCode, setJoinCode] = useState("");
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [appliedSearchQuery, setAppliedSearchQuery] = useState("");
  const [greeting, setGreeting] = useState("Chào buổi sáng");
  const [showProfileReminder, setShowProfileReminder] = useState(false);
  const [isTourOpen, setIsTourOpen] = useState(false);
  const [isDashboardTourDone, setIsDashboardTourDone] = useState(false);
  const [statisticsSummary, setStatisticsSummary] = useState<StatisticsResponse["summary"] | null>(null);
  const [myQuizPage, setMyQuizPage] = useState(1);
  const [publicQuizPage, setPublicQuizPage] = useState(1);
  const [isFriendsPanelOpen, setIsFriendsPanelOpen] = useState(false);

  // Fix hydration error: update greeting after client hydration
  useEffect(() => {
    setGreeting(getGreeting());
  }, []);

  const loadQuizzes = useCallback(async () => {
    try {
      setIsLoading(true);
      setError(null);
      const data = await quizService.getAllQuizzes();
      setQuizzes(data);
    } catch (err) {
      setError(getApiErrorMessage(err, "Không tải được danh sách quiz. Kiểm tra backend rồi thử lại."));
    } finally {
      setIsLoading(false);
    }
  }, []);

  const loadStatistics = useCallback(async () => {
    try {
      const data = await statisticsService.getMyStatistics();
      setStatisticsSummary(data.summary);
    } catch (err) {
      console.error("Không tải được thống kê dashboard:", err);
      setStatisticsSummary(null);
    }
  }, []);

  useEffect(() => {
    if (isAuthLoading) {
      return;
    }

    if (!user) {
      setIsLoading(false);
      setError("Bạn chưa đăng nhập. Đang chuyển về trang đăng nhập...");
      router.push("/");
      return;
    }

    void loadQuizzes();
    void loadStatistics();
  }, [isAuthLoading, user, router, loadQuizzes, loadStatistics]);

  useEffect(() => {
    const timeout = setTimeout(() => {
      setAppliedSearchQuery(searchQuery.trim());
    }, SEARCH_DEBOUNCE_MS);

    return () => clearTimeout(timeout);
  }, [searchQuery]);

  useEffect(() => {
    if (!user) {
      setShowProfileReminder(false);
      return;
    }

    const hasAvatar = Boolean(user.avatar_url?.trim());
    const wasDismissed = sessionStorage.getItem(`${PROFILE_REMINDER_DISMISSED_KEY}_${user.id}`) === "true";
    setShowProfileReminder(!hasAvatar && !wasDismissed);
  }, [user]);

  useEffect(() => {
    if (!user || isAuthLoading) return;

    const shouldContinueOnboarding = localStorage.getItem(ONBOARDING_STATE_KEY) === "dashboard";
    const wasDashboardTourDone = localStorage.getItem(DASHBOARD_TOUR_DONE_KEY) === "true";
    setIsDashboardTourDone(wasDashboardTourDone);
    if (shouldContinueOnboarding || !wasDashboardTourDone) {
      const timeout = window.setTimeout(() => setIsTourOpen(true), 500);
      return () => window.clearTimeout(timeout);
    }
  }, [isAuthLoading, user]);

  const myQuizzes = useMemo(
    () => quizzes.filter((quiz) => quiz.created_by === user?.id),
    [quizzes, user?.id]
  );

  const stats = useMemo(
    () => [
      { value: statisticsSummary?.total_games ?? 0, label: "Game đã chơi", color: "purple" },
      { value: Math.round(statisticsSummary?.avg_score ?? 0).toLocaleString("vi-VN"), label: "Điểm trung bình", color: "cyan" },
      { value: myQuizzes.filter((quiz) => !quiz.is_public).length, label: "Quiz private", color: "purple" },
      { value: myQuizzes.filter((quiz) => quiz.is_public).length, label: "Quiz public", color: "gold" },
    ],
    [myQuizzes, statisticsSummary]
  );

  const publicQuizzes = useMemo(
    () => quizzes.filter((quiz) => quiz.is_public && quiz.created_by !== user?.id),
    [quizzes, user?.id]
  );

  const filteredMyQuizzes = useMemo(() => {
    if (!appliedSearchQuery) return myQuizzes;

    const normalizedQuery = normalizeSearchText(appliedSearchQuery);
    return myQuizzes.filter((quiz) => normalizeSearchText(quiz.title).includes(normalizedQuery));
  }, [myQuizzes, appliedSearchQuery]);

  const myQuizTotalPages = Math.max(1, Math.ceil(filteredMyQuizzes.length / MY_QUIZZES_PER_PAGE));
  const myQuizPageItems = getVisiblePageItems(myQuizPage, myQuizTotalPages);
  const paginatedMyQuizzes = useMemo(() => {
    const startIndex = (myQuizPage - 1) * MY_QUIZZES_PER_PAGE;
    return filteredMyQuizzes.slice(startIndex, startIndex + MY_QUIZZES_PER_PAGE);
  }, [filteredMyQuizzes, myQuizPage]);

  useEffect(() => {
    setMyQuizPage(1);
  }, [appliedSearchQuery, myQuizzes.length]);

  useEffect(() => {
    if (myQuizPage > myQuizTotalPages) {
      setMyQuizPage(myQuizTotalPages);
    }
  }, [myQuizPage, myQuizTotalPages]);

  const filteredPublicQuizzes = useMemo(() => {
    if (!appliedSearchQuery) return publicQuizzes;

    const normalizedQuery = normalizeSearchText(appliedSearchQuery);
    return publicQuizzes.filter((quiz) => normalizeSearchText(quiz.title).includes(normalizedQuery));
  }, [publicQuizzes, appliedSearchQuery]);

  const publicQuizTotalPages = Math.max(1, Math.ceil(filteredPublicQuizzes.length / MY_QUIZZES_PER_PAGE));
  const publicQuizPageItems = getVisiblePageItems(publicQuizPage, publicQuizTotalPages);
  const paginatedPublicQuizzes = useMemo(() => {
    const startIndex = (publicQuizPage - 1) * MY_QUIZZES_PER_PAGE;
    return filteredPublicQuizzes.slice(startIndex, startIndex + MY_QUIZZES_PER_PAGE);
  }, [filteredPublicQuizzes, publicQuizPage]);

  useEffect(() => {
    setPublicQuizPage(1);
  }, [appliedSearchQuery, publicQuizzes.length]);

  useEffect(() => {
    if (publicQuizPage > publicQuizTotalPages) {
      setPublicQuizPage(publicQuizTotalPages);
    }
  }, [publicQuizPage, publicQuizTotalPages]);

  const pendingQuizCount = myQuizzes.length;
  const displayName = user?.full_name || user?.username || "Minh Khoa";

  const handleJoinRoom = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const code = joinCode.trim().toUpperCase();
    if (!code) return;

    router.push(`/room/${code}`);
  };

  const handleSearch = () => {
    setAppliedSearchQuery(searchQuery.trim());
  };

  const handleRefreshQuizzes = () => {
    setSearchQuery("");
    setAppliedSearchQuery("");
    void loadQuizzes();
    void loadStatistics();
  };

  const handleOpenProfile = () => {
    window.dispatchEvent(new Event("open-account-modal"));
  };

  const handleDismissProfileReminder = () => {
    if (user?.id) {
      sessionStorage.setItem(`${PROFILE_REMINDER_DISMISSED_KEY}_${user.id}`, "true");
    }
    setShowProfileReminder(false);
  };

  const handleFocusJoinRoom = () => {
    document.getElementById("join-room")?.focus();
  };

  const handleCloseTour = () => {
    localStorage.setItem(ONBOARDING_STATE_KEY, "done");
    localStorage.setItem(DASHBOARD_TOUR_DONE_KEY, "true");
    setIsDashboardTourDone(true);
    setIsTourOpen(false);
  };

  const shouldShowFirstPlayPanel = showProfileReminder || !isDashboardTourDone;

  return (
    <div className="home-wrap">
      <section className="home-hero">
        <div className="hero-text">
          <p className="hero-greeting">{greeting} 👋</p>
          <h1 className="hero-title">
            Xin chào, <span>{displayName}!</span>
          </h1>
          <p className="hero-subtitle">
            Bạn có {pendingQuizCount} quiz đang chờ được chơi. Sẵn sàng chiến chưa?
          </p>
          <div className="hero-cta">
            <button className="btn-hero-primary" onClick={() => router.push("/editor")} data-tour="create-quiz">
              + Tạo quiz mới
            </button>
            <button
              className="btn-hero-secondary"
              onClick={() => setIsFriendsPanelOpen(true)}
              style={{ background: "linear-gradient(135deg, #6366f1 0%, #8b5cf6 100%)" }}
            >
              👥 Bạn bè & Chat
            </button>
            <div className="hero-search">
              <input
                className="hero-search-input"
                placeholder="Tìm quiz theo tên..."
                value={searchQuery}
                onChange={(event) => setSearchQuery(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter") {
                    handleSearch();
                  }
                }}
              />
              <button
                className="btn-hero-secondary hero-refresh-btn"
                onClick={handleRefreshQuizzes}
                disabled={isLoading}
                type="button"
                title="Làm mới danh sách quiz"
              >
                ↻ Làm mới
              </button>
            </div>
            <button className="btn-hero-secondary" onClick={() => router.push("/create-room")} data-tour="create-room">
              ⚡ Tạo phòng chơi
            </button>
            <button className="btn-hero-secondary" onClick={handleFocusJoinRoom}>
              🔍 Join phòng
            </button>
          </div>

        </div>

        <div className="hero-stats">
          {stats.map((stat) => (
            <div className="hero-stat-card" key={stat.label}>
              <div className={`hero-stat-val ${stat.color}`}>{stat.value}</div>
              <div className="hero-stat-lbl">{stat.label}</div>
            </div>
          ))}
        </div>
      </section>

      {shouldShowFirstPlayPanel && (
        <section className="first-play-guide" aria-labelledby="first-play-title">
          <div className="first-play-panel">
            <div className="first-play-icon-badge">
              {(user?.full_name || user?.username || "?").slice(0, 1).toUpperCase()}
            </div>
            <div className="first-play-copy-block">
              <span className="section-title" id="first-play-title">
                {showProfileReminder ? "🚀 Hoàn thiện hồ sơ & vào chơi lần đầu" : "🚀 Lần đầu vào chơi"}
              </span>
              <p className="first-play-subtitle">
                {showProfileReminder
                  ? "Thêm avatar để bạn bè nhận ra bạn trong lobby, rồi mở hướng dẫn từng bước để tạo quiz, tạo phòng hoặc nhập mã phòng."
                  : "Mở hướng dẫn từng bước để app chỉ đúng nút cần bấm: hồ sơ, tạo quiz, tạo phòng và nhập mã phòng."}
              </p>
            </div>
            <div className="first-play-actions">
              {showProfileReminder && (
                <button type="button" className="first-play-later-btn" onClick={handleDismissProfileReminder}>
                  Để sau
                </button>
              )}
              <button type="button" className="first-play-profile-btn" onClick={handleOpenProfile} data-tour="profile">
                {showProfileReminder ? "Cập nhật ngay" : "Cập nhật hồ sơ"}
              </button>
              <button type="button" className="first-play-tour-btn" onClick={() => setIsTourOpen(true)}>
                Xem hướng dẫn
              </button>
            </div>
          </div>
        </section>
      )}

      <div className="home-body">
        <main>
          <div className="section-header">
            <span className="section-title">📚 Quiz của tôi</span>
            <button className="section-action" onClick={() => router.push("/editor")}>
              + Tạo quiz mới
            </button>
          </div>

          {error && <div className="section-error">{error}</div>}

          <div className="quiz-grid">
            {isLoading ? (
              <div className="quiz-card">
                <div className="quiz-card-title">Đang tải danh sách quiz...</div>
                <div className="quiz-card-meta">
                  <span>Vui lòng chờ trong giây lát</span>
                </div>
              </div>
            ) : filteredMyQuizzes.length > 0 ? (
              paginatedMyQuizzes.map((quiz) => (
                <article className="quiz-card" key={quiz.id}>
                  <div className="quiz-card-title">{quiz.title}</div>
                  <div className="quiz-card-meta">
                    <div className="quiz-card-meta-info">
                      <span>{quiz.description || "Chưa có mô tả"}</span>
                    </div>
                    <div className="quiz-card-tags">
                      <span className={`tag ${quiz.is_public ? "public" : "private"}`}>
                        {quiz.is_public ? "Public" : "Private"}
                      </span>
                      {quiz.is_public && <span className="tag cyan">Có thể chia sẻ</span>}
                    </div>
                  </div>
                  <div className="quiz-card-footer">
                    <span className="quiz-card-note">{formatDate(quiz.created_at)}</span>
                    <div className="quiz-card-actions">
                      <button className="play-btn" onClick={() => router.push(`/create-room?quizId=${quiz.id}`)}>
                        ▶ Chơi ngay
                      </button>
                      <button
                        className="edit-btn"
                        onClick={() => router.push(`/editor/${quiz.id}`)}
                        title="Sửa quiz"
                      >
                        ✎ Sửa
                      </button>
                      <button
                        className="delete-btn"
                        onClick={async () => {
                          if (confirm("Bạn chắc chắn muốn xóa quiz này?")) {
                            try {
                              await quizService.deleteQuiz(quiz.id);
                              setQuizzes((prev) => prev.filter((q) => q.id !== quiz.id));
                            } catch (err) {
                              alert("Không xóa được quiz. Vui lòng thử lại.");
                            }
                          }
                        }}
                        title="Xóa quiz"
                      >
                        🗑 Xóa
                      </button>
                    </div>
                  </div>
                </article>
              ))
            ) : (
              <article className="quiz-card">
                <div className="quiz-card-title">
                  {appliedSearchQuery ? "Không có quiz phù hợp trong Quiz của tôi" : "Chưa có quiz nào"}
                </div>
                <div className="quiz-card-meta">
                  <span>
                    {appliedSearchQuery
                      ? "Thử từ khóa khác hoặc bấm Tìm với từ khóa mới."
                      : "Bạn chưa tạo quiz nào. Bắt đầu với một bộ câu hỏi mới nhé."}
                  </span>
                </div>
                <div className="quiz-card-footer">
                  <span className="quiz-card-note">Sẵn sàng tạo quiz đầu tiên</span>
                  <button className="play-btn compact" onClick={() => router.push("/editor")}>
                    + Tạo quiz
                  </button>
                </div>
              </article>
            )}

          </div>

          {!isLoading && filteredMyQuizzes.length > MY_QUIZZES_PER_PAGE && (
            <div className="quiz-pagination" aria-label="Phân trang Quiz của tôi">
              <div className="quiz-page-summary">
                Hiển thị {(myQuizPage - 1) * MY_QUIZZES_PER_PAGE + 1}-
                {Math.min(myQuizPage * MY_QUIZZES_PER_PAGE, filteredMyQuizzes.length)} / {filteredMyQuizzes.length}
              </div>
              <div className="quiz-page-controls">
                <button
                  className="quiz-page-btn"
                  type="button"
                  onClick={() => setMyQuizPage((page) => Math.max(1, page - 1))}
                  disabled={myQuizPage === 1}
                >
                  Trước
                </button>
                {myQuizPageItems.map((item) => {
                  if (typeof item === "string") {
                    return (
                      <span className="quiz-page-ellipsis" key={item}>
                        ...
                      </span>
                    );
                  }

                  const page = item;
                  return (
                    <button
                      className={`quiz-page-number${page === myQuizPage ? " active" : ""}`}
                      type="button"
                      key={page}
                      onClick={() => setMyQuizPage(page)}
                      aria-current={page === myQuizPage ? "page" : undefined}
                    >
                      {page}
                    </button>
                  );
                })}
                <button
                  className="quiz-page-btn"
                  type="button"
                  onClick={() => setMyQuizPage((page) => Math.min(myQuizTotalPages, page + 1))}
                  disabled={myQuizPage === myQuizTotalPages}
                >
                  Sau
                </button>
              </div>
            </div>
          )}

          <div className="section-header" style={{ marginTop: 28 }}>
            <span className="section-title">📖 Thư viện công khai</span>
            <button className="section-action">Xem tất cả →</button>
          </div>
          <div className="quiz-grid">
            {filteredPublicQuizzes.length > 0 ? (
              paginatedPublicQuizzes.map((quiz) => (
                <article className="quiz-card" key={quiz.id}>
                  <div className="quiz-card-title">{quiz.title}</div>
                  <div className="quiz-card-meta">
                    <div className="quiz-card-meta-info">
                      {/* <span>{getQuestionCount(quiz) || "Chưa rõ"} câu hỏi</span> */}
                      <span>{quiz.description || "Chưa có mô tả"}</span>
                    </div>
                    <div className="quiz-card-tags">
                      <span className="tag public">Public</span>
                      <span className="tag cyan">Có thể chia sẻ</span>
                    </div>
                  </div>
                  <div className="quiz-card-footer">
                    <span className="quiz-card-note">{formatDate(quiz.created_at)}</span>
                    <button className="play-btn" onClick={() => router.push(`/create-room?quizId=${quiz.id}`)}>
                      ▶ Dùng ngay
                    </button>
                  </div>
                </article>
              ))
            ) : (
              <article className="quiz-card">
                <div className="quiz-card-title">
                  {appliedSearchQuery ? "Không có quiz phù hợp trong Thư viện công khai" : "Chưa có quiz public"}
                </div>
                <div className="quiz-card-meta">
                  <span>
                    {appliedSearchQuery
                      ? "Thử từ khóa khác để tìm quiz công khai."
                      : "Hiện chưa có quiz công khai nào để khám phá."}
                  </span>
                </div>
                <div className="quiz-card-footer">
                  <span className="quiz-card-note">Hãy thử lại sau hoặc tự tạo quiz mới</span>
                </div>
              </article>
            )}
          </div>

          {filteredPublicQuizzes.length > MY_QUIZZES_PER_PAGE && (
            <div className="quiz-pagination" aria-label="Phân trang Thư viện công khai">
              <div className="quiz-page-summary">
                Hiển thị {(publicQuizPage - 1) * MY_QUIZZES_PER_PAGE + 1}-
                {Math.min(publicQuizPage * MY_QUIZZES_PER_PAGE, filteredPublicQuizzes.length)} / {filteredPublicQuizzes.length}
              </div>
              <div className="quiz-page-controls">
                <button
                  className="quiz-page-btn"
                  type="button"
                  onClick={() => setPublicQuizPage((page) => Math.max(1, page - 1))}
                  disabled={publicQuizPage === 1}
                >
                  Trước
                </button>
                {publicQuizPageItems.map((item) => {
                  if (typeof item === "string") {
                    return (
                      <span className="quiz-page-ellipsis" key={item}>
                        ...
                      </span>
                    );
                  }

                  const page = item;
                  return (
                    <button
                      className={`quiz-page-number${page === publicQuizPage ? " active" : ""}`}
                      type="button"
                      key={page}
                      onClick={() => setPublicQuizPage(page)}
                      aria-current={page === publicQuizPage ? "page" : undefined}
                    >
                      {page}
                    </button>
                  );
                })}
                <button
                  className="quiz-page-btn"
                  type="button"
                  onClick={() => setPublicQuizPage((page) => Math.min(publicQuizTotalPages, page + 1))}
                  disabled={publicQuizPage === publicQuizTotalPages}
                >
                  Sau
                </button>
              </div>
            </div>
          )}
        </main>

        <aside className="sidebar">
          <div className="sidebar-card">
            <div className="sidebar-card-title">🎯 Join phòng nhanh</div>
            <div className="sidebar-card-subtitle">Nhập mã phòng 6 ký tự:</div>
            <form className="join-input-row" onSubmit={handleJoinRoom}>
              <input
                id="join-room"
                className="join-input"
                data-tour="join-room"
                placeholder="......."
                maxLength={6}
                value={joinCode}
                onChange={(event) => setJoinCode(event.target.value.toUpperCase())}
              />
              <button className="btn-join" type="submit">
                Join
              </button>
            </form>
          </div>

          <div className="sidebar-card">
            <div className="sidebar-card-title">🕐 Hoạt động gần đây</div>
            <div className="activity-list">
              {recentActivities.map((activity) => (
                <div className="activity-item" key={activity.title}>
                  <div className={`activity-dot ${activity.dot}`} />
                  <div className="activity-text">
                    {activity.title}
                    <div className="activity-detail">{activity.detail}</div>
                  </div>
                  <div className="activity-time">{activity.time}</div>
                </div>
              ))}
            </div>
          </div>

          <div className="sidebar-card streak-card">
            <div className="streak-icon">🔥</div>
            <div className="streak-title">Streak 5 ngày!</div>
            <div className="streak-subtitle">Chơi thêm hôm nay để duy trì streak</div>
            <div className="streak-track">
              {Array.from({ length: 7 }).map((_, index) => (
                <div className={`streak-bar${index < 5 ? " active" : ""}`} key={index} />
              ))}
            </div>
          </div>
        </aside>
      </div>
      <GuidedTour
        steps={dashboardTourSteps}
        isOpen={isTourOpen}
        onClose={handleCloseTour}
        storageKey={DASHBOARD_TOUR_DONE_KEY}
      />
      <FriendsPanel
        isOpen={isFriendsPanelOpen}
        onClose={() => setIsFriendsPanelOpen(false)}
      />
    </div>
  );
}
