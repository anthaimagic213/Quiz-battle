"use client";

import React, { ChangeEvent, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { quizService, QuizSavePayload } from "@/services/quizService";
import { importQuestions } from "@/services/importService";
import { Quiz } from "@/types";

interface QuizEditorScreenProps {
  quizId?: string;
}

type QuestionType = "MCQ" | "TRUE_FALSE";
type SetupMode = "sample" | "blank" | "import";

interface EditorQuestion {
  id: string;
  text: string;
  type: QuestionType;
  timeLimit: number;
  points: number;
  options: string[];
  correctIndex: number;
}

const letters = ["A", "B", "C", "D", "E", "F", "G", "H"];
const maxChoiceOptions = 8;
const timeOptions = [10, 20, 30, 60,90, 120];
const defaultPoints = 100;
const minPoints = 50;
const maxPoints = 300;
const pointsOptions = Array.from(
  { length: (maxPoints - minPoints) / 10 + 1 },
  (_, index) => minPoints + index * 10
);

const initialQuestions: EditorQuestion[] = [
  {
    id: "q1",
    text: "Thủ đô của Nhật Bản là gì?",
    type: "MCQ",
    timeLimit: 30,
    points: 100,
    options: ["Osaka", "Tokyo", "Kyoto", "Nagoya"],
    correctIndex: 1,
  },
  {
    id: "q2",
    text: "Úc là một lục địa?",
    type: "TRUE_FALSE",
    timeLimit: 20,
    points: 100,
    options: ["Đúng", "Sai", "", ""],
    correctIndex: 0,
  },
  {
    id: "q3",
    text: "Sông dài nhất thế giới?",
    type: "MCQ",
    timeLimit: 30,
    points: 100,
    options: ["Amazon", "Nile", "Mekong", "Yangtze"],
    correctIndex: 1,
  },
];

const blankQuestion: EditorQuestion = {
  id: "q1",
  text: "",
  type: "MCQ",
  timeLimit: 30,
  points: 100,
  options: ["", "", "", ""],
  correctIndex: 0,
};

function normalizeOptions(type: QuestionType, options?: string[]) {
  if (type === "TRUE_FALSE") return ["Đúng", "Sai"];
  return options && options.length >= 2 ? options : ["", "", "", ""];
}

function getQuestionOptions(question: EditorQuestion) {
  return question.type === "TRUE_FALSE" ? question.options.slice(0, 2) : question.options;
}

function optionLetter(index: number) {
  return letters[index] || String.fromCharCode(65 + index);
}

const setupModeLabels: Record<SetupMode, string> = {
  sample: "Đã chọn: Dùng câu mẫu",
  blank: "Đã chọn: Tạo từ đầu",
  import: "Đã chọn: Import câu hỏi",
};

function ImportFormatGuide() {
  return (
    <section className="import-format-guide" aria-label="Hướng dẫn định dạng file import">
      <div className="import-guide-head">
        <div>
          <div className="import-guide-kicker">Định dạng file import</div>
          <h2>Chuẩn bị file theo mẫu này để hệ thống đọc đúng câu hỏi</h2>
        </div>
        <span className="import-guide-badge">Tô màu đáp án đúng</span>
      </div>

      <div className="import-guide-grid">
        <div className="import-guide-panel">
          <div className="import-guide-title">Excel / CSV</div>
          <p>Dòng đầu là tiêu đề cột. Mỗi dòng bên dưới là 1 câu hỏi. Với Excel, tô màu xanh ô đáp án đúng.</p>
          <div className="import-table-wrap" aria-label="Mẫu định dạng Excel">
            <table className="import-sample-table">
              <thead>
                <tr>
                  <th>Nội dung câu hỏi</th>
                  <th>Phương án A</th>
                  <th>Phương án B</th>
                  <th>Phương án C</th>
                  <th>Phương án D</th>
                  <th>Thời gian trả lời</th>
                  <th>Điểm số</th>
                </tr>
              </thead>
              <tbody>
                <tr>
                  <td>The man ______ next to me is my uncle.</td>
                  <td className="sample-correct">sitting</td>
                  <td>sat</td>
                  <td>to sit</td>
                  <td>was sitting</td>
                  <td>20</td>
                  <td>1000</td>
                </tr>
                <tr>
                  <td>This is the best movie ______ this year.</td>
                  <td>to see</td>
                  <td>seeing</td>
                  <td className="sample-correct">seen</td>
                  <td>saw</td>
                  <td>20</td>
                  <td>1000</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>

        <div className="import-guide-panel">
          <div className="import-guide-title">Word / Google Docs</div>
          <p>Mỗi câu gồm 1 dòng câu hỏi và 4 dòng đáp án ngay bên dưới. Tô màu vàng dòng đáp án đúng, rồi lưu/tải xuống dạng .docx.</p>
          <div className="import-doc-sample" aria-label="Mẫu định dạng Word hoặc Google Docs">
            <strong>Kết quả của lệnh print(type(1/2)) trong Python 3 là gì?</strong>
            <span>{"<class 'int'>"}</span>
            <span className="sample-highlight">{"<class 'float'>"}</span>
            <span>{"<class 'double'>"}</span>
            <span>{"<class 'number'>"}</span>
            <strong>Hàm nào được dùng để lấy độ dài của một danh sách?</strong>
            <span>size()</span>
            <span>length()</span>
            <span>count()</span>
            <span className="sample-highlight">len()</span>
          </div>
        </div>
      </div>
    </section>
  );
}

export default function QuizEditorScreen({ quizId }: QuizEditorScreenProps) {
  const router = useRouter();
  const quizTitleInputRef = useRef<HTMLInputElement>(null);
  const [quizTitle, setQuizTitle] = useState("");
  const [visibility, setVisibility] = useState("private");
  const [questions, setQuestions] = useState<EditorQuestion[]>(initialQuestions);
  const [activeIndex, setActiveIndex] = useState(0);
  const [isSaving, setIsSaving] = useState(false);
  const [isLoading, setIsLoading] = useState(quizId ? true : false);
  const [showInitialSetup, setShowInitialSetup] = useState(!quizId);
  const [showSetup, setShowSetup] = useState(false);
  const [selectedSetupMode, setSelectedSetupMode] = useState<SetupMode | null>("sample");
  const [importFileName, setImportFileName] = useState("");
  const [importFile, setImportFile] = useState<File | null>(null);
  const [isImporting, setIsImporting] = useState(false);
  const [isImportGuideOpen, setIsImportGuideOpen] = useState(false);

  useEffect(() => {
    if (!quizId) return;

    const loadQuiz = async () => {
      try {
        setIsLoading(true);
        const quiz = await quizService.getQuizById(quizId);
        setQuizTitle(quiz.title);
        setVisibility(quiz.is_public ? "public" : "private");

                if (quiz.questions && quiz.questions.length > 0) {
          const convertedQuestions = quiz.questions.map((q) => {
            const options = q.answer_options?.map((opt) => opt.content) || ["", "", "", ""];
            const correctIndex = q.answer_options?.findIndex((opt) => opt.is_correct) ?? 0;
            const rawPoints = q.points ?? defaultPoints;
            const clampedPoints = pointsOptions.includes(rawPoints)
              ? rawPoints
              : pointsOptions.reduce((closest, current) =>
                  Math.abs(current - rawPoints) < Math.abs(closest - rawPoints) ? current : closest
                );
            return {
              id: q.id,
              text: q.content,
              type: q.question_type as QuestionType,
              timeLimit: q.time_limit || 30,
              points: clampedPoints,
              options,
              correctIndex: correctIndex >= 0 ? correctIndex : 0,
            };
          });
          setQuestions(convertedQuestions);
          setActiveIndex(0);
        }
      } catch (err) {
        console.error("Failed to load quiz:", err);
        alert("Không tải được quiz. Vui lòng thử lại.");
      } finally {
        setIsLoading(false);
      }
    };

    loadQuiz();
  }, [quizId]);

  const activeQuestion = questions[activeIndex] ?? questions[0];
  const visibleOptions = useMemo(
    () => getQuestionOptions(activeQuestion),
    [activeQuestion]
  );

  const updateActiveQuestion = (patch: Partial<EditorQuestion>) => {
    setQuestions((current) =>
      current.map((question, index) => (index === activeIndex ? { ...question, ...patch } : question))
    );
  };

  const handleTypeChange = (type: QuestionType) => {
    updateActiveQuestion({
      type,
      options: normalizeOptions(type, activeQuestion.options),
      correctIndex: 0,
    });
  };

  const handleOptionChange = (optionIndex: number, event: ChangeEvent<HTMLInputElement>) => {
    const nextOptions = [...activeQuestion.options];
    nextOptions[optionIndex] = event.target.value;
    updateActiveQuestion({ options: nextOptions });
  };

  const handleAddOption = () => {
    if (activeQuestion.type !== "MCQ" || activeQuestion.options.length >= maxChoiceOptions) return;
    updateActiveQuestion({ options: [...activeQuestion.options, ""] });
  };

  const handleRemoveOption = (optionIndex: number) => {
    if (activeQuestion.type !== "MCQ" || activeQuestion.options.length <= 2) return;

    const nextOptions = activeQuestion.options.filter((_, index) => index !== optionIndex);
    const nextCorrectIndex =
      activeQuestion.correctIndex === optionIndex
        ? 0
        : activeQuestion.correctIndex > optionIndex
          ? activeQuestion.correctIndex - 1
          : activeQuestion.correctIndex;

    updateActiveQuestion({
      options: nextOptions,
      correctIndex: Math.min(nextCorrectIndex, nextOptions.length - 1),
    });
  };

    const handleAddQuestion = () => {
    const newQuestion: EditorQuestion = {
      id: `q${Date.now()}`,
      text: "Câu hỏi mới...",
      type: "MCQ",
      timeLimit: 30,
      points: defaultPoints,
      options: ["", "", "", ""],
      correctIndex: 0,
    };

    setQuestions((current) => [...current, newQuestion]);
    setActiveIndex(questions.length);
  };

  const openSetupPanel = () => {
    setSelectedSetupMode(null);
    setImportFileName("");
    setIsImportGuideOpen(false);
    setShowSetup(true);
  };

  const closeSetupPanel = () => {
    setShowSetup(false);
  };

  const startWithMode = (mode: SetupMode) => {
    setSelectedSetupMode(mode);
    if (mode !== "import") {
      setIsImportGuideOpen(false);
    }

    if (mode === "sample") {
      setQuestions(initialQuestions);
      setActiveIndex(0);
      setShowSetup(false);
      return;
    }

    if (mode === "blank") {
      setQuestions([{ ...blankQuestion, id: `q${Date.now()}` }]);
      setActiveIndex(0);
      setShowSetup(false);
      return;
    }

    if (mode === "import" && importFile) {
      handleImportFile();
    }
  };

  const toggleImportGuide = (event: React.MouseEvent<HTMLButtonElement>) => {
    event.stopPropagation();
    setSelectedSetupMode("import");
    setIsImportGuideOpen((current) => !current);
  };

  const continueFromInitialSetup = async () => {
    if (!quizTitle.trim()) {
      alert("Vui lòng nhập tên quiz trước khi tiếp tục.");
      quizTitleInputRef.current?.focus();
      return;
    }

    if (!selectedSetupMode) {
      alert("Vui lòng chọn cách thêm câu hỏi.");
      return;
    }

    if (selectedSetupMode === "sample") {
      setQuestions(initialQuestions);
      setActiveIndex(0);
      setShowInitialSetup(false);
      return;
    }

    if (selectedSetupMode === "blank") {
      setQuestions([{ ...blankQuestion, id: `q${Date.now()}` }]);
      setActiveIndex(0);
      setShowInitialSetup(false);
      return;
    }

    if (selectedSetupMode === "import") {
      if (!importFile) {
        alert("Vui lòng chọn file câu hỏi trước khi tiếp tục.");
        return;
      }

      const imported = await handleImportFile();
      if (imported) {
        setShowInitialSetup(false);
      }
    }
  };

  const handleImportFileChange = (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (file) {
      setImportFile(file);
      setImportFileName(file.name);
    }
  };

  const handleImportFile = async () => {
    if (!importFile) {
      alert("Vui lòng chọn file trước");
      return false;
    }

    setIsImporting(true);
    try {
            const importedQuestions = await importQuestions(importFile);

      // Convert imported questions to EditorQuestion format
      const convertedQuestions = importedQuestions.map((q) => {
        const rawPoints = q.points ?? defaultPoints;
        const safePoints = pointsOptions.includes(rawPoints)
          ? rawPoints
          : defaultPoints;
        return {
          id: q.id || `q${Date.now()}`,
          text: q.text,
          type: q.type,
          timeLimit: q.timeLimit || 30,
          points: safePoints,
          options: q.options,
          correctIndex: q.correctIndex || 0,
        };
      });

      setQuestions(convertedQuestions);
      setActiveIndex(0);
      setShowSetup(false);
      alert(`✅ Đã import thành công ${convertedQuestions.length} câu hỏi!`);
      return true;
    } catch (error) {
      console.error("Import error:", error);
      alert(`❌ Lỗi import file: ${error instanceof Error ? error.message : "Unknown error"}`);
      return false;
    } finally {
      setIsImporting(false);
    }
  };

  const handleDeleteQuestion = () => {
        if (questions.length === 1) {
      updateActiveQuestion({
        text: "",
        type: "MCQ",
        timeLimit: 30,
        points: defaultPoints,
        options: ["", "", "", ""],
        correctIndex: 0,
      });
      return;
    }

    setQuestions((current) => current.filter((_, index) => index !== activeIndex));
    setActiveIndex((current) => Math.max(0, current - 1));
  };

  const handleMoveUp = () => {
    if (activeIndex === 0) return;

    setQuestions((current) => {
      const next = [...current];
      const currentQuestion = next[activeIndex];
      next[activeIndex] = next[activeIndex - 1];
      next[activeIndex - 1] = currentQuestion;
      return next;
    });
    setActiveIndex((current) => current - 1);
  };

  const handleMoveDown = () => {
    if (activeIndex >= questions.length - 1) return;

    setQuestions((current) => {
      const next = [...current];
      const currentQuestion = next[activeIndex];
      next[activeIndex] = next[activeIndex + 1];
      next[activeIndex + 1] = currentQuestion;
      return next;
    });
    setActiveIndex((current) => current + 1);
  };

  const validateQuizTitle = () => {
    if (quizTitle.trim()) return true;

    alert("Vui lòng nhập tên quiz trước khi lưu.");
    quizTitleInputRef.current?.focus();
    return false;
  };

  const handleSaveAndPlay = async () => {
    if (isSaving) return;
    if (!validateQuizTitle()) return;

    setIsSaving(true);
    try {
      const payload: QuizSavePayload = {
        title: quizTitle.trim(),
        description: `Có ${questions.length} câu hỏi`,
        is_public: visibility === "public",
        questions: questions.map((q) => ({
          content: q.text,
          question_type: q.type,
          time_limit: q.timeLimit,
          points: q.points,
          order_index: questions.indexOf(q),
          answer_options: getQuestionOptions(q).map((opt, idx) => ({
            content: opt,
            is_correct: idx === q.correctIndex,
          })),
        })),
      };

      const savedQuiz = quizId
        ? await quizService.updateQuiz(quizId, payload)
        : await quizService.createQuiz(payload);

      // Chuyển sang create-room với quiz ID
      router.push(`/create-room?quizId=${savedQuiz.id}`);
    } catch (error) {
      console.error("Failed to save quiz:", error);
      alert("Lưu quiz thất bại. Vui lòng thử lại.");
    } finally {
      setIsSaving(false);
    }
  };

  const handleSaveQuiz = async () => {
    if (isSaving) return;
    if (!validateQuizTitle()) return;

    setIsSaving(true);
    try {
      const isCreatingNewQuiz = !quizId;
      const payload: QuizSavePayload = {
        title: quizTitle.trim(),
        description: `Có ${questions.length} câu hỏi`,
        is_public: visibility === "public",
        questions: questions.map((q) => ({
          content: q.text,
          question_type: q.type,
          time_limit: q.timeLimit,
          points: q.points,
          order_index: questions.indexOf(q),
          answer_options: getQuestionOptions(q).map((opt, idx) => ({
            content: opt,
            is_correct: idx === q.correctIndex,
          })),
        })),
      };

      const savedQuiz = quizId
        ? await quizService.updateQuiz(quizId, payload)
        : await quizService.createQuiz(payload);

      if (isCreatingNewQuiz) {
        alert(`Đã tạo quiz "${savedQuiz.title}" thành công!`);
        router.push("/dashboard");
        return;
      }

      alert(`Đã sửa quiz "${savedQuiz.title}" thành công!`);
      router.push(`/editor/${savedQuiz.id}`);
    } catch (error) {
      console.error("Failed to save quiz:", error);
      alert("Lưu quiz thất bại. Vui lòng thử lại.");
    } finally {
      setIsSaving(false);
    }
  };

  if (isLoading) {
    return (
      <div className="editor-wrap">
        <div style={{ padding: "32px", textAlign: "center" }}>
          <div style={{ fontSize: "18px", color: "var(--muted)" }}>Đang tải quiz...</div>
        </div>
      </div>
    );
  }

  if (showInitialSetup) {
    return (
      <div className="editor-wrap setup-mode">
        <main className="editor-main setup-main">
          <div className="setup-panel quiz-start-panel">
            <div className="setup-kicker">Tạo Quiz</div>
            <h1 className="setup-title">Thiết lập quiz trước khi vào editor</h1>
            <p className="setup-sub">Nhập thông tin cơ bản và chọn cách bạn muốn bắt đầu thêm câu hỏi.</p>

            <div className="quiz-start-form">
              <label className="quiz-start-field">
                <span>Tên quiz</span>
                <input
                  ref={quizTitleInputRef}
                  className="form-input"
                  placeholder="Nhập tên quiz, ví dụ: Hackathon Quiz 2026"
                  required
                  value={quizTitle}
                  onChange={(event) => setQuizTitle(event.target.value)}
                />
              </label>

              <div className="quiz-start-field">
                <span>Chế độ hiển thị</span>
                <div className="visibility-segment">
                  <button
                    className={`visibility-choice${visibility === "private" ? " active" : ""}`}
                    onClick={() => setVisibility("private")}
                    type="button"
                  >
                    Private
                  </button>
                  <button
                    className={`visibility-choice${visibility === "public" ? " active" : ""}`}
                    onClick={() => setVisibility("public")}
                    type="button"
                  >
                    Public
                  </button>
                </div>
              </div>
            </div>

            <div className="setup-option-grid quiz-start-options">
              <button
                className={`setup-option-card${selectedSetupMode === "sample" ? " active" : ""}`}
                onClick={() => setSelectedSetupMode("sample")}
                type="button"
              >
                <div className="setup-option-icon">✨</div>
                <div className="setup-option-title">Dùng câu mẫu</div>
                <div className="setup-option-desc">Vào editor với 3 câu demo để chỉnh sửa nhanh.</div>
              </button>

              <button
                className={`setup-option-card${selectedSetupMode === "blank" ? " active" : ""}`}
                onClick={() => setSelectedSetupMode("blank")}
                type="button"
              >
                <div className="setup-option-icon">🧩</div>
                <div className="setup-option-title">Tạo từ đầu</div>
                <div className="setup-option-desc">Bắt đầu bằng một câu hỏi trống.</div>
              </button>

              <div
                className={`setup-option-card import-card${selectedSetupMode === "import" ? " active" : ""}`}
                onClick={() => setSelectedSetupMode("import")}
              >
                <div className="setup-option-icon">📥</div>
                <div className="setup-option-title">Import câu hỏi</div>
                <div className="setup-option-desc">Chọn file Excel, CSV hoặc Word để đưa câu hỏi vào editor.</div>

                <label className="import-file-picker" onClick={(event) => event.stopPropagation()}>
                  Chọn file (.xlsx, .xls, .csv, .docx)
                  <input
                    type="file"
                    accept=".xlsx,.xls,.csv,.docx"
                    onChange={(event) => {
                      setSelectedSetupMode("import");
                      handleImportFileChange(event);
                    }}
                  />
                </label>

                <div className="import-file-name">
                  {importFileName ? `Đã chọn file: ${importFileName}` : "Chưa chọn file"}
                </div>

                <button className="import-guide-toggle" type="button" onClick={toggleImportGuide}>
                  {isImportGuideOpen ? "Ẩn hướng dẫn" : "Chú ý: xem định dạng file"}
                </button>
              </div>
            </div>

            {selectedSetupMode === "import" && isImportGuideOpen ? <ImportFormatGuide /> : null}

            {selectedSetupMode ? (
              <div className="setup-selected-note">{setupModeLabels[selectedSetupMode]}</div>
            ) : null}

            <div className="setup-actions">
              <button className="setup-back-btn" onClick={() => router.push("/dashboard")} type="button">
                Hủy
              </button>
              <button className="setup-continue-btn" onClick={continueFromInitialSetup} disabled={isImporting} type="button">
                {isImporting ? "Đang xử lý..." : "Tiếp tục"}
              </button>
            </div>
          </div>
        </main>
      </div>
    );
  }

  if (showSetup) {
    return (
      <div className="editor-wrap setup-mode">
        <main className="editor-main setup-main">
          <div className="setup-panel">
            <div className="setup-kicker">Tạo Quiz</div>
            <h1 className="setup-title">Bạn muốn thêm câu hỏi theo cách nào cho bộ Quiz?</h1>
            <p className="setup-sub">Chọn 1 trong 3 cách dưới đây.</p>

            <div className="setup-option-grid">
              <button
                className={`setup-option-card${selectedSetupMode === "sample" ? " active" : ""}`}
                onClick={() => startWithMode("sample")}
              >
                <div className="setup-option-icon">✨</div>
                <div className="setup-option-title">Dùng 3 câu mẫu</div>
                <div className="setup-option-desc">Giữ nguyên 3 câu demo như hiện tại để chỉnh sửa nhanh.</div>
              </button>

              <button
                className={`setup-option-card${selectedSetupMode === "blank" ? " active" : ""}`}
                onClick={() => startWithMode("blank")}
              >
                <div className="setup-option-icon">🧩</div>
                <div className="setup-option-title">Bắt đầu trống</div>
                <div className="setup-option-desc">Không có câu mẫu nào, tạo câu hỏi từ đầu.</div>
              </button>

              <div
                className={`setup-option-card import-card${selectedSetupMode === "import" ? " active" : ""}`}
                onClick={() => setSelectedSetupMode("import")}
              >
                <div className="setup-option-icon">📥</div>
                <div className="setup-option-title">Import từ file</div>
                <div className="setup-option-desc">
                  Hỗ trợ giao diện nhập từ Excel hoặc Word. Bước parser sẽ làm tiếp sau.
                </div>

                <label className="import-file-picker" onClick={(event) => event.stopPropagation()}>
                  Chọn file (.xlsx, .xls, .csv, .docx)
                  <input
                    type="file"
                    accept=".xlsx,.xls,.csv,.docx"
                    onChange={(event) => {
                      setSelectedSetupMode("import");
                      handleImportFileChange(event);
                    }}
                  />
                </label>

                <div className="import-file-name">
                  {importFileName ? `Đã chọn file: ${importFileName}` : "Chưa chọn file"}
                </div>

                <div className="import-preview-note">
                  Hỗ trợ: Excel (.xlsx, .xls), CSV, Word (.docx). Hệ thống sẽ tự phát hiện đáp án đúng từ phần bôi vàng.
                </div>

                <button 
                  className="import-continue-btn" 
                  onClick={(event) => {
                    event.stopPropagation();
                    handleImportFile();
                  }}
                  disabled={!importFile || isImporting}
                  type="button"
                >
                  {isImporting ? "Đang xử lý..." : "Tiếp tục với file"}
                </button>

                <button className="import-guide-toggle" type="button" onClick={toggleImportGuide}>
                  {isImportGuideOpen ? "Ẩn hướng dẫn" : "Chú ý: xem định dạng file"}
                </button>
              </div>
            </div>

            {selectedSetupMode === "import" && isImportGuideOpen ? <ImportFormatGuide /> : null}

            <div className="setup-actions">
              <button className="setup-back-btn" onClick={closeSetupPanel} type="button">
                Quay lại editor
              </button>
            </div>
          </div>
        </main>
      </div>
    );
  }

  return (
    <div className="editor-wrap">
      <aside className="editor-sidebar">
        <div className="editor-quiz-box">
          <input
            ref={quizTitleInputRef}
            className="form-input"
            placeholder="Nhập tên quiz..."
            required
            value={quizTitle}
            onChange={(event) => setQuizTitle(event.target.value)}
            style={{ fontFamily: "Syne, sans-serif", fontWeight: 700 }}
          />
          <div className="editor-quiz-meta">
            <select className="editor-select" value={visibility} onChange={(event) => setVisibility(event.target.value)}>
              <option value="private">🔒 Private</option>
              <option value="public">🌍 Public</option>
            </select>
          </div>
          <button className="editor-setup-btn" onClick={openSetupPanel} type="button">
            + Chọn cách thêm câu hỏi
          </button>
        </div>

        <div className="es-title">Câu hỏi ({questions.length})</div>
        {questions.map((question, index) => (
          <button
            className={`es-q-item${index === activeIndex ? " active" : ""}`}
            key={question.id}
            onClick={() => setActiveIndex(index)}
          >
            <div className="es-q-num">{index + 1}</div>
            <div className="es-q-text">{question.text || "Câu hỏi chưa có nội dung"}</div>
          </button>
        ))}
        <button className="es-add" onClick={handleAddQuestion}>
          + Thêm câu hỏi
        </button>

        <div className="editor-sidebar-actions">
          <button className="btn-save" style={{ width: "100%" }} onClick={handleSaveQuiz} disabled={isSaving}>
            {isSaving ? "Đang lưu..." : quizId ? "Cập nhật sửa" : "💾 Lưu"}
          </button>
          <button className="btn-publish" style={{ width: "100%" }} onClick={handleSaveAndPlay} disabled={isSaving}>
            🚀 Lưu & Chơi
          </button>
        </div>
      </aside>

      <main className="editor-main">
        <div className="editor-main-header">
          <h1 className="em-title">
            {quizId ? "Chỉnh sửa quiz" : "Câu hỏi"} {activeIndex + 1} / {questions.length}
          </h1>
          {selectedSetupMode && !quizId ? <div className="editor-mode-badge">Mode: {selectedSetupMode}</div> : null}
          <div className="editor-header-actions">
            <button className="editor-icon-btn" onClick={handleDeleteQuestion}>
              🗑 Xóa
            </button>
            <button className="editor-icon-btn strong" onClick={handleMoveUp}>
              ⬆ Lên
            </button>
            <button className="editor-icon-btn strong" onClick={handleMoveDown}>
              ⬇ Xuống
            </button>
          </div>
        </div>

        <section className="question-editor">
          <div className="qe-top">
            <div className="qe-type-toggle">
              <button
                className={`qe-type-btn${activeQuestion.type === "MCQ" ? " active" : ""}`}
                onClick={() => handleTypeChange("MCQ")}
              >
                Chọn câu
              </button>
              <button
                className={`qe-type-btn${activeQuestion.type === "TRUE_FALSE" ? " active" : ""}`}
                onClick={() => handleTypeChange("TRUE_FALSE")}
              >
                Đúng / Sai
              </button>
            </div>
            <div className="qe-time">⏱ Thời gian:</div>
            <div className="time-select">
              {timeOptions.map((time) => (
                <button
                  className={`time-chip${activeQuestion.timeLimit === time ? " active" : ""}`}
                  key={time}
                  onClick={() => updateActiveQuestion({ timeLimit: time })}
                >
                  {time}s
                </button>
              ))}
            </div>
                        <div className="qe-score-wrap">
              <div className="qe-score-label">🏆 Điểm:</div>
              <div className="points-select" role="group" aria-label="Chọn điểm số cho câu hỏi">
                {pointsOptions.map((points) => (
                  <button
                    className={`points-chip${activeQuestion.points === points ? " active" : ""}`}
                    key={points}
                    onClick={() => updateActiveQuestion({ points })}
                    type="button"
                  >
                    {points}
                  </button>
                ))}
              </div>
            </div>
          </div>

          <textarea
            className="qe-textarea"
            rows={3}
            value={activeQuestion.text}
            onChange={(event) => updateActiveQuestion({ text: event.target.value })}
          />

          <div className="answers-toolbar">
            <div className="answers-label">Đáp án (chọn đáp án đúng ✓):</div>
            {activeQuestion.type === "MCQ" ? (
              <button
                className="add-option-btn"
                onClick={handleAddOption}
                disabled={activeQuestion.options.length >= maxChoiceOptions}
                type="button"
              >
                + Thêm đáp án
              </button>
            ) : null}
          </div>
                    <div className="options-editor">
            {visibleOptions.map((option, index) => (
              <div
                className={`option-editor${activeQuestion.correctIndex === index ? " correct" : ""}`}
                key={optionLetter(index)}
                onClick={(event) => {
                  // Không chọn đáp án khi click vào input/button bên trong
                  const target = event.target as HTMLElement;
                  if (target.closest("input, button")) return;
                  updateActiveQuestion({ correctIndex: index });
                }}
                onKeyDown={(event) => {
                  // Bỏ qua nếu user đang gõ vào input bên trong (để gõ khoảng trắng bình thường)
                  const target = event.target as HTMLElement;
                  if (target.tagName === "INPUT" || target.tagName === "TEXTAREA") return;

                  if (event.key === "Enter" || event.key === " ") {
                    event.preventDefault();
                    updateActiveQuestion({ correctIndex: index });
                  }
                }}
                role="button"
                tabIndex={0}
              >
                <div className="opt-letter">{optionLetter(index)}</div>
                <input
                  className="opt-input"
                  value={option}
                  onChange={(event) => handleOptionChange(index, event)}
                  onKeyDown={(event) => event.stopPropagation()}
                  readOnly={activeQuestion.type === "TRUE_FALSE"}
                  placeholder={`Đáp án ${optionLetter(index)}`}
                />
                <button
                  className={`opt-correct-btn${activeQuestion.correctIndex === index ? " checked" : ""}`}
                  onClick={(event) => {
                    event.stopPropagation();
                    updateActiveQuestion({ correctIndex: index });
                  }}
                  aria-label={`Chọn đáp án ${optionLetter(index)} là đúng`}
                  type="button"
                >
                  {activeQuestion.correctIndex === index ? "✓" : ""}
                </button>
                {activeQuestion.type === "MCQ" && activeQuestion.options.length > 2 ? (
                  <button
                    className="opt-remove-btn"
                    onClick={(event) => {
                      event.stopPropagation();
                      handleRemoveOption(index);
                    }}
                    aria-label={`Xóa đáp án ${optionLetter(index)}`}
                    type="button"
                  >
                    ×
                  </button>
                ) : null}
              </div>
            ))}
          </div>
        </section>

        <section className="editor-preview">
          <div className="editor-preview-title">Preview câu hỏi</div>
          <div className="preview-question">{activeQuestion.text}</div>
          <div className="preview-options">
            {visibleOptions.map((option, index) => {
              const isCorrect = activeQuestion.correctIndex === index;
              const isFirstWrong = index === 0 && !isCorrect;

              return (
                <div
                  className={`preview-option${isCorrect ? " correct" : ""}${isFirstWrong ? " wrong" : ""}`}
                  key={optionLetter(index)}
                >
                  <span className="preview-letter">{optionLetter(index)}</span>
                  <span className="preview-option-text">
                    {option || `Đáp án ${optionLetter(index)}`} {isCorrect ? "✓" : ""}
                  </span>
                </div>
              );
            })}
          </div>
        </section>
      </main>
    </div>
  );
}
