import { apiClient, BASE_URL } from './client';
import { getStoredSession } from './auth';
import type { ManagedUser } from '../types';

/**
 * 使用者管理走真後端（皆為 admin-only 端點，token 由 apiClient 自動帶）：
 *   GET   /users               → 名單（後端只回未停用帳號）
 *   PATCH /users/{id}          → 改姓名（後端只收 full_name）
 *   PATCH /users/{id}/role     → 改角色（後端只收 role，且擋「改自己」）
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

export interface CreateUserInput {
  employee_id: string;
  full_name: string;
  password: string;      // admin 給的臨時密碼（≥6 碼），新帳號後端自動設 must_change_password=true
  role: ManagedUser['role'];
  email?: string;        // 選填
}

// 新增使用者（admin-only POST /register）。員編／email 重複後端回 400，
// 走原生 fetch 讀後端回的 detail 訊息（中文，如「員編已存在」）直接呈現，
// 因通用 apiClient 只丟籠統的 status 錯誤、分不出是哪個欄位重複。
export async function createUser(input: CreateUserInput): Promise<void> {
  const token = getStoredSession()?.token;
  const res = await fetch(`${BASE_URL}/register`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify({
      employee_id: input.employee_id,
      full_name: input.full_name,
      password: input.password,
      role: input.role,
      email: input.email || null, // 空字串轉 null，後端才不會把空字串當 email 存
    }),
  });
  if (!res.ok) {
    const detail = await res
      .json()
      .then((d: { detail?: string }) => d?.detail)
      .catch(() => null);
    throw new Error(detail ?? `建立失敗（${res.status}）`);
  }
}

// 改角色（admin-only PATCH /users/{id}/role）。後端擋「改自己」回 400、找不到回 404；
// 走原生 fetch 讀後端 detail 訊息（如「不能改自己的角色」）直接呈現——
// 通用 apiClient 只丟籠統的 status 錯誤，會把這句話吃掉。
async function patchRole(id: string, role: ManagedUser['role']): Promise<void> {
  const token = getStoredSession()?.token;
  const res = await fetch(`${BASE_URL}/users/${id}/role`, {
    method: 'PATCH',
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify({ role }),
  });
  if (!res.ok) {
    const detail = await res
      .json()
      .then((d: { detail?: string }) => d?.detail)
      .catch(() => null);
    throw new Error(detail ?? `角色變更失敗（${res.status}）`);
  }
}

// 改名、改角色與（選填）改密碼。後端拆成三支端點，故內部視情況打 1~3 次請求，
// 呼叫端仍只呼叫本函式一次。密碼為 undefined／空字串視為不變更。
// 角色排在最前面：三者中只有它會被後端擋（改到自己回 400），失敗時姓名與密碼都還沒動，
// 不會留下「名字改了、角色沒改」的半套狀態。
export async function updateUser(
  id: string,
  patch: { name?: string; password?: string; role?: ManagedUser['role'] },
): Promise<void> {
  if (patch.role !== undefined) {
    await patchRole(id, patch.role);
  }
  if (patch.name !== undefined) {
    await apiClient.patch(`/users/${id}`, { full_name: patch.name });
  }
  if (patch.password) {
    await apiClient.patch(`/users/${id}/password`, { new_password: patch.password });
  }
}

// 停用使用者（軟刪除，admin-only DELETE /users/{id}）：後端把 is_active 設 false，
// 資料保留、員編不重用，該帳號從 GET /users 名單消失。
// 後端擋「停用自己」回 400、找不到回 404；走原生 fetch 讀後端 detail 訊息直接呈現。
export async function deleteUser(id: string): Promise<void> {
  const token = getStoredSession()?.token;
  const res = await fetch(`${BASE_URL}/users/${id}`, {
    method: 'DELETE',
    headers: {
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
  });
  if (!res.ok) {
    const detail = await res
      .json()
      .then((d: { detail?: string }) => d?.detail)
      .catch(() => null);
    throw new Error(detail ?? `停用失敗（${res.status}）`);
  }
}
