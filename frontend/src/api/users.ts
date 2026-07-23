import { apiClient } from './client';
import type { ManagedUser } from '../types';

/**
 * 使用者管理走真後端（皆為 admin-only 端點，token 由 apiClient 自動帶）：
 *   GET   /users               → 名單（後端只回未停用帳號）
 *   PATCH /users/{id}          → 改姓名（後端只收 full_name）
 *   PATCH /users/{id}/password → 重設密碼（後端只收 new_password，最少 6 碼）
 * 後端無「查單筆」端點，getUserById 內部撈名單再挑出該筆。
 * 後端的 POST /register、DELETE /users/{id} 本輪不接（前端無對應 UI 入口）。
 */

// 後端 GET /users 每筆回傳格式（backend/users/router.py list_users）。
// 欄位對照 ManagedUser：employee_id→employee_code、full_name→name；
// id 後端是整數流水號，前端統一存字串（打路徑 /users/{id} 時後端會轉回 int）。
interface RawUser {
  id: number;
  employee_id: string;
  full_name: string;
  role: ManagedUser['role']; // 'staff' | 'admin'，兩邊同值
}

function parseRawUser(raw: RawUser): ManagedUser {
  return {
    id: String(raw.id),
    name: raw.full_name,
    employee_code: raw.employee_id,
    role: raw.role,
  };
}

export async function getUsers(): Promise<ManagedUser[]> {
  const raw = await apiClient.get<RawUser[]>('/users');
  return raw.map(parseRawUser);
}

// 後端無查單筆端點，改撈名單再挑出（demo 資料量小，無效能顧慮）；找不到回 null。
export async function getUserById(id: string): Promise<ManagedUser | null> {
  const all = await getUsers();
  return all.find((u) => u.id === id) ?? null;
}

// 改名與（選填）改密碼。後端拆成兩支端點，故內部視情況打 1~2 次請求，
// 呼叫端仍只呼叫本函式一次。密碼為 undefined／空字串視為不變更。
export async function updateUser(
  id: string,
  patch: { name?: string; password?: string },
): Promise<void> {
  if (patch.name !== undefined) {
    await apiClient.patch(`/users/${id}`, { full_name: patch.name });
  }
  if (patch.password) {
    await apiClient.patch(`/users/${id}/password`, { new_password: patch.password });
  }
}
