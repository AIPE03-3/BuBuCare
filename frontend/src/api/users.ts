import type { ManagedUser } from '../types';
import usersMock from './mock/users.json';

// 管理使用者：後端目前無 /users 端點，demo 以 localStorage 承載（首次由假資料 seed），
// 讓改名／改密碼在本機持久呈現。未來接後端時只需改寫本檔各函式實作，呼叫端不動。
const USERS_KEY = 'fulilian_users';

// 內部儲存型別：比對外的 ManagedUser 多一個 demo 密碼欄（write-only，不對外曝光）。
// ⚠ demo 才把密碼存 localStorage；正式後端一律雜湊、前端不得留存明文。
interface StoredUser extends ManagedUser {
  password?: string;
}

function seedUsers(): StoredUser[] {
  return (usersMock as ManagedUser[]).map((u) => ({ ...u }));
}

function readAll(): StoredUser[] {
  const raw = localStorage.getItem(USERS_KEY);
  if (!raw) {
    const seeded = seedUsers();
    localStorage.setItem(USERS_KEY, JSON.stringify(seeded));
    return seeded;
  }
  try {
    return JSON.parse(raw) as StoredUser[];
  } catch {
    return seedUsers();
  }
}

function writeAll(list: StoredUser[]): void {
  localStorage.setItem(USERS_KEY, JSON.stringify(list));
}

// 對外一律只吐 ManagedUser（不含密碼），避免密碼外流到畫面。
function toManagedUser(u: StoredUser): ManagedUser {
  return { id: u.id, name: u.name, employee_code: u.employee_code, role: u.role };
}

export async function getUsers(): Promise<ManagedUser[]> {
  return readAll().map(toManagedUser);
}

export async function getUserById(id: string): Promise<ManagedUser | null> {
  const found = readAll().find((u) => u.id === id);
  return found ? toManagedUser(found) : null;
}

// 更新名稱與／或密碼；欄位未提供者維持原值。密碼為空字串視為不變更。
export async function updateUser(
  id: string,
  patch: { name?: string; password?: string },
): Promise<void> {
  const list = readAll();
  const idx = list.findIndex((u) => u.id === id);
  if (idx === -1) return;
  const next: StoredUser = { ...list[idx] };
  if (patch.name !== undefined) next.name = patch.name;
  if (patch.password) next.password = patch.password; // demo：明文暫存，正式須改後端雜湊
  list[idx] = next;
  writeAll(list);
}
