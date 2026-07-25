// 員工帳號＋密碼登入（fulilian-backend）。
// 後端 POST /login 是 OAuth2 form 格式（非 JSON），成功回 { access_token, token_type }，
// access_token 為 JWT，payload 內含 sub（員編）／full_name（真名）／role。
// display_name 直接取 JWT 的 full_name（後端登入時已包入），毋須額外打 /me。
import { BASE_URL, NGROK_HEADERS } from '../client';
import type { AuthProvider, AuthSession, Role } from '../../types';
import { setStoredSession, clearStoredSession } from './session';

interface LoginResponse {
  access_token: string;
  token_type: string;
  must_change_password: boolean; // 後端在回應最外層帶回，供強制改密碼流程判斷
}

interface JwtPayload {
  sub?: string;
  full_name?: string;
  role?: string;
  exp?: number;
}

// 解 JWT 中段 payload（base64url）。僅為取 role，不做簽章驗證（驗簽是後端的事）。
function decodeJwtPayload(token: string): JwtPayload {
  try {
    const base64url = token.split('.')[1];
    const base64 = base64url.replace(/-/g, '+').replace(/_/g, '/');
    const json = decodeURIComponent(
      atob(base64)
        .split('')
        .map((c) => '%' + c.charCodeAt(0).toString(16).padStart(2, '0'))
        .join(''),
    );
    return JSON.parse(json) as JwtPayload;
  } catch {
    return {};
  }
}

function normalizeRole(role: string | undefined): Role {
  return role === 'admin' ? 'admin' : 'staff';
}

export const employeePasswordProvider: AuthProvider = {
  async loginWithPassword(employeeId, password): Promise<AuthSession> {
    // OAuth2 password grant：application/x-www-form-urlencoded，欄位 username／password。
    const body = new URLSearchParams({ username: employeeId, password });
    const res = await fetch(`${BASE_URL}/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded', ...NGROK_HEADERS },
      body,
    });
    if (!res.ok) {
      throw new Error(res.status === 401 ? '帳號或密碼錯誤' : `登入失敗（${res.status}）`);
    }
    const data = (await res.json()) as LoginResponse;
    const payload = decodeJwtPayload(data.access_token);
    const session: AuthSession = {
      token: data.access_token,
      role: normalizeRole(payload.role),
      display_name: payload.full_name ?? payload.sub ?? employeeId,
      must_change_password: data.must_change_password ?? false,
    };
    setStoredSession(session);
    return session;
  },

  logout() {
    clearStoredSession();
  },
};

export default employeePasswordProvider;
