// 後端位址吃環境變數 VITE_API_BASE，未設定時退回同源 /api。
//
// ── 三種情境該用哪個值、寫在哪個檔 ─────────────────────────────
// | 情境                          | VITE_API_BASE              | 寫在            |
// | 本機 npm run dev（無 nginx）  | http://127.0.0.1:8000      | .env.local      |
// | docker compose（有 nginx）    | /api                       | .env.production |
// | 本機 dev 但要打雲端後端        | http://35.221.135.197/api  | .env.local 暫改 |
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
