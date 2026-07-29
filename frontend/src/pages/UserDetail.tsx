import { useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { BackButton } from '../components/BackButton';
import { getUserById, updateUser, deleteUser } from '../api/users';
import { useCurrentUser } from '../hooks/useCurrentUser';
import { ROLE_LABEL, type ManagedUser } from '../types';

const ROLE_OPTIONS = ['staff', 'admin'] as const; // 顯示文字一律走 ROLE_LABEL，不在此寫死

const PASSWORD_MIN_LENGTH = 6; // 對齊後端 PATCH /users/{id}/password 的 min_length=6

const inputClass =
  'w-full rounded-md border border-[var(--border)] bg-[var(--bg-surface)] px-3 py-2 text-sm text-[var(--text-primary)] focus:outline-none focus:ring-2 focus:ring-[var(--brand-soft)]';

// 唯讀資訊列（工號、角色）。
function InfoRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between border-b border-[var(--border)] py-3 text-sm last:border-b-0">
      <span className="text-[var(--text-secondary)]">{label}</span>
      <span className="text-[var(--text-primary)]">{value}</span>
    </div>
  );
}

// 使用者詳情：修改名稱、角色與密碼。密碼留空＝不變更。
export function UserDetail() {
  const { id } = useParams();
  const navigate = useNavigate();
  const me = useCurrentUser(); // 用來判斷這一筆是不是自己（自己的角色不可改）
  const [user, setUser] = useState<ManagedUser | null>(null);
  const [loading, setLoading] = useState(true);
  const [name, setName] = useState('');
  const [role, setRole] = useState<ManagedUser['role']>('staff');
  const [saving, setSaving] = useState(false);
  const [password, setPassword] = useState('');
  const [passwordConfirm, setPasswordConfirm] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [confirmingDelete, setConfirmingDelete] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  useEffect(() => {
    if (!id) return;
    getUserById(id).then((found) => {
      setUser(found);
      if (found) {
        setName(found.name);
        setRole(found.role);
      }
      setLoading(false);
    });
  }, [id]);

  if (loading) {
    return (
      <div className="flex flex-col gap-3">
        <BackButton />
        <p className="text-sm text-[var(--text-secondary)]">載入中…</p>
      </div>
    );
  }

  if (!user) {
    return (
      <div className="flex flex-col gap-3">
        <BackButton />
        <p className="text-sm text-[var(--text-secondary)]">找不到此使用者</p>
      </div>
    );
  }

  const currentUser = user; // early return 後的 narrowed 常數，供下方 async 函式引用

  // 是不是在編輯自己？後端擋「改自己的角色」（400），前端先把下拉停用，
  // 讓人根本點不下去，而不是按了儲存才吃錯誤。
  // 認不出自己時（employeeCode 為 null，如 OTP mock 登入）不擋，交給後端把關。
  const isSelf = me.employeeCode !== null && me.employeeCode === currentUser.employee_code;

  async function handleSave() {
    setError(null);
    const trimmedName = name.trim();
    if (!trimmedName) {
      setError('名稱不可空白');
      return;
    }
    // 密碼選填：任一欄有填才驗證長度與一致性。
    if (password || passwordConfirm) {
      if (password.length < PASSWORD_MIN_LENGTH) {
        setError(`密碼至少 ${PASSWORD_MIN_LENGTH} 碼`);
        return;
      }
      if (password !== passwordConfirm) {
        setError('兩次輸入的密碼不一致');
        return;
      }
    }
    setSaving(true);
    try {
      await updateUser(currentUser.id, {
        name: trimmedName,
        // 角色沒動就不送，避免多打一次請求（也避免編輯自己時白撞後端的 400）
        role: role !== currentUser.role ? role : undefined,
        password: password || undefined,
      });
      navigate('/users');
    } catch (err) {
      // updateUser 內部已把後端 detail（如「不能改自己的角色」）當 Error message 拋出
      setError(err instanceof Error ? err.message : '儲存失敗');
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete() {
    setDeleteError(null);
    setDeleting(true);
    try {
      await deleteUser(currentUser.id);
      navigate('/users'); // 停用成功，回列表（該帳號已從名單消失）
    } catch (err) {
      // deleteUser 已把後端 detail（如「不能停用自己的帳號」）當 Error message 拋出
      setDeleteError(err instanceof Error ? err.message : '停用失敗');
    } finally {
      setDeleting(false);
    }
  }

  return (
    <div className="flex flex-col gap-4">
      <BackButton />
      <h1 className="text-xl font-semibold text-[var(--text-primary)]">編輯使用者</h1>

      <div className="mx-auto flex w-full max-w-xl flex-col gap-6">
        {/* 唯讀資訊：工號是登入帳號，開帳號後不可更改 */}
        <div className="rounded-2xl border border-[var(--border)] bg-[var(--bg-surface)] p-5 shadow-sm">
          <InfoRow label="工號" value={currentUser.employee_code} />
        </div>

        {/* 可編輯：名稱、角色與密碼 */}
        <div className="flex flex-col gap-4 rounded-2xl border border-[var(--border)] bg-[var(--bg-surface)] p-5 shadow-sm">
          <label className="flex flex-col gap-1 text-sm">
            <span className="text-[var(--text-secondary)]">名稱</span>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              className={inputClass}
            />
          </label>

          <label className="flex flex-col gap-1 text-sm">
            <span className="text-[var(--text-secondary)]">角色</span>
            <select
              value={role}
              onChange={(e) => setRole(e.target.value as ManagedUser['role'])}
              disabled={isSelf}
              className={`${inputClass} disabled:cursor-not-allowed disabled:opacity-60`}
            >
              {ROLE_OPTIONS.map((r) => (
                <option key={r} value={r}>
                  {ROLE_LABEL[r]}
                </option>
              ))}
            </select>
            <span className="text-xs text-[var(--text-secondary)]">
              {isSelf
                ? '不能修改自己的角色，以免系統失去管理者。'
                : '變更角色後，該使用者需重新登入才會生效。'}
            </span>
          </label>

          <label className="flex flex-col gap-1 text-sm">
            <span className="text-[var(--text-secondary)]">新密碼</span>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="new-password"
              placeholder="留空表示不變更"
              className={inputClass}
            />
          </label>

          <label className="flex flex-col gap-1 text-sm">
            <span className="text-[var(--text-secondary)]">確認新密碼</span>
            <input
              type="password"
              value={passwordConfirm}
              onChange={(e) => setPasswordConfirm(e.target.value)}
              autoComplete="new-password"
              placeholder="再次輸入新密碼"
              className={inputClass}
            />
          </label>

          {error && <p className="text-xs text-[var(--danger)]">{error}</p>}
        </div>

        <div className="flex justify-end gap-2">
          <button
            type="button"
            onClick={() => navigate('/users')}
            className="rounded-md border border-[var(--text-secondary)] bg-transparent px-4 py-2 text-sm text-[var(--text-secondary)] transition-colors duration-150 hover:bg-[var(--brand-soft)]"
          >
            取消
          </button>
          <button
            type="button"
            onClick={handleSave}
            disabled={saving}
            className="rounded-md bg-[var(--brand)] px-4 py-2 text-sm font-medium text-white transition-colors duration-150 hover:opacity-90 disabled:opacity-50"
          >
            {saving ? '儲存中…' : '儲存'}
          </button>
        </div>

        {/* 停用帳號（後端軟刪除＝is_active=false，資料保留可回溯） */}
        <div className="flex flex-col gap-2">
          {!confirmingDelete ? (
            <>
              <button
                type="button"
                onClick={() => setConfirmingDelete(true)}
                className="self-start rounded-md border border-[var(--danger)] px-4 py-2 text-sm font-medium text-[var(--danger)] transition-colors duration-150 hover:bg-[var(--danger-bg)]"
              >
                停用帳號
              </button>
              <p className="text-xs text-[var(--text-secondary)]">
                停用後此帳號無法登入、並從使用者名單消失；資料保留可回溯。
              </p>
            </>
          ) : (
            <div className="flex flex-col gap-3 rounded-md border border-[var(--danger)] bg-[var(--danger-bg)] p-4">
              <p className="text-sm text-[var(--text-primary)]">
                確定要停用{' '}
                <span className="font-semibold">
                  {currentUser.name}（{currentUser.employee_code}）
                </span>{' '}
                嗎？帳號將被停用、資料保留可回溯。
              </p>
              {deleteError && <p className="text-xs text-[var(--danger)]">{deleteError}</p>}
              <div className="flex gap-2">
                <button
                  type="button"
                  onClick={handleDelete}
                  disabled={deleting}
                  className="rounded-md bg-[var(--danger)] px-4 py-2 text-sm font-medium text-white transition-colors duration-150 hover:opacity-90 disabled:opacity-50"
                >
                  {deleting ? '停用中…' : '確定停用'}
                </button>
                <button
                  type="button"
                  onClick={() => {
                    setConfirmingDelete(false);
                    setDeleteError(null);
                  }}
                  className="rounded-md border border-[var(--text-secondary)] bg-transparent px-4 py-2 text-sm text-[var(--text-secondary)] transition-colors duration-150 hover:bg-[var(--brand-soft)]"
                >
                  取消
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export default UserDetail;
