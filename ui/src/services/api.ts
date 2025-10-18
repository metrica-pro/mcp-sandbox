import axios from "axios";

// Use environment variable if available, otherwise use relative path for production
const API_URL = import.meta.env.VITE_API_URL || window.location.origin;

const api = axios.create({
  baseURL: API_URL,
  headers: {
    "Content-Type": "application/json",
  },
});

// Add a request interceptor to include the auth token in all requests
api.interceptors.request.use(
  (config) => {
    const token = localStorage.getItem("token");
    if (token) {
      config.headers["Authorization"] = `Bearer ${token}`;
    }
    return config;
  },
  (error) => Promise.reject(error)
);

export interface User {
  id: string;
  username: string;
  email: string;
  created_at: string;
  is_active: boolean;
  api_key?: string;
}

export interface Sandbox {
  id: string;
  name: string;
  user_id: string;
  created_at: string;
}

export interface LoginCredentials {
  username: string;
  password: string;
}

export interface RegisterCredentials {
  username: string;
  email: string;
  password: string;
}

// Auth API
export const authApi = {
  login: async (credentials: LoginCredentials) => {
    const formData = new URLSearchParams();
    formData.append("username", credentials.username);
    formData.append("password", credentials.password);

    const response = await api.post("/api/token", formData, {
      headers: {
        "Content-Type": "application/x-www-form-urlencoded",
      },
    });
    return response.data;
  },

  register: async (credentials: RegisterCredentials) => {
    const response = await api.post("/api/register", credentials);
    return response.data;
  },

  getCurrentUser: async () => {
    const response = await api.get("/api/users/me");
    return response.data as User;
  },

  getApiKey: async () => {
    const response = await api.get("/api/users/me/api-key");
    return response.data;
  },

  regenerateApiKey: async () => {
    const response = await api.post("/api/users/me/api-key/regenerate");
    return response.data;
  },
};

// Sandbox API
export const sandboxApi = {
  getUserSandboxes: async () => {
    const response = await api.get("/api/users/me/sandboxes");
    return response.data.sandboxes as Sandbox[];
  },

  createSandbox: async (name?: string) => {
    const response = await api.post("/api/users/me/sandboxes", { name });
    return response.data;
  },

  deleteSandbox: async (sandboxId: string) => {
    const response = await api.delete(`/api/users/me/sandboxes/${sandboxId}`);
    return response.data;
  },

  getSandboxDetails: async (sandboxId: string) => {
    const response = await api.get(`/api/users/me/sandboxes/${sandboxId}`);
    return response.data;
  },

  getSseUrl: (apiKey: string) => {
    return `${API_URL}/sse?api_key=${apiKey}`;
  },
};

export default api;
