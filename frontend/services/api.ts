import axios, {
  AxiosInstance,
  AxiosError,
  InternalAxiosRequestConfig,
} from "axios";

// Fallback dev-only. Khi build production qua Docker, biến NEXT_PUBLIC_API_URL
// được truyền vào lúc build (xem docker-compose.yml args). Nếu app chạy production
// mà vẫn dùng localhost, nghĩa là build bị sai thiếu env var.
const API_URL =
  process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api/v1";

if (
  process.env.NODE_ENV === "production" &&
  API_URL.startsWith("http://localhost")
) {
  // Cảnh báo trong console — không crash app để tránh brick UI, nhưng dev thấy ngay.
  // eslint-disable-next-line no-console
  console.warn(
    "[apiClient] NEXT_PUBLIC_API_URL chưa được set khi build production. " +
      "App đang dùng fallback localhost — frontend sẽ không gọi được backend thật. " +
      "Kiểm tra docker-compose.yml args: NEXT_PUBLIC_API_URL.",
  );
}

// Create axios instance
const apiClient: AxiosInstance = axios.create({
  baseURL: API_URL,
  headers: {
    "Content-Type": "application/json",
  },
});

// Request interceptor to add token
apiClient.interceptors.request.use(
  (config: InternalAxiosRequestConfig) => {
    const token =
      typeof window !== "undefined"
        ? localStorage.getItem("access_token")
        : null;
    if (token) {
      config.headers.Authorization = `Bearer ${token}`;
    }
    return config;
  },
  (error: AxiosError) => Promise.reject(error),
);

// Response interceptor to handle token refresh
apiClient.interceptors.response.use(
  (response) => response,
  async (error: AxiosError) => {
    const originalRequest = error.config as InternalAxiosRequestConfig & {
      _retry?: boolean;
    };

    // Handle 401 (Unauthorized) - try to refresh token sai hoặc hết hạn
    if (
      error.response?.status === 401 &&
      !originalRequest._retry &&
      typeof window !== "undefined"
    ) {
      originalRequest._retry = true;

      try {
        const refreshToken = localStorage.getItem("refresh_token");
        if (refreshToken) {
          const response = await axios.post(`${API_URL}/auth/refresh`, {
            refresh_token: refreshToken,
          });

          const { access_token } = response.data;
          localStorage.setItem("access_token", access_token);

          // Retry original request
          originalRequest.headers.Authorization = `Bearer ${access_token}`;
          return apiClient(originalRequest);
        }
      } catch (refreshError) {
        // Refresh failed, redirect to login
        localStorage.removeItem("access_token");
        localStorage.removeItem("refresh_token");
        if (typeof window !== "undefined") {
          window.location.href = "/";
        }
        return Promise.reject(refreshError);
      }
    }

    return Promise.reject(error);
  },
);

export default apiClient;
