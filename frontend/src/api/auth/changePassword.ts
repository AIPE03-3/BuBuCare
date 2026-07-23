// 改自己的密碼（fulilian-backend PATCH /me/password）。
// 後端會先驗舊密碼：舊密碼錯回 400、新密碼不足 6 碼回 422。
// 比照 employeePassword 走原生 fetch（而非通用 apiClient），以便把狀態碼對應成友善中文訊息。
import { BASE_URL, NGROK_HEADERS } from '../client';
import { getStoredSession, setStoredSession } from './session';

export async function changeMyPassword(oldPassword: string, newPassword: string): Promise<void> {
  const token = getStoredSession()?.token;
  const res = await fetch(`${BASE_URL}/me/password`, {
    method: 'PATCH',
    headers: {
      'Content-Type': 'application/json',
      ...NGROK_HEADERS,
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify({ old_password: oldPassword, new_password: newPassword }),
  });
  if (!res.ok) {
    if (res.status === 400) throw new Error('目前密碼錯誤');
    if (res.status === 422) throw new Error('新密碼格式不符（至少 6 碼）');
    throw new Error(`密碼更新失敗（${res.status}）`);
  }

  // 改成功：後端已把 must_change_password 歸 False，前端 session 同步更新，
  // 讓主區塊守衛（RequirePasswordChanged）重新掛載時讀到最新旗標、不再攔截。
  const session = getStoredSession();
  if (session) {
    setStoredSession({ ...session, must_change_password: false });
  }
}
