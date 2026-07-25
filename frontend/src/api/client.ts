// baseURL 吃環境變數 VITE_API_BASE，未設定時預設同源 /api（由 nginx 反向代理轉給後端）。
// 本機非 docker 開發可設 VITE_API_BASE=http://localhost:8000 直連後端、繞過 nginx；本機要測雲端才設 VITE_API_BASE=http://35.221.135.197/api。
export const BASE_URL = import.meta.env.VITE_API_BASE ?? '/api';

// 直接讀 localStorage 的登入 token（session.ts 存入時的 key），塞進 Authorization。
// 不 import auth/session 以避開循環相依；欄位對照 auth/session.ts 的 SESSION_KEY 與 AuthSession.token。
const SESSION_KEY = 'fulilian_auth_session';

function authHeader(): Record<string, string> {
  try {
    const raw = localStorage.getItem(SESSION_KEY);
    if (!raw) return {};
    const token = (JSON.parse(raw) as { token?: string }).token;
    return token ? { Authorization: `Bearer ${token}` } : {};
  } catch {
    return {};
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE_URL}${path}`, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...authHeader(), ...init?.headers },
  });
  if (!res.ok) {
    throw new Error(`API error ${res.status}: ${res.statusText}`);
  }
  // 容忍空回應（204 或空 body，ack/resolve 類端點常見）：直接 res.json() 會把成功誤判成解析失敗。
  const text = await res.text();
  return (text ? JSON.parse(text) : undefined) as T;
}

export const apiClient = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body?: unknown) => request<T>(path, { method: 'POST', body: JSON.stringify(body) }),
  put: <T>(path: string, body?: unknown) => request<T>(path, { method: 'PUT', body: JSON.stringify(body) }),
  patch: <T>(path: string, body?: unknown) => request<T>(path, { method: 'PATCH', body: JSON.stringify(body) }),
  delete: <T>(path: string) => request<T>(path, { method: 'DELETE' }),
};
